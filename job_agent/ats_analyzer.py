from __future__ import annotations

import re
from typing import Any

from job_agent.config import load_profile, read_master_resume


def _tokens(text: str) -> set[str]:
    return {token.lower() for token in re.findall(r"[A-Za-z][A-Za-z0-9+.#-]{1,}", text or "")}


def analyze_ats(job: dict[str, Any], resume_text: str | None = None, profile: dict[str, Any] | None = None) -> dict[str, Any]:
    profile = profile or load_profile()
    resume_text = resume_text or read_master_resume(profile)
    jd = " ".join(
        [
            str(job.get("title") or ""),
            str(job.get("description") or ""),
            " ".join(job.get("required_skills") or []),
        ]
    )
    job_tokens = _tokens(jd)
    resume_tokens = _tokens(resume_text + " " + " ".join(profile.get("skills") or []))
    profile_skills = [str(item) for item in profile.get("skills") or []]
    overlapping = [skill for skill in profile_skills if skill.lower() in jd.lower()]
    missing_from_resume = [
        skill for skill in (job.get("required_skills") or []) if str(skill).lower() not in resume_text.lower()
    ]
    coverage = 0
    if job_tokens:
        coverage = round(100 * len(job_tokens & resume_tokens) / max(1, len(job_tokens)))
    return {
        "coverage_percent": min(100, coverage),
        "overlapping_profile_skills": overlapping,
        "job_skills_absent_from_resume": missing_from_resume,
        "changes_to_make": [
            "Move overlapping skills higher on the resume.",
            "Keep missing skills off the resume unless they are already in the approved profile.",
            "Do not add internships, projects or certificates that are not in profile.json.",
        ],
        "safe_to_claim": overlapping,
        "not_safe_to_claim": missing_from_resume,
    }
