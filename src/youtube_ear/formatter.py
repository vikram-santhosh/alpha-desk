"""Telegram HTML formatter for YouTube Ear output.

Formats analyzed and tracked YouTube video intelligence into a concise
Telegram message using HTML parse mode. Sections include top analyses,
theses, trending tickers, and view spike alerts.
"""

from typing import Any

from src.shared.security import sanitize_html
from src.utils.logger import get_logger

log = get_logger(__name__)

MAX_OUTPUT_CHARS = 2000

# Sentiment to emoji mapping
_SENTIMENT_EMOJI = {
    -2: "\U0001f534\U0001f534",
    -1: "\U0001f534",
    0: "\u26aa",
    1: "\U0001f7e2",
    2: "\U0001f7e2\U0001f7e2",
}


def _sentiment_indicator(sentiment: float) -> str:
    """Convert numeric sentiment to a visual indicator."""
    rounded = round(sentiment)
    clamped = max(-2, min(2, rounded))
    return _SENTIMENT_EMOJI.get(clamped, "\u26aa")


def _format_views(views: int) -> str:
    """Format view count as a readable string with emoji."""
    if views >= 1_000_000:
        return f"\U0001f4fa {views / 1_000_000:.1f}M views"
    elif views >= 1_000:
        return f"\U0001f4fa {views / 1_000:.0f}K views"
    return f"\U0001f4fa {views:,} views"


def format_output(
    analysis: dict[str, Any],
    view_spikes: list[dict[str, Any]],
    convergences: list[dict[str, Any]],
    videos: list[dict[str, Any]],
) -> str:
    """Format YouTube Ear results into Telegram HTML message.

    Args:
        analysis: Aggregated analysis dict from analyzer.
        view_spikes: List of view spike alerts from tracker.
        convergences: List of multi-channel convergences from tracker.
        videos: Original list of video dicts for context.

    Returns:
        Formatted HTML string for Telegram (max ~2000 chars).
    """
    tickers = analysis.get("tickers", {})
    theses = analysis.get("theses", [])
    themes = analysis.get("themes", [])
    macro_signals = analysis.get("macro_signals", [])
    market_mood = analysis.get("market_mood", "unknown")

    sections: list[str] = []

    # Header
    sections.append("\U0001f3ac <b>YOUTUBE EAR \u2014 Video Intelligence</b>")
    if market_mood != "unknown":
        safe_mood = sanitize_html(market_mood)
        sections.append(f"<i>Mood: {safe_mood}</i>")
    sections.append(f"<i>{len(videos)} videos analyzed</i>")

    # Top Tickers by mentions
    sorted_tickers = sorted(
        tickers.items(),
        key=lambda x: x[1].get("total_mentions", 0),
        reverse=True,
    )[:8]

    if sorted_tickers:
        sections.append("")
        sections.append("<b>Top Discussed</b>")
        for symbol, data in sorted_tickers:
            sentiment = data.get("avg_sentiment", 0)
            mentions = data.get("total_mentions", 0)
            emoji = _sentiment_indicator(sentiment)
            channels = data.get("channels", [])
            channel_str = f" ({', '.join(channels[:2])})" if channels else ""

            safe_symbol = sanitize_html(symbol)
            sections.append(
                f"  {emoji} <code>{safe_symbol}</code> x{mentions} ({sentiment:+.1f}){channel_str}"
            )

    # Theses
    if theses:
        sections.append("")
        sections.append("<b>Expert Theses</b>")
        for thesis in theses[:3]:
            ticker = sanitize_html(thesis.get("ticker", ""))
            direction = thesis.get("direction", "neutral")
            text = sanitize_html(thesis.get("thesis", ""))
            source = sanitize_html(thesis.get("source", ""))
            arrow = "\u2191" if direction == "bullish" else ("\u2193" if direction == "bearish" else "\u2192")

            sections.append(f"  {arrow} <code>{ticker}</code>: {text}")
            if source:
                sections.append(f"    <i>\u2014 {source}</i>")

    # Macro Signals
    if macro_signals:
        sections.append("")
        sections.append("<b>Macro Signals</b>")
        for signal in macro_signals[:4]:
            safe_signal = sanitize_html(signal)
            sections.append(f"  \u2022 {safe_signal}")

    # View Spike Alerts
    if view_spikes:
        sections.append("")
        sections.append("<b>View Spikes</b>")
        for spike in view_spikes[:3]:
            channel = sanitize_html(spike.get("channel", ""))
            title = sanitize_html(spike.get("title", "")[:60])
            views = spike.get("views", 0)
            multiplier = spike.get("multiplier", 1)
            sections.append(
                f"  {_format_views(views)} {multiplier}x avg"
            )
            sections.append(f"    <i>{channel}: {title}</i>")

    # Multi-Channel Convergence
    if convergences:
        sections.append("")
        sections.append("<b>Multi-Channel Convergence</b>")
        for c in convergences[:3]:
            safe_ticker = sanitize_html(c["ticker"])
            channels = ", ".join(c.get("channels", [])[:3])
            sections.append(
                f"  <code>{safe_ticker}</code> \u2014 {c['channel_count']} channels ({channels})"
            )

    # Themes
    if themes:
        sections.append("")
        sections.append("<b>Themes</b>")
        for theme in themes[:4]:
            safe_theme = sanitize_html(theme)
            sections.append(f"  \u2022 {safe_theme}")

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
