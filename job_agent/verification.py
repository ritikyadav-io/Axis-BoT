"""Listing verification. Kept separate so tracker/dashboard can import it without circular imports."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

UNVERIFIED_SOURCES = {"sample", "fixture", "demo", "test", "offline"}
FAKE_HOSTS = {"example.com", "example.org", "localhost", "127.0.0.1"}


def is_verified_listing(job: dict[str, Any] | None) -> bool:
    """True only for public listings with a real http(s) apply URL.

    Sample fixtures, example.com URLs, and rows missing a title or apply link stay unverified.
    """
    if not isinstance(job, dict) or not job:
        return False
    source = str(job.get("source") or "").strip().lower()
    if source in UNVERIFIED_SOURCES:
        return False
    title = str(job.get("title") or "").strip()
    apply_url = str(job.get("apply_url") or "").strip()
    if not title or not apply_url:
        return False
    parsed = urlparse(apply_url)
    host = (parsed.netloc or "").lower().removeprefix("www.")
    if parsed.scheme not in {"http", "https"} or not host or host in FAKE_HOSTS:
        return False
    return True
