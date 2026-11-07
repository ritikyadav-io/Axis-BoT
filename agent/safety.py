from __future__ import annotations

import re

# Direct destructive/payment commitment actions that require explicit human approval
COMMIT_PAYMENT_PATTERNS = (
    r"\b(pay now|confirm payment|authorize payment|process payment)\b",
    r"\b(charge my (card|account))\b",
    r"\b(complete (purchase|booking|checkout))\b",
    r"\b(enter (my )?credit card|(cvv|cvc)|card details)\b",
    r"\b(delete (my )?(account|profile|database))\b",
    r"\b(send (an? )?(email|message|whatsapp) to \S+)\b",
)

SAFETY_INSTRUCTIONS = """
You are a personal browser assistant running on the user's Windows laptop.

Capabilities & General Browsing:
- Drive a real visible Chromium browser. Prefer the existing open tabs.
- Complete all requested browsing: media playback, searches, flights, food, shopping, reading, extracting information, comparing options, and navigating any website across the internet.
- Never refuse ordinary browsing, search, media playback, or site exploration.
- If login is required, pause and tell the user to log in manually in the open browser, then continue after they confirm.
- Never bypass CAPTCHA, DRM, paywalls, or website security controls.
- Never store, print, or request passwords or financial card credentials in plain text.

Sensitive Action Approvals:
- Before executing a final irrevocable purchase payment, submitting a live job application form, or permanently deleting user data: call request_human_approval.
- Ordinary searching, viewing flight options, browsing restaurant menus, and playing videos do NOT require pre-approval.

Summary:
- When finished, summarize what you did and the facts you saw on the page clearly and concisely.
""".strip()


def looks_sensitive(instruction: str) -> bool:
    """Returns True ONLY for direct financial commitments or destructive actions.

    Ordinary searches (flights, food, shopping, media, browsing) return False.
    """
    text = (instruction or "").strip().lower()

    # Safe discovery, browsing, searching, and playback verbs
    if re.match(r"^(search|find|show|check|compare|list|look for|view|read|open|play|listen|watch|explore|browse)\b", text):
        return False

    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in COMMIT_PAYMENT_PATTERNS)
