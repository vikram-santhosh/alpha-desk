"""YouTube sensor — adapter over youtube_ear signals on the agent bus."""
from __future__ import annotations

import asyncio

from src.score_engine.sensors._bus import build_bus_signals
from src.score_engine.signals import TickerSignal

YT_SIGNAL_TYPES = ("expert_analysis", "narrative_amplification")


class YouTubeSensor:
    name = "youtube"
    weight_key = "youtube"

    async def vote(self, tickers: list[str], ctx: dict) -> list[TickerSignal]:
        return await asyncio.to_thread(build_bus_signals, "youtube", YT_SIGNAL_TYPES, tickers)
