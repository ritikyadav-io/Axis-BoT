"""Browser Use launch test without OpenRouter chat calls."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


async def main() -> int:
    from agent.browser_agent import PROFILE_DIR, build_browser_session, ensure_browser_started
    from agent.chromium import kill_orphaned_agent_browsers

    session = None
    try:
        session = build_browser_session()
        print("Starting Browser Use session...")
        await ensure_browser_started(session)
        print(f"CDP URL: {session.cdp_url}")

        page = await session.must_get_current_page()
        await page.goto("https://example.com")
        title = await page.get_title()
        print(f"Browser Use example.com title: {title}")

        await page.goto("https://www.google.com/search?q=example")
        search_title = await page.get_title()
        print(f"Browser Use Google search title: {search_title}")

        await page.goto("https://example.com")
        second_title = await page.get_title()
        print(f"Second consecutive task title: {second_title}")
        print("Two consecutive Browser Use navigations: OK")
    finally:
        if session is not None:
            try:
                await session.kill()
                print("Browser Use shutdown: OK")
            except Exception as exc:
                print(f"Shutdown warning: {exc}")
        leftovers = kill_orphaned_agent_browsers(PROFILE_DIR)
        if leftovers:
            print(f"Killed leftover agent Chromium PIDs: {leftovers}")
        else:
            print("No leftover agent Chromium processes.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except Exception as exc:
        print(f"BROWSER USE LAUNCH TEST FAILED: {type(exc).__name__}: {exc}")
        raise SystemExit(1)
