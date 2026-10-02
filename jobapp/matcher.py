"""Instant, rule-based answers for the standard application questions.

Anything a rule can answer never goes to Claude, which keeps applications fast
and the common answers (name, email, sponsorship...) exactly what you wrote.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .profile import Profile


@dataclass
class FormField:
    """One question on the page, as scraped by the browser."""

    uid: str                      # our data-jobapp-id, used to find it again
    kind: str                     # text, email, tel, url, number, date, textarea, select, radio, checkbox, file, combobox
    label: str
    name: str = ""
    placeholder: str = ""
    options: list[str] = field(default_factory=list)
    required: bool = False

    @property
    def question(self) -> str:
        return self.label or self.placeholder or self.name


# (pattern, profile key). First match wins, so specific patterns go first.
# Patterns are searched in "label | name | placeholder", lowercased.
RULES: list[tuple[str, str]] = [
    (r"linkedin", "personal.linkedin"),
    (r"github", "personal.github"),
    (r"portfolio", "personal.portfolio"),
    (r"preferred (first )?name|nickname", "personal.preferred_name"),
    (r"first[\s_-]?name|given name|fname", "personal.first_name"),
    (r"last[\s_-]?name|surname|family name|lname", "personal.last_name"),
    (r"e-?mail", "personal.email"),
    (r"phone|mobile|telephone", "personal.phone"),
    (r"(street )?address( line)? ?1|street address|^address", "personal.address"),
    (r"\bcity\b|town", "personal.city"),
    (r"\bstate\b|province|region", "personal.state"),
    (r"zip|postal", "personal.zip"),
    (r"country", "personal.country"),
    (r"website|personal (site|url)|blog", "personal.website"),
    (r"sponsor", "preferences.require_sponsorship"),
    (r"authori[sz]ed to work|legally (eligible|authorized|able)|right to work|work authori[sz]ation|eligible to work", "preferences.authorized_to_work"),
    (r"relocat", "preferences.willing_to_relocate"),
    (r"salary|compensation|pay expectation", "preferences.desired_salary"),
    (r"start date|available to start|earliest .*start|when can you start", "preferences.start_date"),
    (r"notice period", "preferences.notice_period"),
    (r"18 years|at least 18|over (the age of )?18", "preferences.over_18"),
    (r"background check", "preferences.background_check"),
    (r"drug (test|screen)", "preferences.drug_test"),
    (r"how did you (hear|find|learn)|referral source|source of application", "preferences.how_did_you_hear"),
    (r"(previously|ever) (been )?(employed|worked)", "preferences.previously_employed_here"),
    (r"remote|on-?site|hybrid|work arrangement", "preferences.remote_preference"),
    (r"hispanic|latin[oax]", "eeo.hispanic_latino"),
    (r"gender|\bsex\b", "eeo.gender"),
    (r"\brace\b|ethnic", "eeo.race"),
    (r"veteran", "eeo.veteran_status"),
    (r"disabilit", "eeo.disability_status"),
    (r"current (job )?title|job title", "work.current_title"),
    (r"current (company|employer)|most recent (company|employer)", "work.current_company"),
    (r"years of (relevant |professional )?experience", "work.years_experience"),
    (r"\bgpa\b|grade point", "work.gpa"),
    (r"(highest )?(level of )?education|degree level", "work.highest_education"),
    (r"school|university|college", "work.school"),
    (r"\bdegree\b|major|field of study", "work.degree"),
    (r"graduat", "work.graduation_year"),
    # Plain "name" / "full name" last so it doesn't swallow "first name", "company name"...
    (r"^(full |legal |your )?name\b", "__full_name__"),
]

_COMPILED = [(re.compile(p), key) for p, key in RULES]


def normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def rule_answer(f: FormField, profile: Profile) -> str | None:
    haystack = " | ".join(x for x in (f.label, f.name, f.placeholder) if x).lower()
    if not haystack:
        return None

    for phrase, answer in (profile.data.get("custom_answers") or {}).items():
        if answer and normalize(phrase) in normalize(haystack):
            return str(answer)

    for pattern, key in _COMPILED:
        if pattern.search(haystack):
            value = profile.full_name if key == "__full_name__" else profile.get(key)
            return value or None
    return None


def pick_option(answer: str, options: list[str]) -> str | None:
    """Choose the dropdown/radio option that best matches an answer."""
    if not options or not answer:
        return None
    a = normalize(answer)
    norm = [(o, normalize(o)) for o in options if normalize(o) and not _is_placeholder(o)]

    for o, n in norm:
        if n == a:
            return o
    # Yes/No questions often have options like "Yes, I am authorized..."
    if a in ("yes", "no"):
        for o, n in norm:
            if n.split(" ")[0] == a:
                return o
    for o, n in norm:
        if n.startswith(a) or a.startswith(n):
            return o
    for o, n in norm:
        if a in n or n in a:
            return o
    # "Decline to self-identify" phrased many ways
    declines = ("decline", "prefer not", "rather not", "not want", "not wish", "t wish", "choose not", "not to answer", "not to disclose")
    if any(w in a for w in declines):
        for o, n in norm:
            if any(w in n for w in declines):
                return o
    return None


def _is_placeholder(option: str) -> bool:
    n = normalize(option)
    return n in ("", "select", "select one", "please select", "choose", "choose one", "none selected") or n.startswith("select ")


class AnswerCache:
    """Remembers Claude's answers so a repeated question is instant next time."""

    def __init__(self, path: Path):
        self.path = path
        self.data: dict[str, str] = {}
        if path.exists():
            self.data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    def get(self, question: str) -> str | None:
        return self.data.get(normalize(question))

    def put(self, question: str, answer: str) -> None:
        if question and answer:
            self.data[normalize(question)] = answer

    def save(self) -> None:
        self.path.write_text(yaml.safe_dump(self.data, sort_keys=True, allow_unicode=True), encoding="utf-8")
