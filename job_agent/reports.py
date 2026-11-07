from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any

from job_agent.database import JobStore
from job_agent.notifications import notify, send_daily_summary
from job_agent.paths import REPORTS_DIR, ensure_runtime_dirs


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def write_daily_report(store: JobStore | None = None) -> str:
    store = store or JobStore()
    ensure_runtime_dirs()
    stats = store.stats()
    today = _today()
    path = REPORTS_DIR / f"daily-summary-{today}.md"
    excellent = store.list_jobs("job_matches.match_percent >= 85")
    lines = [
        f"# Daily job summary — {today}",
        "",
        f"- Jobs discovered (all time): {stats['total_jobs']}",
        f"- New today: {stats['new_today']}",
        f"- Excellent matches: {stats.get('excellent_matches', 0)}",
        f"- Shortlisted: {stats.get('shortlisted', 0)}",
        f"- Applications submitted: {stats['applications_submitted']}",
        "",
        "## Excellent matches",
    ]
    if not excellent:
        lines.append("None yet.")
    for job in excellent[:20]:
        lines.append(f"- {job.get('title')} at {job.get('company')} ({job.get('match_percent')}%)")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    send_daily_summary(store=store)
    return str(path)


def write_weekly_report(store: JobStore | None = None) -> str:
    store = store or JobStore()
    ensure_runtime_dirs()
    stats = store.stats()
    today = _today()
    path = REPORTS_DIR / f"weekly-report-{today}.md"
    apps = store.list_applications()
    jobs = store.list_jobs()
    categories = Counter()
    for job in jobs:
        title = (job.get("title") or "other").lower()
        if "data engineer" in title:
            categories["Data Engineering"] += 1
        elif "analyst" in title:
            categories["Data Analyst"] += 1
        elif "cloud" in title:
            categories["Cloud"] += 1
        elif "python" in title or "developer" in title or "software" in title:
            categories["Software"] += 1
        else:
            categories["Other"] += 1
    lines = [
        f"# Weekly application report — {today}",
        "",
        f"- Vacancies tracked: {stats['total_jobs']}",
        f"- Applications submitted: {stats['applications_submitted']}",
        f"- Interviews: {stats['interviews']}",
        f"- Rejections: {stats['rejected']}",
        f"- Response rate: {stats['success_rate']}%",
        f"- Strongest categories: {', '.join(f'{k} ({v})' for k, v in categories.most_common(3)) or 'n/a'}",
        "",
        "## Skills to improve",
        "- Add only real projects/internships to profile.json so tailored resumes can use them.",
        "- Optional tools that appear often in JDs but are missing from the profile stay as learning gaps, not invented skills.",
        "",
        "## Applications",
    ]
    if not apps:
        lines.append("None yet.")
    for app in apps:
        lines.append(f"- {app.get('status')}: {app.get('title')} at {app.get('company')}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    notify(
        "weekly_report",
        f"Weekly report: submitted={stats['applications_submitted']} interviews={stats['interviews']} rejects={stats['rejected']}.",
        store=store,
        send=True,
    )
    return str(path)
