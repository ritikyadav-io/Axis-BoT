"""Task-level failure tracking. Stop identical retries instead of looping."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from llm.provider import classify_provider_error


def action_fingerprint(action: str, error: str) -> str:
    act = re.sub(r"\s+", " ", (action or "").strip().lower())[:160]
    err = re.sub(r"\s+", " ", (error or "").strip().lower())[:160]
    err = re.sub(r"0x[0-9a-f]+", "", err)
    err = re.sub(r"\d{2,}", "n", err)
    return f"{act}|{err}"


def classify_browser_issue(text: str) -> str:
    blob = (text or "").lower()
    if "captcha" in blob or "recaptcha" in blob or "verify you are human" in blob:
        return "captcha"
    if "login" in blob or "sign in" in blob or "log in" in blob:
        return "login"
    if "cookie" in blob and ("accept" in blob or "consent" in blob):
        return "cookie_banner"
    if "timeout" in blob or "timed out" in blob:
        return "page_timeout"
    if "not found" in blob or "no such element" in blob or ("element" in blob and "not" in blob):
        return "element_missing"
    if "net::err" in blob or "err_name_not_resolved" in blob or "404" in blob:
        return "broken_url"
    classified = classify_provider_error(RuntimeError(text))
    if classified.kind in {"unavailable", "invalid_key", "quota", "rate_limit", "credits"}:
        return classified.kind
    return "other"


USER_MESSAGES = {
    "captcha": "This website requires a CAPTCHA. Please solve it in the open browser. I will not bypass it.",
    "login": "This website requires login. Please log in manually in the open browser, then give the next instruction.",
    "cookie_banner": "A cookie banner is blocking the page. I will try the visible Accept/Close control once.",
    "page_timeout": "The page was slow. I will check what loaded and retry once.",
    "element_missing": "The expected button or field was not found. I will re-read the page and try one alternative.",
    "broken_url": "That address did not load. I will not keep opening the same broken URL.",
    "unavailable": "The chat model is unavailable. I stopped instead of retrying it.",
    "invalid_key": "The API key was rejected. Update it in .env. I will not keep calling the API.",
    "quota": "The daily quota is exhausted. I will not keep retrying.",
    "rate_limit": "The provider rate-limited this request. I will wait, then continue with a smaller step if possible.",
    "credits": "OpenRouter rejected this request because your account balance or API key credit limit is insufficient. Check your OpenRouter Credits and API Key settings.",
    "other": "That step failed. I will try one different approach, then stop if it fails the same way.",
}


@dataclass
class FailureTracker:
    max_identical: int = 2
    counts: Counter[str] = field(default_factory=Counter)
    last_kind: str = ""

    def record(self, action: str, error: str) -> tuple[bool, str, str]:
        kind = classify_browser_issue(error)
        self.last_kind = kind
        fingerprint = action_fingerprint(action, error)
        self.counts[fingerprint] += 1
        stop = self.counts[fingerprint] >= self.max_identical or kind in {
            "unavailable",
            "invalid_key",
            "quota",
            "credits",
            "captcha",
            "login",
            "broken_url",
        }
        if kind == "broken_url" and self.counts[fingerprint] < 2:
            stop = False
        message = USER_MESSAGES.get(kind, USER_MESSAGES["other"])
        if stop and self.counts[fingerprint] >= self.max_identical:
            message = "I tried two approaches, but this page is still unavailable. I stopped instead of repeating the same action."
        return stop, kind, message
