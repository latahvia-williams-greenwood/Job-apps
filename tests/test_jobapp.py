import os
from pathlib import Path

import pytest
import yaml

from jobapp import llm
from jobapp.matcher import FormField, pick_option, rule_answer
from jobapp.profile import load_profile

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = Path(__file__).with_name("fixtures") / "application.html"


@pytest.fixture
def profile(tmp_path):
    data = yaml.safe_load((ROOT / "profile.example.yaml").read_text())
    (tmp_path / "resume.txt").write_text("Jane Doe\nCustomer Success Manager, Acme Corp, 2019-2024\nSQL, Tableau")
    data["resume"] = "resume.txt"
    path = tmp_path / "profile.yaml"
    path.write_text(yaml.safe_dump(data))
    return load_profile(path)


def field(label, kind="text", options=None, name=""):
    return FormField(uid="x", kind=kind, label=label, name=name, options=options or [])


@pytest.mark.parametrize("label,expected", [
    ("First Name *", "Jane"),
    ("Last name", "Doe"),
    ("Full Name", "Jane Doe"),
    ("Email address", "jane.doe@example.com"),
    ("LinkedIn Profile", "https://www.linkedin.com/in/janedoe"),
    ("Will you now or in the future require sponsorship?", "No"),
    ("Are you legally authorized to work in the United States?", "Yes"),
    ("Zip / Postal code", "30301"),
    ("Company name", None),
])
def test_rule_answers(profile, label, expected):
    assert rule_answer(field(label), profile) == expected


def test_pick_option():
    assert pick_option("No", ["Select...", "Yes", "No"]) == "No"
    assert pick_option("Yes", ["Yes, I am authorized", "No, I am not"]) == "Yes, I am authorized"
    assert pick_option("Decline to self-identify", ["Male", "Female", "I don't wish to answer"]) == "I don't wish to answer"
    assert pick_option("Maybe", ["Yes", "No"]) is None


def test_fill_fixture_form(profile, tmp_path, monkeypatch):
    """End to end in a real (headless) browser, with Claude stubbed out."""
    from playwright.sync_api import sync_playwright

    from jobapp.filler import Applicant

    asked = {}

    def fake_answers(fields, prof, jd):
        asked["questions"] = [f.question for f in fields]
        return {f.uid: ("Because I love reporting." if f.kind == "textarea" else
                        "yes" if f.kind == "checkbox" else "4") for f in fields}

    monkeypatch.setattr(llm, "answer_questions", fake_answers)
    monkeypatch.setattr(llm, "extract_job_info", lambda jd: {"company": "Example Co", "title": "Senior Analyst"})
    monkeypatch.setattr(llm, "write_cover_letter", lambda p, jd, extra="": "Dear Hiring Team,\n\nHello.\n\nJane Doe")

    app = Applicant(profile, out_dir=tmp_path / "out", headless=True)
    with sync_playwright() as pw:
        # CHROMIUM_PATH lets the tests run against a pre-installed browser.
        browser = pw.chromium.launch(executable_path=os.environ.get("CHROMIUM_PATH") or None)
        page = browser.new_page()
        page.goto(FIXTURE.as_uri())
        app.job_description = app._read_job_description(page)
        app.fill_page(page)

        v = lambda sel: page.locator(sel).input_value()
        assert v("#first_name") == "Jane"
        assert v("#last_name") == "Doe"
        assert v("#email") == "jane.doe@example.com"
        assert v("input[name=phone]") == "555-123-4567"
        assert v("input[name='urls[LinkedIn]']") == "https://www.linkedin.com/in/janedoe"
        assert page.locator("input[name=sponsor][value='0']").is_checked()
        assert page.locator("#auth option:checked").inner_text() == "Yes"
        assert page.locator("#gender option:checked").inner_text() == "Decline To Self Identify"
        assert v("#why") == "Because I love reporting."
        assert v("#sql") == "4"
        assert page.locator("input[name=privacy]").is_checked()
        assert page.locator("#resume").evaluate("el => el.files[0].name") == "resume.txt"
        assert page.locator("#cl").evaluate("el => el.files[0].name").endswith(".pdf")
        browser.close()

    # Only the job-specific questions went to Claude; standard ones were instant.
    assert sorted(asked["questions"]) == sorted([
        "Why are you interested in this role?",
        "How many years of SQL experience do you have?",
        "I acknowledge the privacy policy",
    ])
    assert list((tmp_path / "out").glob("*.pdf"))


def test_read_notion_csv(tmp_path):
    from jobapp.joblist import pending, read_jobs

    csv_path = tmp_path / "Job Tracker.csv"
    csv_path.write_text(
        "﻿Company,Position,Status,Job Link,Notes\n"
        "Acme,Data Analyst,Not applied,https://boards.greenhouse.io/acme/jobs/1,\n"
        "Globex,Intern,Applied,https://jobs.lever.co/globex/2,\n"
        "Initech,PM Intern,,,apply here: https://initech.wd1.myworkdayjobs.com/x/3).\n"
        "Umbrella,Analyst,Interested,,\n"
        "Acme,Data Analyst,,https://boards.greenhouse.io/acme/jobs/1,dup\n",
        encoding="utf-8",
    )
    jobs = read_jobs(csv_path)
    assert [j.url for j in jobs] == [
        "https://boards.greenhouse.io/acme/jobs/1",
        "https://jobs.lever.co/globex/2",
        "https://initech.wd1.myworkdayjobs.com/x/3",
        "https://boards.greenhouse.io/acme/jobs/1",
    ]
    assert jobs[0].label == "Acme – Data Analyst"

    log = tmp_path / "applications.csv"
    log.write_text("date,company,title,url,cover_letter\n2026-10-01,,,https://initech.wd1.myworkdayjobs.com/x/3,\n")
    assert [j.company for j in pending(jobs, log)] == ["Acme"]
    assert len(pending(jobs, log, include_all=True)) == 4
