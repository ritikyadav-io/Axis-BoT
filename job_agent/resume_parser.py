from __future__ import annotations

import re
from pathlib import Path
from typing import Any


SECTION_ALIASES = {
    "education": ("education", "academic"),
    "skills": ("skill", "technical skill", "technologies"),
    "internships": ("internship", "internships"),
    "projects": ("project", "projects"),
    "certifications": ("certification", "certificate", "certifications"),
    "experience": ("experience", "work history", "employment"),
    "contact": ("contact", "profile"),
}


def parse_resume_file(path: str | Path) -> dict[str, Any]:
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(str(file_path))
    suffix = file_path.suffix.lower()
    if suffix == ".pdf":
        text = _read_pdf(file_path)
    elif suffix in {".docx", ".doc"}:
        text = _read_docx(file_path)
    else:
        text = file_path.read_text(encoding="utf-8", errors="ignore")
    return extract_sections(text, source=str(file_path))


def _read_pdf(path: Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    pages = []
    for page in reader.pages:
        pages.append(page.extract_text() or "")
    return "\n".join(pages)


def _read_docx(path: Path) -> str:
    from docx import Document

    document = Document(str(path))
    return "\n".join(paragraph.text for paragraph in document.paragraphs)


def extract_sections(text: str, source: str = "") -> dict[str, Any]:
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    joined = "\n".join(lines)
    email = re.search(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", joined, flags=re.I)
    phone = re.search(r"(\+91[\s-]?)?[6-9]\d{9}", joined)
    buckets: dict[str, list[str]] = {key: [] for key in SECTION_ALIASES}
    current = "contact"
    buckets.setdefault("contact", [])
    for line in lines:
        lowered = line.lower().strip(":# ")
        matched = None
        for key, aliases in SECTION_ALIASES.items():
            if any(lowered == alias or lowered.startswith(alias) for alias in aliases) and len(line) < 40:
                matched = key
                break
        if matched:
            current = matched
            continue
        buckets.setdefault(current, []).append(line)

    skills = []
    for line in buckets.get("skills") or []:
        skills.extend([part.strip() for part in re.split(r"[,|/•;]", line) if part.strip() and len(part.strip()) < 40])

    return {
        "source": source,
        "raw_text": text,
        "email": email.group(0) if email else "",
        "phone": phone.group(0) if phone else "",
        "education": buckets.get("education") or [],
        "skills": skills,
        "internships": buckets.get("internships") or [],
        "projects": buckets.get("projects") or [],
        "certifications": buckets.get("certifications") or [],
        "experience": buckets.get("experience") or [],
        "notes": "Extracted only from the uploaded file. Empty fields were not invented.",
    }
