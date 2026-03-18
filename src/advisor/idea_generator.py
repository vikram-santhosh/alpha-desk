"""Weekly novel idea generator for AlphaDesk.

Uses Gemini (via gemini_compat shim) to generate creative investment ideas
by looking across all available signals. Runs weekly (Mondays) or on first
invocation when no ideas have ever been generated.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta

from src.shared import gemini_compat as anthropic
from src.shared.cost_tracker import check_budget, record_usage
from src.shared.security import sanitize_html
from src.advisor.memory import get_last_idea_date, save_generated_idea
from src.utils.logger import get_logger

log = get_logger(__name__)

MODEL = "claude-opus-4-6"

def _build_idea_prompt(
    holdings_str: str,
    macro_str: str,
    news_str: str,
    conviction_str: str,
    moonshot_str: str,
) -> str:
    """Build the idea generation prompt with data injected safely."""
    return f"""You are a creative investment analyst. Given the current portfolio holdings, \
macro theses, recent news signals, conviction list, and moonshot list, generate \
2-3 novel investment ideas that are NOT already in the holdings, conviction, or \
moonshot lists.

Focus on:
- Non-obvious second-order effects (e.g. if AI demand surges, who supplies the cooling systems?)
- Supply chain plays upstream or downstream of current themes
- Thematic connections across sectors that the market may be underpricing
- Contrarian angles where consensus is wrong

## Current Holdings
{holdings_str}

## Macro Theses
{macro_str}

## Recent News Signals
{news_str}

## Conviction List
{conviction_str}

## Moonshot List
{moonshot_str}

Return a JSON array of 2-3 ideas. Each idea must have:
- "ticker": string or null if it's a thematic idea without a specific ticker
- "theme": short theme label (e.g. "AI cooling infrastructure")
- "thesis": 2-3 sentence investment thesis
- "source_signals": which of the above inputs inspired this idea

Return ONLY the JSON array, no other text."""


def should_run_ideas() -> bool:
    """Return True if ideas haven't been generated today yet."""
    today = date.today()

    last_date_str = get_last_idea_date()
    if last_date_str is None:
        log.info("No previous ideas found — will generate.")
        return True

    last_date = date.fromisoformat(last_date_str)
    if last_date >= today:
        log.info("Ideas already generated today (%s) — skipping.", last_date_str)
        return False

    log.info("No ideas generated today — will generate.")
    return True


def generate_novel_ideas(
    holdings: list[dict],
    macro_theses: list[dict],
    news_signals: list[dict],
    conviction_list: list[dict],
    moonshot_list: list[dict],
) -> list[dict]:
    """Generate 2-3 novel investment ideas not in current holdings, conviction, or moonshots.

    Uses Opus to find non-obvious second-order effects, supply chain plays,
    and thematic connections across all available signals.

    Returns:
        List of idea dicts with keys: ticker, theme, thesis, source_signals.
    """
    within_budget, spent, cap = check_budget()
    if not within_budget:
        log.warning("idea_generator skipped: budget exceeded (%.2f / %.2f)", spent, cap)
        return []

    prompt = _build_idea_prompt(
        holdings_str=json.dumps(holdings, default=str)[:3000],
        macro_str=json.dumps(macro_theses, default=str)[:2000],
        news_str=json.dumps(news_signals, default=str)[:3000],
        conviction_str=json.dumps(conviction_list, default=str)[:2000],
        moonshot_str=json.dumps(moonshot_list, default=str)[:2000],
    )

    client = anthropic.Anthropic()
    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=1500,
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception:
        log.exception("Idea generation API call failed")
        return []

    # Track usage
    usage = response.usage
    record_usage(
        agent="idea_generator",
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        model=MODEL,
    )

    raw_text = response.content[0].text.strip()
    log.info("Raw idea response: %s", raw_text[:200])

    # Parse JSON response
    try:
        ideas = json.loads(raw_text)
    except json.JSONDecodeError:
        # Try to extract JSON array from the response
        start = raw_text.find("[")
        end = raw_text.rfind("]") + 1
        if start >= 0 and end > start:
            try:
                ideas = json.loads(raw_text[start:end])
            except json.JSONDecodeError:
                log.error("Could not parse idea response as JSON")
                return []
        else:
            log.error("No JSON array found in idea response")
            return []

    if not isinstance(ideas, list):
        log.error("Expected list of ideas, got %s", type(ideas).__name__)
        return []

    # Validate and save each idea
    validated: list[dict] = []
    for idea in ideas:
        if not isinstance(idea, dict):
            continue
        ticker = idea.get("ticker")
        theme = idea.get("theme", "")
        thesis = idea.get("thesis", "")
        source_signals = idea.get("source_signals", "")

        if not theme or not thesis:
            log.warning("Skipping idea with missing theme/thesis: %s", idea)
            continue

        if isinstance(source_signals, list):
            source_signals = ", ".join(str(s) for s in source_signals)

        save_generated_idea(
            theme=theme,
            thesis=thesis,
            ticker=ticker,
            source_signals=str(source_signals),
        )
        validated.append({
            "ticker": ticker,
            "theme": theme,
            "thesis": thesis,
            "source_signals": str(source_signals),
        })
        log.info("Saved idea: %s — %s", ticker or "(thematic)", theme)

    log.info("Generated %d novel ideas.", len(validated))
    return validated


def format_ideas_section(ideas: list[dict]) -> str:
    """Format ideas as Telegram HTML for the daily brief.

    Args:
        ideas: List of idea dicts from generate_novel_ideas.

    Returns:
        Formatted HTML string for Telegram.
    """
    if not ideas:
        return ""

    lines = ["\n<b>\U0001f4a1 Novel Ideas</b>\n"]

    for idea in ideas:
        ticker = idea.get("ticker")
        theme = sanitize_html(idea.get("theme", ""))
        thesis = sanitize_html(idea.get("thesis", ""))
        source = sanitize_html(idea.get("source_signals", ""))

        ticker_str = f" <b>{sanitize_html(ticker)}</b>" if ticker else ""
        lines.append(f"\U0001f4a1 <b>[NEW IDEA]</b>{ticker_str} — {theme}")
        lines.append(f"   {thesis}")
        if source:
            lines.append(f"   <i>Signals: {source}</i>")
        lines.append("")

    return "\n".join(lines)
