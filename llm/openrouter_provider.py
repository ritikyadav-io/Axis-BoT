from __future__ import annotations

from typing import Any

from config import is_configured, openrouter_api_key, openrouter_chat_model, validate_chat_model
from llm.provider import (
    CREDITS_MESSAGE,
    NON_RETRYABLE_KINDS,
    ProviderCallError,
    ProviderConfigError,
    classify_provider_error,
    safe_print,
)


class FailFastChatModel:
    """Stops HTTP retries after a permanent provider error such as HTTP 404."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self._fatal: ProviderCallError | None = None
        self._agent = None
        self._announced = False

    def bind_agent(self, agent: Any) -> None:
        self._agent = agent

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def _halt_agent(self) -> None:
        agent = self._agent
        if agent is None:
            return
        state = getattr(agent, "state", None)
        if state is not None:
            state.stopped = True

    def _announce(self, error: ProviderCallError) -> None:
        if self._announced:
            return
        self._announced = True
        model = getattr(self._inner, "model", "the configured model")
        if error.kind == "unavailable":
            safe_print(f"\n❌ Model unavailable (HTTP 404): {model}")
            safe_print("OpenRouter reports this chat model is missing, renamed, or withdrawn.")
            safe_print("Update OPENROUTER_MODEL in .env to a current chat/instruct model. I will not retry this model.")
            return
        if error.kind == "credits":
            safe_print(f"\n❌ {CREDITS_MESSAGE}")
            safe_print("The configured free chat model was not changed. I will not retry this request.")
            return
        safe_print(f"\n❌ Provider error ({error.kind}): {error}")

    async def ainvoke(self, *args: Any, **kwargs: Any):
        if self._fatal is not None:
            raise self._fatal
        try:
            return await self._inner.ainvoke(*args, **kwargs)
        except ProviderCallError as exc:
            if exc.kind in NON_RETRYABLE_KINDS:
                self._fatal = exc
                self._announce(exc)
                self._halt_agent()
            raise
        except Exception as exc:
            classified = classify_provider_error(exc)
            if classified.kind in NON_RETRYABLE_KINDS:
                self._fatal = classified
                self._announce(classified)
                self._halt_agent()
                raise classified from exc
            raise


def build_openrouter_chat():
    from browser_use import ChatOpenRouter

    if not is_configured("OPENROUTER_API_KEY"):
        raise ProviderConfigError("OPENROUTER_API_KEY is missing. Add it to .env from https://openrouter.ai/keys")
    model = openrouter_chat_model()
    problem = validate_chat_model(model, "openrouter")
    if problem:
        raise ProviderConfigError(problem)
    inner = ChatOpenRouter(
        model=model,
        api_key=openrouter_api_key(),
        base_url="https://openrouter.ai/api/v1",
        http_referer="https://localhost",
        max_retries=0,
        timeout=60,
    )
    return FailFastChatModel(inner)


def probe_openrouter_account() -> None:
    """Check OpenRouter key/credit status without a chat completion.

    Uses GET /api/v1/key only. Does not switch models and does not send prompts.
    """
    import httpx

    if not is_configured("OPENROUTER_API_KEY"):
        raise ProviderConfigError("OPENROUTER_API_KEY is missing. Add it to .env from https://openrouter.ai/keys")
    problem = validate_chat_model(openrouter_chat_model(), "openrouter")
    if problem:
        raise ProviderConfigError(problem)
    headers = {
        "Authorization": f"Bearer {openrouter_api_key()}",
        "HTTP-Referer": "https://localhost",
    }
    try:
        response = httpx.get("https://openrouter.ai/api/v1/key", headers=headers, timeout=20.0)
    except httpx.HTTPError as exc:
        raise classify_provider_error(exc) from exc
    if response.status_code == 402:
        raise ProviderCallError("credits", CREDITS_MESSAGE)
    if response.status_code in {401, 403}:
        raise classify_provider_error(RuntimeError(f"status {response.status_code} {response.text[:200]}"))
    if response.status_code == 429:
        raise classify_provider_error(RuntimeError("status 429 rate limit"))
    if response.status_code >= 400:
        raise classify_provider_error(RuntimeError(f"status {response.status_code} {response.text[:200]}"))
    payload = {}
    try:
        payload = response.json()
    except ValueError:
        return
    data = payload.get("data") or payload
    remaining = data.get("limit_remaining")
    if remaining is not None:
        try:
            if float(remaining) <= 0:
                raise ProviderCallError("credits", CREDITS_MESSAGE)
        except (TypeError, ValueError):
            return
