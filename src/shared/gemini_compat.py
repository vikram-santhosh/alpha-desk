"""LLM shim for AlphaDesk.

Auto-selects backend based on available API keys:
  1. ANTHROPIC_API_KEY → Anthropic Claude API
  2. GEMINI_API_KEY or GOOGLE_API_KEY → Google Gemini API

Exposes the same interface so every call-site can keep using:

    client = Anthropic()
    response = client.messages.create(model=..., max_tokens=..., messages=[...])
    text = response.content[0].text
    tokens_in = response.usage.input_tokens
    tokens_out = response.usage.output_tokens

Model mapping (Anthropic):
  claude-haiku-*  → claude-haiku-4-5-20251001
  claude-sonnet-* → claude-sonnet-4-6-20250514
  claude-opus-*   → claude-opus-4-6-20250514

Model mapping (Gemini):
  claude-haiku-*  → gemini-2.0-flash
  claude-sonnet-* → gemini-2.5-flash
  claude-opus-*   → gemini-2.5-pro
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


# ── Gemini model mapping ────────────────────────────────────────────────────

GEMINI_OPUS = "gemini-2.5-pro"
GEMINI_SONNET = "gemini-2.5-flash"
GEMINI_HAIKU = "gemini-2.0-flash"


def _resolve_gemini_model(model: str) -> str:
    """Map Claude model names to Gemini equivalents."""
    if model.startswith("claude-haiku") or model.startswith("gemini-2.0-flash"):
        return GEMINI_HAIKU
    if model.startswith("claude-opus") or model.startswith("gemini-2.5-pro"):
        return GEMINI_OPUS
    if model.startswith("claude-sonnet") or model.startswith("gemini-2.5-flash"):
        return GEMINI_SONNET
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

def _detect_backend(api_key: str | None = None) -> str:
    """Return 'anthropic' or 'gemini' based on available keys."""
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
        if self._backend == "anthropic":
            return self._create_anthropic(model, max_tokens, messages, system)
        elif self._backend == "gemini":
            return self._create_gemini(model, max_tokens, messages, system)
        else:
            raise APIError(
                "No API key found. Set ANTHROPIC_API_KEY or GEMINI_API_KEY / GOOGLE_API_KEY."
            )

    # ── Anthropic backend ───────────────────────────────────────────────────

    def _create_anthropic(
        self, model: str, max_tokens: int, messages: list[dict], system: str | None
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
        )

    # ── Gemini backend ──────────────────────────────────────────────────────

    def _create_gemini(
        self, model: str, max_tokens: int, messages: list[dict], system: str | None
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

        config = types.GenerateContentConfig(
            max_output_tokens=max_tokens,
        )
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
        )


# ── Public client ────────────────────────────────────────────────────────────

class Anthropic:
    """Drop-in LLM client. Uses Anthropic if ANTHROPIC_API_KEY is set, else Gemini."""

    def __init__(self, api_key: str | None = None, **kwargs):
        self._api_key = api_key
        self._backend = _detect_backend(api_key)
        self.messages = _Messages(api_key=api_key, backend=self._backend)

    @property
    def backend(self) -> str:
        """Which backend is active: 'anthropic', 'gemini', or 'none'."""
        return self._backend
