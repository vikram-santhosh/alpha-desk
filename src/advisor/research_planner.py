"""Dynamic deep-research planning for AlphaDesk."""
from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
from typing import Any

from src.shared import gemini_compat as anthropic
from src.shared.agent_decorator import extract_json_payload, track_agent
from src.shared.cost_tracker import check_budget, record_usage
from src.utils.logger import get_logger

log = get_logger(__name__)

FLASH_MODEL = "claude-haiku-4-5"

VALID_DATA_NEEDS = frozenset({
    "full_article_text", "earnings_context", "sec_filing",
    "competitor_comparison", "cross_validation", "superinvestor_check",
})


@dataclass(frozen=True)
class ResearchTask:
    ticker: str
    research_question: str
    task_type: str
    priority: int
    data_needs: list[str]


@dataclass(frozen=True)
class ResearchPlan:
    tasks: list[ResearchTask]

    def to_dict(self) -> dict[str, Any]:
        return {"tasks": [asdict(task) for task in self.tasks]}


class ResearchPlanner:
    """Ranks research tasks by information density and uncertainty."""

    def plan(
        self,
        *,
        tickers: list[str],
        holdings_reports: list[dict[str, Any]],
        news_articles: list[dict[str, Any]],
        signals: list[dict[str, Any]],
        earnings_data: dict[str, Any] | None = None,
        max_tasks: int = 6,
        calibration: dict[str, Any] | None = None,
    ) -> ResearchPlan:
        article_map: dict[str, list[dict[str, Any]]] = {}
        for article in news_articles:
            related = article.get("related_tickers", []) or []
            for ticker in related:
                article_map.setdefault(ticker, []).append(article)

        signal_map: dict[str, list[dict[str, Any]]] = {}
        for signal in signals:
            payload = signal.get("payload", {})
            related = payload.get("affected_tickers") or []
            ticker = payload.get("ticker") or signal.get("ticker") or ""
            if ticker:
                related = [ticker, *related]
            for item in dict.fromkeys([t for t in related if t]):
                signal_map.setdefault(item, []).append(signal)

        holding_map = {report.get("ticker", ""): report for report in holdings_reports}
        earnings_map = (earnings_data or {}).get("per_ticker", {}) if isinstance(earnings_data, dict) else {}

        tasks: list[ResearchTask] = []
        for ticker in tickers:
            if not ticker:
                continue
            report = holding_map.get(ticker, {})
            articles = article_map.get(ticker, [])
            related_signals = signal_map.get(ticker, [])
            move = abs(report.get("change_pct") or 0)
            earnings = earnings_map.get(ticker, {}) if isinstance(earnings_map, dict) else {}

            info_density = min(len(articles) * 2 + len(related_signals), 5)
            uncertainty = 2 if not articles else 0
            if report.get("thesis_status") in {"weakening", "invalidated"}:
                uncertainty += 2
            if move >= 4:
                uncertainty += 2
            elif move >= 2:
                uncertainty += 1
            if earnings:
                uncertainty += 1

            priority = max(1, min(5, info_density + uncertainty))
            if priority < 2:
                continue

            question = self._build_research_question(ticker, report, articles, earnings)
            task_type = self._infer_task_type(move, articles, earnings)
            data_needs = self._infer_data_needs(articles, earnings, move)
            tasks.append(
                ResearchTask(
                    ticker=ticker,
                    research_question=question,
                    task_type=task_type,
                    priority=priority,
                    data_needs=data_needs,
                )
            )

        if calibration:
            tasks = self._apply_calibration(tasks, calibration, signal_map)

        ordered = sorted(tasks, key=lambda task: (-task.priority, task.ticker))[:max_tasks]
        log.info("Research planner selected %d tasks", len(ordered))
        return ResearchPlan(tasks=ordered)

    @track_agent("research_planner")
    async def plan_with_llm(
        self,
        *,
        tickers: list[str],
        holdings_reports: list[dict[str, Any]],
        news_articles: list[dict[str, Any]],
        signals: list[dict[str, Any]],
        earnings_data: dict[str, Any] | None = None,
        max_tasks: int = 6,
        calibration: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run rule-based plan, then refine with a single Flash LLM call."""
        rule_plan = self.plan(
            tickers=tickers,
            holdings_reports=holdings_reports,
            news_articles=news_articles,
            signals=signals,
            earnings_data=earnings_data,
            max_tasks=max_tasks,
            calibration=calibration,
        )
        if not rule_plan.tasks:
            return {"text": "", "data": rule_plan}

        within_budget, spent, cap = check_budget()
        if not within_budget:
            log.warning("research_planner LLM skipped: budget exceeded (%.2f / %.2f)", spent, cap)
            return {"text": "", "data": rule_plan}

        candidates = []
        for task in rule_plan.tasks:
            candidates.append(
                f"- {task.ticker} (priority={task.priority}, type={task.task_type}): {task.research_question}"
            )

        signal_lines = []
        for sig in signals[:15]:
            payload = sig.get("payload", {})
            title = payload.get("title") or payload.get("summary") or sig.get("signal_type", "")
            ticker = payload.get("ticker") or sig.get("ticker", "")
            signal_lines.append(f"- [{sig.get('signal_type', '')}] {ticker}: {title}")

        prompt = (
            "Given these candidate tickers and today's signals, generate research questions and data needs.\n"
            "For each ticker, respond with JSON: a list of objects with fields:\n"
            "  ticker, research_question (specific and actionable), task_type, "
            "data_needs (list from: full_article_text, earnings_context, sec_filing, "
            "competitor_comparison, cross_validation, superinvestor_check).\n\n"
            f"Candidates:\n" + "\n".join(candidates) + "\n\n"
            f"Today's signals:\n" + ("\n".join(signal_lines) if signal_lines else "(none)") + "\n\n"
            "Return ONLY a JSON list. No explanation."
        )

        try:
            client = anthropic.Anthropic()
            response = await asyncio.to_thread(
                client.messages.create,
                model=FLASH_MODEL,
                max_tokens=1200,
                messages=[{"role": "user", "content": prompt}],
            )
            raw_text = response.content[0].text.strip()
            parsed = extract_json_payload(raw_text, default=[])

            if isinstance(parsed, list) and parsed:
                llm_map = {item.get("ticker"): item for item in parsed if isinstance(item, dict)}
                refined_tasks = []
                for task in rule_plan.tasks:
                    override = llm_map.get(task.ticker)
                    if override:
                        question = override.get("research_question", task.research_question)
                        task_type = override.get("task_type", task.task_type)
                        raw_needs = override.get("data_needs", task.data_needs)
                        data_needs = [n for n in raw_needs if n in VALID_DATA_NEEDS] or task.data_needs
                        refined_tasks.append(ResearchTask(
                            ticker=task.ticker,
                            research_question=question,
                            task_type=task_type,
                            priority=task.priority,
                            data_needs=data_needs,
                        ))
                    else:
                        refined_tasks.append(task)
                refined_plan = ResearchPlan(tasks=refined_tasks)
                log.info("LLM refined %d/%d research tasks", len(llm_map), len(rule_plan.tasks))
                return {
                    "text": raw_text,
                    "usage": response.usage,
                    "model": FLASH_MODEL,
                    "data": refined_plan,
                }

            log.warning("LLM returned unparseable output, falling back to rule-based plan")
            return {"text": raw_text, "usage": response.usage, "model": FLASH_MODEL, "data": rule_plan}

        except Exception:
            log.exception("LLM planner call failed, falling back to rule-based plan")
            return {"text": "", "data": rule_plan}

    def _apply_calibration(
        self,
        tasks: list[ResearchTask],
        calibration: dict[str, Any],
        signal_map: dict[str, list[dict[str, Any]]],
    ) -> list[ResearchTask]:
        """Adjust task priorities based on historical recommendation outcome calibration."""
        adjusted = []
        for task in tasks:
            trigger_types = set()
            for sig in signal_map.get(task.ticker, []):
                sig_type = sig.get("signal_type", "")
                if sig_type:
                    trigger_types.add(sig_type)

            modifier = 1.0
            for trigger_type in trigger_types:
                cal = calibration.get(trigger_type)
                if cal and isinstance(cal, dict):
                    hit_rate = cal.get("hit_rate", 0.5)
                    # Scale modifier: hit_rate=0 -> 0.7, hit_rate=0.5 -> 1.0, hit_rate=1.0 -> 1.3
                    modifier *= 0.7 + (hit_rate * 0.6)

            modifier = max(0.7, min(1.3, modifier))
            new_priority = max(1, min(5, round(task.priority * modifier)))
            if new_priority != task.priority:
                adjusted.append(ResearchTask(
                    ticker=task.ticker,
                    research_question=task.research_question,
                    task_type=task.task_type,
                    priority=new_priority,
                    data_needs=task.data_needs,
                ))
            else:
                adjusted.append(task)
        return adjusted

    def _build_research_question(
        self,
        ticker: str,
        report: dict[str, Any],
        articles: list[dict[str, Any]],
        earnings: dict[str, Any],
    ) -> str:
        if articles:
            headline = articles[0].get("title") or articles[0].get("headline") or "latest news"
            return f"Why is {ticker} in focus and what does '{headline}' mean for the thesis?"
        if earnings:
            return f"Does the latest earnings context for {ticker} change the investment thesis?"
        status = report.get("thesis_status")
        if status in {"weakening", "invalidated"}:
            return f"What is breaking in the thesis for {ticker}, and is the market fully pricing it?"
        return f"What changed for {ticker} today, and does it alter the portfolio stance?"

    def _infer_task_type(
        self,
        move: float,
        articles: list[dict[str, Any]],
        earnings: dict[str, Any],
    ) -> str:
        if earnings:
            return "event_analysis"
        if articles:
            return "news_deep_dive"
        if move >= 2:
            return "thesis_validation"
        return "event_analysis"

    def _infer_data_needs(
        self,
        articles: list[dict[str, Any]],
        earnings: dict[str, Any],
        move: float,
    ) -> list[str]:
        needs: list[str] = []
        if articles:
            needs.append("full_article_text")
            needs.append("cross_validation")
        if earnings:
            needs.append("earnings_context")
        if move >= 2:
            needs.append("competitor_comparison")
        if not needs:
            needs.append("sec_filing")
        return needs
