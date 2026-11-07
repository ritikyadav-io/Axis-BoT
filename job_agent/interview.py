from __future__ import annotations

from typing import Any

from job_agent.config import load_profile
from job_agent.database import JobStore


def generate_prep(job: dict[str, Any], profile: dict[str, Any] | None = None) -> dict[str, Any]:
    profile = profile or load_profile()
    title = job.get("title") or "this role"
    skills = job.get("required_skills") or profile.get("skills") or []
    python_q = [
        "Explain Python lists versus tuples and when you would use each.",
        "How do you read a CSV file with Pandas and filter rows?",
        "What is the difference between a list comprehension and a for-loop?",
    ]
    sql_q = [
        "Write a SQL query to find duplicate emails in a users table.",
        "What is the difference between INNER JOIN and LEFT JOIN?",
        "How would you calculate a running total in SQL?",
    ]
    aptitude_q = [
        "A pipeline processes 1000 rows in 4 minutes. How long for 2500 rows at the same rate?",
        "If 3 ETL jobs run sequentially for 12, 18 and 10 minutes, what is total runtime?",
    ]
    hr_q = [
        f"Why are you interested in {title} as a fresher graduating in 2027?",
        "Describe a project from your approved profile. If none are listed, say you have not added one yet.",
        "How do you learn a new tool such as Docker or AWS?",
    ]
    technical_q = [f"How would you apply {skill} in an entry-level {title} role?" for skill in list(skills)[:5]]
    if not technical_q:
        technical_q = ["Walk through a simple ETL flow using Python and SQL."]
    return {
        "job_id": job.get("id"),
        "title": title,
        "technical": technical_q,
        "python": python_q,
        "sql": sql_q,
        "aptitude": aptitude_q,
        "hr": hr_q,
        "notes": "Questions are practice prompts generated from the listing and your target skills. They do not invent work history.",
    }


def evaluate_answer(question: str, answer: str, profile: dict[str, Any] | None = None) -> dict[str, Any]:
    profile = profile or load_profile()
    text = (answer or "").strip()
    if not text:
        return {"score": 0, "feedback": "No answer provided.", "gaps": ["Write a short factual answer."]}
    banned = ["i have 5 years", "i interned at google", "i led a team of"]
    lowered = text.lower()
    if any(phrase in lowered for phrase in banned) and not any(phrase in " ".join(map(str, profile.get("internships") or [])).lower() for phrase in banned):
        return {"score": 0, "feedback": "Do not claim experience that is not in your approved profile.", "gaps": ["Stick to listed skills and education."]}
    score = 40
    if len(text.split()) >= 40:
        score += 20
    for skill in profile.get("skills") or []:
        if str(skill).lower() in lowered:
            score += 5
    score = min(90, score)
    gaps = []
    if "example" not in lowered and "project" not in lowered:
        gaps.append("Add a concrete example only if it exists in your profile.")
    return {"score": score, "feedback": "Keep answers factual and tied to B.Tech AI & DS plus listed skills.", "gaps": gaps}


def save_prep(job_id: int, store: JobStore | None = None) -> dict[str, Any]:
    store = store or JobStore()
    job = store.get_job(job_id)
    if not job:
        raise ValueError(f"Job {job_id} was not found.")
    prep = generate_prep(job)
    store.save_interview(job_id, prep)
    return prep
