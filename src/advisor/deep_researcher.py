"""Iterative deep research pipeline for AlphaDesk."""
from __future__ import annotations

import asyncio
import json
import re
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Any

import uuid

import requests

from src.shared import gemini_compat as anthropic
from src.shared.agent_decorator import extract_json_payload, select_model, track_agent
from src.shared.citations import CitationRegistry
from src.shared.context_manager import ContextBudget
from src.shared.prompt_loader import load_prompt, load_skill
from src.utils.logger import get_logger

from src.advisor.gap_resolver import GapResolver, format_supplementary_research
from src.advisor.memory import get_ticker_deep_context
from src.advisor.research_planner import ResearchPlan, ResearchTask
from src.shared.agent_bus import consume_since

log = get_logger(__name__)

FLASH_MODEL = "claude-haiku-4-5"
PRO_MODEL = "claude-opus-4-6"
HTTP_TIMEOUT = 10

# Map task_type values to skill prompt names
TASK_TYPE_TO_SKILL: dict[str, str] = {
    "thesis_refresh": "thesis_refresh",
    "thesis_review": "thesis_refresh",
    "earnings_analysis": "earnings_deep_dive",
    "earnings_deep_dive": "earnings_deep_dive",
    "variant_perception": "variant_perception",
    "consensus_divergence": "variant_perception",
    "catalyst_analysis": "catalyst_stress_test",
    "catalyst_stress_test": "catalyst_stress_test",
}


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
            return {"blocks": {}, "citations": [], "citations_html": "", "artifacts_path": ""}

        # Create workspace for artifacts
        run_id = uuid.uuid4().hex[:12]
        workspace = Path("reports") / date.today().isoformat() / "research" / run_id
        workspace.mkdir(parents=True, exist_ok=True)

        registry = CitationRegistry()
        tasks = []
        for idx, task in enumerate(plan.tasks):
            tier = "full" if idx < self.max_full else "summary"
            tasks.append(self._research_one(task, tier, data_context, registry, last_signal_id, source_agent, workspace))

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
            "artifacts_path": str(workspace),
        }

    def _load_artifact(self, workspace: Path, ticker: str) -> dict[str, Any] | None:
        """Load partial artifact for a ticker if it exists."""
        artifact_path = workspace / f"{ticker}.json"
        if artifact_path.exists():
            try:
                return json.loads(artifact_path.read_text())
            except (json.JSONDecodeError, OSError):
                log.debug("Failed to load artifact for %s", ticker)
        return None

    def _save_artifact(self, workspace: Path, ticker: str, state: dict[str, Any]) -> None:
        """Write current research state to artifact file."""
        artifact_path = workspace / f"{ticker}.json"
        try:
            artifact_path.write_text(json.dumps(state, default=str))
        except OSError:
            log.debug("Failed to save artifact for %s", ticker, exc_info=True)

    async def _research_one(
        self,
        task: ResearchTask,
        tier: str,
        data_context: dict[str, Any],
        registry: CitationRegistry,
        last_signal_id: int,
        source_agent: str,
        workspace: Path | None = None,
    ) -> dict[str, Any]:
        # Check for partial artifact to resume from
        partial = self._load_artifact(workspace, task.ticker) if workspace else None
        completed_steps = set(partial.get("completed_steps", [])) if partial else set()
        observations: list[str] = partial.get("observations", []) if partial else []
        analysis_data: dict[str, Any] = partial.get("analysis_data", {}) if partial else {}

        # Step 1: Gather
        if "gather" not in completed_steps:
            gather_result = await self._gather(task, data_context, registry)
            observations.extend(gather_result["observations"])
            completed_steps.add("gather")
            if workspace:
                self._save_artifact(workspace, task.ticker, {
                    "completed_steps": list(completed_steps),
                    "observations": observations,
                    "analysis_data": analysis_data,
                    "tier": tier,
                })

        # Step 2: Analyze
        if "analyze" not in completed_steps:
            analysis_result = await self._analyze(task, observations)
            analysis_data = analysis_result.get("data", {}) if isinstance(analysis_result, dict) else {}
            synthesized_analysis = analysis_data.get("analysis", "")
            if synthesized_analysis:
                observations.append("Step 2 analysis:\n" + synthesized_analysis)
            completed_steps.add("analyze")
            if workspace:
                self._save_artifact(workspace, task.ticker, {
                    "completed_steps": list(completed_steps),
                    "observations": observations,
                    "analysis_data": analysis_data,
                    "tier": tier,
                })

        # Step 3: Fill gaps
        if "fill_gaps" not in completed_steps:
            gaps = analysis_data.get("data_gaps", []) if isinstance(analysis_data, dict) else []
            fill_result = await self._fill_gaps(task, gaps, data_context, observations, last_signal_id)
            if fill_result:
                observations.append(fill_result)
            completed_steps.add("fill_gaps")
            if workspace:
                self._save_artifact(workspace, task.ticker, {
                    "completed_steps": list(completed_steps),
                    "observations": observations,
                    "analysis_data": analysis_data,
                    "tier": tier,
                })

        # Step 4: Synthesize
        block_result = await self._synthesize(task, tier, observations, registry)
        text = block_result.get("raw_text") or block_result.get("data") or ""
        completed_steps.add("synthesize")
        if workspace:
            self._save_artifact(workspace, task.ticker, {
                "completed_steps": list(completed_steps),
                "observations": observations,
                "analysis_data": analysis_data,
                "tier": tier,
                "result": text if isinstance(text, str) else str(text),
            })

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
        data_needs = set(task.data_needs) if task.data_needs else {"full_article_text"}
        gather_coros = []
        gather_labels: list[str] = []

        if "full_article_text" in data_needs or "cross_validation" in data_needs:
            gather_coros.append(self._gather_articles(task.ticker, data_context, registry))
            gather_labels.append("articles")

        if "earnings_context" in data_needs:
            gather_coros.append(self._gather_earnings(task.ticker, data_context))
            gather_labels.append("earnings")

        if "competitor_comparison" in data_needs:
            gather_coros.append(self._gather_competitor(task.ticker, data_context))
            gather_labels.append("competitor")

        if "superinvestor_check" in data_needs:
            gather_coros.append(self._gather_superinvestor(task.ticker, data_context))
            gather_labels.append("superinvestor")

        results = await asyncio.gather(*gather_coros, return_exceptions=True)

        observations: list[str] = []
        articles: list[dict[str, Any]] = []
        for label, result in zip(gather_labels, results):
            if isinstance(result, Exception):
                log.warning("Gather %s failed for %s: %s", label, task.ticker, result)
                continue
            if label == "articles":
                observations.extend(result.get("observations", []))
                articles = result.get("articles", [])
            else:
                observations.extend(result.get("observations", []))

        if "sec_filing" in data_needs:
            observations.append(
                f"[Data gap] SEC filing data for {task.ticker} not yet available — noted for manual review."
            )

        # Always include holding context
        holdings_map = {item.get("ticker"): item for item in data_context.get("holdings_reports", [])}
        holding = holdings_map.get(task.ticker, {})
        if holding:
            observations.append(
                f"Holding context: {task.ticker} price={holding.get('price')} change={holding.get('change_pct')} thesis_status={holding.get('thesis_status')}"
            )

        # Per-ticker deep memory context
        try:
            deep_ctx = get_ticker_deep_context(task.ticker)
            for section, data in deep_ctx.items():
                observations.append(f"Memory ({section}): {json.dumps(data)}")
        except Exception:
            log.debug("Failed to load deep context for %s", task.ticker, exc_info=True)

        return {"observations": observations, "articles": articles}

    async def _gather_articles(
        self,
        ticker: str,
        data_context: dict[str, Any],
        registry: CitationRegistry,
    ) -> dict[str, Any]:
        articles = self._select_articles(ticker, data_context)
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
        return {"observations": observations, "articles": articles}

    async def _gather_earnings(
        self,
        ticker: str,
        data_context: dict[str, Any],
    ) -> dict[str, Any]:
        earnings = data_context.get("earnings_data", {})
        per_ticker = earnings.get("per_ticker", {}) if isinstance(earnings, dict) else {}
        ticker_earnings = per_ticker.get(ticker, {})
        observations: list[str] = []
        if ticker_earnings:
            summary = ticker_earnings.get("summary", "")
            surprise = ticker_earnings.get("surprise_pct", "")
            obs = f"Earnings context for {ticker}: {summary}"
            if surprise:
                obs += f" (surprise: {surprise}%)"
            observations.append(obs)
        return {"observations": observations}

    async def _gather_competitor(
        self,
        ticker: str,
        data_context: dict[str, Any],
    ) -> dict[str, Any]:
        observations: list[str] = []
        try:
            resolver = GapResolver()
            gaps = [{"gap_type": "missing_competitor_data", "ticker": ticker,
                      "description": f"Competitor comparison for {ticker}", "priority": "medium"}]
            resolutions = await resolver.resolve_gaps(gaps, data_context)
            if resolutions:
                sections = format_supplementary_research(resolutions)
                if sections:
                    observations.append(f"Competitor data for {ticker}:\n{sections}")
        except Exception:
            log.debug("Competitor gather failed for %s", ticker, exc_info=True)
        return {"observations": observations}

    async def _gather_superinvestor(
        self,
        ticker: str,
        data_context: dict[str, Any],
    ) -> dict[str, Any]:
        superinvestor = data_context.get("superinvestor_data", {})
        per_ticker = superinvestor.get("per_ticker", superinvestor) if isinstance(superinvestor, dict) else {}
        ticker_data = per_ticker.get(ticker, {})
        observations: list[str] = []
        if ticker_data:
            investors = ticker_data.get("investors", [])
            if investors:
                names = ", ".join(i.get("name", "unknown") for i in investors[:5])
                observations.append(f"Superinvestor activity for {ticker}: tracked by {names}")
            else:
                observations.append(f"Superinvestor data for {ticker}: {ticker_data}")
        return {"observations": observations}

    @track_agent("deep_research_analysis")
    async def _analyze(self, task: ResearchTask, observations: list[str]) -> dict[str, Any]:
        analysis_model = select_model(PRO_MODEL)
        prompt = (
            "Review the observations below and respond with JSON containing "
            "analysis (string), contradictions (list), and data_gaps (list of objects with gap_type, ticker, description, priority).\n\n"
            f"Ticker: {task.ticker}\nQuestion: {task.research_question}\n\nObservations:\n" + "\n".join(observations)
        )
        response = await asyncio.to_thread(
            self.client.messages.create,
            model=analysis_model,
            max_tokens=1800,
            messages=[{"role": "user", "content": prompt}],
        )
        return {"text": response.content[0].text.strip(), "usage": response.usage, "model": analysis_model}

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

        # Append skill-specific instructions if available
        skill_name = TASK_TYPE_TO_SKILL.get(task.task_type, "")
        if skill_name:
            skill_prompt = load_skill(skill_name, ticker=task.ticker)
            if skill_prompt:
                prompt += "\n\n" + skill_prompt

        response = await asyncio.to_thread(
            self.client.messages.create,
            model=PRO_MODEL,
            max_tokens=1200 if tier == "full" else 500,
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
