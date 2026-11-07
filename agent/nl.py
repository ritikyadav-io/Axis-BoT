"""Lightweight instruction cleanup. No LLM calls."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

WORD_FIXES = {
    "yotube": "youtube",
    "youtub": "youtube",
    "ytube": "youtube",
    "you tube": "youtube",
    "gogle": "google",
    "googel": "google",
    "goole": "google",
    "goolge": "google",
    "enginer": "engineer",
    "enginerr": "engineer",
    "pyhton": "python",
    "pytohn": "python",
    "interveiw": "interview",
    "intervew": "interview",
    "naukari": "naukri",
    "linkeidin": "linkedin",
    "linkdin": "linkedin",
    "linkdin.com": "linkedin.com",
}

HINGLISH = {
    "kholo": "open",
    "khol": "open",
    "dekho": "show",
    "dhundo": "find",
    "jobes": "jobs",
}

SITE_URLS = {
    "youtube": "https://www.youtube.com",
    "google": "https://www.google.com",
    "naukri": "https://www.naukri.com",
    "linkedin": "https://www.linkedin.com",
    "indeed": "https://in.indeed.com",
}

SITE_ALIASES = {
    "yt": "youtube",
    "ytb": "youtube",
}


@dataclass
class NormalizedTask:
    original: str
    cleaned: str
    expanded: str
    kind: str
    simple: bool
    start_message: str
    plan_steps: list[str] = field(default_factory=list)
    ambiguous: str | None = None


def collapse_spaces(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def _protect_urls(text: str) -> tuple[str, dict[str, str]]:
    held: dict[str, str] = {}
    def stash(match: re.Match[str]) -> str:
        key = f"URLTOKEN{len(held)}"
        held[key] = match.group(0)
        return key
    protected = re.sub(r"https?://\S+", stash, text)
    return protected, held


def apply_word_fixes(text: str) -> str:
    protected, urls = _protect_urls(text)
    lowered = protected
    for src, dst in WORD_FIXES.items():
        lowered = re.sub(rf"\b{re.escape(src)}\b", dst, lowered, flags=re.IGNORECASE)
    for src, dst in HINGLISH.items():
        lowered = re.sub(rf"\b{re.escape(src)}\b", dst, lowered, flags=re.IGNORECASE)
    for src, dst in SITE_ALIASES.items():
        lowered = re.sub(rf"\b{re.escape(src)}\b", dst, lowered, flags=re.IGNORECASE)
    for key, url in urls.items():
        lowered = lowered.replace(key, url)
    return collapse_spaces(lowered)


def _mentioned_site(text: str) -> str | None:
    blob = text.lower()
    for name in SITE_URLS:
        if re.search(rf"\b{name}\b", blob):
            return name
    parsed = urlparse(text)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        host = parsed.netloc.lower().removeprefix("www.")
        for name, url in SITE_URLS.items():
            if name in host:
                return name
    return None


def classify_complexity(text: str) -> bool:
    blob = text.lower()
    if re.search(r"\b(find|search|compare|extract|summar|jobs?|interview|apply)\b", blob):
        if re.search(r"\b(\d+|five|5|list|results?|and then|then)\b", blob) or " and " in blob:
            return False
    if re.search(r"\b(find|search).+\bjobs?\b", blob):
        return False
    return True


def normalize_instruction(raw: str) -> NormalizedTask:
    original = raw or ""
    cleaned = apply_word_fixes(collapse_spaces(original))
    blob = cleaned.lower()
    site = _mentioned_site(blob)
    simple = classify_complexity(cleaned)
    plan: list[str] = []
    ambiguous = None
    expanded = cleaned
    kind = "browse"
    start_message = "Working on your request."

    if re.fullmatch(r"(open|play|go to|visit)\s+(the\s+)?youtube", blob) or blob in {"play youtube", "youtube kholo", "open youtube"}:
        kind = "open_site"
        simple = True
        expanded = f"Open {SITE_URLS['youtube']} in the existing Chromium window. Do not search unless a video title was given."
        start_message = "Opening YouTube."
        plan = ["Open YouTube."]
    elif re.fullmatch(r"(open|go to|visit)\s+(the\s+)?google", blob) or blob == "open google":
        kind = "open_site"
        simple = True
        expanded = f"Open {SITE_URLS['google']} in the existing Chromium window."
        start_message = "Opening Google."
        plan = ["Open Google."]
    elif site and re.match(r"^(open|go to|visit|play)\b", blob) and "search" not in blob and "find" not in blob:
        kind = "open_site"
        simple = True
        expanded = f"Open {SITE_URLS[site]} in the existing Chromium window."
        start_message = f"Opening {site.title()}."
        plan = [f"Open {site.title()}."]
    elif "job" in blob:
        kind = "job_search"
        simple = False
        expanded = (
            f"{cleaned}\n\n"
            "Objective: find relevant job listings the user asked for. "
            "Distinguish Data Engineer, Data Analyst, Software Developer, Cloud Engineer and Python Developer. "
            "Prefer India/fresher/junior when those words appear. "
            "Extract company, role, location, experience, salary if shown, and the real apply URL. "
            "Skip duplicates. Never invent a listing. Uncertain fields stay unknown."
        )
        start_message = "Searching for matching job listings."
        plan = [
            "Search relevant public job sources.",
            "Keep only roles that match the requested title.",
            "Extract company, role, location, experience, salary if shown, and apply URL.",
            "Remove duplicates.",
            "Return the best relevant results actually seen.",
        ]
    elif "search" in blob and site == "google":
        kind = "google_search"
        query = re.sub(r"^(please\s+)?(open\s+google\s+(and\s+)?)?(search(\s+for)?|google)\s+", "", blob, flags=re.IGNORECASE)
        query = re.sub(r"^on\s+google\s+", "", query).strip(" .")
        expanded = (
            f"Open {SITE_URLS['google'] if 'http' not in cleaned else cleaned.split()[0]}. "
            f"Search Google for: {query or cleaned}. Extract the visible results. Do not invent listings."
        )
        start_message = f"Searching Google for {query or 'your query'}."
        plan = ["Open Google.", f"Search for {query or cleaned}.", "Summarize visible results."]
        simple = True
    elif re.match(r"^(search|find|google)\b", blob) and site is None:
        kind = "google_search"
        query = re.sub(r"^(search|find|google)(\s+for)?\s+", "", blob).strip()
        expanded = f"Open {SITE_URLS['google']} and search for: {query}. Report only what appears on the page."
        start_message = f"Searching Google for {query}."
        plan = ["Open Google.", f"Search for {query}.", "Summarize visible results."]
        simple = True
    elif site is None and re.match(r"^(open|play)\b", blob) and not re.search(r"https?://", blob):
        ambiguous = "Which website should I open? For example YouTube or Google."
        kind = "ambiguous"
        start_message = ambiguous
        expanded = cleaned

    if not simple and not plan:
        plan = ["Understand the request.", "Open only the needed site.", "Do the minimum clicks.", "Summarize facts from the page."]
        expanded = cleaned + "\n\nBreak this into the fewest browser steps. Do not repeat a failed click. Summarize facts you actually saw."

    return NormalizedTask(
        original=original,
        cleaned=cleaned,
        expanded=expanded,
        kind=kind,
        simple=simple,
        start_message=start_message,
        plan_steps=plan,
        ambiguous=ambiguous,
    )
