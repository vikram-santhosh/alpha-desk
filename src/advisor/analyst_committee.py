"""Analyst committee orchestration for AlphaDesk Advisor."""
from __future__ import annotations

import asyncio
import json
import os
from typing import Any

from src.advisor.council import CouncilRequest, CouncilResponse, GCPCouncilClient
from src.shared import cost_tracker
from src.shared import gemini_compat as anthropic
from src.shared.agent_decorator import select_model, track_agent
from src.shared.citations import CitationRegistry
from src.shared.context_manager import ContextBudget
from src.shared.model_registry import council_enabled
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
        "model": response.model,
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
                f"price={report.get('price', 'N/A')} change={report.get('change_pct') or 0:+.1f}% | sector={report.get('sector', '')}"
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
    run_type: str = "morning_full",
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
        committee_config = (config or {}).get("committee", {})
        deep_researcher = MultiStepDeepResearcher(
            max_full=committee_config.get("deep_research_full_max", 3),
            web_search_enabled=committee_config.get("web_search_enabled", True),
            web_search_max_results=committee_config.get("web_search_max_results", 5),
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

    council_result = await _maybe_run_brief_council(
        run_type=run_type,
        tickers=tickers,
        data_context=data_context,
        macro_context=macro_context,
        holdings_context=holdings_context,
        conviction_context=conviction_context,
        strategy_context=strategy_context,
        config=config or {},
    )
    council_context = council_result.get("prompt_context", "")
    if council_context:
        deep_research_prompt_section = (
            f"{deep_research_prompt_section}\n\n{council_context}"
            if deep_research_prompt_section
            else council_context
        )

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
    if council_result.get("enabled"):
        result["council"] = council_result.get("summary", {})
        degraded_reasons = council_result.get("degraded_reasons", [])
        if degraded_reasons:
            result["degraded_reasons"] = degraded_reasons
    if editor_result.get("error"):
        result["error"] = editor_result["error"]
    return result


def _brief_council_cost_cap_usd() -> float:
    try:
        return float(os.getenv("COUNCIL_COST_CAP_USD", "2.00"))
    except ValueError:
        return 2.0


def _brief_council_max_tokens() -> int:
    try:
        return max(1000, min(4000, int(os.getenv("COUNCIL_BRIEF_MAX_TOKENS", "3500"))))
    except ValueError:
        return 3500


def _top_council_tickers(tickers: list[str], conviction_context: str, config: dict[str, Any]) -> list[str]:
    output_config = config.get("output", {}) if isinstance(config, dict) else {}
    try:
        max_names = max(1, int(output_config.get("max_conviction_list", 5)))
    except (TypeError, ValueError):
        max_names = 5

    selected: list[str] = []
    seen: set[str] = set()
    for line in (conviction_context or "").splitlines():
        stripped = line.strip()
        if not stripped.startswith("- "):
            continue
        token = stripped[2:].split(":", 1)[0].strip().upper()
        normalized = token.replace(".", "").replace("-", "")
        if token and normalized.isalnum() and token not in seen:
            selected.append(token)
            seen.add(token)
        if len(selected) >= max_names:
            return selected

    for ticker in tickers:
        normalized_ticker = str(ticker).strip().upper()
        if normalized_ticker and normalized_ticker not in seen:
            selected.append(normalized_ticker)
            seen.add(normalized_ticker)
        if len(selected) >= max_names:
            break
    return selected


async def _maybe_run_brief_council(
    *,
    run_type: str,
    tickers: list[str],
    data_context: dict[str, Any],
    macro_context: str,
    holdings_context: str,
    conviction_context: str,
    strategy_context: str,
    config: dict[str, Any],
) -> dict[str, Any]:
    if run_type != "morning_full" or not council_enabled():
        return {"enabled": False}

    cap_usd = _brief_council_cost_cap_usd()
    if cap_usd <= 0:
        return {
            "enabled": True,
            "summary": {"mode": "skipped", "cost_usd": 0.0, "responses": []},
            "degraded_reasons": ["Model council skipped because COUNCIL_COST_CAP_USD is 0."],
        }

    within_budget, spent, budget_cap = cost_tracker.check_budget()
    if not within_budget:
        return {
            "enabled": True,
            "summary": {"mode": "skipped", "cost_usd": 0.0, "responses": []},
            "degraded_reasons": [
                f"Model council skipped because run budget is exhausted (${spent:.2f} / ${budget_cap:.2f})."
            ],
        }

    selected_tickers = _top_council_tickers(tickers, conviction_context, config)
    if not selected_tickers:
        return {
            "enabled": True,
            "summary": {"mode": "skipped", "cost_usd": 0.0, "responses": []},
            "degraded_reasons": ["Model council skipped because there were no conviction tickers to review."],
        }

    prompt = _build_brief_council_prompt(
        selected_tickers=selected_tickers,
        data_context=data_context,
        macro_context=macro_context,
        holdings_context=holdings_context,
        conviction_context=conviction_context,
        strategy_context=strategy_context,
    )
    request = CouncilRequest(
        prompt=prompt,
        system=(
            "You are an adversarial investment council seat. Use only the supplied context, "
            "separate evidence from inference, and explicitly challenge weak claims."
        ),
        max_tokens=_brief_council_max_tokens(),
    )

    try:
        responses = await GCPCouncilClient().deliberate(request)
    except Exception as exc:
        log.warning("Model council skipped: %s", exc)
        return {
            "enabled": True,
            "summary": {"mode": "failed", "cost_usd": 0.0, "responses": []},
            "degraded_reasons": [f"Model council unavailable: {exc}"],
        }

    cost_usd, response_costs = _record_council_costs(responses)
    degraded_reasons = [
        f"{response.label} failed: {response.error}" for response in responses if response.error
    ]
    response_dicts = [
        _council_response_to_dict(response, response_costs.get(_council_response_key(response), 0.0))
        for response in responses
    ]

    if cost_usd > cap_usd:
        degraded_reasons.append(
            f"Model council omitted from CIO context because cost ${cost_usd:.2f} exceeded COUNCIL_COST_CAP_USD ${cap_usd:.2f}."
        )
        return {
            "enabled": True,
            "summary": {
                "mode": "cost_cap_exceeded",
                "selected_tickers": selected_tickers,
                "cost_usd": round(cost_usd, 4),
                "responses": response_dicts,
            },
            "degraded_reasons": degraded_reasons,
        }

    run_budget = cost_tracker.get_current_run_budget()
    if run_budget is not None and cost_tracker.get_run_cost() > run_budget:
        degraded_reasons.append(
            f"Model council omitted from CIO context because run cost exceeded budget after council execution (${cost_tracker.get_run_cost():.2f} / ${run_budget:.2f})."
        )
        return {
            "enabled": True,
            "summary": {
                "mode": "run_budget_exceeded",
                "selected_tickers": selected_tickers,
                "cost_usd": round(cost_usd, 4),
                "responses": response_dicts,
            },
            "degraded_reasons": degraded_reasons,
        }

    prompt_context = _format_brief_council_context(responses)
    mode = "completed" if prompt_context else "failed"
    if not prompt_context:
        degraded_reasons.append("Model council produced no usable responses for CIO synthesis.")

    return {
        "enabled": True,
        "prompt_context": prompt_context,
        "summary": {
            "mode": mode,
            "selected_tickers": selected_tickers,
            "cost_usd": round(cost_usd, 4),
            "responses": response_dicts,
        },
        "degraded_reasons": degraded_reasons,
    }


def _build_brief_council_prompt(
    *,
    selected_tickers: list[str],
    data_context: dict[str, Any],
    macro_context: str,
    holdings_context: str,
    conviction_context: str,
    strategy_context: str,
) -> str:
    fundamentals = data_context.get("fundamentals", {})
    valuations = data_context.get("valuation_data", {})
    news_articles = data_context.get("news_articles", [])
    prediction_markets = data_context.get("prediction_markets", {})

    ticker_lines = []
    for ticker in selected_tickers:
        fund = fundamentals.get(ticker, {}) if isinstance(fundamentals, dict) else {}
        valuation = valuations.get(ticker, {}) if isinstance(valuations, dict) else {}
        ticker_lines.append(
            f"- {ticker}: price={fund.get('current_price', 'N/A')} "
            f"rev_growth={fund.get('revenue_growth', 'N/A')} "
            f"forward_pe={fund.get('pe_forward', 'N/A')} "
            f"target={valuation.get('target_price', 'N/A')} "
            f"implied_cagr={valuation.get('implied_cagr', 'N/A')} "
            f"mos={valuation.get('margin_of_safety', 'N/A')}"
        )

    headline_lines = []
    for article in news_articles[:10]:
        if isinstance(article, dict):
            title = article.get("title") or article.get("headline")
            if title:
                headline_lines.append(f"- {title}")

    prediction_context = json.dumps(prediction_markets, default=str)[:1600] if prediction_markets else "None."

    return "\n".join(
        [
            "Review the top AlphaDesk conviction names as an independent model council seat.",
            "Do not give personalized financial advice. Treat this as decision-support research.",
            "",
            f"Top conviction names: {', '.join(selected_tickers)}",
            "",
            "For each name, return concise sections:",
            "1. Claims you accept from the AlphaDesk context and why.",
            "2. Claims you reject or would haircut.",
            "3. Missing evidence, source-quality problems, or crowded-narrative risk.",
            "4. Final stance: Add / Hold / Trim / Avoid, with confidence.",
            "",
            "Ticker metrics:",
            "\n".join(ticker_lines) if ticker_lines else "None.",
            "",
            "Conviction context:",
            conviction_context or "None.",
            "",
            "Strategy context:",
            strategy_context or "None.",
            "",
            "Holdings context:",
            holdings_context or "None.",
            "",
            "Macro context:",
            macro_context or "None.",
            "",
            "Prediction market context:",
            prediction_context,
            "",
            "Recent headlines:",
            "\n".join(headline_lines) if headline_lines else "None.",
        ]
    )


def _record_council_costs(responses: list[CouncilResponse]) -> tuple[float, dict[str, float]]:
    total_cost = 0.0
    costs: dict[str, float] = {}
    for response in responses:
        if not response.ok:
            continue
        output_tokens = int(response.output_tokens or 0) + int(response.reasoning_tokens or 0)
        cost = cost_tracker.record_usage(
            "committee_model_council",
            int(response.input_tokens or 0),
            output_tokens,
            model=response.model,
        )
        total_cost += cost
        costs[_council_response_key(response)] = cost
    return total_cost, costs


def _format_brief_council_context(responses: list[CouncilResponse]) -> str:
    usable = [response for response in responses if response.ok and response.text.strip()]
    if not usable:
        return ""

    lines = [
        "## Model Council",
        "CIO judge instruction: synthesize these independent council seats with the analyst reports. "
        "Explicitly surface material disagreements, rejected claims, and lower-confidence areas; do not average away dissent.",
        _council_disagreement_note(usable),
    ]
    for response in usable:
        lines.extend(
            [
                "",
                f"### {response.label} ({response.model})",
                response.text.strip()[:2200],
            ]
        )
    return "\n".join(lines)


def _council_disagreement_note(responses: list[CouncilResponse]) -> str:
    stances: dict[str, str] = {}
    for response in responses:
        text = response.text.lower()
        if any(word in text for word in ("avoid", "sell", "trim", "underweight")):
            stance = "bearish"
        elif any(word in text for word in ("hold", "neutral", "wait")):
            stance = "neutral"
        elif any(word in text for word in ("add", "buy", "overweight", "constructive")):
            stance = "bullish"
        else:
            stance = "unclear"
        stances[response.label] = stance

    unique_stances = {stance for stance in stances.values() if stance != "unclear"}
    stance_text = ", ".join(f"{label}: {stance}" for label, stance in stances.items())
    if len(unique_stances) > 1:
        return f"Council disagreement detected across seats ({stance_text})."
    if len(unique_stances) == 1:
        return f"Council stance alignment: {next(iter(unique_stances))} ({stance_text})."
    return f"Council stance unclear from model text ({stance_text})."


def _council_response_to_dict(response: CouncilResponse, cost_usd: float) -> dict[str, Any]:
    provider = getattr(response.provider, "value", str(response.provider))
    return {
        "provider": provider,
        "model": response.model,
        "label": response.label,
        "ok": response.ok,
        "text": response.text,
        "input_tokens": response.input_tokens,
        "output_tokens": response.output_tokens,
        "reasoning_tokens": response.reasoning_tokens,
        "cost_usd": round(cost_usd, 6),
        "error": response.error,
    }


def _council_response_key(response: CouncilResponse) -> str:
    return f"{response.label}:{response.model}"
