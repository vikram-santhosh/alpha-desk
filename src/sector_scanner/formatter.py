"""Sector Scanner — format output for Telegram delivery.

Groups articles by sector, shows top 1-2 per sector with direction emoji.
Max 5 sectors in output.
"""
from __future__ import annotations

from typing import Any

from src.shared.security import sanitize_html
from src.utils.logger import get_logger

log = get_logger(__name__)

DIRECTION_EMOJI = {
    "bullish": "\U0001f7e2",   # 🟢
    "bearish": "\U0001f534",   # 🔴
    "neutral": "\u26aa",       # ⚪
    "mixed": "\U0001f7e1",     # 🟡
}

SECTOR_LABELS = {
    "space_tech": "Space Tech",
    "quantum_computing": "Quantum Computing",
    "nuclear_energy": "Nuclear Energy",
    "robotics_ai": "Robotics & AI",
    "defense_aerospace": "Defense & Aerospace",
    "gold_miners": "Gold Miners",
    "energy_infrastructure": "Energy Infrastructure",
    "uranium": "Uranium",
    "infrastructure_build": "Infrastructure",
    "commodity_supercycle": "Commodity Supercycle",
}

MAX_SECTORS = 5
MAX_ARTICLES_PER_SECTOR = 2


def format_output(
    analyzed_articles: list[dict[str, Any]],
    signals: list[dict[str, Any]] | None = None,
) -> str:
    """Format sector scanner results as Telegram HTML.

    Args:
        analyzed_articles: Articles that passed analysis (with sector, direction, etc.)
        signals: Published signal dicts (for stats).

    Returns:
        HTML-formatted string for Telegram.
    """
    if not analyzed_articles:
        return "<b>\U0001f30d Sector Scanner</b>\n<i>No notable sector activity detected.</i>"

    # Group by sector, sorted by max relevance
    sector_groups: dict[str, list[dict[str, Any]]] = {}
    for article in analyzed_articles:
        sector = article.get("sector", "unknown")
        sector_groups.setdefault(sector, []).append(article)

    # Sort sectors by highest relevance article, take top MAX_SECTORS
    sorted_sectors = sorted(
        sector_groups.items(),
        key=lambda x: max(a.get("sector_relevance", 0) for a in x[1]),
        reverse=True,
    )[:MAX_SECTORS]

    lines = ["<b>\U0001f30d Sector Scanner</b>", ""]

    for sector, articles in sorted_sectors:
        label = SECTOR_LABELS.get(sector, sector.replace("_", " ").title())

        # Determine overall sector direction
        bullish = sum(1 for a in articles if a.get("direction") == "bullish")
        bearish = sum(1 for a in articles if a.get("direction") == "bearish")
        if bullish > bearish:
            direction = "bullish"
        elif bearish > bullish:
            direction = "bearish"
        else:
            direction = "mixed" if bullish > 0 else "neutral"

        emoji = DIRECTION_EMOJI.get(direction, "\u26aa")
        lines.append(f"{emoji} <b>{label}</b>")

        # Top articles by relevance
        top = sorted(articles, key=lambda a: a.get("sector_relevance", 0), reverse=True)
        for article in top[:MAX_ARTICLES_PER_SECTOR]:
            summary = sanitize_html(article.get("sector_summary", article.get("title", "")))
            catalyst = sanitize_html(article.get("catalyst_type", ""))
            catalyst_tag = f" [{catalyst}]" if catalyst and catalyst != "other" else ""
            tickers = article.get("sector_tickers", [])
            ticker_str = f" ({', '.join(sanitize_html(t) for t in tickers[:3])})" if tickers else ""
            lines.append(f"  \u2022 {summary}{catalyst_tag}{ticker_str}")

        lines.append("")

    # Stats footer
    total = len(analyzed_articles)
    signal_count = len(signals) if signals else 0
    lines.append(f"<i>{total} articles across {len(sorted_sectors)} sectors | {signal_count} signals</i>")

    return "\n".join(lines)
