"""Standalone Playwright Chromium check. Does not use Browser Use or OpenRouter."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        executable = Path(playwright.chromium.executable_path)
        print(f"Playwright Chromium executable: {executable}")
        print(f"Exists: {executable.is_file()}")
        browser = playwright.chromium.launch(headless=False)
        print(f"Browser version: {browser.version}")
        page = browser.new_page()
        page.goto("https://example.com", wait_until="domcontentloaded", timeout=30000)
        print(f"Page title: {page.title()}")
        print(f"Page url: {page.url}")
        browser.close()
    print("Standalone Chromium: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
