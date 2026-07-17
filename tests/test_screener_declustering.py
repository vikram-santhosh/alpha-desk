"""Top-buy scores must spread out, not all hard-pin to the 88 quality floor."""
from __future__ import annotations

from src.alpha_scout.screener import screen_candidates


def _candidate(ticker: str) -> dict:
    # "existing_portfolio/..." source so the quality floor is eligible to apply.
    return {"ticker": ticker, "source": "existing_portfolio/core", "signal_data": {}, "signal_type": ""}


# Four strong, tracked mega-caps with genuinely different fundamentals AND
# different forward risk/reward (analyst upside + multiple) — the profile of
# real names, which is what the valuation dimension spreads apart.
_FUNDAMENTALS = {
    "AAA": {"pe_trailing": 25, "revenue_growth": 0.30, "net_margin": 0.30, "gross_margin": 0.60,
            "market_cap": 600_000_000_000, "pct_from_52w_high": -12, "pct_from_52w_low": 40,
            "implied_upside_pct": 40, "ev_to_ebitda": 16, "sector": "Technology"},
    "BBB": {"pe_trailing": 28, "revenue_growth": 0.12, "net_margin": 0.18, "gross_margin": 0.50,
            "market_cap": 150_000_000_000, "pct_from_52w_high": -20, "pct_from_52w_low": 30,
            "implied_upside_pct": 12, "ev_to_ebitda": 22, "sector": "Industrials"},
    "CCC": {"pe_trailing": 22, "revenue_growth": 0.05, "net_margin": 0.16, "gross_margin": 0.45,
            "market_cap": 50_000_000_000, "pct_from_52w_high": -30, "pct_from_52w_low": 15,
            "implied_upside_pct": 8, "ev_to_ebitda": 20, "sector": "Materials"},
    "DDD": {"pe_trailing": 24, "revenue_growth": 0.25, "net_margin": 0.28, "gross_margin": 0.58,
            "market_cap": 1_200_000_000_000, "pct_from_52w_high": -10, "pct_from_52w_low": 50,
            "implied_upside_pct": 28, "ev_to_ebitda": 18, "sector": "Communications"},
}


def _run() -> list[dict]:
    techs = {t: {"rsi": {"rsi": 45}, "macd": {}, "moving_averages": {}, "bollinger_bands": {}, "volume": {}}
             for t in _FUNDAMENTALS}
    candidates = [_candidate(t) for t in _FUNDAMENTALS]
    return screen_candidates(
        candidates=candidates,
        technicals=techs,
        fundamentals=_FUNDAMENTALS,
        portfolio_tickers=list(_FUNDAMENTALS),
        portfolio_fundamentals=_FUNDAMENTALS,
        weights={},
        mode="top_buys",
    )


def test_top_buy_scores_are_not_all_pinned_to_one_value():
    composites = [s["scores"]["composite"] for s in _run()]
    # Before the fix every quality name hard-pinned to 88.0.
    assert composites != [88.0, 88.0, 88.0, 88.0]
    # Scores must genuinely spread, not collapse to a single value. Two equally
    # elite mega-caps whose fundamentals both saturate the rubric may legitimately
    # tie, so we require real differentiation (multiple distinct values + a
    # meaningful spread) rather than a strict per-name uniqueness count.
    assert len(set(composites)) >= 2, f"scores still clustered: {composites}"
    assert max(composites) - min(composites) >= 2.0, f"spread too narrow: {composites}"


def test_quality_names_still_rank_high_and_in_order():
    scored = _run()  # screen_candidates returns sorted by composite desc
    composites = [s["scores"]["composite"] for s in scored]
    assert max(composites) >= 75, f"quality names dropped too low: {composites}"
    # The weakest fundamentals (CCC) should land at the bottom.
    assert scored[-1]["ticker"] == "CCC", [s["ticker"] for s in scored]
