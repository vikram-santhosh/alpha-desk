"""Earnings sensor — adapter over src/advisor/memory earnings history.

Reads the most recently stored earnings call data from memory (populated by
run_earnings_analysis during the morning pipeline) so the score sensor
never re-runs LLM transcript analysis.
"""
from __future__ import annotations

import asyncio
from datetime import date

from src.score_engine.signals import Direction, TickerSignal


class EarningsSensor:
    name = "earnings"
    weight_key = "earnings"

    async def vote(self, tickers: list[str], ctx: dict) -> list[TickerSignal]:
        signals = []
        for ticker in tickers:
            try:
                data = await asyncio.to_thread(self._fetch, ticker)
                if data:
                    signals.append(self._to_signal(ticker, data))
            except Exception:
                pass
        return signals

    def _fetch(self, ticker: str) -> dict | None:
        from src.advisor.memory import get_earnings_history
        history = get_earnings_history(ticker, quarters=1)
        if not history:
            return None
        return history[0]

    def _to_signal(self, ticker: str, data: dict) -> TickerSignal:
        guidance = (data.get("guidance_sentiment") or "neutral").lower()
        tone = (data.get("management_tone") or "neutral").lower()

        # Compute rough surprise_pct from eps actual vs estimate
        eps_actual   = data.get("eps_actual")
        eps_estimate = data.get("eps_estimate")
        if eps_actual is not None and eps_estimate and eps_estimate != 0:
            surprise_pct = ((eps_actual - eps_estimate) / abs(eps_estimate)) * 100
        else:
            surprise_pct = 0.0

        if guidance in ("raised", "positive") or surprise_pct > 3:
            direction = Direction.BULL
        elif guidance in ("lowered", "negative", "withdrawn") or surprise_pct < -3:
            direction = Direction.BEAR
        else:
            direction = Direction.NEUTRAL

        strength = min(abs(surprise_pct) / 10.0, 1.0) if surprise_pct else 0.5

        ambiguous = guidance in ("maintained", "mixed", "neutral", "not_discussed") or tone == "cautious"
        confidence = 0.6 if ambiguous else 0.85

        summary = data.get("transcript_summary") or f"guidance={guidance}, tone={tone}"
        evidence = summary[:120]

        as_of = data.get("call_date") or date.today().isoformat()

        return TickerSignal(
            ticker=ticker,
            sensor="earnings",
            direction=direction,
            strength=round(strength, 3),
            confidence=confidence,
            evidence=evidence,
            as_of=as_of,
        )
