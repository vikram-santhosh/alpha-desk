"""Top-tier (3+ bull platform) names must spread by conviction, not all pin to
10 — otherwise a 40% EPS beat ties a marginal one and breadth alone decides."""
from __future__ import annotations

from src.score_engine.aggregator import score_tickers
from src.score_engine.signals import Direction, TickerSignal


def _bull(ticker, sensor, strength, confidence):
    return TickerSignal(ticker, sensor, Direction.BULL, strength, confidence, "e", "2026-07-17")


def test_strong_top_tier_name_beats_marginal_one():
    signals = []
    # Both have 3 bull platforms (top tier), but STRONG has far higher conviction.
    for t, s, c in [("STRONG", 0.95, 0.95), ("MARGINAL", 0.45, 0.55)]:
        for sensor in ("earnings", "valuation", "news"):
            signals.append(_bull(t, sensor, s, c))
    weights = {"earnings": 1.8, "valuation": 1.4, "news": 1.0}

    scores = {x.ticker: x.score for x in score_tickers(signals, weights, [])}
    assert scores["STRONG"] > scores["MARGINAL"], scores
    # Both still qualify as top tier (>= 8.0), but they are not identical.
    assert scores["STRONG"] >= 8.0 and scores["MARGINAL"] >= 8.0, scores
    assert scores["STRONG"] != scores["MARGINAL"], scores


def test_top_tier_no_longer_all_pins_to_10():
    signals = []
    for t, s in [("A", 0.9), ("B", 0.7), ("C", 0.55)]:
        for sensor in ("earnings", "valuation", "news"):
            signals.append(_bull(t, sensor, s, s))
    weights = {"earnings": 1.5, "valuation": 1.5, "news": 1.0}
    scores = [x.score for x in score_tickers(signals, weights, [])]
    assert len(set(scores)) == 3, f"top tier still clustered: {scores}"
    assert max(scores) <= 10.0
