"""Interactive personal AI browser agent.

Type a plain-English task. The configured LLM (OpenRouter by default) plans
the work. Browser Use drives a visible Chromium window.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from agent.browser_agent import (  # noqa: F401
    BROWSER_DATA_DIR,
    PROFILE_DIR,
    ask_yes_no,
    build_browser_session,
    build_llm,
    build_tools,
    configure_windows_console,
    interactive_loop,
    print_history_result,
    revive_browser_event_bus,
    run_browser_task,
)
from agent.safety import SAFETY_INSTRUCTIONS, SENSITIVE_PATTERNS, looks_sensitive
from config import is_configured, load_environment, llm_provider_name, startup_summary


def verify_python() -> None:
    if sys.version_info[:2] != (3, 12):
        raise RuntimeError(f"Expected Python 3.12 in this project, found {sys.version.split()[0]}")
    print(f"Python: {sys.version.split()[0]} ({sys.executable})")


def verify_imports() -> None:
    import browser_use
    import playwright
    from dotenv import dotenv_values
    from google import genai
    from playwright.sync_api import sync_playwright

    print(f"browser-use: {getattr(browser_use, '__version__', 'imported')}")
    print(f"playwright: {getattr(playwright, '__version__', 'imported')}")
    print(f"python-dotenv: {dotenv_values.__module__}")
    print(f"google-genai: {genai.__name__}")
    print(f"playwright.sync_api: {sync_playwright.__name__}")


def verify_chromium_navigation() -> None:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto("https://example.com", wait_until="domcontentloaded", timeout=30000)
        title = page.title()
        browser.close()
    if "example" not in title.lower():
        raise RuntimeError(f"Unexpected page title: {title}")
    print(f"Chromium navigation: opened https://example.com, title={title}")


def verify_browser_search() -> None:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto("https://www.google.com/search?q=example", wait_until="domcontentloaded", timeout=30000)
        title = page.title()
        browser.close()
    print(f"Browser search (no LLM): Google title={title}")


def verify_browser_use_api() -> None:
    from browser_use import Agent, BrowserSession, ChatGoogle, ChatOpenRouter, Tools

    print(
        "Browser Use API: "
        f"Agent={Agent.__name__}, ChatOpenRouter={ChatOpenRouter.__name__}, "
        f"ChatGoogle={ChatGoogle.__name__}, BrowserSession={BrowserSession.__name__}, Tools={Tools.__name__}"
    )


def verify_provider_init() -> None:
    from llm.provider import ProviderConfigError, build_chat_model

    for line in startup_summary():
        print(line)
    try:
        model = build_chat_model()
        print(f"Chat model class: {type(model).__name__} (no live API call)")
        print(f"Chat model name: {getattr(model, 'model', llm_provider_name())}")
    except ProviderConfigError as exc:
        print(f"Chat model init skipped: {exc}")


def verify_embedding_config() -> None:
    from config import is_embedding_model, openrouter_chat_model, openrouter_embedding_model

    chat = openrouter_chat_model()
    embed = openrouter_embedding_model()
    print(f"Embedding model configured: {embed}")
    if is_embedding_model(chat):
        raise RuntimeError("OPENROUTER_MODEL is an embedding model. That is not allowed for Browser Use.")
    print("Chat model is not an embedding model.")


def verify_openrouter_catalog() -> None:
    """Public model list only. Does not send the API key or start a chat completion."""
    import httpx

    from config import openrouter_chat_model

    model_id = openrouter_chat_model()
    response = httpx.get("https://openrouter.ai/api/v1/models", timeout=30.0)
    response.raise_for_status()
    rows = {row.get("id"): row for row in response.json().get("data") or []}
    info = rows.get(model_id)
    if info is None:
        raise RuntimeError(f"{model_id} is not in OpenRouter's current catalog.")
    params = info.get("supported_parameters") or []
    print(f"OpenRouter catalog: exact id found ({info.get('name') or model_id})")
    print(
        "Browser Use 0.13 compatibility: "
        f"tools={'tools' in params}, tool_choice={'tool_choice' in params}, "
        f"response_format={'response_format' in params}, structured_outputs={'structured_outputs' in params}"
    )
    missing = [name for name in ("tools", "response_format") if name not in params]
    if missing:
        raise RuntimeError(f"{model_id} is missing catalog parameters Browser Use needs: {missing}")


def run_self_test() -> int:
    print("=== Self-test ===")
    verify_python()
    verify_imports()
    verify_browser_use_api()
    verify_provider_init()
    verify_embedding_config()
    verify_openrouter_catalog()
    verify_chromium_navigation()
    verify_browser_search()
    if is_configured("GEMINI_API_KEY") or is_configured("GOOGLE_API_KEY"):
        print("Gemini credentials: present (value hidden). Live Gemini calls skipped in --self-test.")
    else:
        print("Gemini credentials: not configured (optional).")
    print("Live OpenRouter chat/embedding HTTP calls: skipped in --self-test to avoid extra usage.")
    return 0


def main() -> int:
    configure_windows_console()
    load_environment()
    parser = argparse.ArgumentParser(description="Personal AI browser agent")
    parser.add_argument("--self-test", action="store_true", help="Verify the local environment and exit")
    args = parser.parse_args()

    if args.self_test:
        try:
            return run_self_test()
        except Exception as exc:
            print(f"SELF-TEST FAILED: {type(exc).__name__}: {exc}")
            return 1

    try:
        verify_python()
    except RuntimeError as exc:
        print(exc)
        return 1

    asyncio.run(interactive_loop())
    return 0


if __name__ == "__main__":
    sys.exit(main())
