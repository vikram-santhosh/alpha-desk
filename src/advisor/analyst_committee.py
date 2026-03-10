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
                superinvestor_context: str = "",
                config: dict | None = None) -> dict:
        """Produce deep research blocks for priority tickers."""
        within_budget, _, _ = check_budget()
        if not within_budget:
            return {"error": "budget_exceeded", "blocks": {}}

        if not priority_tickers:
            return {"blocks": {}}

        # ── Tier tickers into deep vs summary ──
        _cfg = config or {}
        committee_cfg = _cfg.get("committee", {})
        full_max = committee_cfg.get("deep_research_full_max", 3)
        max_position_pct = _cfg.get("strategy", {}).get("max_position_pct", 15)

        report_map = {r.get("ticker"): r for r in data_context.get("holdings_reports", [])}
        sorted_tickers = sorted(
            priority_tickers,
            key=lambda t: abs(report_map.get(t, {}).get("change_pct") or 0),
            reverse=True,
        )
        deep_tickers = sorted_tickers[:full_max]
        summary_tickers = sorted_tickers[full_max:]

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

        # Build mandate breach alerts
        breach_alerts = []
        for t in priority_tickers:
            pct = report_map.get(t, {}).get("position_pct")
            if pct is not None and pct > max_position_pct:
                breach_alerts.append(f"MANDATE BREACH: {t} at {pct:.1f}% vs {max_position_pct}% limit — trimming is not optional.")
        breach_section = "\n".join(breach_alerts) if breach_alerts else ""

        # Build summary ticker list for prompt
        summary_list = f"\nSUMMARY tickers (brief only): {', '.join(summary_tickers)}" if summary_tickers else ""

        prompt = f"""You are a lead buy-side research analyst at a concentrated long-only fund.
Your job is to convert raw signals into decision-useful equity research for the portfolio manager.
You are writing for a smart, busy PM who reads hundreds of these. Be sharp, be direct, take positions.

{breach_section}

STOCK DATA AND ANALYST VIEWS:
{context}

SIGNAL INTELLIGENCE:
{signal_section}

You must produce research for ALL of these tickers, but at DIFFERENT depths:

DEEP RESEARCH tickers (full prose): {', '.join(deep_tickers)}{summary_list}

═══════════════════════════════════════
DEEP RESEARCH FORMAT (for {', '.join(deep_tickers)})
═══════════════════════════════════════

For each deep ticker, write a PROSE-STYLE analyst note. NOT a templated form. Use this header:

## {{TICKER}} — Deep Research Block

Then write these 4 sections as flowing narrative:

### The Key Question
One sentence framing the central question for this name RIGHT NOW. Examples:
- "Is VRT's 8.5% rally on a down day the start of a 'safe haven AI' rotation, or a one-day anomaly?"
- "Can AWS maintain enterprise trust after physical attacks on its data centers?"

### What We Know
3-5 paragraphs of INTERPRETIVE NARRATIVE — not bullet dumps. Connect the dots between signals.
Cover: what changed today, what the signals mean for the thesis, what the market is pricing in,
and how this name relates to the rest of the portfolio.

Use comparisons and analogies: "VRT is trading like a defense stock today, not a tech stock" is
10x more useful than "VRT outperformed the broader market."

Weave in the Growth Analyst and Value Analyst perspectives where they add insight. Don't just
repeat their scores — tell the reader what the TENSION between them means.

If a holding has a mandate breach (position > {max_position_pct}%), this MUST be the first thing discussed.

### What We Could Be Wrong About
1-2 paragraphs on the strongest counterargument. Be specific:
- "If hyperscaler CapEx guidance is cut >15% in Q2 calls, VRT's growth story collapses"
NOT: "There are risks to the thesis"

### Action & Catalysts
- Stance: {{Add / Hold / Trim / Avoid}} (ONE word, no slashes like "Hold / Trim")
- 2-3 sentences on WHY this stance, WHY NOW (not generic "monitor the situation")
- Next 2-3 catalysts with approximate dates
- 1-2 key unresolved questions

═══════════════════════════════════════
SUMMARY FORMAT (for {', '.join(summary_tickers) if summary_tickers else 'none'})
═══════════════════════════════════════

For each summary ticker, write a COMPACT take. Use this header:

## {{TICKER}} — Summary

Then 3-5 sentences covering: what happened, thesis impact, and your stance.
End with: Stance: {{Add/Hold/Trim/Avoid}}

═══════════════════════════════════════
WRITING RULES (apply to ALL tickers)
═══════════════════════════════════════

TOKEN ALLOCATION:
- Allocate ~1200-1500 words per deep ticker
- Allocate ~60-100 words per summary ticker
- Go DEEP on {', '.join(deep_tickers)}, be BRIEF on the rest

CROSS-STOCK READ-THROUGHS:
When a signal on one company affects others, explicitly state:
"Read-through to [ticker]: [impact]"

ANTI-HEDGING RULES:
- Pick a stance. "Hold" is fine. "Hold / Trim" is not.
- Never write "mildly bearish" or "medium confidence" — either you're bearish or you're not.
- Replace "consider trimming" with "trim." Replace "monitor closely" with what you'd actually watch for.
- Never start a sentence with "It's worth noting" or "Investors should be aware."

ANTI-SHALLOW RULES:
- Do NOT merely restate headlines — interpret them
- Do NOT say "thesis intact" without citing specific evidence
- Do NOT give generic commentary like "AI demand remains strong" unless tied to a concrete data point
- Do NOT repeat the same headline across tickers without tailoring the interpretation

STYLE:
Write like a sharp buy-side analyst talking to a PM over coffee: direct, opinionated, evidence-based.
Good: "This is the day the market decided VRT is a defense stock, not a tech stock. That matters because..."
Bad: "VRT showed significant outperformance relative to the broader market, potentially indicating..."

Respond with the research blocks as structured text (not JSON)."""

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
            blocks = self._parse_blocks(text, priority_tickers, deep_tickers)
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

    def _parse_blocks(self, text: str, tickers: list[str],
                      deep_tickers: list[str] | None = None) -> dict[str, dict]:
        """Parse the raw text into per-ticker blocks with tier info.

        Returns dict of ticker -> {"content": str, "tier": "full"|"summary"}.
        """
        import re
        blocks: dict[str, dict] = {}
        _deep = set(t.upper() for t in (deep_tickers or []))

        # Try splitting on ## TICKER — Deep Research Block or ## TICKER — Summary
        parts = re.split(r'\n##\s+(\w+)\s*[—–\-]\s*(?:Deep Research Block|Summary)', text)
        if len(parts) > 1:
            for i in range(1, len(parts), 2):
                ticker = parts[i].strip().upper()
                content = parts[i + 1].strip() if i + 1 < len(parts) else ""
                tier = "full" if ticker in _deep else "summary"
                blocks[ticker] = {"content": content, "tier": tier}
        else:
            # Fallback: try to find each ticker's block
            for t in tickers:
                pattern = rf'(?:##\s*)?{re.escape(t)}\b.*?(?=(?:##\s*\w+|$))'
                match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
                if match:
                    content = match.group(0).strip()
                    tier = "full" if t.upper() in _deep else "summary"
                    blocks[t] = {"content": content, "tier": tier}
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
        mandate_breach_ctx: str = "",
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

        # Build mandate breach header for prompt
        _breach_header = ""
        if mandate_breach_ctx:
            _breach_header = f"""
╔══════════════════════════════════════════════════╗
  MANDATE BREACHES — MUST ADDRESS IN EXECUTIVE TAKE
{mandate_breach_ctx}
╚══════════════════════════════════════════════════╝

"""

        prompt = f"""You are the Chief Investment Officer writing the daily brief for a concentrated AI/tech portfolio. You have reports from your Growth Analyst, Value Analyst, and Risk Officer, plus raw signal intelligence.

{_breach_header}GROWTH ANALYST REPORT:
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
3-4 sentences MAXIMUM. This is the most important part of the brief. Structure:
(1) LEAD with any MANDATE BREACHES. If a position exceeds its max weight, say so plainly: "META is at 25% of portfolio, breaching our 15% cap — we trim this week."
(2) State the single most important development today and why it matters for THIS portfolio specifically.
(3) State what we are doing about it — a specific action ("trim META to 15%") or an explicit non-action ("no changes warranted because X").
Do NOT hedge. "Trim META" not "consider trimming." "Do nothing" not "monitor the situation."

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
- Cite specific numbers and specific headlines.
- Separate sections with blank lines. Use bullet points within sections.

TONE:
- Write like a CIO dictating to a PA, not like a compliance report.
- Use "we" not "the portfolio." Use "trim" not "consider trimming."
- If all three analysts agree on a name, say "high conviction across all desks" and move on — don't repeat their reasoning.
- Cut any sentence that starts with "It's worth noting" or "Investors should be aware."
- Be direct. Be opinionated. Be brief."""

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
    config: dict | None = None,
    mandate_breach_ctx: str = "",
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
                config,
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
        mandate_breach_ctx=mandate_breach_ctx,
    )

    # Attach deep research to result
    result["deep_research"] = deep_research_result

    log.info("Committee complete. Brief length: %d chars, deep research blocks: %d",
             len(result.get("formatted_brief", "")),
             len(deep_research_result.get("blocks", {})))

    return result
