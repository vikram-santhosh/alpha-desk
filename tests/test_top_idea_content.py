"""Top Buys cards must carry real, per-name catalysts/risks — not boilerplate."""
from __future__ import annotations

import importlib


def _app():
    return importlib.import_module("src.api.app")


def test_catalysts_are_derived_not_boilerplate():
    app = _app()
    fund = {
        "revenue_growth": 0.21,
        "net_margin": 0.30,
        "pe_trailing": 25.0,
        "pct_from_52w_high": -17.2,
        "next_earnings_date": "2026-07-16",
    }
    cats = app._alpha_scout_catalysts(fund, [])
    assert cats, "expected real catalysts"
    assert not any("composite score" in c.lower() for c in cats)
    assert any("revenue" in c.lower() for c in cats)


def test_risks_flag_real_concerns_not_boilerplate():
    app = _app()
    risks = app._alpha_scout_risks({"pe_trailing": 91.7, "pct_from_52w_high": -3.0}, {"sentiment": 50})
    assert not any("requires follow-up council" in r.lower() for r in risks)
    assert any("p/e" in r.lower() for r in risks)
    assert any("52-week high" in r.lower() for r in risks)


def test_top_idea_builder_emits_real_content():
    app = _app()
    rec = {
        "ticker": "NVDA",
        "company": "NVIDIA",
        "category": "portfolio",
        "scores": {"composite": 84.0, "sentiment": 50, "fundamental": 95, "evidence_quality": 90},
        "fundamentals_summary": {
            "revenue_growth": 0.85,
            "net_margin": 0.50,
            "pe_trailing": 29.5,
            "pct_from_52w_high": -18.6,
            "sector": "Technology",
        },
        "thesis": "Real thesis here.",
    }
    idea = app._top_idea_from_alpha_scout_rec(rec, 0)
    assert idea is not None
    joined = " ".join(idea.catalysts + idea.risks).lower()
    assert "composite score" not in joined
    assert "requires follow-up council" not in joined
    assert idea.catalysts, "expected non-empty catalysts"
