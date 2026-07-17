"""Tests for cost tracker resolved-model pricing."""
from __future__ import annotations

import importlib
from dataclasses import dataclass

from src.shared.cost_tracker import _get_pricing


@dataclass
class _FakeUsage:
    input_tokens: int
    output_tokens: int


@dataclass
class _FakeResponse:
    model: str
    usage: _FakeUsage


def _reload_cost_tracker(monkeypatch, tmp_path):
    monkeypatch.setenv("ALPHADESK_DATA_DIR", str(tmp_path))
    cost_tracker = importlib.import_module("src.shared.cost_tracker")
    return importlib.reload(cost_tracker)


def test_get_pricing_for_openrouter_kimi():
    """Resolved Kimi should be priced as OpenRouter, not as Claude Opus."""
    pricing = _get_pricing("moonshotai/kimi-k2.6")
    assert pricing["input"] < 1.0


def test_get_pricing_for_openrouter_glm():
    """Resolved GLM should be priced as an inexpensive council model."""
    pricing = _get_pricing("z-ai/glm-5.2")
    assert pricing["input"] < 1.0


def test_record_usage_prefers_response_model(monkeypatch, tmp_path):
    """record_usage uses the resolved backend model, not the requested alias."""
    cost_tracker = _reload_cost_tracker(monkeypatch, tmp_path)

    # Simulate an OpenRouter shim response: requested claude-opus-4-6, resolved Kimi.
    response = _FakeResponse(
        model="moonshotai/kimi-k2.6",
        usage=_FakeUsage(input_tokens=1_000_000, output_tokens=1_000_000),
    )

    cost = cost_tracker.record_usage(
        "test_agent", 1_000_000, 1_000_000, model="claude-opus-4-6", response=response
    )

    # OpenRouter Kimi pricing: $0.15 in + $2.50 out = $2.65
    assert cost == 2.65

    # If it had used the requested alias, it would be $15 + $75 = $90
    assert cost != 90.0
