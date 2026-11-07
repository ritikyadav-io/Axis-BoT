from __future__ import annotations

import argparse
import json
import sys

from job_agent.application import ApprovalRequired, open_application_page, prepare_application, set_application_approval
from job_agent.config import load_environment
from job_agent.database import JobStore
from job_agent.notifications import test_telegram_connection
from job_agent.pipeline import run_discovery_and_match, write_daily_summary, write_weekly_report
from job_agent.scheduler import main as scheduler_main, scheduler_status


def main() -> int:
    load_environment()
    parser = argparse.ArgumentParser(description="Personal AI job-hunting commands")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("discover")
    sub.add_parser("telegram-test")
    sub.add_parser("summary")
    sub.add_parser("weekly")
    sub.add_parser("status")
    sched = sub.add_parser("scheduler")
    sched.add_argument("action", choices=["start", "stop", "status"])
    for name in ("preview", "approve", "deny", "open", "submit"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--job-id", type=int, required=True)
    args = parser.parse_args()

    if args.command == "discover":
        result = run_discovery_and_match()
        print(json.dumps({k: v for k, v in result.items() if k != "job_ids"}, indent=2))
        print(f"Stored {result['inserted']} new jobs ({result['duplicates']} duplicates).")
        print(f"Telegram alerts sent: {result.get('notified', 0)} (verified jobs scoring 80%+ only).")
        return 0
    if args.command == "telegram-test":
        result = test_telegram_connection()
        print(json.dumps({k: v for k, v in result.items() if k != "bot_username" or True}, indent=2))
        return 0 if result.get("ok") else 1
    if args.command == "summary":
        print(write_daily_summary())
        return 0
    if args.command == "weekly":
        print(write_weekly_report())
        return 0
    if args.command == "status":
        stats = JobStore().stats()
        print(json.dumps({"scheduler": scheduler_status(), **stats}, indent=2))
        return 0
    if args.command == "scheduler":
        sys.argv = ["job_agent.scheduler", args.action]
        return scheduler_main()
    if args.command == "preview":
        print(json.dumps(prepare_application(args.job_id), indent=2))
        return 0
    if args.command == "approve":
        print(json.dumps(set_application_approval(args.job_id, True), indent=2))
        return 0
    if args.command == "deny":
        print(json.dumps(set_application_approval(args.job_id, False), indent=2))
        return 0
    if args.command in {"open", "submit"}:
        import asyncio

        try:
            result = asyncio.run(open_application_page(args.job_id, submit=args.command == "submit"))
        except ApprovalRequired as exc:
            print(exc)
            return 1
        print(json.dumps({k: v for k, v in result.items() if k != "result"}, indent=2))
        if result.get("result"):
            print(result["result"])
        return 0
    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
