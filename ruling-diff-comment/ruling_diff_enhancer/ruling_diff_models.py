from __future__ import annotations

import os
import re


PORTKEY_KEY_VARIABLES = {
    "openai": "PORTKEY_API_KEY_OPENAI",
    "anthropic": "PORTKEY_API_KEY_CLAUDE",
    "google": "PORTKEY_API_KEY_GOOGLE",
}


def model_family(model: str) -> str | None:
    normalized = model.lower()
    if normalized.startswith("gpt-") or re.match(r"^o\d", normalized):
        return "openai"
    if normalized.startswith("claude-"):
        return "anthropic"
    if normalized.startswith("gemini-"):
        return "google"
    return None


def model_connection(
    model: str, provider: str = "auto", api_base: str | None = None,
) -> tuple[str, dict]:
    model = model.strip()
    if not model:
        raise ValueError("Model name must not be empty")
    if provider not in ("auto", "direct", "portkey"):
        raise ValueError(f"Unknown provider mode: {provider}")
    prefix, separator, suffix = model.partition("/")
    bare_model = suffix if separator else model
    supported_prefix = not separator or prefix in ("openai", "anthropic", "gemini")
    family = model_family(bare_model) if supported_prefix else None
    key_variable = PORTKEY_KEY_VARIABLES.get(family) if family else None
    family_key = os.environ.get(key_variable, "").strip() if key_variable else ""
    portkey_key = family_key or os.environ.get("PORTKEY_API_KEY", "").strip()
    use_portkey = provider == "portkey" or (
        provider == "auto" and family is not None and bool(portkey_key)
    )
    options: dict = {"api_base": api_base} if api_base else {}
    if use_portkey:
        if family is None:
            raise ValueError("Portkey requires a GPT/o-series, Claude, or Gemini model name; use --provider direct for other endpoints")
        if not portkey_key:
            raise ValueError(f"Set {PORTKEY_KEY_VARIABLES[family]} or PORTKEY_API_KEY to use Portkey")
        native_claude = family == "anthropic"
        model = f"{'anthropic' if native_claude else 'openai'}/{bare_model}"
        options.update({
            "api_key": portkey_key,
            "api_base": api_base or ("https://api.portkey.ai" if native_claude else "https://api.portkey.ai/v1"),
            "extra_headers": {"x-portkey-provider": family},
        })
        if native_claude:
            options["extra_headers"]["x-portkey-api-key"] = portkey_key
    elif not separator:
        if family is None:
            raise ValueError("Use a provider/model identifier for an unrecognized direct model")
        direct_family = "gemini" if family == "google" else family
        model = f"{direct_family}/{bare_model}"
    if family == "openai" and (bare_model.lower().startswith("gpt-5") or re.match(r"^o\d", bare_model.lower())):
        options.update({"temperature": 1.0, "max_tokens": 16000})
    return model, options
