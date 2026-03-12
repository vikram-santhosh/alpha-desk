"""Iterative deep research pipeline for AlphaDesk."""
from __future__ import annotations

import asyncio
import re
from dataclasses import asdict
from typing import Any

import requests

from src.shared import gemini_compat as anthropic
from src.shared.agent_decorator import extract_json_payload, track_agent
from src.shared.citations import CitationRegistry
from src.shared.context_manager import ContextBudget
from src.shared.prompt_loader import load_prompt
from src.utils.logger import get_logger

from src.advisor.gap_resolver import GapResolver, format_supplementary_research
from src.advisor.research_planner import ResearchPlan, ResearchTask
from src.shared.agent_bus import consume_since

log = get_logger(__name__)

FLASH_MODEL = "claude-haiku-4-5"
PRO_MODEL = "claude-opus-4-6"
HTTP_TIMEOUT = 10


class MultiStepDeepResearcher:
    """Runs sequential research steps per ticker and parallelises across tickers."""

    def __init__(self, *, max_full: int = 3):
        self.max_full = max_full
        self.client = anthropic.Anthropic()

    async def run(
        self,
        plan: ResearchPlan,
        data_context: dict[str, Any],
        *,
        last_signal_id: int = 0,
        source_agent: str = "deep_researcher",
    ) -> dict[str, Any]:
        if not plan.tasks:
            return {"blocks": {}, "citations": [], "citations_html": ""}

        registry = CitationRegistry()
        tasks = []
        for idx, task in enumerate(plan.tasks):
            tier = "full" if idx < self.max_full else "summary"
            tasks.append(self._research_one(task, tier, data_context, registry, last_signal_id, source_agent))

        raw_results = await asyncio.gather(*tasks, return_exceptions=True)
        blocks: dict[str, dict[str, Any]] = {}
        for task, result in zip(plan.tasks, raw_results):
            if isinstance(result, Exception):
                log.warning("Deep research failed for %s: %s", task.ticker, result)
                continue
            blocks[task.ticker] = result

        return {
            "blocks": blocks,
            "citations": registry.as_list(),
            "citations_html": registry.format_for_html(),
        }

    async def _research_one(
        self,
        task: ResearchTask,
        tier: str,
        data_context: dict[str, Any],
        registry: CitationRegistry,
        last_signal_id: int,
        source_agent: str,
    ) -> dict[str, Any]:
        observations: list[str] = []

        gather_result = await self._gather(task, data_context, registry)
        observations.extend(gather_result["observations"])

        analysis_result = await self._analyze(task, observations)
        analysis_data = analysis_result.get("data", {}) if isinstance(analysis_result, dict) else {}
        synthesized_analysis = analysis_data.get("analysis", "")
        if synthesized_analysis:
            observations.append("Step 2 analysis:\n" + synthesized_analysis)

        gaps = analysis_data.get("data_gaps", []) if isinstance(analysis_data, dict) else []
        fill_result = await self._fill_gaps(task, gaps, data_context, observations, last_signal_id)
        if fill_result:
            observations.append(fill_result)

        block_result = await self._synthesize(task, tier, observations, registry)
        text = block_result.get("raw_text") or block_result.get("data") or ""
        return {
            "content": text if isinstance(text, str) else str(text),
            "tier": tier,
            "research_task": asdict(task),
            "analysis": analysis_data,
        }

    async def _gather(
        self,
        task: ResearchTask,
        data_context: dict[str, Any],
        registry: CitationRegistry,
    ) -> dict[str, Any]:
        articles = self._select_articles(task.ticker, data_context)
        article_bodies = await asyncio.gather(
            *[asyncio.to_thread(self._fetch_article_body, article.get("url", "")) for article in articles[:3]],
            return_exceptions=True,
        )

        observations: list[str] = []
        for article, body in zip(articles[:3], article_bodies):
            citation_id = registry.register(
                article.get("url", ""),
                article.get("title", "Untitled"),
                article.get("origin", article.get("source", "news")),
                article.get("published_at", ""),
            )
            snippet = article.get("summary", "")
            if isinstance(body, str) and body:
                snippet = body[:1200]
            snippet = re.sub(r"\s+", " ", snippet).strip()
            observations.append(f"[{citation_id}] {article.get('title', 'Untitled')} — {snippet}")

        holdings_map = {item.get("ticker"): item for item in data_context.get("holdings_reports", [])}
        holding = holdings_map.get(task.ticker, {})
        if holding:
            observations.append(
                f"Holding context: {task.ticker} price={holding.get('price')} change={holding.get('change_pct')} thesis_status={holding.get('thesis_status')}"
            )

        return {"observations": observations, "articles": articles}

    @track_agent("deep_research_analysis")
    async def _analyze(self, task: ResearchTask, observations: list[str]) -> dict[str, Any]:
        prompt = (
            "Review the observations below and respond with JSON containing "
            "analysis (string), contradictions (list), and data_gaps (list of objects with gap_type, ticker, description, priority).\n\n"
            f"Ticker: {task.ticker}\nQuestion: {task.research_question}\n\nObservations:\n" + "\n".join(observations)
        )
        response = await asyncio.to_thread(
            self.client.messages.create,
            model=PRO_MODEL,
            max_tokens=1800,
            messages=[{"role": "user", "content": prompt}],
        )
        return {"text": response.content[0].text.strip(), "usage": response.usage, "model": PRO_MODEL}

    async def _fill_gaps(
        self,
        task: ResearchTask,
        gaps: list[dict[str, Any]],
        data_context: dict[str, Any],
        observations: list[str],
        last_signal_id: int,
    ) -> str:
        sections: list[str] = []

        if gaps:
            resolver = GapResolver()
            resolutions = await resolver.resolve_gaps(gaps[:3], data_context)
            if resolutions:
                sections.append(format_supplementary_research(resolutions))

        if last_signal_id:
            fresh = consume_since(last_signal_id, mark_consumed=False)
            if fresh:
                lines = []
                for signal in fresh[:5]:
                    payload = signal.get("payload", {})
                    title = payload.get("title") or payload.get("summary") or signal.get("signal_type", "signal")
                    lines.append(f"- {signal.get('signal_type')}: {title}")
                sections.append("New signals during run:\n" + "\n".join(lines))

        return "\n\n".join(section for section in sections if section)

    @track_agent("deep_research_synthesis")
    async def _synthesize(
        self,
        task: ResearchTask,
        tier: str,
        observations: list[str],
        registry: CitationRegistry,
    ) -> dict[str, Any]:
        budget = ContextBudget(token_budget=8000 if tier == "full" else 2500)
        budget.add_section("Research Task", f"Ticker: {task.ticker}\nQuestion: {task.research_question}\nType: {task.task_type}\nPriority: {task.priority}", 100)
        budget.add_section("Observations", "\n".join(observations), 80)
        budget.add_section("Sources", registry.format_for_prompt(), 60)

        prompt = load_prompt(
            "deep_researcher",
            ticker=task.ticker,
            research_question=task.research_question,
            task_type=task.task_type,
            priority=task.priority,
            context=budget.render(),
            observations="\n".join(observations),
            citations=registry.format_for_prompt(),
        )
        response = await asyncio.to_thread(
            self.client.messages.create,
            model=PRO_MODEL,
            max_tokens=2400 if tier == "full" else 700,
            messages=[{"role": "user", "content": prompt}],
        )
        return {"raw_text": response.content[0].text.strip(), "usage": response.usage, "model": PRO_MODEL}

    def _select_articles(self, ticker: str, data_context: dict[str, Any]) -> list[dict[str, Any]]:
        matches = []
        for article in data_context.get("news_articles", []):
            related = article.get("related_tickers", []) or []
            if ticker in related or ticker in (article.get("title", "") + article.get("summary", "")):
                matches.append(article)
        if matches:
            return matches
        return [
            article for article in data_context.get("news_articles", [])[:5]
        ]

    def _fetch_article_body(self, url: str) -> str:
        if not url:
            return ""
        try:
            response = requests.get(url, timeout=HTTP_TIMEOUT, headers={"User-Agent": "Mozilla/5.0 AlphaDesk"})
            response.raise_for_status()
        except Exception:
            log.debug("Article body fetch failed for %s", url, exc_info=True)
            return ""

        text = re.sub(r"<script.*?</script>", " ", response.text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<style.*?</style>", " ", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()
