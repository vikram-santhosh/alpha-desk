"""OpenRouter model roster for the AlphaDesk council."""
from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class CostTier(str, Enum):
    FRONTIER = "frontier"
    CHEAP = "cheap"


class CouncilProvider(str, Enum):
    OPENROUTER = "openrouter"


@dataclass(frozen=True)
class ModelSpec:
    provider: CouncilProvider
    model_id: str
    label: str
    cost_tier: CostTier
    enabled: bool = True

    @property
    def uses_gcp(self) -> bool:
        return False


def _env_flag(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


DEFAULT_OPENROUTER_ROSTER: list[ModelSpec] = [
    ModelSpec(
        provider=CouncilProvider.OPENROUTER,
        model_id="z-ai/glm-5.2",
        label="GLM 5.2",
        cost_tier=CostTier.FRONTIER,
    ),
    ModelSpec(
        provider=CouncilProvider.OPENROUTER,
        model_id="moonshotai/kimi-k2.6",
        label="Kimi K2.6",
        cost_tier=CostTier.FRONTIER,
    ),
    ModelSpec(
        provider=CouncilProvider.OPENROUTER,
        model_id="deepseek/deepseek-v4-pro",
        label="DeepSeek V4 Pro",
        cost_tier=CostTier.FRONTIER,
    ),
]


def _label_from_model_id(model_id: str) -> str:
    return model_id.split("/")[-1].replace("-", " ").replace(".", " ").title()


def _configured_roster() -> list[ModelSpec]:
    configured = os.getenv("OPENROUTER_ANALYSIS_MODELS", "").strip()
    if not configured:
        return DEFAULT_OPENROUTER_ROSTER
    specs: list[ModelSpec] = []
    for model_id in [item.strip() for item in configured.split(",") if item.strip()]:
        if any(spec.model_id == model_id for spec in specs):
            continue
        default = next((spec for spec in DEFAULT_OPENROUTER_ROSTER if spec.model_id == model_id), None)
        specs.append(
            default
            or ModelSpec(
                provider=CouncilProvider.OPENROUTER,
                model_id=model_id,
                label=_label_from_model_id(model_id),
                cost_tier=CostTier.FRONTIER,
            )
        )
    return specs or DEFAULT_OPENROUTER_ROSTER


COUNCIL_ROSTER: list[ModelSpec] = _configured_roster()


def council_enabled() -> bool:
    """Return whether the multi-model council is enabled for runtime use."""
    return _env_flag("COUNCIL_ENABLED", False)


def enabled_roster(tier: Optional[CostTier] = None) -> list[ModelSpec]:
    """Return enabled OpenRouter model specs, optionally restricted by cost tier."""
    specs = [spec for spec in _configured_roster() if spec.enabled]
    if tier is not None:
        specs = [spec for spec in specs if spec.cost_tier == tier]
    if not specs:
        raise RuntimeError("No enabled OpenRouter council models are configured.")
    return specs
