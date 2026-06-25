"""Earnings sensor — adapter over src/advisor/memory earnings history.

Reads the most recently stored earnings call data from memory (populated by
run_earnings_analysis during the morning pipeline) so the score sensor
never re-runs LLM transcript analysis.
"""
from __future__ import annotations

import asyncio
import math
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
        raw_guidance = data.get("guidance_sentiment")
        raw_tone     = data.get("management_tone")
        guidance = (raw_guidance or "").lower()
        tone     = (raw_tone or "").lower()
        has_guidance = guidance in ("raised", "lowered", "maintained", "positive", "negative", "withdrawn")

        # EPS surprise from actual vs estimate (the hard quantitative driver).
        eps_actual   = data.get("eps_actual")
        eps_estimate = data.get("eps_estimate")
        has_surprise = eps_actual is not None and eps_estimate not in (None, 0)
        surprise_pct = (
            ((eps_actual - eps_estimate) / abs(eps_estimate)) * 100 if has_surprise else 0.0
        )

        # Direction: guidance language and EPS surprise both vote; combine.
        bull = guidance in ("raised", "positive") or surprise_pct > 3
        bear = guidance in ("lowered", "negative", "withdrawn") or surprise_pct < -3
        if bull and not bear:
            direction = Direction.BULL
        elif bear and not bull:
            direction = Direction.BEAR
        else:
            direction = Direction.NEUTRAL

        # Strength: smooth (tanh) on |surprise| so a 40% beat outranks a 17% beat
        # instead of both saturating at 1.0. Falls back to guidance-only magnitude.
        if has_surprise and abs(surprise_pct) >= 1.0:
            strength = math.tanh(abs(surprise_pct) / 20.0)
        elif has_guidance:
            strength = 0.5
        else:
            strength = 0.3

        # Confidence: a real EPS number is solid data; guidance prose that
        # agrees adds confidence; soft-only signals are weaker.
        if has_surprise and has_guidance:
            confidence = 0.85
        elif has_surprise:
            confidence = 0.75            # hard number, no narrative
        elif has_guidance:
            confidence = 0.6
        else:
            confidence = 0.45

        # Evidence: name the ACTUAL driver, not just guidance prose.
        summary = data.get("transcript_summary")
        if summary:
            evidence = str(summary)[:120]
        else:
            parts = []
            if has_surprise:
                verb = "beat" if surprise_pct >= 0 else "miss"
                parts.append(f"EPS {verb} {surprise_pct:+.1f}% ({eps_actual} vs {eps_estimate:.2f} est)")
            if has_guidance:
                parts.append(f"guidance={guidance}")
            if tone:
                parts.append(f"tone={tone}")
            evidence = ", ".join(parts) if parts else "no earnings signal"

        as_of = data.get("call_date") or date.today().isoformat()

        return TickerSignal(
            ticker=ticker,
            sensor="earnings",
            direction=direction,
            strength=round(strength, 3),
            confidence=confidence,
            evidence=evidence[:120],
            as_of=as_of,
        )
