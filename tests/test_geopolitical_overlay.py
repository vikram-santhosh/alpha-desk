"""Geopolitical overlay is grounded in macro proxies (gold/oil/USD/VIX)."""
from __future__ import annotations

from src.advisor import deployment_planner as dp


def test_overlay_grounds_signals_in_macro_proxies():
    macro = {
        "gold": {"value": 4078.7, "change_pct": 1.2},
        "oil_wti": {"value": 69.2, "change_pct": -3.7},
        "usd_index": {"value": 101.4, "change_pct": -0.6},
        "vix": {"value": 18.9},
    }
    out = dp._geopolitical_overlay(macro)
    joined = " ".join(out["signals"]).lower()
    assert "gold" in joined and "wti" in joined and "dollar" in joined and "vix" in joined
    assert "safe-haven" in joined  # gold >= 3000 flags stress
    # gold (+2) only -> "moderate"; range is contained/moderate/elevated.
    assert out["risk_level"] == "moderate"


def test_overlay_escalates_with_multiple_stress_signals():
    macro = {
        "gold": {"value": 4100, "change_pct": 2.0},  # +2
        "oil_wti": {"value": 95, "change_pct": 5.0},  # +1
        "vix": {"value": 28, "change_pct": 10.0},  # +1
    }
    assert dp._geopolitical_overlay(macro)["risk_level"] == "elevated"


def test_overlay_is_honest_when_macro_missing():
    out = dp._geopolitical_overlay({})
    assert out["risk_level"] == "unknown"
    assert out["signals"] == []
    assert "verify live" in out["note"]
