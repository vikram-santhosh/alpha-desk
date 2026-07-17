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
from dataclasses import dataclass
from typing import Any


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
        import requests

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
