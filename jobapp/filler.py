"""Browser automation: open an application, fill every question, leave Submit to you."""

from __future__ import annotations

import csv
import datetime as dt
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from playwright.sync_api import Frame, Page, sync_playwright

from . import llm
from .cover_letter import save_cover_letter
from .matcher import AnswerCache, FormField, pick_option, rule_answer
from .profile import Profile

SCAN_JS = (Path(__file__).with_name("scan.js")).read_text(encoding="utf-8")

GREEN = "3px solid #22c55e"
AMBER = "3px solid #f59e0b"


class Applicant:
    def __init__(self, profile: Profile, cover_letter: str = "auto", out_dir: Path = Path("output"),
                 headless: bool = False, use_ai: bool = True):
        self.profile = profile
        self.cover_letter_mode = cover_letter      # "auto", "always" or "never"
        self.out_dir = out_dir
        self.headless = headless
        self.use_ai = use_ai
        self.cache = AnswerCache(profile.base_dir / "answers_cache.yaml")
        self.job_description = ""
        self.job_info: dict[str, str] = {}
        self.page_title = ""
        self.cover_letter_text: str | None = None
        self.cover_letter_paths: dict[str, Path] = {}

    # ---------- entry point ----------

    def run(self, url: str) -> None:
        start = time.monotonic()
        with sync_playwright() as pw:
            ctx = pw.chromium.launch_persistent_context(
                str(self.profile.base_dir / ".browser-profile"),
                headless=self.headless,
                viewport={"width": 1280, "height": 900},
            )
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto(url, wait_until="domcontentloaded")
            self._settle(page)

            self.job_description = self._read_job_description(page)
            self.page_title = page.title()
            self._open_application_form(page)

            while True:
                self.fill_page(page)
                print(f"\n⏱  {time.monotonic() - start:.0f}s elapsed.")
                print("Review the highlighted fields in the browser and click Submit yourself.")
                print("  [Enter]  fill the current page again (e.g. after clicking Next on a multi-step form)")
                print("  q        finish (logs the application and closes the browser)")
                if input("> ").strip().lower().startswith("q"):
                    break
                self._settle(page)

            self._log(url)
            self.cache.save()
            ctx.close()

    # ---------- page helpers ----------

    def _settle(self, page: Page) -> None:
        try:
            page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass

    def _read_job_description(self, page: Page) -> str:
        texts = []
        for frame in page.frames:
            try:
                texts.append(frame.evaluate("() => document.body ? document.body.innerText : ''"))
            except Exception:
                continue
        text = re.sub(r"\n{3,}", "\n\n", "\n".join(texts)).strip()
        return text[:40000]

    def _open_application_form(self, page: Page) -> None:
        """If the posting page has no form yet, click its Apply button."""
        if self._count_inputs(page) >= 3:
            return
        for pattern in (r"^\s*apply( now| for this (job|position|role))?\s*$", r"apply"):
            button = page.get_by_role("button", name=re.compile(pattern, re.I)).or_(
                page.get_by_role("link", name=re.compile(pattern, re.I))
            ).first
            try:
                if button.is_visible(timeout=1000):
                    button.click()
                    self._settle(page)
                    page.wait_for_timeout(1000)
                    return
            except Exception:
                continue

    def _count_inputs(self, page: Page) -> int:
        total = 0
        for frame in page.frames:
            try:
                total += frame.locator("input:visible, textarea:visible, select:visible").count()
            except Exception:
                pass
        return total

    def _scan(self, page: Page) -> list[tuple[Frame, FormField, bool]]:
        found = []
        for i, frame in enumerate(page.frames):
            try:
                raw = frame.evaluate(SCAN_JS, f"f{i}")
            except Exception:
                continue
            for item in raw:
                filled = item.pop("filled")
                found.append((frame, FormField(**item), filled))
        return found

    # ---------- filling ----------

    def fill_page(self, page: Page) -> None:
        # 1. Upload the résumé first: many portals parse it and pre-fill fields.
        fields = self._scan(page)
        for frame, f, filled in fields:
            if f.kind == "file" and not filled and not _is_cover_letter(f) and self.profile.resume_path:
                if self._upload(frame, f, self.profile.resume_path):
                    print(f"  ✓ uploaded résumé → {f.question or 'file field'}")
                    page.wait_for_timeout(2500)
                    self._settle(page)
        fields = [(fr, f) for fr, f, filled in self._scan(page) if not filled]

        # 2. Decide whether a cover letter is needed.
        wants_letter = self.cover_letter_mode == "always" or (
            self.cover_letter_mode == "auto" and any(_is_cover_letter(f) for _, f in fields)
        )

        # 3. Instant answers from profile rules and saved answers.
        answers: dict[str, str] = {}
        todo: list[FormField] = []
        for _, f in fields:
            if f.kind == "file" or _is_cover_letter(f):
                continue
            a = rule_answer(f, self.profile)
            if a is None and f.kind != "textarea":
                a = self.cache.get(f.question)
            if a is not None:
                answers[f.uid] = a
            elif f.question:
                todo.append(f)

        # 4. Claude answers the rest in one call, while the cover letter is written in parallel.
        if self.use_ai and (todo or (wants_letter and self.cover_letter_text is None)):
            print(f"  … asking Claude about {len(todo)} question(s)"
                  + (" and writing your cover letter" if wants_letter and self.cover_letter_text is None else ""))
            with ThreadPoolExecutor(max_workers=2) as pool:
                letter_job = pool.submit(self._make_cover_letter) if wants_letter and self.cover_letter_text is None else None
                ai = llm.answer_questions(todo, self.profile, self.job_description)
                if letter_job:
                    letter_job.result()
            answers.update(ai)
            for f in todo:
                if f.uid in ai and f.kind != "textarea":
                    self.cache.put(f.question, ai[f.uid])

        # 5. Fill everything.
        filled, skipped = 0, []
        for frame, f in fields:
            ok = False
            try:
                if f.kind == "file" and _is_cover_letter(f) and self.cover_letter_paths:
                    ok = self._upload(frame, f, self.cover_letter_paths["pdf"])
                elif _is_cover_letter(f) and f.kind == "textarea" and self.cover_letter_text:
                    ok = self._fill_text(frame, f, self.cover_letter_text)
                elif f.uid in answers:
                    ok = self._fill(frame, f, answers[f.uid])
            except Exception as e:  # keep going; one odd widget shouldn't stop the rest
                print(f"  ! couldn't fill '{f.question[:60]}': {e.__class__.__name__}")
            self._mark(frame, f, ok)
            if ok:
                filled += 1
            elif f.kind != "file" or f.required:
                skipped.append(f)

        print(f"\n  ✓ filled {filled} field(s)")
        if skipped:
            print("  ⚠ needs your attention (outlined in amber):")
            for f in skipped:
                print(f"     - {f.question[:90] or f.name}{'  (required)' if f.required else ''}")

    def _make_cover_letter(self) -> None:
        self.job_info = llm.extract_job_info(self.job_description)
        self.cover_letter_text = llm.write_cover_letter(self.profile, self.job_description)
        self.cover_letter_paths = save_cover_letter(
            self.cover_letter_text, self.profile, self.out_dir,
            self.job_info.get("company", ""), self.job_info.get("title", ""),
        )
        print(f"  ✓ cover letter saved: {self.cover_letter_paths['pdf']}")

    def _loc(self, frame: Frame, uid: str):
        return frame.locator(f'[data-jobapp-id="{uid}"]').first

    def _upload(self, frame: Frame, f: FormField, path: Path) -> bool:
        self._loc(frame, f.uid).set_input_files(str(path))
        return True

    def _fill_text(self, frame: Frame, f: FormField, value: str) -> bool:
        loc = self._loc(frame, f.uid)
        loc.fill(value)
        loc.dispatch_event("change")
        loc.dispatch_event("blur")
        return True

    def _fill(self, frame: Frame, f: FormField, value: str) -> bool:
        if not value.strip():
            return False
        loc = self._loc(frame, f.uid)
        if f.kind == "select":
            option = pick_option(value, f.options)
            if not option:
                return False
            loc.select_option(label=option)
            return True
        if f.kind == "radio":
            option = pick_option(value, f.options)
            if option is None:
                return False
            i = f.options.index(option)
            frame.locator(f'[data-jobapp-id="{f.uid}-opt{i}"]').first.check(force=True)
            return True
        if f.kind == "checkbox":
            if not f.options:  # single yes/no box
                if value.strip().lower() in ("yes", "true", "y", "1", "checked"):
                    loc.check(force=True)
                    return True
                return value.strip().lower() in ("no", "false")
            hit = False
            for part in value.split("|"):
                option = pick_option(part.strip(), f.options)
                if option is not None:
                    frame.locator(f'[data-jobapp-id="{f.uid}-opt{f.options.index(option)}"]').first.check(force=True)
                    hit = True
            return hit
        if f.kind == "combobox":
            # Searchable dropdowns (react-select etc.): type, then pick the highlighted option.
            loc.click()
            loc.fill(value)
            frame.page.wait_for_timeout(600)
            loc.press("Enter")
            return True
        return self._fill_text(frame, f, value)

    def _mark(self, frame: Frame, f: FormField, ok: bool) -> None:
        sel = f'[data-jobapp-id^="{f.uid}"]'
        try:
            frame.evaluate(
                "([sel, style]) => document.querySelectorAll(sel).forEach(el => {"
                " const t = (el.type === 'radio' || el.type === 'checkbox') ? (el.closest('label') || el) : el;"
                " t.style.outline = style; })",
                [sel, GREEN if ok else AMBER],
            )
        except Exception:
            pass

    def _log(self, url: str) -> None:
        log = self.profile.base_dir / "applications.csv"
        new = not log.exists()
        with log.open("a", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            if new:
                w.writerow(["date", "company", "title", "url", "cover_letter"])
            w.writerow([
                dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
                self.job_info.get("company", ""), self.job_info.get("title", "") or self.page_title, url,
                str(self.cover_letter_paths.get("pdf", "")),
            ])
        print(f"Logged to {log}")


def _is_cover_letter(f: FormField) -> bool:
    return bool(re.search(r"cover[\s_-]?letter|motivation letter|letter of interest", f.question + " " + f.name, re.I))
