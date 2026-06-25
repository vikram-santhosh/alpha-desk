"""LLM shim for AlphaDesk.

Backend selection logic:
  - On GCP (detected via GOOGLE_CLOUD_PROJECT or K_SERVICE env vars): always Gemini
  - Locally: ANTHROPIC_API_KEY → Anthropic, else GEMINI_API_KEY → Gemini

Exposes the same interface so every call-site can keep using:

    client = Anthropic()
    response = client.messages.create(model=..., max_tokens=..., messages=[...])
    text = response.content[0].text
    tokens_in = response.usage.input_tokens
    tokens_out = response.usage.output_tokens

Model mapping (Anthropic):
  claude-haiku-*  → claude-haiku-4-5-20251001
  claude-sonnet-* → claude-sonnet-4-6
  claude-opus-*   → claude-opus-4-6

Model mapping (Gemini):
  claude-haiku-*  → gemini-3.1-flash-lite-preview
  claude-sonnet-* → gemini-3.1-pro-preview
  claude-opus-*   → gemini-3.1-pro-preview
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

# ── Anthropic model mapping ──────────────────────────────────────────────────

OPUS_MODEL = "claude-opus-4-6"
SONNET_MODEL = "claude-sonnet-4-6"
HAIKU_MODEL = "claude-haiku-4-5"


def _resolve_anthropic_model(model: str) -> str:
    """Map shorthand Claude model names to full Anthropic model IDs."""
    if model.startswith("claude-haiku"):
        return HAIKU_MODEL
    if model.startswith("claude-opus"):
        return OPUS_MODEL
    if model.startswith("claude-sonnet"):
        return SONNET_MODEL
    if model.startswith("claude"):
        return SONNET_MODEL
    return model


# ── OpenRouter model mapping ────────────────────────────────────────────────
# OpenRouter is OpenAI-compatible and serves Claude directly with one key.
# Slugs can be overridden via env (OPENROUTER_OPUS / _SONNET / _HAIKU) since
# OpenRouter occasionally revises them.

# User-chosen models (override via env). Roles map by cost/capability:
#   heavy synthesis → Kimi K2.6 · standard analysis → GLM 5.2 · bulk extraction → Gemini 3.5 Flash
OPENROUTER_OPUS   = os.getenv("OPENROUTER_OPUS",   "moonshotai/kimi-k2.6")
OPENROUTER_SONNET = os.getenv("OPENROUTER_SONNET", "z-ai/glm-5.2")
OPENROUTER_HAIKU  = os.getenv("OPENROUTER_HAIKU",  "google/gemini-3.5-flash")


def _resolve_openrouter_model(model: str) -> str:
    """Map shorthand Claude names to OpenRouter slugs (pass through real slugs)."""
    if "/" in model:
        return model  # already an OpenRouter slug, e.g. "anthropic/claude-sonnet-4"
    if model.startswith("claude-haiku"):
        return OPENROUTER_HAIKU
    if model.startswith("claude-opus"):
        return OPENROUTER_OPUS
    if model.startswith("claude"):
        return OPENROUTER_SONNET
    return model


# ── Gemini model mapping ────────────────────────────────────────────────────

GEMINI_OPUS = "gemini-3.1-pro-preview"
GEMINI_SONNET = "gemini-3.1-pro-preview"
GEMINI_HAIKU = "gemini-3.1-flash-lite-preview"


def _resolve_gemini_model(model: str) -> str:
    """Map Claude model names to Gemini equivalents."""
    if model.startswith("claude-haiku") or model.startswith("gemini-3.1-flash"):
        return GEMINI_HAIKU
    if model.startswith("claude-opus") or model.startswith("claude-sonnet") or model.startswith("gemini-3.1-pro"):
        return GEMINI_OPUS
    if model.startswith("claude"):
        return GEMINI_SONNET
    if model.startswith("gemini"):
        return model  # pass through native Gemini model names
    return GEMINI_SONNET


# ── Response objects (mimic Anthropic SDK shapes) ───────────────────────────

@dataclass
class _ContentBlock:
    type: str
    text: str


@dataclass
class _Usage:
    input_tokens: int
    output_tokens: int


@dataclass
class _Message:
    content: list[_ContentBlock]
    usage: _Usage
    model: str = ""


# ── Exception hierarchy ──────────────────────────────────────────────────────

class APIError(Exception):
    """Base API error."""


class APIStatusError(APIError):
    """Mirrors anthropic.APIStatusError (.message and .status_code)."""
    def __init__(self, message: str, status_code: int = 500):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class APIConnectionError(APIError):
    """Mirrors anthropic.APIConnectionError."""


# ── Backend detection ───────────────────────────────────────────────────────

def _is_running_on_gcp() -> bool:
    """Detect if running inside a GCP environment (Cloud Run, GCE, etc.)."""
    # K_SERVICE is set by Cloud Run; GOOGLE_CLOUD_PROJECT by most GCP runtimes
    return bool(os.getenv("K_SERVICE") or os.getenv("GOOGLE_CLOUD_PROJECT"))


def _detect_backend(api_key: str | None = None) -> str:
    """Return 'openrouter', 'anthropic', or 'gemini' based on environment.

    Preference order (everywhere): OpenRouter if OPENROUTER_API_KEY is set —
    one key, OpenAI-compatible, serves Claude directly. Then a direct Anthropic
    key, then Gemini as a last resort.
    """
    if os.getenv("OPENROUTER_API_KEY"):
        return "openrouter"
    if api_key or os.getenv("ANTHROPIC_API_KEY"):
        return "anthropic"
    if os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"):
        return "gemini"
    return "none"


# ── Messages resource ────────────────────────────────────────────────────────

class _Messages:
    def __init__(self, api_key: str | None, backend: str):
        self._api_key = api_key
        self._backend = backend

    def create(
        self,
        *,
        model: str,
        max_tokens: int,
        messages: list[dict[str, Any]],
        system: str | None = None,
        **kwargs,
    ) -> _Message:
        if self._backend == "openrouter":
            return self._create_openrouter(model, max_tokens, messages, system, kwargs)
        elif self._backend == "anthropic":
            return self._create_anthropic(model, max_tokens, messages, system, kwargs)
        elif self._backend == "gemini":
            return self._create_gemini(model, max_tokens, messages, system, kwargs)
        else:
            raise APIError(
                "No API key found. Set OPENROUTER_API_KEY (preferred), "
                "ANTHROPIC_API_KEY, or GEMINI_API_KEY / GOOGLE_API_KEY."
            )

    # ── Anthropic backend ───────────────────────────────────────────────────

    def _create_anthropic(
        self,
        model: str,
        max_tokens: int,
        messages: list[dict],
        system: str | None,
        options: dict[str, Any] | None = None,
    ) -> _Message:
        import anthropic as _anthropic

        resolved_model = _resolve_anthropic_model(model)
        api_key = self._api_key or os.getenv("ANTHROPIC_API_KEY")

        client = _anthropic.Anthropic(api_key=api_key)
        create_kwargs: dict[str, Any] = {
            "model": resolved_model,
            "max_tokens": max_tokens,
            "messages": messages,
        }
        if system:
            create_kwargs["system"] = system
        options = options or {}
        for key in ("temperature", "top_p", "stop_sequences"):
            if key in options:
                create_kwargs[key] = options[key]

        try:
            response = client.messages.create(**create_kwargs)
        except _anthropic.APIStatusError as exc:
            raise APIStatusError(str(exc), status_code=exc.status_code) from exc
        except _anthropic.APIConnectionError as exc:
            raise APIConnectionError(str(exc)) from exc
        except _anthropic.APIError as exc:
            raise APIError(str(exc)) from exc
        except Exception as exc:
            exc_type = type(exc).__name__
            if exc_type in ("RemoteProtocolError", "ConnectError", "ReadError",
                            "WriteError", "TimeoutException", "NetworkError"):
                raise APIConnectionError(str(exc)) from exc
            raise APIError(str(exc)) from exc

        text = ""
        for block in response.content:
            if hasattr(block, "text"):
                text = block.text
                break

        return _Message(
            content=[_ContentBlock(type="text", text=text)],
            usage=_Usage(
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
            ),
            model=getattr(response, "model", resolved_model),
        )

    # ── OpenRouter backend (OpenAI-compatible, serves Claude) ────────────────

    def _create_openrouter(
        self,
        model: str,
        max_tokens: int,
        messages: list[dict],
        system: str | None,
        options: dict[str, Any] | None = None,
    ) -> _Message:
        import requests

        resolved_model = _resolve_openrouter_model(model)
        api_key = self._api_key or os.getenv("OPENROUTER_API_KEY")

        # Anthropic-style (system separate) → OpenAI-style (system as a message).
        oai_messages: list[dict] = []
        if system:
            oai_messages.append({"role": "system", "content": system})
        for msg in messages:
            content = msg["content"] if isinstance(msg["content"], str) else str(msg["content"])
            oai_messages.append({"role": msg["role"], "content": content})

        payload: dict[str, Any] = {
            "model": resolved_model,
            "max_tokens": max_tokens,
            "messages": oai_messages,
        }
        options = options or {}
        for key in ("temperature", "top_p", "stop_sequences"):
            if key in options:
                payload[key] = options[key]

        try:
            resp = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "X-Title": "AlphaDesk",
                },
                json=payload,
                timeout=120,
            )
        except requests.exceptions.ConnectionError as exc:
            raise APIConnectionError(str(exc)) from exc
        except requests.exceptions.RequestException as exc:
            raise APIError(str(exc)) from exc

        if resp.status_code >= 400:
            raise APIStatusError(
                f"OpenRouter {resp.status_code}: {resp.text[:300]}",
                status_code=resp.status_code,
            )

        data = resp.json()
        text = (data.get("choices") or [{}])[0].get("message", {}).get("content", "") or ""
        usage = data.get("usage") or {}
        return _Message(
            content=[_ContentBlock(type="text", text=text)],
            usage=_Usage(
                input_tokens=usage.get("prompt_tokens", 0) or 0,
                output_tokens=usage.get("completion_tokens", 0) or 0,
            ),
            model=resolved_model,
        )

    # ── Gemini backend ──────────────────────────────────────────────────────

    def _create_gemini(
        self,
        model: str,
        max_tokens: int,
        messages: list[dict],
        system: str | None,
        options: dict[str, Any] | None = None,
    ) -> _Message:
        from google import genai
        from google.genai import types

        resolved_model = _resolve_gemini_model(model)
        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")

        client = genai.Client(api_key=api_key)

        # Convert Anthropic-style messages to Gemini contents
        contents = []
        for msg in messages:
            role = "model" if msg["role"] == "assistant" else "user"
            text = msg["content"] if isinstance(msg["content"], str) else str(msg["content"])
            contents.append(types.Content(role=role, parts=[types.Part(text=text)]))

        options = options or {}
        config_kwargs: dict[str, Any] = {"max_output_tokens": max_tokens}
        for key in ("temperature", "top_p", "top_k"):
            if key in options:
                config_kwargs[key] = options[key]
        response_mime_type = options.get("response_mime_type")
        if response_mime_type:
            config_kwargs["response_mime_type"] = response_mime_type
        config = types.GenerateContentConfig(**config_kwargs)
        if system:
            config.system_instruction = system

        try:
            response = client.models.generate_content(
                model=resolved_model,
                contents=contents,
                config=config,
            )
        except Exception as exc:
            exc_type = type(exc).__name__
            if "status" in str(exc).lower() or "http" in exc_type.lower():
                raise APIStatusError(str(exc)) from exc
            if any(k in exc_type for k in ("Connection", "Network", "Timeout")):
                raise APIConnectionError(str(exc)) from exc
            raise APIError(str(exc)) from exc

        text = response.text or ""
        input_tokens = getattr(response.usage_metadata, "prompt_token_count", 0) or 0
        output_tokens = getattr(response.usage_metadata, "candidates_token_count", 0) or 0

        return _Message(
            content=[_ContentBlock(type="text", text=text)],
            usage=_Usage(input_tokens=input_tokens, output_tokens=output_tokens),
            model=resolved_model,
        )


# ── Public client ────────────────────────────────────────────────────────────

class Anthropic:
    """Drop-in LLM client. On GCP: Gemini. Locally: Anthropic if key present, else Gemini."""

    def __init__(self, api_key: str | None = None, **kwargs):
        self._api_key = api_key
        self._backend = _detect_backend(api_key)
        self.messages = _Messages(api_key=api_key, backend=self._backend)

    @property
    def backend(self) -> str:
        """Which backend is active: 'anthropic', 'gemini', or 'none'."""
        return self._backend
