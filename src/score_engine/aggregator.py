"""Pure, deterministic score aggregator.

score_tickers() is a pure function: same inputs → identical outputs every time.
No I/O, no globals, no randomness.

Scoring algorithm:
  1. Deduplicate (ticker, sensor) pairs — keep highest-confidence signal.
  2. raw_score(ticker) = Σ weight[sensor] × direction × strength × confidence
  3. Normalize to 0–10:  score = clamp(raw / MAX_RAW * 10, 0, 10)
     where MAX_RAW = Σ weight[sensor] (all sensors at full bull).
  4. Breadth gate:
       bull_platforms < BREADTH_MIN  → cap at 6.9
       bull_platforms in [BREADTH_MIN, TOP_TIER_MIN)  → cap at 7.9
       bull_platforms >= TOP_TIER_MIN → no cap (full 0–10 range)
  5. Stable sort: (-score, ticker) so ties break alphabetically.
"""
from __future__ import annotations

from src.score_engine.signals import Direction, TickerSignal, TickerScore

BREADTH_MIN   = 2    # platforms required to cross 7.0
TOP_TIER_MIN  = 3    # platforms required for 8–10 band
SCORE_SCALE   = 10.0
SCORE_PRECISION = 2

# When no weights entry exists for a sensor, use this fallback.
DEFAULT_SENSOR_WEIGHT = 1.0

# Denominator baseline: sum of default weights for all known sensors.
# If actual weights differ, MAX_RAW is recomputed per call.
_FALLBACK_MAX_RAW = 10.0


def _dedup(signals: list[TickerSignal]) -> list[TickerSignal]:
    """Keep one signal per (ticker, sensor) — highest confidence wins."""
    best: dict[tuple[str, str], TickerSignal] = {}
    for sig in signals:
        key = (sig.ticker, sig.sensor)
        if key not in best or sig.confidence > best[key].confidence:
            best[key] = sig
    return list(best.values())


def score_tickers(
    signals: list[TickerSignal],
    weights: dict[str, float],
    missing_sensors: list[str],
) -> list[TickerScore]:
    """Score every ticker that has at least one signal.

    Args:
        signals: Raw TickerSignals from all sensors.
        weights: Sensor-name → weight float.
        missing_sensors: Sensor names that failed this run (recorded on every score).

    Returns:
        List of TickerScore, stable-sorted by (-score, ticker).
    """
    deduped = _dedup(signals)

    # Group by ticker
    by_ticker: dict[str, list[TickerSignal]] = {}
    for sig in deduped:
        by_ticker.setdefault(sig.ticker, []).append(sig)

    scores: list[TickerScore] = []

    for ticker, ticker_signals in by_ticker.items():
        raw = 0.0
        breakdown: list[dict] = []
        bull_platforms: list[str] = []
        bear_platforms: list[str] = []

        # Sort signals by sensor name for deterministic breakdown order
        for sig in sorted(ticker_signals, key=lambda s: s.sensor):
            w = weights.get(sig.sensor, DEFAULT_SENSOR_WEIGHT)
            contribution = w * sig.direction.value * sig.strength * sig.confidence
            raw += contribution
            breakdown.append({
                "sensor":       sig.sensor,
                "direction":    sig.direction.name,
                "strength":     sig.strength,
                "confidence":   sig.confidence,
                "weight":       w,
                "contribution": round(contribution, 4),
                "evidence":     sig.evidence,
            })
            if sig.direction == Direction.BULL:
                bull_platforms.append(sig.sensor)
            elif sig.direction == Direction.BEAR:
                bear_platforms.append(sig.sensor)

        # Conviction-weighted normalization. Divide by the confidence-weighted
        # weight of only the platforms that took a DIRECTIONAL stance. Neutral
        # "no view" votes add 0 to the numerator and are excluded from the
        # denominator so they don't dilute genuine consensus. The result is the
        # average conviction (0..1) among platforms that have a view, scaled to
        # 0..10; the breadth gate below caps how high a thinly-corroborated name
        # may climb. Adding sensors can no longer lower a score.
        denom = sum(
            weights.get(s.sensor, DEFAULT_SENSOR_WEIGHT) * s.confidence
            for s in ticker_signals if s.direction != Direction.NEUTRAL
        )
        if denom <= 0:
            raw_score = 0.0   # no directional conviction → not a buy
        else:
            raw_score = max(0.0, raw / denom * SCORE_SCALE)
            raw_score = min(raw_score, SCORE_SCALE)

        # Breadth gate
        n_bull = len(bull_platforms)
        if n_bull < BREADTH_MIN:
            raw_score = min(raw_score, 6.9)
        elif n_bull < TOP_TIER_MIN:
            raw_score = min(raw_score, 7.9)

        final_score = round(raw_score, SCORE_PRECISION)

        scores.append(TickerScore(
            ticker=ticker,
            score=final_score,
            platforms_reporting=sorted(set(s.sensor for s in ticker_signals)),
            platforms_failed=list(missing_sensors),
            breakdown=breakdown,
        ))

    # Stable sort: highest score first; alphabetical ticker as tiebreaker
    scores.sort(key=lambda s: (-s.score, s.ticker))
    return scores
