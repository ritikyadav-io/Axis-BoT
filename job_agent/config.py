from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Any

from dotenv import dotenv_values, load_dotenv

from job_agent.paths import PROFILE_PATH, PROJECT_ROOT, SCHEDULE_PATH, ensure_runtime_dirs

DEFAULT_PROFILE: dict[str, Any] = {
    "full_name": "",
    "email": "",
    "phone": "",
    "city": "",
    "linkedin_url": "",
    "github_url": "",
    "target_country": "India",
    "preferred_locations": ["India", "Remote"],
    "target_roles": [],
    "education": {},
    "experience_level": "Fresher / entry-level",
    "years_of_experience": "0-1",
    "skills": [],
    "search_keywords": ["fresher", "entry-level"],
    "projects": [],
    "internships": [],
    "certifications": [],
    "achievements": [],
    "expected_salary": "",
    "master_resume_path": "resumes/master/master_resume.md",
    "company_career_pages": [],
    "enabled_sources": ["sample"],
}


def load_environment() -> None:
    env_path = PROJECT_ROOT / ".env"
    load_dotenv(env_path, override=False)
    for key, value in (dotenv_values(env_path) or {}).items():
        if value and not (os.getenv(key) or "").strip():
            os.environ[key] = str(value).strip().strip('"').strip("'")
    gemini_key = (os.getenv("GEMINI_API_KEY") or "").strip()
    google_key = (os.getenv("GOOGLE_API_KEY") or "").strip()
    if gemini_key and not google_key:
        os.environ["GOOGLE_API_KEY"] = gemini_key


def groq_api_key() -> str:
    return (os.getenv("GROQ_API_KEY") or "").strip()


def groq_is_configured() -> bool:
    key = groq_api_key()
    return bool(key) and key.lower() not in {"your_groq_api_key_here", "your-key", "changeme"}


def openrouter_api_key() -> str:
    return (os.getenv("OPENROUTER_API_KEY") or "").strip()


def openrouter_is_configured() -> bool:
    key = openrouter_api_key()
    return bool(key) and key.lower() not in {"your_openrouter_api_key_here", "your-key", "changeme"}


def gemini_api_key() -> str:
    return (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip()


def gemini_is_configured() -> bool:
    key = gemini_api_key()
    return bool(key) and key.lower() not in {"your_gemini_api_key_here", "your-key", "changeme"}



def describe_secret(name: str) -> str:
    value = (os.getenv(name) or "").strip()
    if not value:
        return "not configured"
    return f"detected ({len(value)} characters, value hidden)"


def load_json(path: Path, default: dict[str, Any] | None = None) -> dict[str, Any]:
    if not path.exists():
        return deepcopy(default or {})
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def load_profile() -> dict[str, Any]:
    ensure_runtime_dirs()
    profile = deepcopy(DEFAULT_PROFILE)
    profile.update(load_json(PROFILE_PATH, {}))
    return profile


def save_profile(profile: dict[str, Any]) -> None:
    save_json(PROFILE_PATH, profile)


def load_schedule() -> dict[str, Any]:
    return load_json(SCHEDULE_PATH, {"timezone": "Asia/Kolkata", "jobs": {}})


def master_resume_path(profile: dict[str, Any] | None = None) -> Path:
    profile = profile or load_profile()
    relative = profile.get("master_resume_path") or "resumes/master_resume.md"
    path = Path(relative)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


def read_master_resume(profile: dict[str, Any] | None = None) -> str:
    path = master_resume_path(profile)
    if path.exists():
        return path.read_text(encoding="utf-8")
    return ""
