"""Claude analysis of Reddit posts for Street Ear.

Batches Reddit posts and sends them to Claude for extraction of ticker
mentions, sentiment, confidence, themes, and notable quotes. Aggregates
results across batches into per-ticker summaries.

Uses Sonnet for ticker extraction and sentiment classification rather
than Opus, since this is structured extraction, not creative reasoning.
"""
from __future__ import annotations

import json
from typing import Any

from src.shared import gemini_compat as anthropic

from src.shared.config_loader import get_all_tickers
from src.shared.cost_tracker import check_budget, record_usage
from src.shared.security import sanitize_ticker
from src.utils.logger import get_logger

log = get_logger(__name__)

MODEL = "claude-sonnet-4-6"
AGENT_NAME = "street_ear"
BATCH_SIZE = 20
MAX_TOKENS = 4096

SYSTEM_PROMPT = """You are a financial market analyst specializing in retail investor sentiment analysis.
You analyze Reddit posts to extract stock ticker mentions, sentiment, and emerging narratives.

IMPORTANT RULES:
- Only extract actual stock ticker symbols (e.g., AAPL, TSLA, NVDA), not random abbreviations
- Validate tickers: they should be 1-5 uppercase letters, optionally with a dot (e.g., BRK.B)
- Ignore common words that look like tickers (e.g., IT, A, BE, SO, ALL, FOR, ARE, CEO, IPO, ETF)
- Sentiment scale: -2 (very bearish), -1 (bearish), 0 (neutral), +1 (bullish), +2 (very bullish)
- Confidence scale: 0.0 (low) to 1.0 (high) — based on how clear the sentiment is
- Be concise with themes and quotes"""

ANALYSIS_PROMPT = """Analyze these Reddit posts for stock market intelligence.

Posts:
{posts_text}

Known portfolio/watchlist tickers for reference: {known_tickers}

Return a JSON object with this exact structure:
{{
  "tickers": [
    {{
      "symbol": "AAPL",
      "mentions": 3,
      "sentiment": 1.5,
      "confidence": 0.8,
      "themes": ["strong earnings", "AI integration"],
      "notable_quote": "Apple's AI play is undervalued...",
      "source_subreddits": ["wallstreetbets", "stocks"]
    }}
  ],
  "overall_themes": ["AI hype cycle", "rate cut expectations"],
  "market_mood": "cautiously bullish"
}}

Only include tickers that are actually mentioned. Be precise with sentiment scores.
Return ONLY the JSON object, no other text."""


def _format_posts_for_prompt(posts: list[dict[str, Any]]) -> str:
    """Format a batch of posts into a readable text block for the prompt.

    Args:
        posts: List of post dicts from reddit_fetcher.

    Returns:
        Formatted string with numbered posts.
    """
    lines: list[str] = []
    for i, post in enumerate(posts, 1):
        sub = post.get("subreddit", "unknown")
        score = post.get("score", 0)
        comments = post.get("num_comments", 0)
        title = post.get("title", "")
        selftext = post.get("selftext", "")

        # Truncate selftext for prompt efficiency
        if len(selftext) > 500:
            selftext = selftext[:500] + "..."

        lines.append(
            f"[{i}] r/{sub} | score:{score} comments:{comments}\n"
            f"Title: {title}\n"
            f"{selftext}\n"
        )
    return "\n---\n".join(lines)


def _parse_llm_response(response_text: str) -> dict[str, Any]:
    """Parse the JSON response from Claude, handling edge cases.

    Args:
        response_text: Raw text response from Claude.

    Returns:
        Parsed dict with tickers, themes, and mood.
    """
    text = response_text.strip()

    # Strip markdown code fences if present
    if text.startswith("```"):
        # Remove opening fence (with optional language tag)
        first_newline = text.index("\n") if "\n" in text else 3
        text = text[first_newline + 1:]
        # Remove closing fence
        if text.endswith("```"):
            text = text[:-3].strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        log.error("Failed to parse LLM JSON response: %s", e)
        log.debug("Raw response: %s", response_text[:500])
        return {"tickers": [], "overall_themes": [], "market_mood": "unknown"}

    # Validate structure
    if "tickers" not in data:
        data["tickers"] = []
    if "overall_themes" not in data:
        data["overall_themes"] = []
    if "market_mood" not in data:
        data["market_mood"] = "unknown"

    return data


def _validate_ticker_symbol(symbol: str) -> str | None:
    """Validate and sanitize a ticker symbol.

    Args:
        symbol: Raw ticker symbol string.

    Returns:
        Sanitized uppercase ticker, or None if invalid.
    """
    # Common false positives to reject
    false_positives = {
        "IT", "A", "BE", "SO", "ALL", "FOR", "ARE", "CEO", "IPO", "ETF",
        "DD", "OP", "PM", "AM", "US", "UK", "EU", "AI", "EV", "WSB",
        "IMO", "FYI", "TBH", "LOL", "OMG", "WTF", "YOLO", "FOMO",
        "GDP", "CPI", "FED", "SEC", "FDA", "DOJ", "ATH", "ATL",
        "OTC", "NYSE", "HODL", "DCA", "RIP", "NFT", "APR", "APY",
    }

    if not symbol or not isinstance(symbol, str):
        return None

    try:
        cleaned = sanitize_ticker(symbol)
    except ValueError:
        return None

    if cleaned in false_positives:
        return None

    # Must be 1-5 chars (allowing dot for BRK.B style)
    alpha_part = cleaned.replace(".", "")
    if len(alpha_part) < 1 or len(alpha_part) > 5:
        return None

    return cleaned


def _analyze_batch(
    posts: list[dict[str, Any]],
    known_tickers: list[str],
    client: anthropic.Anthropic,
) -> dict[str, Any]:
    """Analyze a single batch of posts using Gemini.

    Args:
        posts: Batch of post dicts to analyze.
        known_tickers: List of known portfolio/watchlist tickers.
        client: Gemini compatibility client.

    Returns:
        Parsed analysis results dict.
    """
    # Check budget before making API call
    within_budget, spent, cap = check_budget()
    if not within_budget:
        log.warning(
            "Budget exceeded ($%.2f / $%.2f) — skipping analysis batch",
            spent, cap,
        )
        return {"tickers": [], "overall_themes": [], "market_mood": "unknown"}

    posts_text = _format_posts_for_prompt(posts)
    tickers_str = ", ".join(known_tickers[:50]) if known_tickers else "none specified"

    prompt = ANALYSIS_PROMPT.format(
        posts_text=posts_text,
        known_tickers=tickers_str,
    )

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
    except anthropic.APIError as e:
        log.error("Gemini API error: %s", e)
        return {"tickers": [], "overall_themes": [], "market_mood": "unknown"}

    # Track costs
    usage = response.usage
    record_usage(AGENT_NAME, usage.input_tokens, usage.output_tokens, model=MODEL)

    # Extract text from response
    response_text = ""
    for block in response.content:
        if block.type == "text":
            response_text += block.text

    return _parse_llm_response(response_text)


def _aggregate_results(
    batch_results: list[dict[str, Any]],
) -> dict[str, Any]:
    """Aggregate analysis results from multiple batches into per-ticker summaries.

    Args:
        batch_results: List of parsed result dicts from each batch.

    Returns:
        Aggregated dict with:
        - tickers: dict mapping symbol to aggregated stats
        - themes: deduplicated list of overall themes
        - market_mood: most common mood across batches
    """
    ticker_data: dict[str, dict[str, Any]] = {}
    all_themes: list[str] = []
    moods: list[str] = []

    for result in batch_results:
        all_themes.extend(result.get("overall_themes", []))
        mood = result.get("market_mood", "unknown")
        if mood != "unknown":
            moods.append(mood)

        for ticker_info in result.get("tickers", []):
            symbol = _validate_ticker_symbol(ticker_info.get("symbol", ""))
            if not symbol:
                continue

            mentions = ticker_info.get("mentions", 1)
            sentiment = ticker_info.get("sentiment", 0)
            confidence = ticker_info.get("confidence", 0.5)
            themes = ticker_info.get("themes", [])
            quote = ticker_info.get("notable_quote", "")
            subreddits = ticker_info.get("source_subreddits", [])

            if symbol not in ticker_data:
                ticker_data[symbol] = {
                    "symbol": symbol,
                    "total_mentions": 0,
                    "sentiment_sum": 0.0,
                    "confidence_sum": 0.0,
                    "count": 0,  # number of batch appearances for averaging
                    "themes": [],
                    "notable_quotes": [],
                    "subreddits": set(),
                }

            entry = ticker_data[symbol]
            entry["total_mentions"] += mentions
            entry["sentiment_sum"] += sentiment * mentions  # Weight by mentions
            entry["confidence_sum"] += confidence
            entry["count"] += 1
            entry["themes"].extend(themes)
            if quote:
                entry["notable_quotes"].append(quote)
            entry["subreddits"].update(subreddits)

    # Compute averages and finalize
    aggregated_tickers: dict[str, dict[str, Any]] = {}
    for symbol, data in ticker_data.items():
        total = data["total_mentions"]
        aggregated_tickers[symbol] = {
            "symbol": symbol,
            "total_mentions": total,
            "avg_sentiment": round(data["sentiment_sum"] / total, 2) if total > 0 else 0,
            "avg_confidence": round(data["confidence_sum"] / data["count"], 2),
            "themes": list(dict.fromkeys(data["themes"])),  # deduplicate, preserve order
            "notable_quotes": data["notable_quotes"][:3],  # Keep top 3 quotes
            "subreddits": sorted(data["subreddits"]),
        }

    # Deduplicate themes
    unique_themes = list(dict.fromkeys(all_themes))

    # Most common mood
    market_mood = "unknown"
    if moods:
        from collections import Counter
        mood_counts = Counter(moods)
        market_mood = mood_counts.most_common(1)[0][0]

    return {
        "tickers": aggregated_tickers,
        "themes": unique_themes,
        "market_mood": market_mood,
    }


def analyze_posts(posts: list[dict[str, Any]]) -> dict[str, Any]:
    """Analyze Reddit posts using Claude for market intelligence.

    Batches posts into groups and sends each batch to the LLM for analysis.
    Extracts ticker mentions, sentiment, themes, and notable quotes.
    Aggregates results across all batches.

    Args:
        posts: List of post dicts from reddit_fetcher.fetch_posts().

    Returns:
        Aggregated analysis dict with:
        - tickers: dict mapping symbol to {total_mentions, avg_sentiment,
          avg_confidence, themes, notable_quotes, subreddits}
        - themes: list of overall market themes
        - market_mood: string describing general market mood
    """
    if not posts:
        log.warning("No posts to analyze")
        return {"tickers": {}, "themes": [], "market_mood": "unknown"}

    known_tickers = get_all_tickers()
    client = anthropic.Anthropic()

    # Split posts into batches
    batches: list[list[dict[str, Any]]] = []
    for i in range(0, len(posts), BATCH_SIZE):
        batches.append(posts[i:i + BATCH_SIZE])

    log.info(
        "Analyzing %d posts in %d batches (model=%s)",
        len(posts), len(batches), MODEL,
    )

    batch_results: list[dict[str, Any]] = []
    for i, batch in enumerate(batches):
        log.info("Processing batch %d/%d (%d posts)", i + 1, len(batches), len(batch))

        result = _analyze_batch(batch, known_tickers, client)
        batch_results.append(result)

        ticker_count = len(result.get("tickers", []))
        log.info("Batch %d/%d: extracted %d tickers", i + 1, len(batches), ticker_count)

    aggregated = _aggregate_results(batch_results)

    log.info(
        "Analysis complete: %d unique tickers, %d themes, mood=%s",
        len(aggregated["tickers"]),
        len(aggregated["themes"]),
        aggregated["market_mood"],
    )
    return aggregated
