from __future__ import annotations

import asyncio

from src.score_engine.sensors.valuation import ValuationSensor
from src.score_engine.signals import Direction

AFRM_LIKE = {
    "pe_trailing": 72.0, "pe_forward": 21.0, "ev_to_ebitda": 53.7,
    "revenue_growth": 0.33, "net_margin": 0.10, "gross_margin": 0.48,
    "implied_upside_pct": 5.5, "pct_from_52w_high": -20.5,
    "market_cap": 26_000_000_000,
}

HIGH_QUALITY = {
    "pe_trailing": 25.0, "ev_to_ebitda": 18.0,
    "revenue_growth": 0.30, "net_margin": 0.40, "gross_margin": 0.70,
    "implied_upside_pct": 35.0, "pct_from_52w_high": -12.0,
    "market_cap": 1_000_000_000_000,
}

BROKEN_FUNDAMENTALS = {
    "revenue_growth": -0.20, "net_margin": -0.30, "gross_margin": 0.05,
    "free_cashflow": -1_000_000_000, "implied_upside_pct": -15.0,
}

# Same CAGR/margin-of-safety pair used by the pre-existing bullish-signal test.
BULLISH_VAL = {"implied_cagr": 13.0, "margin_of_safety": 46.0}


def test_high_quality_fundamentals_keep_full_bull_strength():
    sensor = ValuationSensor()
    signal = sensor._to_signal("QUALCO", BULLISH_VAL, HIGH_QUALITY)  # noqa: SLF001

    assert signal.direction == Direction.BULL
    assert signal.strength == 0.62  # unchanged: quality 100 -> no discount


def test_afrm_like_fundamentals_discount_bull_strength_but_stay_bull():
    """AFRM's profile (rich P/E/EV-EBITDA, thin analyst upside) scores a
    mediocre ~70/100 on the shared quality rubric — not garbage, so it stays
    BULL if the DCF says so, but its conviction is discounted proportionally
    rather than treated as full-strength undervaluation."""
    sensor = ValuationSensor()
    signal = sensor._to_signal("AFRM", BULLISH_VAL, AFRM_LIKE)  # noqa: SLF001

    assert signal.direction == Direction.BULL
    assert signal.strength < 0.62
    assert "fundamental quality" in signal.evidence


def test_broken_fundamentals_force_bear_despite_bullish_dcf():
    """A DCF holding a P/E flat while compounding growth can show an
    attractive implied CAGR even for a name with deep losses and cash burn.
    Quality below the hard floor overrides the DCF's direction to BEAR."""
    sensor = ValuationSensor()
    signal = sensor._to_signal("BROKEN", BULLISH_VAL, BROKEN_FUNDAMENTALS)  # noqa: SLF001

    assert signal.direction == Direction.BEAR
    assert "weak" in signal.evidence


def test_no_fundamentals_passed_preserves_prior_behavior():
    sensor = ValuationSensor()
    signal = sensor._to_signal("AMZN", BULLISH_VAL)  # noqa: SLF001

    assert signal.direction == Direction.BULL
    assert signal.strength >= 0.4


def test_vote_threads_fundamentals_into_quality_gate(monkeypatch):
    """End-to-end: vote() must fetch fundamentals and pass them through to the
    quality gate, not just the DCF output — this is the wiring that broke
    silently if _value() only returned the val dict."""
    sensor = ValuationSensor()

    def fake_fetch_fundamentals(ticker):
        return AFRM_LIKE

    def fake_compute_target_price(ticker, fundamentals):
        assert fundamentals == AFRM_LIKE
        return dict(BULLISH_VAL, insufficient_data=False, ticker=ticker)

    monkeypatch.setattr(
        "src.portfolio_analyst.fundamental_analyzer.fetch_fundamentals",
        fake_fetch_fundamentals,
    )
    monkeypatch.setattr(
        "src.advisor.valuation_engine.compute_target_price",
        fake_compute_target_price,
    )

    signals = asyncio.new_event_loop().run_until_complete(sensor.vote(["AFRM"], {}))

    assert len(signals) == 1
    assert signals[0].direction == Direction.BULL
    assert signals[0].strength < 0.62  # discounted, proving fundamentals reached the gate
