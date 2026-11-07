from __future__ import annotations

import json
import os
import re
from job_agent.config import (
    gemini_api_key,
    gemini_is_configured,
    groq_api_key,
    groq_is_configured,
    load_profile,
    openrouter_api_key,
    openrouter_is_configured,
    read_master_resume,
)

ENTRY_HINTS = (
    "fresher",
    "entry-level",
    "entry level",
    "graduate trainee",
    "associate trainee",
    "junior",
    "0-1",
    "0 to 1",
    "intern",
    "trainee",
)
SENIOR_HINTS = (
    "8+",
    "7+",
    "6+",
    "5+ years",
    "staff",
    "principal",
    "senior",
    "lead",
    "architect",
)


def _norm(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().lower())


def classify_match(percent: int) -> tuple[str, str]:
    if percent >= 85:
        return "Excellent", "high"
    if percent >= 70:
        return "Good", "high"
    if percent >= 50:
        return "Moderate", "medium"
    return "Low", "low"


ROLE_FAMILIES: dict[str, tuple[str, ...]] = {
    "data_engineer": ("data engineer", "data engineering", "etl engineer", "data pipeline engineer"),
    "data_analyst": ("data analyst", "business analyst", "bi analyst", "reporting analyst"),
    "data_scientist": ("data scientist", "machine learning engineer", "ml engineer"),
    "python_developer": ("python developer", "python engineer"),
    "cloud_engineer": ("cloud engineer", "devops engineer", "site reliability", "sre"),
    "software_developer": (
        "software developer",
        "software engineer",
        "associate software engineer",
        "sde",
        "ase intern",
        "full stack",
        "fullstack",
    ),
}


def detect_role_family(title: str) -> str | None:
    text = _norm(title)
    for family, needles in ROLE_FAMILIES.items():
        if any(needle in text for needle in needles):
            return family
    return None


def role_title_score(job_title: str, target_roles: list[str] | None) -> int:
    title = _norm(job_title)
    roles = [_norm(role) for role in (target_roles or []) if role]
    if any(role and (role in title or title in role) for role in roles):
        return 92
    job_family = detect_role_family(title)
    target_families = {detect_role_family(role) for role in roles}
    target_families.discard(None)
    if job_family and target_families and job_family not in target_families:
        return 22
    if job_family and not target_families:
        return 55
    return 35


def _skill_list(values: list[str] | None) -> list[str]:
    seen = []
    for item in values or []:
        text = str(item).strip()
        if text and text.lower() not in {s.lower() for s in seen}:
            seen.append(text)
    return seen


def heuristic_match(job: dict[str, Any], profile: dict[str, Any] | None = None, resume_text: str = "") -> dict[str, Any]:
    profile = profile or load_profile()
    resume_text = resume_text or read_master_resume(profile)
    profile_skills = _skill_list(profile.get("skills"))
    job_skills = _skill_list(job.get("required_skills"))
    blob = " ".join(
        [
            str(job.get("title") or ""),
            str(job.get("description") or ""),
            " ".join(job_skills),
            str(job.get("experience") or ""),
        ]
    )
    blob_l = _norm(blob)
    resume_l = _norm(resume_text + " " + " ".join(profile_skills))

    if not job_skills:
        for skill in profile_skills:
            if _norm(skill) in blob_l:
                job_skills.append(skill)

    possessed = [skill for skill in job_skills if _norm(skill) in resume_l]
    missing = [skill for skill in job_skills if skill not in possessed]
    optional_missing = [skill for skill in missing if skill.lower() not in {"python", "sql", "git"}]
    required_missing = [skill for skill in missing if skill not in optional_missing]

    skill_score = 0
    if job_skills:
        skill_score = round(100 * len(possessed) / len(job_skills))
    else:
        skill_score = 50

    title = _norm(job.get("title"))
    title_score = role_title_score(str(job.get("title") or ""), profile.get("target_roles") or [])
    if any(hint in title for hint in ENTRY_HINTS):
        title_score = min(100, title_score + 8)

    locations = [_norm(item) for item in (profile.get("preferred_locations") or [])]
    job_location = _norm(job.get("location"))
    location_ok = (not job_location) or any(loc and loc in job_location or job_location in loc for loc in locations)
    if "united states" in job_location or "us work authorization" in blob_l:
        location_ok = False

    experience_text = _norm(str(job.get("experience") or "") + " " + blob_l)
    senior = any(hint in experience_text or hint in title for hint in SENIOR_HINTS)
    entry = any(hint in experience_text or hint in title for hint in ENTRY_HINTS)
    if senior and not entry:
        experience_eligible = "No — the listing asks for senior experience."
        exp_score = 10
    elif entry or not job.get("experience"):
        experience_eligible = "Yes — fresher / 0-1 / trainee language is compatible, or experience was not stated."
        exp_score = 90
    else:
        experience_eligible = "Unclear from the listing; do not assume eligibility."
        exp_score = 50

    match_percent = round((skill_score * 0.45) + (title_score * 0.25) + (exp_score * 0.2) + (15 if location_ok else 0))
    match_percent = max(0, min(100, match_percent))
    if senior and not entry:
        match_percent = min(match_percent, 35)

    grade, priority = classify_match(match_percent)
    education = profile.get("education") or {}
    education_eligible = (
        f"Yes — {(education.get('degree') or 'listed degree')}, graduating {education.get('graduation_year')}, "
        "is compatible with fresher/trainee listings unless a postgraduate-only requirement is explicit."
    )
    if "phd" in blob_l and "bachelor" not in blob_l and "b.tech" not in blob_l and "btech" not in blob_l:
        education_eligible = "Unclear — listing may prefer a postgraduate degree; do not assume eligibility."

    reasons_apply = []
    reasons_reject = []
    if title_score >= 80:
        reasons_apply.append("Title is close to a target role.")
    if possessed:
        reasons_apply.append("Listed skills already on the profile: " + ", ".join(possessed[:8]))
    if entry:
        reasons_apply.append("Listing appears fresher/entry-level compatible.")
    if location_ok:
        reasons_apply.append("Location looks compatible with the India/remote preference list.")
    if optional_missing:
        reasons_apply.append("Missing skills look optional rather than automatic disqualifiers: " + ", ".join(optional_missing[:6]))

    if not location_ok:
        reasons_reject.append("Location/work authorization does not match India-focused search.")
    if senior and not entry:
        reasons_reject.append("Experience requirement is well above fresher/0-1 years.")
    if required_missing:
        reasons_reject.append("Core listed skills not on the profile: " + ", ".join(required_missing[:6]))
    if not reasons_apply and grade == "Low":
        reasons_reject.append("Weak overlap with the current target roles and skills.")

    return {
        "match_percent": match_percent,
        "grade": grade,
        "required_skills": job_skills,
        "possessed_skills": possessed,
        "missing_skills": missing,
        "experience_eligible": experience_eligible,
        "education_eligible": education_eligible,
        "salary_information": job.get("salary") or "Not published",
        "location_compatible": location_ok,
        "priority": priority,
        "reasons_apply": reasons_apply,
        "reasons_reject": reasons_reject,
        "method": "heuristic",
        "notes": "Heuristic scoring never invents qualifications. Optional missing skills do not auto-reject.",
    }


def _build_match_prompt(job: dict[str, Any], profile: dict[str, Any], resume_text: str) -> dict[str, Any]:
    return {
        "instructions": (
            "Compare the job with the candidate profile and master resume. "
            "Return JSON only. Do not invent skills, projects, internships or experience. "
            "Do not reject only because one optional skill is missing. "
            "Score 85-100 excellent, 70-84 good, 50-69 moderate, below 50 low. "
            "If a field is unknown, use null or an empty list."
        ),
        "profile": {
            "target_roles": profile.get("target_roles"),
            "education": profile.get("education"),
            "experience_level": profile.get("experience_level"),
            "skills": profile.get("skills"),
            "preferred_locations": profile.get("preferred_locations"),
            "projects": profile.get("projects") or [],
            "internships": profile.get("internships") or [],
        },
        "resume": resume_text[:8000],
        "job": {
            "title": job.get("title"),
            "company": job.get("company"),
            "location": job.get("location"),
            "salary": job.get("salary"),
            "experience": job.get("experience"),
            "description": (job.get("description") or "")[:6000],
            "required_skills": job.get("required_skills") or [],
        },
        "output_schema": {
            "match_percent": "0-100 integer",
            "grade": "Excellent, Good, Moderate or Low",
            "required_skills": [],
            "possessed_skills": [],
            "missing_skills": [],
            "experience_eligible": "short string",
            "location_compatible": True,
            "priority": "high/medium/low",
            "reasons_apply": [],
            "reasons_reject": [],
        },
    }


def _groq_match(prompt: dict[str, Any]) -> dict[str, Any] | None:
    if not groq_is_configured():
        return None
    from groq import Groq

    client = Groq(api_key=groq_api_key(), timeout=15.0)
    model = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": "You are an ATS job matcher. Compare the profile to the job. Output strict JSON only matching output_schema.",
            },
            {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
        ],
        response_format={"type": "json_object"},
    )
    text = (resp.choices[0].message.content or "").strip()
    data = json.loads(text)
    data["method"] = f"groq ({model})"
    return data


def _openrouter_match(prompt: dict[str, Any]) -> dict[str, Any] | None:
    if not openrouter_is_configured():
        return None
    import httpx

    key = openrouter_api_key()
    model = os.getenv("OPENROUTER_MODEL", "nvidia/nemotron-3.5-super-vl:free")
    resp = httpx.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": "You are an ATS job matcher. Compare the profile to the job. Output strict JSON only matching output_schema.",
                },
                {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
            ],
            "response_format": {"type": "json_object"},
        },
        timeout=30.0,
    )
    resp.raise_for_status()
    payload = resp.json()
    content = payload["choices"][0]["message"]["content"]
    data = json.loads(content)
    data["method"] = f"openrouter ({model})"
    return data


def _gemini_api_match(prompt: dict[str, Any]) -> dict[str, Any] | None:
    if not gemini_is_configured():
        return None
    from google import genai

    client = genai.Client(api_key=gemini_api_key())
    model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    response = client.models.generate_content(
        model=model,
        contents=json.dumps(prompt, ensure_ascii=False),
        config={"response_mime_type": "application/json"},
    )
    text = (response.text or "").strip()
    data = json.loads(text)
    data["method"] = "gemini"
    return data


def _llm_match(job: dict[str, Any], profile: dict[str, Any], resume_text: str) -> dict[str, Any] | None:
    prompt = _build_match_prompt(job, profile, resume_text)

    # 1. Try Groq (primary, ultra-fast)
    try:
        data = _groq_match(prompt)
        if data:
            return data
    except Exception:
        pass

    # 2. Try OpenRouter (secondary)
    try:
        data = _openrouter_match(prompt)
        if data:
            return data
    except Exception:
        pass

    # 3. Try Gemini (tertiary)
    try:
        data = _gemini_api_match(prompt)
        if data:
            return data
    except Exception:
        pass

    return None


def _gemini_match(job: dict[str, Any], profile: dict[str, Any], resume_text: str) -> dict[str, Any] | None:
    """Backward-compatible wrapper; executes multi-tier LLM match."""
    return _llm_match(job, profile, resume_text)


def analyze_job(job: dict[str, Any], profile: dict[str, Any] | None = None, use_gemini: bool = True) -> dict[str, Any]:
    profile = profile or load_profile()
    resume_text = read_master_resume(profile)
    base = heuristic_match(job, profile, resume_text)
    if not use_gemini:
        return base
    try:
        llm_result = _llm_match(job, profile, resume_text)
    except Exception as exc:
        base["llm_error"] = type(exc).__name__
        return base
    if not llm_result:
        return base

    merged = dict(base)
    for key in (
        "match_percent",
        "grade",
        "required_skills",
        "possessed_skills",
        "missing_skills",
        "experience_eligible",
        "education_eligible",
        "location_compatible",
        "priority",
        "reasons_apply",
        "reasons_reject",
    ):
        if llm_result.get(key) not in (None, "", []):
            merged[key] = llm_result[key]
    try:
        merged["match_percent"] = max(0, min(100, int(merged.get("match_percent") or 0)))
    except (TypeError, ValueError):
        merged["match_percent"] = base["match_percent"]
    merged["grade"], merged["priority"] = classify_match(int(merged["match_percent"]))
    merged["method"] = llm_result.get("method", "llm") + "+heuristic"
    return merged
