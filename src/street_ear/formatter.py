"""Telegram HTML formatter for Street Ear output.

Formats analyzed and tracked Reddit intelligence into a concise Telegram
message using HTML parse mode. Sections include holdings mentions, watchlist
hits, trending tickers, active narratives, and anomaly alerts.
"""

from typing import Any

from src.shared.config_loader import load_portfolio, load_watchlist
from src.shared.security import sanitize_html
from src.utils.logger import get_logger

log = get_logger(__name__)

MAX_OUTPUT_CHARS = 2000

# Sentiment to emoji mapping
_SENTIMENT_EMOJI = {
    -2: "🔴🔴",
    -1: "🔴",
    0: "⚪",
    1: "🟢",
    2: "🟢🟢",
}

# Trend direction arrows
_TREND_UP = "↑"
_TREND_DOWN = "↓"
_TREND_FLAT = "→"


def _sentiment_indicator(sentiment: float) -> str:
    """Convert numeric sentiment to a visual indicator.

    Args:
        sentiment: Sentiment score from -2.0 to +2.0.

    Returns:
        Emoji string representing sentiment.
    """
    rounded = round(sentiment)
    clamped = max(-2, min(2, rounded))
    return _SENTIMENT_EMOJI.get(clamped, "⚪")


def _trend_arrow(trend: list[dict[str, Any]]) -> str:
    """Determine trend direction from mention history.

    Args:
        trend: List of daily mention dicts (date, mention_count) sorted ascending.

    Returns:
        Arrow character indicating direction.
    """
    if len(trend) < 2:
        return _TREND_FLAT

    recent = trend[-1].get("mention_count", 0)
    previous = trend[-2].get("mention_count", 0)

    if recent > previous:
        return _TREND_UP
    elif recent < previous:
        return _TREND_DOWN
    return _TREND_FLAT


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


def _format_ticker_line(
    symbol: str,
    data: dict[str, Any],
    trends: dict[str, list[dict[str, Any]]],
) -> str:
    """Format a single ticker line for the output.

    Args:
        symbol: Ticker symbol.
        data: Ticker analysis data dict.
        trends: Dict mapping symbols to their mention trend data.

    Returns:
        Formatted HTML line string.
    """
    sentiment = data.get("avg_sentiment", 0)
    mentions = data.get("total_mentions", 0)
    emoji = _sentiment_indicator(sentiment)
    trend = trends.get(symbol, [])
    arrow = _trend_arrow(trend)

    safe_symbol = sanitize_html(symbol)
    return f"  {emoji} <code>{safe_symbol}</code> x{mentions} {arrow} ({sentiment:+.1f})"


def format_output(
    analysis: dict[str, Any],
    anomalies: list[dict[str, Any]],
    reversals: list[dict[str, Any]],
    convergences: list[dict[str, Any]],
    trends: dict[str, list[dict[str, Any]]],
) -> str:
    """Format Street Ear results into Telegram HTML message.

    Args:
        analysis: Aggregated analysis dict from analyzer.
        anomalies: List of mention spike anomalies from tracker.
        reversals: List of sentiment reversals from tracker.
        convergences: List of multi-sub convergences from tracker.
        trends: Dict mapping ticker symbols to their mention trend data.

    Returns:
        Formatted HTML string for Telegram (max ~2000 chars).
    """
    tickers = analysis.get("tickers", {})
    themes = analysis.get("themes", [])
    market_mood = analysis.get("market_mood", "unknown")

    portfolio_tickers = _get_portfolio_tickers()
    watchlist_tickers = _get_watchlist_tickers()

    sections: list[str] = []

    # Header
    sections.append(f"<b>Street Ear — Reddit Pulse</b>")
    if market_mood != "unknown":
        safe_mood = sanitize_html(market_mood)
        sections.append(f"<i>Mood: {safe_mood}</i>")

    # Holdings Mentions
    holdings_lines: list[str] = []
    for symbol in sorted(portfolio_tickers):
        if symbol in tickers:
            line = _format_ticker_line(symbol, tickers[symbol], trends)
            holdings_lines.append(line)

    if holdings_lines:
        sections.append("")
        sections.append("<b>Holdings Mentions</b>")
        sections.extend(holdings_lines)

    # Watchlist Hits
    watchlist_lines: list[str] = []
    for symbol in sorted(watchlist_tickers):
        if symbol in tickers:
            line = _format_ticker_line(symbol, tickers[symbol], trends)
            watchlist_lines.append(line)

    if watchlist_lines:
        sections.append("")
        sections.append("<b>Watchlist Hits</b>")
        sections.extend(watchlist_lines)

    # Trending Tickers (top 5 non-portfolio/non-watchlist by mention count)
    other_tickers = {
        sym: data for sym, data in tickers.items()
        if sym not in portfolio_tickers and sym not in watchlist_tickers
    }
    sorted_others = sorted(
        other_tickers.items(),
        key=lambda x: x[1].get("total_mentions", 0),
        reverse=True,
    )[:5]

    if sorted_others:
        sections.append("")
        sections.append("<b>Trending</b>")
        for symbol, data in sorted_others:
            line = _format_ticker_line(symbol, data, trends)
            sections.append(line)

    # Active Narratives
    if themes:
        sections.append("")
        sections.append("<b>Narratives</b>")
        for theme in themes[:5]:  # Limit to top 5 themes
            safe_theme = sanitize_html(theme)
            sections.append(f"  - {safe_theme}")

    # Anomaly Alerts
    alerts: list[str] = []

    for a in anomalies[:3]:  # Limit alerts
        safe_ticker = sanitize_html(a["ticker"])
        alerts.append(
            f"  Spike: <code>{safe_ticker}</code> {a['multiplier']}x usual volume"
        )

    for r in reversals[:3]:
        safe_ticker = sanitize_html(r["ticker"])
        direction = "bearish->bullish" if r["direction"] == "bearish_to_bullish" else "bullish->bearish"
        alerts.append(
            f"  Flip: <code>{safe_ticker}</code> {direction}"
        )

    for c in convergences[:3]:
        safe_ticker = sanitize_html(c["ticker"])
        subs = ", ".join(c["subreddits"][:4])
        alerts.append(
            f"  Convergence: <code>{safe_ticker}</code> in {c['subreddit_count']} subs ({subs})"
        )

    if alerts:
        sections.append("")
        sections.append("<b>Alerts</b>")
        sections.extend(alerts)

    # Join and enforce character limit
    output = "\n".join(sections)

    if len(output) > MAX_OUTPUT_CHARS:
        # Truncate at the last complete line within limit
        truncated = output[:MAX_OUTPUT_CHARS]
        last_newline = truncated.rfind("\n")
        if last_newline > 0:
            truncated = truncated[:last_newline]
        output = truncated + "\n<i>...truncated</i>"

    log.info("Formatted output: %d chars", len(output))
    return output
