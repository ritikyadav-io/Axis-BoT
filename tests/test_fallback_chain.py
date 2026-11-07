from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock

from llm.provider import FallbackChainChatModel, ProviderCallError


class FallbackChainChatModelTests(unittest.IsolatedAsyncioTestCase):
    async def test_uses_primary_when_successful(self) -> None:
        primary = MagicMock()
        primary.ainvoke = AsyncMock(return_value="primary_success")
        primary.model = "groq-model"
        primary.provider = "groq"

        fallback = MagicMock()
        fallback.ainvoke = AsyncMock(return_value="fallback_success")
        fallback.model = "openrouter-model"
        fallback.provider = "openrouter"

        chain = FallbackChainChatModel([("groq", primary), ("openrouter", fallback)])
        result = await chain.ainvoke([])

        self.assertEqual(result, "primary_success")
        self.assertEqual(chain.active_name, "groq")
        self.assertEqual(primary.ainvoke.call_count, 1)
        self.assertEqual(fallback.ainvoke.call_count, 0)

    async def test_falls_back_when_primary_fails(self) -> None:
        primary = MagicMock()
        primary.ainvoke = AsyncMock(side_effect=RuntimeError("Rate limit 429 exceeded"))
        primary.model = "groq-model"
        primary.provider = "groq"

        fallback = MagicMock()
        fallback.ainvoke = AsyncMock(return_value="fallback_success")
        fallback.model = "openrouter-model"
        fallback.provider = "openrouter"

        chain = FallbackChainChatModel([("groq", primary), ("openrouter", fallback)])
        result = await chain.ainvoke([])

        self.assertEqual(result, "fallback_success")
        self.assertEqual(chain.active_name, "openrouter")
        self.assertEqual(primary.ainvoke.call_count, 1)
        self.assertEqual(fallback.ainvoke.call_count, 1)

    async def test_three_tier_fallback_to_gemini(self) -> None:
        primary = MagicMock()
        primary.ainvoke = AsyncMock(side_effect=RuntimeError("Daily limit reached 429"))

        secondary = MagicMock()
        secondary.ainvoke = AsyncMock(side_effect=RuntimeError("Error code: 402 - Insufficient credits"))

        tertiary = MagicMock()
        tertiary.ainvoke = AsyncMock(return_value="gemini_success")
        tertiary.model = "gemini-2.5-flash"

        chain = FallbackChainChatModel([
            ("groq", primary),
            ("openrouter", secondary),
            ("gemini", tertiary),
        ])
        result = await chain.ainvoke([])

        self.assertEqual(result, "gemini_success")
        self.assertEqual(chain.active_name, "gemini")
        self.assertEqual(primary.ainvoke.call_count, 1)
        self.assertEqual(secondary.ainvoke.call_count, 1)
        self.assertEqual(tertiary.ainvoke.call_count, 1)


if __name__ == "__main__":
    unittest.main()
