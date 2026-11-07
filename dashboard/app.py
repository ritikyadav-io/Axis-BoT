from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st

from config import (
    describe_secret,
    gemini_api_key,
    gemini_model,
    groq_api_key,
    groq_model,
    is_configured,
    load_environment,
    openrouter_api_key,
    openrouter_chat_model,
    update_env_value,
)
from job_agent.application import prepare_application, set_application_approval
from job_agent.ats_analyzer import analyze_ats
from job_agent.config import load_profile, load_schedule, save_profile
from job_agent.database import JobStore
from job_agent.interview import evaluate_answer, generate_prep, save_prep
from job_agent.notifications import telegram_status
from job_agent.pipeline import run_discovery_and_match
from job_agent.resume_builder import rewrite_master_resume_from_profile, save_tailored_documents
from job_agent.resume_parser import parse_resume_file
from job_agent.scheduler import scheduler_status
from job_agent.tracker import STATUSES, set_status, upcoming_follow_ups

# Page setup
st.set_page_config(
    page_title="Axis-BoT Career & Automation Hub",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)
load_environment()
store = JobStore()

# Modern custom CSS styling
st.markdown(
    """
    <style>
    .main .block-container { padding-top: 1.5rem; padding-bottom: 2rem; }
    div[data-testid="metric-container"] {
        background: rgba(125, 125, 125, 0.08);
        border: 1px solid rgba(125, 125, 125, 0.18);
        padding: 0.75rem 1rem;
        border-radius: 10px;
    }
    .badge-excellent { background-color: #0f5132; color: #d1e7dd; padding: 2px 8px; border-radius: 4px; font-weight: 600; font-size: 0.85rem; }
    .badge-good { background-color: #084298; color: #cff4fc; padding: 2px 8px; border-radius: 4px; font-weight: 600; font-size: 0.85rem; }
    .badge-moderate { background-color: #664d03; color: #fff3cd; padding: 2px 8px; border-radius: 4px; font-weight: 600; font-size: 0.85rem; }
    .badge-low { background-color: #842029; color: #f8d7da; padding: 2px 8px; border-radius: 4px; font-weight: 600; font-size: 0.85rem; }
    .status-pill {
        display: inline-block;
        padding: 3px 10px;
        border-radius: 12px;
        font-size: 0.8rem;
        font-weight: 600;
        margin-right: 6px;
    }
    .pill-green { background-color: #198754; color: white; }
    .pill-blue { background-color: #0d6efd; color: white; }
    .pill-yellow { background-color: #ffc107; color: black; }
    .pill-gray { background-color: #6c757d; color: white; }
    </style>
    """,
    unsafe_allow_html=True,
)


def parse_json_list(value: Any) -> list:
    if isinstance(value, list):
        return value
    if not value:
        return []
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def format_grade_badge(grade: str | None) -> str:
    g = (grade or "").capitalize()
    if g == "Excellent":
        return '<span class="badge-excellent">🟢 Excellent</span>'
    if g == "Good":
        return '<span class="badge-good">🔵 Good</span>'
    if g == "Moderate":
        return '<span class="badge-moderate">🟡 Moderate</span>'
    return '<span class="badge-low">⚪ Low</span>'


def render_sidebar_status() -> None:
    st.sidebar.markdown("### ⚡ System Status")
    groq_ok = is_configured("GROQ_API_KEY")
    or_ok = is_configured("OPENROUTER_API_KEY")
    gem_ok = is_configured("GEMINI_API_KEY") or is_configured("GOOGLE_API_KEY")

    st.sidebar.markdown(
        f"""
        <div style="font-size: 0.85rem; line-height: 1.6; margin-bottom: 1rem;">
        <div><b>1. Groq (Primary):</b> {'🟢 Active' if groq_ok else '🔴 Missing'}</div>
        <div><b>2. OpenRouter (FB 1):</b> {'🟢 Active' if or_ok else '⚪ Off'}</div>
        <div><b>3. Gemini (FB 2):</b> {'🟢 Active' if gem_ok else '⚪ Off'}</div>
        <div><b>Scheduler:</b> {scheduler_status()}</div>
        <div><b>Telegram:</b> {'🟢 Ready' if telegram_status().get('ready') == 'yes' else '⚪ Not configured'}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ---------------- PAGE HANDLERS ---------------- #


def overview() -> None:
    st.title("📊 Overview & Dashboard")

    try:
        stats = store.stats()
    except Exception as e:
        st.error(f"Failed to load stats: {e}")
        stats = {"total_jobs": 0, "new_today": 0, "applications_submitted": 0, "interviews": 0}

    # Grid 1: Match & Ingestion Stats
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Jobs Found", stats.get("total_jobs", 0))
    c2.metric("New Today", stats.get("new_today", 0))
    c3.metric("Excellent Matches", stats.get("excellent_matches", 0))
    c4.metric("Good Matches", stats.get("good_matches", 0))

    # Grid 2: Pipeline & Status
    c5, c6, c7, c8 = st.columns(4)
    c5.metric("Shortlisted", stats.get("shortlisted", 0))
    c6.metric("Applications Submitted", stats.get("applications_submitted", 0))
    c7.metric("Interviews", stats.get("interviews", 0))
    c8.metric("Offers", stats.get("offers", 0))

    st.divider()

    # System status notification banner
    active_providers = []
    if is_configured("GROQ_API_KEY"):
        active_providers.append("Groq (1st)")
    if is_configured("OPENROUTER_API_KEY"):
        active_providers.append("OpenRouter (2nd)")
    if is_configured("GEMINI_API_KEY") or is_configured("GOOGLE_API_KEY"):
        active_providers.append("Gemini (3rd)")

    provider_summary = " ➔ ".join(active_providers) if active_providers else "None configured"
    st.info(f"**Multi-Tier Engine**: {provider_summary} · Seamless zero-error fallback active.")

    try:
        due = upcoming_follow_ups(store)
        if due:
            st.warning(f"🔔 **{len(due)} follow-up reminder(s) are due.** Check Application Tracker.")
    except Exception:
        pass

    col_jobs, col_notifs = st.columns([3, 2])

    with col_jobs:
        st.subheader("📌 Latest Stored Jobs")
        try:
            recent = store.list_jobs()[:8]
        except Exception as e:
            recent = []
            st.error(f"Error fetching jobs: {e}")

        if not recent:
            st.info("No jobs stored yet. Go to **Discover Jobs** and run automated search.")
        for job in recent:
            with st.container(border=True):
                title = job.get("title") or "Untitled Role"
                comp = job.get("company") or "Unknown Company"
                loc = job.get("location") or "Location not specified"
                pct = job.get("match_percent")
                match_txt = f"{pct}%" if pct is not None else "N/A"
                grade_html = format_grade_badge(job.get("grade"))

                st.markdown(f"**{title}** — *{comp}* · {grade_html}", unsafe_allow_html=True)
                st.caption(f"📍 {loc} · Match Score: **{match_txt}**")
                if job.get("apply_url"):
                    st.link_button("View / Apply", job["apply_url"], key=f"ov_btn_{job.get('id')}")

    with col_notifs:
        st.subheader("🔔 Recent Notifications")
        try:
            notifs = store.list_notifications(limit=6)
        except Exception as e:
            notifs = []
            st.error(f"Error loading notifications: {e}")

        if not notifs:
            st.caption("No alerts sent yet.")
        for row in notifs:
            with st.container(border=True):
                st.markdown(f"**{row.get('kind', 'Alert').title()}** · <small>{row.get('created_at', '')}</small>", unsafe_allow_html=True)
                st.write((row.get("message") or "")[:200])


def discover() -> None:
    st.title("🔎 Discover & Match Jobs")
    st.markdown("Run automated searches across RSS, careers boards, and feeds with multi-provider intelligent ranking.")

    if st.button("🚀 Run Discovery + Matching Now", type="primary", key="btn_run_discovery"):
        with st.spinner("Executing job ingestion and multi-tier scoring (Groq ➔ OpenRouter ➔ Gemini)..."):
            try:
                res = run_discovery_and_match()
                st.session_state["discovery_result"] = res
                st.success(
                    f"Found {res.get('found', 0)} jobs. Newly inserted: {res.get('inserted', 0)}. "
                    f"Duplicates: {res.get('duplicates', 0)}. Alerts sent: {res.get('notified', 0)}."
                )
            except Exception as e:
                st.error(f"Discovery error: {e}")

    cached_res = st.session_state.get("discovery_result")
    if cached_res:
        with st.expander("Discovery Execution Details", expanded=True):
            st.json(cached_res)

    st.divider()
    st.subheader("Recent Ingested Jobs")
    try:
        jobs = store.list_jobs()[:30]
    except Exception as e:
        st.error(f"Failed to list jobs: {e}")
        jobs = []

    st.write(f"Displaying {len(jobs)} most recent listings.")
    for j in jobs:
        with st.container(border=True):
            cols = st.columns([3, 1, 1])
            with cols[0]:
                st.markdown(f"**{j.get('title', 'Untitled')}** · {j.get('company', 'Unknown')}")
                st.caption(f"Source: {j.get('source', 'feed')} · Location: {j.get('location', 'N/A')}")
            with cols[1]:
                st.markdown(format_grade_badge(j.get("grade")), unsafe_allow_html=True)
                st.caption(f"Match: {j.get('match_percent', 0)}%")
            with cols[2]:
                if j.get("apply_url"):
                    st.link_button("Open URL", j["apply_url"], key=f"disc_link_{j.get('id')}")


def recommended() -> None:
    st.title("⭐ Recommended Jobs")
    c_search, c_sort, c_match = st.columns([2, 1, 1])
    search = c_search.text_input("Filter by keywords / skills", key="rec_search")
    sort = c_sort.selectbox("Sort by", ["match", "date", "company"], key="rec_sort")
    min_match = c_match.slider("Minimum match %", 0, 100, 35, key="rec_min_match")

    c1, c2, c3 = st.columns(3)
    company = c1.text_input("Company", key="rec_comp")
    location = c2.text_input("Location", key="rec_loc")
    experience = c3.text_input("Experience filter", key="rec_exp")

    try:
        jobs = store.list_jobs_filtered(
            search=search,
            company=company,
            location=location,
            min_match=min_match,
            experience=experience,
            sort=sort,
        )
    except Exception as e:
        st.error(f"Error filtering jobs: {e}")
        jobs = []

    if not jobs:
        st.info("No jobs match the current filters.")
        return

    st.markdown(f"**Found {len(jobs)} matches:**")
    for job in jobs:
        with st.container(border=True):
            col_main, col_badge = st.columns([4, 1])
            with col_main:
                st.markdown(f"### {job.get('title', 'Untitled')}")
                st.markdown(f"**{job.get('company', 'Unknown')}** · 📍 {job.get('location', 'Unknown location')}")
                st.caption(f"Salary: {job.get('salary') or 'Not published'} · Experience: {job.get('experience') or 'Fresher / Entry'}")
            with col_badge:
                st.markdown(format_grade_badge(job.get("grade")), unsafe_allow_html=True)
                st.markdown(f"### {job.get('match_percent', 0)}%")

            desc = (job.get("description") or "").strip()
            if desc:
                with st.expander("Job Description Snippet"):
                    st.write(desc[:800] + ("..." if len(desc) > 800 else ""))

            c_act1, c_act2 = st.columns([1, 4])
            with c_act1:
                if job.get("apply_url"):
                    st.link_button("Apply Listing", job["apply_url"], key=f"rec_apply_{job.get('id')}")
            with c_act2:
                reasons = parse_json_list(job.get("reasons_apply"))
                if reasons:
                    st.caption("✅ " + " | ".join(reasons[:3]))


def details() -> None:
    st.title("📄 Job Details & Deep Inspection")
    try:
        jobs = store.list_jobs()
    except Exception as e:
        st.error(f"Error fetching jobs: {e}")
        return

    if not jobs:
        st.info("No jobs stored yet.")
        return

    labels = {f"#{j['id']} - {j.get('title', 'Untitled')} ({j.get('company', 'Unknown')})": j["id"] for j in jobs}
    sel = st.selectbox("Select a Job to Inspect", list(labels.keys()), key="details_sel")
    job_id = labels[sel]
    job = store.get_job(job_id)
    if not job:
        st.error("Job details could not be retrieved.")
        return

    c_left, c_right = st.columns([2, 1])
    with c_left:
        st.subheader(job.get("title") or "Untitled")
        st.markdown(f"**Company**: {job.get('company')} · **Location**: {job.get('location')}")
        st.markdown(f"**Salary**: {job.get('salary') or 'Not disclosed'}")
        st.markdown(f"**Experience Requirement**: {job.get('experience') or 'Not specified'}")
    with c_right:
        st.markdown(format_grade_badge(job.get("grade")), unsafe_allow_html=True)
        st.metric("Overall Match", f"{job.get('match_percent', 0)}%")
        st.caption(f"Scoring Engine: `{job.get('method', 'heuristic')}`")

    st.divider()

    c_skills1, c_skills2 = st.columns(2)
    with c_skills1:
        st.markdown("#### ✅ Matching / Approved Skills")
        possessed = parse_json_list(job.get("possessed_skills"))
        if possessed:
            st.success(", ".join(map(str, possessed)))
        else:
            st.write("No direct keyword match.")

    with c_skills2:
        st.markdown("#### ⚠️ Missing / Desired Skills")
        missing = parse_json_list(job.get("missing_skills"))
        if missing:
            st.warning(", ".join(map(str, missing)))
        else:
            st.write("None missing.")

    st.markdown("#### Full Job Description")
    st.text_area("Description Text", job.get("description") or "No description provided.", height=250, key="details_desc_box")

    if job.get("apply_url"):
        st.link_button("🌐 Open Job Application URL", job["apply_url"], key="details_btn_url")


def resume_manager() -> None:
    st.title("📑 Resume Manager & Tailoring")

    with st.expander("📤 Upload & Parse Master Resume (PDF, DOCX, MD, TXT)", expanded=False):
        uploaded = st.file_uploader("Upload resume file", type=["pdf", "docx", "md", "txt"], key="resume_uploader")
        if uploaded:
            dest = ROOT / "resumes" / "master" / uploaded.name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(uploaded.getvalue())
            try:
                parsed = parse_resume_file(dest)
                st.success("Resume parsed successfully. Facts grounded strictly from document.")
                st.json({k: v for k, v in parsed.items() if k != "raw_text"})
            except Exception as e:
                st.error(f"Error parsing resume: {e}")

    st.divider()
    st.subheader("🎯 Tailor Resume for a Specific Role")
    try:
        jobs = store.list_jobs()
    except Exception:
        jobs = []

    if not jobs:
        st.info("No jobs available for tailoring.")
        return

    labels = {f"#{j['id']} - {j.get('title', 'Untitled')} @ {j.get('company', 'Unknown')[:30]}": j["id"] for j in jobs}
    sel_job = st.selectbox("Select Target Job", list(labels.keys()), key="resume_job_sel")
    target_job = store.get_job(labels[sel_job])

    if st.button("✨ Generate Tailored Resume + Cover Letter", type="primary", key="btn_tailor"):
        with st.spinner("Synthesizing customized documents using approved profile facts..."):
            try:
                res = save_tailored_documents(target_job, store=store)
                st.session_state["tailored_result"] = res
                st.success("Generated tailored documents (Markdown, TXT, DOCX, LaTeX).")
            except Exception as e:
                st.error(f"Generation error: {e}")

    tailored_res = st.session_state.get("tailored_result")
    if tailored_res:
        st.markdown("### Generated Files")
        st.json({k: v for k, v in tailored_res.items() if v})


def ats() -> None:
    st.title("🎯 ATS Keyword & Fit Analyzer")
    try:
        jobs = store.list_jobs()
    except Exception:
        jobs = []

    if not jobs:
        st.info("No jobs available.")
        return

    labels = {f"#{j['id']} - {j.get('title', 'Untitled')} @ {j.get('company', 'Unknown')[:30]}": j["id"] for j in jobs}
    sel_job = st.selectbox("Select Role to Analyze", list(labels.keys()), key="ats_job_sel")
    job = store.get_job(labels[sel_job])

    if st.button("🔍 Run ATS Diagnostic", type="primary", key="btn_run_ats"):
        with st.spinner("Evaluating keyword density, requirements, and profile coverage..."):
            try:
                res = analyze_ats(job)
                st.session_state["ats_result"] = res
            except Exception as e:
                st.error(f"ATS analysis error: {e}")

    result = st.session_state.get("ats_result")
    if result:
        st.metric("ATS Token Overlap Score", f"{result.get('coverage_percent', 0)}%")
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("##### Safe to Emphasize")
            safe = result.get("safe_to_claim") or []
            st.success(", ".join(map(str, safe)) if safe else "None identified")
        with c2:
            st.markdown("##### Do Not Claim (Missing Facts)")
            not_safe = result.get("not_safe_to_claim") or []
            st.error(", ".join(map(str, not_safe)) if not_safe else "None")

        st.markdown("##### Recommended Optimizations")
        for ch in result.get("changes_to_make", []):
            st.markdown(f"- {ch}")


def assistant() -> None:
    st.title("🤖 Application Assistant & Browser Dispatch")
    st.warning("⚠️ **Safety Guarantee**: Final submission is blocked until you review and approve. Never bypasses logins/CAPTCHAs.")

    try:
        jobs = store.list_jobs()
    except Exception:
        jobs = []

    if not jobs:
        st.info("No jobs available.")
        return

    labels = {f"#{j['id']} - {j.get('title', 'Untitled')} @ {j.get('company', 'Unknown')[:30]}": j["id"] for j in jobs}
    job_id = labels[st.selectbox("Select Job to Prepare", list(labels.keys()), key="asst_job_sel")]

    col_btn1, col_btn2, col_btn3 = st.columns(3)
    if col_btn1.button("📋 Prepare Application Preview", key="btn_preview"):
        try:
            prev = prepare_application(job_id)
            st.session_state["app_preview"] = prev
        except Exception as e:
            st.error(f"Preparation failed: {e}")

    if col_btn2.button("✅ Approve for Submission", key="btn_approve"):
        try:
            msg = set_application_approval(job_id, True)
            st.success(msg)
        except Exception as e:
            st.error(f"Error: {e}")

    if col_btn3.button("🚫 Deny / Reset Approval", key="btn_deny"):
        try:
            msg = set_application_approval(job_id, False)
            st.warning(msg)
        except Exception as e:
            st.error(f"Error: {e}")

    preview = st.session_state.get("app_preview")
    if preview:
        st.subheader("Application Package Preview")
        st.json(preview)

    st.divider()
    st.markdown("##### CLI Execution Commands")
    st.code(f"python -m job_agent open --job-id {job_id}", language="bash")
    st.code(f"python -m job_agent submit --job-id {job_id}", language="bash")


def tracker_page() -> None:
    st.title("📌 Application Tracker & Follow-Ups")
    try:
        apps = store.list_applications()
        if apps:
            st.dataframe(apps, use_container_width=True)
        else:
            st.caption("No application records logged yet.")
    except Exception as e:
        st.error(f"Error loading applications: {e}")

    st.divider()
    st.subheader("Update Job Status")
    try:
        jobs = store.list_jobs()
    except Exception:
        jobs = []

    if jobs:
        labels = {f"#{j['id']} - {j.get('title', 'Untitled')}": j["id"] for j in jobs}
        c1, c2, c3 = st.columns([2, 1, 1])
        job_id = labels[c1.selectbox("Select Job", list(labels.keys()), key="trk_job_sel")]
        status = c2.selectbox("New Status", STATUSES, key="trk_status_sel")
        notes = c3.text_input("Status Notes", key="trk_notes_input")

        if st.button("💾 Save Status Update", key="btn_save_status"):
            try:
                res = set_status(job_id, status, notes=notes, store=store)
                st.success(res)
            except Exception as e:
                st.error(f"Update failed: {e}")

    st.subheader("Upcoming Follow-Ups Due")
    try:
        due = upcoming_follow_ups(store)
        st.write(due if due else "No immediate follow-ups scheduled.")
    except Exception as e:
        st.caption(f"Notice: {e}")


def interviews() -> None:
    st.title("🎙️ Interview Preparation & Mock Q&A")
    try:
        jobs = store.list_jobs("jobs.status IN ('shortlisted', 'applied', 'interview') OR job_matches.match_percent >= 70")
        if not jobs:
            jobs = store.list_jobs()
    except Exception:
        jobs = []

    if not jobs:
        st.info("No jobs available for interview prep.")
        return

    labels = {f"#{j['id']} - {j.get('title', 'Untitled')}": j["id"] for j in jobs}
    job_id = labels[st.selectbox("Select Target Interview", list(labels.keys()), key="prep_job_sel")]

    if st.button("⚡ Generate Practice Questions", type="primary", key="btn_gen_questions"):
        with st.spinner("Synthesizing technical, coding, aptitude, and behavioral questions..."):
            try:
                prep_result = save_prep(job_id, store=store)
                st.session_state["interview_prep"] = prep_result
                st.success("Questions generated successfully.")
            except Exception as e:
                st.error(f"Failed to generate questions: {e}")

    saved = store.get_interview(job_id)
    if saved:
        try:
            questions = json.loads(saved.get("questions_json") or "{}")
            with st.expander("Practice Questions List", expanded=True):
                st.json(questions)
        except Exception:
            pass

    st.divider()
    st.subheader("Interactive Answer Evaluation")
    q_answered = st.text_input("Question to evaluate", placeholder="e.g. Explain Python lists versus tuples", key="prep_eval_q")
    ans_text = st.text_area("Your proposed answer", height=120, key="prep_eval_ans")

    if st.button("Evaluate My Answer", key="btn_eval_ans"):
        if not q_answered or not ans_text:
            st.warning("Please provide both the question and your answer.")
        else:
            with st.spinner("Analyzing answer factual accuracy and relevance..."):
                try:
                    eval_res = evaluate_answer(q_answered, ans_text)
                    st.json(eval_res)
                except Exception as e:
                    st.error(f"Evaluation error: {e}")


def notifications() -> None:
    st.title("🔔 Notifications & Alert Feed")
    st.markdown("Review Telegram delivery status and recent alert logs.")
    st.json(telegram_status())

    try:
        notifs = store.list_notifications()
        if not notifs:
            st.caption("No notifications stored.")
        for row in notifs:
            with st.container(border=True):
                st.markdown(f"**{row.get('kind', 'Alert')}** · {row.get('created_at')} · `{row.get('channel') or 'local'}`")
                st.write(row.get("message"))
    except Exception as e:
        st.error(f"Error loading notifications: {e}")


def settings() -> None:
    st.title("⚙️ Settings & API Configuration")

    tab_profile, tab_llm, tab_automation = st.tabs(["Candidate Profile", "LLM & Keys", "Automation Schedule"])

    with tab_profile:
        profile = load_profile()
        c_p1, c_p2 = st.columns(2)
        profile["full_name"] = c_p1.text_input("Full Name", profile.get("full_name") or "", key="prof_name")
        profile["email"] = c_p2.text_input("Email", profile.get("email") or "", key="prof_email")

        c_p3, c_p4 = st.columns(2)
        profile["phone"] = c_p3.text_input("Phone Number", profile.get("phone") or "", key="prof_phone")
        profile["city"] = c_p4.text_input("Current City", profile.get("city") or "", key="prof_city")

        profile["expected_salary"] = st.text_input("Expected Salary (optional)", profile.get("expected_salary") or "", key="prof_sal")

        education = profile.get("education") or {}
        c_ed1, c_ed2 = st.columns(2)
        education["degree"] = c_ed1.text_input("Degree / Program", education.get("degree") or "", key="prof_degree")
        education["graduation_year"] = c_ed2.number_input("Graduation Year", value=int(education.get("graduation_year") or 2027), step=1, key="prof_grad")
        profile["education"] = education

        roles = st.text_area("Target Roles (one per line)", "\n".join(profile.get("target_roles") or []), key="prof_roles")
        skills = st.text_area("Technical Skills (one per line)", "\n".join(profile.get("skills") or []), key="prof_skills")
        locations = st.text_area("Preferred Locations (one per line)", "\n".join(profile.get("preferred_locations") or []), key="prof_locs")

        if st.button("💾 Save Candidate Profile", type="primary", key="btn_save_prof"):
            profile["target_roles"] = [l.strip() for l in roles.splitlines() if l.strip()]
            profile["skills"] = [l.strip() for l in skills.splitlines() if l.strip()]
            profile["preferred_locations"] = [l.strip() for l in locations.splitlines() if l.strip()]
            try:
                save_profile(profile)
                rewrite_master_resume_from_profile(profile)
                st.success("Profile saved and master resume updated successfully.")
            except Exception as e:
                st.error(f"Failed to save profile: {e}")

    with tab_llm:
        st.subheader("Multi-Provider Fallback Configuration")
        st.markdown(
            """
            The agent prioritizes **Groq** (1st, sub-second speed), falls back to **OpenRouter** (2nd), and then **Gemini** (3rd).
            """
        )

        with st.form("llm_keys_form"):
            groq_k = st.text_input("Groq API Key (1st priority)", value=groq_api_key(), type="password", key="form_groq_key")
            groq_m = st.text_input("Groq Model", value=groq_model(), key="form_groq_mod")

            or_k = st.text_input("OpenRouter API Key (2nd priority)", value=openrouter_api_key(), type="password", key="form_or_key")
            or_m = st.text_input("OpenRouter Model", value=openrouter_chat_model(), key="form_or_mod")

            gem_k = st.text_input("Gemini API Key (3rd priority)", value=gemini_api_key(), type="password", key="form_gem_key")
            gem_m = st.text_input("Gemini Model", value=gemini_model(), key="form_gem_mod")

            submitted = st.form_submit_button("Update Keys in .env")
            if submitted:
                if groq_k:
                    update_env_value("GROQ_API_KEY", groq_k)
                if groq_m:
                    update_env_value("GROQ_MODEL", groq_m)
                if or_k:
                    update_env_value("OPENROUTER_API_KEY", or_k)
                if or_m:
                    update_env_value("OPENROUTER_MODEL", or_m)
                if gem_k:
                    update_env_value("GEMINI_API_KEY", gem_k)
                    update_env_value("GOOGLE_API_KEY", gem_k)
                if gem_m:
                    update_env_value("GEMINI_MODEL", gem_m)
                st.success("API keys and models successfully saved to .env!")

        st.divider()
        st.markdown("#### Live Connectivity Check")
        if st.button("🧪 Test All Providers Live", key="btn_test_providers"):
            with st.spinner("Testing API connections..."):
                # Test Groq
                if is_configured("GROQ_API_KEY"):
                    try:
                        from groq import Groq
                        client = Groq(api_key=groq_api_key(), timeout=10.0)
                        resp = client.chat.completions.create(
                            model=groq_model(),
                            messages=[{"role": "user", "content": "hi"}],
                            max_tokens=10,
                        )
                        st.success(f"✅ **Groq**: Connected successfully! (Model: `{groq_model()}`)")
                    except Exception as e:
                        st.error(f"❌ **Groq failed**: {e}")
                else:
                    st.warning("⚪ **Groq**: Key not configured.")

                # Test OpenRouter
                if is_configured("OPENROUTER_API_KEY"):
                    try:
                        import httpx
                        r = httpx.get("https://openrouter.ai/api/v1/key", headers={"Authorization": f"Bearer {openrouter_api_key()}"}, timeout=10.0)
                        if r.status_code == 200:
                            st.success(f"✅ **OpenRouter**: Key validated! (Model: `{openrouter_chat_model()}`)")
                        else:
                            st.error(f"❌ **OpenRouter returned status {r.status_code}**: {r.text}")
                    except Exception as e:
                        st.error(f"❌ **OpenRouter check failed**: {e}")
                else:
                    st.caption("⚪ **OpenRouter**: Not configured.")

                # Test Gemini
                if is_configured("GEMINI_API_KEY") or is_configured("GOOGLE_API_KEY"):
                    try:
                        from google import genai
                        c = genai.Client(api_key=gemini_api_key())
                        c.models.generate_content(model=gemini_model(), contents="hi")
                        st.success(f"✅ **Gemini**: Connected successfully! (Model: `{gemini_model()}`)")
                    except Exception as e:
                        st.error(f"❌ **Gemini failed**: {e}")
                else:
                    st.caption("⚪ **Gemini**: Not configured.")

    with tab_automation:
        st.subheader("Local Automation Schedule")
        st.json(load_schedule())
        st.caption("To run background automation daemon: `python -m job_agent.scheduler`")


# Render sidebar and execute route
render_sidebar_status()

page = st.sidebar.radio(
    "Navigation",
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
    key="nav_page_selection",
)

routes = {
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
}

if page in routes:
    routes[page]()
