"""Model roster for the AlphaDesk council.

The council is GCP-first: Gemini, Claude, and Grok all run through Google
Cloud's Agent Platform / Vertex AI managed APIs when enabled.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class CostTier(str, Enum):
    FRONTIER = "frontier"
    CHEAP = "cheap"


class CouncilProvider(str, Enum):
    GCP_GEMINI = "gcp_gemini"
    GCP_CLAUDE = "gcp_claude"
    GCP_GROK = "gcp_grok"


@dataclass(frozen=True)
class ModelSpec:
    provider: CouncilProvider
    model_id: str
    label: str
    cost_tier: CostTier
    enabled: bool = True

    @property
    def uses_gcp(self) -> bool:
        return self.provider.value.startswith("gcp_")


def _env_flag(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


COUNCIL_ROSTER: list[ModelSpec] = [
    ModelSpec(
        provider=CouncilProvider.GCP_GEMINI,
        model_id=os.getenv("COUNCIL_GEMINI_MODEL", "gemini-3.1-pro-preview"),
        label=os.getenv("COUNCIL_GEMINI_LABEL", "Gemini 3.1 Pro"),
        cost_tier=CostTier.FRONTIER,
        enabled=_env_flag("COUNCIL_ENABLE_GEMINI", True),
    ),
    ModelSpec(
        provider=CouncilProvider.GCP_CLAUDE,
        model_id=os.getenv("COUNCIL_CLAUDE_MODEL", "claude-opus-4-8"),
        label=os.getenv("COUNCIL_CLAUDE_LABEL", "Claude Opus 4.8"),
        cost_tier=CostTier.FRONTIER,
        enabled=_env_flag("COUNCIL_ENABLE_CLAUDE", True),
    ),
    ModelSpec(
        provider=CouncilProvider.GCP_GROK,
        model_id=os.getenv("COUNCIL_GROK_MODEL", "xai/grok-4.20-reasoning"),
        label=os.getenv("COUNCIL_GROK_LABEL", "Grok 4.20 Reasoning"),
        cost_tier=CostTier.FRONTIER,
        enabled=_env_flag("COUNCIL_ENABLE_GROK", True),
    ),
]


def council_enabled() -> bool:
    """Return whether the multi-model council is enabled for runtime use."""
    return _env_flag("COUNCIL_ENABLED", False)


def gcp_project_configured() -> bool:
    """Return whether the minimum GCP project env exists for Agent Platform."""
    return bool(os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("GOOGLE_CLOUD_PROJECT_ID"))


def gcp_project_id() -> str:
    """Return the configured GCP project id or raise a clear setup error."""
    project_id = os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("GOOGLE_CLOUD_PROJECT_ID")
    if not project_id:
        raise RuntimeError("Set GOOGLE_CLOUD_PROJECT for the GCP model council.")
    return project_id


def gcp_location() -> str:
    """Return the Agent Platform location; global is preferred for council calls."""
    return os.getenv("GOOGLE_CLOUD_LOCATION", "global")


def enabled_roster(tier: Optional[CostTier] = None, require_gcp_project: bool = True) -> list[ModelSpec]:
    """Return enabled model specs, optionally restricted by cost tier."""
    specs = [spec for spec in COUNCIL_ROSTER if spec.enabled]
    if tier is not None:
        specs = [spec for spec in specs if spec.cost_tier == tier]
    if require_gcp_project and any(spec.uses_gcp for spec in specs) and not gcp_project_configured():
        raise RuntimeError("Set GOOGLE_CLOUD_PROJECT before enabling the GCP model council.")
    if not specs:
        raise RuntimeError("No enabled council models are configured.")
    return specs
