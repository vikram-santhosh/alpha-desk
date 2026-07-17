from __future__ import annotations

import importlib


def test_explain_fundamental_factors_flags_expensive_thin_name():
    from src.alpha_scout.screener import explain_fundamental_factors

    factors = explain_fundamental_factors(
        {
            "pe_trailing": 72, "ev_to_ebitda": 53.7, "revenue_growth": 0.33,
            "net_margin": 0.10, "gross_margin": 0.48, "implied_upside_pct": 5.5,
            "pct_from_52w_high": -20.5, "market_cap": 26e9,
        }
    )
    joined = " | ".join(factors)
    assert any("EV/EBITDA" in f and f.startswith("-") for f in factors)
    assert any("P/E" in f and f.startswith("-") for f in factors)
    assert any("revenue growth" in f and f.startswith("+") for f in factors)
    assert "little left" in joined  # low analyst upside surfaced


def test_explain_fundamental_factors_penalises_losses():
    from src.alpha_scout.screener import explain_fundamental_factors

    factors = explain_fundamental_factors({"net_margin": -0.20, "revenue_growth": 0.05})
    assert any("net margin" in f and f.startswith("-") for f in factors)


def test_explain_fundamental_factors_flags_thin_margin_and_cash_burn():
    from src.alpha_scout.screener import explain_fundamental_factors

    factors = explain_fundamental_factors({"gross_margin": 0.08, "free_cashflow": -7e9})
    assert any("gross margin" in f and f.startswith("-") for f in factors)
    assert any("free cash flow" in f and f.startswith("-") for f in factors)


def test_idea_debug_from_rec_builds_dimensions_and_provenance():
    app = importlib.import_module("src.api.app")
    rec = {
        "ticker": "AFRM",
        "source": "agent_bus/portfolio_analyst",
        "corroboration_count": 2,
        "corroborating_sources": ["agent_bus/portfolio_analyst", "supply_chain"],
        "synthesis_source": "score_fallback",
    }
    scores = {
        "technical": 91, "fundamental": 70, "evidence_quality": 78, "composite": 74.3,
        "weights": {"technical": 0.14, "fundamental": 0.36, "evidence_quality": 0.24},
    }
    fund = {"pe_trailing": 72, "ev_to_ebitda": 53.7, "net_margin": 0.10, "revenue_growth": 0.33}

    debug = app._idea_debug_from_rec(rec, scores, fund)
    assert debug is not None
    assert debug.composite == 74.3
    assert debug.corroboration_count == 2
    assert debug.synthesis_source == "score_fallback"
    by_name = {d.name: d for d in debug.dimensions}
    assert by_name["fundamental"].contribution == round(70 * 0.36, 1)
    assert debug.factors  # has human-readable factors


def test_idea_debug_none_without_scores():
    app = importlib.import_module("src.api.app")
    assert app._idea_debug_from_rec({"ticker": "X"}, {}, {}) is None


def test_progress_endpoint_returns_model():
    app = importlib.import_module("src.api.app")
    from src.shared import scout_progress

    scout_progress.start("top_buys")
    scout_progress.stage("screening")
    out = app.idea_scout_progress()
    assert out.active is True
    assert out.current == "screening"
    assert any(s.key == "screening" and s.status == "running" for s in out.stages)
