from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from job_agent.database import JobStore, utc_now
from job_agent.notifications import notify
from job_agent.verification import is_verified_listing

STATUSES = [
    "Discovered",
    "Under Review",
    "Shortlisted",
    "Resume Prepared",
    "Ready for Approval",
    "Applied",
    "Assessment Pending",
    "Interview Scheduled",
    "Rejected",
    "Offer Received",
]

JOB_STATUS_MAP = {
    "Discovered": "discovered",
    "Under Review": "reviewed",
    "Shortlisted": "shortlisted",
    "Resume Prepared": "shortlisted",
    "Ready for Approval": "shortlisted",
    "Applied": "applied",
    "Assessment Pending": "applied",
    "Interview Scheduled": "interview",
    "Rejected": "rejected",
    "Offer Received": "applied",
}


def set_status(job_id: int, status: str, notes: str = "", follow_up_days: int | None = None, store: JobStore | None = None) -> dict[str, Any]:
    if status not in STATUSES:
        raise ValueError(f"Unknown status: {status}")
    store = store or JobStore()
    follow = None
    if follow_up_days is not None:
        follow = (date.today() + timedelta(days=follow_up_days)).isoformat()
    elif status in {"Applied", "Assessment Pending", "Interview Scheduled"}:
        follow = (date.today() + timedelta(days=7)).isoformat()
    fields: dict[str, Any] = {"status": status, "follow_up_at": follow}
    if notes:
        fields["notes"] = notes
    if status == "Applied":
        fields["submitted_at"] = utc_now()
    store.upsert_application(job_id, **fields)
    store.set_job_status(job_id, JOB_STATUS_MAP.get(status, "discovered"))
    if status in {"Interview Scheduled", "Offer Received", "Applied"}:
        job = store.get_job(job_id) or {}
        notify(
            "status_change",
            f"{status}: {job.get('title')} at {job.get('company')}.",
            job_id=job_id,
            store=store,
            send=is_verified_listing(job),
        )
    return {"job_id": job_id, "status": status, "follow_up_at": follow}


def _follow_up_rows(store: JobStore) -> list[dict[str, Any]]:
    lister = getattr(store, "list_follow_ups", None)
    if callable(lister):
        return list(lister())
    with store.connect() as conn:
        rows = conn.execute(
            """
            SELECT applications.*, jobs.title, jobs.company
            FROM applications
            JOIN jobs ON jobs.id = applications.job_id
            WHERE applications.follow_up_at IS NOT NULL AND applications.follow_up_at != ''
            ORDER BY applications.follow_up_at
            """
        ).fetchall()
    return [dict(row) for row in rows]


def upcoming_follow_ups(store: JobStore | None = None) -> list[dict[str, Any]]:
    store = store or JobStore()
    today = date.today().isoformat()
    try:
        rows = _follow_up_rows(store)
    except Exception:
        return []
    return [row for row in rows if (row.get("follow_up_at") or "") <= today]
