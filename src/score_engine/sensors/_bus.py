"""Shared helper: read per-ticker sentiment from the agent bus.

News, YouTube, and Substack agents publish signals to the agent bus with a
payload carrying `affected_tickers` (or `tickers`) and a `sentiment` in -2..+2.
This aggregates those into a per-ticker (sentiment_sum, count) so each sensor
can map them to a TickerSignal. Reuses the existing transport (charter: one path).
"""
from __future__ import annotations

from datetime import date
from typing import Iterable

from src.score_engine.signals import Direction, TickerSignal


def aggregate_bus_sentiment(signal_types: Iterable[str], limit: int = 200) -> dict[str, dict]:
    """Return {ticker: {"sentiment_sum": float, "count": int, "samples": [str]}}.

    Reads recent bus signals of the given types (read-only; does not consume).
    """
    from src.shared.agent_bus import get_recent_signals

    wanted = set(signal_types)
    out: dict[str, dict] = {}
    for sig in get_recent_signals(limit=limit):
        if sig.get("signal_type") not in wanted:
            continue
        payload = sig.get("payload") or {}
        tickers = payload.get("affected_tickers") or payload.get("tickers") or []
        try:
            sentiment = float(payload.get("sentiment", 0) or 0)
        except (TypeError, ValueError):
            sentiment = 0.0
        note = (payload.get("summary") or payload.get("title") or "")[:80]
        for t in tickers:
            if not isinstance(t, str):
                continue
            entry = out.setdefault(t, {"sentiment_sum": 0.0, "count": 0, "samples": []})
            entry["sentiment_sum"] += sentiment
            entry["count"] += 1
            if note and len(entry["samples"]) < 2:
                entry["samples"].append(note)
    return out


def build_bus_signals(
    sensor: str,
    signal_types: Iterable[str],
    tickers: list[str],
    *,
    min_count: int = 1,
) -> list[TickerSignal]:
    """Map aggregated bus sentiment into TickerSignals for `tickers`.

    sentiment is on a -2..+2 scale; strength normalises |avg|/2. Confidence
    grows with how many items mention the ticker (more corroboration = cleaner).
    """
    agg = aggregate_bus_sentiment(signal_types)
    today = date.today().isoformat()
    signals: list[TickerSignal] = []
    for t in tickers:
        entry = agg.get(t)
        if not entry or entry["count"] < min_count:
            continue
        count = entry["count"]
        avg = entry["sentiment_sum"] / count
        if avg > 0.3:
            direction = Direction.BULL
        elif avg < -0.3:
            direction = Direction.BEAR
        else:
            direction = Direction.NEUTRAL
        strength = min(abs(avg) / 2.0, 1.0)
        confidence = min(0.5 + 0.1 * count, 0.9)
        note = "; ".join(entry["samples"]) or f"{count} item(s)"
        evidence = f"{count} item(s), avg_sentiment={avg:+.2f} — {note}"[:120]
        signals.append(TickerSignal(
            ticker=t,
            sensor=sensor,
            direction=direction,
            strength=round(strength, 3),
            confidence=round(confidence, 3),
            evidence=evidence,
            as_of=today,
        ))
    return signals
