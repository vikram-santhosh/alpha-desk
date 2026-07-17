"""Golden-fixture regression guard: the Alpha Scout screener and the score
engine's valuation sensor must always agree on fundamental quality, because
they both import src.shared.fundamental_quality. If this ever fails, someone
re-inlined divergent scoring logic in one of the two call sites — the exact
drift that let a name fixed in the screener resurface via the score-engine
fallback path."""
from __future__ import annotations

FIXTURES = [
    {},
    {
        "pe_trailing": 72.0, "ev_to_ebitda": 53.7, "revenue_growth": 0.33,
        "net_margin": 0.10, "gross_margin": 0.48, "implied_upside_pct": 5.5,
        "pct_from_52w_high": -20.5, "market_cap": 26_000_000_000,
    },
    {
        "pe_trailing": 25.0, "ev_to_ebitda": 18.0, "revenue_growth": 0.30,
        "net_margin": 0.40, "gross_margin": 0.70, "implied_upside_pct": 35.0,
        "pct_from_52w_high": -12.0, "market_cap": 1_000_000_000_000,
    },
    {
        "pe_trailing": 16, "ev_to_ebitda": 16, "revenue_growth": 1.2,
        "net_margin": 0.04, "gross_margin": 0.08, "free_cashflow": -7e9,
        "implied_upside_pct": 21, "pct_from_52w_high": -50, "market_cap": 20e9,
    },
    {"net_margin": -0.20, "revenue_growth": 0.05},
]


def test_screener_and_shared_module_score_identically():
    from src.alpha_scout.screener import score_fundamental
    from src.shared.fundamental_quality import score_fundamental_quality

    for fixture in FIXTURES:
        assert score_fundamental(fixture) == score_fundamental_quality(fixture), fixture


def test_screener_and_shared_module_explain_identically():
    from src.alpha_scout.screener import explain_fundamental_factors
    from src.shared.fundamental_quality import explain_fundamental_quality

    for fixture in FIXTURES:
        assert explain_fundamental_factors(fixture) == explain_fundamental_quality(fixture), fixture


def test_valuation_sensor_uses_the_same_shared_rubric():
    from src.score_engine.sensors.valuation import score_fundamental_quality as sensor_scorer
    from src.shared.fundamental_quality import score_fundamental_quality as shared_scorer

    assert sensor_scorer is shared_scorer
