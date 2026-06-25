"""Tests for cost tracker resolved-model pricing."""
from __future__ import annotations

import importlib
from dataclasses import dataclass
from pathlib import Path

from src.shared.cost_tracker import _get_pricing, record_usage


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


def test_get_pricing_for_gemini_31_pro():
    """gemini-3.1-pro-preview must be priced as Gemini, not as Claude Opus."""
    pricing = _get_pricing("gemini-3.1-pro-preview")
    assert pricing["input"] < 5.0  # Claude Opus is $15


def test_get_pricing_for_gemini_31_flash_lite():
    """gemini-3.1-flash-lite-preview must be priced as a flash model."""
    pricing = _get_pricing("gemini-3.1-flash-lite-preview")
    assert pricing["input"] < 1.0


def test_record_usage_prefers_response_model(monkeypatch, tmp_path):
    """record_usage uses the resolved backend model, not the requested alias."""
    cost_tracker = _reload_cost_tracker(monkeypatch, tmp_path)

    # Simulate a Gemini shim response: requested claude-opus-4-6, resolved gemini-3.1-pro-preview
    response = _FakeResponse(
        model="gemini-3.1-pro-preview",
        usage=_FakeUsage(input_tokens=1_000_000, output_tokens=1_000_000),
    )

    cost = cost_tracker.record_usage(
        "test_agent", 1_000_000, 1_000_000, model="claude-opus-4-6", response=response
    )

    # Gemini pricing: $1.25 in + $10.00 out = $11.25
    assert cost == 11.25

    # If it had used the requested alias, it would be $15 + $75 = $90
    assert cost != 90.0
