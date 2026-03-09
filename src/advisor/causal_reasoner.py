"""Causal Reasoner for AlphaDesk Advisor.

Sits between the analyst committee and CIO synthesis. Decomposes bull/bear
theses into ordered assumption chains with confidence levels, traces
second-order effects, and builds scenario matrices.

This is the deepest reasoning step in the pipeline — the one place we justify
Pro-tier cost. It enables reasoning like:

    "scaling limits reached -> $100B capex may be malinvestment
     -> bearish for AI infra stack"

Architecture:
    - Single Pro LLM call with all top tickers batched together.
    - Budget-gated: skipped entirely if daily cap is exceeded.
    - Output is structured JSON consumed by the CIO editor synthesis.
"""

import asyncio
import json
from typing import Any

from src.shared import gemini_compat as anthropic
from src.shared.cost_tracker import check_budget, record_usage
from src.utils.logger import get_logger

log = get_logger(__name__)

AGENT_NAME = "causal_reasoner"
MODEL = "claude-opus-4-6"

# ═══════════════════════════════════════════════════════════════════════════════
# System prompt — injected once per call
# ═══════════════════════════════════════════════════════════════════════════════

SYSTEM_PROMPT = """You are a senior investment strategist specializing in causal chain analysis. \
Your job is to decompose investment theses into falsifiable assumption chains \
and trace second-order effects.

For each thesis, you must:
1. Identify the 3-5 key assumptions in dependency order (each assumption depends on previous ones)
2. Assign honest confidence percentages (don't cluster everything at 70-80%)
3. Specify what happens if each assumption is wrong
4. Trace second-order effects that most analysts miss
5. Build bull/base/bear scenarios with probabilities that sum to ~100%

Be contrarian and intellectually honest. If the conventional wisdom is \
"AI will keep growing," challenge it with specific mechanisms that could \
break the thesis."""


# ═══════════════════════════════════════════════════════════════════════════════
# CausalReasoner
# ═══════════════════════════════════════════════════════════════════════════════

class CausalReasoner:
    """Decomposes investment theses into causal chains with confidence levels."""

    def __init__(self):
        self.client = anthropic.Anthropic()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def analyze(
        self,
        top_tickers: list[str],
        analyst_reports: dict,         # {analyst_name: {ticker: report_text}}
        holdings_data: list[dict],     # from holdings_reports
        macro_context: str,            # macro theses summary
        calibration_context: str = "", # from reasoning_journal
    ) -> dict[str, Any]:
        """Run causal analysis on top 5 tickers.

        Returns:
            {
                "analyses": {
                    "NVDA": {
                        "assumption_chain": [...],
                        "second_order_effects": [...],
                        "scenarios": {"bull": {...}, "base": {...}, "bear": {...}},
                        "thesis_confidence": 72,
                        "key_risk": "..."
                    },
                    ...
                },
                "cross_portfolio_risks": [...],
                "model_used": "claude-opus-4-6",
                "cost_usd": 0.0
            }
        """
        # Budget gate — skip entirely if over cap
        within_budget, spent, cap = check_budget()
        if not within_budget:
            log.warning(
                "Causal reasoner skipped — budget exceeded ($%.2f / $%.2f)",
                spent, cap,
            )
            return self._empty_result()

        # Select top 5 tickers by portfolio weight + conviction
        selected = self._select_top_tickers(top_tickers, holdings_data)
        if not selected:
            log.warning("Causal reasoner: no tickers to analyze")
            return self._empty_result()

        log.info("Causal reasoner: analyzing %d tickers: %s", len(selected), selected)

        # Build the user prompt
        user_prompt = self._build_user_prompt(
            selected, analyst_reports, holdings_data, macro_context, calibration_context,
        )

        # LLM call (sync client, wrapped with asyncio.to_thread)
        try:
            result, cost = await asyncio.to_thread(
                self._call_llm, user_prompt,
            )
            result["model_used"] = MODEL
            result["cost_usd"] = round(cost, 4)
            log.info(
                "Causal reasoner complete: %d ticker analyses, %d cross-portfolio risks, $%.4f",
                len(result.get("analyses", {})),
                len(result.get("cross_portfolio_risks", [])),
                cost,
            )
            return result

        except Exception:
            log.exception("Causal reasoner failed — returning empty result")
            return self._empty_result()

    # ------------------------------------------------------------------
    # Ticker selection
    # ------------------------------------------------------------------

    def _select_top_tickers(
        self, top_tickers: list[str], holdings_data: list[dict],
    ) -> list[str]:
        """Pick up to 5 tickers ranked by portfolio weight + conviction.

        If top_tickers is already curated, just cap at 5. Otherwise rank
        from holdings_data by position_pct descending.
        """
        if top_tickers:
            return top_tickers[:5]

        # Fallback: rank by portfolio weight
        ranked = sorted(
            holdings_data,
            key=lambda h: (h.get("position_pct") or h.get("portfolio_pct") or 0),
            reverse=True,
        )
        return [h["ticker"] for h in ranked[:5] if h.get("ticker")]

    # ------------------------------------------------------------------
    # Prompt construction
    # ------------------------------------------------------------------

    def _build_user_prompt(
        self,
        tickers: list[str],
        analyst_reports: dict,
        holdings_data: list[dict],
        macro_context: str,
        calibration_context: str,
    ) -> str:
        """Assemble the user prompt with all context."""
        sections: list[str] = []

        # --- Holdings snapshot ---
        sections.append("## PORTFOLIO HOLDINGS")
        report_map = {r.get("ticker"): r for r in holdings_data}
        for t in tickers:
            r = report_map.get(t, {})
            price = r.get("price", "N/A")
            chg = r.get("change_pct")
            chg_str = f" ({chg:+.1f}%)" if chg is not None else ""
            pct = r.get("position_pct") or r.get("portfolio_pct")
            pct_str = f" | {pct:.1f}% of portfolio" if pct is not None else ""
            sector = r.get("sector", "")
            thesis_status = r.get("thesis_status", r.get("thesis", ""))
            entry = r.get("entry_price")
            entry_str = f" | entry ${entry}" if entry else ""

            line = f"- {t}: ${price}{chg_str}{pct_str}{entry_str} | {sector}"
            if thesis_status:
                thesis_text = thesis_status if isinstance(thesis_status, str) else str(thesis_status)
                line += f"\n  Thesis: {thesis_text[:200]}"

            # Key events
            key_events = r.get("key_events", [])
            for evt in key_events[:2]:
                headline = evt.get("headline", evt) if isinstance(evt, dict) else str(evt)
                line += f"\n  Event: {headline}"

            sections.append(line)

        # --- Analyst reports ---
        sections.append("\n## ANALYST COMMITTEE REPORTS")
        for analyst_name, ticker_reports in analyst_reports.items():
            sections.append(f"\n### {analyst_name.upper()}")
            if isinstance(ticker_reports, dict):
                # Could be {ticker: report_text} or a full report dict with "analyses" key
                analyses = ticker_reports.get("analyses", ticker_reports)
                for ticker_key, report_content in analyses.items():
                    if ticker_key not in tickers:
                        continue
                    if isinstance(report_content, dict):
                        # Serialize the dict, truncating long values
                        content_str = json.dumps(report_content, indent=1)
                        sections.append(f"{ticker_key}: {content_str[:500]}")
                    else:
                        sections.append(f"{ticker_key}: {str(report_content)[:500]}")
            elif isinstance(ticker_reports, str):
                sections.append(ticker_reports[:1500])

        # --- Macro context ---
        if macro_context:
            sections.append(f"\n## MACRO CONTEXT\n{macro_context[:1500]}")

        # --- Calibration context ---
        if calibration_context:
            sections.append(f"\n## CALIBRATION DATA\n{calibration_context[:1000]}")

        # --- Output schema ---
        sections.append(self._output_schema(tickers))

        return "\n".join(sections)

    def _output_schema(self, tickers: list[str]) -> str:
        """Append the expected JSON output schema to the prompt."""
        ticker_example = tickers[0] if tickers else "TICKER"
        return f"""
## YOUR TASK

Analyze the holdings above. Respond with ONLY valid JSON matching this schema:

{{
  "analyses": {{
    "{ticker_example}": {{
      "assumption_chain": [
        {{
          "assumption": "Key assumption in plain English",
          "confidence_pct": 70,
          "depends_on": "What this assumption rests on",
          "if_wrong": "Specific consequence if this assumption fails"
        }}
      ],
      "second_order_effects": [
        "If X happens, Y follows 2-3 quarters later"
      ],
      "scenarios": {{
        "bull": {{"probability": 35, "impact": "+20-30%", "catalyst": "Specific catalyst"}},
        "base": {{"probability": 45, "impact": "-5% to +10%", "catalyst": "What maintains status quo"}},
        "bear": {{"probability": 20, "impact": "-15-25%", "catalyst": "Specific negative catalyst"}}
      }},
      "thesis_confidence": 72,
      "key_risk": "Single biggest risk to the thesis"
    }}
  }},
  "cross_portfolio_risks": [
    "Portfolio-level risk that affects multiple holdings"
  ]
}}

RULES:
- Provide analysis for EACH of these tickers: {', '.join(tickers)}
- assumption_chain must have 3-5 assumptions in DEPENDENCY ORDER
- confidence_pct should vary meaningfully — NOT everything at 70-80%
- Scenario probabilities must sum to approximately 100% for each ticker
- second_order_effects should trace cross-holding impacts (e.g., if NVDA capex slows, which other holdings are affected?)
- cross_portfolio_risks should identify correlated exposures across the portfolio
- Be specific: "Fed raises 50bp" not "rates go up"; "$100B capex proves malinvestment" not "spending risk"
- thesis_confidence is your overall confidence in the current thesis (0-100)
"""

    # ------------------------------------------------------------------
    # LLM call
    # ------------------------------------------------------------------

    def _call_llm(self, user_prompt: str) -> tuple[dict, float]:
        """Make the synchronous LLM call and parse the response.

        Returns:
            (parsed_result_dict, cost_usd)
        """
        response = self.client.messages.create(
            model=MODEL,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )

        usage = response.usage
        cost = record_usage(
            AGENT_NAME, usage.input_tokens, usage.output_tokens, model=MODEL,
        )
        log.info(
            "Causal reasoner LLM: %d in, %d out, $%.4f",
            usage.input_tokens, usage.output_tokens, cost,
        )

        # Parse JSON from response
        text = response.content[0].text.strip()
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()

        try:
            result = json.loads(text)
        except json.JSONDecodeError:
            log.warning("Causal reasoner returned invalid JSON — attempting repair")
            result = self._attempt_json_repair(text)

        # Validate structure
        if "analyses" not in result:
            result = {"analyses": result}
        if "cross_portfolio_risks" not in result:
            result["cross_portfolio_risks"] = []

        return result, cost

    def _attempt_json_repair(self, text: str) -> dict:
        """Try common JSON repair strategies for truncated output.

        If the LLM output was cut off mid-JSON, we try to close open
        braces/brackets and parse again.
        """
        # Strategy 1: truncated — close open braces
        repaired = text.rstrip()
        open_braces = repaired.count("{") - repaired.count("}")
        open_brackets = repaired.count("[") - repaired.count("]")

        if open_braces > 0 or open_brackets > 0:
            # Remove trailing comma if present
            repaired = repaired.rstrip(",").rstrip()
            repaired += "]" * max(0, open_brackets)
            repaired += "}" * max(0, open_braces)

            try:
                return json.loads(repaired)
            except json.JSONDecodeError:
                pass

        # Strategy 2: find the last valid JSON object boundary
        last_brace = text.rfind("}")
        if last_brace > 0:
            candidate = text[: last_brace + 1]
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                pass

        log.error("JSON repair failed — returning empty analyses")
        return {"analyses": {}, "cross_portfolio_risks": []}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _empty_result(self) -> dict[str, Any]:
        """Return a well-formed empty result dict."""
        return {
            "analyses": {},
            "cross_portfolio_risks": [],
            "model_used": MODEL,
            "cost_usd": 0.0,
        }


# ═══════════════════════════════════════════════════════════════════════════════
# Formatting helper for CIO prompt injection
# ═══════════════════════════════════════════════════════════════════════════════

def format_causal_for_prompt(analysis: dict) -> str:
    """Format causal analysis output into a text block for the CIO prompt.

    Produces a concise, readable summary that the CIO editor can reference
    during synthesis. Returns empty string if analysis is empty.

    Args:
        analysis: The full dict returned by CausalReasoner.analyze().

    Returns:
        Formatted text block suitable for prompt injection, or "".
    """
    analyses = analysis.get("analyses", {})
    cross_risks = analysis.get("cross_portfolio_risks", [])

    if not analyses and not cross_risks:
        return ""

    lines: list[str] = ["## CAUSAL CHAIN ANALYSIS"]

    # Per-ticker summaries
    for ticker, data in analyses.items():
        lines.append(f"\n### {ticker} (thesis confidence: {data.get('thesis_confidence', 'N/A')}%)")

        # Assumption chain — compact format
        chain = data.get("assumption_chain", [])
        if chain:
            lines.append("Assumption chain:")
            for i, link in enumerate(chain, 1):
                assumption = link.get("assumption", "")
                conf = link.get("confidence_pct", "?")
                depends = link.get("depends_on", "")
                if_wrong = link.get("if_wrong", "")
                lines.append(f"  {i}. [{conf}%] {assumption}")
                if depends:
                    lines.append(f"     Depends on: {depends}")
                if if_wrong:
                    lines.append(f"     If wrong: {if_wrong}")

        # Second-order effects
        effects = data.get("second_order_effects", [])
        if effects:
            lines.append("Second-order effects:")
            for effect in effects:
                lines.append(f"  - {effect}")

        # Scenarios — one-line each
        scenarios = data.get("scenarios", {})
        if scenarios:
            lines.append("Scenarios:")
            for label in ("bull", "base", "bear"):
                s = scenarios.get(label, {})
                if s:
                    prob = s.get("probability", "?")
                    impact = s.get("impact", "?")
                    catalyst = s.get("catalyst", "")
                    lines.append(f"  {label.upper()}: {prob}% prob, {impact} — {catalyst}")

        # Key risk
        key_risk = data.get("key_risk", "")
        if key_risk:
            lines.append(f"KEY RISK: {key_risk}")

    # Cross-portfolio risks
    if cross_risks:
        lines.append("\n### CROSS-PORTFOLIO RISKS")
        for risk in cross_risks:
            lines.append(f"  - {risk}")

    return "\n".join(lines)
