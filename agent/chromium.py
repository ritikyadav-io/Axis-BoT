"""Resolve Playwright's bundled Chromium for Browser Use on Windows.

Browser Use 0.13.14 looks for chrome-win\\chrome.exe. Playwright 1.64 installs
chrome-win64\\chrome.exe, so the watchdog falls through to system Google Chrome.
If Chrome is already running, that subprocess exits before CDP is ready.
"""

from __future__ import annotations

import glob
import os
from pathlib import Path

PROFILE_LOCK_NAMES = ("SingletonLock", "SingletonSocket", "SingletonCookie")


class BrowserLaunchError(RuntimeError):
    pass


def _playwright_cache_roots() -> list[Path]:
    roots: list[Path] = []
    env_path = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if env_path:
        roots.append(Path(env_path))
    local_app = os.environ.get("LOCALAPPDATA")
    if local_app:
        roots.append(Path(local_app) / "ms-playwright")
    return roots


def playwright_chromium_executable() -> Path:
    """Locate Playwright Chromium without starting the Playwright driver.

    Must not call Playwright's Sync API from an asyncio loop (Browser Use runs in asyncio).
    """
    patterns = [
        "chromium-*/chrome-win64/chrome.exe",
        "chromium-*/chrome-win/chrome.exe",
        "chromium-*/chrome-linux/chrome",
        "chromium-*/chrome-mac*/Chromium.app/Contents/MacOS/Chromium",
    ]
    matches: list[str] = []
    for root in _playwright_cache_roots():
        for pattern in patterns:
            matches.extend(glob.glob(str(root / pattern)))
    files = [item for item in matches if Path(item).is_file() and "headless_shell" not in item.lower()]
    if files:
        files.sort()
        return Path(files[-1])
    raise BrowserLaunchError(
        "Playwright Chromium was not found. Install it with: "
        r".\.venv\Scripts\python.exe -m playwright install chromium"
    )


def clear_stale_profile_locks(profile_dir: Path) -> list[str]:
    removed: list[str] = []
    if not profile_dir.exists():
        return removed
    for name in PROFILE_LOCK_NAMES:
        lock_path = profile_dir / name
        if lock_path.exists():
            try:
                lock_path.unlink()
                removed.append(name)
            except OSError:
                pass
    return removed


def kill_orphaned_agent_browsers(profile_dir: Path) -> list[int]:
    """Kill chrome processes that were started with this project's user-data-dir only."""
    try:
        import psutil
    except ImportError:
        return []

    marker = str(profile_dir).lower()
    killed: list[int] = []
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            name = (proc.info.get("name") or "").lower()
            if "chrome" not in name and "chromium" not in name:
                continue
            cmd = " ".join(proc.info.get("cmdline") or []).lower()
            if marker not in cmd:
                continue
            proc.kill()
            killed.append(proc.info["pid"])
        except (psutil.Error, TypeError, KeyError):
            continue
    return killed


def format_browser_launch_error(exc: BaseException, executable: Path | None) -> str:
    text = str(exc).strip() or type(exc).__name__
    lines = [
        "Chromium failed to start before CDP was ready.",
        f"Underlying error: {type(exc).__name__}: {text}",
    ]
    if executable is not None:
        lines.append(f"Executable: {executable}")
    lines.append("I will not keep retrying a browser that exits immediately.")
    lines.append("Close leftover agent Chromium windows, then try again. Your everyday Google Chrome windows can stay open.")
    return "\n".join(lines)
