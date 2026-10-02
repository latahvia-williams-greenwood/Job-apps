"""Reading a list of jobs, e.g. a CSV exported from a Notion tracker."""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path

URL_RE = re.compile(r"https?://\S+")

# Rows whose status contains one of these are skipped by default.
DONE_STATUSES = ("applied", "submitted", "interview", "offer", "rejected", "declined", "withdrawn", "closed", "accepted")


@dataclass
class Job:
    url: str
    company: str = ""
    role: str = ""
    status: str = ""

    @property
    def label(self) -> str:
        return " – ".join(x for x in (self.company, self.role) if x) or self.url


def _find(headers: list[str], *words: str) -> str | None:
    for h in headers:
        if any(w in h.lower() for w in words):
            return h
    return None


def read_jobs(path: Path) -> list[Job]:
    """Read jobs from a .csv (any columns; the link column is found automatically) or a .txt of URLs."""
    if path.suffix.lower() != ".csv":
        return [Job(url=m.group(0)) for m in URL_RE.finditer(path.read_text(encoding="utf-8"))]

    with path.open(newline="", encoding="utf-8-sig") as fh:  # Notion exports start with a BOM
        rows = list(csv.DictReader(fh))
    if not rows:
        return []
    headers = list(rows[0].keys())
    url_col = _find(headers, "link", "url", "posting", "apply", "application")
    company_col = _find(headers, "company", "employer", "organization", "organisation")
    role_col = _find(headers, "role", "position", "title", "job")
    status_col = _find(headers, "status", "stage")
    if role_col in (url_col, company_col):
        role_col = None

    jobs = []
    for row in rows:
        cells = [url_col] if url_col else []
        cells += [h for h in headers if h != url_col]  # fall back to any cell holding a link
        url = next((m.group(0) for h in cells if (m := URL_RE.search(row.get(h) or ""))), None)
        if not url:
            continue
        jobs.append(Job(
            url=url.rstrip(").,;"),
            company=(row.get(company_col) or "").strip() if company_col else "",
            role=(row.get(role_col) or "").strip() if role_col else "",
            status=(row.get(status_col) or "").strip() if status_col else "",
        ))
    return jobs


def _is_done(status: str) -> bool:
    s = status.lower()
    if re.search(r"\bnot\b|to apply|haven.?t|want|saved|interested|todo|to do", s):
        return False
    return any(word in s for word in DONE_STATUSES)


def already_applied(log: Path) -> set[str]:
    if not log.exists():
        return set()
    with log.open(newline="", encoding="utf-8") as fh:
        return {row["url"] for row in csv.DictReader(fh) if row.get("url")}


def pending(jobs: list[Job], log: Path, include_all: bool = False) -> list[Job]:
    """Drop jobs already logged in applications.csv or marked done in the tracker."""
    if include_all:
        return jobs
    done = already_applied(log)
    seen: set[str] = set()
    out = []
    for j in jobs:
        if j.url in done or j.url in seen or _is_done(j.status):
            continue
        seen.add(j.url)
        out.append(j)
    return out
