"""Dynamic macro thesis discovery for AlphaDesk Advisor.

Uses Gemini (via gemini_compat shim) to identify emerging macro themes from
news + social signals that aren't already in the thesis list.

Focuses on: trade policy, geopolitical shifts, sector rotation,
regulatory changes, and commodity cycles.
"""
from __future__ import annotations

import json

from src.shared import gemini_compat as anthropic
from src.shared.cost_tracker import check_budget, record_usage
from src.utils.logger import get_logger

log = get_logger(__name__)

_AGENT_NAME = "advisor_macro_scanner"
_MODEL = "claude-haiku-4-5"


def scan_for_emerging_themes(
    news_signals: list[dict],
    existing_theses: list[dict],
    reddit_themes: list[str] | None = None,
) -> list[dict]:
    """Identify 1-3 emerging macro themes not already tracked.

    Args:
        news_signals: Recent news signal dicts from News Desk.
        existing_theses: Current thesis list (each has at least a 'title').
        reddit_themes: Optional list of trending Reddit theme strings.

    Returns:
        List of theme dicts with keys: title, description,
        affected_tickers, confidence, source_signals.
        Returns empty list if no signals or budget exceeded.
    """
    if not news_signals:
        log.info("No news signals provided — skipping macro scan")
        return []

    within_budget, spent, cap = check_budget()
    if not within_budget:
        log.warning("Budget exceeded ($%.2f / $%.2f) — skipping macro scan", spent, cap)
        return []

    # Build existing thesis titles for the prompt
    existing_titles = [t.get("title", "") for t in existing_theses if t.get("title")]
    existing_str = "\n".join(f"- {t}" for t in existing_titles) if existing_titles else "(none)"

    # Summarise news signals
    signal_summaries = []
    for sig in news_signals[:20]:  # cap to keep prompt reasonable
        headline = sig.get("headline") or sig.get("title") or sig.get("summary", "")
        tickers = sig.get("tickers") or sig.get("affected_tickers") or []
        if headline:
            ticker_str = f" [{', '.join(tickers)}]" if tickers else ""
            signal_summaries.append(f"- {headline}{ticker_str}")
    signals_str = "\n".join(signal_summaries) if signal_summaries else "(no headlines)"

    # Reddit themes context
    reddit_str = ""
    if reddit_themes:
        reddit_str = "\n\nREDDIT TRENDING THEMES:\n" + "\n".join(f"- {t}" for t in reddit_themes[:10])

    prompt = f"""You are a macro strategist scanning for EMERGING investment themes.

RECENT NEWS SIGNALS:
{signals_str}{reddit_str}

EXISTING THESES (already tracked — do NOT repeat these):
{existing_str}

Identify 1-3 emerging macro themes that are NOT already in the existing theses list.
Focus on:
- Trade policy shifts (tariffs, sanctions, trade agreements)
- Geopolitical shifts (alliances, conflicts, elections)
- Sector rotation (capital flowing between sectors)
- Regulatory changes (new rules, deregulation, antitrust)
- Commodity cycles (supply disruptions, demand shifts)

For each theme return a JSON object with:
- "title": short theme name (5-10 words)
- "description": 2-3 sentence explanation of the thesis
- "affected_tickers": list of 2-5 stock tickers most exposed
- "confidence": float 0-1 indicating conviction
- "source_signals": brief string noting which signals support this

Return a JSON array of theme objects. If no compelling new themes emerge, return an empty array [].
Respond with ONLY valid JSON, no markdown code blocks."""

    try:
        client = anthropic.Anthropic()
        response = client.messages.create(
            model=_MODEL,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )

        usage = response.usage
        record_usage(_AGENT_NAME, usage.input_tokens, usage.output_tokens, model=_MODEL)

        if not response.content:
            log.warning("Empty response from macro scan")
            return []

        raw = response.content[0].text.strip()

        # Strip markdown code blocks if present
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
            if raw.endswith("```"):
                raw = raw[:-3]
            raw = raw.strip()

        try:
            themes = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            log.warning("Failed to parse JSON from macro scan response")
            return []

        if not isinstance(themes, list):
            log.warning("Macro scan returned non-list: %s", type(themes).__name__)
            return []

        # Validate and normalise each theme
        validated: list[dict] = []
        for theme in themes[:3]:
            if not isinstance(theme, dict) or not theme.get("title"):
                continue
            validated.append({
                "title": theme["title"],
                "description": theme.get("description", ""),
                "affected_tickers": theme.get("affected_tickers", []),
                "confidence": float(theme.get("confidence", 0.5)),
                "source_signals": theme.get("source_signals", ""),
            })

        log.info(
            "Macro scan found %d emerging themes (%d in, %d out)",
            len(validated), usage.input_tokens, usage.output_tokens,
        )
        return validated

    except Exception:
        log.exception("Macro scan failed")
        return []
