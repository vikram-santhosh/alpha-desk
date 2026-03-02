"""Gemini analysis of YouTube video transcripts for YouTube Ear.

Batches video transcripts and sends them to Gemini for extraction of
ticker mentions, sentiment, confidence, themes, theses, and macro signals.
Aggregates results across batches into per-ticker summaries.

Uses the lightweight Gemini path for cost efficiency — transcripts are long but extraction is
structured, not creative reasoning.
"""

import json
from typing import Any

from src.shared import gemini_compat as anthropic

from src.shared.config_loader import get_all_tickers
from src.shared.cost_tracker import check_budget, record_usage
from src.shared.security import sanitize_ticker
from src.utils.logger import get_logger

log = get_logger(__name__)

MODEL = "claude-haiku-4-5"
AGENT_NAME = "youtube_ear"
BATCH_SIZE = 4
MAX_TOKENS = 4096

SYSTEM_PROMPT = """You are a financial market analyst specializing in extracting investment intelligence from YouTube video transcripts.

IMPORTANT RULES FOR TRANSCRIPT ANALYSIS:
- Transcripts are auto-generated and may contain errors, filler words, and unclear segments
- Ignore sponsor segments, self-promotion, and channel plugs
- Verbal hedging ("I think", "maybe", "could be") should reduce confidence scores
- Only extract actual stock ticker symbols (e.g., AAPL, TSLA, NVDA), not random abbreviations
- Validate tickers: they should be 1-5 uppercase letters, optionally with a dot (e.g., BRK.B)
- Ignore common words that look like tickers (e.g., IT, A, BE, SO, ALL, FOR, ARE, CEO, IPO, ETF)
- Sentiment scale: -2 (very bearish), -1 (bearish), 0 (neutral), +1 (bullish), +2 (very bullish)
- Confidence scale: 0.0 (low) to 1.0 (high) — based on how clear and well-argued the position is
- For theses: extract the core investment argument, not just a summary
- Be concise with themes and quotes"""

ANALYSIS_PROMPT = """Analyze these YouTube video transcripts for stock market intelligence.

Videos:
{videos_text}

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
      "source_channels": ["Patrick Boyle", "Joseph Carlson"]
    }}
  ],
  "theses": [
    {{
      "ticker": "AAPL",
      "direction": "bullish",
      "thesis": "Core investment argument in 1-2 sentences",
      "confidence": 0.8,
      "source": "Channel Name",
      "themes": ["AI", "services growth"]
    }}
  ],
  "macro_signals": ["rate cut expectations building", "inflation cooling"],
  "overall_themes": ["AI infrastructure spending", "rate cut expectations"],
  "market_mood": "cautiously bullish"
}}

Only include tickers that are actually discussed (not just name-dropped). Be precise with sentiment scores.
Return ONLY the JSON object, no other text."""


def _format_videos_for_prompt(videos: list[dict[str, Any]]) -> str:
    """Format a batch of videos into a readable text block for the prompt.

    Args:
        videos: List of video dicts from youtube_fetcher.

    Returns:
        Formatted string with numbered videos.
    """
    lines: list[str] = []
    for i, video in enumerate(videos, 1):
        channel = video.get("subreddit", "unknown")
        views = video.get("score", 0)
        comments = video.get("num_comments", 0)
        title = video.get("title", "")
        transcript = video.get("selftext", "")
        duration = video.get("duration_seconds", 0)

        # Truncate transcript for prompt efficiency
        if len(transcript) > 4000:
            transcript = transcript[:4000] + "..."

        duration_str = f"{duration // 60}m{duration % 60}s" if duration else "unknown"

        lines.append(
            f"[{i}] {channel} | views:{views:,} comments:{comments} duration:{duration_str}\n"
            f"Title: {title}\n"
            f"Transcript:\n{transcript}\n"
        )
    return "\n---\n".join(lines)


def _parse_llm_response(response_text: str) -> dict[str, Any]:
    """Parse the JSON response from Claude, handling edge cases.

    Args:
        response_text: Raw text response from Claude.

    Returns:
        Parsed dict with tickers, theses, themes, and mood.
    """
    text = response_text.strip()

    # Strip markdown code fences if present
    if text.startswith("```"):
        first_newline = text.index("\n") if "\n" in text else 3
        text = text[first_newline + 1:]
        if text.endswith("```"):
            text = text[:-3].strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        log.error("Failed to parse LLM JSON response: %s", e)
        log.debug("Raw response: %s", response_text[:500])
        return {
            "tickers": [],
            "theses": [],
            "macro_signals": [],
            "overall_themes": [],
            "market_mood": "unknown",
        }

    # Validate structure
    if "tickers" not in data:
        data["tickers"] = []
    if "theses" not in data:
        data["theses"] = []
    if "macro_signals" not in data:
        data["macro_signals"] = []
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

    alpha_part = cleaned.replace(".", "")
    if len(alpha_part) < 1 or len(alpha_part) > 5:
        return None

    return cleaned


def _analyze_batch(
    videos: list[dict[str, Any]],
    known_tickers: list[str],
    client: anthropic.Anthropic,
) -> dict[str, Any]:
    """Analyze a single batch of videos using Claude.

    Args:
        videos: Batch of video dicts to analyze.
        known_tickers: List of known portfolio/watchlist tickers.
        client: Gemini compatibility client.

    Returns:
        Parsed analysis results dict.
    """
    within_budget, spent, cap = check_budget()
    if not within_budget:
        log.warning(
            "Budget exceeded ($%.2f / $%.2f) — skipping analysis batch",
            spent, cap,
        )
        return {
            "tickers": [],
            "theses": [],
            "macro_signals": [],
            "overall_themes": [],
            "market_mood": "unknown",
        }

    videos_text = _format_videos_for_prompt(videos)
    tickers_str = ", ".join(known_tickers[:50]) if known_tickers else "none specified"

    prompt = ANALYSIS_PROMPT.format(
        videos_text=videos_text,
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
        return {
            "tickers": [],
            "theses": [],
            "macro_signals": [],
            "overall_themes": [],
            "market_mood": "unknown",
        }

    # Track costs
    usage = response.usage
    record_usage(AGENT_NAME, usage.input_tokens, usage.output_tokens, model=MODEL)

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
        Aggregated dict with tickers, theses, macro_signals, themes, market_mood.
    """
    ticker_data: dict[str, dict[str, Any]] = {}
    all_themes: list[str] = []
    all_theses: list[dict[str, Any]] = []
    all_macro_signals: list[str] = []
    moods: list[str] = []

    for result in batch_results:
        all_themes.extend(result.get("overall_themes", []))
        all_macro_signals.extend(result.get("macro_signals", []))
        all_theses.extend(result.get("theses", []))
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
            channels = ticker_info.get("source_channels", [])

            if symbol not in ticker_data:
                ticker_data[symbol] = {
                    "symbol": symbol,
                    "total_mentions": 0,
                    "sentiment_sum": 0.0,
                    "confidence_sum": 0.0,
                    "count": 0,
                    "themes": [],
                    "notable_quotes": [],
                    "channels": set(),
                }

            entry = ticker_data[symbol]
            entry["total_mentions"] += mentions
            entry["sentiment_sum"] += sentiment * mentions
            entry["confidence_sum"] += confidence
            entry["count"] += 1
            entry["themes"].extend(themes)
            if quote:
                entry["notable_quotes"].append(quote)
            entry["channels"].update(channels)

    # Compute averages and finalize
    aggregated_tickers: dict[str, dict[str, Any]] = {}
    for symbol, data in ticker_data.items():
        total = data["total_mentions"]
        aggregated_tickers[symbol] = {
            "symbol": symbol,
            "total_mentions": total,
            "avg_sentiment": round(data["sentiment_sum"] / total, 2) if total > 0 else 0,
            "avg_confidence": round(data["confidence_sum"] / data["count"], 2),
            "themes": list(dict.fromkeys(data["themes"])),
            "notable_quotes": data["notable_quotes"][:3],
            "channels": sorted(data["channels"]),
        }

    # Deduplicate
    unique_themes = list(dict.fromkeys(all_themes))
    unique_macro = list(dict.fromkeys(all_macro_signals))

    # Validate theses ticker symbols
    valid_theses: list[dict[str, Any]] = []
    for thesis in all_theses:
        ticker = _validate_ticker_symbol(thesis.get("ticker", ""))
        if ticker:
            thesis["ticker"] = ticker
            valid_theses.append(thesis)

    # Most common mood
    market_mood = "unknown"
    if moods:
        from collections import Counter
        mood_counts = Counter(moods)
        market_mood = mood_counts.most_common(1)[0][0]

    return {
        "tickers": aggregated_tickers,
        "theses": valid_theses,
        "macro_signals": unique_macro,
        "themes": unique_themes,
        "market_mood": market_mood,
    }


def analyze_videos(videos: list[dict[str, Any]]) -> dict[str, Any]:
    """Analyze YouTube video transcripts using Claude for market intelligence.

    Batches videos into groups and sends each batch to the LLM for analysis.
    Extracts ticker mentions, sentiment, theses, macro signals, and themes.
    Aggregates results across all batches.

    Args:
        videos: List of video dicts from youtube_fetcher.fetch_videos().

    Returns:
        Aggregated analysis dict with:
        - tickers: dict mapping symbol to {total_mentions, avg_sentiment,
          avg_confidence, themes, notable_quotes, channels}
        - theses: list of thesis dicts
        - macro_signals: list of macro signal strings
        - themes: list of overall market themes
        - market_mood: string describing general market mood
    """
    if not videos:
        log.warning("No videos to analyze")
        return {
            "tickers": {},
            "theses": [],
            "macro_signals": [],
            "themes": [],
            "market_mood": "unknown",
        }

    known_tickers = get_all_tickers()
    client = anthropic.Anthropic()

    # Split videos into batches (smaller batches since transcripts are long)
    batches: list[list[dict[str, Any]]] = []
    for i in range(0, len(videos), BATCH_SIZE):
        batches.append(videos[i:i + BATCH_SIZE])

    log.info(
        "Analyzing %d videos in %d batches (model=%s)",
        len(videos), len(batches), MODEL,
    )

    batch_results: list[dict[str, Any]] = []
    for i, batch in enumerate(batches):
        log.info("Processing batch %d/%d (%d videos)", i + 1, len(batches), len(batch))

        result = _analyze_batch(batch, known_tickers, client)
        batch_results.append(result)

        ticker_count = len(result.get("tickers", []))
        log.info("Batch %d/%d: extracted %d tickers", i + 1, len(batches), ticker_count)

    aggregated = _aggregate_results(batch_results)

    log.info(
        "Analysis complete: %d unique tickers, %d theses, %d themes, mood=%s",
        len(aggregated["tickers"]),
        len(aggregated["theses"]),
        len(aggregated["themes"]),
        aggregated["market_mood"],
    )
    return aggregated
