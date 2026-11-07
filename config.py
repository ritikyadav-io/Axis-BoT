"""Root LLM and agent configuration. Secrets stay in .env."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent
EMBEDDING_MARKERS = ("embed", "embedding")
PLACEHOLDERS = {"", "your-key", "changeme", "paste_here", "your_openrouter_api_key_here"}


def load_environment() -> None:
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    gemini_key = (os.getenv("GEMINI_API_KEY") or "").strip()
    google_key = (os.getenv("GOOGLE_API_KEY") or "").strip()
    if gemini_key and not google_key:
        os.environ["GOOGLE_API_KEY"] = gemini_key
    os.environ.setdefault("BROWSER_USE_HEADLESS", "false")
    os.environ.setdefault("ANONYMIZED_TELEMETRY", "false")
    os.environ.setdefault("LLM_PROVIDER", "groq")
    os.environ.setdefault("FALLBACK_PROVIDER", "openrouter")
    os.environ.setdefault("TERTIARY_PROVIDER", "gemini")


def update_env_value(key: str, value: str) -> None:
    """Updates or adds an environment variable in the .env file and in os.environ."""
    env_file = PROJECT_ROOT / ".env"
    text = env_file.read_text(encoding="utf-8") if env_file.exists() else ""
    pattern = rf"^{re.escape(key)}=.*$"
    new_line = f"{key}={value}"
    if re.search(pattern, text, flags=re.MULTILINE):
        updated = re.sub(pattern, new_line, text, flags=re.MULTILINE)
    else:
        updated = text.rstrip() + f"\n{new_line}\n"
    env_file.write_text(updated, encoding="utf-8")
    os.environ[key] = value


def _secret(name: str) -> str:
    return (os.getenv(name) or "").strip()


def is_configured(name: str) -> bool:
    value = _secret(name)
    return bool(value) and value.lower() not in PLACEHOLDERS


def describe_secret(name: str) -> str:
    if not is_configured(name):
        return "not configured"
    return f"detected ({len(_secret(name))} characters, value hidden)"


def is_embedding_model(model: str) -> bool:
    lowered = (model or "").lower()
    return any(marker in lowered for marker in EMBEDDING_MARKERS)


def llm_provider_name() -> str:
    return (os.getenv("LLM_PROVIDER") or "groq").strip().lower() or "groq"


def fallback_provider_name() -> str:
    return (os.getenv("FALLBACK_PROVIDER") or "openrouter").strip().lower()


def tertiary_provider_name() -> str:
    return (os.getenv("TERTIARY_PROVIDER") or "gemini").strip().lower()


def groq_api_key() -> str:
    return _secret("GROQ_API_KEY")


DEFAULT_GROQ_CHAT_MODEL = "openai/gpt-oss-120b"


def groq_model() -> str:
    return (os.getenv("GROQ_MODEL") or DEFAULT_GROQ_CHAT_MODEL).strip()


def openrouter_api_key() -> str:
    return _secret("OPENROUTER_API_KEY")


DEFAULT_OPENROUTER_CHAT_MODEL = "nvidia/nemotron-3.5-super-vl:free"


def openrouter_chat_model() -> str:
    return (os.getenv("OPENROUTER_MODEL") or DEFAULT_OPENROUTER_CHAT_MODEL).strip()


def openrouter_embedding_model() -> str:
    return (os.getenv("OPENROUTER_EMBEDDING_MODEL") or "nvidia/nemotron-3.5-embed-1b:free").strip()


def gemini_api_key() -> str:
    return _secret("GEMINI_API_KEY") or _secret("GOOGLE_API_KEY")


def gemini_model() -> str:
    return (os.getenv("GEMINI_MODEL") or "gemini-2.5-flash").strip()


def validate_chat_model(model: str, provider: str) -> str | None:
    if not model:
        return f"{provider} chat model is empty."
    if is_embedding_model(model):
        return (
            f"{provider} chat model '{model}' looks like an embedding model. "
            "Browser Use needs a chat/instruct model. Put embedding models in OPENROUTER_EMBEDDING_MODEL only."
        )
    return None


def startup_summary() -> list[str]:
    lines = [
        f"Active LLM: {llm_provider_name()} (1st) -> {fallback_provider_name() or 'none'} (2nd) -> {tertiary_provider_name() or 'none'} (3rd)",
        f"Groq key: {describe_secret('GROQ_API_KEY')} | model: {groq_model()}",
        f"OpenRouter key: {describe_secret('OPENROUTER_API_KEY')} | model: {openrouter_chat_model()}",
        f"Gemini key: {describe_secret('GEMINI_API_KEY') if is_configured('GEMINI_API_KEY') else describe_secret('GOOGLE_API_KEY')} | model: {gemini_model()}",
    ]
    warning = validate_chat_model(openrouter_chat_model(), "openrouter")
    if warning:
        lines.append("Config warning: " + warning)
    return lines

