import asyncio
import unittest
from types import SimpleNamespace

from agent.browser_agent import await_agent_run, task_timeout_seconds


class FakeHistory:
    def __init__(self, done: bool = True, successful: bool = True, result: str = "ok") -> None:
        self._done = done
        self._successful = successful
        self._result = result

    def is_done(self) -> bool:
        return self._done

    def is_successful(self) -> bool:
        return self._successful

    def final_result(self) -> str:
        return self._result

    def errors(self) -> list:
        return []


class FakeAgent:
    def __init__(self, hang_after_done: bool = True, never_finish: bool = False) -> None:
        self.history = FakeHistory()
        self.register_done_callback = None
        self.state = SimpleNamespace(stopped=False)
        self.hang_after_done = hang_after_done
        self.never_finish = never_finish

    async def run(self, max_steps: int = 40, on_step_end=None, on_step_start=None):
        if self.never_finish:
            await asyncio.sleep(30)
            return self.history
        if callable(self.register_done_callback):
            result = self.register_done_callback(self.history)
            if asyncio.iscoroutine(result):
                await result
        if self.hang_after_done:
            await asyncio.sleep(30)
        return self.history


class TaskTimeoutTests(unittest.IsolatedAsyncioTestCase):
    async def test_returns_after_done_even_if_cleanup_hangs(self) -> None:
        agent = FakeAgent(hang_after_done=True)
        history = await await_agent_run(agent, max_steps=5, timeout_seconds=2, cleanup_grace_seconds=0.05)
        self.assertTrue(history.is_done())
        self.assertTrue(agent.state.stopped)

    async def test_genuine_timeout_when_task_never_completes(self) -> None:
        agent = FakeAgent(never_finish=True)
        agent.history = FakeHistory(done=False, successful=False)
        with self.assertRaises(TimeoutError):
            await await_agent_run(agent, max_steps=5, timeout_seconds=0.2)
        self.assertTrue(agent.state.stopped)

    def test_default_timeout_is_600(self) -> None:
        import os
        from unittest.mock import patch

        with patch.dict(os.environ, {"AGENT_TASK_TIMEOUT": ""}, clear=False):
            os.environ.pop("AGENT_TASK_TIMEOUT", None)
            self.assertEqual(task_timeout_seconds(), 600.0)


if __name__ == "__main__":
    unittest.main()
