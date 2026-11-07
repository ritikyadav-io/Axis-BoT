"""Lightweight instruction cleanup and intent normalization. No LLM calls."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

WORD_FIXES = {
    "yotube": "youtube",
    "youtub": "youtube",
    "ytube": "youtube",
    "you tube": "youtube",
    "yoyutbe": "youtube",
    "youtbe": "youtube",
    "yutube": "youtube",
    "yutub": "youtube",
    "yotuub": "youtube",
    "youtueb": "youtube",
    "yoytube": "youtube",
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
    "chalao": "play",
    "bajao": "play",
    "dikhao": "show",
    "gaana": "song",
    "gana": "song",
    "khana": "food",
}

SITE_URLS = {
    "youtube": "https://www.youtube.com",
    "google": "https://www.google.com",
    "naukri": "https://www.naukri.com",
    "linkedin": "https://www.linkedin.com",
    "indeed": "https://in.indeed.com",
    "github": "https://www.github.com",
    "reddit": "https://www.reddit.com",
    "wikipedia": "https://www.wikipedia.org",
    "amazon": "https://www.amazon.com",
    "flipkart": "https://www.flipkart.com",
    "duckduckgo": "https://duckduckgo.com",
    "google flights": "https://www.google.com/travel/flights",
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

    # Normalize obvious YouTube typos with regex
    lowered = re.sub(r"\by[ouy]{1,4}t[ub]{1,3}e?\b", "youtube", lowered, flags=re.IGNORECASE)

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
        for name in SITE_URLS:
            if name in host:
                return name
    return None


def classify_complexity(text: str) -> bool:
    blob = text.lower()
    if re.search(r"\b(find|search|compare|extract|summar|jobs?|interview|apply|play|watch|listen|flight|food)\b", blob):
        if re.search(r"\b(\d+|five|5|list|results?|and then|then)\b", blob) or " and " in blob:
            return False
    if re.search(r"\b(find|search).+\b(jobs?|flights?|food|restaurants?)\b", blob):
        return False
    if re.search(r"\b(play|watch|listen)\b", blob):
        return False
    return True


def normalize_instruction(raw: str) -> NormalizedTask:
    original = raw or ""
    cleaned = apply_word_fixes(collapse_spaces(original))
    blob = cleaned.lower()
    site = _mentioned_site(blob)
    simple = classify_complexity(cleaned)
    plan: list[str] = []
    expanded = cleaned
    kind = "browse"
    start_message = "Working on your request."

    # Intent flags
    is_play_intent = bool(re.search(r"\b(play|watch|listen|stream|chalao|bajao)\b", blob))
    is_flight_intent = bool(re.search(r"\b(flights?|plane ticket|air ticket|flight booking|airline)\b", blob))
    is_food_intent = bool(re.search(r"\b(food|restaurant|order food|swiggy|zomato|pizza|burger|biryani|dining|cafe|khana)\b", blob)) and not is_play_intent
    is_adult_intent = bool(re.search(r"\b(porn|xxx|xvideos|pornhub|metaporn|dinotube|adult)\b", blob))

    is_pure_open_youtube = (
        re.fullmatch(r"(open|play|go to|visit)\s+(the\s+)?youtube", blob)
        or blob in {"play youtube", "youtube kholo", "open youtube"}
    )

    # 1. YouTube Pure Open
    if is_pure_open_youtube:
        kind = "open_site"
        simple = True
        expanded = f"Open {SITE_URLS['youtube']} in the existing Chromium window. Do not search unless a video title was given."
        start_message = "Opening YouTube."
        plan = ["Open YouTube."]

    # 2. Adult Video / Content Request
    elif is_adult_intent:
        kind = "adult_content"
        simple = False
        target_site = site or "duckduckgo"
        target_url = SITE_URLS.get(target_site, "https://duckduckgo.com")

        # Extract search query
        query = re.sub(r"^(please\s+)?(can you\s+)?(play|watch|listen|open|search(\s+for)?)\s+", "", blob, flags=re.IGNORECASE)
        query = re.sub(r"\s+(on|in)\s+\S+$", "", query).strip(" .")
        query_display = query or cleaned

        if site and site not in {"google", "duckduckgo", "youtube"}:
            expanded = (
                f"Navigate directly to {SITE_URLS[site]}. "
                f"Search for '{query_display}' on the site, find the best matching video, click to open it, "
                f"and start playback. Unmute audio if muted and ensure the video player starts playing."
            )
            start_message = f"Opening {site.title()} and playing '{query_display}'."
        else:
            expanded = (
                f"Navigate to {target_url} and search for '{cleaned}'. "
                f"From the search results, click on the top relevant video link to open it. "
                f"Start video playback, unmute audio if muted, and ensure the player is actively playing."
            )
            start_message = f"Searching for and playing '{cleaned}'."

        plan = ["Navigate to the site/search.", f"Find video matching '{query_display}'.", "Start playback and unmute audio."]

    # 3. Media Playback Intent (Music, Songs, Videos)
    elif is_play_intent or (site == "youtube" and not is_pure_open_youtube):
        kind = "play_media"
        simple = False
        query = re.sub(r"^(please\s+)?(can you\s+)?(play|listen(\s+to)?|watch|stream|chalao|bajao)\s+", "", blob, flags=re.IGNORECASE)
        query = re.sub(r"\s+(on|in|from)\s+youtube\b", "", query, flags=re.IGNORECASE).strip(" .")
        query_display = query or cleaned

        target_site_url = SITE_URLS.get(site or "youtube", "https://www.youtube.com")
        expanded = (
            f"Navigate to {target_site_url}. "
            f"Click on the search box, type '{query_display}' and press Enter. "
            f"Wait for the search results to load, then click on the first video link or thumbnail matching '{query_display}'. "
            f"Wait for the video player page to load and ensure the video starts playing. "
            f"If the video is muted, click unmute (or press 'm'). "
            f"Increase volume to an audible level (press the Up Arrow key several times). "
            f"If an ad with a 'Skip Ad' button or a cookie banner appears, dismiss or skip it immediately. "
            f"Confirm that the video '{query_display}' is currently playing with sound."
        )
        start_message = f"Playing '{query_display}' on YouTube with volume up."
        plan = [
            "Open YouTube.",
            f"Search for '{query_display}'.",
            "Click on the top video result.",
            "Ensure playback starts, unmute audio, and raise volume.",
        ]

    # 4. Flight Search Intent
    elif is_flight_intent:
        kind = "flight_search"
        simple = False
        expanded = (
            f"Navigate to https://www.google.com/travel/flights. "
            f"Search for flights based on: '{cleaned}'. "
            f"Enter the departure location, destination, and dates if specified, and submit the search. "
            f"Extract the top 3-5 flight options (airlines, departure/arrival times, duration, stops, prices in INR/USD). "
            f"Summarize the flight details clearly for the user."
        )
        start_message = f"Searching flights for '{cleaned}' on Google Flights."
        plan = ["Open Google Flights.", "Input flight route and dates.", "Extract flight times and prices.", "Summarize results."]

    # 5. Food & Restaurant Search Intent
    elif is_food_intent:
        kind = "food_search"
        simple = False
        expanded = (
            f"Navigate to https://www.google.com/maps or Google Search. "
            f"Search for '{cleaned}'. "
            f"Extract top-rated restaurants, food options, or delivery outlets matching the query. "
            f"List restaurant names, ratings, address/location, cuisine, and delivery/price info."
        )
        start_message = f"Searching food/restaurants for '{cleaned}'."
        plan = ["Search for food options.", "Extract top restaurants and ratings.", "Summarize menu and ordering details."]

    # 6. Job Search Intent
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

    # 7. Pure Open Site Intent (e.g. "open google", "open linkedin")
    elif re.fullmatch(r"(open|go to|visit)\s+(the\s+)?google", blob) or blob == "open google":
        kind = "open_site"
        simple = True
        expanded = f"Open {SITE_URLS['google']} in the existing Chromium window."
        start_message = "Opening Google."
        plan = ["Open Google."]

    elif site and re.fullmatch(r"(open|go to|visit)\s+(the\s+)?" + re.escape(site), blob):
        kind = "open_site"
        simple = True
        expanded = f"Open {SITE_URLS[site]} in the existing Chromium window."
        start_message = f"Opening {site.title()}."
        plan = [f"Open {site.title()}."]

    # 8. Search on Google Intent
    elif "search" in blob and site == "google":
        kind = "google_search"
        query = re.sub(r"^(please\s+)?(open\s+google\s+(and\s+)?)?(search(\s+for)?|google)\s+", "", blob, flags=re.IGNORECASE)
        query = re.sub(r"^on\s+google\s+", "", query).strip(" .")
        expanded = (
            f"Open {SITE_URLS['google']}. "
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

    # 9. Generic Site, Domain or Universal Search
    else:
        single_word = cleaned.strip()
        is_domain = bool(re.search(r"^[a-zA-Z0-9-]+\.[a-zA-Z]{2,}(/.*)?$", single_word))
        is_single_word = " " not in single_word and not is_domain and len(single_word) > 2

        if is_domain:
            target_url = f"https://{single_word}" if not single_word.startswith("http") else single_word
            kind = "open_site"
            simple = True
            expanded = f"Navigate directly to {target_url} in the existing Chromium window."
            start_message = f"Navigating to {target_url}."
            plan = [f"Open {target_url}."]
        elif is_single_word:
            kind = "site_search"
            simple = False
            expanded = (
                f"Navigate to https://duckduckgo.com or Google and search for '{single_word}'. "
                f"From the search results, click on the official website link for '{single_word}'. "
                f"Once the website loads, display the loaded page and report what is on the site."
            )
            start_message = f"Searching for and opening '{single_word}'."
            plan = [f"Search for '{single_word}'.", f"Open the official {single_word} page."]
        else:
            kind = "browse"
            simple = False
            expanded = (
                f"{cleaned}\n\n"
                "Carry out this browsing request in the existing Chromium window. "
                "Navigate directly or search using Google/DuckDuckGo if no direct URL is given. "
                "Do not ask unnecessary questions; perform the action and summarize what you did."
            )
            start_message = "Working on your request."
            plan = ["Understand the request.", "Navigate to the site.", "Perform requested action.", "Summarize results."]

    return NormalizedTask(
        original=original,
        cleaned=cleaned,
        expanded=expanded,
        kind=kind,
        simple=simple,
        start_message=start_message,
        plan_steps=plan,
        ambiguous=None,  # Never block user with ambiguous questions
    )
