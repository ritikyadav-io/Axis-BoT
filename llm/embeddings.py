"""OpenRouter embeddings. Never used as the Browser Use chat model."""

from __future__ import annotations

import time
from typing import Sequence

import httpx

from config import is_configured, load_environment, openrouter_api_key, openrouter_embedding_model
from llm.provider import ProviderCallError, classify_provider_error

OPENROUTER_URL = "https://openrouter.ai/api/v1/embeddings"


def embed_texts(texts: str | Sequence[str], timeout: float = 30.0) -> list[list[float]]:
    load_environment()
    if not is_configured("OPENROUTER_API_KEY"):
        raise ProviderCallError("invalid_key", "OPENROUTER_API_KEY is not configured.")
    payload_input: str | list[str]
    if isinstance(texts, str):
        payload_input = texts
    else:
        payload_input = [str(item) for item in texts]
        if not payload_input:
            return []

    headers = {
        "Authorization": f"Bearer {openrouter_api_key()}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://localhost",
    }
    body = {"model": openrouter_embedding_model(), "input": payload_input}
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            response = httpx.post(OPENROUTER_URL, headers=headers, json=body, timeout=timeout)
        except httpx.HTTPError as exc:
            last_error = exc
            time.sleep(2**attempt)
            continue
        if response.status_code == 429:
            time.sleep(2**attempt)
            last_error = RuntimeError("rate limit")
            continue
        if response.status_code in {401, 402, 404}:
            raise classify_provider_error(RuntimeError(f"status {response.status_code} {response.text[:200]}"))
        if response.status_code >= 500:
            last_error = RuntimeError(f"status {response.status_code}")
            time.sleep(2**attempt)
            continue
        if response.status_code >= 400:
            raise classify_provider_error(RuntimeError(response.text[:300]))
        data = response.json()
        items = data.get("data") or []
        vectors = [item.get("embedding") or [] for item in sorted(items, key=lambda row: row.get("index", 0))]
        return vectors
    raise classify_provider_error(last_error or RuntimeError("embedding request failed"))


def embed_text(text: str) -> list[float]:
    vectors = embed_texts(text)
    return vectors[0] if vectors else []
