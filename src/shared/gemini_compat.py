"""OpenRouter-only LLM compatibility shim for AlphaDesk.

Call sites intentionally keep using an Anthropic-shaped interface:

    client = Anthropic()
    response = client.messages.create(model=..., max_tokens=..., messages=[...])
    text = response.content[0].text
    tokens_in = response.usage.input_tokens
    tokens_out = response.usage.output_tokens

The implementation routes every request through OpenRouter and clamps model
selection to the current allowlist. Legacy Claude/Gemini/Grok aliases resolve
onto the same allowlist so stale prompts or env values cannot escape it.
"""
from __future__ import annotations

import os
import random
import time
from dataclasses import dataclass
from typing import Any

# Transient failures worth retrying: rate limits and server-side errors.
# Anything else (4xx auth/validation) fails the same way every time.
_RETRYABLE_STATUS_CODES = {408, 429, 500, 502, 503, 504}
_MAX_RETRIES = int(os.getenv("OPENROUTER_MAX_RETRIES", "3"))
_BACKOFF_BASE_S = float(os.getenv("OPENROUTER_RETRY_BACKOFF_S", "1.0"))


# Roles map by cost/capability: heavy -> Kimi K2.6, standard/bulk -> GLM 5.2,
# plus DeepSeek V4 for model-council diversity.
OPENROUTER_OPUS = os.getenv("OPENROUTER_OPUS", "moonshotai/kimi-k2.6")
OPENROUTER_SONNET = os.getenv("OPENROUTER_SONNET", "z-ai/glm-5.2")
OPENROUTER_HAIKU = os.getenv("OPENROUTER_HAIKU", "z-ai/glm-5.2")
OPENROUTER_DEEPSEEK = os.getenv("OPENROUTER_DEEPSEEK", "deepseek/deepseek-v4-pro")

ALLOWED_OPENROUTER_MODELS = {
    OPENROUTER_OPUS,
    OPENROUTER_SONNET,
    OPENROUTER_HAIKU,
    OPENROUTER_DEEPSEEK,
}


def _resolve_openrouter_model(model: str) -> str:
    """Resolve any requested model name to an allowed OpenRouter slug."""
    raw = (model or "").strip()
    lowered = raw.lower()
    aliases = {
        "claude-opus-4-8": OPENROUTER_OPUS,
        "claude-opus-4-6": OPENROUTER_OPUS,
        "anthropic/claude-opus-4.8": OPENROUTER_OPUS,
        "anthropic/claude-opus-4.8-fast": OPENROUTER_OPUS,
        "claude-sonnet-4-6": OPENROUTER_SONNET,
        "claude-haiku-4-5": OPENROUTER_HAIKU,
        "gemini-3.1-pro-preview": OPENROUTER_SONNET,
        "gemini-3.1-flash-lite-preview": OPENROUTER_HAIKU,
        "google/gemini-3.1-flash-lite": OPENROUTER_HAIKU,
        "gemini-3.5-flash": OPENROUTER_HAIKU,
        "google/gemini-3.5-flash": OPENROUTER_HAIKU,
        "xai/grok-4.20-reasoning": OPENROUTER_SONNET,
        "x-ai/grok-4.20": OPENROUTER_SONNET,
        "x-ai/grok-4.3": OPENROUTER_SONNET,
        "kimi-k2.6": OPENROUTER_OPUS,
        "moonshotai/kimi-k2.6": OPENROUTER_OPUS,
        "moonshotai/kimi-k2.7-code": OPENROUTER_OPUS,
        "deepseek-v4-pro": OPENROUTER_DEEPSEEK,
        "deepseek/deepseek-v4-pro": OPENROUTER_DEEPSEEK,
        "glm-5.2": OPENROUTER_SONNET,
        "z-ai/glm-5.2": OPENROUTER_SONNET,
    }
    if lowered in aliases:
        return aliases[lowered]
    if raw in ALLOWED_OPENROUTER_MODELS:
        return raw
    if lowered.startswith("claude-opus"):
        return OPENROUTER_OPUS
    if lowered.startswith("claude-haiku"):
        return OPENROUTER_HAIKU
    return OPENROUTER_SONNET


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


def _detect_backend(api_key: str | None = None) -> str:
    """OpenRouter if OPENROUTER_API_KEY is set, else ``none``."""
    return "openrouter" if os.getenv("OPENROUTER_API_KEY") else "none"


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
        **kwargs: Any,
    ) -> _Message:
        if self._backend == "openrouter":
            return self._create_openrouter(model, max_tokens, messages, system, kwargs)
        raise APIError("No API key found. Set OPENROUTER_API_KEY.")

    def _create_openrouter(
        self,
        model: str,
        max_tokens: int,
        messages: list[dict[str, Any]],
        system: str | None,
        options: dict[str, Any] | None = None,
    ) -> _Message:
        resolved_model = _resolve_openrouter_model(model)
        api_key = self._api_key or os.getenv("OPENROUTER_API_KEY")
        if not api_key:
            raise APIError("No API key found. Set OPENROUTER_API_KEY.")

        oai_messages: list[dict[str, str]] = []
        if system:
            oai_messages.append({"role": "system", "content": system})
        for msg in messages:
            content = msg.get("content", "")
            oai_messages.append(
                {
                    "role": str(msg.get("role", "user")),
                    "content": content if isinstance(content, str) else str(content),
                }
            )

        payload: dict[str, Any] = {
            "model": resolved_model,
            "max_tokens": max_tokens,
            "messages": oai_messages,
        }
        options = options or {}
        for key in ("temperature", "top_p", "stop_sequences"):
            if key in options:
                payload[key] = options[key]

        resp = self._post_with_retry(payload, api_key)
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

    @staticmethod
    def _post_with_retry(payload: dict[str, Any], api_key: str) -> Any:
        """POST with retry on transient failures (timeouts, connection errors,
        429/5xx). A single dropped OpenRouter call otherwise kills a whole
        council seat or pipeline stage outright."""
        import requests

        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRIES + 1):
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
                last_exc = APIConnectionError(str(exc))
            except requests.exceptions.Timeout as exc:
                last_exc = APIConnectionError(str(exc))
            except requests.exceptions.RequestException as exc:
                raise APIError(str(exc)) from exc
            else:
                if resp.status_code < 400:
                    return resp
                if resp.status_code not in _RETRYABLE_STATUS_CODES:
                    raise APIStatusError(
                        f"OpenRouter {resp.status_code}: {resp.text[:300]}",
                        status_code=resp.status_code,
                    )
                last_exc = APIStatusError(
                    f"OpenRouter {resp.status_code}: {resp.text[:300]}",
                    status_code=resp.status_code,
                )

            if attempt < _MAX_RETRIES:
                delay = _BACKOFF_BASE_S * (2**attempt) + random.uniform(0, _BACKOFF_BASE_S)
                time.sleep(delay)

        assert last_exc is not None
        raise last_exc


class Anthropic:
    """Drop-in LLM client backed only by OpenRouter."""

    def __init__(self, api_key: str | None = None, **kwargs: Any):
        self._api_key = api_key
        self._backend = _detect_backend(api_key)
        self.messages = _Messages(api_key=api_key, backend=self._backend)

    @property
    def backend(self) -> str:
        """Which backend is active: ``openrouter`` or ``none``."""
        return self._backend
