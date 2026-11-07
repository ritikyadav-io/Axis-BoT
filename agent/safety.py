from __future__ import annotations

import re

SENSITIVE_PATTERNS = (
    r"\bbuy\b",
    r"\bpurchase\b",
    r"\bpay(ment|ing)?\b",
    r"\bcheckout\b",
    r"\bbook(ing)?\b",
    r"\breserv(e|ation)\b",
    r"\bflight ticket\b",
    r"\bhotel\b",
    r"\bsend (an? )?(email|message|dm|whatsapp)\b",
    r"\bapply(ing)? (for|to)\b",
    r"\bjob application\b",
    r"\bdelete\b",
    r"\bremove account\b",
    r"\bchange (my )?(password|email|settings)\b",
    r"\bshare (my )?(personal|private)\b",
    r"\bcredit card\b",
    r"\bcvv\b",
    r"\bssn\b",
    r"\baadhaar\b",
    r"\bpan card\b",
)

SAFETY_INSTRUCTIONS = """
You are a personal browser assistant running on the user's Windows laptop.

Hard rules:
- Drive a real visible Chromium browser. Prefer the existing open tabs.
- Complete ordinary browsing: search, navigate, click, read, extract, compare, fill ordinary forms.
- If login is required, pause and tell the user to log in manually in the open browser, then continue after they confirm.
- Never bypass CAPTCHA, DRM, paywalls, or website security controls.
- Never store, print, or request passwords or authentication tokens in plain text.
- Never claim a sensitive action completed unless the website actually confirmed it.
- Before purchasing, booking flights/hotels, paying, sending emails/messages, submitting job applications, deleting data, changing account settings, or sharing personal information: call request_human_approval. If approval is denied, stop that action and report that you did not do it.
- Do not invent search results, prices, or match listings. Report only what you actually saw on the page.
- When finished, summarize what you did, the important facts you found, and any blockers.
""".strip()


def looks_sensitive(instruction: str) -> bool:
    text = instruction.lower()
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in SENSITIVE_PATTERNS)
