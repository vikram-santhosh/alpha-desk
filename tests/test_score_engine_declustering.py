"""Mid-breadth score-engine names must spread by conviction, not all pin to 7.9."""
from __future__ import annotations

from src.score_engine.aggregator import score_tickers
from src.score_engine.signals import Direction, TickerSignal


def _bull(ticker: str, sensor: str, strength: float, confidence: float) -> TickerSignal:
    return TickerSignal(
        ticker=ticker,
        sensor=sensor,
        direction=Direction.BULL,
        strength=strength,
        confidence=confidence,
        evidence="e",
        as_of="2026-06-27",
    )


def test_mid_breadth_names_spread_instead_of_pinning_to_7_9():
    signals: list[TickerSignal] = []
    # Each name has exactly 2 bullish platforms (mid-breadth tier) but different
    # conviction. Before the fix all three returned exactly 7.9.
    for ticker, strength, confidence in [("HIGH", 0.95, 0.95), ("MID", 0.6, 0.6), ("LOW", 0.4, 0.4)]:
        signals.append(_bull(ticker, "earnings", strength, confidence))
        signals.append(_bull(ticker, "valuation", strength, confidence))

    scores = {s.ticker: s.score for s in score_tickers(signals, weights={}, missing_sensors=[])}
    vals = [scores["HIGH"], scores["MID"], scores["LOW"]]

    assert vals != [7.9, 7.9, 7.9]
    assert len(set(vals)) == 3, f"still clustered: {vals}"
    assert scores["HIGH"] > scores["MID"] > scores["LOW"]
    # Still respects the 2-platform tier ceiling.
    assert all(7.0 <= v < 8.0 for v in vals), vals
