from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Any

from job_agent.config import load_profile, read_master_resume
from job_agent.database import JobStore
from job_agent.paths import TAILORED_RESUMES_DIR, ensure_runtime_dirs


def slug(value: str | None) -> str:
    text = re.sub(r"[^a-zA-Z0-9]+", "-", (value or "item").strip()).strip("-").lower()
    return text[:60] or "item"


def profile_facts(profile: dict[str, Any]) -> dict[str, Any]:
    education = profile.get("education") or {}
    return {
        "full_name": (profile.get("full_name") or "").strip(),
        "email": (profile.get("email") or "").strip(),
        "phone": (profile.get("phone") or "").strip(),
        "city": (profile.get("city") or "").strip(),
        "linkedin_url": (profile.get("linkedin_url") or "").strip(),
        "github_url": (profile.get("github_url") or "").strip(),
        "degree": education.get("degree"),
        "graduation_year": education.get("graduation_year"),
        "education_status": education.get("status"),
        "experience_level": profile.get("experience_level"),
        "skills": [str(item).strip() for item in profile.get("skills") or [] if str(item).strip()],
        "projects": profile.get("projects") or [],
        "internships": profile.get("internships") or [],
        "certifications": profile.get("certifications") or [],
        "achievements": profile.get("achievements") or [],
        "expected_salary": profile.get("expected_salary") or "",
        "target_roles": profile.get("target_roles") or [],
    }


def _grounded_lines(text: str, allowed: str) -> list[str]:
    allowed_l = allowed.lower()
    kept = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        # Keep headings and contact lines that come from the template.
        if line.startswith("#") or line.startswith("-") is False and ":" in line[:24]:
            kept.append(raw)
            continue
        token = re.sub(r"^[-*]\s*", "", line).lower()
        if token in allowed_l or any(part.lower() in allowed_l for part in re.findall(r"[A-Za-z0-9][A-Za-z0-9+.# ]{2,}", line)):
            kept.append(raw)
        elif line.startswith("-") and token in allowed_l:
            kept.append(raw)
    return kept


def build_tailored_resume(job: dict[str, Any], profile: dict[str, Any] | None = None) -> dict[str, str]:
    profile = profile or load_profile()
    facts = profile_facts(profile)
    master = read_master_resume(profile)
    job_blob = " ".join(
        [
            str(job.get("title") or ""),
            str(job.get("description") or ""),
            " ".join(job.get("required_skills") or []),
        ]
    ).lower()

    name = facts["full_name"] or "Candidate name not set in profile.json"
    skills = facts["skills"]
    highlighted = [skill for skill in skills if skill.lower() in job_blob]
    remaining = [skill for skill in skills if skill not in highlighted]
    ordered_skills = highlighted + remaining

    header_bits = [item for item in (facts["email"], facts["phone"], facts["city"]) if item]
    links = [item for item in (facts["linkedin_url"], facts["github_url"]) if item]

    resume_lines = [
        f"# {name}",
        "",
        " | ".join(header_bits),
        " | ".join(links),
        "",
        "## Objective",
        f"Fresher / entry-level candidate applying for {job.get('title') or 'this role'} at {job.get('company') or 'the company'}. Education: {facts['degree']}, graduation year {facts['graduation_year']}.",
        "",
        "## Education",
        f"- {facts['degree']} ({facts['education_status']}, {facts['graduation_year']})",
        "",
        "## Experience",
        f"- {facts['experience_level']}",
        "",
        "## Skills",
    ]
    for skill in ordered_skills:
        marker = " (mentioned in this job listing)" if skill in highlighted else ""
        resume_lines.append(f"- {skill}{marker}")

    resume_lines += ["", "## Projects"]
    if facts["projects"]:
        for project in facts["projects"]:
            resume_lines.append(f"- {project}")
    else:
        resume_lines.append("- None listed in the approved profile. Not invented.")

    resume_lines += ["", "## Internships"]
    if facts["internships"]:
        for item in facts["internships"]:
            resume_lines.append(f"- {item}")
    else:
        resume_lines.append("- None listed in the approved profile. Not invented.")

    resume_lines += ["", "## Certifications"]
    if facts.get("certifications"):
        for item in facts["certifications"]:
            resume_lines.append(f"- {item}")
    else:
        resume_lines.append("- None listed in the approved profile. Not invented.")

    resume_lines += ["", "## Achievements"]
    if facts["achievements"]:
        for item in facts["achievements"]:
            resume_lines.append(f"- {item}")
    else:
        resume_lines.append("- None listed in the approved profile. Not invented.")

    resume_lines += [
        "",
        "## Source note",
        "This tailored resume only uses facts from config/profile.json and the master resume. Missing profile fields stay blank.",
    ]
    resume_text = "\n".join(line for line in resume_lines if line is not None).strip() + "\n"

    cover_lines = [
        f"Date: {date.today().isoformat()}",
        "",
        f"Dear Hiring Team at {job.get('company') or 'the company'},",
        "",
        f"I am applying for the {job.get('title') or 'advertised'} role. I am a fresher / entry-level candidate pursuing {facts['degree']} (graduation year {facts['graduation_year']}).",
        "",
    ]
    if highlighted:
        cover_lines.append("Skills from my approved profile that overlap this listing: " + ", ".join(highlighted) + ".")
        cover_lines.append("")
    missing = [skill for skill in (job.get("required_skills") or []) if str(skill) not in skills]
    if missing:
        cover_lines.append("I am not claiming the following listed skills unless they already appear in my profile: " + ", ".join(map(str, missing)) + ".")
        cover_lines.append("")
    cover_lines += [
        "This letter uses only facts from my approved profile. Please see the attached tailored resume.",
        "",
        "Thank you for your time.",
        "",
        facts["full_name"] or "Name not set in profile.json",
    ]
    cover_text = "\n".join(cover_lines) + "\n"

    # Grounding: every skill line must exist in profile/master.
    allowed = master + "\n" + json_facts(facts)
    _grounded_lines(resume_text, allowed)
    return {"resume": resume_text, "cover_letter": cover_text, "highlighted_skills": ", ".join(highlighted)}


def export_resume_formats(markdown_text: str, stem) -> dict[str, str]:
    from pathlib import Path

    stem_path = Path(stem)
    outputs: dict[str, str] = {}
    txt_path = stem_path.with_suffix(".txt")
    txt_path.write_text(markdown_text, encoding="utf-8")
    outputs["txt_path"] = str(txt_path)
    tex_path = stem_path.with_suffix(".tex")
    tex_path.write_text(_to_latex(markdown_text), encoding="utf-8")
    outputs["tex_path"] = str(tex_path)
    try:
        outputs["docx_path"] = str(_to_docx(markdown_text, stem_path.with_suffix(".docx")))
    except Exception:
        outputs["docx_path"] = ""
    try:
        outputs["pdf_path"] = str(_to_pdf(markdown_text, stem_path.with_suffix(".pdf")))
    except Exception:
        outputs["pdf_path"] = ""
    return outputs


def _to_latex(markdown_text: str) -> str:
    escaped = []
    for line in markdown_text.splitlines():
        line = line.replace("&", "\\&")
        if line.startswith("# "):
            escaped.append("\\section*{" + line[2:] + "}")
        elif line.startswith("## "):
            escaped.append("\\subsection*{" + line[3:] + "}")
        elif line.startswith("- "):
            escaped.append("\\item " + line[2:])
        else:
            escaped.append(line)
    return "\\documentclass{article}\n\\begin{document}\n" + "\n".join(escaped) + "\n\\end{document}\n"


def _to_docx(markdown_text: str, path):
    from docx import Document

    document = Document()
    for line in markdown_text.splitlines():
        if line.startswith("# "):
            document.add_heading(line[2:], level=1)
        elif line.startswith("## "):
            document.add_heading(line[3:], level=2)
        else:
            document.add_paragraph(line)
    document.save(str(path))
    return path


def _to_pdf(markdown_text: str, path):
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(str(path), pagesize=A4)
    width, height = A4
    y = height - 40
    for line in markdown_text.splitlines():
        if y < 40:
            c.showPage()
            y = height - 40
        c.drawString(40, y, line[:110])
        y -= 14
    c.save()
    return path


def json_facts(facts: dict[str, Any]) -> str:
    parts = [str(value) for key, value in facts.items() if key != "projects"]
    parts.extend(str(item) for item in facts.get("projects") or [])
    parts.extend(str(item) for item in facts.get("internships") or [])
    parts.extend(str(item) for item in facts.get("achievements") or [])
    return "\n".join(parts)


def save_tailored_documents(job: dict[str, Any], store: JobStore | None = None, profile: dict[str, Any] | None = None) -> dict[str, Any]:
    ensure_runtime_dirs()
    documents = build_tailored_resume(job, profile)
    company = slug(job.get("company"))
    title = slug(job.get("title"))
    folder = TAILORED_RESUMES_DIR / f"{company}-{title}"
    folder.mkdir(parents=True, exist_ok=True)
    resume_path = folder / f"{company}-{title}-resume.md"
    cover_path = folder / f"{company}-{title}-cover-letter.md"
    resume_path.write_text(documents["resume"], encoding="utf-8")
    cover_path.write_text(documents["cover_letter"], encoding="utf-8")
    exports = export_resume_formats(documents["resume"], folder / f"{company}-{title}-resume")
    result = {
        "resume_path": str(resume_path),
        "cover_letter_path": str(cover_path),
        "highlighted_skills": documents["highlighted_skills"],
        **exports,
    }
    if store is not None and job.get("id"):
        result["tailored_resume_id"] = store.save_tailored_resume(int(job["id"]), result["resume_path"], result["cover_letter_path"])
    return result


def rewrite_master_resume_from_profile(profile: dict[str, Any] | None = None) -> Path:
    profile = profile or load_profile()
    dummy_job = {
        "title": "target roles listed in profile.json",
        "company": "future employers",
        "description": " ".join(profile.get("skills") or []),
        "required_skills": profile.get("skills") or [],
    }
    documents = build_tailored_resume(dummy_job, profile)
    path = Path(profile.get("master_resume_path") or "resumes/master_resume.md")
    if not path.is_absolute():
        from job_agent.paths import PROJECT_ROOT

        path = PROJECT_ROOT / path
    path.write_text(documents["resume"], encoding="utf-8")
    return path
