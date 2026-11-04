from __future__ import annotations

import os
import re


PORTKEY_KEY_VARIABLES = {
    "openai": "PORTKEY_API_KEY_OPENAI",
    "anthropic": "PORTKEY_API_KEY_CLAUDE",
    "google": "PORTKEY_API_KEY_GOOGLE",
}


def has_api_key(model: str, provider: str = "auto", api_base: str | None = None) -> bool:
    resolved_model, options = model_connection(model, provider, api_base)
    if options.get("api_key"):
        return True
    key_variables = {
        "openai": ("OPENAI_API_KEY",),
        "anthropic": ("ANTHROPIC_API_KEY",),
        "gemini": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
        "azure": ("AZURE_API_KEY", "AZURE_OPENAI_API_KEY"),
    }
    return any(
        os.environ.get(variable, "").strip()
        for variable in key_variables.get(resolved_model.partition("/")[0], ())
    )


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
    bare_model, family = _model_details(model)
    portkey_key = _portkey_key(family)
    use_portkey = _uses_portkey(provider, family, portkey_key, api_base)
    options: dict = {"api_base": api_base} if api_base else {}
    if use_portkey:
        model, portkey_options = _portkey_connection(bare_model, family, portkey_key, api_base)
        options.update(portkey_options)
    elif "/" not in model:
        if family is None:
            raise ValueError("Use a provider/model identifier for an unrecognized direct model")
        direct_family = "gemini" if family == "google" else family
        model = f"{direct_family}/{bare_model}"
    if _is_reasoning_model(family, bare_model):
        options.update({"temperature": 1.0, "max_tokens": 16000})
    return model, options


def _model_details(model: str) -> tuple[str, str | None]:
    prefix, separator, suffix = model.partition("/")
    bare_model = suffix if separator else model
    supported_prefix = not separator or prefix in ("openai", "anthropic", "gemini")
    return bare_model, model_family(bare_model) if supported_prefix else None


def _portkey_key(family: str | None) -> str:
    key_variable = PORTKEY_KEY_VARIABLES.get(family) if family else None
    family_key = os.environ.get(key_variable, "").strip() if key_variable else ""
    return family_key or os.environ.get("PORTKEY_API_KEY", "").strip()


def _uses_portkey(provider: str, family: str | None, key: str, api_base: str | None) -> bool:
    return provider == "portkey" or (provider == "auto" and family is not None and bool(key) and not api_base)


def _portkey_connection(bare_model: str, family: str | None, key: str, api_base: str | None) -> tuple[str, dict]:
    if family is None:
        raise ValueError("Portkey requires a GPT/o-series, Claude, or Gemini model name; use --provider direct for other endpoints")
    if not key:
        raise ValueError(f"Set {PORTKEY_KEY_VARIABLES[family]} or PORTKEY_API_KEY to use Portkey")
    native_claude = family == "anthropic"
    headers = {"x-portkey-provider": family}
    if native_claude:
        headers["x-portkey-api-key"] = key
    return f"{'anthropic' if native_claude else 'openai'}/{bare_model}", {
        "api_key": key, "api_base": api_base or ("https://api.portkey.ai" if native_claude else "https://api.portkey.ai/v1"),
        "extra_headers": headers,
    }


def _is_reasoning_model(family: str | None, model: str) -> bool:
    normalized = model.lower()
    return family == "openai" and (normalized.startswith("gpt-5") or re.match(r"^o\d", normalized) is not None)
