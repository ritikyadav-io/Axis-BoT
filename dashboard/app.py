from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st

from job_agent.application import prepare_application, set_application_approval
from job_agent.ats_analyzer import analyze_ats
from job_agent.config import describe_secret, gemini_is_configured, load_environment, load_profile, load_schedule, save_profile
from job_agent.database import JobStore
from job_agent.interview import evaluate_answer, generate_prep, save_prep
from job_agent.notifications import telegram_status
from job_agent.pipeline import run_discovery_and_match
from job_agent.resume_builder import rewrite_master_resume_from_profile, save_tailored_documents
from job_agent.resume_parser import parse_resume_file
from job_agent.scheduler import scheduler_status
from job_agent.tracker import STATUSES, set_status, upcoming_follow_ups

st.set_page_config(page_title="AI Career Agent", layout="wide", initial_sidebar_state="expanded")
load_environment()
store = JobStore()


def parse_json_list(value) -> list:
    if isinstance(value, list):
        return value
    if not value:
        return []
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, list) else []
    except json.JSONDecodeError:
        return []


def overview() -> None:
    stats = store.stats()
    st.title("Overview")
    cols = st.columns(8)
    cols[0].metric("Jobs found", stats["total_jobs"])
    cols[1].metric("New today", stats["new_today"])
    cols[2].metric("Excellent", stats.get("excellent_matches", 0))
    cols[3].metric("Good", stats.get("good_matches", 0))
    cols[4].metric("Shortlisted", stats.get("shortlisted", 0))
    cols[5].metric("Applied", stats["applications_submitted"])
    cols[6].metric("Interviews", stats["interviews"])
    cols[7].metric("Offers", stats.get("offers", 0))
    st.caption(f"Scheduler: {scheduler_status()} · Gemini: {'ready' if gemini_is_configured() else 'not configured'} · Telegram: {telegram_status()['ready']}")
    st.info("Local job monitoring only runs while the laptop and scheduler process stay on.")
    due = upcoming_follow_ups(store)
    if due:
        st.warning(f"{len(due)} follow-up reminder(s) are due.")
    recent = store.list_jobs()[:8]
    st.subheader("Latest stored jobs")
    if not recent:
        st.write("No jobs stored yet. Open Discover Jobs and run discovery.")
    for job in recent:
        st.markdown(
            f"**{job.get('title') or 'Untitled'}** · {job.get('company') or 'Unknown company'} · "
            f"{job.get('location') or 'location unknown'} · match {job.get('match_percent') if job.get('match_percent') is not None else 'n/a'}%"
        )
        if job.get("apply_url"):
            st.caption(job["apply_url"])
    st.subheader("Recent notifications")
    for row in store.list_notifications(limit=5):
        st.caption(f"{row.get('kind')} · {row.get('channel') or 'local'}")
        st.write((row.get("message") or "")[:240])


def discover() -> None:
    st.title("Discover Jobs")
    if st.button("Run discovery + matching now"):
        with st.spinner("Searching public feeds..."):
            result = run_discovery_and_match()
        st.success(
            f"Found {result['found']}. New {result['inserted']}. Duplicates {result['duplicates']}. "
            f"Telegram alerts sent: {result.get('notified', 0)}."
        )
        for item in result.get("notified_jobs") or []:
            st.markdown(f"- {item.get('title')} at {item.get('company')} · {item.get('apply_url')}")
        for note in result.get("notes") or []:
            st.info(note)
    jobs = store.list_jobs()[:25]
    st.write(f"Showing {len(jobs)} most recent stored jobs.")
    for job in jobs:
        st.markdown(f"**{job.get('title')}** · {job.get('company')} · {job.get('source')} · {job.get('grade') or '-'}")


def recommended() -> None:
    st.title("Recommended Jobs")
    search = st.text_input("Search")
    c1, c2, c3, c4 = st.columns(4)
    company = c1.text_input("Company")
    location = c2.text_input("Location")
    experience = c3.text_input("Experience")
    sort = c4.selectbox("Sort", ["match", "date", "company"])
    min_match = st.slider("Minimum match %", 0, 90, 40)
    jobs = store.list_jobs_filtered(search=search, company=company, location=location, min_match=min_match, experience=experience, sort=sort)
    if not jobs:
        st.write("No jobs matched these filters. Showing the latest stored jobs instead.")
        jobs = store.list_jobs()[:25]
    if not jobs:
        st.write("No jobs stored yet. Run Discover Jobs first.")
        return
    for job in jobs:
        with st.container(border=True):
            st.markdown(f"**{job.get('title')}** — {job.get('company')}")
            st.write(f"{job.get('location') or 'location unknown'} · Match {job.get('match_percent')}% · {job.get('grade')} · Posted {job.get('posted_at') or 'unverified'}")
            if job.get("apply_url"):
                st.link_button("Original listing", job["apply_url"])


def details() -> None:
    st.title("Job Details")
    jobs = store.list_jobs()
    if not jobs:
        st.write("No jobs stored.")
        return
    labels = {f"#{job['id']} {job.get('title')} — {job.get('company')}": job["id"] for job in jobs}
    job = store.get_job(labels[st.selectbox("Select a job", list(labels))])
    if not job:
        return
    st.header(job.get("title") or "")
    st.write(f"{job.get('company')} · {job.get('location')} · {job.get('salary') or 'salary not published'}")
    st.write(f"Match {job.get('match_percent')}% · {job.get('grade')} · Experience {job.get('experience') or 'not published'}")
    st.write(job.get("description") or "Not published.")
    st.write("Apply reasons: " + "; ".join(parse_json_list(job.get("reasons_apply"))))
    st.write("Skip reasons: " + "; ".join(parse_json_list(job.get("reasons_reject"))))
    if job.get("apply_url"):
        st.link_button("Application URL", job["apply_url"])


def resume_manager() -> None:
    st.title("Resume Manager")
    uploaded = st.file_uploader("Upload master resume (PDF or DOCX)", type=["pdf", "docx", "md", "txt"])
    if uploaded:
        dest = ROOT / "resumes" / "master" / uploaded.name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(uploaded.getvalue())
        parsed = parse_resume_file(dest)
        st.success("File stored. Extracted text only — nothing was invented.")
        st.json({k: v for k, v in parsed.items() if k != "raw_text"})
    jobs = store.list_jobs()
    if not jobs:
        return
    labels = {f"#{job['id']} {job.get('title')}": job["id"] for job in jobs}
    job = store.get_job(labels[st.selectbox("Tailor for job", list(labels))])
    if st.button("Generate tailored resume + cover letter"):
        result = save_tailored_documents(job, store=store)
        st.success("Saved Markdown/TXT/DOCX/PDF/LaTeX from approved facts only.")
        st.json({k: v for k, v in result.items() if v})


def ats() -> None:
    st.title("ATS Analyzer")
    jobs = store.list_jobs()
    if not jobs:
        return
    labels = {f"#{job['id']} {job.get('title')}": job["id"] for job in jobs}
    job = store.get_job(labels[st.selectbox("Analyze job", list(labels))])
    result = analyze_ats(job)
    st.metric("Token overlap", f"{result['coverage_percent']}%")
    st.write("Safe to emphasize:", ", ".join(result["safe_to_claim"]) or "none")
    st.write("Do not claim:", ", ".join(map(str, result["not_safe_to_claim"])) or "none")
    for change in result["changes_to_make"]:
        st.write("- " + change)


def assistant() -> None:
    st.title("Application Assistant")
    st.warning("Submit is blocked until you approve. CAPTCHA and login walls are not bypassed.")
    jobs = store.list_jobs()
    if not jobs:
        return
    labels = {f"#{job['id']} {job.get('title')} — {job.get('company')}": job["id"] for job in jobs}
    job_id = labels[st.selectbox("Job", list(labels))]
    if st.button("Create preview"):
        st.json(prepare_application(job_id))
    c1, c2 = st.columns(2)
    if c1.button("Approve"):
        st.success(set_application_approval(job_id, True))
    if c2.button("Deny"):
        st.warning(set_application_approval(job_id, False))
    st.caption(f"Open without submit: python -m job_agent open --job-id {job_id}")
    st.caption(f"Submit after approval: python -m job_agent submit --job-id {job_id}")


def tracker_page() -> None:
    st.title("Application Tracker")
    apps = store.list_applications()
    if apps:
        st.dataframe(apps, use_container_width=True)
    jobs = store.list_jobs()
    if not jobs:
        return
    labels = {f"#{job['id']} {job.get('title')}": job["id"] for job in jobs}
    job_id = labels[st.selectbox("Update status", list(labels))]
    status = st.selectbox("Status", STATUSES)
    notes = st.text_input("Notes")
    if st.button("Save status"):
        st.success(set_status(job_id, status, notes=notes, store=store))
    st.subheader("Follow-ups due")
    st.write(upcoming_follow_ups(store) or "None")


def interviews() -> None:
    st.title("Interview Tracker")
    jobs = store.list_jobs("jobs.status IN ('shortlisted', 'applied', 'interview') OR job_matches.match_percent >= 70")
    if not jobs:
        jobs = store.list_jobs()
    if not jobs:
        return
    labels = {f"#{job['id']} {job.get('title')}": job["id"] for job in jobs}
    job_id = labels[st.selectbox("Prepare for", list(labels))]
    if st.button("Generate practice questions"):
        st.json(save_prep(job_id, store=store))
    saved = store.get_interview(job_id)
    if saved:
        questions = json.loads(saved.get("questions_json") or "{}")
        st.write(questions)
        answer = st.text_area("Practice answer")
        question = st.text_input("Question you answered")
        if st.button("Evaluate answer") and question:
            st.json(evaluate_answer(question, answer))


def notifications() -> None:
    st.title("Notifications")
    st.write(telegram_status())
    for row in store.list_notifications():
        st.markdown(f"**{row.get('kind')}** · {row.get('created_at')} · {row.get('channel') or 'local'}")
        st.write(row.get("message"))


def settings() -> None:
    st.title("Settings")
    profile = load_profile()
    profile["full_name"] = st.text_input("Name", profile.get("full_name") or "")
    profile["email"] = st.text_input("Email", profile.get("email") or "")
    profile["phone"] = st.text_input("Phone", profile.get("phone") or "")
    profile["city"] = st.text_input("City", profile.get("city") or "")
    profile["expected_salary"] = st.text_input("Expected salary", profile.get("expected_salary") or "")
    education = profile.get("education") or {}
    education["degree"] = st.text_input("Education", education.get("degree") or "")
    education["graduation_year"] = st.number_input("Graduation year", value=int(education.get("graduation_year") or 2027), step=1)
    profile["education"] = education
    roles = st.text_area("Target roles", "\n".join(profile.get("target_roles") or []))
    skills = st.text_area("Skills", "\n".join(profile.get("skills") or []))
    locations = st.text_area("Preferred cities", "\n".join(profile.get("preferred_locations") or []))
    projects = st.text_area("Projects (one per line)", "\n".join(map(str, profile.get("projects") or [])))
    internships = st.text_area("Internships (one per line)", "\n".join(map(str, profile.get("internships") or [])))
    certs = st.text_area("Certifications (one per line)", "\n".join(map(str, profile.get("certifications") or [])))
    if st.button("Save profile"):
        profile["target_roles"] = [line.strip() for line in roles.splitlines() if line.strip()]
        profile["skills"] = [line.strip() for line in skills.splitlines() if line.strip()]
        profile["preferred_locations"] = [line.strip() for line in locations.splitlines() if line.strip()]
        profile["projects"] = [line.strip() for line in projects.splitlines() if line.strip()]
        profile["internships"] = [line.strip() for line in internships.splitlines() if line.strip()]
        profile["certifications"] = [line.strip() for line in certs.splitlines() if line.strip()]
        save_profile(profile)
        rewrite_master_resume_from_profile(profile)
        st.success("Saved. Empty personal fields stay empty.")
    st.write({"GEMINI": describe_secret("GEMINI_API_KEY"), **telegram_status()})
    st.json(load_schedule())
    st.caption("python -m job_agent.scheduler   (runs while this laptop stays on)")


page = st.sidebar.radio(
    "Pages",
    [
        "Overview",
        "Discover Jobs",
        "Recommended Jobs",
        "Job Details",
        "Resume Manager",
        "ATS Analyzer",
        "Application Assistant",
        "Application Tracker",
        "Interview Tracker",
        "Notifications",
        "Settings",
    ],
)
{
    "Overview": overview,
    "Discover Jobs": discover,
    "Recommended Jobs": recommended,
    "Job Details": details,
    "Resume Manager": resume_manager,
    "ATS Analyzer": ats,
    "Application Assistant": assistant,
    "Application Tracker": tracker_page,
    "Interview Tracker": interviews,
    "Notifications": notifications,
    "Settings": settings,
}[page]()
