"""Runtime knobs for the browser agent. Values come from .env."""

from __future__ import annotations

import os


def _env_int(name: str, default: int, *, minimum: int = 1, maximum: int = 100) -> int:
    raw = (os.getenv(name) or "").strip()
    try:
        value = int(raw) if raw else default
    except ValueError:
        value = default
    return max(minimum, min(maximum, value))


def _env_bool(name: str, default: bool) -> bool:
    raw = (os.getenv(name) or "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def agent_max_steps() -> int:
    return _env_int("AGENT_MAX_STEPS", 15, minimum=3, maximum=40)


def agent_max_retries() -> int:
    return _env_int("AGENT_MAX_RETRIES", 2, minimum=1, maximum=3)


def agent_verbose() -> bool:
    return _env_bool("AGENT_VERBOSE", False)


def agent_memory_enabled() -> bool:
    return _env_bool("AGENT_MEMORY_ENABLED", True)


def configure_agent_logging() -> None:
    if agent_verbose():
        return
    os.environ.setdefault("BROWSER_USE_LOGGING_LEVEL", "warning")
