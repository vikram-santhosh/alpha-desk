"""Telegram HTML formatter for Alpha Scout recommendations.

Produces two sections:
- Portfolio Recommendations (buy) with conviction badges
- Watchlist Recommendations (monitor) with conviction badges
"""
from __future__ import annotations

from typing import Any

from src.shared.security import sanitize_html
from src.utils.logger import get_logger

log = get_logger(__name__)

# Emoji constants
ROCKET = "\U0001f680"         # Portfolio recommendation
EYES = "\U0001f440"           # Watchlist recommendation
GREEN_CIRCLE = "\U0001f7e2"   # High conviction
YELLOW_CIRCLE = "\U0001f7e1"  # Medium conviction
WHITE_CIRCLE = "\u26aa"       # Low conviction
CHART_UP = "\U0001f4c8"       # Score trending up
MAGNIFYING = "\U0001f50d"     # Discovery
STAR = "\u2b50"               # Top pick


def _conviction_badge(conviction: str) -> str:
    """Return emoji + label for conviction level."""
    if conviction == "high":
        return f"{GREEN_CIRCLE} HIGH"
    elif conviction == "medium":
        return f"{YELLOW_CIRCLE} MED"
    return f"{WHITE_CIRCLE} LOW"


def _format_scores_bar(scores: dict[str, Any]) -> str:
    """Format a compact score summary."""
    parts = []
    for key in ("technical", "fundamental", "sentiment", "diversification"):
        val = scores.get(key)
        if val is not None:
            abbrev = key[0].upper()
            parts.append(f"{abbrev}:{val}")
    composite = scores.get("composite")
    if composite is not None:
        parts.append(f"={composite:.0f}")
    return " ".join(parts)


def _format_recommendation(rec: dict[str, Any], rank: int) -> str:
    """Format a single recommendation entry."""
    ticker = sanitize_html(rec.get("ticker", "???"))
    conviction = rec.get("conviction", "medium")
    thesis = sanitize_html(rec.get("thesis", ""))
    scores = rec.get("scores", {})
    fund = rec.get("fundamentals_summary", {})

    # Build detail line
    details = []
    sector = fund.get("sector")
    if sector:
        details.append(sanitize_html(sector))

    pe = fund.get("pe_trailing")
    if pe is not None:
        details.append(f"P/E {pe:.1f}")

    market_cap = fund.get("market_cap")
    if market_cap is not None:
        if market_cap >= 1e12:
            details.append(f"${market_cap / 1e12:.1f}T")
        elif market_cap >= 1e9:
            details.append(f"${market_cap / 1e9:.1f}B")
        elif market_cap >= 1e6:
            details.append(f"${market_cap / 1e6:.0f}M")

    badge = _conviction_badge(conviction)
    score_str = _format_scores_bar(scores)

    lines = [
        f"  {rank}. <b>{ticker}</b> [{badge}]",
    ]
    if details:
        lines.append(f"     {' | '.join(details)}")
    if score_str:
        lines.append(f"     <code>{score_str}</code>")
    if thesis:
        lines.append(f"     <i>{thesis}</i>")

    return "\n".join(lines)


def format_discovery_report(
    portfolio_recs: list[dict[str, Any]],
    watchlist_recs: list[dict[str, Any]],
    stats: dict[str, Any],
) -> str:
    """Format the complete Alpha Scout discovery report.

    Args:
        portfolio_recs: List of portfolio (buy) recommendation dicts.
        watchlist_recs: List of watchlist (monitor) recommendation dicts.
        stats: Pipeline stats dict.

    Returns:
        Telegram HTML formatted string.
    """
    sections: list[str] = []

    # Header
    sections.append(f"{MAGNIFYING} <b>ALPHA SCOUT \u2014 Ticker Discovery</b>")

    # Portfolio Recommendations
    if portfolio_recs:
        sections.append("")
        sections.append(f"{ROCKET} <b>Portfolio Recommendations (Buy)</b>")
        sections.append("")
        for i, rec in enumerate(portfolio_recs, 1):
            sections.append(_format_recommendation(rec, i))
            sections.append("")
    else:
        sections.append("")
        sections.append(f"{ROCKET} <b>Portfolio Recommendations</b>")
        sections.append("  <i>No strong buy candidates found this cycle.</i>")

    # Watchlist Recommendations
    if watchlist_recs:
        sections.append("")
        sections.append(f"{EYES} <b>Watchlist Recommendations (Monitor)</b>")
        sections.append("")
        for i, rec in enumerate(watchlist_recs, 1):
            sections.append(_format_recommendation(rec, i))
            sections.append("")
    else:
        sections.append("")
        sections.append(f"{EYES} <b>Watchlist Recommendations</b>")
        sections.append("  <i>No watchlist candidates found this cycle.</i>")

    # Stats footer
    candidates_screened = stats.get("candidates_screened", 0)
    total_time = stats.get("total_time_s", 0)
    sections.append(
        f"<i>Screened {candidates_screened} candidates in {total_time:.0f}s</i>"
    )

    report = "\n".join(sections)
    log.info("Formatted discovery report: %d chars", len(report))
    return report
