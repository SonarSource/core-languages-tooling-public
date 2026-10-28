from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import enhance
from ruling_diff_models import model_connection


class ModelConnectionTests(unittest.TestCase):
    def setUp(self) -> None:
        environment = patch.dict(os.environ, {"LITELLM_LOCAL_MODEL_COST_MAP": "True"}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)

    def test_direct_prefixed_model_and_endpoint_are_unchanged(self) -> None:
        self.assertEqual(
            model_connection("provider/model", api_base="http://localhost:8000/v1"),
            ("provider/model", {"api_base": "http://localhost:8000/v1"}),
        )

    def test_auto_without_portkey_key_infers_direct_family(self) -> None:
        for model, expected in (
            ("gpt-4.1", "openai/gpt-4.1"),
            ("claude-test", "anthropic/claude-test"),
            ("gemini-test", "gemini/gemini-test"),
        ):
            with self.subTest(model=model):
                self.assertEqual(model_connection(model), (expected, {}))

    def test_portkey_auto_detection_and_transport_for_each_family(self) -> None:
        os.environ["PORTKEY_API_KEY"] = "test-key"
        for model, expected, family, api_base in (
            ("gpt-4.1", "openai/gpt-4.1", "openai", "https://api.portkey.ai/v1"),
            ("anthropic/claude-test", "anthropic/claude-test", "anthropic", "https://api.portkey.ai"),
            ("gemini/gemini-test", "openai/gemini-test", "google", "https://api.portkey.ai/v1"),
        ):
            with self.subTest(model=model):
                resolved, options = model_connection(model)
                self.assertEqual(resolved, expected)
                self.assertEqual(options["api_base"], api_base)
                self.assertEqual(options["api_key"], "test-key")
                self.assertEqual(options["extra_headers"]["x-portkey-provider"], family)
                if family == "anthropic":
                    self.assertEqual(options["extra_headers"]["x-portkey-api-key"], "test-key")

    def test_family_specific_keys_take_precedence(self) -> None:
        os.environ["PORTKEY_API_KEY"] = "generic-key"
        for model, variable in (
            ("gpt-4.1", "PORTKEY_API_KEY_OPENAI"),
            ("claude-test", "PORTKEY_API_KEY_CLAUDE"),
            ("gemini-test", "PORTKEY_API_KEY_GOOGLE"),
        ):
            with self.subTest(model=model), patch.dict(os.environ, {variable: "family-key"}):
                _, options = model_connection(model)
                self.assertEqual(options["api_key"], "family-key")

    def test_family_specific_key_alone_enables_portkey(self) -> None:
        os.environ["PORTKEY_API_KEY_CLAUDE"] = "family-key"
        _, options = model_connection("claude-test")
        self.assertEqual(options["api_key"], "family-key")
        self.assertEqual(model_connection("gpt-4.1"), ("openai/gpt-4.1", {}))

    def test_explicit_direct_never_uses_portkey_credentials(self) -> None:
        os.environ["PORTKEY_API_KEY"] = "test-key"
        self.assertEqual(model_connection("claude-test", "direct"), ("anthropic/claude-test", {}))

    def test_custom_provider_model_is_not_automatically_rerouted(self) -> None:
        os.environ["PORTKEY_API_KEY"] = "test-key"
        self.assertEqual(model_connection("ollama_chat/local-model"), ("ollama_chat/local-model", {}))

    def test_explicit_portkey_requires_matching_key(self) -> None:
        os.environ["PORTKEY_API_KEY_OPENAI"] = "different-family-key"
        with self.assertRaisesRegex(ValueError, "PORTKEY_API_KEY_CLAUDE or PORTKEY_API_KEY"):
            model_connection("claude-test", "portkey")

    def test_portkey_endpoint_override_preserves_authentication(self) -> None:
        os.environ["PORTKEY_API_KEY"] = "test-key"
        _, options = model_connection("claude-test", "portkey", "https://gateway.example")
        self.assertEqual(options["api_base"], "https://gateway.example")
        self.assertEqual(options["extra_headers"]["x-portkey-api-key"], "test-key")

    def test_reasoning_models_use_required_dspy_defaults(self) -> None:
        for provider in ("direct", "portkey"):
            for model in ("gpt-5.4", "o3"):
                with self.subTest(provider=provider, model=model):
                    os.environ["PORTKEY_API_KEY"] = "test-key"
                    _, options = model_connection(model, provider)
                    self.assertEqual(options["temperature"], 1.0)
                    self.assertEqual(options["max_tokens"], 16000)

    def test_invalid_configuration_is_rejected(self) -> None:
        for model, provider in ((" ", "auto"), ("unknown", "direct"), ("unknown", "portkey"), ("gpt-4.1", "invalid")):
            with self.subTest(model=model, provider=provider), self.assertRaises(ValueError):
                model_connection(model, provider)

    def test_cli_provider_environment_default_and_explicit_override(self) -> None:
        os.environ["DSPY_PROVIDER"] = "portkey"
        with patch("sys.argv", ["enhance.py", "comment.md", "--prepare-only"]):
            self.assertEqual(enhance.parse_args().provider, "portkey")
        with patch("sys.argv", ["enhance.py", "comment.md", "--prepare-only", "--provider", "direct"]):
            self.assertEqual(enhance.parse_args().provider, "direct")

    def test_cli_passes_portkey_connection_to_dspy(self) -> None:
        import dspy
        from test_enhancer import comment_section, review_data, write_metadata

        os.environ["PORTKEY_API_KEY"] = "test-key"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_metadata(root)
            comment = root / "comment.md"
            comment.write_text(comment_section(), encoding="utf-8")
            output = root / "review.json"
            predictor = Mock(return_value=SimpleNamespace(review=review_data()))
            with (
                patch("sys.argv", ["enhance.py", str(comment), "--repo", str(root), "--model", "claude-test", "--format", "json", "--output", str(output)]),
                patch.object(dspy, "configure_cache"),
                patch.object(dspy, "LM") as language_model,
                patch.object(dspy, "context"),
                patch.object(dspy, "Predict", return_value=predictor),
            ):
                self.assertEqual(enhance.main(), 0)
            model, options = model_connection("claude-test")
            language_model.assert_called_once_with(model, cache=False, **options)
            self.assertEqual(json.loads(output.read_text(encoding="utf-8"))[0]["opinion"], "negative")

    def test_real_litellm_transports_send_expected_portkey_requests(self) -> None:
        import dspy
        import httpx

        os.environ["PORTKEY_API_KEY"] = "test-key"
        for model, route in (("gpt-4.1", "/v1/chat/completions"), ("claude-sonnet-4-5-20250929", "/v1/messages")):
            with self.subTest(model=model):
                requests = []

                def respond(request, **kwargs):
                    requests.append(request)
                    if model.startswith("claude-"):
                        response = {
                            "id": "msg_test", "type": "message", "role": "assistant",
                            "model": model, "content": [{"type": "text", "text": "review"}],
                            "stop_reason": "end_turn", "stop_sequence": None,
                            "usage": {"input_tokens": 1, "output_tokens": 1},
                        }
                    else:
                        response = {
                            "id": "chatcmpl-test", "object": "chat.completion", "created": 0,
                            "model": model, "choices": [{"index": 0, "message": {"role": "assistant", "content": "review"}, "finish_reason": "stop"}],
                            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                        }
                    return httpx.Response(200, request=request, json=response)

                resolved, options = model_connection(model, "portkey")
                lm = dspy.LM(resolved, cache=False, **options)
                with (
                    patch.object(httpx.Client, "send", side_effect=respond),
                    patch.object(httpx.AsyncClient, "send", side_effect=AssertionError("Unexpected async request")),
                    patch("litellm.utils._client_async_logging_helper", new_callable=AsyncMock),
                ):
                    result = lm.forward(messages=[{"role": "user", "content": "Review this change."}])
                self.assertEqual(result.choices[0].message.content, "review")
                self.assertEqual(len(requests), 1)
                request = requests[0]
                self.assertEqual(str(request.url), f"https://api.portkey.ai{route}")
                self.assertEqual(request.headers["x-portkey-provider"], "anthropic" if model.startswith("claude-") else "openai")
                if model.startswith("claude-"):
                    self.assertEqual(request.headers["x-portkey-api-key"], "test-key")
                else:
                    self.assertEqual(request.headers["authorization"], "Bearer test-key")


if __name__ == "__main__":
    unittest.main()
