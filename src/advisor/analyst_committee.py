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
            # Append top 3 news headlines for this holding
            key_events = report.get("key_events", [])
            for evt in key_events[:3]:
                headline = evt.get("headline", evt) if isinstance(evt, dict) else str(evt)
                lines.append(f"    news: {headline}")
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
# STAGE 3.5: DEEP RESEARCH ANALYST
# ═══════════════════════════════════════════════════════

class DeepResearchAnalyst:
    """Produces deep research blocks for priority stocks.

    For each priority ticker, generates a structured research note covering:
    why in focus, what changed, signal chains, management commentary,
    narrative/crowd intelligence, thesis scorecard, second-order effects,
    valuation expectations, bull/bear/base framing, and actionability.
    """

    AGENT_NAME = "committee_deep_research"

    def analyze(self, priority_tickers: list[str], data_context: dict,
                growth_report: dict, value_report: dict, risk_report: dict,
                news_context: str = "", reddit_context: str = "",
                substack_context: str = "", earnings_context: str = "",
                superinvestor_context: str = "") -> dict:
        """Produce deep research blocks for priority tickers."""
        within_budget, _, _ = check_budget()
        if not within_budget:
            return {"error": "budget_exceeded", "blocks": {}}

        if not priority_tickers:
            return {"blocks": {}}

        context = self._build_context(priority_tickers, data_context,
                                       growth_report, value_report, risk_report)

        # Append signal intelligence
        signal_parts = []
        if news_context:
            signal_parts.append(f"NEWS HEADLINES:\n{news_context}")
        if reddit_context:
            signal_parts.append(f"REDDIT / RETAIL SENTIMENT:\n{reddit_context}")
        if substack_context:
            signal_parts.append(f"EXPERT NEWSLETTERS:\n{substack_context}")
        if earnings_context:
            signal_parts.append(f"EARNINGS & GUIDANCE:\n{earnings_context}")
        if superinvestor_context:
            signal_parts.append(f"SUPERINVESTOR ACTIVITY:\n{superinvestor_context}")
        signal_section = "\n\n".join(signal_parts)

        prompt = f"""You are a lead buy-side research analyst at a concentrated long-only fund.
Your job is to convert raw signals into decision-useful equity research for the portfolio manager.

DO NOT produce a news digest. Produce compact buy-side research notes.

STOCK DATA AND ANALYST VIEWS:
{context}

SIGNAL INTELLIGENCE:
{signal_section}

For EACH of the following tickers, produce a Deep Research Block: {', '.join(priority_tickers)}

For each ticker, write these sections using the EXACT headers shown:

## {{TICKER}} — Deep Research Block

### 1. Why this name is in focus
State clearly why the stock is being discussed (held in portfolio, newly recommended, watchlist, catalyst-driven, unusual move, crowded narrative, thesis checkpoint).

### 2. What changed today
3-6 bullets of high-signal new information only. Include earnings/guidance, management commentary, analyst/industry commentary, regulatory/geopolitical developments, product/supply chain updates, unusual social/retail momentum. Skip if nothing material.

### 3. Signal → Interpretation → Investment Impact
For each important signal, use this format:
- Signal: {{fact/quote/event}}
- Interpretation: {{what this means in industry/company context}}
- Investment impact: {{bullish/bearish/mixed, and for whom}}
- Confidence: {{high/medium/low}}
Include 2-4 signal chains when enough data exists.

### 4. Management / Expert Commentary
Capture the most important commentary from management, customers, suppliers, industry leaders, serious analysts. For each: who said it, what they said (paraphrased), why it matters, whether it strengthens or weakens the thesis. Interpret, don't just dump quotes.

### 5. Narrative / Crowd Intelligence
Structure: bullish narrative, bearish narrative, what is newly trending, whether the narrative is early/crowded/fading. Be specific — avoid "sentiment mixed."

### 6. Thesis Scorecard
Format:
- Thesis: {{one sentence}}
- Status: {{Strengthening/Stable/Weakening/Broken}}
- Confidence: {{0-100}}
- Evidence supporting: 2-3 bullets
- Evidence against: 1-3 bullets
- What would break the thesis: 1-2 bullets

### 7. Second-Order Effects
Non-obvious effects if the current signal persists. Show systems thinking. Include read-throughs to other portfolio names where relevant.

### 8. Valuation / Market Expectations
What is the market pricing in? Use valuation context, growth expectations, implied optimism/skepticism, whether setup is asymmetric or crowded. Tie to expectations, not generic commentary.

### 9. Bull / Bear / Base
- Bull case: trigger + expected reaction + supporting evidence
- Base case: trigger + expected reaction + supporting evidence
- Bear case: trigger + expected reaction + supporting evidence

### 10. Actionability
- Recommended stance: {{Add/Hold/Trim/Avoid/Watch closely/Research further}}
- Why now: 2-3 sentences
- Next catalysts: 2-3 bullets
- Key unresolved questions: 1-3 bullets

CROSS-STOCK READ-THROUGHS:
When a signal on one company has implications for others, explicitly state:
Read-through to other names:
- {{ticker}}: {{impact}}

PRIORITIZATION:
- Priority 1 (full depth): portfolio holdings with meaningful move, newly recommended stocks, watchlist names with strong signal
- Priority 2 (medium depth): secondary watchlist names, adjacent read-through names
- Priority 3 (light mention): weak relevance, no meaningful new evidence

ANTI-SHALLOW RULES:
- Do NOT merely restate headlines
- Do NOT say "thesis intact" without evidence
- Do NOT say "sentiment mixed" without specifics
- Do NOT give generic commentary like "AI demand remains strong" unless tied to concrete evidence
- Do NOT repeat the same headline under multiple stocks without tailoring interpretation
- Do NOT give valuation commentary without stating what expectations appear embedded

STYLE:
Write like a sharp internal buy-side analyst: compact, high-signal, evidence-based, interpretive not descriptive, willing to surface uncertainty and counterarguments.

Good language: "This suggests…", "The key read-through is…", "The market appears to be pricing…", "This strengthens the thesis because…", "This is a headline risk, but not yet a thesis-breaker because…", "Second-order effect: …"

Respond with the research blocks as structured text (not JSON). Use the exact section headers shown above."""

        try:
            client = anthropic.Anthropic()
            response = client.messages.create(
                model=MODEL, max_tokens=8000,
                messages=[{"role": "user", "content": prompt}],
            )
            usage = response.usage
            record_usage(self.AGENT_NAME, usage.input_tokens, usage.output_tokens, model=MODEL)
            log.info("Deep research analyst: %d in, %d out", usage.input_tokens, usage.output_tokens)

            text = response.content[0].text.strip()
            blocks = self._parse_blocks(text, priority_tickers)
            return {"blocks": blocks, "raw_text": text}

        except Exception:
            log.exception("Deep research analyst failed")
            return {"error": "analysis_failed", "blocks": {}}

    def _build_context(self, tickers: list[str], ctx: dict,
                       growth_report: dict, value_report: dict,
                       risk_report: dict) -> str:
        lines = []
        fundamentals = ctx.get("fundamentals", {})
        holdings_reports = ctx.get("holdings_reports", [])
        report_map = {r.get("ticker"): r for r in holdings_reports}
        valuation_data = ctx.get("valuation_data", {})
        macro_data = ctx.get("macro_data", {})

        # Macro snapshot
        vix = macro_data.get("vix", {})
        vix_val = vix.get("value") if isinstance(vix, dict) else vix
        sp = macro_data.get("sp500", {})
        sp_val = sp.get("value") if isinstance(sp, dict) else sp
        sp_chg = sp.get("change_pct") if isinstance(sp, dict) else None
        lines.append(f"MACRO: S&P {sp_val} ({sp_chg:+.1f}% today), VIX {vix_val}" if sp_chg else f"MACRO: S&P {sp_val}, VIX {vix_val}")
        lines.append("")

        growth_analyses = growth_report.get("analyses", {})
        value_analyses = value_report.get("analyses", {})

        for t in tickers:
            fund = fundamentals.get(t, {})
            report = report_map.get(t, {})
            val = valuation_data.get(t, {})

            lines.append(f"{'='*50}")
            lines.append(f"TICKER: {t}")
            lines.append(f"{'='*50}")

            price = report.get("price", fund.get("current_price", "N/A"))
            chg = report.get("change_pct")
            pct = report.get("position_pct")
            thesis = report.get("thesis", "")
            thesis_status = report.get("thesis_status", "intact")

            chg_str = f"{chg:+.1f}%" if chg is not None else ""
            pct_str = f"{pct:.1f}% of portfolio" if pct is not None else "not in portfolio"
            lines.append(f"Price: ${price} {chg_str} | Position: {pct_str}")
            lines.append(f"Thesis: {thesis} | Status: {thesis_status}")

            # Fundamentals
            fund_parts = []
            for key, label in [("revenue_growth", "Rev growth"), ("net_margin", "Net margin"),
                               ("gross_margin", "Gross margin"), ("pe_forward", "P/E(f)"),
                               ("pe_trailing", "P/E(t)"), ("roic", "ROIC"), ("fcf_yield", "FCF yield")]:
                v = fund.get(key)
                if v is not None:
                    if key in ("pe_forward", "pe_trailing"):
                        fund_parts.append(f"{label}: {v:.1f}")
                    elif key == "fcf_yield":
                        fund_parts.append(f"{label}: {v:.1%}")
                    else:
                        fund_parts.append(f"{label}: {v:.0%}")
            if fund_parts:
                lines.append(f"Fundamentals: {' | '.join(fund_parts)}")

            # Valuation
            val_parts = []
            if val.get("target_price") is not None:
                val_parts.append(f"Target: ${val['target_price']:.2f}")
            if val.get("implied_cagr") is not None:
                val_parts.append(f"CAGR: {val['implied_cagr']:.1f}%")
            if val.get("margin_of_safety") is not None:
                val_parts.append(f"MoS: {val['margin_of_safety']:.1f}%")
            if val_parts:
                lines.append(f"Valuation: {' | '.join(val_parts)}")

            # Growth analyst view
            ga = growth_analyses.get(t, {})
            if ga:
                lines.append(f"Growth analyst: score {ga.get('growth_score', 'N/A')}/100, "
                            f"moat: {ga.get('competitive_moat', 'N/A')}, "
                            f"rev accel: {ga.get('revenue_acceleration', 'N/A')}")
                if ga.get("growth_thesis"):
                    lines.append(f"  Growth view: {ga['growth_thesis']}")
                if ga.get("key_growth_risk"):
                    lines.append(f"  Key risk: {ga['key_growth_risk']}")

            # Value analyst view
            va = value_analyses.get(t, {})
            if va:
                lines.append(f"Value analyst: score {va.get('value_score', 'N/A')}/100, "
                            f"regime: {va.get('current_regime', 'N/A')}, "
                            f"MoS: {va.get('margin_of_safety_pct', 'N/A')}%")
                if va.get("value_thesis"):
                    lines.append(f"  Value view: {va['value_thesis']}")

            # Key events
            events = report.get("key_events", [])
            if events:
                lines.append("Key events today:")
                for evt in events[:5]:
                    headline = evt.get("headline", evt) if isinstance(evt, dict) else str(evt)
                    lines.append(f"  - {headline}")

            lines.append("")

        return "\n".join(lines)

    def _parse_blocks(self, text: str, tickers: list[str]) -> dict[str, str]:
        """Parse the raw text into per-ticker blocks."""
        import re
        blocks = {}
        parts = re.split(r'\n##\s+(\w+)\s*[—–\-]\s*Deep Research Block', text)
        if len(parts) > 1:
            for i in range(1, len(parts), 2):
                ticker = parts[i].strip().upper()
                content = parts[i + 1].strip() if i + 1 < len(parts) else ""
                blocks[ticker] = content
        else:
            for t in tickers:
                pattern = rf'(?:##\s*)?{re.escape(t)}\b.*?(?=(?:##\s*\w+|$))'
                match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
                if match:
                    blocks[t] = match.group(0).strip()
        return blocks


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
        news_context: str = "",
        reddit_context: str = "",
        substack_context: str = "",
        calibration_context: str = "",
        preference_context: str = "",
        causal_context: str = "",
        supplementary_research: str = "",
    ) -> dict:
        """Synthesize all analyst reports into the final daily brief."""
        within_budget, _, _ = check_budget()
        if not within_budget:
            return {"error": "budget_exceeded", "formatted_brief": ""}

        signal_intelligence = ""
        if news_context or reddit_context or substack_context:
            parts = []
            if news_context:
                parts.append(f"TOP NEWS HEADLINES:\n{news_context}")
            if reddit_context:
                parts.append(f"REDDIT / RETAIL SENTIMENT:\n{reddit_context}")
            if substack_context:
                parts.append(f"EXPERT NEWSLETTER SIGNALS (Substack):\n{substack_context}")
            signal_intelligence = "\n\n".join(parts)

        prompt = f"""You are the Chief Investment Officer writing the daily brief for a concentrated AI/tech portfolio. You have reports from your Growth Analyst, Value Analyst, and Risk Officer, plus raw signal intelligence.

GROWTH ANALYST REPORT:
{json.dumps(growth_report, indent=2)[:3000]}

VALUE ANALYST REPORT:
{json.dumps(value_report, indent=2)[:3000]}

RISK OFFICER REPORT:
{json.dumps(risk_report, indent=2)[:3000]}

{delta_summary}

{retrospective_context}

{calibration_context}

{preference_context}

{causal_context}

{supplementary_research}

{catalyst_section}

MACRO CONTEXT:
{macro_context}

HOLDINGS SNAPSHOT:
{holdings_context}

STRATEGY ENGINE OUTPUT:
{strategy_context}

CONVICTION LIST:
{conviction_context}

{signal_intelligence}

Write the daily brief with these sections. Use the EXACT section headers shown:

**SECTION 1 - EXECUTIVE TAKE**
1 short paragraph: what changed, what matters, what to do. Lead with the most important change. Reference specific news or signals. If nothing material changed, say so.

**SECTION 2 - THEME DASHBOARD**
For each active macro thesis, provide:
- Theme name
- Status: Strengthening / Stable / Weakening / Broken (NOT just "INTACT" — use evidence)
- Confidence: 0-100
- Latest supporting evidence (specific, cited)
- Latest risks (specific, cited)
Do NOT mark everything as "intact" without justification. If chip export controls hit AI infrastructure, say the theme is under pressure.

**SECTION 3 - PORTFOLIO ACTIONS**
Specific recommendations with conviction and sizing. Structure as:
- Trims (with target weight and reasoning)
- Adds (with conviction level and evidence)
- Holds (brief justification)
- Risk management notes
"No action" is the default. Only recommend when evidence warrants.

**SECTION 4 - CROSS-ASSET / MACRO RISKS**
Regulatory, geopolitical, rate/oil/FX risks that affect this portfolio. Be specific about mechanisms and affected holdings.

**SECTION 5 - THESIS BREAKERS**
What would invalidate major portfolio themes? Be specific: "If hyperscaler CapEx guidance is cut >15% in Q2 calls, the AI infrastructure theme breaks for NVDA, AVGO, VRT, MRVL."

**SECTION 6 - UPCOMING CATALYSTS**
Events in the next 1-2 weeks that could change views. Include earnings dates, FOMC, regulatory deadlines, product launches.

**SECTION 7 - ANALYST CONSENSUS & DISAGREEMENTS**
Where do your analysts agree? Where do they disagree? When analysts disagree, who has the stronger evidence? Cross-reference with crowd sentiment.

RULES:
- When Growth Analyst is bullish but Value Analyst says expensive and Risk Officer flags concentration, surface this CONFLICT explicitly.
- If all three analysts agree, it's high conviction. Say so.
- Theme status MUST be evidence-based. Never mark a theme as stable/intact without citing specific recent evidence.
- If your track record shows a bias, explicitly correct for it.
- If CAUSAL CHAIN ANALYSIS is provided, reference assumption chains. If action depends on <50% confidence assumption, flag it explicitly.
- "No action" is always the default. Only recommend changes when evidence is overwhelming.
- Be direct. Cite specific numbers and specific headlines. No hedging language.
- Write like a sharp buy-side CIO: compact, high-signal, interpretive not descriptive.
- Separate sections with blank lines. Use bullet points within sections."""

        try:
            client = anthropic.Anthropic()
            response = client.messages.create(
                model=MODEL, max_tokens=4000,
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
) -> dict:
    """Run the full analyst committee pipeline.

    Stages 1-3 run in parallel, Stage 3.5 (deep research) runs after,
    Stage 4 (editor) runs last.

    Returns dict with: formatted_brief, growth_report, value_report, risk_report,
                       deep_research.
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

    # Stage 3.5: Deep research + Causal reasoning + Gap resolution (parallel)
    _causal_ctx = causal_context
    _supplementary_ctx = supplementary_research
    deep_research_result = {"blocks": {}}

    # Determine priority tickers for deep research
    if deep_research_tickers is None:
        # Default: holdings with >2% move + watchlist tickers
        priority = []
        for r in data_context.get("holdings_reports", []):
            chg = abs(r.get("change_pct") or 0)
            if chg >= 2.0:
                priority.append(r.get("ticker", ""))
        # Add all holding tickers as lower priority (up to 6 total)
        for t in tickers:
            if t not in priority and len(priority) < 6:
                priority.append(t)
        deep_research_tickers = priority[:6]

    try:
        parallel_tasks = []

        # Deep research analyst
        if deep_research_tickers:
            deep_analyst = DeepResearchAnalyst()
            deep_task = asyncio.to_thread(
                deep_analyst.analyze,
                deep_research_tickers, data_context,
                growth_result, value_result, risk_result,
                news_context, reddit_context, substack_context,
                earnings_context, superinvestor_context,
            )
            parallel_tasks.append(("deep_research", deep_task))

        # Causal reasoning
        if not _causal_ctx:
            try:
                from src.advisor.causal_reasoner import CausalReasoner, format_causal_for_prompt
                reasoner = CausalReasoner()
                analyst_reports = {
                    "growth": growth_result.get("analyses", {}),
                    "value": value_result.get("analyses", {}),
                }
                holdings_data = data_context.get("holdings_reports", [])
                causal_task = reasoner.analyze(
                    top_tickers=tickers[:5],
                    analyst_reports=analyst_reports,
                    holdings_data=holdings_data,
                    macro_context=macro_context,
                    calibration_context=calibration_context,
                )
                parallel_tasks.append(("causal", causal_task))
            except ImportError:
                log.debug("Causal reasoner not available")

        # Gap resolution
        if not _supplementary_ctx:
            try:
                from src.advisor.gap_resolver import (
                    GapResolver, parse_gaps_from_analyst_output,
                    format_supplementary_research,
                )
                all_gaps = []
                for analyst_output in (growth_result, value_result, risk_result):
                    all_gaps.extend(parse_gaps_from_analyst_output(analyst_output))
                if all_gaps:
                    resolver = GapResolver()
                    gap_task = resolver.resolve_gaps(all_gaps[:5], data_context)
                    parallel_tasks.append(("gap", gap_task))
            except ImportError:
                log.debug("Gap resolver not available")

        # Run all stage 3.5 tasks in parallel
        if parallel_tasks:
            results = await asyncio.gather(
                *[t[1] for t in parallel_tasks],
                return_exceptions=True,
            )
            for (name, _), result_val in zip(parallel_tasks, results):
                if isinstance(result_val, Exception):
                    log.warning("Stage 3.5 %s failed: %s", name, result_val)
                    continue
                if name == "deep_research":
                    deep_research_result = result_val
                    block_count = len(result_val.get("blocks", {}))
                    log.info("Deep research: %d blocks produced", block_count)
                elif name == "causal" and not _causal_ctx:
                    _causal_ctx = format_causal_for_prompt(result_val)
                    log.info("Causal analysis: %d chars", len(_causal_ctx))
                elif name == "gap" and not _supplementary_ctx:
                    _supplementary_ctx = format_supplementary_research(result_val)
                    log.info("Gap resolution: %d chars", len(_supplementary_ctx))

    except Exception:
        log.exception("Stage 3.5 (deep research/causal/gap) failed — continuing without")

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
        news_context=news_context,
        reddit_context=reddit_context,
        substack_context=substack_context,
        calibration_context=calibration_context,
        preference_context=preference_context,
        causal_context=_causal_ctx,
        supplementary_research=_supplementary_ctx,
    )

    # Attach deep research to result
    result["deep_research"] = deep_research_result

    log.info("Committee complete. Brief length: %d chars, deep research blocks: %d",
             len(result.get("formatted_brief", "")),
             len(deep_research_result.get("blocks", {})))

    return result
