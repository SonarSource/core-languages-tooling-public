from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from ruling_diff_enhancer.ruling_diff_models import has_api_key, model_connection


class ModelConnectionTests(unittest.TestCase):
    def setUp(self) -> None:
        environment = patch.dict(os.environ, {}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)

    def test_api_key_detection_requires_portkey_key(self) -> None:
        self.assertFalse(has_api_key())
        with patch.dict(os.environ, {"OPENAI_API_KEY": "unrelated", "PORTKEY_API_KEY": " "}):
            self.assertFalse(has_api_key())
        for variable in ("PORTKEY_API_KEY", "PORTKEY_API_KEY_OPENAI"):
            with patch.dict(os.environ, {variable: "test-key"}):
                self.assertTrue(has_api_key())

    def test_model_is_routed_through_portkey(self) -> None:
        os.environ["PORTKEY_API_KEY"] = "test-key"
        for model in ("gpt-4.1", "openai/gpt-4.1"):
            with self.subTest(model=model):
                resolved, options = model_connection(model)
                self.assertEqual(resolved, "gpt-4.1")
                self.assertEqual(options["base_url"], "https://api.portkey.ai/v1")
                self.assertEqual(options["api_key"], "test-key")
                self.assertEqual(options["default_headers"], {"x-portkey-provider": "openai"})

    def test_openai_specific_key_takes_precedence(self) -> None:
        os.environ["PORTKEY_API_KEY"] = "generic-key"
        os.environ["PORTKEY_API_KEY_OPENAI"] = "openai-key"
        self.assertEqual(model_connection("gpt-4.1")[1]["api_key"], "openai-key")

    def test_reasoning_models_use_required_model_defaults(self) -> None:
        os.environ["PORTKEY_API_KEY"] = "test-key"
        for model in ("gpt-5.4", "o3"):
            with self.subTest(model=model):
                _, options = model_connection(model)
                self.assertEqual(options["temperature"], 1.0)
                self.assertEqual(options["max_completion_tokens"], 16000)

    def test_invalid_configuration_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "PORTKEY_API_KEY"):
            model_connection("gpt-4.1")
        os.environ["PORTKEY_API_KEY"] = "test-key"
        with self.assertRaises(ValueError):
            model_connection(" ")

    def test_real_openai_transport_sends_expected_portkey_request(self) -> None:
        import httpx
        from openai import OpenAI

        os.environ["PORTKEY_API_KEY"] = "test-key"
        model = "gpt-4.1"
        requests = []

        def respond(request, **kwargs):
            requests.append(request)
            return httpx.Response(200, request=request, json={
                "id": "chatcmpl-test", "object": "chat.completion", "created": 0,
                "model": model, "choices": [{"index": 0, "message": {"role": "assistant", "content": "review"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            })

        resolved, options = model_connection(model)
        with (
            patch.object(httpx.Client, "send", side_effect=respond),
        ):
            client = OpenAI(**options)
            result = client.chat.completions.create(
                model=resolved, messages=[{"role": "user", "content": "Review this change."}],
            )
        self.assertEqual(result.choices[0].message.content, "review")
        self.assertEqual(len(requests), 1)
        request = requests[0]
        self.assertEqual(str(request.url), "https://api.portkey.ai/v1/chat/completions")
        self.assertEqual(request.headers["x-portkey-provider"], "openai")
        self.assertEqual(request.headers["authorization"], "Bearer test-key")


if __name__ == "__main__":
    unittest.main()
