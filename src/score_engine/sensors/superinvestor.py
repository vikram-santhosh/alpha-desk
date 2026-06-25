"""Superinvestor / 13F sensor — adapter over advisor.superinvestor_tracker.

Reads pre-computed smart-money summaries from memory (insider net buying,
superinvestor 13F activity) and emits one TickerSignal per ticker. Smart-money
corroboration is high-signal for a personal research tool.
"""
from __future__ import annotations

import asyncio
from datetime import date

from src.score_engine.signals import Direction, TickerSignal


class SuperinvestorSensor:
    name = "superinvestor"
    weight_key = "superinvestor"

    async def vote(self, tickers: list[str], ctx: dict) -> list[TickerSignal]:
        signals = []
        for ticker in tickers:
            try:
                data = await asyncio.to_thread(self._fetch, ticker)
                sig = self._to_signal(ticker, data) if data else None
                if sig:
                    signals.append(sig)
            except Exception:
                pass
        return signals

    def _fetch(self, ticker: str) -> dict | None:
        from src.advisor.superinvestor_tracker import get_smart_money_summary
        return get_smart_money_summary(ticker)

    def _to_signal(self, ticker: str, data: dict) -> TickerSignal | None:
        insider_buying = bool(data.get("insider_net_buying"))
        holders        = data.get("superinvestors_holding") or []
        activity       = data.get("superinvestor_activity") or []

        # Count directional 13F actions among tracked superinvestors.
        adds = sum(1 for a in activity if str(a.get("action", "")).lower() in ("new", "add", "added", "buy", "increase"))
        cuts = sum(1 for a in activity if str(a.get("action", "")).lower() in ("sold", "sell", "reduce", "reduced", "exit", "trim"))

        # No smart-money footprint at all → no signal (honest: don't fabricate).
        if not insider_buying and not holders and not activity:
            return None

        bull_points = adds + (1 if insider_buying else 0)
        bear_points = cuts
        if bull_points > bear_points:
            direction = Direction.BULL
        elif bear_points > bull_points:
            direction = Direction.BEAR
        else:
            direction = Direction.NEUTRAL

        # Strength scales with how many independent smart-money actors corroborate.
        corroborators = adds + cuts + (1 if insider_buying else 0)
        strength = min(corroborators / 4.0, 1.0) if corroborators else 0.3

        # Confidence: more holders / actors = cleaner read.
        confidence = min(0.5 + 0.1 * (len(holders) + len(activity)), 0.9)

        bits = []
        if insider_buying:
            bits.append("insider net buying")
        if adds:
            bits.append(f"{adds} superinvestor add(s)")
        if cuts:
            bits.append(f"{cuts} superinvestor cut(s)")
        if holders and not bits:
            bits.append(f"{len(holders)} superinvestor holder(s)")
        evidence = ", ".join(bits)[:120] or "smart-money footprint"

        return TickerSignal(
            ticker=ticker,
            sensor="superinvestor",
            direction=direction,
            strength=round(strength, 3),
            confidence=round(confidence, 3),
            evidence=evidence,
            as_of=date.today().isoformat(),
        )
