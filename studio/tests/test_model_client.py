import unittest
import unittest.mock
import urllib.error

from studio.model_client import ModelRoutingError, chat_with_failover, is_rate_limit_error
from studio.model_catalog import ModelEndpoint


class ModelClientTest(unittest.TestCase):
    def test_is_rate_limit_error_detects_http_429(self) -> None:
        error = urllib.error.HTTPError(
            url="https://integrate.api.nvidia.com/v1/chat/completions",
            code=429,
            msg="Too Many Requests",
            hdrs=None,
            fp=None,
        )
        self.assertTrue(is_rate_limit_error(error))

    def test_chat_with_failover_switches_after_rate_limit(self) -> None:
        calls: list[str] = []

        def fake_post(url: str, payload: dict, timeout_seconds: int, headers=None) -> dict:
            calls.append(payload["model"])
            if payload["model"] == "meta/llama-3.3-70b-instruct":
                raise RuntimeError("HTTP 429 from https://integrate.api.nvidia.com/v1/chat/completions: rate limit")
            if "/api/chat" in url:
                return {"message": {"content": "ok from local backup"}}
            return {"choices": [{"message": {"content": "ok from nvidia backup"}}]}

        with unittest.mock.patch.dict("os.environ", {"NVIDIA_API_KEY": "test-key"}, clear=False):
            content, endpoint = chat_with_failover(
                "director",
                "Prompt",
                assigned_model="meta/llama-3.3-70b-instruct",
                timeout_seconds=30,
                prefer_nvidia=True,
                post_json=fake_post,
                sleep=lambda _: None,
            )

        self.assertEqual(content, "ok from nvidia backup")
        self.assertEqual(endpoint.model, "nvidia/nemotron-3-nano-30b-a3b")
        self.assertEqual(calls[0], "meta/llama-3.3-70b-instruct")
        self.assertEqual(calls[1], "nvidia/nemotron-3-nano-30b-a3b")

    def test_chat_with_failover_uses_ollama_without_nvidia_key(self) -> None:
        def fake_post(url: str, payload: dict, timeout_seconds: int, headers=None) -> dict:
            self.assertIn("/api/chat", url)
            return {"message": {"content": "local ok"}}

        with unittest.mock.patch.dict("os.environ", {}, clear=True):
            content, endpoint = chat_with_failover(
                "builder",
                "Prompt",
                assigned_model=None,
                timeout_seconds=30,
                prefer_nvidia=True,
                post_json=fake_post,
            )

        self.assertEqual(content, "local ok")
        self.assertEqual(endpoint.provider, "ollama")

    def test_chat_with_failover_raises_when_all_endpoints_fail(self) -> None:
        def fake_post(url: str, payload: dict, timeout_seconds: int, headers=None) -> dict:
            raise RuntimeError(f"boom on {payload['model']}")

        with unittest.mock.patch.dict("os.environ", {"NVIDIA_API_KEY": "test-key"}, clear=False):
            with self.assertRaises(ModelRoutingError):
                chat_with_failover(
                    "reviewer",
                    "Prompt",
                    assigned_model="meta/llama-3.1-8b-instruct",
                    timeout_seconds=30,
                    prefer_nvidia=True,
                    post_json=fake_post,
                    sleep=lambda _: None,
                )


if __name__ == "__main__":
    unittest.main()
