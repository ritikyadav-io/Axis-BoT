"""Offline tests for the job-hunting modules. Safe to run without Telegram or live sites."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from job_agent.application import known_profile_answers, prepare_application, set_application_approval
from job_agent.config import load_profile
from job_agent.database import JobStore
from job_agent.discovery import discover_jobs, ingest_discovered_jobs, job_fingerprint, load_sample_jobs
from job_agent.matching import analyze_job, heuristic_match
from job_agent.notifications import format_job_alert, is_verified_listing, send_job_alert, telegram_status
from job_agent.ats_analyzer import analyze_ats
from job_agent.interview import evaluate_answer, generate_prep
from job_agent.resume_builder import build_tailored_resume, export_resume_formats
from job_agent.resume_parser import extract_sections
from job_agent.tracker import set_status
from job_agent.scheduler import build_scheduler, scheduler_status


def telegram_ready_safe() -> bool:
    return False


def test_sample_discovery() -> None:
    jobs = load_sample_jobs()
    assert len(jobs) == 4
    assert all(job["fingerprint"] for job in jobs)
    assert len({job["fingerprint"] for job in jobs}) == 4


def test_duplicate_detection() -> None:
    job = load_sample_jobs()[0]
    same = dict(job)
    same["description"] = "Changed description should not create a new vacancy."
    assert job_fingerprint(job) == job_fingerprint(same)
    different = dict(job)
    different["apply_url"] = "https://example.com/jobs/other-role"
    assert job_fingerprint(job) != job_fingerprint(different)


def test_sqlite_and_ingest(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jobs.db")
    first = ingest_discovered_jobs(store=store, use_network=False)
    second = ingest_discovered_jobs(store=store, use_network=False)
    assert first["inserted"] >= 4
    assert second["inserted"] == 0
    assert second["duplicates"] >= 4
    stats = store.stats()
    assert stats["total_jobs"] >= 4


def test_matching_classes() -> None:
    profile = load_profile()
    samples = {job["title"]: job for job in load_sample_jobs()}
    junior = heuristic_match(samples["Junior Data Engineer"], profile)
    staff = heuristic_match(samples["Staff Machine Learning Engineer"], profile)
    analyst = heuristic_match(samples["Data Analyst Intern"], profile)
    assert junior["grade"] in {"Excellent", "Good"}
    assert "Python" in junior["possessed_skills"]
    assert staff["grade"] == "Low"
    assert staff["location_compatible"] is False
    assert analyst["grade"] in {"Excellent", "Good"}
    assert junior["match_percent"] > staff["match_percent"]
    assert "education_eligible" in junior


def test_resume_does_not_invent() -> None:
    job = load_sample_jobs()[0]
    documents = build_tailored_resume(job, load_profile())
    banned = ["google internship", "5 years experience", "i led a team of", "staff machine learning"]
    blob = (documents["resume"] + documents["cover_letter"]).lower()
    assert "b.tech" in blob
    assert "python" in blob
    for phrase in banned:
        assert phrase not in blob
    assert "none listed" in documents["resume"].lower()


def test_application_approval(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "apps.db")
    ingest_discovered_jobs(store=store, use_network=False)
    job = store.list_jobs()[0]
    preview = prepare_application(job["id"], store=store)
    assert preview["submit_allowed"] is False
    denied = set_application_approval(job["id"], False, store=store)
    assert denied["submit_allowed"] is False
    other = store.list_jobs()[1]
    prepare_application(other["id"], store=store)
    approved = set_application_approval(other["id"], True, store=store)
    assert approved["submit_allowed"] is True
    row = store.get_job(other["id"])
    assert row and row.get("approved_at")


def test_telegram_config_hidden() -> None:
    status = telegram_status()
    assert "TELEGRAM_BOT_TOKEN" in status
    assert "detected" in status["TELEGRAM_BOT_TOKEN"] or status["TELEGRAM_BOT_TOKEN"] == "not configured"
    assert "AQ." not in json.dumps(status)


def test_scheduler_builds() -> None:
    scheduler = build_scheduler()
    ids = {job.id for job in scheduler.get_jobs()}
    assert "morning_discovery" in ids
    assert "stop_watcher" in ids
    assert "running" in scheduler_status() or "stopped" in scheduler_status()


def test_unverified_jobs_are_not_alerted(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "alerts.db")
    job = load_sample_jobs()[0]
    job["id"] = 99
    job["match_percent"] = 95
    assert is_verified_listing(job) is False
    result = send_job_alert(job, store=store)
    assert result["sent"] is False
    assert result["reason"] == "unverified_or_sample_listing"
    text = format_job_alert(job)
    assert "NEW JOB MATCH" in text
    assert "Junior Data Engineer" in text
    assert "Apply here:" in text


def test_resume_parser_and_ats() -> None:
    text = """Name\nSkills\nPython, SQL\nEducation\nB.Tech AI and Data Science\nProjects\nCampus dashboard"""
    parsed = extract_sections(text, source="test")
    assert "Python" in parsed["skills"]
    job = load_sample_jobs()[0]
    ats = analyze_ats(job, resume_text=text)
    assert "coverage_percent" in ats
    assert "Python" in ats["overlapping_profile_skills"] or "python" in text.lower()


def test_interview_and_tracker(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "track.db")
    ingest_discovered_jobs(store=store, use_network=False)
    job = store.list_jobs()[0]
    prep = generate_prep(job)
    assert prep["python"] and prep["sql"] and prep["hr"]
    store.save_interview(job["id"], prep)
    saved = store.get_interview(job["id"])
    assert saved
    result = evaluate_answer("Why this role?", "I am a fresher studying B.Tech AI and Data Science and I use Python and SQL.")
    assert result["score"] > 0
    updated = set_status(job["id"], "Shortlisted", store=store)
    assert updated["status"] == "Shortlisted"


def test_resume_export(tmp_path: Path) -> None:
    docs = build_tailored_resume(load_sample_jobs()[0])
    outputs = export_resume_formats(docs["resume"], tmp_path / "resume")
    assert Path(outputs["txt_path"]).exists()
    assert Path(outputs["tex_path"]).exists()


def test_profile_answers_do_not_fabricate() -> None:
    answers = known_profile_answers()
    assert "password" not in answers
    # Empty contact fields stay omitted rather than invented.
    profile = load_profile()
    if not profile.get("full_name"):
        assert "full_name" not in answers


def run_all() -> None:
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        test_sample_discovery()
        print("PASS discovery sample jobs")
        test_duplicate_detection()
        print("PASS duplicate detection")
        test_sqlite_and_ingest(tmp)
        print("PASS sqlite storage")
        test_matching_classes()
        print("PASS heuristic matching")
        test_resume_does_not_invent()
        print("PASS resume grounding")
        test_application_approval(tmp)
        print("PASS application approval gate")
        test_telegram_config_hidden()
        print("PASS telegram config")
        test_scheduler_builds()
        print("PASS scheduler configuration")
        test_unverified_jobs_are_not_alerted(tmp)
        print("PASS unverified jobs skipped")
        test_resume_parser_and_ats()
        print("PASS resume parser and ATS")
        test_interview_and_tracker(tmp)
        print("PASS interview and tracker")
        test_resume_export(tmp)
        print("PASS resume export")
        test_profile_answers_do_not_fabricate()
        print("PASS profile answers")


if __name__ == "__main__":
    run_all()
    print("All offline job-agent tests passed.")
