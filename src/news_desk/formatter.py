"""Telegram HTML message formatting for AlphaDesk News Desk.

Formats analyzed news articles into a structured Telegram message with
sections for portfolio-relevant news, market & macro, earnings calendar,
and sector news.

Telegram HTML supports: <b>, <i>, <a href="">, <code>, <pre>.
Max message length target: ~2000 characters (Telegram limit is 4096,
but we aim for readability).
"""
from __future__ import annotations

from typing import Any

from src.shared.security import sanitize_html
from src.utils.logger import get_logger

log = get_logger(__name__)

# Target max characters for the formatted message
MAX_CHARS = 2000
MAX_ARTICLES = 15

# Category to section mapping
SECTION_MAP = {
    "portfolio": "Portfolio-Relevant News",
    "market": "Market & Macro",
    "earnings": "Earnings Calendar",
    "sector": "Sector News",
}

# Urgency emojis
URGENCY_EMOJI = {
    "high": "\U0001f534",    # red circle
    "med": "\U0001f7e1",     # yellow circle
    "low": "\U0001f7e2",     # green circle
}

# Sentiment emojis
SENTIMENT_EMOJI = {
    2: "\U0001f680",    # rocket (very bullish)
    1: "\U0001f4c8",    # chart increasing (bullish)
    0: "\u2796",         # minus (neutral)
    -1: "\U0001f4c9",   # chart decreasing (bearish)
    -2: "\U0001f4a5",   # collision (very bearish)
}


def _get_sentiment_emoji(sentiment: float) -> str:
    """Get the emoji for a sentiment score.

    Args:
        sentiment: Sentiment score from -2 to +2.

    Returns:
        Emoji string for the sentiment.
    """
    rounded = round(sentiment)
    return SENTIMENT_EMOJI.get(rounded, "\u2796")


def _get_urgency_emoji(urgency: str) -> str:
    """Get the emoji for an urgency level.

    Args:
        urgency: One of "low", "med", "high".

    Returns:
        Emoji string for the urgency.
    """
    return URGENCY_EMOJI.get(urgency, "\U0001f7e2")


def _classify_article(article: dict[str, Any], portfolio_tickers: list[str]) -> str:
    """Classify an article into a display section.

    Priority: portfolio > earnings > sector > market.

    Args:
        article: Analyzed article dict.
        portfolio_tickers: List of tickers from the user's portfolio.

    Returns:
        Section key: "portfolio", "earnings", "sector", or "market".
    """
    category = article.get("category", "other")
    related_tickers = article.get("related_tickers", [])

    # Check if any related ticker is in the portfolio
    if related_tickers and portfolio_tickers:
        if any(t in portfolio_tickers for t in related_tickers):
            return "portfolio"

    if category == "earnings":
        return "earnings"
    elif category == "sector":
        return "sector"
    else:
        return "market"


def _format_article_line(article: dict[str, Any]) -> str:
    """Format a single article as an HTML line for Telegram.

    Format: {urgency_emoji}{sentiment_emoji} <a href="url">Headline</a> ({source}) [R:{relevance}] {tickers}

    Args:
        article: Analyzed article dict.

    Returns:
        Formatted HTML string for the article.
    """
    urgency = article.get("urgency", "low")
    sentiment = article.get("sentiment", 0)
    title = article.get("title", "Untitled")
    url = article.get("url", "")
    source = sanitize_html(article.get("source", "Unknown"))
    relevance = article.get("relevance", 0)
    tickers = article.get("related_tickers", [])

    urgency_emoji = _get_urgency_emoji(urgency)
    sentiment_emoji = _get_sentiment_emoji(sentiment)

    # Build headline with link (or plain text if no URL)
    if url:
        headline = f'<a href="{url}">{title}</a>'
    else:
        headline = f"<b>{title}</b>"

    # Ticker tags
    ticker_str = ""
    if tickers:
        ticker_tags = " ".join(f"${t}" for t in tickers[:3])  # max 3 tickers shown
        ticker_str = f" {ticker_tags}"

    return f"{urgency_emoji}{sentiment_emoji} {headline} ({source}) [R:{relevance}]{ticker_str}"


def format_news_digest(
    articles: list[dict[str, Any]],
    portfolio_tickers: list[str] | None = None,
) -> str:
    """Format analyzed news articles into a Telegram HTML message.

    Organizes articles into four sections:
    - Portfolio-Relevant News: articles affecting portfolio tickers
    - Market & Macro: general market and macro-economic news
    - Earnings Calendar: earnings-related articles
    - Sector News: sector-specific articles

    Each article is formatted with urgency/sentiment emojis, linked headline,
    source, relevance score, and affected tickers. Output is capped at ~2000
    characters to keep Telegram messages readable.

    Args:
        articles: List of analyzed and filtered article dicts.
        portfolio_tickers: List of tickers from the user's portfolio,
            used to classify portfolio-relevant articles.

    Returns:
        Formatted HTML string ready for Telegram delivery.
    """
    if not articles:
        return "<b>\U0001f4f0 News Desk</b>\n\nNo significant news to report."

    portfolio_tickers = portfolio_tickers or []

    # Classify articles into sections
    sections: dict[str, list[dict[str, Any]]] = {
        "portfolio": [],
        "market": [],
        "earnings": [],
        "sector": [],
    }

    # Only take top MAX_ARTICLES articles (already sorted by relevance)
    top_articles = articles[:MAX_ARTICLES]

    for article in top_articles:
        section = _classify_article(article, portfolio_tickers)
        sections[section].append(article)

    # Build the message
    lines: list[str] = [f"<b>\U0001f4f0 News Desk</b>"]
    current_length = len(lines[0])

    # Section order: portfolio first, then earnings, sector, market
    section_order = ["portfolio", "earnings", "sector", "market"]

    for section_key in section_order:
        section_articles = sections[section_key]
        if not section_articles:
            continue

        section_title = SECTION_MAP[section_key]
        header = f"\n<b>{section_title}</b>"

        # Check if adding this section would exceed limit
        if current_length + len(header) > MAX_CHARS:
            break

        lines.append(header)
        current_length += len(header)

        for article in section_articles:
            line = _format_article_line(article)

            # Check if adding this line would exceed limit
            if current_length + len(line) + 1 > MAX_CHARS:
                lines.append("  <i>...more articles omitted</i>")
                current_length = MAX_CHARS + 1  # force outer break
                break

            lines.append(line)
            current_length += len(line) + 1  # +1 for newline

        if current_length > MAX_CHARS:
            break

    # Add footer with stats
    total = len(articles)
    shown = sum(len(v) for v in sections.values())
    footer = f"\n<i>Showing {min(shown, MAX_ARTICLES)} of {total} articles</i>"
    if current_length + len(footer) <= MAX_CHARS + 200:  # small buffer for footer
        lines.append(footer)

    result = "\n".join(lines)
    log.info("Formatted news digest: %d chars, %d articles shown", len(result), shown)
    return result
