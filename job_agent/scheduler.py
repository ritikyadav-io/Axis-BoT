"""Start/stop local job-discovery schedules.

Local schedules only run while this process and the laptop are awake.
Deploy later on a cloud VM if you need 24/7 monitoring.
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from job_agent.config import load_environment, load_schedule
from job_agent.paths import PID_PATH, STOP_PATH, ensure_runtime_dirs
from job_agent.pipeline import run_discovery_and_match, write_daily_summary, write_weekly_report


def _write_pid() -> None:
    ensure_runtime_dirs()
    PID_PATH.write_text(str(os.getpid()), encoding="utf-8")
    if STOP_PATH.exists():
        STOP_PATH.unlink()


def _clear_pid() -> None:
    if PID_PATH.exists():
        PID_PATH.unlink()


def scheduler_status() -> str:
    if STOP_PATH.exists():
        return "stop requested"
    if not PID_PATH.exists():
        return "stopped"
    pid = PID_PATH.read_text(encoding="utf-8").strip()
    return f"running (pid {pid})"


def request_stop() -> str:
    ensure_runtime_dirs()
    STOP_PATH.write_text("stop", encoding="utf-8")
    if PID_PATH.exists():
        pid_text = PID_PATH.read_text(encoding="utf-8").strip()
        try:
            os.kill(int(pid_text), signal.SIGTERM)
        except OSError:
            _clear_pid()
            return "scheduler was not running; stop file written"
        return f"sent stop signal to pid {pid_text}"
    return "scheduler was not running"


def _should_stop(scheduler: BlockingScheduler) -> None:
    if STOP_PATH.exists():
        scheduler.shutdown(wait=False)


def build_scheduler() -> BlockingScheduler:
    load_environment()
    config = load_schedule()
    timezone = config.get("timezone") or "Asia/Kolkata"
    scheduler = BlockingScheduler(timezone=timezone)
    jobs = config.get("jobs") or {}

    def morning() -> None:
        print("Running morning discovery...")
        print(run_discovery_and_match())

    def evening() -> None:
        print("Running evening discovery...")
        print(run_discovery_and_match())

    def summary() -> None:
        print("Writing daily summary...")
        print(write_daily_summary())

    def weekly() -> None:
        print("Writing weekly report...")
        print(write_weekly_report())

    mapping = {
        "morning_discovery": morning,
        "evening_discovery": evening,
        "daily_summary": summary,
        "weekly_report": weekly,
    }
    for name, func in mapping.items():
        spec = jobs.get(name) or {}
        if not spec.get("enabled", True):
            continue
        trigger_kwargs = {"hour": spec.get("hour", 0), "minute": spec.get("minute", 0)}
        if spec.get("day_of_week"):
            trigger_kwargs["day_of_week"] = spec["day_of_week"]
        scheduler.add_job(func, CronTrigger(**trigger_kwargs, timezone=timezone), id=name, replace_existing=True)
        print(f"Scheduled {name}: {spec.get('description') or name}")

    scheduler.add_job(lambda: _should_stop(scheduler), "interval", seconds=15, id="stop_watcher", replace_existing=True)
    return scheduler


def start_scheduler() -> int:
    print("Local scheduler starting.")
    print("This only runs while the laptop is on and this window stays open.")
    print("For 24/7 monitoring later, run the same command on a cloud server.")
    print(f"Timezone and hours: {load_schedule().get('timezone')}")
    _write_pid()
    scheduler = build_scheduler()
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        print("Scheduler stopped.")
    finally:
        _clear_pid()
        if STOP_PATH.exists():
            STOP_PATH.unlink()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Job-hunting scheduler")
    parser.add_argument("command", nargs="?", default="start", choices=["start", "stop", "status"])
    args = parser.parse_args()
    if args.command == "start":
        return start_scheduler()
    if args.command == "stop":
        print(request_stop())
        return 0
    print(scheduler_status())
    return 0


if __name__ == "__main__":
    sys.exit(main())
