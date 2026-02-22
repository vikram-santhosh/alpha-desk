"""News analysis using Anthropic Claude Opus 4.6 for AlphaDesk News Desk.

Analyzes fetched news articles in batches, scoring each for relevance,
sentiment, urgency, and categorization. Publishes signals to the agent bus
for inter-agent coordination.
"""

import json
from typing import Any

import anthropic

from src.shared.agent_bus import publish
from src.shared.cost_tracker import check_budget, record_usage
from src.utils.logger import get_logger

log = get_logger(__name__)

AGENT_NAME = "news_desk"
MODEL = "claude-opus-4-6"
BATCH_SIZE = 15
MAX_TOKENS = 4096

# System prompt template — portfolio context is injected at runtime
_ANALYSIS_SYSTEM_PROMPT_TEMPLATE = """You are a financial news analyst for AlphaDesk, a personal stock portfolio intelligence system.

Analyze news articles and score each one on multiple dimensions relevant to an individual investor.

PORTFOLIO CONTEXT (use this to assess direct AND indirect impact):
{portfolio_context}

SCORING RULES:
1. **relevance** (0-10): How relevant to this investor's portfolio and market outlook?
   - 9-10: Directly affects a portfolio holding or triggers immediate action
   - 7-8: Affects portfolio sector, macro thesis, or market environment significantly
   - 5-6: Relevant market/economic context worth tracking
   - 3-4: Tangentially related
   - 0-2: Not relevant
   IMPORTANT: Macro-economic events (trade policy, tariffs, sanctions, central bank decisions,
   fiscal policy, geopolitical developments, regulation changes) that affect broad market sectors
   should score 7+ even if no specific tickers are mentioned. An investor with a tech-heavy
   portfolio NEEDS to know about semiconductor tariffs even if "NVDA" isn't in the headline.
2. **sentiment** (-2 to +2): Market sentiment implied. -2 = very bearish, +2 = very bullish.
3. **urgency** ("low", "med", "high"): "high" = breaking/market-moving. Policy changes, trade
   deals, Fed decisions, major earnings surprises, geopolitical escalations are HIGH urgency.
4. **affected_tickers** (list of strings): Tickers directly affected. Also infer indirectly
   affected tickers from the portfolio context (e.g., tariff news → semiconductor holdings).
   Use standard US ticker symbols. Empty list if truly no stocks affected.
5. **category** (string): One of "earnings", "macro", "sector", "company", "regulatory",
   "geopolitical", "market_sentiment", "other".
6. **summary** (string): A concise 1-2 sentence summary focused on the market impact.

Respond with ONLY a JSON array of objects, one per article, in the same order as provided.
Each object must have the keys: relevance, sentiment, urgency, affected_tickers, category, summary."""

# Fallback when portfolio context is unavailable
ANALYSIS_SYSTEM_PROMPT = _ANALYSIS_SYSTEM_PROMPT_TEMPLATE.format(
    portfolio_context="No portfolio context available. Score based on general equity investor relevance."
)


def _prepare_batch_prompt(articles: list[dict[str, Any]]) -> str:
    """Build the user prompt for a batch of articles.

    Args:
        articles: List of normalized article dicts to analyze.

    Returns:
        Formatted string prompt listing all articles for analysis.
    """
    lines = [f"Analyze these {len(articles)} news articles:\n"]

    for i, article in enumerate(articles, 1):
        title = article.get("title", "Untitled")
        source = article.get("source", "Unknown")
        published = article.get("published_at", "Unknown")
        summary = article.get("summary", "No summary available")
        tickers = article.get("related_tickers", [])
        ticker_str = ", ".join(tickers) if tickers else "none"

        lines.append(f"--- Article {i} ---")
        lines.append(f"Title: {title}")
        lines.append(f"Source: {source}")
        lines.append(f"Published: {published}")
        lines.append(f"Related tickers: {ticker_str}")
        lines.append(f"Summary: {summary}")
        lines.append("")

    return "\n".join(lines)


def _parse_analysis_response(response_text: str, batch_size: int) -> list[dict[str, Any]]:
    """Parse Claude's JSON response into a list of analysis dicts.

    Handles edge cases where the response may contain markdown code fences
    or other non-JSON content.

    Args:
        response_text: Raw text response from Claude.
        batch_size: Expected number of articles in the batch, for validation.

    Returns:
        List of analysis dicts with keys: relevance, sentiment, urgency,
        affected_tickers, category, summary.
    """
    text = response_text.strip()

    # Strip markdown code fences if present
    if text.startswith("```"):
        # Remove opening fence (with optional language specifier)
        first_newline = text.index("\n")
        text = text[first_newline + 1:]
    if text.endswith("```"):
        text = text[:-3].strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as e:
        log.error("Failed to parse analysis response as JSON: %s", e)
        log.debug("Response text: %s", text[:500])
        return []

    if not isinstance(parsed, list):
        log.error("Expected a JSON array, got %s", type(parsed).__name__)
        return []

    if len(parsed) != batch_size:
        log.warning(
            "Analysis returned %d results for %d articles; proceeding with available",
            len(parsed),
            batch_size,
        )

    # Validate and sanitize each result
    validated: list[dict[str, Any]] = []
    for item in parsed:
        if not isinstance(item, dict):
            log.warning("Skipping non-dict analysis item: %s", type(item).__name__)
            continue

        validated.append({
            "relevance": _clamp(int(item.get("relevance", 0)), 0, 10),
            "sentiment": _clamp(float(item.get("sentiment", 0)), -2.0, 2.0),
            "urgency": item.get("urgency", "low") if item.get("urgency") in ("low", "med", "high") else "low",
            "affected_tickers": item.get("affected_tickers", []) if isinstance(item.get("affected_tickers"), list) else [],
            "category": item.get("category", "other"),
            "summary": str(item.get("summary", "")),
        })

    return validated


def _clamp(value: int | float, min_val: int | float, max_val: int | float) -> int | float:
    """Clamp a numeric value between min and max bounds.

    Args:
        value: The value to clamp.
        min_val: Minimum allowed value.
        max_val: Maximum allowed value.

    Returns:
        Clamped value.
    """
    return max(min_val, min(max_val, value))


def analyze_batch(
    client: anthropic.Anthropic,
    articles: list[dict[str, Any]],
    system_prompt: str | None = None,
) -> list[dict[str, Any]]:
    """Analyze a single batch of articles using Claude Opus 4.6.

    Sends the batch to Claude for scoring and parses the structured response.
    Tracks API costs and checks budget before making the call.

    Args:
        client: Initialized Anthropic client.
        articles: Batch of normalized article dicts (up to BATCH_SIZE).
        system_prompt: Optional system prompt with portfolio context injected.
            Falls back to ANALYSIS_SYSTEM_PROMPT if not provided.

    Returns:
        List of analysis result dicts, one per article. Returns empty list
        if budget is exceeded or an error occurs.
    """
    # Check budget before making the call
    within_budget, spent, cap = check_budget()
    if not within_budget:
        log.warning(
            "Budget exceeded ($%.2f / $%.2f); skipping analysis batch",
            spent,
            cap,
        )
        return []

    user_prompt = _prepare_batch_prompt(articles)
    prompt_to_use = system_prompt or ANALYSIS_SYSTEM_PROMPT

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=prompt_to_use,
            messages=[{"role": "user", "content": user_prompt}],
        )

        # Track costs
        usage = response.usage
        record_usage(
            agent=AGENT_NAME,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
        )

        # Extract text from response
        response_text = ""
        for block in response.content:
            if block.type == "text":
                response_text += block.text

        results = _parse_analysis_response(response_text, len(articles))
        log.info(
            "Analyzed batch of %d articles (tokens: %d in, %d out)",
            len(articles),
            usage.input_tokens,
            usage.output_tokens,
        )
        return results

    except anthropic.APIStatusError as e:
        log.error("Anthropic API error during analysis: %s (status %d)", e.message, e.status_code)
        return []
    except anthropic.APIConnectionError as e:
        log.error("Anthropic connection error during analysis: %s", e)
        return []
    except Exception as e:
        log.error("Unexpected error during news analysis: %s", e, exc_info=True)
        return []


def _build_portfolio_context() -> str:
    """Build portfolio context string for the analysis prompt.

    Loads holdings and watchlist to give Claude awareness of the investor's
    positions, sectors, and macro exposure — so it can score indirect impact
    (e.g., tariff news → semiconductor holdings).

    Returns:
        Formatted context string describing the portfolio.
    """
    try:
        from src.shared.config_loader import load_portfolio, load_watchlist

        portfolio = load_portfolio()
        watchlist = load_watchlist()

        holdings = portfolio.get("holdings", [])
        watchlist_tickers = watchlist.get("tickers", [])

        if not holdings and not watchlist_tickers:
            return "No portfolio data available."

        lines = []
        if holdings:
            holding_parts = []
            for h in holdings:
                ticker = h.get("ticker", "???")
                category = h.get("category", "")
                thesis = h.get("thesis", "")
                part = f"{ticker} ({category})"
                if thesis:
                    part += f" — {thesis}"
                holding_parts.append(part)
            lines.append(f"Holdings: {', '.join(h.get('ticker', '?') for h in holdings)}")
            lines.append("Details:")
            for part in holding_parts:
                lines.append(f"  - {part}")

        if watchlist_tickers:
            lines.append(f"Watchlist: {', '.join(watchlist_tickers)}")

        lines.append("Portfolio is tech/AI-heavy. Semiconductor, cloud, and AI infrastructure exposure is significant.")
        return "\n".join(lines)

    except Exception as e:
        log.warning("Failed to build portfolio context: %s", e)
        return "Portfolio context unavailable."


def analyze_news(
    articles: list[dict[str, Any]],
    anthropic_key: str,
) -> list[dict[str, Any]]:
    """Analyze all news articles in batches using Claude Opus 4.6.

    Articles are processed in batches of ~15 to optimize API usage.
    Each article is enriched with analysis fields (relevance, sentiment,
    urgency, affected_tickers, category, summary). Articles with
    relevance >= 5 or urgency == "high" are kept; others are filtered out.

    Portfolio context is injected into the system prompt so the LLM can
    infer indirect impact (e.g., tariff news → semiconductor holdings).

    Args:
        articles: List of normalized article dicts from news_fetcher.
        anthropic_key: Anthropic API key for Claude access.

    Returns:
        List of analyzed and filtered article dicts, sorted by relevance
        descending. Each article includes the original fields plus analysis
        fields merged in.
    """
    if not articles:
        log.info("No articles to analyze")
        return []

    if not anthropic_key:
        log.error("Anthropic API key not provided; cannot analyze news")
        return []

    client = anthropic.Anthropic(api_key=anthropic_key)
    analyzed: list[dict[str, Any]] = []

    # Build portfolio-aware system prompt
    portfolio_context = _build_portfolio_context()
    system_prompt = _ANALYSIS_SYSTEM_PROMPT_TEMPLATE.format(portfolio_context=portfolio_context)
    log.info("Portfolio context injected into analysis prompt (%d chars)", len(portfolio_context))

    # Process in batches
    total_batches = (len(articles) + BATCH_SIZE - 1) // BATCH_SIZE
    log.info("Analyzing %d articles in %d batches", len(articles), total_batches)

    for batch_idx in range(0, len(articles), BATCH_SIZE):
        batch = articles[batch_idx : batch_idx + BATCH_SIZE]
        batch_num = (batch_idx // BATCH_SIZE) + 1

        log.info("Processing batch %d/%d (%d articles)", batch_num, total_batches, len(batch))

        results = analyze_batch(client, batch, system_prompt=system_prompt)

        if not results:
            log.warning("Batch %d returned no results; skipping", batch_num)
            continue

        # Merge analysis into article dicts
        for article, analysis in zip(batch, results):
            enriched = {**article, **analysis}

            # Merge affected_tickers with existing related_tickers
            existing_tickers = article.get("related_tickers", [])
            analysis_tickers = analysis.get("affected_tickers", [])
            merged_tickers = list(dict.fromkeys(existing_tickers + analysis_tickers))
            enriched["related_tickers"] = merged_tickers

            analyzed.append(enriched)

    # Filter: keep articles with relevance >= 5 or urgency == "high"
    filtered = [
        a for a in analyzed
        if a.get("relevance", 0) >= 5 or a.get("urgency") == "high"
    ]

    log.info(
        "Analysis complete: %d analyzed, %d passed filter (relevance>=5 or urgency=high)",
        len(analyzed),
        len(filtered),
    )

    # Sort by relevance descending, then urgency
    urgency_order = {"high": 0, "med": 1, "low": 2}
    filtered.sort(
        key=lambda a: (-a.get("relevance", 0), urgency_order.get(a.get("urgency", "low"), 2)),
    )

    return filtered


def publish_signals(articles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Publish relevant signals to the agent bus based on analyzed articles.

    Publishes four types of signals:
    - "breaking_news": High-urgency articles (urgency == "high")
    - "earnings_approaching": Articles with category "earnings"
    - "sector_news": Articles with category "sector" and relevance >= 7
    - "macro_event": Macro/geopolitical/regulatory articles with relevance >= 6

    Args:
        articles: List of analyzed and filtered article dicts.

    Returns:
        List of published signal dicts for tracking.
    """
    signals: list[dict[str, Any]] = []

    for article in articles:
        urgency = article.get("urgency", "low")
        category = article.get("category", "other")
        relevance = article.get("relevance", 0)

        # Breaking news: high urgency articles
        if urgency == "high":
            payload = {
                "title": article.get("title", ""),
                "url": article.get("url", ""),
                "summary": article.get("summary", ""),
                "sentiment": article.get("sentiment", 0),
                "affected_tickers": article.get("related_tickers", []),
                "source": article.get("source", ""),
            }
            try:
                signal_id = publish("breaking_news", AGENT_NAME, payload)
                signals.append({
                    "id": signal_id,
                    "type": "breaking_news",
                    "title": article.get("title", ""),
                })
            except Exception as e:
                log.error("Failed to publish breaking_news signal: %s", e)

        # Earnings approaching
        if category == "earnings":
            payload = {
                "title": article.get("title", ""),
                "url": article.get("url", ""),
                "summary": article.get("summary", ""),
                "affected_tickers": article.get("related_tickers", []),
                "source": article.get("source", ""),
            }
            try:
                signal_id = publish("earnings_approaching", AGENT_NAME, payload)
                signals.append({
                    "id": signal_id,
                    "type": "earnings_approaching",
                    "title": article.get("title", ""),
                })
            except Exception as e:
                log.error("Failed to publish earnings_approaching signal: %s", e)

        # Sector news: high-relevance sector articles
        if category == "sector" and relevance >= 7:
            payload = {
                "title": article.get("title", ""),
                "url": article.get("url", ""),
                "summary": article.get("summary", ""),
                "sentiment": article.get("sentiment", 0),
                "affected_tickers": article.get("related_tickers", []),
                "source": article.get("source", ""),
            }
            try:
                signal_id = publish("sector_news", AGENT_NAME, payload)
                signals.append({
                    "id": signal_id,
                    "type": "sector_news",
                    "title": article.get("title", ""),
                })
            except Exception as e:
                log.error("Failed to publish sector_news signal: %s", e)

        # Macro/geopolitical/regulatory events: broad market impact
        # Publish if relevance >= 6 OR urgency is high (e.g., emergency Fed action
        # or geopolitical escalation that might score relevance 5 but is urgent)
        if category in ("macro", "geopolitical", "regulatory") and (relevance >= 6 or urgency == "high"):
            payload = {
                "title": article.get("title", ""),
                "url": article.get("url", ""),
                "summary": article.get("summary", ""),
                "sentiment": article.get("sentiment", 0),
                "affected_tickers": article.get("related_tickers", []),
                "source": article.get("source", ""),
                "category": category,
            }
            try:
                signal_id = publish("macro_event", AGENT_NAME, payload)
                signals.append({
                    "id": signal_id,
                    "type": "macro_event",
                    "title": article.get("title", ""),
                })
            except Exception as e:
                log.error("Failed to publish macro_event signal: %s", e)

    log.info("Published %d signals to agent bus", len(signals))
    return signals
