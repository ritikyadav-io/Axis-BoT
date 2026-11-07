from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from job_agent.paths import DB_PATH, ensure_runtime_dirs

SCHEMA = """
CREATE TABLE IF NOT EXISTS companies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    website TEXT,
    notes TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fingerprint TEXT NOT NULL UNIQUE,
    source TEXT NOT NULL,
    title TEXT NOT NULL,
    company TEXT NOT NULL,
    location TEXT,
    salary TEXT,
    experience TEXT,
    description TEXT,
    required_skills TEXT,
    posted_at TEXT,
    deadline TEXT,
    apply_url TEXT,
    raw_json TEXT,
    status TEXT NOT NULL DEFAULT 'discovered',
    discovered_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    last_notified_at TEXT
);

CREATE TABLE IF NOT EXISTS job_matches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL UNIQUE,
    match_percent INTEGER NOT NULL,
    grade TEXT NOT NULL,
    required_skills TEXT,
    possessed_skills TEXT,
    missing_skills TEXT,
    experience_eligible TEXT,
    location_compatible INTEGER,
    priority TEXT,
    reasons_apply TEXT,
    reasons_reject TEXT,
    analysis_json TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(job_id) REFERENCES jobs(id)
);

CREATE TABLE IF NOT EXISTS tailored_resumes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL,
    resume_path TEXT NOT NULL,
    cover_letter_path TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(job_id) REFERENCES jobs(id)
);

CREATE TABLE IF NOT EXISTS applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL UNIQUE,
    status TEXT NOT NULL,
    preview_json TEXT,
    approved_at TEXT,
    submitted_at TEXT,
    notes TEXT,
    tailored_resume_id INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(job_id) REFERENCES jobs(id)
);

CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    job_id INTEGER,
    message TEXT NOT NULL,
    channel TEXT,
    created_at TEXT NOT NULL,
    sent_at TEXT,
    FOREIGN KEY(job_id) REFERENCES jobs(id)
);

CREATE TABLE IF NOT EXISTS search_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    query TEXT NOT NULL,
    source TEXT NOT NULL,
    results_count INTEGER NOT NULL DEFAULT 0,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS interviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL UNIQUE,
    questions_json TEXT,
    answers_json TEXT,
    evaluation_json TEXT,
    gaps_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(job_id) REFERENCES jobs(id)
);
"""

MIGRATIONS = (
    ("jobs", "posted_verified", "INTEGER DEFAULT 0"),
    ("applications", "follow_up_at", "TEXT"),
    ("applications", "resume_version", "TEXT"),
    ("job_matches", "education_eligible", "TEXT"),
)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class JobStore:
    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = Path(db_path) if db_path else DB_PATH
        ensure_runtime_dirs()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript(SCHEMA)
            self._migrate(conn)

    def _migrate(self, conn: sqlite3.Connection) -> None:
        for table, column, ddl in MIGRATIONS:
            cols = [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]
            if column not in cols:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def upsert_company(self, name: str, website: str | None = None) -> None:
        if not name:
            return
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO companies (name, website, notes, created_at)
                VALUES (?, ?, '', ?)
                ON CONFLICT(name) DO UPDATE SET website=COALESCE(excluded.website, companies.website)
                """,
                (name.strip(), website, utc_now()),
            )

    def upsert_job(self, job: dict[str, Any]) -> tuple[int, bool, bool]:
        """Insert or refresh a job.

        Returns (job_id, is_new, status_changed).
        """
        fingerprint = job["fingerprint"]
        now = utc_now()
        self.upsert_company(job.get("company") or "Unknown")
        with self.connect() as conn:
            existing = conn.execute("SELECT * FROM jobs WHERE fingerprint = ?", (fingerprint,)).fetchone()
            payload = (
                fingerprint,
                job.get("source") or "unknown",
                job.get("title") or "Untitled",
                job.get("company") or "Unknown",
                job.get("location"),
                job.get("salary"),
                job.get("experience"),
                job.get("description"),
                json.dumps(job.get("required_skills") or [], ensure_ascii=False),
                job.get("posted_at"),
                job.get("deadline"),
                job.get("apply_url"),
                json.dumps(job, ensure_ascii=False, default=str),
                now,
                now,
            )
            if existing is None:
                cursor = conn.execute(
                    """
                    INSERT INTO jobs (
                        fingerprint, source, title, company, location, salary, experience,
                        description, required_skills, posted_at, deadline, apply_url, raw_json,
                        status, discovered_at, last_seen_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'discovered', ?, ?)
                    """,
                    payload,
                )
                return int(cursor.lastrowid), True, False

            changed = any(
                (existing[field] or "") != (job.get(field) or "")
                for field in ("title", "salary", "deadline", "apply_url", "status")
            )
            conn.execute(
                """
                UPDATE jobs SET
                    source=?, title=?, company=?, location=?, salary=?, experience=?,
                    description=?, required_skills=?, posted_at=?, deadline=?, apply_url=?,
                    raw_json=?, last_seen_at=?
                WHERE id=?
                """,
                (
                    job.get("source") or existing["source"],
                    job.get("title") or existing["title"],
                    job.get("company") or existing["company"],
                    job.get("location"),
                    job.get("salary"),
                    job.get("experience"),
                    job.get("description"),
                    json.dumps(job.get("required_skills") or json.loads(existing["required_skills"] or "[]"), ensure_ascii=False),
                    job.get("posted_at"),
                    job.get("deadline"),
                    job.get("apply_url"),
                    json.dumps(job, ensure_ascii=False, default=str),
                    now,
                    existing["id"],
                ),
            )
            return int(existing["id"]), False, changed

    def save_match(self, job_id: int, match: dict[str, Any]) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO job_matches (
                    job_id, match_percent, grade, required_skills, possessed_skills, missing_skills,
                    experience_eligible, education_eligible, location_compatible, priority, reasons_apply, reasons_reject,
                    analysis_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(job_id) DO UPDATE SET
                    match_percent=excluded.match_percent,
                    grade=excluded.grade,
                    required_skills=excluded.required_skills,
                    possessed_skills=excluded.possessed_skills,
                    missing_skills=excluded.missing_skills,
                    experience_eligible=excluded.experience_eligible,
                    education_eligible=excluded.education_eligible,
                    location_compatible=excluded.location_compatible,
                    priority=excluded.priority,
                    reasons_apply=excluded.reasons_apply,
                    reasons_reject=excluded.reasons_reject,
                    analysis_json=excluded.analysis_json,
                    created_at=excluded.created_at
                """,
                (
                    job_id,
                    int(match.get("match_percent") or 0),
                    match.get("grade") or "C",
                    json.dumps(match.get("required_skills") or [], ensure_ascii=False),
                    json.dumps(match.get("possessed_skills") or [], ensure_ascii=False),
                    json.dumps(match.get("missing_skills") or [], ensure_ascii=False),
                    match.get("experience_eligible"),
                    match.get("education_eligible"),
                    1 if match.get("location_compatible") else 0,
                    match.get("priority"),
                    json.dumps(match.get("reasons_apply") or [], ensure_ascii=False),
                    json.dumps(match.get("reasons_reject") or [], ensure_ascii=False),
                    json.dumps(match, ensure_ascii=False),
                    utc_now(),
                ),
            )

    def save_tailored_resume(self, job_id: int, resume_path: str, cover_letter_path: str | None) -> int:
        with self.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO tailored_resumes (job_id, resume_path, cover_letter_path, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (job_id, resume_path, cover_letter_path, utc_now()),
            )
            return int(cursor.lastrowid)

    def upsert_application(self, job_id: int, **fields: Any) -> int:
        now = utc_now()
        with self.connect() as conn:
            existing = conn.execute("SELECT id FROM applications WHERE job_id = ?", (job_id,)).fetchone()
            if existing is None:
                cursor = conn.execute(
                    """
                    INSERT INTO applications (job_id, status, preview_json, approved_at, submitted_at, notes, tailored_resume_id, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        job_id,
                        fields.get("status") or "draft",
                        fields.get("preview_json"),
                        fields.get("approved_at"),
                        fields.get("submitted_at"),
                        fields.get("notes"),
                        fields.get("tailored_resume_id"),
                        now,
                        now,
                    ),
                )
                return int(cursor.lastrowid)
            assignments = ["updated_at = ?"]
            values: list[Any] = [now]
            for key in ("status", "preview_json", "approved_at", "submitted_at", "notes", "tailored_resume_id", "follow_up_at", "resume_version"):
                if key in fields:
                    assignments.append(f"{key} = ?")
                    values.append(fields[key])
            values.append(existing["id"])
            conn.execute(f"UPDATE applications SET {', '.join(assignments)} WHERE id = ?", values)
            return int(existing["id"])

    def add_notification(self, kind: str, message: str, job_id: int | None = None, channel: str | None = None, sent: bool = False) -> int:
        now = utc_now()
        with self.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO notifications (kind, job_id, message, channel, created_at, sent_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (kind, job_id, message, channel, now, now if sent else None),
            )
            return int(cursor.lastrowid)

    def mark_job_notified(self, job_id: int) -> None:
        with self.connect() as conn:
            conn.execute("UPDATE jobs SET last_notified_at = ? WHERE id = ?", (utc_now(), job_id))

    def add_search_history(self, query: str, source: str, results_count: int, notes: str = "") -> None:
        now = utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO search_history (query, source, results_count, started_at, finished_at, notes)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (query, source, results_count, now, now, notes),
            )

    def set_job_status(self, job_id: int, status: str) -> None:
        with self.connect() as conn:
            conn.execute("UPDATE jobs SET status = ? WHERE id = ?", (status, job_id))

    def get_job(self, job_id: int) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT jobs.*, job_matches.match_percent, job_matches.grade, job_matches.priority,
                       job_matches.possessed_skills AS match_possessed, job_matches.missing_skills AS match_missing,
                       job_matches.reasons_apply, job_matches.reasons_reject, job_matches.experience_eligible,
                       job_matches.location_compatible, applications.status AS application_status,
                       applications.approved_at, applications.submitted_at
                FROM jobs
                LEFT JOIN job_matches ON job_matches.job_id = jobs.id
                LEFT JOIN applications ON applications.job_id = jobs.id
                WHERE jobs.id = ?
                """,
                (job_id,),
            ).fetchone()
        return dict(row) if row else None

    def list_jobs(self, where: str = "1=1", params: tuple[Any, ...] = (), order_by: str = "jobs.discovered_at DESC, jobs.id DESC") -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT jobs.*, job_matches.match_percent, job_matches.grade, job_matches.priority,
                       applications.status AS application_status
                FROM jobs
                LEFT JOIN job_matches ON job_matches.job_id = jobs.id
                LEFT JOIN applications ON applications.job_id = jobs.id
                WHERE {where}
                ORDER BY {order_by}
                """,
                params,
            ).fetchall()
        return [dict(row) for row in rows]

    def list_notifications(self, limit: int = 100) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM notifications ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_applications(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT applications.*, jobs.title, jobs.company, jobs.apply_url, job_matches.grade
                FROM applications
                JOIN jobs ON jobs.id = applications.job_id
                LEFT JOIN job_matches ON job_matches.job_id = jobs.id
                ORDER BY applications.updated_at DESC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def stats(self) -> dict[str, int]:
        today = utc_now()[:10]
        with self.connect() as conn:
            total = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
            new_today = conn.execute("SELECT COUNT(*) FROM jobs WHERE discovered_at LIKE ?", (f"{today}%",)).fetchone()[0]
            excellent = conn.execute(
                "SELECT COUNT(*) FROM job_matches WHERE match_percent >= 85 OR grade IN ('A', 'Excellent')"
            ).fetchone()[0]
            good = conn.execute(
                "SELECT COUNT(*) FROM job_matches WHERE (match_percent BETWEEN 70 AND 84) OR grade IN ('B', 'Good')"
            ).fetchone()[0]
            shortlisted = conn.execute("SELECT COUNT(*) FROM jobs WHERE status = 'shortlisted'").fetchone()[0]
            submitted = conn.execute(
                "SELECT COUNT(*) FROM applications WHERE status IN ('submitted', 'Applied', 'interview', 'Interview Scheduled')"
            ).fetchone()[0]
            interviews = conn.execute(
                "SELECT COUNT(*) FROM applications WHERE status IN ('interview', 'Interview Scheduled')"
            ).fetchone()[0]
            offers = conn.execute("SELECT COUNT(*) FROM applications WHERE status = 'Offer Received'").fetchone()[0]
            rejected = conn.execute(
                "SELECT COUNT(*) FROM applications WHERE status IN ('rejected', 'Rejected', 'rejected_by_user')"
            ).fetchone()[0]
            notifications = conn.execute("SELECT COUNT(*) FROM notifications").fetchone()[0]
        success_rate = 0
        if submitted:
            success_rate = round((interviews / submitted) * 100)
        return {
            "total_jobs": total,
            "new_today": new_today,
            "excellent_matches": excellent,
            "good_matches": good,
            "strong_matches": excellent,
            "shortlisted": shortlisted,
            "applications_submitted": submitted,
            "interviews": interviews,
            "offers": offers,
            "rejected": rejected,
            "notifications": notifications,
            "success_rate": success_rate,
        }

    def save_interview(self, job_id: int, questions: dict[str, Any], answers: dict[str, Any] | None = None, evaluation: dict[str, Any] | None = None, gaps: list[str] | None = None) -> int:
        now = utc_now()
        with self.connect() as conn:
            existing = conn.execute("SELECT id FROM interviews WHERE job_id = ?", (job_id,)).fetchone()
            questions_json = json.dumps(questions, ensure_ascii=False)
            answers_json = json.dumps(answers or {}, ensure_ascii=False)
            evaluation_json = json.dumps(evaluation or {}, ensure_ascii=False)
            gaps_json = json.dumps(gaps or [], ensure_ascii=False)
            if existing is None:
                cursor = conn.execute(
                    """
                    INSERT INTO interviews (job_id, questions_json, answers_json, evaluation_json, gaps_json, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (job_id, questions_json, answers_json, evaluation_json, gaps_json, now, now),
                )
                return int(cursor.lastrowid)
            conn.execute(
                """
                UPDATE interviews SET questions_json=?, answers_json=?, evaluation_json=?, gaps_json=?, updated_at=?
                WHERE job_id=?
                """,
                (questions_json, answers_json, evaluation_json, gaps_json, now, job_id),
            )
            return int(existing["id"])

    def get_interview(self, job_id: int) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM interviews WHERE job_id = ?", (job_id,)).fetchone()
        return dict(row) if row else None

    def list_follow_ups(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
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

    def list_jobs_filtered(
        self,
        search: str = "",
        company: str = "",
        location: str = "",
        min_match: int | None = None,
        experience: str = "",
        sort: str = "match",
    ) -> list[dict[str, Any]]:
        clauses = ["1=1"]
        params: list[Any] = []
        if search:
            clauses.append("(jobs.title LIKE ? OR jobs.company LIKE ? OR jobs.description LIKE ?)")
            like = f"%{search}%"
            params.extend([like, like, like])
        if company:
            clauses.append("jobs.company LIKE ?")
            params.append(f"%{company}%")
        if location:
            clauses.append("jobs.location LIKE ?")
            params.append(f"%{location}%")
        if min_match is not None:
            clauses.append("COALESCE(job_matches.match_percent, 0) >= ?")
            params.append(min_match)
        if experience:
            clauses.append("jobs.experience LIKE ?")
            params.append(f"%{experience}%")
        order = {
            "match": "COALESCE(job_matches.match_percent, 0) DESC, jobs.discovered_at DESC",
            "date": "jobs.posted_at DESC, jobs.discovered_at DESC",
            "company": "jobs.company COLLATE NOCASE",
        }.get(sort, "jobs.discovered_at DESC")
        return self.list_jobs(" AND ".join(clauses), tuple(params), order_by=order)

