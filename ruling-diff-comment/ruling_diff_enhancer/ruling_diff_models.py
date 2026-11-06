from __future__ import annotations

import os
import re


PORTKEY_API_BASE = "https://api.portkey.ai/v1"


def portkey_key() -> str:
    return (
        os.environ.get("PORTKEY_API_KEY_OPENAI", "").strip()
        or os.environ.get("PORTKEY_API_KEY", "").strip()
    )


def has_api_key() -> bool:
    return bool(portkey_key())


def model_connection(model: str) -> tuple[str, dict]:
    bare_model = model.strip().removeprefix("openai/")
    if not bare_model:
        raise ValueError("Model name must not be empty")
    key = portkey_key()
    if not key:
        raise ValueError("Set PORTKEY_API_KEY_OPENAI or PORTKEY_API_KEY to use Portkey")
    options: dict = {
        "api_key": key,
        "api_base": PORTKEY_API_BASE,
        "extra_headers": {"x-portkey-provider": "openai"},
    }
    if bare_model.startswith("gpt-5") or re.match(r"^o\d", bare_model):
        options.update({"temperature": 1.0, "max_tokens": 16000})
    return f"openai/{bare_model}", options
