"""OpenRouter multi-model council fan-out."""
from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import Optional

from src.shared import gemini_compat as anthropic
from src.shared.model_registry import (
    CouncilProvider,
    CostTier,
    ModelSpec,
    council_enabled,
    enabled_roster,
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


class CouncilClient:
    """Dispatch one question to the configured OpenRouter council models."""

    def __init__(self, timeout_s: Optional[float] = None):
        self.timeout_s = timeout_s or float(os.getenv("COUNCIL_MODEL_TIMEOUT_S", DEFAULT_TIMEOUT_S))

    async def deliberate(
        self,
        request: CouncilRequest,
        roster: Optional[list[ModelSpec]] = None,
    ) -> list[CouncilResponse]:
        """Fan out a request to all roster members and return per-model results."""
        if roster is None and not council_enabled():
            raise RuntimeError("Set COUNCIL_ENABLED=true to run the model council.")
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
        client = anthropic.Anthropic()
        response = client.messages.create(
            model=spec.model_id,
            max_tokens=request.max_tokens,
            system=request.system,
            messages=[{"role": "user", "content": request.prompt}],
        )
        text = (response.content[0].text if response.content else "").strip()
        if not text:
            raise RuntimeError(f"{spec.label} returned empty text")
        return CouncilResponse(
            provider=spec.provider,
            model=response.model or spec.model_id,
            label=spec.label,
            text=text,
            input_tokens=int(response.usage.input_tokens or 0),
            output_tokens=int(response.usage.output_tokens or 0),
        )


async def deliberate(
    prompt: str,
    system: Optional[str] = None,
    roster: Optional[list[ModelSpec]] = None,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> list[CouncilResponse]:
    """Convenience wrapper for one-off council fan-out."""
    request = CouncilRequest(prompt=prompt, system=system, max_tokens=max_tokens)
    return await CouncilClient().deliberate(request, roster=roster)
