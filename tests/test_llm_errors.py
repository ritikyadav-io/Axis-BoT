import unittest
from unittest.mock import MagicMock, patch

from config import is_embedding_model, validate_chat_model
from llm.provider import classify_provider_error


class ChatModelGuardTests(unittest.TestCase):
    def test_embed_model_is_rejected_for_chat(self) -> None:
        model = "nvidia/nemotron-3.5-embed-1b:free"
        self.assertTrue(is_embedding_model(model))
        self.assertIsNotNone(validate_chat_model(model, "openrouter"))

    def test_instruct_model_is_allowed(self) -> None:
        model = "nvidia/nemotron-3.5-super-vl:free"
        self.assertFalse(is_embedding_model(model))
        self.assertIsNone(validate_chat_model(model, "openrouter"))

    def test_super_vl_is_not_an_embedding_model(self) -> None:
        self.assertFalse(is_embedding_model("nvidia/nemotron-3.5-super-vl:free"))
        self.assertTrue(is_embedding_model("nvidia/nemotron-3.5-embed-1b:free"))


class ProviderErrorTests(unittest.TestCase):
    def test_invalid_key(self) -> None:
        err = classify_provider_error(RuntimeError("401 Unauthorized: invalid api key"))
        self.assertEqual(err.kind, "invalid_key")

    def test_rate_limit(self) -> None:
        exc = RuntimeError("Too many requests")
        exc.status_code = 429
        err = classify_provider_error(exc)
        self.assertEqual(err.kind, "rate_limit")

    def test_quota_not_retried_as_rate_limit(self) -> None:
        err = classify_provider_error(RuntimeError("RESOURCE_EXHAUSTED: daily quota"))
        self.assertEqual(err.kind, "quota")

    def test_credits(self) -> None:
        from llm.provider import CREDITS_MESSAGE

        err = classify_provider_error(RuntimeError("402 insufficient credits"))
        self.assertEqual(err.kind, "credits")
        self.assertEqual(str(err), CREDITS_MESSAGE)

    def test_http_402_is_not_rate_limit(self) -> None:
        from llm.provider import CREDITS_MESSAGE

        exc = RuntimeError("Error code: 402 - {'error': {'message': 'Insufficient credits'}}")
        err = classify_provider_error(exc)
        self.assertEqual(err.kind, "credits")
        self.assertEqual(str(err), CREDITS_MESSAGE)
        self.assertNotEqual(err.kind, "rate_limit")

    def test_429_is_not_credits(self) -> None:
        exc = RuntimeError("Error code: 429 - rate limit exceeded")
        exc.status_code = 429
        err = classify_provider_error(exc)
        self.assertEqual(err.kind, "rate_limit")

    def test_credit_error_hides_api_key(self) -> None:
        err = classify_provider_error(RuntimeError("402 insufficient credits sk-or-v1-secretvaluehere"))
        self.assertNotIn("sk-or-v1-", str(err))
        self.assertEqual(err.kind, "credits")

    def test_model_no_longer_available_is_unavailable(self) -> None:
        exc = RuntimeError("HTTP 404: nvidia/nemotron-nano-9b-v2:free is no longer available.")
        exc.status_code = 404
        err = classify_provider_error(exc)
        self.assertEqual(err.kind, "unavailable")
        self.assertIn("will not be retried", str(err))

    def test_no_endpoints_is_unavailable(self) -> None:
        err = classify_provider_error(RuntimeError("No endpoints found for nvidia/nemotron-nano-9b-v2:free"))
        self.assertEqual(err.kind, "unavailable")


class FailFastOpenRouterTests(unittest.IsolatedAsyncioTestCase):
    async def test_404_does_not_call_the_model_again(self) -> None:
        from llm.openrouter_provider import FailFastChatModel
        from llm.provider import ProviderCallError

        class FakeInner:
            model = "gone-model"
            calls = 0

            async def ainvoke(self, *args, **kwargs):
                self.calls += 1
                error = RuntimeError("HTTP 404: gone-model is no longer available.")
                error.status_code = 404
                raise error

        inner = FakeInner()
        wrapper = FailFastChatModel(inner)
        with self.assertRaises(ProviderCallError) as first:
            await wrapper.ainvoke([])
        self.assertEqual(first.exception.kind, "unavailable")
        with self.assertRaises(ProviderCallError):
            await wrapper.ainvoke([])
        self.assertEqual(inner.calls, 1)

    async def test_402_does_not_call_the_model_again(self) -> None:
        from llm.openrouter_provider import FailFastChatModel
        from llm.provider import CREDITS_MESSAGE, ProviderCallError

        class FakeInner:
            model = "nvidia/nemotron-3.5-super-vl:free"
            calls = 0

            async def ainvoke(self, *args, **kwargs):
                self.calls += 1
                error = RuntimeError("Error code: 402 - Insufficient credits")
                error.status_code = 402
                raise error

        inner = FakeInner()
        wrapper = FailFastChatModel(inner)
        with self.assertRaises(ProviderCallError) as first:
            await wrapper.ainvoke([])
        self.assertEqual(first.exception.kind, "credits")
        self.assertEqual(str(first.exception), CREDITS_MESSAGE)
        with self.assertRaises(ProviderCallError):
            await wrapper.ainvoke([])
        self.assertEqual(inner.calls, 1)

    def test_probe_detects_402_without_chat_completion(self) -> None:
        from llm.openrouter_provider import probe_openrouter_account
        from llm.provider import CREDITS_MESSAGE, ProviderCallError

        denied = MagicMock(status_code=402, text="Insufficient credits")
        with patch("httpx.get", return_value=denied), patch("llm.openrouter_provider.is_configured", return_value=True), patch(
            "llm.openrouter_provider.openrouter_api_key", return_value="test-key"
        ), patch("llm.openrouter_provider.openrouter_chat_model", return_value="nvidia/nemotron-3.5-super-vl:free"), patch(
            "llm.openrouter_provider.validate_chat_model", return_value=None
        ):
            with self.assertRaises(ProviderCallError) as ctx:
                probe_openrouter_account()
        self.assertEqual(ctx.exception.kind, "credits")
        self.assertEqual(str(ctx.exception), CREDITS_MESSAGE)

    def test_probe_ok_when_key_unlimited(self) -> None:
        from llm.openrouter_provider import probe_openrouter_account

        ok = MagicMock(status_code=200)
        ok.json.return_value = {"data": {"limit_remaining": None, "is_free_tier": True}}
        with patch("httpx.get", return_value=ok), patch("llm.openrouter_provider.is_configured", return_value=True), patch(
            "llm.openrouter_provider.openrouter_api_key", return_value="test-key"
        ), patch("llm.openrouter_provider.openrouter_chat_model", return_value="nvidia/nemotron-3.5-super-vl:free"), patch(
            "llm.openrouter_provider.validate_chat_model", return_value=None
        ):
            probe_openrouter_account()

    def test_chatopenrouter_retries_are_disabled(self) -> None:
        from unittest.mock import MagicMock, patch

        from llm.openrouter_provider import FailFastChatModel, build_openrouter_chat

        fake = MagicMock()
        fake.model = "nvidia/nemotron-3.5-super-vl:free"
        with patch("llm.openrouter_provider.is_configured", return_value=True), patch(
            "llm.openrouter_provider.openrouter_api_key", return_value="test-key"
        ), patch("llm.openrouter_provider.openrouter_chat_model", return_value="nvidia/nemotron-3.5-super-vl:free"), patch(
            "llm.openrouter_provider.validate_chat_model", return_value=None
        ), patch("browser_use.ChatOpenRouter", return_value=fake) as ctor:
            built = build_openrouter_chat()
        self.assertIsInstance(built, FailFastChatModel)
        kwargs = ctor.call_args.kwargs
        self.assertEqual(kwargs["max_retries"], 0)
        self.assertEqual(kwargs["model"], "nvidia/nemotron-3.5-super-vl:free")
        self.assertEqual(kwargs["base_url"], "https://openrouter.ai/api/v1")


class EmbeddingErrorTests(unittest.TestCase):
    def test_mock_429_then_success(self) -> None:
        from llm.embeddings import embed_texts

        limited = MagicMock(status_code=429, text="rate limit")
        ok = MagicMock(status_code=200)
        ok.json.return_value = {"data": [{"index": 0, "embedding": [0.1, 0.2]}]}
        with patch("llm.embeddings.httpx.post", side_effect=[limited, ok]), patch("llm.embeddings.time.sleep"):
            with patch("llm.embeddings.is_configured", return_value=True), patch(
                "llm.embeddings.openrouter_api_key", return_value="test-key"
            ):
                vectors = embed_texts("hello")
        self.assertEqual(vectors, [[0.1, 0.2]])

    def test_mock_invalid_key(self) -> None:
        from llm.embeddings import embed_texts
        from llm.provider import ProviderCallError

        denied = MagicMock(status_code=401, text="invalid api key")
        with patch("llm.embeddings.httpx.post", return_value=denied):
            with patch("llm.embeddings.is_configured", return_value=True), patch(
                "llm.embeddings.openrouter_api_key", return_value="bad"
            ):
                with self.assertRaises(ProviderCallError) as ctx:
                    embed_texts("hello")
        self.assertEqual(ctx.exception.kind, "invalid_key")


if __name__ == "__main__":
    unittest.main()
