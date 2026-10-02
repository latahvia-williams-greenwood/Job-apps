"""Command line:

    python -m jobapp apply <job-url> [--cover-letter auto|always|never]
    python -m jobapp cover-letter <job-url | job.txt | -> [--notes "..."]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="jobapp", description="Fill job applications fast and write cover letters.")
    parser.add_argument("--profile", default="profile.yaml", help="path to your profile (default: profile.yaml)")
    parser.add_argument("--out", default="output", help="folder for cover letters (default: output/)")
    sub = parser.add_subparsers(dest="command", required=True)

    apply = sub.add_parser("apply", help="open an application in the browser and fill it out")
    apply.add_argument("url")
    apply.add_argument("--cover-letter", choices=["auto", "always", "never"], default="auto",
                       help="auto = only when the form asks for one (default)")
    apply.add_argument("--no-ai", action="store_true", help="only use your profile answers; never call Claude")

    letter = sub.add_parser("cover-letter", help="write a cover letter from a job description")
    letter.add_argument("job", help="job posting URL, a text file with the description, or - to paste it")
    letter.add_argument("--notes", default="", help='extra guidance, e.g. "mention my Spanish fluency"')

    args = parser.parse_args(argv)

    from .profile import load_profile

    try:
        profile = load_profile(args.profile)
    except FileNotFoundError as e:
        print(e)
        return 1
    out_dir = Path(args.out)
    if not out_dir.is_absolute():
        out_dir = profile.base_dir / out_dir

    if args.command == "apply":
        from .filler import Applicant

        Applicant(profile, cover_letter="never" if args.no_ai else args.cover_letter,
                  out_dir=out_dir, use_ai=not args.no_ai).run(args.url)
        return 0

    from . import llm
    from .cover_letter import save_cover_letter

    description = read_job(args.job)
    print("Writing your cover letter…")
    info = llm.extract_job_info(description)
    text = llm.write_cover_letter(profile, description, args.notes)
    paths = save_cover_letter(text, profile, out_dir, info.get("company", ""), info.get("title", ""))
    print("\n" + text + "\n")
    for kind, path in paths.items():
        print(f"saved {kind}: {path}")
    return 0


def read_job(source: str) -> str:
    if source == "-":
        print("Paste the job description, then press Ctrl-D (Ctrl-Z then Enter on Windows):")
        return sys.stdin.read()
    if source.startswith(("http://", "https://")):
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page()
            page.goto(source, wait_until="domcontentloaded")
            try:
                page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass
            text = "\n".join(f.evaluate("() => document.body ? document.body.innerText : ''") for f in page.frames)
            browser.close()
            return text[:40000]
    from .profile import read_document

    return read_document(Path(source))


if __name__ == "__main__":
    raise SystemExit(main())
