"""Breadth gate: a single loud platform cannot reach the top tier."""
from __future__ import annotations

from src.score_engine.aggregator import BREADTH_MIN, TOP_TIER_MIN, score_tickers
from src.score_engine.signals import Direction, TickerSignal


def _find(results, ticker):
    return next(s for s in results if s.ticker == ticker)


def test_single_platform_capped_below_7():
    """One platform at max strength → score < 7.0."""
    signals = [
        TickerSignal("NVDA", "earnings", Direction.BULL, 1.0, 1.0, "perfect", "2026-06-23"),
    ]
    weights = {"earnings": 2.0}
    result = score_tickers(signals, weights, [])
    nvda = _find(result, "NVDA")
    assert nvda.score < 7.0, f"Expected <7.0 with 1 platform, got {nvda.score}"


def test_two_platforms_can_reach_7():
    """BREADTH_MIN (2) agreeing platforms → score >= 7.0 is achievable."""
    signals = [
        TickerSignal("NVDA", "earnings", Direction.BULL, 0.9, 0.9, "strong guide",  "2026-06-23"),
        TickerSignal("NVDA", "reddit",   Direction.BULL, 0.8, 0.8, "high mentions", "2026-06-23"),
    ]
    weights = {"earnings": 1.8, "reddit": 0.8}
    result = score_tickers(signals, weights, [])
    nvda = _find(result, "NVDA")
    assert nvda.score >= 7.0, (
        f"Expected >=7.0 with {BREADTH_MIN} bull platforms, got {nvda.score}"
    )


def test_two_platforms_capped_below_8():
    """Two bull platforms → cannot reach 8.0 (top-tier requires TOP_TIER_MIN=3)."""
    signals = [
        TickerSignal("NVDA", "earnings", Direction.BULL, 1.0, 1.0, "max",  "2026-06-23"),
        TickerSignal("NVDA", "reddit",   Direction.BULL, 1.0, 1.0, "max",  "2026-06-23"),
    ]
    weights = {"earnings": 2.0, "reddit": 2.0}
    result = score_tickers(signals, weights, [])
    nvda = _find(result, "NVDA")
    assert nvda.score < 8.0, f"Expected <8.0 with only 2 platforms, got {nvda.score}"


def test_top_tier_requires_three_platforms():
    """Three bull platforms → eligible for 8–10."""
    signals = [
        TickerSignal("NVDA", "earnings", Direction.BULL, 1.0, 1.0, "guide",  "2026-06-23"),
        TickerSignal("NVDA", "reddit",   Direction.BULL, 1.0, 1.0, "reddit", "2026-06-23"),
        TickerSignal("NVDA", "news",     Direction.BULL, 1.0, 1.0, "news",   "2026-06-23"),
    ]
    weights = {"earnings": 2.0, "reddit": 1.0, "news": 1.0}
    result = score_tickers(signals, weights, [])
    nvda = _find(result, "NVDA")
    assert nvda.score >= 8.0, (
        f"Expected >=8.0 with {TOP_TIER_MIN} strong bull platforms, got {nvda.score}"
    )


def test_bear_signal_lowers_score():
    """A BEAR signal subtracts from the score."""
    bull_only = [TickerSignal("AMZN", "earnings", Direction.BULL, 0.8, 0.8, "ok",  "2026-06-23")]
    mixed     = bull_only + [
        TickerSignal("AMZN", "reddit", Direction.BEAR, 0.8, 0.8, "negative", "2026-06-23")
    ]
    weights = {"earnings": 1.0, "reddit": 1.0}

    r_bull  = score_tickers(bull_only, weights, [])
    r_mixed = score_tickers(mixed,     weights, [])

    amzn_bull  = _find(r_bull,  "AMZN")
    amzn_mixed = _find(r_mixed, "AMZN")
    assert amzn_mixed.score < amzn_bull.score, (
        f"Mixed signals should lower score: {amzn_mixed.score} vs {amzn_bull.score}"
    )


def test_weak_bear_does_not_veto_two_positive_platforms():
    """AMZN-like evidence should land in the buy band, not collapse to Weak."""
    signals = [
        TickerSignal("AMZN", "earnings", Direction.BULL, 0.69, 0.75, "EPS beat", "2026-06-23"),
        TickerSignal("AMZN", "valuation", Direction.BULL, 0.40, 0.70, "margin of safety", "2026-06-23"),
        TickerSignal("AMZN", "news", Direction.BEAR, 0.16, 0.90, "policy concern", "2026-06-23"),
    ]
    weights = {"earnings": 1.8, "valuation": 1.4, "news": 1.0}

    result = score_tickers(signals, weights, [])
    amzn = _find(result, "AMZN")

    assert 7.0 <= amzn.score < 8.0


def test_neutral_signal_does_not_count_toward_breadth():
    """A NEUTRAL signal does not count as a bull platform for the breadth gate."""
    signals = [
        TickerSignal("GOOG", "earnings", Direction.BULL,    0.9, 0.9, "guide",    "2026-06-23"),
        TickerSignal("GOOG", "reddit",   Direction.NEUTRAL, 0.5, 0.5, "neutral",  "2026-06-23"),
    ]
    weights = {"earnings": 1.8, "reddit": 0.8}
    result = score_tickers(signals, weights, [])
    goog = _find(result, "GOOG")
    # Only 1 BULL platform → capped below 7.0
    assert goog.score < 7.0, (
        f"Neutral platform should not contribute to breadth gate, got {goog.score}"
    )


def test_platforms_reporting_populated():
    """platforms_reporting contains exactly the sensors that voted for this ticker."""
    signals = [
        TickerSignal("MSFT", "earnings", Direction.BULL, 0.7, 0.8, "ok", "2026-06-23"),
        TickerSignal("MSFT", "reddit",   Direction.BULL, 0.5, 0.6, "ok", "2026-06-23"),
    ]
    result = score_tickers(signals, {"earnings": 1.0, "reddit": 1.0}, [])
    msft = _find(result, "MSFT")
    assert set(msft.platforms_reporting) == {"earnings", "reddit"}


def test_missing_sensors_recorded_on_every_ticker():
    """platforms_failed reflects missing_sensors regardless of which ticker."""
    signals = [
        TickerSignal("NVDA", "earnings", Direction.BULL, 0.8, 0.8, "x", "2026-06-23"),
        TickerSignal("AMZN", "reddit",   Direction.BULL, 0.6, 0.6, "y", "2026-06-23"),
    ]
    missing = ["news", "superinvestor"]
    result  = score_tickers(signals, {"earnings": 1.0, "reddit": 1.0}, missing)
    for ts in result:
        assert set(ts.platforms_failed) == set(missing), (
            f"{ts.ticker} platforms_failed mismatch: {ts.platforms_failed}"
        )
