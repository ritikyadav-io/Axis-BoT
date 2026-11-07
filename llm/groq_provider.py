from __future__ import annotations

from typing import Any

from config import groq_api_key, groq_model, is_configured
from llm.provider import ProviderConfigError


def build_groq_chat():
    from browser_use import ChatGroq

    if not is_configured("GROQ_API_KEY"):
        raise ProviderConfigError("GROQ_API_KEY is missing. Add it to .env from https://console.groq.com/keys")

    model = groq_model()
    return ChatGroq(
        model=model,
        api_key=groq_api_key(),
        timeout=45.0,
        max_retries=3,
    )


def probe_groq_account() -> None:
    from groq import Groq

    if not is_configured("GROQ_API_KEY"):
        raise ProviderConfigError("GROQ_API_KEY is missing. Add it to .env from https://console.groq.com/keys")

    client = Groq(api_key=groq_api_key(), timeout=10.0)
    # Fast lightweight test by retrieving models list
    client.models.list()
