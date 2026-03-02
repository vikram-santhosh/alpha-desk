"""Analyst Committee for AlphaDesk Advisor v2.

Replaces the single Opus synthesis call with a structured multi-perspective
analysis pipeline:
  Stage 1: Growth Analyst (revenue, TAM, competitive moat)
  Stage 2: Value Analyst (valuation, margin of safety, capital allocation)
  Stage 3: Risk Officer (portfolio-level risk, correlation, drawdown scenarios)
  Stage 4: Editor/CIO (synthesizes all perspectives into daily brief)

Stages 1-3 run in parallel. Stage 4 runs after all three complete.
"""

import asyncio
import json
from typing import Any

from src.shared import gemini_compat as anthropic

from src.shared.cost_tracker import check_budget, record_usage
from src.utils.logger import get_logger

log = get_logger(__name__)

MODEL = "claude-opus-4-6"


# ═══════════════════════════════════════════════════════
# STAGE 1: GROWTH ANALYST
# ═══════════════════════════════════════════════════════

class GrowthAnalyst:
    """Evaluates tickers from a growth perspective.

    Focuses on: revenue acceleration, TAM expansion, competitive moats,
    product cycles, management execution, earnings quality.
    """

    AGENT_NAME = "committee_growth"

    def analyze(self, tickers: list[str], data_context: dict) -> dict:
        """Produce growth analysis for key tickers."""
        within_budget, _, _ = check_budget()
        if not within_budget:
            return {"error": "budget_exceeded", "analyses": {}}

        holdings_ctx = self._build_holdings_context(tickers, data_context)

        prompt = f"""You are a growth equity analyst at a top-tier investment firm. You evaluate companies primarily on growth trajectory, competitive positioning, and earnings quality. You are OPTIMISTIC by nature but RIGOROUS about evidence.

PORTFOLIO HOLDINGS AND DATA:
{holdings_ctx}

For each holding, produce a growth assessment. Respond with ONLY valid JSON:
{{
  "analyses": {{
    "TICKER": {{
      "growth_thesis": "2-3 sentences on the growth story",
      "growth_score": 75,
      "revenue_acceleration": true,
      "competitive_moat": "strong",
      "key_growth_risk": "Biggest risk to growth",
      "growth_catalysts": ["catalyst 1", "catalyst 2"]
    }}
  }},
  "top_growth_pick": "TICKER with strongest growth profile",
  "growth_concern": "TICKER with most concerning growth trajectory"
}}

RULES:
- growth_score > 80 requires revenue acceleration AND expanding margins
- growth_score > 70 requires at least revenue growth > 15%
- growth_score < 40 if revenue is decelerating
- Be specific with numbers."""

        try:
            client = anthropic.Anthropic()
            response = client.messages.create(
                model=MODEL, max_tokens=3500,
                messages=[{"role": "user", "content": prompt}],
            )
            usage = response.usage
            record_usage(self.AGENT_NAME, usage.input_tokens, usage.output_tokens, model=MODEL)
            log.info("Growth analyst: %d in, %d out", usage.input_tokens, usage.output_tokens)

            text = response.content[0].text.strip()
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()
            return json.loads(text)

        except json.JSONDecodeError:
            log.warning("Growth analyst returned truncated JSON — returning partial result")
            return {"error": "analysis_failed", "analyses": {}, "reason": "json_truncated"}
        except Exception:
            log.exception("Growth analyst failed")
            return {"error": "analysis_failed", "analyses": {}}

    def _build_holdings_context(self, tickers: list[str], ctx: dict) -> str:
        lines = []
        fundamentals = ctx.get("fundamentals", {})
        holdings_reports = ctx.get("holdings_reports", [])
        report_map = {r.get("ticker"): r for r in holdings_reports}

        for t in tickers[:12]:
            fund = fundamentals.get(t, {})
            report = report_map.get(t, {})
            rev_growth = fund.get("revenue_growth")
            rev_str = f"{rev_growth:.0%}" if rev_growth is not None else "N/A"
            margin = fund.get("net_margin")
            margin_str = f"{margin:.0%}" if margin is not None else "N/A"
            pe = fund.get("pe_trailing", "N/A")
            price = report.get("price", fund.get("current_price", "N/A"))
            chg = report.get("change_pct")
            chg_str = f"{chg:+.1f}%" if chg is not None else ""
            lines.append(f"- {t}: ${price} {chg_str} | Rev growth: {rev_str} | Margin: {margin_str} | P/E: {pe}")
        return "\n".join(lines) if lines else "No holdings data."


# ═══════════════════════════════════════════════════════
# STAGE 2: VALUE ANALYST
# ═══════════════════════════════════════════════════════

class ValueAnalyst:
    """Evaluates tickers from a valuation/risk-reward perspective.

    Focuses on: intrinsic value, margin of safety, peer comparisons,
    capital allocation, balance sheet quality.
    """

    AGENT_NAME = "committee_value"

    def analyze(self, tickers: list[str], data_context: dict) -> dict:
        """Produce value analysis for key tickers."""
        within_budget, _, _ = check_budget()
        if not within_budget:
            return {"error": "budget_exceeded", "analyses": {}}

        holdings_ctx = self._build_context(tickers, data_context)

        prompt = f"""You are a value-oriented portfolio manager in the tradition of Buffett/Klarman. You evaluate companies primarily on valuation, margin of safety, and capital allocation quality. You are SKEPTICAL of hype but OPEN to paying up for genuine quality.

PORTFOLIO HOLDINGS AND VALUATIONS:
{holdings_ctx}

For each holding, produce a value assessment. Respond with ONLY valid JSON:
{{
  "analyses": {{
    "TICKER": {{
      "value_thesis": "2-3 sentences on valuation",
      "value_score": 65,
      "current_regime": "expensive",
      "margin_of_safety_pct": -15,
      "key_valuation_risk": "The biggest valuation risk",
      "what_would_make_it_cheap": "What price/multiple creates margin of safety"
    }}
  }},
  "best_value": "TICKER with best risk-reward",
  "most_expensive": "TICKER most overvalued relative to fundamentals"
}}

RULES:
- value_score > 80 requires margin_of_safety > 20%
- value_score 50-80 for fairly valued with growth optionality
- value_score < 30 if trading at >2x fair value
- Always compare to sector peers, not just absolute multiples"""

        try:
            client = anthropic.Anthropic()
            response = client.messages.create(
                model=MODEL, max_tokens=3500,
                messages=[{"role": "user", "content": prompt}],
            )
            usage = response.usage
            record_usage(self.AGENT_NAME, usage.input_tokens, usage.output_tokens, model=MODEL)
            log.info("Value analyst: %d in, %d out", usage.input_tokens, usage.output_tokens)

            text = response.content[0].text.strip()
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()
            return json.loads(text)

        except json.JSONDecodeError:
            log.warning("Value analyst returned truncated JSON — returning partial result")
            return {"error": "analysis_failed", "analyses": {}, "reason": "json_truncated"}
        except Exception:
            log.exception("Value analyst failed")
            return {"error": "analysis_failed", "analyses": {}}

    def _build_context(self, tickers: list[str], ctx: dict) -> str:
        lines = []
        fundamentals = ctx.get("fundamentals", {})
        valuations = ctx.get("valuation_data", {})

        for t in tickers[:12]:
            fund = fundamentals.get(t, {})
            val = valuations.get(t, {})
            pe = fund.get("pe_trailing", "N/A")
            pe_fwd = fund.get("pe_forward", "N/A")
            cagr = val.get("implied_cagr")
            mos = val.get("margin_of_safety")
            target = val.get("target_price")
            price = fund.get("current_price", "N/A")
            cagr_str = f"{cagr:.1f}%" if cagr is not None else "N/A"
            mos_str = f"{mos:.1f}%" if mos is not None else "N/A"
            target_str = f"${target:.2f}" if target is not None else "N/A"
            lines.append(f"- {t}: ${price} | P/E: {pe} fwd {pe_fwd} | Target: {target_str} | CAGR: {cagr_str} | MoS: {mos_str}")
        return "\n".join(lines) if lines else "No valuation data."


# ═══════════════════════════════════════════════════════
# STAGE 3: RISK OFFICER
# ═══════════════════════════════════════════════════════

class RiskOfficer:
    """Evaluates portfolio-level risk and per-ticker risk.

    Focuses on: correlation risk, concentration, drawdown scenarios,
    macro sensitivity, liquidity risk, thesis dependency.
    """

    AGENT_NAME = "committee_risk"

    def analyze(self, tickers: list[str], data_context: dict) -> dict:
        """Produce risk analysis for portfolio and individual tickers."""
        within_budget, _, _ = check_budget()
        if not within_budget:
            return {"error": "budget_exceeded"}

        portfolio_ctx = self._build_context(tickers, data_context)

        prompt = f"""You are a risk officer at a multi-billion dollar fund. Your job is to identify what could go wrong. You think in scenarios, correlations, and tail risks. You are paid to worry.

PORTFOLIO:
{portfolio_ctx}

Analyze PORTFOLIO-LEVEL risk and per-ticker risk. Respond with ONLY valid JSON:
{{
  "portfolio_risk_flags": [
    {{
      "flag": "Description of risk",
      "exposure_pct": 62,
      "affected_tickers": ["NVDA", "AVGO"],
      "scenario": "If X happens, estimated impact: -Y%",
      "mitigation": "How to reduce this risk"
    }}
  ],
  "correlation_warning": "How many holdings are effectively correlated",
  "max_drawdown_scenario": {{
    "scenario": "Worst case scenario name",
    "estimated_portfolio_drawdown_pct": -35,
    "which_holdings_survive": ["ticker1"],
    "which_dont": ["ticker2"]
  }},
  "risk_score_portfolio": 42,
  "top_risk": "Single biggest portfolio risk right now"
}}

RULES:
- risk_score: 0-100 where higher = LESS risky (100 = very safe portfolio)
- Be specific about mechanisms: "Fed raises rates 50bp" not "rates go up"
- Quantify everything: exposure percentages, drawdown estimates, correlation counts
- Think about hidden correlations: tech stocks that all depend on the same CapEx cycle"""

        try:
            client = anthropic.Anthropic()
            response = client.messages.create(
                model=MODEL, max_tokens=3500,
                messages=[{"role": "user", "content": prompt}],
            )
            usage = response.usage
            record_usage(self.AGENT_NAME, usage.input_tokens, usage.output_tokens, model=MODEL)
            log.info("Risk officer: %d in, %d out", usage.input_tokens, usage.output_tokens)

            text = response.content[0].text.strip()
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()
            return json.loads(text)

        except json.JSONDecodeError:
            log.warning("Risk officer returned truncated JSON — returning partial result")
            return {"error": "analysis_failed", "reason": "json_truncated"}
        except Exception:
            log.exception("Risk officer failed")
            return {"error": "analysis_failed"}

    def _build_context(self, tickers: list[str], ctx: dict) -> str:
        lines = []
        holdings_reports = ctx.get("holdings_reports", [])
        macro_data = ctx.get("macro_data", {})
        strategy = ctx.get("strategy", {})

        # Portfolio summary
        total_value = sum(r.get("market_value", 0) or 0 for r in holdings_reports)
        lines.append(f"Total portfolio value: ${total_value:,.0f}")

        # Macro
        vix = macro_data.get("vix", {})
        vix_val = vix.get("value") if isinstance(vix, dict) else vix
        lines.append(f"VIX: {vix_val or 'N/A'}")

        lines.append("")
        lines.append("HOLDINGS:")
        for r in holdings_reports:
            t = r.get("ticker", "")
            pct = r.get("position_pct")
            sector = r.get("sector", "")
            price = r.get("price")
            chg = r.get("change_pct")
            pct_str = f"{pct:.1f}%" if pct is not None else "N/A"
            chg_str = f"{chg:+.1f}%" if chg is not None else ""
            lines.append(f"  {t}: {pct_str} of portfolio | ${price} {chg_str} | {sector}")

        # Strategy actions
        actions = strategy.get("actions", [])
        if actions:
            lines.append("")
            lines.append("PENDING STRATEGY ACTIONS:")
            for a in actions:
                lines.append(f"  {a.get('action', '').upper()} {a.get('ticker')} — {a.get('reason', '')}")

        return "\n".join(lines)


# ═══════════════════════════════════════════════════════
# STAGE 4: EDITOR / CIO
# ═══════════════════════════════════════════════════════

class AdvisorEditor:
    """Synthesizes all analyst outputs into the final daily brief.

    Has access to: growth analysis, value analysis, risk analysis,
    delta report, retrospective, and all raw data.
    """

    AGENT_NAME = "committee_editor"

    def synthesize(
        self,
        growth_report: dict,
        value_report: dict,
        risk_report: dict,
        delta_summary: str = "",
        retrospective_context: str = "",
        catalyst_section: str = "",
        macro_context: str = "",
        holdings_context: str = "",
        conviction_context: str = "",
        strategy_context: str = "",
    ) -> dict:
        """Synthesize all analyst reports into the final daily brief."""
        within_budget, _, _ = check_budget()
        if not within_budget:
            return {"error": "budget_exceeded", "formatted_brief": ""}

        prompt = f"""You are the Chief Investment Officer writing the daily brief. You have reports from your Growth Analyst, Value Analyst, and Risk Officer.

GROWTH ANALYST REPORT:
{json.dumps(growth_report, indent=2)[:3000]}

VALUE ANALYST REPORT:
{json.dumps(value_report, indent=2)[:3000]}

RISK OFFICER REPORT:
{json.dumps(risk_report, indent=2)[:3000]}

{delta_summary}

{retrospective_context}

{catalyst_section}

MACRO CONTEXT:
{macro_context}

HOLDINGS SNAPSHOT:
{holdings_context}

STRATEGY ENGINE OUTPUT:
{strategy_context}

CONVICTION LIST:
{conviction_context}

Write the daily brief with these sections:

**SECTION 1 - WHAT CHANGED TODAY** (2-3 sentences)
Lead with the most important change. If nothing material changed, say so.

**SECTION 2 - ANALYST CONSENSUS & DISAGREEMENTS** (3-5 bullet points)
Where do your analysts agree? Where do they disagree? When analysts disagree, who has the stronger evidence?

**SECTION 3 - ACTIONS** (if any)
Specific recommendations with conviction and sizing. Only if evidence warrants. "No action" is always the default.

**SECTION 4 - WHAT TO WATCH THIS WEEK**
Specific upcoming events that matter for this portfolio.

**SECTION 5 - PORTFOLIO HEALTH**
Risk officer's top concern, concentration, correlation.

RULES:
- When Growth Analyst is bullish but Value Analyst says expensive and Risk Officer flags concentration, surface this CONFLICT explicitly.
- If all three analysts agree, it's high conviction. Say so.
- If your track record shows a bias, explicitly correct for it.
- "No action" is always the default. Only recommend changes when evidence is overwhelming.
- Be direct. Cite specific numbers. No hedging language.
- Separate sections with blank lines. Use bullet points for Sections 2-5."""

        try:
            client = anthropic.Anthropic()
            response = client.messages.create(
                model=MODEL, max_tokens=3000,
                messages=[{"role": "user", "content": prompt}],
            )
            usage = response.usage
            record_usage(self.AGENT_NAME, usage.input_tokens, usage.output_tokens, model=MODEL)
            log.info("Editor synthesis: %d in, %d out", usage.input_tokens, usage.output_tokens)

            brief_text = response.content[0].text.strip()
            return {
                "formatted_brief": brief_text,
                "growth_report": growth_report,
                "value_report": value_report,
                "risk_report": risk_report,
            }

        except Exception:
            log.exception("Editor synthesis failed")
            return {"error": "synthesis_failed", "formatted_brief": ""}


# ═══════════════════════════════════════════════════════
# COMMITTEE ORCHESTRATOR
# ═══════════════════════════════════════════════════════

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
) -> dict:
    """Run the full analyst committee pipeline.

    Stages 1-3 run in parallel, Stage 4 after all complete.

    Returns dict with: formatted_brief, growth_report, value_report, risk_report.
    """
    log.info("Running analyst committee for %d tickers", len(tickers))

    growth = GrowthAnalyst()
    value = ValueAnalyst()
    risk = RiskOfficer()
    editor = AdvisorEditor()

    # Stages 1-3: parallel
    growth_result, value_result, risk_result = await asyncio.gather(
        asyncio.to_thread(growth.analyze, tickers, data_context),
        asyncio.to_thread(value.analyze, tickers, data_context),
        asyncio.to_thread(risk.analyze, tickers, data_context),
    )

    log.info("Committee stages 1-3 complete. Growth: %s, Value: %s, Risk: %s",
             "OK" if "error" not in growth_result else growth_result["error"],
             "OK" if "error" not in value_result else value_result["error"],
             "OK" if "error" not in risk_result else risk_result["error"])

    # Stage 4: editor synthesis
    result = editor.synthesize(
        growth_report=growth_result,
        value_report=value_result,
        risk_report=risk_result,
        delta_summary=delta_summary,
        retrospective_context=retrospective_context,
        catalyst_section=catalyst_section,
        macro_context=macro_context,
        holdings_context=holdings_context,
        conviction_context=conviction_context,
        strategy_context=strategy_context,
    )

    log.info("Committee complete. Brief length: %d chars",
             len(result.get("formatted_brief", "")))

    return result
