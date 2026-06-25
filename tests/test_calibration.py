"""Score calibration guarantees (conviction-weighted rubric).

Locks in the agreed rubric:
- a strong 2-platform consensus lands in the Strong tier (>=7 before the
  2-platform cap, realized as the 7.9 cap),
- a strong 3-platform consensus reaches the Conviction tier (>=8.5),
- NEUTRAL "no view" votes do NOT dilute a directional consensus,
- adding a non-reporting sensor never lowers a score.
"""
from __future__ import annotations

from src.score_engine.aggregator import score_tickers
from src.score_engine.signals import Direction, TickerSignal


def _find(rows, ticker):
    return next(r for r in rows if r.ticker == ticker)


def test_strong_two_platform_consensus_reaches_strong_tier():
    signals = [
        TickerSignal("NVDA", "earnings",  Direction.BULL, 0.9, 0.85, "beat", "2026-06-24"),
        TickerSignal("NVDA", "valuation", Direction.BULL, 0.9, 0.8,  "cheap", "2026-06-24"),
    ]
    weights = {"earnings": 1.8, "valuation": 1.4}
    nvda = _find(score_tickers(signals, weights, []), "NVDA")
    assert nvda.score >= 7.0, f"strong 2-platform consensus should hit Strong tier, got {nvda.score}"


def test_strong_three_platform_consensus_reaches_conviction_tier():
    signals = [
        TickerSignal("NVDA", "earnings",  Direction.BULL, 0.9, 0.9, "beat",  "2026-06-24"),
        TickerSignal("NVDA", "valuation", Direction.BULL, 0.9, 0.9, "cheap", "2026-06-24"),
        TickerSignal("NVDA", "news",      Direction.BULL, 0.9, 0.9, "good",  "2026-06-24"),
    ]
    weights = {"earnings": 1.8, "valuation": 1.4, "news": 1.0}
    nvda = _find(score_tickers(signals, weights, []), "NVDA")
    assert nvda.score >= 8.5, f"strong 3-platform consensus should hit Conviction tier, got {nvda.score}"


def test_neutral_vote_does_not_dilute_consensus():
    """Adding a NEUTRAL 'no view' platform must not lower a directional score."""
    base = [
        TickerSignal("NVDA", "earnings",  Direction.BULL, 0.9, 0.85, "beat",  "2026-06-24"),
        TickerSignal("NVDA", "valuation", Direction.BULL, 0.9, 0.8,  "cheap", "2026-06-24"),
    ]
    with_neutral = base + [
        TickerSignal("NVDA", "news", Direction.NEUTRAL, 0.5, 0.6, "mixed", "2026-06-24"),
    ]
    weights = {"earnings": 1.8, "valuation": 1.4, "news": 1.0}
    s_base    = _find(score_tickers(base, weights, []), "NVDA").score
    s_neutral = _find(score_tickers(with_neutral, weights, []), "NVDA").score
    assert s_neutral == s_base, f"neutral vote diluted consensus: {s_base} -> {s_neutral}"


def test_bear_vote_still_lowers_score():
    """A genuine BEAR view must still pull conviction down (sanity guard)."""
    base = [
        TickerSignal("AMZN", "earnings",  Direction.BULL, 0.8, 0.8, "beat", "2026-06-24"),
        TickerSignal("AMZN", "valuation", Direction.BULL, 0.8, 0.8, "ok",   "2026-06-24"),
    ]
    with_bear = base + [
        TickerSignal("AMZN", "news", Direction.BEAR, 0.8, 0.8, "lawsuit", "2026-06-24"),
    ]
    weights = {"earnings": 1.8, "valuation": 1.4, "news": 1.0}
    s_base = _find(score_tickers(base, weights, []), "AMZN").score
    s_bear = _find(score_tickers(with_bear, weights, []), "AMZN").score
    assert s_bear < s_base, f"bear view should lower score: {s_base} -> {s_bear}"
