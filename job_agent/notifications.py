from __future__ import annotations

import json
import os
import re
from typing import Any
import httpx

from job_agent.config import describe_secret, load_environment
from job_agent.database import JobStore
from job_agent.verification import FAKE_HOSTS, UNVERIFIED_SOURCES, is_verified_listing

ALERT_MATCH_THRESHOLD = 80

__all__ = [
    "ALERT_MATCH_THRESHOLD",
    "FAKE_HOSTS",
    "UNVERIFIED_SOURCES",
    "is_verified_listing",
    "notify",
    "send_job_alert",
    "send_telegram_message",
    "telegram_status",
]


def _redact(text: str) -> str:
    load_environment()
    cleaned = str(text or "")
    token = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    chat_id = (os.getenv("TELEGRAM_CHAT_ID") or "").strip()
    if token:
        cleaned = cleaned.replace(token, "[REDACTED]")
    if chat_id:
        cleaned = cleaned.replace(chat_id, "[REDACTED]")
    cleaned = re.sub(r"bot\d+:[A-Za-z0-9_-]+", "bot[REDACTED]", cleaned)
    return cleaned


def telegram_is_configured() -> bool:
    token, chat_id = _credentials()
    return bool(token and chat_id and ":" in token and chat_id.lstrip("-").isdigit())


def telegram_status() -> dict[str, str]:
    load_environment()
    return {
        "TELEGRAM_BOT_TOKEN": describe_secret("TELEGRAM_BOT_TOKEN"),
        "TELEGRAM_CHAT_ID": describe_secret("TELEGRAM_CHAT_ID"),
        "ready": "yes" if telegram_is_configured() else "no",
    }


def _clean_secret(value: str | None) -> str:
    return (value or "").strip().strip('"').strip("'")


def _credentials() -> tuple[str, str]:
    load_environment()
    token = _clean_secret(os.getenv("TELEGRAM_BOT_TOKEN"))
    chat_id = _clean_secret(os.getenv("TELEGRAM_CHAT_ID"))
    if not token or not chat_id:
        from dotenv import dotenv_values

        from job_agent.paths import PROJECT_ROOT

        file_vals = dotenv_values(PROJECT_ROOT / ".env") or {}
        token = token or _clean_secret(file_vals.get("TELEGRAM_BOT_TOKEN"))
        chat_id = chat_id or _clean_secret(file_vals.get("TELEGRAM_CHAT_ID"))
    return token, chat_id


def send_telegram_message(message: str) -> dict[str, Any]:
    token, chat_id = _credentials()
    if not token or not chat_id:
        return {"sent": False, "reason": "Telegram is not configured."}
    if ":" not in token or not chat_id.lstrip("-").isdigit():
        return {"sent": False, "reason": "Telegram credentials look invalid."}
    text = str(message or "").strip()
    if not text:
        return {"sent": False, "reason": "empty_message"}
    if len(text) > 3500:
        text = text[:3490] + "\n…"
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        response = httpx.post(
            url,
            json={"chat_id": chat_id, "text": text, "disable_web_page_preview": False},
            timeout=20,
        )
    except httpx.HTTPError as exc:
        return {"sent": False, "reason": f"network_error:{type(exc).__name__}"}
    try:
        payload = response.json()
    except ValueError:
        return {"sent": False, "reason": f"telegram_non_json:{response.status_code}"}
    if response.status_code == 401:
        return {"sent": False, "reason": "invalid_credentials"}
    if response.status_code == 400:
        return {"sent": False, "reason": "telegram_bad_request"}
    ok = response.status_code == 200 and bool(payload.get("ok"))
    if ok:
        return {"sent": True, "status_code": 200, "reason": None}
    description = _redact(str(payload.get("description") or "Telegram API did not accept the message."))
    return {"sent": False, "status_code": response.status_code, "reason": description}


def test_telegram_connection() -> dict[str, Any]:
    token, chat_id = _credentials()
    if not token or not chat_id:
        return {"ok": False, "step": "config", "reason": "Telegram is not configured."}
    try:
        me = httpx.get(f"https://api.telegram.org/bot{token}/getMe", timeout=20)
        me_json = me.json()
    except httpx.HTTPError as exc:
        return {"ok": False, "step": "getMe", "reason": f"network_error:{type(exc).__name__}"}
    except ValueError:
        return {"ok": False, "step": "getMe", "reason": "telegram_non_json"}
    if me.status_code == 401 or not me_json.get("ok"):
        return {"ok": False, "step": "getMe", "reason": "invalid_credentials"}
    result = send_telegram_message(
        "Job Hunting Agent connected.\nThis is a Telegram connection test. You will get alerts for verified jobs scoring 80% or higher."
    )
    if not result.get("sent"):
        return {"ok": False, "step": "sendMessage", "reason": result.get("reason")}
    username = (me_json.get("result") or {}).get("username") or "bot"
    return {"ok": True, "step": "sendMessage", "bot_username": username, "reason": None}


def _as_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if item]
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return [str(item) for item in parsed if item]
        except json.JSONDecodeError:
            return [value]
    return []


def format_job_alert(job: dict[str, Any]) -> str:
    skills = _as_list(job.get("possessed_skills") or job.get("match_possessed"))
    missing = _as_list(job.get("missing_skills") or job.get("match_missing"))
    apply_url = str(job.get("apply_url") or "").strip() or "Link not published"
    match = job.get("match_percent")
    match_text = f"{match}% {job.get('grade') or ''}".strip() if match is not None else "Not scored"
    lines = [
        "NEW JOB MATCH",
        str(job.get("title") or "Role not published"),
        f"Company: {job.get('company') or 'Not published'}",
        f"Location: {job.get('location') or 'Not published'}",
        f"Experience: {job.get('experience') or 'Not published'}",
        f"Salary: {job.get('salary') or 'Not published'}",
        f"Match: {match_text}",
        f"Posted: {job.get('posted_at') or 'Not published'}",
        f"Source: {job.get('source') or 'unknown'}",
        "",
        "Matching skills: " + (", ".join(skills[:8]) if skills else "not listed"),
        "Missing skills: " + (", ".join(missing[:8]) if missing else "none listed"),
        "",
        "Apply here:",
        apply_url,
    ]
    return "\n".join(lines)


def already_alerted(job_id: int | None, store: JobStore) -> bool:
    if not job_id:
        return False
    with store.connect() as conn:
        row = conn.execute(
            """
            SELECT 1 FROM notifications
            WHERE job_id = ? AND kind IN ('job_alert', 'strong_match') AND sent_at IS NOT NULL
            LIMIT 1
            """,
            (job_id,),
        ).fetchone()
        job = conn.execute("SELECT last_notified_at FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if row:
        return True
    return bool(job and job["last_notified_at"])


def send_job_alert(job: dict[str, Any], store: JobStore | None = None) -> dict[str, Any]:
    store = store or JobStore()
    job_id = job.get("id")
    if not is_verified_listing(job):
        return {"sent": False, "reason": "unverified_or_sample_listing"}
    try:
        score = int(job.get("match_percent") if job.get("match_percent") is not None else -1)
    except (TypeError, ValueError):
        score = -1
    if score < ALERT_MATCH_THRESHOLD:
        return {"sent": False, "reason": "below_alert_threshold"}
    if already_alerted(job_id, store):
        return {"sent": False, "reason": "duplicate_alert"}
    message = format_job_alert(job)
    result = send_telegram_message(message)
    store.add_notification(
        "job_alert",
        message,
        job_id=job_id,
        channel="telegram" if result.get("sent") else None,
        sent=bool(result.get("sent")),
    )
    if result.get("sent") and job_id:
        store.mark_job_notified(int(job_id))
    return result


def notify(kind: str, message: str, job_id: int | None = None, store: JobStore | None = None, send: bool = True) -> dict[str, Any]:
    store = store or JobStore()
    result = {"sent": False, "reason": "stored locally only"}
    channel = None
    if send and telegram_is_configured():
        result = send_telegram_message(message)
        channel = "telegram" if result.get("sent") else None
    store.add_notification(kind, message, job_id=job_id, channel=channel, sent=bool(result.get("sent")))
    return result


def notify_new_matches(jobs: list[dict[str, Any]], store: JobStore | None = None) -> list[dict[str, Any]]:
    store = store or JobStore()
    results = []
    for job in jobs:
        results.append(send_job_alert(job, store=store))
    return results


def send_daily_summary(store: JobStore | None = None) -> dict[str, Any]:
    store = store or JobStore()
    stats = store.stats()
    excellent = store.list_jobs("job_matches.match_percent >= 85 AND jobs.source NOT IN ('sample', 'fixture', 'demo', 'test')")
    lines = [
        "DAILY JOB SUMMARY",
        "",
        f"Total jobs: {stats['total_jobs']}",
        f"New today: {stats['new_today']}",
        f"Excellent matches: {stats.get('excellent_matches', stats.get('strong_matches', 0))}",
        f"Good matches: {stats.get('good_matches', 0)}",
        f"Applications submitted: {stats['applications_submitted']}",
        "",
        "Top verified excellent matches:",
    ]
    verified = [job for job in excellent if is_verified_listing(job)][:8]
    if not verified:
        lines.append("None today.")
    for job in verified:
        lines.append(f"- {job.get('title')} at {job.get('company')} ({job.get('match_percent')}%)")
    return notify("daily_summary", "\n".join(lines), store=store, send=True)
