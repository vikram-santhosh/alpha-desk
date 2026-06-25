"""GCP-first multi-model council fan-out.

This module only provides the council plumbing. Production brief integration
stays behind ``COUNCIL_ENABLED`` and later policy/cost-guardrail work.
"""
from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import Any, Optional

from src.shared.model_registry import (
    CouncilProvider,
    CostTier,
    ModelSpec,
    council_enabled,
    enabled_roster,
    gcp_location,
    gcp_project_id,
)


DEFAULT_TIMEOUT_S = 60.0
DEFAULT_MAX_TOKENS = 1200


@dataclass(frozen=True)
class CouncilRequest:
    prompt: str
    system: Optional[str] = None
    max_tokens: int = DEFAULT_MAX_TOKENS
    thinking_level: str = "HIGH"


@dataclass(frozen=True)
class CouncilResponse:
    provider: CouncilProvider
    model: str
    label: str
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.error is None


class GCPCouncilClient:
    """Dispatch one question to the configured GCP council models."""

    def __init__(self, timeout_s: Optional[float] = None):
        self.timeout_s = timeout_s or float(os.getenv("COUNCIL_MODEL_TIMEOUT_S", DEFAULT_TIMEOUT_S))

    async def deliberate(
        self,
        request: CouncilRequest,
        roster: Optional[list[ModelSpec]] = None,
    ) -> list[CouncilResponse]:
        """Fan out a request to all roster members and return per-model results."""
        if roster is None and not council_enabled():
            raise RuntimeError("Set COUNCIL_ENABLED=true to run the GCP model council.")
        specs = roster or enabled_roster(CostTier.FRONTIER)
        tasks = [self._call_with_timeout(spec, request) for spec in specs]
        return await asyncio.gather(*tasks)

    async def _call_with_timeout(self, spec: ModelSpec, request: CouncilRequest) -> CouncilResponse:
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(self._call_model, spec, request),
                timeout=self.timeout_s,
            )
        except Exception as exc:
            return CouncilResponse(
                provider=spec.provider,
                model=spec.model_id,
                label=spec.label,
                text="",
                error=str(exc),
            )

    def _call_model(self, spec: ModelSpec, request: CouncilRequest) -> CouncilResponse:
        if spec.provider == CouncilProvider.GCP_GEMINI:
            return self._call_gemini(spec, request)
        if spec.provider == CouncilProvider.GCP_CLAUDE:
            return self._call_claude_vertex(spec, request)
        if spec.provider == CouncilProvider.GCP_GROK:
            return self._call_grok_agent_platform(spec, request)
        raise ValueError(f"Unsupported council provider: {spec.provider}")

    def _call_gemini(self, spec: ModelSpec, request: CouncilRequest) -> CouncilResponse:
        from google import genai
        from google.genai import types

        client = genai.Client()
        config_kwargs: dict[str, Any] = {"max_output_tokens": request.max_tokens}
        if request.system:
            config_kwargs["system_instruction"] = request.system
        thinking_level = getattr(getattr(types, "ThinkingLevel", object), request.thinking_level, request.thinking_level)
        config_kwargs["thinking_config"] = types.ThinkingConfig(thinking_level=thinking_level)

        response = client.models.generate_content(
            model=spec.model_id,
            contents=request.prompt,
            config=types.GenerateContentConfig(**config_kwargs),
        )
        text = (getattr(response, "text", "") or "").strip()
        if not text:
            raise RuntimeError(f"{spec.label} returned empty text")

        usage = getattr(response, "usage_metadata", None)
        return CouncilResponse(
            provider=spec.provider,
            model=spec.model_id,
            label=spec.label,
            text=text,
            input_tokens=int(getattr(usage, "prompt_token_count", 0) or 0),
            output_tokens=int(getattr(usage, "candidates_token_count", 0) or 0),
        )

    def _call_claude_vertex(self, spec: ModelSpec, request: CouncilRequest) -> CouncilResponse:
        from anthropic import AnthropicVertex

        client = AnthropicVertex(project_id=gcp_project_id(), region=gcp_location())
        kwargs: dict[str, Any] = {
            "model": spec.model_id,
            "max_tokens": request.max_tokens,
            "messages": [{"role": "user", "content": request.prompt}],
        }
        if request.system:
            kwargs["system"] = request.system

        message = client.messages.create(**kwargs)
        text = _anthropic_text(message)
        if not text:
            raise RuntimeError(f"{spec.label} returned empty text")

        usage = getattr(message, "usage", None)
        return CouncilResponse(
            provider=spec.provider,
            model=getattr(message, "model", spec.model_id),
            label=spec.label,
            text=text,
            input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
            output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
        )

    def _call_grok_agent_platform(self, spec: ModelSpec, request: CouncilRequest) -> CouncilResponse:
        import google.auth
        from google.auth.transport.requests import AuthorizedSession

        credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        authed_session = AuthorizedSession(credentials)
        url = (
            "https://aiplatform.googleapis.com/v1/projects/"
            f"{gcp_project_id()}/locations/{gcp_location()}/endpoints/openapi/responses"
        )
        input_text = request.prompt if not request.system else f"System:\n{request.system}\n\nUser:\n{request.prompt}"
        response = authed_session.post(
            url,
            json={
                "model": spec.model_id,
                "input": input_text,
                "max_output_tokens": request.max_tokens,
            },
            timeout=self.timeout_s,
        )
        response.raise_for_status()
        payload = response.json()
        text = _responses_api_text(payload)
        if not text:
            raise RuntimeError(f"{spec.label} returned empty text")

        usage = payload.get("usage") or {}
        output_details = usage.get("output_tokens_details") or usage.get("completion_tokens_details") or {}
        return CouncilResponse(
            provider=spec.provider,
            model=payload.get("model") or spec.model_id,
            label=spec.label,
            text=text,
            input_tokens=int(usage.get("input_tokens") or usage.get("prompt_tokens") or 0),
            output_tokens=int(usage.get("output_tokens") or usage.get("completion_tokens") or 0),
            reasoning_tokens=int(output_details.get("reasoning_tokens") or usage.get("reasoning_tokens") or 0),
        )


def _anthropic_text(message: Any) -> str:
    chunks = []
    for block in getattr(message, "content", []) or []:
        text = getattr(block, "text", None)
        if text:
            chunks.append(text)
    return "\n".join(chunks).strip()


def _responses_api_text(payload: dict[str, Any]) -> str:
    if payload.get("output_text"):
        return str(payload["output_text"]).strip()

    chunks = []
    for item in payload.get("output", []) or []:
        for part in item.get("content", []) or []:
            text = part.get("text") or part.get("content")
            if text:
                chunks.append(str(text))
    return "\n".join(chunks).strip()


async def deliberate(
    prompt: str,
    system: Optional[str] = None,
    roster: Optional[list[ModelSpec]] = None,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> list[CouncilResponse]:
    """Convenience wrapper for one-off council fan-out."""
    request = CouncilRequest(prompt=prompt, system=system, max_tokens=max_tokens)
    return await GCPCouncilClient().deliberate(request, roster=roster)
