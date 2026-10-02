"""Claude calls: answering application questions and writing cover letters."""

from __future__ import annotations

import json
import os

import anthropic

from .matcher import FormField
from .profile import Profile

MODEL = os.environ.get("JOBAPP_MODEL", "claude-opus-5-5")

# If a safety classifier declines a request, let the API retry it on Anthropic's
# recommended fallback model instead of failing the application.
_FALLBACK = dict(
    extra_headers={"anthropic-beta": "server-side-fallback-2026-07-01"},
    extra_body={"fallbacks": "default"},
)

_client: anthropic.Anthropic | None = None


def client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


SYSTEM = """You help a job seeker fill out job applications quickly and honestly.

Rules:
- Only state facts supported by the applicant's profile or résumé. Never invent \
employers, degrees, certifications, skills, numbers or dates.
- If a question can't be answered truthfully from what you have, answer "" (empty) \
so the applicant can fill it in themselves.
- For questions with options, answer with the exact text of one option. For \
multi-select checkbox groups, separate chosen options with " | ".
- For yes/no checkboxes (no options), answer "yes" to check or "no" to leave unchecked. \
Only check agreement/consent boxes if they are routine (e.g. privacy policy acknowledgement).
- Short-answer fields: answer in a few words. Long-answer (textarea) questions: 2-5 \
sentences in first person, specific to this job, in the applicant's voice, no clichés.
- Voluntary self-identification (gender, race, veteran, disability): use the profile's \
eeo choices; otherwise choose the "decline to answer" option."""


def _context(profile: Profile, job_description: str) -> str:
    transcript = (
        f"<transcript>\n{profile.transcript_text}\n</transcript>\n\n" if profile.transcript_text else ""
    )
    return (
        f"<applicant_profile>\n{profile.as_prompt_text()}</applicant_profile>\n\n"
        f"<resume>\n{profile.resume_text or '(no résumé provided)'}\n</resume>\n\n"
        + transcript
        + f"<job_posting>\n{job_description or '(not available)'}\n</job_posting>"
    )


def _text(response) -> str:
    if response.stop_reason == "refusal":
        raise RuntimeError("Claude declined this request.")
    return "".join(b.text for b in response.content if b.type == "text").strip()


ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "answers": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"id": {"type": "string"}, "answer": {"type": "string"}},
                "required": ["id", "answer"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["answers"],
    "additionalProperties": False,
}


def answer_questions(fields: list[FormField], profile: Profile, job_description: str) -> dict[str, str]:
    """Answer every remaining question in ONE request. Returns {uid: answer}."""
    if not fields:
        return {}
    questions = [
        {
            "id": f.uid,
            "question": f.question,
            "type": f.kind,
            **({"options": f.options} if f.options else {}),
            "required": f.required,
        }
        for f in fields
    ]
    response = client().messages.create(
        model=MODEL,
        max_tokens=16000,
        system=SYSTEM,
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": ANSWER_SCHEMA}},
        messages=[{
            "role": "user",
            "content": _context(profile, job_description)
            + "\n\nAnswer each of these application questions:\n"
            + json.dumps(questions, indent=1, ensure_ascii=False),
        }],
        **_FALLBACK,
    )
    data = json.loads(_text(response))
    return {a["id"]: a["answer"] for a in data["answers"] if a["answer"].strip()}


COVER_LETTER_SYSTEM = """You write tailored, honest cover letters.

- Use only experience and achievements found in the applicant's résumé and profile; \
never invent facts, metrics or employers.
- Connect the applicant's most relevant experience to the specific requirements in \
the job posting. Name the company and role.
- 250-400 words, 3-4 paragraphs, confident and warm, plain language, no clichés \
("I am writing to express my interest", "team player", "passionate").
- Output only the letter: greeting through sign-off with the applicant's name. \
No date, addresses, subject line, or commentary."""


def write_cover_letter(profile: Profile, job_description: str, extra_instructions: str = "") -> str:
    request = "Write the cover letter for this job."
    if extra_instructions:
        request += f"\n\nAdditional instructions from the applicant: {extra_instructions}"
    with client().messages.stream(
        model=MODEL,
        max_tokens=64000,
        system=COVER_LETTER_SYSTEM,
        output_config={"effort": "medium"},
        messages=[{"role": "user", "content": _context(profile, job_description) + "\n\n" + request}],
        **_FALLBACK,
    ) as stream:
        return _text(stream.get_final_message())


def extract_job_info(job_description: str) -> dict[str, str]:
    """Pull the company and job title out of a posting (used for file names)."""
    response = client().messages.create(
        model=MODEL,
        max_tokens=2000,
        output_config={
            "effort": "low",
            "format": {
                "type": "json_schema",
                "schema": {
                    "type": "object",
                    "properties": {"company": {"type": "string"}, "title": {"type": "string"}},
                    "required": ["company", "title"],
                    "additionalProperties": False,
                },
            },
        },
        messages=[{
            "role": "user",
            "content": "Give the hiring company's name and the job title from this posting "
            "(empty string if unknown).\n\n" + job_description[:20000],
        }],
        **_FALLBACK,
    )
    return json.loads(_text(response))
