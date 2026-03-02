"""Gemini analysis of Substack articles for Substack Ear.

Analyzes expert newsletter articles individually or in small batches
using Gemini for cost-efficient extraction of investment theses,
macro signals, and ticker mentions.
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
AGENT_NAME = "substack_ear"
BATCH_SIZE = 3
MAX_TOKENS = 4096

# Common false positives to reject
_FALSE_POSITIVES = {
    "IT", "A", "BE", "SO", "ALL", "FOR", "ARE", "CEO", "IPO", "ETF",
    "DD", "OP", "PM", "AM", "US", "UK", "EU", "AI", "EV", "WSB",
    "IMO", "FYI", "TBH", "LOL", "OMG", "WTF", "YOLO", "FOMO",
    "GDP", "CPI", "FED", "SEC", "FDA", "DOJ", "ATH", "ATL",
    "OTC", "NYSE", "HODL", "DCA", "RIP", "NFT", "APR", "APY",
}

SYSTEM_PROMPT = """You are a financial market analyst specializing in expert newsletter analysis.
You analyze articles from top financial Substack authors to extract investment theses,
macro frameworks, and actionable ticker mentions.

IMPORTANT RULES:
- These are expert-written analyses, not retail sentiment — treat them as high-signal sources
- Extract concrete investment theses with conviction levels and time horizons
- Identify macro signals and framework shifts
- Only extract actual stock ticker symbols (e.g., AAPL, TSLA, NVDA), not abbreviations
- Validate tickers: 1-5 uppercase letters, optionally with a dot (e.g., BRK.B)
- Ignore common words that look like tickers (IT, A, BE, SO, ALL, CEO, IPO, ETF, etc.)
- Sentiment scale: -2 (very bearish) to +2 (very bullish)
- Confidence scale: 0.0 to 1.0
- Flag contrarian views explicitly"""

ANALYSIS_PROMPT = """Analyze these expert newsletter articles for investment intelligence.

Articles:
{articles_text}

Known portfolio/watchlist tickers for reference: {known_tickers}

Return a JSON object with this exact structure:
{{
  "tickers": [
    {{
      "symbol": "AAPL",
      "sentiment": 1.5,
      "confidence": 0.8,
      "themes": ["strong earnings", "AI integration"],
      "source_publication": "The Diff"
    }}
  ],
  "theses": [
    {{
      "title": "Short thesis title",
      "summary": "2-3 sentence summary of the investment thesis",
      "affected_tickers": ["AAPL", "MSFT"],
      "conviction": "high",
      "time_horizon": "medium_term",
      "contrarian": false
    }}
  ],
  "macro_signals": [
    {{
      "indicator": "Yield curve",
      "implication": "Recession risk rising",
      "affected_sectors": ["financials", "real_estate"]
    }}
  ],
  "overall_themes": ["AI infrastructure spending", "rate cut expectations"],
  "market_mood": "cautiously bullish"
}}

Only include tickers actually mentioned. Be precise with sentiment scores.
conviction: "low", "medium", or "high"
time_horizon: "short_term" (days-weeks), "medium_term" (weeks-months), "long_term" (months-years)
Return ONLY the JSON object, no other text."""


def _validate_ticker_symbol(symbol: str) -> str | None:
    """Validate and sanitize a ticker symbol.

    Returns:
        Sanitized uppercase ticker, or None if invalid.
    """
    if not symbol or not isinstance(symbol, str):
        return None

    try:
        cleaned = sanitize_ticker(symbol)
    except ValueError:
        return None

    if cleaned in _FALSE_POSITIVES:
        return None

    alpha_part = cleaned.replace(".", "")
    if len(alpha_part) < 1 or len(alpha_part) > 5:
        return None

    return cleaned


def _format_articles_for_prompt(articles: list[dict[str, Any]]) -> str:
    """Format a batch of articles into a readable text block for the prompt."""
    lines: list[str] = []
    for i, article in enumerate(articles, 1):
        pub = article.get("subreddit", "unknown")
        author = article.get("author", "unknown")
        title = article.get("title", "")
        selftext = article.get("selftext", "")

        # Truncate selftext for prompt efficiency — keep more than Reddit (expert content)
        if len(selftext) > 2000:
            selftext = selftext[:2000] + "..."

        lines.append(
            f"[{i}] {pub} by {author}\n"
            f"Title: {title}\n"
            f"{selftext}\n"
        )
    return "\n---\n".join(lines)


def _parse_llm_response(response_text: str) -> dict[str, Any]:
    """Parse the JSON response from Claude, handling edge cases."""
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
            "tickers": [], "theses": [], "macro_signals": [],
            "overall_themes": [], "market_mood": "unknown",
        }

    # Validate structure
    for key in ("tickers", "theses", "macro_signals", "overall_themes"):
        if key not in data:
            data[key] = []
    if "market_mood" not in data:
        data["market_mood"] = "unknown"

    return data


def _analyze_batch(
    articles: list[dict[str, Any]],
    known_tickers: list[str],
    client: anthropic.Anthropic,
) -> dict[str, Any]:
    """Analyze a single batch of articles using Claude."""
    within_budget, spent, cap = check_budget()
    if not within_budget:
        log.warning(
            "Budget exceeded ($%.2f / $%.2f) — skipping analysis batch",
            spent, cap,
        )
        return {
            "tickers": [], "theses": [], "macro_signals": [],
            "overall_themes": [], "market_mood": "unknown",
        }

    articles_text = _format_articles_for_prompt(articles)
    tickers_str = ", ".join(known_tickers[:50]) if known_tickers else "none specified"

    prompt = ANALYSIS_PROMPT.format(
        articles_text=articles_text,
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
            "tickers": [], "theses": [], "macro_signals": [],
            "overall_themes": [], "market_mood": "unknown",
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
    """Aggregate analysis results from multiple batches."""
    ticker_data: dict[str, dict[str, Any]] = {}
    all_themes: list[str] = []
    all_theses: list[dict[str, Any]] = []
    all_macro_signals: list[dict[str, Any]] = []
    moods: list[str] = []

    for result in batch_results:
        all_themes.extend(result.get("overall_themes", []))
        all_theses.extend(result.get("theses", []))
        all_macro_signals.extend(result.get("macro_signals", []))

        mood = result.get("market_mood", "unknown")
        if mood != "unknown":
            moods.append(mood)

        for ticker_info in result.get("tickers", []):
            symbol = _validate_ticker_symbol(ticker_info.get("symbol", ""))
            if not symbol:
                continue

            sentiment = ticker_info.get("sentiment", 0)
            confidence = ticker_info.get("confidence", 0.5)
            themes = ticker_info.get("themes", [])
            source_pub = ticker_info.get("source_publication", "")

            if symbol not in ticker_data:
                ticker_data[symbol] = {
                    "symbol": symbol,
                    "sentiment_sum": 0.0,
                    "confidence_sum": 0.0,
                    "count": 0,
                    "themes": [],
                    "source_publications": set(),
                }

            entry = ticker_data[symbol]
            entry["sentiment_sum"] += sentiment
            entry["confidence_sum"] += confidence
            entry["count"] += 1
            entry["themes"].extend(themes)
            if source_pub:
                entry["source_publications"].add(source_pub)

    # Compute averages and finalize
    aggregated_tickers: dict[str, dict[str, Any]] = {}
    for symbol, data in ticker_data.items():
        count = data["count"]
        aggregated_tickers[symbol] = {
            "symbol": symbol,
            "total_mentions": count,
            "avg_sentiment": round(data["sentiment_sum"] / count, 2) if count > 0 else 0,
            "avg_confidence": round(data["confidence_sum"] / count, 2),
            "themes": list(dict.fromkeys(data["themes"])),
            "source_publications": sorted(data["source_publications"]),
        }

    # Validate tickers in theses
    for thesis in all_theses:
        validated = []
        for t in thesis.get("affected_tickers", []):
            v = _validate_ticker_symbol(t)
            if v:
                validated.append(v)
        thesis["affected_tickers"] = validated

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
        "theses": all_theses,
        "macro_signals": all_macro_signals,
        "market_mood": market_mood,
    }


def analyze_articles(articles: list[dict[str, Any]]) -> dict[str, Any]:
    """Analyze Substack articles using Claude for investment intelligence.

    Batches articles into small groups and sends each batch to Gemini
    for extraction of theses, macro signals, and ticker mentions.

    Args:
        articles: List of article dicts from substack_fetcher.fetch_articles().

    Returns:
        Aggregated analysis dict with:
        - tickers: dict mapping symbol to aggregated stats
        - themes: list of overall themes
        - theses: list of investment thesis dicts
        - macro_signals: list of macro signal dicts
        - market_mood: string describing general market mood
    """
    if not articles:
        log.warning("No articles to analyze")
        return {
            "tickers": {}, "themes": [], "theses": [],
            "macro_signals": [], "market_mood": "unknown",
        }

    known_tickers = get_all_tickers()
    client = anthropic.Anthropic()

    # Split articles into small batches (1-3 per batch for expert content)
    batches: list[list[dict[str, Any]]] = []
    for i in range(0, len(articles), BATCH_SIZE):
        batches.append(articles[i:i + BATCH_SIZE])

    log.info(
        "Analyzing %d articles in %d batches (model=%s)",
        len(articles), len(batches), MODEL,
    )

    batch_results: list[dict[str, Any]] = []
    for i, batch in enumerate(batches):
        log.info("Processing batch %d/%d (%d articles)", i + 1, len(batches), len(batch))

        result = _analyze_batch(batch, known_tickers, client)
        batch_results.append(result)

        ticker_count = len(result.get("tickers", []))
        thesis_count = len(result.get("theses", []))
        log.info("Batch %d/%d: %d tickers, %d theses", i + 1, len(batches), ticker_count, thesis_count)

    aggregated = _aggregate_results(batch_results)

    log.info(
        "Analysis complete: %d tickers, %d theses, %d macro signals, mood=%s",
        len(aggregated["tickers"]),
        len(aggregated["theses"]),
        len(aggregated["macro_signals"]),
        aggregated["market_mood"],
    )
    return aggregated
