"""Telegram HTML formatter for Substack Ear output.

Formats analyzed newsletter intelligence into a concise Telegram message
using HTML parse mode. Sections include theses, macro signals, and
mentioned tickers relevant to the portfolio/watchlist.
"""

from typing import Any

from src.shared.config_loader import load_portfolio, load_watchlist
from src.shared.security import sanitize_html
from src.utils.logger import get_logger

log = get_logger(__name__)

MAX_OUTPUT_CHARS = 2000

_CONVICTION_ICON = {
    "high": "!!!",
    "medium": "!!",
    "low": "!",
}


def _get_portfolio_tickers() -> set[str]:
    """Load portfolio ticker symbols as a set."""
    try:
        portfolio = load_portfolio()
        return {h["ticker"] for h in portfolio.get("holdings", [])}
    except Exception as e:
        log.warning("Failed to load portfolio: %s", e)
        return set()


def _get_watchlist_tickers() -> set[str]:
    """Load watchlist ticker symbols as a set."""
    try:
        watchlist = load_watchlist()
        return set(watchlist.get("tickers", []))
    except Exception as e:
        log.warning("Failed to load watchlist: %s", e)
        return set()


def format_output(analysis: dict[str, Any]) -> str:
    """Format Substack Ear results into Telegram HTML message.

    Args:
        analysis: Aggregated analysis dict from analyzer.

    Returns:
        Formatted HTML string for Telegram (max ~2000 chars).
    """
    tickers = analysis.get("tickers", {})
    theses = analysis.get("theses", [])
    macro_signals = analysis.get("macro_signals", [])
    themes = analysis.get("themes", [])
    market_mood = analysis.get("market_mood", "unknown")

    portfolio_tickers = _get_portfolio_tickers()
    watchlist_tickers = _get_watchlist_tickers()
    relevant_tickers = portfolio_tickers | watchlist_tickers

    sections: list[str] = []

    # Header
    sections.append("<b>SUBSTACK EAR -- Expert Intelligence</b>")
    if market_mood != "unknown":
        safe_mood = sanitize_html(market_mood)
        sections.append(f"<i>Mood: {safe_mood}</i>")

    # Theses
    if theses:
        sections.append("")
        sections.append("<b>Theses</b>")
        for thesis in theses[:5]:
            conviction = thesis.get("conviction", "medium")
            icon = _CONVICTION_ICON.get(conviction, "!")
            title = sanitize_html(thesis.get("title", "Untitled"))
            summary = sanitize_html(thesis.get("summary", ""))
            affected = thesis.get("affected_tickers", [])

            # Highlight if relevant to portfolio
            ticker_str = ""
            if affected:
                highlighted = []
                for t in affected[:5]:
                    safe_t = sanitize_html(t)
                    if t in relevant_tickers:
                        highlighted.append(f"<b>{safe_t}</b>")
                    else:
                        highlighted.append(safe_t)
                ticker_str = f" [{', '.join(highlighted)}]"

            contrarian_tag = " [CONTRARIAN]" if thesis.get("contrarian") else ""
            horizon = thesis.get("time_horizon", "")
            horizon_tag = f" ({horizon})" if horizon else ""

            line = f"  {icon} <b>{title}</b>{contrarian_tag}{horizon_tag}{ticker_str}"
            sections.append(line)
            if summary:
                # Truncate summary to keep output concise
                short_summary = summary[:150] + "..." if len(summary) > 150 else summary
                sections.append(f"    {short_summary}")

    # Macro Signals
    if macro_signals:
        sections.append("")
        sections.append("<b>Macro Signals</b>")
        for signal in macro_signals[:4]:
            indicator = sanitize_html(signal.get("indicator", ""))
            implication = sanitize_html(signal.get("implication", ""))
            sections.append(f"  - {indicator}: {implication}")

    # Portfolio/Watchlist Ticker Mentions
    relevant_mentions: list[str] = []
    for symbol in sorted(relevant_tickers):
        if symbol in tickers:
            data = tickers[symbol]
            sentiment = data.get("avg_sentiment", 0)
            safe_sym = sanitize_html(symbol)
            pubs = data.get("source_publications", [])
            pub_str = f" ({', '.join(pubs[:2])})" if pubs else ""
            relevant_mentions.append(
                f"  <code>{safe_sym}</code> ({sentiment:+.1f}){pub_str}"
            )

    if relevant_mentions:
        sections.append("")
        sections.append("<b>Your Tickers Mentioned</b>")
        sections.extend(relevant_mentions[:8])

    # Themes
    if themes:
        sections.append("")
        sections.append("<b>Themes</b>")
        for theme in themes[:5]:
            safe_theme = sanitize_html(theme)
            sections.append(f"  - {safe_theme}")

    # Join and enforce character limit
    output = "\n".join(sections)

    if len(output) > MAX_OUTPUT_CHARS:
        truncated = output[:MAX_OUTPUT_CHARS]
        last_newline = truncated.rfind("\n")
        if last_newline > 0:
            truncated = truncated[:last_newline]
        output = truncated + "\n<i>...truncated</i>"

    log.info("Formatted output: %d chars", len(output))
    return output
