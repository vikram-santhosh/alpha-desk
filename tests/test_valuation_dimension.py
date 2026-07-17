"""The valuation dimension must break ties between equally-strong businesses
that differ on forward risk/reward — the MU (75% analyst upside) vs TSM (22%)
case that previously collapsed to an identical 88."""
from __future__ import annotations

from src.alpha_scout.screener import score_valuation, screen_candidates


def test_high_upside_scores_above_low_upside():
    # Two names identical except analyst implied upside.
    high = {"pe_trailing": 21, "implied_upside_pct": 75, "ev_to_ebitda": 12}
    low = {"pe_trailing": 21, "implied_upside_pct": 20, "ev_to_ebitda": 12}
    assert score_valuation(high) > score_valuation(low) + 15


def test_valuation_is_continuous_not_bucketed():
    # A 1-point upside change should move the score (no coarse plateaus at the
    # values that matter for ranking).
    a = score_valuation({"implied_upside_pct": 30})
    b = score_valuation({"implied_upside_pct": 45})
    c = score_valuation({"implied_upside_pct": 60})
    assert a < b < c


def test_no_data_is_neutral():
    assert score_valuation({}) == 50


def _tracked(t: str) -> dict:
    return {"ticker": t, "source": "existing_portfolio/core", "signal_data": {}, "signal_type": ""}


def test_two_elite_names_separate_by_upside_in_full_screen():
    funds = {
        "MU":  {"pe_trailing": 21, "revenue_growth": 0.34, "net_margin": 0.30, "gross_margin": 0.55,
                "market_cap": 150_000_000_000, "pct_from_52w_high": -20, "implied_upside_pct": 75,
                "ev_to_ebitda": 11, "sector": "Technology"},
        "TSM": {"pe_trailing": 24, "revenue_growth": 0.35, "net_margin": 0.40, "gross_margin": 0.58,
                "market_cap": 900_000_000_000, "pct_from_52w_high": -8, "implied_upside_pct": 22,
                "ev_to_ebitda": 15, "sector": "Technology"},
    }
    techs = {t: {"rsi": {"rsi": 50}, "macd": {}, "moving_averages": {}, "bollinger_bands": {}, "volume": {}}
             for t in funds}
    scored = screen_candidates(
        candidates=[_tracked(t) for t in funds],
        technicals=techs,
        fundamentals=funds,
        portfolio_tickers=list(funds),
        portfolio_fundamentals=funds,
        weights={},
        mode="top_buys",
    )
    by = {s["ticker"]: s["scores"]["composite"] for s in scored}
    # MU's far larger analyst upside must rank it clearly ahead — not a tie.
    assert by["MU"] > by["TSM"], by
    assert by["MU"] - by["TSM"] >= 2.0, by
