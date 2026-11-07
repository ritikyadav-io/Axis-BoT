from __future__ import annotations

import os
import re
import sys
from typing import Any

from config import (
    fallback_provider_name,
    is_configured,
    llm_provider_name,
    tertiary_provider_name,
)

CREDITS_MESSAGE = (
    "OpenRouter rejected this request because your account balance or API key credit "
    "limit is insufficient. Check your OpenRouter Credits and API Key settings."
)


def safe_print(*args: Any, **kwargs: Any) -> None:
    """Print to stdout without crashing on Windows cp1252/charmap unicode characters."""
    sep = kwargs.get("sep", " ")
    end = kwargs.get("end", "\n")
    text = sep.join(str(a) for a in args) + end
    try:
        sys.stdout.write(text)
        sys.stdout.flush()
    except (UnicodeEncodeError, UnicodeError):
        encoding = getattr(sys.stdout, "encoding", None) or "ascii"
        clean = text.encode(encoding, errors="replace").decode(encoding)
        sys.stdout.write(clean)
        sys.stdout.flush()
    except Exception:
        pass


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
    redacted = re.sub(r"sk-or-v1-[A-Za-z0-9]+", "[REDACTED]", text)
    redacted = re.sub(r"gsk_[A-Za-z0-9]+", "[REDACTED]", redacted)
    return redacted


def classify_provider_error(exc: BaseException) -> ProviderCallError:
    text = _redact(str(exc).lower())
    status = _status_from_error(exc, text)
    if status == 401 or "invalid api key" in text or "incorrect api key" in text or "authentication" in text:
        return ProviderCallError("invalid_key", "The API key was rejected. Verify your keys in .env.")
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
    if status == 429 or "rate limit" in text or "too many requests" in text or "tokens per day" in text:
        return ProviderCallError("rate_limit", "The provider rate-limited this request. Daily or RPM limit reached.")
    if "quota" in text or "resource exhausted" in text or ("exceeded" in text and "limit" in text):
        return ProviderCallError("quota", "The daily quota is exhausted.")
    if (
        status == 404
        or "no longer available" in text
        or "no endpoints" in text
        or "model not found" in text
        or "is not a valid model" in text
    ):
        return ProviderCallError(
            "unavailable",
            "That chat model is unavailable or retired on the provider. Set a valid chat model in .env. This request will not be retried.",
        )
    if "timeout" in text or "timed out" in text:
        return ProviderCallError("timeout", "The model request timed out. Check the network and try again.")
    return ProviderCallError("provider", f"{type(exc).__name__}: {exc}")


def _build_named(name: str):
    provider = (name or "").strip().lower()
    if provider == "groq":
        from llm.groq_provider import build_groq_chat

        return build_groq_chat()
    if provider == "openrouter":
        from llm.openrouter_provider import build_openrouter_chat

        return build_openrouter_chat()
    if provider == "gemini":
        from llm.gemini_provider import build_gemini_chat

        return build_gemini_chat()
    raise ProviderConfigError(f"Unknown LLM_PROVIDER '{name}'. Use groq, openrouter, or gemini.")


def _flatten_messages_for_text_models(messages: Any) -> Any:
    """Ensure message content is a plain string for text-only models like Groq."""
    if not isinstance(messages, (list, tuple)):
        return messages

    out = []
    for m in messages:
        content = getattr(m, "content", None)
        if isinstance(content, list):
            text_parts = []
            for part in content:
                txt = getattr(part, "text", None) or (part.get("text") if isinstance(part, dict) else None)
                if txt:
                    text_parts.append(str(txt))
            flattened = "\n".join(text_parts) if text_parts else "..."
            msg_type = type(m)
            try:
                out.append(msg_type(content=flattened))
            except Exception:
                out.append(m)
        else:
            out.append(m)
    return out


class FallbackChainChatModel:
    """Resilient multi-tier LLM wrapper.

    Order of priority requested by user:
      1st: Groq (ultra-fast, large daily token quota)
      2nd: OpenRouter (broad model catalog)
      3rd: Gemini (fallback)

    If a provider hits daily quota, rate limits, credit limits, or API errors,
    it automatically fails over to the next configured provider so automation never halts.
    """

    def __init__(self, candidates: list[tuple[str, Any]]) -> None:
        if not candidates:
            raise ProviderConfigError("No LLM provider could be initialized. Please configure GROQ_API_KEY, OPENROUTER_API_KEY, or GEMINI_API_KEY.")
        self._candidates = candidates
        self._current_index = 0
        self._agent = None
        self._fatal = None

    @property
    def active_name(self) -> str:
        return self._candidates[self._current_index][0]

    @property
    def active_model(self) -> Any:
        return self._candidates[self._current_index][1]

    @property
    def provider(self) -> str:
        return getattr(self.active_model, "provider", self.active_name)

    @property
    def model(self) -> str:
        return getattr(self.active_model, "model", self.active_name)

    @property
    def model_name(self) -> str:
        return getattr(self.active_model, "model_name", self.model)

    @property
    def name(self) -> str:
        return getattr(self.active_model, "name", str(self.model))

    def bind_agent(self, agent: Any) -> None:
        self._agent = agent
        for _, model in self._candidates:
            binder = getattr(model, "bind_agent", None)
            if callable(binder):
                try:
                    binder(agent)
                except Exception:
                    pass

    def __getattr__(self, name: str) -> Any:
        return getattr(self.active_model, name)

    async def ainvoke(self, messages: Any, *args: Any, **kwargs: Any) -> Any:
        total = len(self._candidates)
        last_error = None

        for attempt in range(total):
            idx = (self._current_index + attempt) % total
            provider_name, model = self._candidates[idx]

            # Flatten text for Groq if vision/list content is passed
            call_messages = _flatten_messages_for_text_models(messages) if provider_name == "groq" else messages

            try:
                res = await model.ainvoke(call_messages, *args, **kwargs)
                if idx != self._current_index:
                    safe_print(f"✅ Successfully completed step using fallback provider '{provider_name}'.")
                    self._current_index = idx
                return res
            except Exception as exc:
                last_error = exc
                classified = classify_provider_error(exc)
                safe_print(f"\n[LLM Notice] Provider '{provider_name}' encountered {classified.kind}: {classified}")

                if attempt < total - 1:
                    next_name = self._candidates[(self._current_index + attempt + 1) % total][0]
                    safe_print(f"[LLM Fallback] Seamlessly switching to next provider: '{next_name}'...")
                else:
                    safe_print("❌ All configured LLM providers in fallback chain failed.")
                    raise classified from exc

        if last_error:
            raise last_error


def build_chat_model() -> Any:
    """Builds the fallback chain in priority order: Groq -> OpenRouter -> Gemini."""
    priority_order = ["groq", "openrouter", "gemini"]

    # Reorder if user specified a custom primary in environment
    primary = llm_provider_name()
    fb = fallback_provider_name()
    tert = tertiary_provider_name()

    chain = [primary]
    for p in (fb, tert, "groq", "openrouter", "gemini"):
        if p and p not in chain:
            chain.append(p)

    candidates: list[tuple[str, Any]] = []
    errors: list[str] = []

    for name in chain:
        try:
            model = _build_named(name)
            candidates.append((name, model))
        except ProviderConfigError as exc:
            errors.append(f"{name}: {exc}")
        except Exception as exc:
            errors.append(f"{name} init failed: {exc}")

    if not candidates:
        msg = "No LLM providers could be initialized:\n  " + "\n  ".join(errors)
        raise ProviderConfigError(msg)

    if len(candidates) == 1 and candidates[0][0] != "groq":
        return candidates[0][1]

    return FallbackChainChatModel(candidates)
