"""Coherence auditor for AlphaDesk Advisor.

Runs after synthesis to detect contradictions between report sections.
For example: recommending moonshots when safety < 30, or marking theses
STABLE while the macro section flags headwinds to those same theses.

This is Phase 6 in the pipeline — a single Claude call that reviews
the full synthesized report and flags internal contradictions.
"""
from __future__ import annotations

import json
from datetime import date
from typing import Any

from src.shared import gemini_compat as anthropic

from src.shared.cost_tracker import check_budget, record_usage
from src.utils.logger import get_logger

log = get_logger(__name__)

AGENT_NAME = "coherence_auditor"
MODEL = "claude-sonnet-4-6"  # Sonnet is sufficient for coherence checking


def audit_coherence(
    brief_text: str,
    safety_score: int,
    exposure_gaps: list[dict],
    strategy_actions: list[dict],
    thesis_statuses: dict[str, str],
    macro_theses: list[dict],
) -> dict[str, Any]:
    """Audit a synthesized report for internal contradictions.

    Args:
        brief_text: The full synthesized report text.
        safety_score: Portfolio safety score (0-100).
        exposure_gaps: List of exposure gap dicts from exposure_analyzer.
        strategy_actions: List of action dicts from strategy_engine.
        thesis_statuses: Dict of ticker -> thesis_status.
        macro_theses: List of macro thesis dicts with status.

    Returns:
        Dict with:
            contradictions: List of contradiction dicts.
            revised_sections: Dict of section_name -> revised text (if any).
            coherence_score: 0-100 (higher = more coherent).
            audit_summary: One-line summary.
    """
    within_budget, spent, cap = check_budget()
    if not within_budget:
        log.warning("Budget exceeded — skipping coherence audit")
        return {
            "contradictions": [],
            "coherence_score": None,
            "audit_summary": "Skipped (budget exceeded)",
        }

    if not brief_text or len(brief_text) < 100:
        return {
            "contradictions": [],
            "coherence_score": 100,
            "audit_summary": "No report to audit.",
        }

    # Build structured context for the auditor
    context_parts: list[str] = []
    context_parts.append(f"PORTFOLIO SAFETY SCORE: {safety_score}/100")

    if exposure_gaps:
        zero_gaps = [g["sector"] for g in exposure_gaps if g.get("actual_pct", 0) == 0]
        if zero_gaps:
            context_parts.append(f"ZERO-EXPOSURE SECTORS: {', '.join(zero_gaps)}")

    if strategy_actions:
        action_lines = [
            f"  {a.get('action', '').upper()} {a.get('ticker', '')}: {a.get('reason', '')} [{a.get('urgency', 'low')}]"
            for a in strategy_actions
        ]
        context_parts.append("STRATEGY ACTIONS:\n" + "\n".join(action_lines))

    weakening = [
        f"{t}: {s}" for t, s in thesis_statuses.items()
        if s in ("weakening", "invalidated")
    ]
    if weakening:
        context_parts.append(f"STRESSED THESES: {'; '.join(weakening)}")

    macro_warnings = [
        f"{mt.get('title', '')}: {mt.get('status', 'intact')}"
        for mt in macro_theses
        if mt.get("status") in ("weakening", "invalidated")
    ]
    if macro_warnings:
        context_parts.append(f"MACRO HEADWINDS: {'; '.join(macro_warnings)}")

    structured_context = "\n".join(context_parts)

    prompt = f"""You are a coherence auditor for an investment report. Your job is to find INTERNAL CONTRADICTIONS between different sections of the same report.

TODAY: {date.today().strftime('%B %d, %Y')}

STRUCTURED CONTEXT (these are facts from the data pipeline):
{structured_context}

FULL REPORT:
{brief_text[:8000]}

TASK: Identify contradictions. Specifically check:
1. Do any recommendations (watchlist, moonshots, adds) contradict the risk assessment? (e.g., speculative picks when safety < 30)
2. Do any thesis ratings ("INTACT" or "STABLE") conflict with macro headwinds that affect those holdings?
3. Are watchlist/moonshot picks appropriate for the portfolio's current risk state?
4. Does the actions section actually address the problems identified in the risk section?
5. Are there exposure gaps (0% sectors) that the report fails to mention or address?

Respond with ONLY valid JSON:
{{
  "contradictions": [
    {{
      "sections": ["section A", "section B"],
      "description": "Brief description of the contradiction",
      "severity": "high" or "medium" or "low",
      "resolution": "How to fix it"
    }}
  ],
  "coherence_score": 0-100,
  "summary": "One sentence overall assessment"
}}

If there are NO contradictions, return an empty list and score 100. Be specific — cite tickers and numbers."""

    try:
        client = anthropic.Anthropic()
        response = client.messages.create(
            model=MODEL,
            max_tokens=1000,
            messages=[{"role": "user", "content": prompt}],
        )

        usage = response.usage
        record_usage(AGENT_NAME, usage.input_tokens, usage.output_tokens, model=MODEL, response=response)

        raw = response.content[0].text.strip()
        # Strip markdown code blocks if present
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
            if raw.endswith("```"):
                raw = raw[:-3]
            raw = raw.strip()

        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            log.warning("Failed to parse coherence audit JSON")
            return {
                "contradictions": [],
                "coherence_score": None,
                "audit_summary": "Parse error — audit inconclusive",
                "raw": raw,
            }

        contradictions = data.get("contradictions", [])
        coherence_score = data.get("coherence_score", 100)
        summary = data.get("summary", "")

        log.info(
            "Coherence audit: score=%s, contradictions=%d, cost=%d+%d tokens",
            coherence_score, len(contradictions),
            usage.input_tokens, usage.output_tokens,
        )

        return {
            "contradictions": contradictions,
            "coherence_score": coherence_score,
            "audit_summary": summary,
        }

    except Exception:
        log.exception("Coherence audit failed")
        return {
            "contradictions": [],
            "coherence_score": None,
            "audit_summary": "Audit failed — error in LLM call",
        }


def format_coherence_warnings(audit_result: dict) -> str:
    """Format coherence contradictions as a warning block for the report.

    Only includes high/medium severity contradictions.
    Returns empty string if no significant issues found.
    """
    contradictions = audit_result.get("contradictions", [])
    significant = [
        c for c in contradictions
        if c.get("severity") in ("high", "medium")
    ]

    if not significant:
        return ""

    lines = ["\u26a0\ufe0f <b>COHERENCE WARNINGS</b>"]
    for c in significant:
        severity_icon = "\U0001f534" if c["severity"] == "high" else "\U0001f7e1"
        lines.append(f"{severity_icon} {c.get('description', '')}")
        resolution = c.get("resolution", "")
        if resolution:
            lines.append(f"   \u2192 {resolution}")

    return "\n".join(lines)
