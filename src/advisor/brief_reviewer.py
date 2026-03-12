"""Flash-model reviewer for investment briefs before delivery."""
from __future__ import annotations

import asyncio
import json
from typing import Any

from src.shared import gemini_compat as anthropic
from src.shared.agent_decorator import track_agent
from src.shared.cost_tracker import check_budget
from src.shared.prompt_loader import load_prompt
from src.utils.logger import get_logger

log = get_logger(__name__)

REVIEWER_MODEL = "claude-haiku-4-5"

REVIEWER_FALLBACK_PROMPT = """\
Review this investment brief for:
(1) claims not supported by the provided evidence
(2) internal contradictions
(3) stale or missing data for tickers mentioned
(4) risk of misleading the reader

## Brief
$brief_text

## Holdings Context
$holdings_context

## News Context
$news_context

Return JSON: {"issues": [{"type": "<unsupported_claim|contradiction|stale_data|misleading>", "severity": "<low|medium|high>", "description": "...", "suggestion": "..."}], "overall_quality": <1-10>, "should_flag": <true|false>}
"""


def _call_reviewer(prompt: str) -> dict[str, Any]:
    client = anthropic.Anthropic()
    response = client.messages.create(
        model=REVIEWER_MODEL,
        max_tokens=800,
        messages=[{"role": "user", "content": prompt}],
    )
    return {
        "text": response.content[0].text.strip(),
        "usage": response.usage,
        "model": REVIEWER_MODEL,
    }


@track_agent("brief_reviewer")
async def _run_reviewer(prompt: str) -> dict[str, Any]:
    return await asyncio.to_thread(_call_reviewer, prompt)


async def review_brief(
    brief_text: str,
    holdings_context: str = "",
    news_context: str = "",
) -> dict[str, Any]:
    """Review an investment brief using Flash model for quality issues.

    Returns dict with keys: issues, overall_quality, should_flag, raw_text, error (if any).
    """
    within_budget, spent, cap = check_budget()
    if not within_budget:
        log.warning("brief_reviewer skipped: budget exceeded (%.2f / %.2f)", spent, cap)
        return {
            "issues": [],
            "overall_quality": 0,
            "should_flag": False,
            "error": "budget_exceeded",
        }

    prompt = load_prompt(
        "brief_reviewer",
        fallback=REVIEWER_FALLBACK_PROMPT,
        brief_text=brief_text[:6000],
        holdings_context=holdings_context[:2000],
        news_context=news_context[:2000],
    )

    result = await _run_reviewer(prompt)

    review_data = result.get("data", {})
    return {
        "issues": review_data.get("issues", []),
        "overall_quality": review_data.get("overall_quality", 0),
        "should_flag": review_data.get("should_flag", False),
        "raw_text": result.get("raw_text", ""),
        "cost_usd": result.get("cost_usd", 0.0),
        "elapsed_s": result.get("elapsed_s", 0.0),
    }
