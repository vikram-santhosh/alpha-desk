"""News sensor — adapter over news_desk signals on the agent bus."""
from __future__ import annotations

import asyncio

from src.score_engine.sensors._bus import build_bus_signals
from src.score_engine.signals import TickerSignal

NEWS_SIGNAL_TYPES = ("breaking_news", "sector_news", "macro_event")


class NewsSensor:
    name = "news"
    weight_key = "news"

    async def vote(self, tickers: list[str], ctx: dict) -> list[TickerSignal]:
        return await asyncio.to_thread(build_bus_signals, "news", NEWS_SIGNAL_TYPES, tickers)
