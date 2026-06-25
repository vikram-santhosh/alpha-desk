"""Reddit sensor — adapter over src/street_ear.

Fetches posts and analyzes them; maps per-ticker avg_sentiment to a TickerSignal.
"""
from __future__ import annotations

import asyncio
from datetime import date

from src.score_engine.signals import Direction, TickerSignal

MIN_MENTIONS = 2   # ignore tickers with fewer mentions (noise floor)


class RedditSensor:
    name = "reddit"
    weight_key = "reddit"

    async def vote(self, tickers: list[str], ctx: dict) -> list[TickerSignal]:
        posts = await asyncio.to_thread(self._fetch_posts)
        if not posts:
            return []
        analysis = await asyncio.to_thread(self._analyze, posts)
        ticker_data: dict = analysis.get("tickers", {})

        signals = []
        for ticker in tickers:
            # ticker_data keys are symbols; look up directly or case-insensitively
            data = ticker_data.get(ticker) or ticker_data.get(ticker.upper())
            if not data:
                continue
            sig = self._to_signal(ticker, data)
            if sig:
                signals.append(sig)
        return signals

    def _fetch_posts(self) -> list[dict]:
        from src.street_ear.reddit_fetcher import fetch_posts
        return fetch_posts()

    def _analyze(self, posts: list[dict]) -> dict:
        from src.street_ear.analyzer import analyze_posts
        return analyze_posts(posts)

    def _to_signal(self, ticker: str, data: dict) -> TickerSignal | None:
        mention_count = data.get("total_mentions") or data.get("mentions") or 0
        if mention_count < MIN_MENTIONS:
            return None

        sentiment  = data.get("avg_sentiment") or data.get("sentiment") or 0.0
        confidence = min(data.get("avg_confidence") or data.get("confidence") or 0.5, 1.0)

        if sentiment > 0.2:
            direction = Direction.BULL
        elif sentiment < -0.2:
            direction = Direction.BEAR
        else:
            direction = Direction.NEUTRAL

        strength = min(abs(sentiment) / 2.0, 1.0)   # sentiment range is -2..+2
        evidence = f"{mention_count} mentions, avg_sentiment={sentiment:+.2f}"

        return TickerSignal(
            ticker=ticker,
            sensor="reddit",
            direction=direction,
            strength=round(strength, 3),
            confidence=confidence,
            evidence=evidence,
            as_of=date.today().isoformat(),
        )
