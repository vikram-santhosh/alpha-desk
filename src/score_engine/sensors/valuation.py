"""Valuation sensor — adapter over valuation_engine (forward-looking).

This is the signal that distinguishes analysis from momentum-chasing: it scores
on implied 3-year CAGR and margin of safety (what's priced in), not on what
already happened. Fetches fundamentals live, then runs the existing scenario
valuation. A name that's run up but is now expensive scores BEAR here even if
its earnings beat — the corrective the score engine needs.
"""
from __future__ import annotations

import asyncio
from datetime import date

from src.score_engine.signals import Direction, TickerSignal

# Gate thresholds for score-engine "top buy" evidence. A moonshot-grade 25%+
# CAGR is ideal, but a mega-cap with a moderate forward CAGR and a large margin
# of safety should still count as bullish rather than neutral.
HIGH_CAGR = 25.0
MIN_ATTRACTIVE_CAGR = 12.0
MIN_MOS = 15.0
HIGH_MOS = 35.0


class ValuationSensor:
    name = "valuation"
    weight_key = "valuation"

    async def vote(self, tickers: list[str], ctx: dict) -> list[TickerSignal]:
        signals = []
        for ticker in tickers:
            try:
                val = await asyncio.to_thread(self._value, ticker)
                sig = self._to_signal(ticker, val) if val else None
                if sig:
                    signals.append(sig)
            except Exception:
                pass
        return signals

    def _value(self, ticker: str) -> dict | None:
        from src.portfolio_analyst.fundamental_analyzer import fetch_fundamentals
        from src.advisor.valuation_engine import compute_target_price
        fundamentals = fetch_fundamentals(ticker)
        if not fundamentals:
            return None
        return compute_target_price(ticker, fundamentals)

    def _to_signal(self, ticker: str, val: dict) -> TickerSignal | None:
        if val.get("insufficient_data"):
            return None
        cagr = val.get("implied_cagr")
        mos  = val.get("margin_of_safety")
        if cagr is None or mos is None:
            return None

        # Direction: attractive forward return + cushion = BULL; expensive = BEAR.
        if (
            cagr >= HIGH_CAGR and mos >= MIN_MOS
        ) or (
            cagr >= MIN_ATTRACTIVE_CAGR and mos >= HIGH_MOS
        ):
            direction = Direction.BULL
        elif cagr < 10.0 or mos < 0.0:
            direction = Direction.BEAR
        else:
            direction = Direction.NEUTRAL

        # Strength from distance past (or below) the CAGR gate, capped.
        if direction == Direction.BULL:
            cagr_strength = (cagr - HIGH_CAGR) / 25.0 + 0.4
            mos_strength = (mos - HIGH_MOS) / 50.0 + 0.4
            strength = min(max(cagr_strength, mos_strength, 0.4), 1.0)
        elif direction == Direction.BEAR:
            strength = min((HIGH_CAGR - cagr) / 25.0 + 0.3, 1.0)
        else:
            strength = 0.4

        confidence = 0.7   # quantitative but model/assumption dependent
        evidence = f"implied CAGR {cagr:.0f}%, margin of safety {mos:.0f}%"[:120]

        return TickerSignal(
            ticker=ticker,
            sensor="valuation",
            direction=direction,
            strength=round(max(strength, 0.0), 3),
            confidence=confidence,
            evidence=evidence,
            as_of=date.today().isoformat(),
        )
