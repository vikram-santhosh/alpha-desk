"""Analyst committee orchestration for AlphaDesk Advisor."""
from __future__ import annotations

import asyncio
import json
from typing import Any

from src.shared import gemini_compat as anthropic
from src.shared.agent_decorator import select_model, track_agent
from src.shared.citations import CitationRegistry
from src.shared.context_manager import ContextBudget
from src.shared.prompt_loader import load_prompt
from src.utils.logger import get_logger

from src.advisor.deep_researcher import MultiStepDeepResearcher
from src.advisor.research_planner import ResearchPlanner

log = get_logger(__name__)

ANALYST_MODEL = "claude-opus-4-6"
EDITOR_MODEL = "claude-opus-4-6"
DELTA_MODEL = "claude-haiku-4-5"


def _call_model(prompt: str, *, model: str, max_tokens: int) -> dict[str, Any]:
    client = anthropic.Anthropic()
    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    return {
        "text": response.content[0].text.strip(),
        "usage": response.usage,
        "model": model,
    }


def _make_json_agent(agent_name: str, model: str, max_tokens: int):
    @track_agent(agent_name)
    async def _runner(prompt: str) -> dict[str, Any]:
        return await asyncio.to_thread(_call_model, prompt, model=model, max_tokens=max_tokens)

    return _runner


def _make_text_agent(agent_name: str, model: str, max_tokens: int):
    @track_agent(agent_name)
    async def _runner(prompt: str) -> dict[str, Any]:
        return await asyncio.to_thread(_call_model, prompt, model=model, max_tokens=max_tokens)

    return _runner


class GrowthAnalyst:
    AGENT_NAME = "committee_growth"

    def build_prompt(self, tickers: list[str], data_context: dict[str, Any]) -> str:
        return load_prompt(
            "growth_analyst",
            holdings_context=self._build_holdings_context(tickers, data_context),
        )

    def _build_holdings_context(self, tickers: list[str], ctx: dict[str, Any]) -> str:
        lines = []
        fundamentals = ctx.get("fundamentals", {})
        holdings_reports = ctx.get("holdings_reports", [])
        report_map = {report.get("ticker"): report for report in holdings_reports}

        for ticker in tickers[:12]:
            fund = fundamentals.get(ticker, {})
            report = report_map.get(ticker, {})
            rev_growth = fund.get("revenue_growth")
            margin = fund.get("net_margin")
            pe = fund.get("pe_trailing")
            price = report.get("price", fund.get("current_price", "N/A"))
            change_pct = report.get("change_pct") or 0.0
            lines.append(
                f"- {ticker}: price={price} change={change_pct:+.1f}% "
                f"rev_growth={self._fmt_pct(rev_growth)} margin={self._fmt_pct(margin)} pe={pe if pe is not None else 'N/A'}"
            )
            for event in report.get("key_events", [])[:3]:
                headline = event.get("headline", event) if isinstance(event, dict) else str(event)
                lines.append(f"  news: {headline}")
        return "\n".join(lines) if lines else "No holdings data."

    def _fmt_pct(self, value: float | None) -> str:
        if value is None:
            return "N/A"
        return f"{value:.0%}"


class ValueAnalyst:
    AGENT_NAME = "committee_value"

    def build_prompt(self, tickers: list[str], data_context: dict[str, Any]) -> str:
        return load_prompt(
            "value_analyst",
            holdings_context=self._build_context(tickers, data_context),
        )

    def _build_context(self, tickers: list[str], ctx: dict[str, Any]) -> str:
        lines = []
        fundamentals = ctx.get("fundamentals", {})
        valuations = ctx.get("valuation_data", {})

        for ticker in tickers[:12]:
            fund = fundamentals.get(ticker, {})
            valuation = valuations.get(ticker, {})
            lines.append(
                f"- {ticker}: price={fund.get('current_price', 'N/A')} pe={fund.get('pe_trailing', 'N/A')} "
                f"forward_pe={fund.get('pe_forward', 'N/A')} target={valuation.get('target_price', 'N/A')} "
                f"implied_cagr={valuation.get('implied_cagr', 'N/A')} margin_of_safety={valuation.get('margin_of_safety', 'N/A')}"
            )
        return "\n".join(lines) if lines else "No valuation data."


class RiskOfficer:
    AGENT_NAME = "committee_risk"

    def build_prompt(self, tickers: list[str], data_context: dict[str, Any]) -> str:
        return load_prompt(
            "risk_officer",
            portfolio_context=self._build_context(tickers, data_context),
        )

    def _build_context(self, tickers: list[str], ctx: dict[str, Any]) -> str:
        holdings_reports = ctx.get("holdings_reports", [])
        macro_data = ctx.get("macro_data", {})
        strategy = ctx.get("strategy", {})
        total_value = sum(report.get("market_value", 0) or 0 for report in holdings_reports)

        lines = [f"Total portfolio value: {total_value:,.0f}"]
        vix = macro_data.get("vix")
        if isinstance(vix, dict):
            vix = vix.get("value")
        lines.append(f"VIX: {vix if vix is not None else 'N/A'}")
        lines.append("HOLDINGS:")
        for report in holdings_reports:
            lines.append(
                f"  {report.get('ticker', '')}: {report.get('position_pct', 'N/A')} percent of portfolio | "
                f"price={report.get('price', 'N/A')} change={report.get('change_pct', 0):+.1f}% | sector={report.get('sector', '')}"
            )
        actions = strategy.get("actions", [])
        if actions:
            lines.append("PENDING STRATEGY ACTIONS:")
            for action in actions:
                lines.append(f"  {action.get('action', '').upper()} {action.get('ticker', '')}: {action.get('reason', '')}")
        return "\n".join(lines)


class AdvisorEditor:
    AGENT_NAME = "committee_editor"

    async def synthesize(
        self,
        *,
        growth_report: dict[str, Any],
        value_report: dict[str, Any],
        risk_report: dict[str, Any],
        missing_reports: list[str],
        delta_summary: str = "",
        retrospective_context: str = "",
        catalyst_section: str = "",
        macro_context: str = "",
        holdings_context: str = "",
        conviction_context: str = "",
        strategy_context: str = "",
        news_context: str = "",
        reddit_context: str = "",
        substack_context: str = "",
        calibration_context: str = "",
        preference_context: str = "",
        causal_context: str = "",
        supplementary_research: str = "",
        mandate_breach_ctx: str = "",
        citations: str = "",
        deep_research_context: str = "",
    ) -> dict[str, Any]:
        analyst_budget = ContextBudget(token_budget=2500)
        analyst_budget.add_section("Growth", json.dumps(growth_report, indent=2), "analyst_reports")
        analyst_budget.add_section("Value", json.dumps(value_report, indent=2), "analyst_reports")
        analyst_budget.add_section("Risk", json.dumps(risk_report, indent=2), "analyst_reports")

        signal_budget = ContextBudget(token_budget=2000)
        signal_budget.add_section("News", news_context, "news")
        signal_budget.add_section("Reddit", reddit_context, "reddit")
        signal_budget.add_section("Substack", substack_context, "substack")

        deep_research_budget = ContextBudget(token_budget=4000)
        deep_research_budget.add_section("Deep Research", deep_research_context, 85)

        prompt = load_prompt(
            "cio_editor",
            mandate_breaches=mandate_breach_ctx or "None.",
            growth_report=_budgeted_json(growth_report, 900),
            value_report=_budgeted_json(value_report, 900),
            risk_report=_budgeted_json(risk_report, 900),
            missing_reports=", ".join(missing_reports) if missing_reports else "None.",
            delta_summary=delta_summary,
            retrospective_context=retrospective_context,
            calibration_context=calibration_context,
            preference_context=preference_context,
            causal_context=causal_context,
            deep_research_blocks=deep_research_budget.render(),
            supplementary_research=supplementary_research,
            catalyst_section=catalyst_section,
            macro_context=macro_context,
            holdings_context=holdings_context,
            strategy_context=strategy_context,
            conviction_context=conviction_context,
            signal_intelligence=signal_budget.render(),
            citations=citations,
        )

        editor_model = select_model(EDITOR_MODEL, allow_downgrade=False)
        runner = _make_text_agent(self.AGENT_NAME, editor_model, 4200)
        return await runner(prompt)


def _budgeted_json(payload: dict[str, Any], token_budget: int) -> str:
    budget = ContextBudget(token_budget=token_budget)
    budget.add_section("JSON", json.dumps(payload, indent=2), "analyst_reports")
    return budget.render()


def _estimate_tokens(data: Any) -> int:
    """Rough token estimate: ~4 chars per token on serialized JSON."""
    try:
        return len(json.dumps(data, default=str)) // 4
    except (TypeError, ValueError):
        return 0


async def run_analyst_committee(
    tickers: list[str],
    data_context: dict,
    delta_summary: str = "",
    retrospective_context: str = "",
    catalyst_section: str = "",
    macro_context: str = "",
    holdings_context: str = "",
    conviction_context: str = "",
    strategy_context: str = "",
    news_context: str = "",
    reddit_context: str = "",
    substack_context: str = "",
    calibration_context: str = "",
    preference_context: str = "",
    causal_context: str = "",
    supplementary_research: str = "",
    earnings_context: str = "",
    superinvestor_context: str = "",
    deep_research_tickers: list[str] | None = None,
    config: dict | None = None,
    mandate_breach_ctx: str = "",
) -> dict[str, Any]:
    log.info("Running analyst committee for %d tickers", len(tickers))

    growth = GrowthAnalyst()
    value = ValueAnalyst()
    risk = RiskOfficer()
    editor = AdvisorEditor()

    # Scope data_context per analyst to reduce token usage
    full_tokens = _estimate_tokens(data_context)

    growth_context = {
        "fundamentals": data_context.get("fundamentals", {}),
        "holdings_reports": data_context.get("holdings_reports", []),
        "earnings_data": data_context.get("earnings_data", {}),
        "news_articles": data_context.get("news_articles", []),
        "signals": data_context.get("signals", []),
    }
    log.info("Growth analyst context: %d tokens (full would be %d)", _estimate_tokens(growth_context), full_tokens)

    value_context = {
        "fundamentals": data_context.get("fundamentals", {}),
        "valuation_data": data_context.get("valuation_data", {}),
        "holdings_reports": data_context.get("holdings_reports", []),
    }
    log.info("Value analyst context: %d tokens (full would be %d)", _estimate_tokens(value_context), full_tokens)

    risk_context = {
        "holdings_reports": data_context.get("holdings_reports", []),
        "macro_data": data_context.get("macro_data", {}),
        "strategy": data_context.get("strategy", {}),
        "news_articles": data_context.get("news_articles", []),
    }
    log.info("Risk analyst context: %d tokens (full would be %d)", _estimate_tokens(risk_context), full_tokens)

    analyst_model = select_model(ANALYST_MODEL)
    growth_runner = _make_json_agent(growth.AGENT_NAME, analyst_model, 3200)
    value_runner = _make_json_agent(value.AGENT_NAME, analyst_model, 3200)
    risk_runner = _make_json_agent(risk.AGENT_NAME, analyst_model, 3200)

    analyst_tasks = {
        "growth": growth_runner(growth.build_prompt(tickers, growth_context)),
        "value": value_runner(value.build_prompt(tickers, value_context)),
        "risk": risk_runner(risk.build_prompt(tickers, risk_context)),
    }
    analyst_results = await asyncio.gather(*analyst_tasks.values(), return_exceptions=True)

    reports: dict[str, dict[str, Any]] = {"growth": {}, "value": {}, "risk": {}}
    missing_reports: list[str] = []
    agent_meta: dict[str, dict[str, Any]] = {}

    for name, outcome in zip(analyst_tasks.keys(), analyst_results):
        if isinstance(outcome, Exception):
            log.warning("%s analyst failed: %s", name, outcome)
            reports[name] = {"error": "analysis_failed", "analyst": name, "analyses": {}}
            missing_reports.append(name)
            continue
        if outcome.get("error"):
            missing_reports.append(name)
        data = outcome.get("data") or {}
        if name != "risk":
            data.setdefault("analyses", {})
        data.setdefault("analyst", name)
        reports[name] = data
        agent_meta[name] = {
            "cost_usd": outcome.get("cost_usd", 0.0),
            "elapsed_s": outcome.get("elapsed_s", 0.0),
        }

    # Stage 3.5: deep research, causal reasoner, and gap resolution with partial-failure tolerance.
    deep_research_result: dict[str, Any] = {"blocks": {}, "citations": [], "citations_html": ""}
    enriched_causal_context = causal_context
    enriched_supplementary = supplementary_research
    citation_registry = CitationRegistry()
    for article in data_context.get("news_articles", [])[:15]:
        citation_registry.register(
            article.get("url", ""),
            article.get("title", "Untitled"),
            article.get("origin", article.get("source", "news_desk")),
            article.get("published_at", ""),
        )

    stage35_tasks: list[tuple[str, asyncio.Future[Any] | asyncio.Task[Any] | Any]] = []

    if deep_research_tickers is None:
        deep_research_tickers = tickers[:6]

    planner = ResearchPlanner()
    plan = planner.plan(
        tickers=deep_research_tickers,
        holdings_reports=data_context.get("holdings_reports", []),
        news_articles=data_context.get("news_articles", []),
        signals=data_context.get("signals", []),
        earnings_data=data_context.get("earnings_data", {}),
        max_tasks=(config or {}).get("committee", {}).get("deep_research_max_tickers", 6),
    )

    if plan.tasks:
        deep_researcher = MultiStepDeepResearcher(
            max_full=(config or {}).get("committee", {}).get("deep_research_full_max", 3)
        )
        stage35_tasks.append(
            (
                "deep_research",
                deep_researcher.run(
                    plan,
                    data_context,
                    last_signal_id=int(data_context.get("last_signal_id") or 0),
                ),
            )
        )

    if not enriched_causal_context:
        try:
            from src.advisor.causal_reasoner import CausalReasoner, format_causal_for_prompt

            reasoner = CausalReasoner()
            stage35_tasks.append(
                (
                    "causal",
                    reasoner.analyze(
                        top_tickers=tickers[:5],
                        analyst_reports={
                            "growth": reports["growth"].get("analyses", {}),
                            "value": reports["value"].get("analyses", {}),
                        },
                        holdings_data=data_context.get("holdings_reports", []),
                        macro_context=macro_context,
                        calibration_context=calibration_context,
                    ),
                )
            )
        except ImportError:
            log.debug("Causal reasoner not available")

    if not enriched_supplementary:
        try:
            from src.advisor.gap_resolver import GapResolver, format_supplementary_research, parse_gaps_from_analyst_output

            gaps = []
            for report in reports.values():
                gaps.extend(parse_gaps_from_analyst_output(report))
            if gaps:
                resolver = GapResolver()
                stage35_tasks.append(("gaps", resolver.resolve_gaps(gaps[:5], data_context)))
        except ImportError:
            log.debug("Gap resolver not available")

    if stage35_tasks:
        stage35_results = await asyncio.gather(*[task for _, task in stage35_tasks], return_exceptions=True)
        for (name, _), outcome in zip(stage35_tasks, stage35_results):
            if isinstance(outcome, Exception):
                log.warning("Stage 3.5 %s failed: %s", name, outcome)
                continue
            if name == "deep_research":
                deep_research_result = outcome
                for citation in outcome.get("citations", []):
                    citation_registry.register(
                        str(citation.get("url", "")),
                        str(citation.get("title", "Untitled")),
                        str(citation.get("source_agent", "deep_researcher")),
                        str(citation.get("published_at", "")),
                    )
            elif name == "causal":
                from src.advisor.causal_reasoner import format_causal_for_prompt

                enriched_causal_context = format_causal_for_prompt(outcome)
            elif name == "gaps":
                from src.advisor.gap_resolver import format_supplementary_research

                enriched_supplementary = format_supplementary_research(outcome)

    # Build deep research prompt section from blocks
    deep_research_prompt_section = ""
    blocks = deep_research_result.get("blocks", {})
    if blocks:
        block_texts = []
        for block in (blocks.values() if isinstance(blocks, dict) else blocks):
            content = block.get("content", "") if isinstance(block, dict) else str(block)
            block_texts.append(content[:1500])
        if block_texts:
            blocks_text = "\n\n---\n\n".join(block_texts)
            deep_research_prompt_section = f"## Deep Research\n{blocks_text}"

    editor_result = await editor.synthesize(
        growth_report=reports["growth"],
        value_report=reports["value"],
        risk_report=reports["risk"],
        missing_reports=missing_reports,
        delta_summary=delta_summary,
        retrospective_context=retrospective_context,
        catalyst_section=catalyst_section,
        macro_context=macro_context,
        holdings_context=holdings_context,
        conviction_context=conviction_context,
        strategy_context=strategy_context,
        news_context=news_context,
        reddit_context=reddit_context,
        substack_context=substack_context,
        calibration_context=calibration_context,
        preference_context=preference_context,
        causal_context=enriched_causal_context,
        supplementary_research=enriched_supplementary,
        mandate_breach_ctx=mandate_breach_ctx,
        citations=citation_registry.format_for_prompt(),
        deep_research_context=deep_research_prompt_section,
    )

    brief_text = editor_result.get("raw_text", "")
    result = {
        "formatted_brief": brief_text,
        "growth_report": reports["growth"],
        "value_report": reports["value"],
        "risk_report": reports["risk"],
        "deep_research": deep_research_result,
        "missing_reports": missing_reports,
        "citations": citation_registry.as_list(),
        "citations_html": citation_registry.format_for_html(),
        "agent_meta": agent_meta,
    }
    if editor_result.get("error"):
        result["error"] = editor_result["error"]
    return result
