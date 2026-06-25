"""Prediction-market sensor — adapter over stored prediction markets.

Prediction markets are macro context more than per-stock conviction, so this
emits a deliberately mild signal: it corroborates that a market-moving theme
touches a ticker, weighted by the market's probability, without overclaiming
single-name direction.
"""
from __future__ import annotations

import asyncio
from datetime import date

from src.score_engine.signals import Direction, TickerSignal

# Categories whose rising probability is broadly constructive for risk assets.
RISK_ON_CATEGORIES = {"fed_policy", "fiscal_policy"}
RISK_OFF_CATEGORIES = {"recession", "trade_war", "regulation"}


class PredictionSensor:
    name = "prediction"
    weight_key = "prediction"

    async def vote(self, tickers: list[str], ctx: dict) -> list[TickerSignal]:
        markets = await asyncio.to_thread(self._fetch)
        if not markets:
            return []

        # Aggregate per ticker across all markets touching it.
        agg: dict[str, dict] = {}
        for m in markets:
            tickers_hit = m.get("affected_tickers") or []
            category = (m.get("category") or "").lower()
            prob = m.get("probability")
            try:
                prob = float(prob) if prob is not None else None
            except (TypeError, ValueError):
                prob = None
            if prob is None:
                continue
            if category in RISK_ON_CATEGORIES:
                lean = (prob - 0.5) * 2          # high prob → bullish
            elif category in RISK_OFF_CATEGORIES:
                lean = -(prob - 0.5) * 2         # high prob → bearish
            else:
                lean = 0.0
            for t in tickers_hit:
                if not isinstance(t, str):
                    continue
                e = agg.setdefault(t, {"lean": 0.0, "count": 0, "note": ""})
                e["lean"] += lean
                e["count"] += 1
                if not e["note"]:
                    e["note"] = (m.get("title") or category)[:70]

        today = date.today().isoformat()
        signals = []
        for t in tickers:
            e = agg.get(t)
            if not e or e["count"] == 0:
                continue
            avg_lean = e["lean"] / e["count"]
            if avg_lean > 0.15:
                direction = Direction.BULL
            elif avg_lean < -0.15:
                direction = Direction.BEAR
            else:
                direction = Direction.NEUTRAL
            strength = min(abs(avg_lean), 1.0)
            confidence = min(0.45 + 0.1 * e["count"], 0.75)   # deliberately modest
            evidence = f"{e['count']} market(s) — {e['note']}"[:120]
            signals.append(TickerSignal(
                ticker=t, sensor="prediction", direction=direction,
                strength=round(strength, 3), confidence=round(confidence, 3),
                evidence=evidence, as_of=today,
            ))
        return signals

    def _fetch(self) -> list[dict]:
        from src.advisor.memory import get_prediction_markets
        return get_prediction_markets()
