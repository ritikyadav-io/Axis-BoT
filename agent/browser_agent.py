from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from agent.chromium import (
    BrowserLaunchError,
    clear_stale_profile_locks,
    format_browser_launch_error,
    kill_orphaned_agent_browsers,
    playwright_chromium_executable,
)
from agent.memory import TaskMemory
from agent.nl import normalize_instruction
from agent.prompts import OPERATING_INSTRUCTIONS
from agent.recovery import FailureTracker
from agent.safety import SAFETY_INSTRUCTIONS, looks_sensitive
from agent.settings import agent_max_retries, agent_max_steps, agent_memory_enabled, agent_verbose, configure_agent_logging
from config import load_environment, startup_summary
from llm.provider import CREDITS_MESSAGE, ProviderCallError, ProviderConfigError, classify_provider_error

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BROWSER_DATA_DIR = PROJECT_ROOT / "browser-data"
PROFILE_DIR = BROWSER_DATA_DIR / "profile"
PROMPT = "👉 What should I do?\n"
PROMPT_FALLBACK = "> What should I do?\n"


def configure_windows_console() -> None:
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    for stream in (sys.stdout, sys.stderr, sys.stdin):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def prompt_text() -> str:
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    try:
        PROMPT.encode(encoding)
        return PROMPT
    except LookupError:
        return PROMPT_FALLBACK
    except UnicodeEncodeError:
        return PROMPT_FALLBACK


async def ask_yes_no(prompt: str) -> bool:
    answer = await asyncio.to_thread(input, prompt)
    return answer.strip().lower() in {"y", "yes"}


def build_tools():
    from browser_use import ActionResult, Tools

    tools = Tools()

    @tools.action(
        "Ask the human operator for explicit yes/no approval before a sensitive action. "
        "Required before purchases, bookings, payments, sending messages/emails, job applications, "
        "deleting data, changing account settings, or sharing personal information."
    )
    async def request_human_approval(reason: str, proposed_action: str) -> ActionResult:
        print("\n⚠️  Approval required")
        print(f"Reason: {reason}")
        print(f"Proposed action: {proposed_action}")
        approved = await ask_yes_no("Type YES to approve, or press Enter to deny: ")
        if approved:
            memory = f"Human approved: {proposed_action}"
            return ActionResult(extracted_content=memory, long_term_memory=memory)
        memory = f"Human denied: {proposed_action}. Do not perform this action."
        return ActionResult(extracted_content=memory, long_term_memory=memory, error=memory)

    return tools


def build_llm():
    from llm.provider import build_chat_model

    return build_chat_model()


def build_browser_session():
    from browser_use import BrowserSession

    BROWSER_DATA_DIR.mkdir(parents=True, exist_ok=True)
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    executable = playwright_chromium_executable()
    kill_orphaned_agent_browsers(PROFILE_DIR)
    removed_locks = clear_stale_profile_locks(PROFILE_DIR)
    if removed_locks:
        print(f"Cleared stale Chromium profile locks: {', '.join(removed_locks)}")
    print(f"Using Playwright Chromium: {executable}")
    return BrowserSession(
        headless=False,
        keep_alive=True,
        is_local=True,
        executable_path=str(executable),
        user_data_dir=str(PROFILE_DIR),
        chromium_sandbox=True,
        highlight_elements=True,
        args=["--remote-allow-origins=*"],
    )


async def ensure_browser_started(session) -> None:
    executable = Path(str(getattr(session.browser_profile, "executable_path", "") or ""))
    try:
        await session.start()
    except Exception as exc:
        kill_orphaned_agent_browsers(PROFILE_DIR)
        raise BrowserLaunchError(format_browser_launch_error(exc, executable if executable.is_file() else None)) from exc


def revive_browser_event_bus(session) -> None:
    event_bus = getattr(session, "event_bus", None)
    if event_bus is None or getattr(event_bus, "event_queue", None) is not None:
        return

    from browser_use.browser.session import ResilientEventBus

    session.event_bus = ResilientEventBus()
    session._register_session_event_handlers()
    session._watchdogs_attached = False


def print_history_result(history) -> None:
    final = history.final_result() if history is not None else None
    if final:
        print("\n✅ Result")
        print(final)
        return

    if history is None:
        print("\n⚠️  The agent returned no history.")
        return

    errors = [error for error in history.errors() if error]
    if errors:
        print("\n❌ The task did not finish cleanly.")
        print(errors[-1])
        return

    if history.is_done():
        success = history.is_successful()
        if success is False:
            print("\n⚠️  The agent marked the task as finished, but not successful.")
        else:
            print("\n✅ Task finished, but no summary text was returned.")
        return

    print("\n⚠️  The agent stopped before it marked the task complete.")


def format_task_failure(exc: BaseException) -> str:
    classified = classify_provider_error(exc)
    return f"{classified.kind}: {classified}"


def task_timeout_seconds() -> float:
    raw = (os.getenv("AGENT_TASK_TIMEOUT") or "600").strip()
    try:
        value = float(raw)
    except ValueError:
        return 600.0
    return value if value > 0 else 600.0


def _history_finished(history) -> bool:
    if history is None:
        return False
    try:
        if history.is_done():
            return True
        success = history.is_successful()
        return success is True
    except Exception:
        return False


async def _stop_hung_agent_run(agent, run_task: asyncio.Task, wait_seconds: float = 2.0) -> None:
    state = getattr(agent, "state", None)
    if state is not None:
        state.stopped = True
    if run_task.done():
        return
    run_task.cancel()
    try:
        await asyncio.wait_for(run_task, timeout=wait_seconds)
    except (TimeoutError, asyncio.CancelledError, Exception):
        pass


async def await_agent_run(
    agent,
    *,
    max_steps: int,
    timeout_seconds: float,
    cleanup_grace_seconds: float = 8.0,
    on_step_end=None,
):
    """Wait for Agent.run() without treating hung cleanup as a failed task.

    Browser Use logs 'Task completed successfully' then still runs event-bus
    shutdown inside Agent.run(). asyncio.wait_for() would wait for that too.
    """
    finished = asyncio.Event()

    async def on_done(history) -> None:
        finished.set()

    agent.register_done_callback = on_done
    run_task = asyncio.create_task(
        agent.run(max_steps=max_steps, on_step_end=on_step_end),
        name="browser-use-agent-run",
    )
    waiter = asyncio.create_task(finished.wait(), name="browser-use-done-waiter")
    try:
        done, _pending = await asyncio.wait(
            {run_task, waiter},
            timeout=timeout_seconds,
            return_when=asyncio.FIRST_COMPLETED,
        )
        if run_task in done:
            waiter.cancel()
            return run_task.result()

        history = getattr(agent, "history", None)
        if finished.is_set() or _history_finished(history):
            try:
                return await asyncio.wait_for(asyncio.shield(run_task), timeout=cleanup_grace_seconds)
            except TimeoutError:
                await _stop_hung_agent_run(agent, run_task)
                print("Task finished. Browser Use cleanup was still running, so control returned to the terminal.")
                print("The browser window was left open for the next command.")
                return history

        await _stop_hung_agent_run(agent, run_task, wait_seconds=5)
        raise TimeoutError(f"The task was still running after {int(timeout_seconds)} seconds.")
    finally:
        if not waiter.done():
            waiter.cancel()


def _step_action_label(agent) -> str:
    output = getattr(getattr(agent, "state", None), "last_model_output", None)
    actions = getattr(output, "action", None) if output is not None else None
    if not actions:
        return "unknown"
    try:
        dumped = actions[0].model_dump(exclude_unset=True)
        return next(iter(dumped.keys()), "unknown")
    except Exception:
        return str(actions)[:120]


async def run_browser_task(instruction: str, llm, browser_session, tools, crash_restarts: list[int] | None = None) -> None:
    from browser_use import Agent

    crash_restarts = crash_restarts if crash_restarts is not None else [0]
    parsed = normalize_instruction(instruction)
    print(parsed.start_message)
    if parsed.plan_steps and not parsed.simple:
        print("Plan: " + " -> ".join(parsed.plan_steps))

    max_steps = agent_max_steps() if parsed.simple else max(agent_max_steps(), 12)
    timeout_seconds = task_timeout_seconds()
    retries = agent_max_retries()
    memory = TaskMemory(objective=parsed.cleaned, kind=parsed.kind) if agent_memory_enabled() else None
    tracker = FailureTracker(max_identical=retries)
    revive_browser_event_bus(browser_session)

    extra = SAFETY_INSTRUCTIONS + "\n\n" + OPERATING_INSTRUCTIONS
    if memory is not None:
        extra += "\n\n" + memory.briefing()

    agent = Agent(
        task=parsed.expanded,
        llm=llm,
        browser=browser_session,
        tools=tools,
        extend_system_message=extra,
        use_vision="auto",
        enable_planning=not parsed.simple,
        use_thinking=False,
        use_judge=False,
        flash_mode=parsed.simple,
        enable_signal_handler=False,
        max_failures=retries,
        final_response_after_failure=False,
        max_actions_per_step=3 if parsed.simple else 4,
        max_history_items=6,
        step_timeout=45,
        llm_timeout=45,
        directly_open_url=True,
        loop_detection_enabled=True,
        llm_screenshot_size=(896, 504),
        message_compaction=True,
    )
    bind_agent = getattr(llm, "bind_agent", None)
    if callable(bind_agent):
        bind_agent(agent)

    async def on_step_end(agent_obj) -> None:
        results = getattr(getattr(agent_obj, "state", None), "last_result", None) or []
        errors = [str(getattr(item, "error", "") or "") for item in results if getattr(item, "error", None)]
        if memory is not None:
            try:
                memory.current_url = await agent_obj.browser_session.get_current_page_url()
            except Exception:
                pass
            if not errors:
                memory.remember_success(_step_action_label(agent_obj))
        if not errors:
            return
        action = _step_action_label(agent_obj)
        for err in errors:
            stop, kind, message = tracker.record(action, err)
            if memory is not None:
                memory.remember_failure(f"{kind}:{err}")
            print(message)
            if stop:
                state = getattr(agent_obj, "state", None)
                if state is not None:
                    state.stopped = True
                return

    try:
        try:
            await ensure_browser_started(browser_session)
        except BrowserLaunchError:
            crash_restarts[0] += 1
            print("The browser crashed. I will relaunch Chromium once.")
            kill_orphaned_agent_browsers(PROFILE_DIR)
            raise
        history = await await_agent_run(
            agent,
            max_steps=max_steps,
            timeout_seconds=timeout_seconds,
            on_step_end=on_step_end,
        )
        fatal = getattr(llm, "_fatal", None)
        if isinstance(fatal, ProviderCallError):
            return
        print_history_result(history)
    except TimeoutError:
        print(f"\n⏱️  The task timed out after {int(timeout_seconds)} seconds.")
        print("The browser window was left open. Try a smaller request, or raise AGENT_TASK_TIMEOUT in .env.")
    except KeyboardInterrupt:
        print("\nInterrupted. The current task stopped; the browser is still open for the next command.")
        raise
    except BrowserLaunchError as exc:
        print(f"\n❌ {exc}")
    except ProviderCallError:
        return
    except Exception as exc:
        message = str(exc)
        if "exited before CDP" in message or "Browser process" in message:
            executable = Path(getattr(getattr(browser_session, "browser_profile", None), "executable_path", "") or "")
            print("\n❌ " + format_browser_launch_error(exc, executable if executable.is_file() else None))
            kill_orphaned_agent_browsers(PROFILE_DIR)
            return
        classified = classify_provider_error(exc)
        if classified.kind == "credits":
            print(f"\n❌ {CREDITS_MESSAGE}")
            return
        print(f"\n❌ Task failed ({classified.kind}): {classified}")
        if classified.kind in {"quota", "unavailable"}:
            print("I will not retry this model automatically.")


def _read_instruction_sync() -> str:
    try:
        return input(prompt_text())
    except UnicodeEncodeError:
        return input(PROMPT_FALLBACK)


async def read_instruction() -> str:
    return await asyncio.to_thread(_read_instruction_sync)


async def interactive_loop() -> None:
    load_environment()
    configure_agent_logging()
    print("Personal AI Browser Agent")
    print("Python 3.12 + Browser Use + Playwright Chromium")
    for line in startup_summary():
        print(line)
    print(f"Speed settings: max_steps={agent_max_steps()}, max_retries={agent_max_retries()}, memory={'on' if agent_memory_enabled() else 'off'}")
    print("Type a task in plain English. Type exit or quit to stop. Press Ctrl+C to interrupt.")
    print()

    llm = None
    browser_session = None
    tools = None
    task_running = False
    crash_restarts = [0]

    try:
        while True:
            try:
                raw = await read_instruction()
            except EOFError:
                print("\nNo more input. Shutting down.")
                break

            instruction = raw.strip()
            if not instruction:
                continue
            if instruction.lower() in {"exit", "quit"}:
                print("Goodbye.")
                break

            parsed = normalize_instruction(instruction)
            if parsed.ambiguous:
                print(parsed.ambiguous)
                continue

            if looks_sensitive(parsed.cleaned):
                print("This looks like a sensitive action (payment, booking, message, application, delete, or similar).")
                approved = await ask_yes_no("Type YES if you want me to continue planning it: ")
                if not approved:
                    print("Skipped. I did not open or change anything for that request.")
                    continue

            if llm is None:
                try:
                    llm = build_llm()
                    from config import llm_provider_name

                    active_p = llm_provider_name()
                    if active_p == "groq":
                        try:
                            from llm.groq_provider import probe_groq_account

                            probe_groq_account()
                            print("Groq configuration check: key accepted (value hidden).")
                        except Exception as p_err:
                            print(f"Groq probe notice: {p_err}")
                    elif active_p == "openrouter":
                        try:
                            from llm.openrouter_provider import probe_openrouter_account

                            probe_openrouter_account()
                            print("OpenRouter configuration check: key accepted (value hidden).")
                        except Exception as p_err:
                            print(f"OpenRouter probe notice: {p_err}")
                except ProviderConfigError as exc:
                    print(str(exc))
                    llm = None
                    continue
                except ProviderCallError as exc:
                    if exc.kind == "credits":
                        print(CREDITS_MESSAGE)
                    else:
                        print(str(exc))
                    llm = None
                    continue
                tools = build_tools()
                try:
                    browser_session = build_browser_session()
                    print("Opening a visible Chromium window. You can log into websites there when needed.")
                except Exception as exc:
                    print(f"Browser launch failed: {exc}")
                    print("Run: .\\.venv\\Scripts\\python.exe -m playwright install chromium")
                    llm = None
                    continue

            if task_running:
                print("A task is already running. Wait for it to finish.")
                continue
            task_running = True
            try:
                await run_browser_task(parsed.cleaned, llm, browser_session, tools, crash_restarts)
            except BrowserLaunchError:
                if crash_restarts[0] == 1:
                    try:
                        browser_session = build_browser_session()
                        await run_browser_task(parsed.cleaned, llm, browser_session, tools, crash_restarts)
                    except Exception as exc:
                        print(f"Browser relaunch failed: {exc}")
                else:
                    print("Chromium failed to start again. I stopped instead of looping.")
            except ProviderCallError as exc:
                print(f"Provider error ({exc.kind}): {exc}")
            finally:
                task_running = False
            print()
    except KeyboardInterrupt:
        print("\nInterrupted. Shutting down.")
    finally:
        if browser_session is not None:
            try:
                await browser_session.kill()
            except Exception as exc:
                print(f"Browser shutdown warning: {exc}")
