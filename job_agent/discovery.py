from __future__ import annotations

import hashlib
import json
import os
import re
import time
from datetime import date, datetime, timezone
from typing import Any
from urllib.parse import quote_plus, urlparse
from xml.etree import ElementTree

import httpx

from job_agent.config import load_profile
from job_agent.database import JobStore
from job_agent.paths import FIXTURES_DIR

USER_AGENT = "PersonalJobAgent/1.0 (local research; respects robots and public feeds)"
REQUEST_TIMEOUT = 20.0

LINKEDIN_NOTE = "LinkedIn HTML scraping is disabled. Use the generated public search URL in a browser while logged in if the site allows it."
NAUKRI_NOTE = "Naukri HTML scraping is disabled because the site is protected. Open the generated search URL manually."
WELLFOUND_NOTE = "Wellfound does not provide a public feed used here. Open the generated search URL manually."


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def normalize_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().lower())


def canonicalize_url(url: str | None) -> str:
    if not url:
        return ""
    parsed = urlparse(url.strip())
    host = (parsed.netloc or "").lower().removeprefix("www.")
    path = (parsed.path or "").rstrip("/")
    return f"{host}{path}"


def dedupe_jobs(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for job in jobs:
        key = job.get("fingerprint") or job_fingerprint(job)
        if key in seen:
            continue
        seen.add(key)
        unique.append(job)
    return unique


def job_fingerprint(job: dict[str, Any]) -> str:
    url_key = canonicalize_url(job.get("apply_url"))
    if url_key:
        basis = url_key
    else:
        basis = "|".join(
            [
                normalize_text(job.get("company")),
                normalize_text(job.get("title")),
                normalize_text(job.get("location")),
            ]
        )
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


def _blank_job(**kwargs: Any) -> dict[str, Any]:
    job = {
        "source": None,
        "title": None,
        "company": None,
        "location": None,
        "salary": None,
        "experience": None,
        "description": None,
        "required_skills": [],
        "posted_at": None,
        "deadline": None,
        "apply_url": None,
    }
    job.update(kwargs)
    job["fingerprint"] = job_fingerprint(job)
    return job


def load_sample_jobs() -> list[dict[str, Any]]:
    path = FIXTURES_DIR / "sample_jobs.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    jobs = []
    for item in payload:
        job = _blank_job(**item)
        jobs.append(job)
    return jobs


def _get(url: str) -> httpx.Response | None:
    try:
        with httpx.Client(timeout=REQUEST_TIMEOUT, follow_redirects=True, headers={"User-Agent": USER_AGENT}) as client:
            response = client.get(url)
        if response.status_code >= 400:
            return None
        return response
    except httpx.HTTPError:
        return None


def _text(value: str | None) -> str | None:
    cleaned = re.sub(r"<[^>]+>", " ", value or "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned or None


def fetch_indeed_rss(query: str, location: str = "India") -> list[dict[str, Any]]:
    url = f"https://in.indeed.com/rss?q={quote_plus(query)}&l={quote_plus(location)}"
    response = _get(url)
    if response is None:
        return []
    jobs: list[dict[str, Any]] = []
    try:
        root = ElementTree.fromstring(response.content)
    except ElementTree.ParseError:
        return []
    for item in root.findall(".//item"):
        title = _text(item.findtext("title"))
        company = None
        if title and " - " in title:
            maybe_company = title.rsplit(" - ", 1)[-1]
            if maybe_company and len(maybe_company) < 80:
                company = maybe_company
        jobs.append(
            _blank_job(
                source="indeed_rss",
                title=title,
                company=company,
                location=location,
                description=_text(item.findtext("description")),
                posted_at=_text(item.findtext("pubDate")),
                apply_url=_text(item.findtext("link")),
            )
        )
    return jobs


def fetch_remotive(query: str) -> list[dict[str, Any]]:
    url = f"https://remotive.com/api/remote-jobs?search={quote_plus(query)}&limit=20"
    response = _get(url)
    if response is None:
        return []
    try:
        payload = response.json()
    except ValueError:
        return []
    jobs = []
    for item in payload.get("jobs") or []:
        location = item.get("candidate_required_location")
        loc_text = normalize_text(str(location or ""))
        if loc_text and not any(token in loc_text for token in ("india", "anywhere", "worldwide", "utc", "remote")):
            continue
        jobs.append(
            _blank_job(
                source="remotive",
                title=item.get("title"),
                company=(item.get("company_name") or None),
                location=location,
                salary=item.get("salary") or None,
                description=_text(item.get("description")),
                posted_at=item.get("publication_date"),
                apply_url=item.get("url") or item.get("application_url"),
                required_skills=item.get("tags") or [],
            )
        )
    return jobs


def fetch_arbeitnow(query: str) -> list[dict[str, Any]]:
    url = f"https://www.arbeitnow.com/api/job-board-api?search={quote_plus(query)}"
    response = _get(url)
    if response is None:
        return []
    try:
        payload = response.json()
    except ValueError:
        return []
    jobs = []
    for item in payload.get("data") or []:
        location = item.get("location")
        loc_text = normalize_text(str(location or ""))
        remote = bool(item.get("remote"))
        if loc_text and "india" not in loc_text and not remote:
            continue
        jobs.append(
            _blank_job(
                source="arbeitnow",
                title=item.get("title"),
                company=item.get("company_name"),
                location=location if location else ("Remote" if remote else None),
                description=_text(item.get("description")),
                posted_at=str(item.get("created_at") or "") or None,
                apply_url=item.get("url"),
                required_skills=item.get("tags") or [],
            )
        )
    return jobs


def fetch_remoteok(query: str) -> list[dict[str, Any]]:
    response = _get("https://remoteok.com/api")
    if response is None:
        return []
    try:
        payload = response.json()
    except ValueError:
        return []
    needle = normalize_text(query)
    jobs = []
    for item in payload:
        if not isinstance(item, dict) or "id" not in item:
            continue
        blob = normalize_text(" ".join(str(item.get(key) or "") for key in ("position", "description", "tags")))
        if needle and needle not in blob:
            continue
        location = item.get("location")
        loc_text = normalize_text(str(location or ""))
        if loc_text and not any(token in loc_text for token in ("india", "anywhere", "worldwide", "remote", "")):
            continue
        tags = item.get("tags") or []
        jobs.append(
            _blank_job(
                source="remoteok",
                title=item.get("position"),
                company=item.get("company"),
                location=location or "Remote",
                salary=item.get("salary") or None,
                description=_text(item.get("description")),
                required_skills=tags if isinstance(tags, list) else [],
                posted_at=str(item.get("date") or "") or None,
                apply_url=item.get("url") or item.get("apply_url"),
            )
        )
        if len(jobs) >= 15:
            break
    return jobs


def fetch_internshala(role: str) -> list[dict[str, Any]]:
    slug = re.sub(r"[^a-z0-9]+", "-", role.lower()).strip("-")
    url = f"https://internshala.com/jobs/{slug}-jobs/"
    response = _get(url)
    if response is None:
        return []
    html = response.text
    jobs: list[dict[str, Any]] = []
    # Public listing cards; skip if the page is a login/CAPTCHA wall.
    if "captcha" in html.lower() or "verify you are human" in html.lower():
        return []
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select("div.individual_internship, div.job_title, div.internship_meta")
    if not cards:
        cards = soup.select("a[href*='/job/detail/'], a[href*='/jobs/detail/']")
    seen = set()
    for card in cards[:20]:
        link = card if card.name == "a" else card.find("a", href=True)
        href = link.get("href") if link else None
        title = _text(card.get_text(" ", strip=True))
        if href and href.startswith("/"):
            href = "https://internshala.com" + href
        if not href or href in seen:
            continue
        seen.add(href)
        jobs.append(
            _blank_job(
                source="internshala",
                title=title[:180] if title else role,
                company=None,
                location="India",
                description=title,
                apply_url=href,
            )
        )
    return jobs


def fetch_career_page(url: str) -> list[dict[str, Any]]:
    response = _get(url)
    if response is None:
        return []
    content_type = response.headers.get("content-type", "")
    jobs: list[dict[str, Any]] = []
    if "xml" in content_type or url.endswith(".xml") or "<rss" in response.text[:400].lower():
        try:
            root = ElementTree.fromstring(response.content)
        except ElementTree.ParseError:
            return []
        for item in root.findall(".//item"):
            jobs.append(
                _blank_job(
                    source="career_page",
                    title=_text(item.findtext("title")),
                    company=urlparse(url).netloc,
                    description=_text(item.findtext("description")),
                    posted_at=_text(item.findtext("pubDate")),
                    apply_url=_text(item.findtext("link")),
                )
            )
        return jobs
    return []


def portal_search_urls(profile: dict[str, Any]) -> list[dict[str, str]]:
    role = quote_plus((profile.get("target_roles") or ["Python Developer"])[0])
    country = quote_plus(profile.get("target_country") or "India")
    return [
        {
            "source": "linkedin_search",
            "url": f"https://www.linkedin.com/jobs/search/?keywords={role}&location={country}&f_E=2",
            "notes": LINKEDIN_NOTE,
        },
        {
            "source": "naukri_search",
            "url": f"https://www.naukri.com/{role.replace('+', '-')}-jobs-in-india",
            "notes": NAUKRI_NOTE,
        },
        {
            "source": "wellfound_search",
            "url": f"https://wellfound.com/role/l/{role.replace('+', '-')}",
            "notes": WELLFOUND_NOTE,
        },
    ]


def discover_jobs(profile: dict[str, Any] | None = None, use_network: bool | None = None) -> dict[str, Any]:
    profile = profile or load_profile()
    if use_network is None:
        use_network = (os.getenv("JOB_DISCOVERY_NETWORK", "true").lower() in {"1", "true", "yes"})
    sources = profile.get("enabled_sources") or ["sample"]
    roles = profile.get("target_roles") or ["Python Developer"]
    if roles:
        shift = date.today().toordinal() % len(roles)
        roles = roles[shift:] + roles[:shift]
    keywords = profile.get("search_keywords") or ["fresher"]
    queries = []
    for role in roles[:3]:
        queries.append(f"{role} fresher")
        queries.append(f"{role} 0-1 years")
    queries.append("Graduate Engineer Trainee fresher")
    for keyword in keywords[:2]:
        queries.append(f"{keyword} python developer")
    queries = list(dict.fromkeys(queries))[:4]

    found: list[dict[str, Any]] = []
    source_notes: list[str] = []
    search_log: list[tuple[str, str, int, str]] = []

    if "sample" in sources:
        sample = load_sample_jobs()
        found.extend(sample)
        search_log.append(("sample fixtures", "sample", len(sample), "offline sample jobs"))

    live_fetchers = {
        "indeed_rss": lambda q: fetch_indeed_rss(q, profile.get("target_country") or "India"),
        "remotive": fetch_remotive,
        "arbeitnow": fetch_arbeitnow,
        "remoteok": fetch_remoteok,
        "internshala": fetch_internshala,
    }

    if use_network:
        for source, fetcher in live_fetchers.items():
            if source not in sources:
                continue
            source_count = 0
            query_slice = queries[:1] if source in {"remoteok", "internshala"} else queries[:2]
            locations = ["India", "Bengaluru"] if source == "indeed_rss" else [None]
            for query in query_slice:
                for location in locations:
                    if source == "indeed_rss":
                        jobs = fetch_indeed_rss(query, location or "India")
                    else:
                        jobs = fetcher(query)
                    source_count += len(jobs)
                    found.extend(jobs)
                    time.sleep(0.5)
            search_log.append((", ".join(query_slice), source, source_count, "public feed/API"))
            if source_count == 0:
                source_notes.append(f"{source}: no public results returned (blocked, empty, or unavailable).")

        for career_url in profile.get("company_career_pages") or []:
            jobs = fetch_career_page(career_url)
            found.extend(jobs)
            search_log.append((career_url, "career_page", len(jobs), "configured company page"))
    else:
        source_notes.append("Network discovery skipped (JOB_DISCOVERY_NETWORK is false).")

    for portal in portal_search_urls(profile):
        search_log.append((portal["url"], portal["source"], 0, portal["notes"]))
        source_notes.append(f"{portal['source']}: {portal['notes']}")

    unique: dict[str, dict[str, Any]] = {}
    for job in found:
        if not job.get("title"):
            continue
        unique[job["fingerprint"]] = job

    return {
        "jobs": list(unique.values()),
        "search_log": search_log,
        "notes": source_notes,
        "generated_at": _now(),
    }


def ingest_discovered_jobs(store: JobStore | None = None, use_network: bool | None = None) -> dict[str, Any]:
    store = store or JobStore()
    result = discover_jobs(use_network=use_network)
    inserted = 0
    duplicates = 0
    changed = 0
    job_ids = []
    new_job_ids = []
    for job in result["jobs"]:
        job_id, is_new, status_changed = store.upsert_job(job)
        job_ids.append(job_id)
        if is_new:
            inserted += 1
            new_job_ids.append(job_id)
        else:
            duplicates += 1
            if status_changed:
                changed += 1
    for query, source, count, notes in result["search_log"]:
        store.add_search_history(query, source, count, notes)
    return {
        "found": len(result["jobs"]),
        "inserted": inserted,
        "duplicates": duplicates,
        "changed": changed,
        "job_ids": job_ids,
        "new_job_ids": new_job_ids,
        "notes": result["notes"],
    }
