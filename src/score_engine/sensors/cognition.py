"""Cognition sensor: web search + LLM extraction → cited TickerSignal.

For each ticker, searches the web for current investment evidence, then asks
GLM 5.2 (via OpenRouter) to extract a directional signal with confidence and
a one-line summary citing the source URL. The signal flows into the same
deterministic aggregator as all other sensors — the breadth gate prevents
a lone LLM opinion from pushing any score past 6.9.

Requires OPENROUTER_API_KEY and at least one search provider configured via
WEB_SEARCH_API_KEY / WEB_SEARCH_PROVIDER (or Vertex/GCP for Gemini grounding).
"""
from __future__ import annotations

import asyncio
import json
import os
import re
from datetime import date
from typing import Optional

import requests

from src.score_engine.signals import Direction, TickerSignal
from src.utils.logger import get_logger

log = get_logger(__name__)

_EXTRACTION_PROMPT = """\
You are a signal extractor for a stock scoring engine.

Below are web search results about {ticker} stock. Analyze the evidence and return
a single JSON object — no markdown, no explanation, just the object.

SEARCH RESULTS:
{snippets}

Return exactly this JSON shape:
{{
  "direction": "bull" | "bear" | "neutral",
  "strength": 0.0-1.0,
  "confidence": 0.0-1.0,
  "evidence": "one-line summary ≤120 chars with source URL"
}}

Guidelines:
- direction "bull" = net positive outlook, "bear" = net negative, "neutral" = mixed/unclear
- strength = magnitude of the signal (0 = weak, 1 = very strong)
- confidence = data quality (0 = speculation, 1 = hard quantitative evidence)
- evidence MUST cite the most relevant URL from the search results
"""


class CognitionSensor:
    name = "cognition"
    weight_key = "cognition"

    async def vote(self, tickers: list[str], ctx: dict) -> list[TickerSignal]:
        signals = []
        for ticker in tickers:
            try:
                sig = await asyncio.to_thread(self._score_ticker, ticker)
                if sig is not None:
                    signals.append(sig)
            except Exception as exc:
                log.warning("CognitionSensor failed for %s: %s", ticker, exc)
        return signals

    def _score_ticker(self, ticker: str) -> Optional[TickerSignal]:
        api_key = os.getenv("OPENROUTER_API_KEY")
        if not api_key:
            return None

        from src.shared.web_search import search
        results = search(
            f"{ticker} stock investment thesis fundamental analysis earnings",
            max_results=5,
        )
        if not results:
            return None

        snippets = "\n\n".join(
            f"[{i + 1}] {r['title']}\n{r['snippet']}\nURL: {r['url']}"
            for i, r in enumerate(results[:5])
            if r.get("url")
        )
        if not snippets:
            return None

        prompt = _EXTRACTION_PROMPT.format(ticker=ticker, snippets=snippets)
        try:
            resp = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "HTTP-Referer": os.getenv("OPENROUTER_SITE_URL", "http://localhost:5173"),
                    "X-Title": "AlphaDesk Cognition",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "z-ai/glm-5.2",
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 250,
                    "temperature": 0.0,
                },
                timeout=25,
            )
            resp.raise_for_status()
        except Exception as exc:
            log.warning("CognitionSensor OpenRouter call failed for %s: %s", ticker, exc)
            return None

        try:
            content = resp.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, ValueError) as exc:
            log.warning("CognitionSensor bad response structure for %s: %s", ticker, exc)
            return None

        return self._parse_signal(ticker, content, results)

    def _parse_signal(
        self,
        ticker: str,
        content: str,
        search_results: list[dict],
    ) -> Optional[TickerSignal]:
        m = re.search(r'\{[^{}]+\}', content, re.DOTALL)
        if not m:
            log.debug("CognitionSensor: no JSON in LLM response for %s: %r", ticker, content[:200])
            return None
        try:
            data = json.loads(m.group())
        except json.JSONDecodeError as exc:
            log.debug("CognitionSensor: JSON parse error for %s: %s", ticker, exc)
            return None

        dir_str = str(data.get("direction", "neutral")).strip().lower()
        direction = (
            Direction.BULL if dir_str == "bull" else
            Direction.BEAR if dir_str == "bear" else
            Direction.NEUTRAL
        )

        def _clamp(v: object, default: float) -> float:
            try:
                return max(0.0, min(1.0, float(v)))  # type: ignore[arg-type]
            except (TypeError, ValueError):
                return default

        strength = _clamp(data.get("strength"), 0.5)
        confidence = _clamp(data.get("confidence"), 0.35)

        evidence = str(data.get("evidence") or "").strip()
        if not evidence and search_results:
            top = search_results[0]
            evidence = f"{top.get('title', ticker)[:80]} — {top.get('url', '')}"
        evidence = evidence[:200]

        return TickerSignal(
            ticker=ticker,
            sensor=self.name,
            direction=direction,
            strength=strength,
            confidence=confidence,
            evidence=evidence,
            as_of=str(date.today()),
        )
