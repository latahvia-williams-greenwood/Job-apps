"""Loading the applicant profile and résumé."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class Profile:
    data: dict
    resume_path: Path | None
    resume_text: str
    base_dir: Path = field(default_factory=Path.cwd)

    def get(self, dotted: str, default: str = "") -> str:
        """Look up a value like 'personal.email'."""
        node = self.data
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return "" if node is None else str(node)

    @property
    def full_name(self) -> str:
        return f"{self.get('personal.first_name')} {self.get('personal.last_name')}".strip()

    def as_prompt_text(self) -> str:
        """The profile as YAML, for giving to Claude (résumé path stripped)."""
        data = {k: v for k, v in self.data.items() if k != "resume"}
        return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)


def read_document(path: Path) -> str:
    """Extract plain text from a .pdf, .docx, .txt or .md file."""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        from pypdf import PdfReader

        return "\n".join(page.extract_text() or "" for page in PdfReader(path).pages).strip()
    if suffix == ".docx":
        import docx

        return "\n".join(p.text for p in docx.Document(path).paragraphs).strip()
    return path.read_text(encoding="utf-8").strip()


def load_profile(path: str | Path = "profile.yaml") -> Profile:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found. Copy profile.example.yaml to {path} and fill it in."
        )
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    base_dir = path.resolve().parent

    resume_path = None
    resume_text = ""
    if data.get("resume"):
        resume_path = Path(data["resume"])
        if not resume_path.is_absolute():
            resume_path = base_dir / resume_path
        if resume_path.exists():
            resume_text = read_document(resume_path)
        else:
            print(f"warning: résumé not found at {resume_path}")
            resume_path = None

    return Profile(data=data, resume_path=resume_path, resume_text=resume_text, base_dir=base_dir)
