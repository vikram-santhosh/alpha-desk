"""Derived analyst/valuation fields: EV/FCF, implied upside, and the catalyst."""
from __future__ import annotations

import importlib

from src.portfolio_analyst.fundamental_analyzer import _safe_pct, _safe_ratio


def test_safe_ratio_handles_ev_to_fcf_and_edge_cases():
    assert _safe_ratio(1000.0, 50.0) == 20.0
    assert _safe_ratio(1000.0, 0) is None
    assert _safe_ratio(None, 50.0) is None
    assert _safe_ratio(1000.0, None) is None


def test_safe_pct_computes_implied_upside():
    assert _safe_pct(120.0, 100.0) == 20.0  # target 120 vs price 100 -> +20%
    assert _safe_pct(None, 100.0) is None
    assert _safe_pct(120.0, 0) is None


def test_analyst_upside_surfaces_as_top_buy_catalyst():
    app = importlib.import_module("src.api.app")
    catalysts = app._alpha_scout_catalysts({"implied_upside_pct": 28.0, "revenue_growth": 0.05}, [])
    assert any("upside" in c.lower() for c in catalysts), catalysts
    # A small/negative upside should NOT produce the catalyst.
    none_upside = app._alpha_scout_catalysts({"implied_upside_pct": 3.0}, [])
    assert not any("upside" in c.lower() for c in none_upside)
