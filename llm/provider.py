from __future__ import annotations

import re
from typing import Any

from config import fallback_provider_name, llm_provider_name

CREDITS_MESSAGE = (
    "OpenRouter rejected this request because your account balance or API key credit "
    "limit is insufficient. Check your OpenRouter Credits and API Key settings."
)


class ProviderConfigError(RuntimeError):
    pass


NON_RETRYABLE_KINDS = frozenset({"unavailable", "invalid_key", "credits", "quota"})


class ProviderCallError(RuntimeError):
    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind


def _status_from_error(exc: BaseException, text: str) -> int | None:
    status = getattr(exc, "status_code", None) or getattr(exc, "status", None)
    if status is not None:
        try:
            return int(status)
        except (TypeError, ValueError):
            pass
    match = re.search(r"(?:error code:|http|status)\s*([0-9]{3})", text)
    if match:
        return int(match.group(1))
    return None


def _redact(text: str) -> str:
    return re.sub(r"sk-or-v1-[A-Za-z0-9]+", "[REDACTED]", text)


def classify_provider_error(exc: BaseException) -> ProviderCallError:
    text = _redact(str(exc).lower())
    status = _status_from_error(exc, text)
    if status == 401 or "invalid api key" in text or "incorrect api key" in text:
        return ProviderCallError("invalid_key", "The API key was rejected. Check OPENROUTER_API_KEY or GEMINI_API_KEY in .env.")
    if (
        status == 402
        or "payment required" in text
        or "insufficient credits" in text
        or "insufficient credit" in text
        or "can only afford" in text
        or "credit limit" in text
        or ("requires more credits" in text)
    ):
        return ProviderCallError("credits", CREDITS_MESSAGE)
    if status == 429 or "rate limit" in text or "too many requests" in text:
        return ProviderCallError("rate_limit", "The provider rate-limited this request. Wait and try a smaller task.")
    if "quota" in text or "resource exhausted" in text or ("exceeded" in text and "limit" in text):
        return ProviderCallError("quota", "The daily quota is exhausted. Do not keep retrying until the quota resets.")
    if (
        status == 404
        or "no longer available" in text
        or "no endpoints" in text
        or "model not found" in text
        or "is not a valid model" in text
    ):
        return ProviderCallError(
            "unavailable",
            "That chat model is unavailable on OpenRouter. Set OPENROUTER_MODEL in .env to a current chat/instruct model. This request will not be retried.",
        )
    if "timeout" in text or "timed out" in text:
        return ProviderCallError("timeout", "The model request timed out. Check the network and try again.")
    return ProviderCallError("provider", f"{type(exc).__name__}: {exc}")


def _build_named(name: str):
    if name == "openrouter":
        from llm.openrouter_provider import build_openrouter_chat

        return build_openrouter_chat()
    if name == "gemini":
        from llm.gemini_provider import build_gemini_chat

        return build_gemini_chat()
    raise ProviderConfigError(f"Unknown LLM_PROVIDER '{name}'. Use openrouter or gemini.")


def build_chat_model() -> Any:
    primary = llm_provider_name()
    try:
        return _build_named(primary)
    except ProviderConfigError:
        fallback = fallback_provider_name()
        if fallback and fallback != primary:
            print(f"Primary provider '{primary}' is not configured. Fallback '{fallback}' is enabled.")
            return _build_named(fallback)
        raise
