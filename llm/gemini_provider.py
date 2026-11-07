from __future__ import annotations

from config import gemini_api_key, gemini_model, is_configured
from llm.provider import ProviderConfigError


def build_gemini_chat():
    from browser_use import ChatGoogle

    if not (is_configured("GEMINI_API_KEY") or is_configured("GOOGLE_API_KEY")):
        raise ProviderConfigError("GEMINI_API_KEY is missing. Gemini is optional; set LLM_PROVIDER=groq or add a Gemini key.")

    permissive_config = {
        "safety_settings": [
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
        ]
    }
    return ChatGoogle(model=gemini_model(), api_key=gemini_api_key(), config=permissive_config)
