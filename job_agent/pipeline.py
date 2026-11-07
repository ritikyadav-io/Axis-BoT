from __future__ import annotations

from typing import Any

from job_agent.config import load_profile
from job_agent.database import JobStore
from job_agent.discovery import ingest_discovered_jobs
from job_agent.matching import analyze_job
from job_agent.notifications import ALERT_MATCH_THRESHOLD, notify_new_matches
from job_agent.verification import is_verified_listing
from job_agent.reports import write_daily_report, write_weekly_report as write_weekly_report_file


def run_discovery_and_match(use_network: bool | None = None, use_gemini: bool = True, store: JobStore | None = None) -> dict[str, Any]:
    store = store or JobStore()
    ingest = ingest_discovered_jobs(store=store, use_network=use_network)
    profile = load_profile()
    scored = []
    alert_candidates = []
    unmatched = [job["id"] for job in store.list_jobs("job_matches.job_id IS NULL")]
    score_ids = list(dict.fromkeys((ingest.get("new_job_ids") or []) + unmatched))
    gemini_budget = 12
    for index, job_id in enumerate(score_ids):
        job = store.get_job(job_id)
        if not job:
            continue
        analysis = analyze_job(job, profile=profile, use_gemini=use_gemini and index < gemini_budget)
        store.save_match(job_id, analysis)
        job.update(analysis)
        scored.append(job)
        score = int(analysis.get("match_percent") or 0)
        if score >= ALERT_MATCH_THRESHOLD and is_verified_listing(job):
            alert_candidates.append(job)
    sent_results = notify_new_matches(alert_candidates, store=store) if alert_candidates else []
    ingest["matched"] = len(scored)
    ingest["alert_candidates"] = len(alert_candidates)
    ingest["notified"] = sum(1 for item in sent_results if item.get("sent"))
    ingest["notified_jobs"] = [
        {
            "title": job.get("title"),
            "company": job.get("company"),
            "apply_url": job.get("apply_url"),
            "match_percent": job.get("match_percent"),
        }
        for job, result in zip(alert_candidates, sent_results)
        if result.get("sent")
    ]
    ingest["grades"] = {
        "Excellent": sum(1 for job in scored if job.get("grade") == "Excellent"),
        "Good": sum(1 for job in scored if job.get("grade") == "Good"),
        "Moderate": sum(1 for job in scored if job.get("grade") == "Moderate"),
        "Low": sum(1 for job in scored if job.get("grade") == "Low"),
    }
    return ingest


def write_daily_summary(store: JobStore | None = None) -> str:
    return write_daily_report(store)


def write_weekly_report(store: JobStore | None = None) -> str:
    return write_weekly_report_file(store)
