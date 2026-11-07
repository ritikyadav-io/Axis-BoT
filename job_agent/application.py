from __future__ import annotations

import json
from typing import Any

from job_agent.config import load_profile
from job_agent.database import JobStore, utc_now
from job_agent.notifications import notify
from job_agent.verification import is_verified_listing
from job_agent.resume_builder import profile_facts, save_tailored_documents
from job_agent.tracker import set_status


PROTECTED_MARKERS = (
    "captcha",
    "recaptcha",
    "verify you are human",
    "cloudflare",
    "access denied",
    "login to continue",
)


class ApprovalRequired(RuntimeError):
    pass


def known_profile_answers(profile: dict[str, Any] | None = None) -> dict[str, str]:
    profile = profile or load_profile()
    facts = profile_facts(profile)
    answers = {
        "full_name": facts["full_name"],
        "email": facts["email"],
        "phone": facts["phone"],
        "city": facts["city"],
        "country": profile.get("target_country") or "India",
        "education": facts["degree"] or "",
        "graduation_year": str(facts["graduation_year"] or ""),
        "experience_level": facts["experience_level"] or "",
        "years_of_experience": profile.get("years_of_experience") or "0-1",
        "skills": ", ".join(facts["skills"]),
        "linkedin_url": facts["linkedin_url"],
        "github_url": facts["github_url"],
    }
    return {key: value for key, value in answers.items() if value}


def prepare_application(job_id: int, store: JobStore | None = None, profile: dict[str, Any] | None = None) -> dict[str, Any]:
    store = store or JobStore()
    profile = profile or load_profile()
    job = store.get_job(job_id)
    if not job:
        raise ValueError(f"Job {job_id} was not found.")
    documents = save_tailored_documents(job, store=store, profile=profile)
    preview = {
        "job_id": job_id,
        "title": job.get("title"),
        "company": job.get("company"),
        "apply_url": job.get("apply_url"),
        "known_answers": known_profile_answers(profile),
        "resume_path": documents["resume_path"],
        "cover_letter_path": documents["cover_letter_path"],
        "blank_fields": [key for key in ("full_name", "email", "phone") if not (profile.get(key) or "").strip()],
        "status": "awaiting_approval",
        "submit_allowed": False,
        "warning": "Nothing will be submitted until you explicitly approve this application.",
    }
    store.upsert_application(
        job_id,
        status="awaiting_approval",
        preview_json=json.dumps(preview, ensure_ascii=False),
        tailored_resume_id=documents.get("tailored_resume_id"),
    )
    store.set_job_status(job_id, "shortlisted")
    notify(
        "approval_needed",
        f"Application preview ready for {job.get('title')} at {job.get('company')}. Approve in the dashboard before submit.",
        job_id=job_id,
        store=store,
        send=is_verified_listing(job),
    )
    set_status(job_id, "Ready for Approval", store=store)
    return preview


def set_application_approval(job_id: int, approved: bool, store: JobStore | None = None, notes: str = "") -> dict[str, Any]:
    store = store or JobStore()
    job = store.get_job(job_id)
    if not job:
        raise ValueError(f"Job {job_id} was not found.")
    if approved:
        store.upsert_application(job_id, status="approved", approved_at=utc_now(), notes=notes)
        store.set_job_status(job_id, "shortlisted")
        return {"job_id": job_id, "status": "approved", "submit_allowed": True}
    store.upsert_application(job_id, status="rejected_by_user", notes=notes or "User denied submission.")
    store.set_job_status(job_id, "rejected")
    return {"job_id": job_id, "status": "rejected_by_user", "submit_allowed": False}


def _application_row(store: JobStore, job_id: int) -> dict[str, Any] | None:
    with store.connect() as conn:
        row = conn.execute("SELECT * FROM applications WHERE job_id = ?", (job_id,)).fetchone()
    return dict(row) if row else None


async def open_application_page(job_id: int, store: JobStore | None = None, submit: bool = False) -> dict[str, Any]:
    """Open the original application URL in the existing Browser Use agent.

    Filling known fields is allowed. Submission is blocked unless this application
    was explicitly approved in the database.
    """
    store = store or JobStore()
    job = store.get_job(job_id)
    if not job:
        raise ValueError(f"Job {job_id} was not found.")
    application = _application_row(store, job_id)
    if submit:
        if not application or not application.get("approved_at"):
            raise ApprovalRequired("Refusing to submit: this application has not been approved.")
        if application.get("status") not in {"approved", "submit_ready"}:
            raise ApprovalRequired(f"Refusing to submit from status {application.get('status')}.")

    from run_agent import build_browser_session, build_llm, build_tools, load_environment, revive_browser_event_bus

    load_environment()
    answers = known_profile_answers()
    answer_lines = "\n".join(f"- {key}: {value}" for key, value in answers.items()) or "- No profile contact details yet."
    resume_hint = ""
    if application and application.get("preview_json"):
        preview = json.loads(application["preview_json"])
        resume_hint = preview.get("resume_path") or ""

    if submit:
        task = f"""
Open this URL: {job.get('apply_url')}
This application was explicitly approved by the user.
Read the form. Fill only these known facts:
{answer_lines}
Attach this resume if a file picker is clearly available: {resume_hint}
If a cover letter box exists, paste a short factual note using only those details.
If you hit CAPTCHA, DRM, paywall, or a login wall, stop and ask the user to complete it manually.
After filling, submit the form only if a normal submit button is available and no security wall is present.
Report exactly what happened. Never invent form answers.
"""
    else:
        task = f"""
Open this URL: {job.get('apply_url')}
Do not submit anything.
Read the public application page. Summarize the visible form fields.
If login is required, stop and tell the user to log in manually.
If you see CAPTCHA or access protection, stop.
You may type known facts into fields but you must not click Submit, Apply, or Send.
Known facts:
{answer_lines}
"""

    llm = build_llm()
    tools = build_tools()
    browser = build_browser_session()
    revive_browser_event_bus(browser)
    from browser_use import Agent

    agent = Agent(
        task=task.strip(),
        llm=llm,
        browser=browser,
        tools=tools,
        extend_system_message="Never bypass CAPTCHA or login walls. Never submit unless the task explicitly says the user already approved.",
        enable_signal_handler=False,
        max_failures=3,
    )
    history = await agent.run(max_steps=20)
    result_text = history.final_result() if history else None
    page_text = (result_text or "").lower()
    blocked = any(marker in page_text for marker in PROTECTED_MARKERS)
    status = "submitted" if submit and not blocked else ("blocked" if blocked else "opened_for_review")
    if submit and not blocked:
        store.upsert_application(job_id, status="submitted", submitted_at=utc_now(), notes=result_text)
        store.set_job_status(job_id, "applied")
        store.add_notification("status_change", f"Recorded submission attempt for {job.get('title')} at {job.get('company')}.", job_id=job_id)
    return {
        "job_id": job_id,
        "status": status,
        "result": result_text,
        "blocked": blocked,
        "submitted": status == "submitted",
    }
