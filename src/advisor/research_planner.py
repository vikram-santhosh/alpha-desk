"""Dynamic deep-research planning for AlphaDesk."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from src.utils.logger import get_logger

log = get_logger(__name__)


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

        ordered = sorted(tasks, key=lambda task: (-task.priority, task.ticker))[:max_tasks]
        log.info("Research planner selected %d tasks", len(ordered))
        return ResearchPlan(tasks=ordered)

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
