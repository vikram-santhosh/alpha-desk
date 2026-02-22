"""Skeptic Agent — adversarial analysis for AlphaDesk Advisor v2.

Challenges every recommendation by finding flaws, assessing what's priced in,
providing base rate reasoning, and generating specific invalidation conditions.
Uses Claude Opus for high-quality contrarian analysis.
"""

import json
from typing import Any

import anthropic

from src.shared.cost_tracker import check_budget, record_usage
from src.utils.logger import get_logger

log = get_logger(__name__)

AGENT_NAME = "advisor_skeptic"
MODEL = "claude-opus-4-6"


class SkepticAgent:
    """Adversarial analysis agent that challenges every recommendation.

    For each recommendation, the Skeptic:
    1. Identifies the strongest bear case
    2. Assesses what's already priced in
    3. Provides base rate for this type of thesis
    4. Lists specific invalidation conditions
    5. Assigns a confidence modifier (0.5 = very skeptical, 1.0 = neutral, 1.2 = agrees)
    """

    def __init__(self):
        self._client = anthropic.Anthropic()

    def challenge_recommendation(
        self, recommendation: dict, market_context: dict | None = None,
    ) -> dict:
        """Challenge a single recommendation with adversarial analysis.

        Args:
            recommendation: Dict with ticker, action, conviction, thesis, evidence, valuation.
            market_context: Optional macro context (VIX, yields, sector P/E, etc.).

        Returns:
            Dict with: primary_risk, secondary_risks, whats_priced_in, base_rate,
            evidence_weaknesses, invalidation_conditions, confidence_modifier, one_line_verdict.
        """
        within_budget, spent, cap = check_budget()
        if not within_budget:
            log.warning("Budget exceeded — using template skeptic for %s", recommendation.get("ticker"))
            return self._template_challenge(recommendation)

        ticker = recommendation.get("ticker", "???")
        action = recommendation.get("action", "WATCH")
        conviction = recommendation.get("conviction_level", recommendation.get("conviction", "medium"))

        # Build thesis context
        thesis = recommendation.get("thesis", {})
        thesis_text = thesis.get("core_argument", "") if isinstance(thesis, dict) else str(thesis)

        # Build evidence context
        evidence_items = thesis.get("supporting_evidence", []) if isinstance(thesis, dict) else []
        evidence_text = ""
        if evidence_items:
            for e in evidence_items:
                if isinstance(e, dict):
                    evidence_text += f"- [{e.get('source', 'unknown')}] {e.get('claim', '')} (weight: {e.get('base_weight', 0)}, age: {e.get('recency_days', 0)}d)\n"

        # Build valuation context
        val = recommendation.get("valuation", {})
        current_price = val.get("current_price", "N/A")
        target_price = val.get("target_price", "N/A")
        cagr = val.get("implied_cagr", "N/A")

        # Build market context
        mc = market_context or {}
        sp500_pe = mc.get("sp500_pe", "N/A")
        vix = mc.get("vix", "N/A")
        yield_10y = mc.get("treasury_10y", "N/A")

        prompt = f"""You are a skeptical, contrarian senior portfolio manager whose job is to find flaws in investment recommendations. You are NOT trying to be balanced — your job is to be the strongest possible devil's advocate. You get paid when you correctly identify recommendations that will lose money.

You are reviewing this recommendation:

TICKER: {ticker}
ACTION: {action}
CONVICTION: {conviction}
THESIS: {thesis_text}
EVIDENCE:
{evidence_text or 'No structured evidence provided'}
VALUATION:
Current price: {current_price}, Target: {target_price}, Implied CAGR: {cagr}
MARKET CONTEXT:
- VIX: {vix}
- 10Y Yield: {yield_10y}

YOUR TASK — respond with ONLY valid JSON, no markdown:

{{
  "primary_risk": "The single biggest reason this recommendation could fail. Be specific — name the mechanism, not vague 'macro risk'.",
  "secondary_risks": [
    "Risk 2 — specific mechanism",
    "Risk 3"
  ],
  "whats_priced_in": "What does the current stock price already reflect? If trading at a high multiple, what growth is implied?",
  "base_rate": "For recommendations with similar characteristics, what is the historical success rate?",
  "evidence_weaknesses": [
    "Specific weakness in evidence"
  ],
  "invalidation_conditions": [
    {{
      "condition": "Specific, testable condition that would prove the thesis wrong",
      "monitoring": "How and when to check for this",
      "action_if_triggered": "What to do if this happens"
    }}
  ],
  "confidence_modifier": 0.85,
  "one_line_verdict": "One sentence verdict"
}}

RULES:
- Do NOT be generically negative. Cite specific risks with specific mechanisms.
- "Macro risk" and "competition" are not acceptable without specifics.
- confidence_modifier < 0.7 should be rare — only when you find a genuine flaw.
- confidence_modifier > 1.0 should also be rare — only when evidence is overwhelmingly strong."""

        try:
            response = self._client.messages.create(
                model=MODEL,
                max_tokens=1000,
                messages=[{"role": "user", "content": prompt}],
            )
            usage = response.usage
            record_usage(AGENT_NAME, usage.input_tokens, usage.output_tokens, model=MODEL)
            log.info("Skeptic challenge for %s: %d in, %d out", ticker, usage.input_tokens, usage.output_tokens)

            text = response.content[0].text.strip()
            # Parse JSON
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()

            result = json.loads(text)
            return result

        except json.JSONDecodeError:
            log.error("Skeptic returned invalid JSON for %s", ticker)
            return self._template_challenge(recommendation)
        except Exception:
            log.exception("Skeptic challenge failed for %s", ticker)
            return self._template_challenge(recommendation)

    def challenge_trim_recommendation(
        self, holding: dict, trim_reason: str, market_context: dict | None = None,
    ) -> dict:
        """Challenge a TRIM recommendation — argue why we should NOT trim.

        Returns dict with: reasons_to_hold, trim_confidence_modifier, one_line_verdict.
        """
        within_budget, spent, cap = check_budget()
        if not within_budget:
            return {"reasons_to_hold": ["Budget exceeded — no skeptic review"], "trim_confidence_modifier": 1.0, "one_line_verdict": "No review available."}

        ticker = holding.get("ticker", "???")
        thesis = holding.get("thesis", "")

        prompt = f"""You are a contrarian portfolio manager. Your colleague wants to TRIM {ticker}. Your job is to argue AGAINST the trim — find reasons to HOLD.

TICKER: {ticker}
THESIS: {thesis}
TRIM REASON: {trim_reason}

Respond with ONLY valid JSON:
{{
  "reasons_to_hold": ["Reason 1 to keep holding", "Reason 2"],
  "trim_confidence_modifier": 0.85,
  "one_line_verdict": "Should we trim or hold?"
}}

confidence_modifier: 0.5 = "definitely do NOT trim", 1.0 = "trim is probably right", 1.2 = "trim is definitely right"
"""

        try:
            response = self._client.messages.create(
                model=MODEL,
                max_tokens=500,
                messages=[{"role": "user", "content": prompt}],
            )
            usage = response.usage
            record_usage(AGENT_NAME, usage.input_tokens, usage.output_tokens, model=MODEL)

            text = response.content[0].text.strip()
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()
            return json.loads(text)

        except Exception:
            log.exception("Skeptic trim challenge failed for %s", ticker)
            return {"reasons_to_hold": ["Skeptic review unavailable"], "trim_confidence_modifier": 1.0, "one_line_verdict": "No review available."}

    def batch_challenge(
        self, recommendations: list[dict], market_context: dict | None = None,
    ) -> list[dict]:
        """Challenge multiple recommendations. Runs them individually (no batch LLM call)."""
        results = []
        for rec in recommendations[:5]:  # Cap at 5 to control cost
            result = self.challenge_recommendation(rec, market_context)
            results.append(result)
        return results

    def _template_challenge(self, recommendation: dict) -> dict:
        """Fallback: template-based challenge when LLM is unavailable."""
        ticker = recommendation.get("ticker", "???")
        val = recommendation.get("valuation", {})
        pe = val.get("pe_trailing")

        primary_risk = f"Consensus positioning — {ticker} may already reflect bullish thesis in current price."
        if pe and pe > 50:
            primary_risk = f"Valuation risk — {ticker} trades at {pe}x earnings, requiring sustained growth to justify."

        return {
            "primary_risk": primary_risk,
            "secondary_risks": [
                "Macro sensitivity — rate-sensitive growth stock",
                "Competitive threats in core market",
            ],
            "whats_priced_in": "Market expects continued outperformance based on current multiple.",
            "base_rate": "Most stock picks underperform the index over 12 months (~60% of active picks).",
            "evidence_weaknesses": ["Limited evidence depth — template review only"],
            "invalidation_conditions": [
                {
                    "condition": f"{ticker} drops 20% from current levels",
                    "monitoring": "Daily price check",
                    "action_if_triggered": "Review thesis, consider exit",
                },
            ],
            "confidence_modifier": 0.9,
            "one_line_verdict": f"Proceed with caution — {ticker} needs more evidence depth.",
        }


def apply_skeptic_to_recommendation(
    recommendation: dict, skeptic_result: dict,
) -> dict:
    """Apply skeptic results back to a recommendation dict.

    Updates bear_case, invalidation_conditions, and skeptic_confidence_modifier.
    """
    # Update bear case
    recommendation["bear_case"] = {
        "primary_risk": skeptic_result.get("primary_risk", ""),
        "secondary_risks": skeptic_result.get("secondary_risks", []),
        "base_rate": skeptic_result.get("base_rate", ""),
        "whats_priced_in": skeptic_result.get("whats_priced_in", ""),
        "skeptic_confidence": skeptic_result.get("confidence_modifier", 1.0),
    }

    # Update invalidation conditions
    skeptic_conditions = skeptic_result.get("invalidation_conditions", [])
    if skeptic_conditions:
        recommendation["invalidation_conditions"] = skeptic_conditions

    # Update skeptic confidence modifier
    if "analyst_scores" not in recommendation:
        recommendation["analyst_scores"] = {}
    recommendation["analyst_scores"]["skeptic_confidence_modifier"] = skeptic_result.get("confidence_modifier", 1.0)

    # Log downgrade/rejection
    modifier = skeptic_result.get("confidence_modifier", 1.0)
    ticker = recommendation.get("ticker", "")
    if modifier < 0.6:
        log.warning("Skeptic REJECTS %s: modifier=%.2f — %s", ticker, modifier, skeptic_result.get("one_line_verdict", ""))
    elif modifier < 0.7:
        log.warning("Skeptic strongly doubts %s: modifier=%.2f", ticker, modifier)
        # Downgrade conviction
        current = recommendation.get("conviction_level", recommendation.get("conviction", "medium"))
        if current == "high":
            recommendation["conviction_level"] = "medium"
            recommendation["conviction"] = "medium"
            log.info("Downgraded %s conviction: high → medium (skeptic modifier %.2f)", ticker, modifier)
        elif current == "medium":
            recommendation["conviction_level"] = "low"
            recommendation["conviction"] = "low"
            log.info("Downgraded %s conviction: medium → low (skeptic modifier %.2f)", ticker, modifier)

    return recommendation
