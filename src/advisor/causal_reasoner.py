"""Causal chain reasoning for AlphaDesk thesis validation."""
from __future__ import annotations

import asyncio
import json
from typing import Any

from src.shared import gemini_compat as anthropic
from src.shared.agent_decorator import track_agent
from src.shared.context_manager import ContextBudget
from src.shared.prompt_loader import load_prompt
from src.utils.logger import get_logger

log = get_logger(__name__)

AGENT_NAME = "causal_reasoner"
MODEL = "claude-opus-4-6"


def _call_model(prompt: str) -> dict[str, Any]:
    client = anthropic.Anthropic()
    response = client.messages.create(
        model=MODEL,
        max_tokens=2800,
        messages=[{"role": "user", "content": prompt}],
    )
    return {"text": response.content[0].text.strip(), "usage": response.usage, "model": MODEL}


class CausalReasoner:
    """Decomposes investment theses into causal chains with confidence levels."""

    async def analyze(
        self,
        top_tickers: list[str],
        analyst_reports: dict,
        holdings_data: list[dict],
        macro_context: str,
        calibration_context: str = "",
    ) -> dict[str, Any]:
        tickers = self._select_top_tickers(top_tickers, holdings_data)
        if not tickers:
            return self._empty_result()

        prompt = self._build_user_prompt(
            tickers=tickers,
            analyst_reports=analyst_reports,
            holdings_data=holdings_data,
            macro_context=macro_context,
            calibration_context=calibration_context,
        )
        runner = self._runner()
        result = await runner(prompt)
        if result.get("error"):
            log.warning("Causal reasoner failed: %s", result["error"])
            return self._empty_result()

        payload = result.get("data") or {}
        if "analyses" not in payload:
            payload = {"analyses": payload, "cross_portfolio_risks": []}
        payload.setdefault("cross_portfolio_risks", [])
        payload["model_used"] = result.get("model", MODEL)
        payload["cost_usd"] = result.get("cost_usd", 0.0)
        return payload

    def _runner(self):
        @track_agent(AGENT_NAME)
        async def _invoke(prompt: str) -> dict[str, Any]:
            return await asyncio.to_thread(_call_model, prompt)

        return _invoke

    def _select_top_tickers(self, top_tickers: list[str], holdings_data: list[dict]) -> list[str]:
        if top_tickers:
            return top_tickers[:5]
        ranked = sorted(
            holdings_data,
            key=lambda holding: (holding.get("position_pct") or holding.get("portfolio_pct") or 0),
            reverse=True,
        )
        return [holding.get("ticker", "") for holding in ranked[:5] if holding.get("ticker")]

    def _build_user_prompt(
        self,
        tickers: list[str],
        analyst_reports: dict,
        holdings_data: list[dict],
        macro_context: str,
        calibration_context: str,
    ) -> str:
        budget = ContextBudget(token_budget=10000)

        report_map = {holding.get("ticker"): holding for holding in holdings_data}
        holdings_lines = []
        for ticker in tickers:
            holding = report_map.get(ticker, {})
            line = (
                f"- {ticker}: price={holding.get('price', 'N/A')} change={holding.get('change_pct', 'N/A')} "
                f"position={holding.get('position_pct', holding.get('portfolio_pct', 'N/A'))} sector={holding.get('sector', '')}"
            )
            thesis = holding.get("thesis_status") or holding.get("thesis")
            if thesis:
                line += f" | thesis={thesis}"
            events = holding.get("key_events", [])
            if events:
                preview = "; ".join(
                    event.get("headline", event) if isinstance(event, dict) else str(event)
                    for event in events[:2]
                )
                line += f" | events={preview}"
            holdings_lines.append(line)
        budget.add_section("Holdings", "\n".join(holdings_lines), "holdings")

        analyst_lines = []
        for analyst_name, ticker_reports in analyst_reports.items():
            analyst_lines.append(f"[{analyst_name.upper()}]")
            analyses = ticker_reports.get("analyses", ticker_reports) if isinstance(ticker_reports, dict) else ticker_reports
            if isinstance(analyses, dict):
                for ticker, report in analyses.items():
                    if ticker not in tickers:
                        continue
                    analyst_lines.append(f"- {ticker}: {json.dumps(report, indent=1)}")
            elif analyses:
                analyst_lines.append(str(analyses))
        budget.add_section("Analyst Reports", "\n".join(analyst_lines), "analyst_reports")
        budget.add_section("Macro", macro_context, "news")
        budget.add_section("Calibration", calibration_context, "news")

        prompt = load_prompt(
            "causal_reasoner",
            tickers=", ".join(tickers),
            context=budget.render(),
            output_schema=self._output_schema(tickers),
        )
        return prompt

    def _output_schema(self, tickers: list[str]) -> str:
        ticker_example = tickers[0] if tickers else "TICKER"
        return f"""
{{
  \"analyses\": {{
    \"{ticker_example}\": {{
      \"assumption_chain\": [
        {{
          \"assumption\": \"Key assumption in plain English\",
          \"confidence_pct\": 70,
          \"depends_on\": \"What this assumption rests on\",
          \"if_wrong\": \"Specific consequence if this assumption fails\"
        }}
      ],
      \"second_order_effects\": [\"If X happens, Y follows 2-3 quarters later\"],
      \"scenarios\": {{
        \"bull\": {{\"probability\": 35, \"impact\": \"+20-30%\", \"catalyst\": \"Specific catalyst\"}},
        \"base\": {{\"probability\": 45, \"impact\": \"-5% to +10%\", \"catalyst\": \"Status quo catalyst\"}},
        \"bear\": {{\"probability\": 20, \"impact\": \"-15-25%\", \"catalyst\": \"Specific negative catalyst\"}}
      }},
      \"thesis_confidence\": 72,
      \"key_risk\": \"Single biggest risk to the thesis\"
    }}
  }},
  \"cross_portfolio_risks\": [\"Portfolio-level risk affecting multiple holdings\"]
}}
"""

    def _empty_result(self) -> dict[str, Any]:
        return {
            "analyses": {},
            "cross_portfolio_risks": [],
            "model_used": MODEL,
            "cost_usd": 0.0,
        }


def format_causal_for_prompt(analysis: dict) -> str:
    analyses = analysis.get("analyses", {})
    cross_risks = analysis.get("cross_portfolio_risks", [])

    if not analyses and not cross_risks:
        return ""

    lines: list[str] = ["## CAUSAL CHAIN ANALYSIS"]
    for ticker, data in analyses.items():
        lines.append(f"\n### {ticker} (thesis confidence: {data.get('thesis_confidence', 'N/A')}%)")
        chain = data.get("assumption_chain", [])
        if chain:
            lines.append("Assumption chain:")
            for idx, link in enumerate(chain, 1):
                lines.append(f"  {idx}. [{link.get('confidence_pct', '?')}%] {link.get('assumption', '')}")
                if link.get("depends_on"):
                    lines.append(f"     Depends on: {link['depends_on']}")
                if link.get("if_wrong"):
                    lines.append(f"     If wrong: {link['if_wrong']}")
        effects = data.get("second_order_effects", [])
        if effects:
            lines.append("Second-order effects:")
            for effect in effects:
                lines.append(f"  - {effect}")
        scenarios = data.get("scenarios", {})
        if scenarios:
            lines.append("Scenarios:")
            for label in ("bull", "base", "bear"):
                scenario = scenarios.get(label, {})
                if scenario:
                    lines.append(
                        f"  {label.upper()}: {scenario.get('probability', '?')}% prob, "
                        f"{scenario.get('impact', '?')} — {scenario.get('catalyst', '')}"
                    )
        if data.get("key_risk"):
            lines.append(f"KEY RISK: {data['key_risk']}")

    if cross_risks:
        lines.append("\n### CROSS-PORTFOLIO RISKS")
        for risk in cross_risks:
            lines.append(f"  - {risk}")

    return "\n".join(lines)
