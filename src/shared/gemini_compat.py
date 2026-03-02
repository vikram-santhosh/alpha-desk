"""Anthropic-compatible shim backed by Google Gemini.

Drop-in replacement for the ``anthropic`` package used throughout AlphaDesk.
Exposes the same interface so every call-site can keep using:

    client = anthropic.Anthropic()
    response = client.messages.create(model=..., max_tokens=..., messages=[...])
    text = response.content[0].text
    tokens_in = response.usage.input_tokens
    tokens_out = response.usage.output_tokens

Model mapping:
  claude-haiku-*  → gemini-2.5-flash  (batch/extraction tasks, thinking disabled)
  claude-sonnet-* → gemini-2.5-pro    (thinking capped at 1024 tokens)
  claude-opus-*   → gemini-2.5-pro    (dynamic thinking for synthesis)

google.genai is imported lazily inside _Messages.create() so that test
modules can import this shim without needing the SDK installed.
"""

import os
from dataclasses import dataclass
from typing import Any

# ── Model mapping ────────────────────────────────────────────────────────────

GEMINI_MODEL = "gemini-2.5-pro"
GEMINI_FLASH_MODEL = "gemini-2.5-flash"


def _resolve_model(model: str) -> str:
    """Map Claude model names to Gemini equivalents.

    haiku  → gemini-2.5-flash  (fast, cheap, thinking-optional)
    others → gemini-2.5-pro    (full reasoning)
    """
    if model.startswith("claude-haiku"):
        return GEMINI_FLASH_MODEL
    if model.startswith("claude"):
        return GEMINI_MODEL
    return model


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
    """Base Anthropic-style API error."""


class APIStatusError(APIError):
    """Mirrors anthropic.APIStatusError (.message and .status_code)."""
    def __init__(self, message: str, status_code: int = 500):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class APIConnectionError(APIError):
    """Mirrors anthropic.APIConnectionError."""


# ── Messages resource ────────────────────────────────────────────────────────

class _Messages:
    def __init__(self, api_key: str | None):
        self._api_key = api_key

    def create(
        self,
        *,
        model: str,
        max_tokens: int,
        messages: list[dict[str, Any]],
        system: str | None = None,
        **kwargs,
    ) -> _Message:
        """Send a request to Gemini and return an Anthropic-compatible response."""
        # Lazy imports — keeps module importable in test environments without the SDK
        from google import genai
        from google.genai import types
        from google.api_core import exceptions as google_exceptions

        gemini_model = _resolve_model(model)

        api_key = self._api_key or os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise APIError("GEMINI_API_KEY is not set")

        client = genai.Client(api_key=api_key)

        # Thinking configuration per model family:
        #   gemini-2.5-flash — disable thinking (budget=0): batch JSON extraction
        #     tasks don't benefit from chain-of-thought reasoning.
        #   gemini-2.5-pro — cap thinking at 512 tokens for all callers. This
        #     keeps a predictable output budget regardless of max_tokens size;
        #     dynamic thinking can otherwise consume the entire max_tokens budget
        #     and leave nothing for visible output.
        if GEMINI_FLASH_MODEL in gemini_model:
            thinking_cfg = types.ThinkingConfig(thinking_budget=0)
        else:
            thinking_cfg = types.ThinkingConfig(thinking_budget=512)

        config = types.GenerateContentConfig(
            system_instruction=system,
            max_output_tokens=max_tokens,
            thinking_config=thinking_cfg,
        )

        # Convert Anthropic message list → google.genai Content objects
        contents = [
            types.Content(
                role="user" if msg["role"] == "user" else "model",
                parts=[types.Part(text=msg["content"])],
            )
            for msg in messages
        ]

        try:
            response = client.models.generate_content(
                model=gemini_model,
                contents=contents,
                config=config,
            )
        except google_exceptions.NotFound as exc:
            raise APIStatusError(str(exc), status_code=404) from exc
        except google_exceptions.PermissionDenied as exc:
            raise APIStatusError(str(exc), status_code=403) from exc
        except google_exceptions.ResourceExhausted as exc:
            raise APIStatusError(str(exc), status_code=429) from exc
        except google_exceptions.GoogleAPICallError as exc:
            status = getattr(exc, "code", None)
            if status is not None:
                raise APIStatusError(str(exc), status_code=int(status)) from exc
            raise APIConnectionError(str(exc)) from exc
        except (APIError, APIStatusError, APIConnectionError):
            raise
        except Exception as exc:
            # Catch httpx / network-level errors (e.g. RemoteProtocolError)
            exc_type = type(exc).__name__
            if exc_type in ("RemoteProtocolError", "ConnectError", "ReadError",
                            "WriteError", "TimeoutException", "NetworkError"):
                raise APIConnectionError(str(exc)) from exc
            raise APIError(str(exc)) from exc

        text = response.text if hasattr(response, "text") and response.text else ""

        meta = getattr(response, "usage_metadata", None)
        input_tokens = getattr(meta, "prompt_token_count", 0) if meta else 0
        # Include thinking tokens in output count — both are billed by Google.
        # candidates_token_count can be None when thinking consumes the full budget.
        visible = getattr(meta, "candidates_token_count", None) or 0
        thinking = getattr(meta, "thoughts_token_count", None) or 0
        output_tokens = visible + thinking

        return _Message(
            content=[_ContentBlock(type="text", text=text)],
            usage=_Usage(input_tokens=input_tokens, output_tokens=output_tokens),
        )


# ── Public client ────────────────────────────────────────────────────────────

class Anthropic:
    """Drop-in replacement for ``anthropic.Anthropic()``."""

    def __init__(self, api_key: str | None = None, **kwargs):
        self._api_key = api_key
        self.messages = _Messages(api_key=api_key)
