"""News fetching from Finnhub and NewsAPI for AlphaDesk News Desk.

Supports two data sources:
- Finnhub: stock-specific company news for portfolio and watchlist tickers
- NewsAPI: business headlines and market-wide news search

Both sources are fetched with proper rate limiting, error handling,
and graceful degradation when API keys are missing.
"""
from __future__ import annotations

import time
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from typing import Any

import requests

from src.shared.security import sanitize_html
from src.utils.logger import get_logger

log = get_logger(__name__)

# Timeouts and rate limits
HTTP_TIMEOUT = 10  # seconds
FINNHUB_DELAY = 1.0  # seconds between Finnhub calls (60 calls/min free tier)
FINNHUB_BASE_URL = "https://finnhub.io/api/v1/company-news"
NEWSAPI_HEADLINES_URL = "https://newsapi.org/v2/top-headlines"
NEWSAPI_EVERYTHING_URL = "https://newsapi.org/v2/everything"
ARTICLE_CONTENT_CAP = 1200
SEMANTIC_DUPLICATE_THRESHOLD = 0.7


def _normalize_finnhub_article(article: dict[str, Any], ticker: str) -> dict[str, Any]:
    """Normalize a Finnhub article into our standard schema.

    Args:
        article: Raw article dict from the Finnhub API.
        ticker: The ticker symbol this article was fetched for.

    Returns:
        Normalized article dict with consistent fields.
    """
    # Finnhub uses Unix timestamps
    pub_datetime = datetime.fromtimestamp(article.get("datetime", 0))

    return {
        "title": sanitize_html(article.get("headline", "Untitled")),
        "url": article.get("url", ""),
        "source": article.get("source", "Unknown"),
        "published_at": pub_datetime.isoformat(),
        "published_ts": article.get("datetime", 0),
        "summary": sanitize_html((article.get("summary", "") or "")[:ARTICLE_CONTENT_CAP]),
        "category": article.get("category", "general"),
        "related_tickers": [ticker],
        "origin": "finnhub",
        "image": article.get("image", ""),
        "finnhub_id": article.get("id", None),
    }


def _normalize_newsapi_article(article: dict[str, Any]) -> dict[str, Any]:
    """Normalize a NewsAPI article into our standard schema.

    Args:
        article: Raw article dict from the NewsAPI response.

    Returns:
        Normalized article dict with consistent fields.
    """
    # NewsAPI uses ISO datetime strings
    pub_str = article.get("publishedAt", "")
    try:
        pub_datetime = datetime.fromisoformat(pub_str.replace("Z", "+00:00"))
        pub_ts = int(pub_datetime.timestamp())
    except (ValueError, AttributeError):
        pub_datetime = datetime.now()
        pub_ts = int(pub_datetime.timestamp())

    source_name = "Unknown"
    if isinstance(article.get("source"), dict):
        source_name = article["source"].get("name", "Unknown")
    elif isinstance(article.get("source"), str):
        source_name = article["source"]

    return {
        "title": sanitize_html(article.get("title") or "Untitled"),
        "url": article.get("url", ""),
        "source": source_name,
        "published_at": pub_datetime.isoformat(),
        "published_ts": pub_ts,
        "summary": sanitize_html((article.get("description") or "")[:ARTICLE_CONTENT_CAP]),
        "category": "market",
        "related_tickers": [],
        "origin": "newsapi",
        "image": article.get("urlToImage", ""),
        "finnhub_id": None,
    }


def fetch_finnhub_news(
    tickers: list[str],
    api_key: str,
    days: int = 3,
) -> list[dict[str, Any]]:
    """Fetch company news from Finnhub for each ticker.

    Iterates over each ticker symbol, fetching news from the last `days` days.
    Includes a 1-second delay between requests to respect the free tier rate limit
    of 60 calls/minute.

    Args:
        tickers: List of stock ticker symbols to fetch news for.
        api_key: Finnhub API key.
        days: Number of days of history to fetch (default 3).

    Returns:
        List of normalized article dicts, sorted by datetime descending.
    """
    if not api_key:
        log.warning("Finnhub API key not provided; skipping Finnhub news fetch")
        return []

    if not tickers:
        log.info("No tickers provided for Finnhub news fetch")
        return []

    articles: list[dict[str, Any]] = []
    date_to = datetime.now().strftime("%Y-%m-%d")
    date_from = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    log.info(
        "Fetching Finnhub news for %d tickers (%s to %s)",
        len(tickers),
        date_from,
        date_to,
    )

    for i, ticker in enumerate(tickers):
        try:
            params = {
                "symbol": ticker,
                "from": date_from,
                "to": date_to,
                "token": api_key,
            }

            response = requests.get(
                FINNHUB_BASE_URL,
                params=params,
                timeout=HTTP_TIMEOUT,
            )
            response.raise_for_status()

            data = response.json()
            if not isinstance(data, list):
                log.warning("Unexpected Finnhub response for %s: %s", ticker, type(data))
                continue

            ticker_articles = [_normalize_finnhub_article(a, ticker) for a in data]
            articles.extend(ticker_articles)
            log.info("Finnhub: %d articles for %s", len(ticker_articles), ticker)

        except requests.exceptions.HTTPError as e:
            status_code = e.response.status_code if e.response is not None else 0
            if status_code == 429:
                log.warning("Finnhub rate limit hit at ticker %s; stopping fetch", ticker)
                break
            elif status_code == 401:
                log.error("Finnhub authentication failed; invalid API key")
                break
            else:
                log.error("Finnhub HTTP error for %s: %s", ticker, e)
        except requests.exceptions.Timeout:
            log.warning("Finnhub timeout for %s; skipping", ticker)
        except requests.exceptions.RequestException as e:
            log.error("Finnhub request error for %s: %s", ticker, e)
        except (ValueError, KeyError) as e:
            log.error("Finnhub parsing error for %s: %s", ticker, e)

        # Rate limit: 1s between calls (skip delay after last ticker)
        if i < len(tickers) - 1:
            time.sleep(FINNHUB_DELAY)

    log.info("Finnhub: fetched %d total articles across %d tickers", len(articles), len(tickers))
    return articles


def fetch_newsapi_headlines(api_key: str) -> list[dict[str, Any]]:
    """Fetch top US business headlines from NewsAPI.

    Uses the /v2/top-headlines endpoint with category=business, country=us.
    This counts as 1 of the 100 daily free-tier calls.

    Args:
        api_key: NewsAPI API key.

    Returns:
        List of normalized article dicts.
    """
    if not api_key:
        log.warning("NewsAPI key not provided; skipping headlines fetch")
        return []

    try:
        params = {
            "category": "business",
            "country": "us",
            "pageSize": 50,
            "apiKey": api_key,
        }

        response = requests.get(
            NEWSAPI_HEADLINES_URL,
            params=params,
            timeout=HTTP_TIMEOUT,
        )
        response.raise_for_status()

        data = response.json()
        if data.get("status") != "ok":
            log.error("NewsAPI headlines error: %s", data.get("message", "Unknown error"))
            return []

        raw_articles = data.get("articles", [])
        articles = [_normalize_newsapi_article(a) for a in raw_articles]
        log.info("NewsAPI headlines: %d articles", len(articles))
        return articles

    except requests.exceptions.HTTPError as e:
        status_code = e.response.status_code if e.response is not None else 0
        if status_code == 429:
            log.warning("NewsAPI rate limit reached for headlines")
        elif status_code == 401:
            log.error("NewsAPI authentication failed; invalid API key")
        else:
            log.error("NewsAPI headlines HTTP error: %s", e)
    except requests.exceptions.Timeout:
        log.warning("NewsAPI headlines request timed out")
    except requests.exceptions.RequestException as e:
        log.error("NewsAPI headlines request error: %s", e)
    except (ValueError, KeyError) as e:
        log.error("NewsAPI headlines parsing error: %s", e)

    return []


def fetch_newsapi_market(api_key: str, query: str) -> list[dict[str, Any]]:
    """Search NewsAPI /v2/everything for market-related news.

    Each call consumes 1 of the 100 daily free-tier calls, so use sparingly.

    Args:
        api_key: NewsAPI API key.
        query: Search query string (e.g., "stock market", "Federal Reserve").

    Returns:
        List of normalized article dicts.
    """
    if not api_key:
        log.warning("NewsAPI key not provided; skipping market search for '%s'", query)
        return []

    try:
        # Fetch from last 3 days, sorted by relevancy
        date_from = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d")

        params = {
            "q": query,
            "from": date_from,
            "language": "en",
            "sortBy": "relevancy",
            "pageSize": 15,
            "apiKey": api_key,
        }

        response = requests.get(
            NEWSAPI_EVERYTHING_URL,
            params=params,
            timeout=HTTP_TIMEOUT,
        )
        response.raise_for_status()

        data = response.json()
        if data.get("status") != "ok":
            log.error("NewsAPI market search error: %s", data.get("message", "Unknown error"))
            return []

        raw_articles = data.get("articles", [])
        articles = [_normalize_newsapi_article(a) for a in raw_articles]
        log.info("NewsAPI market search '%s': %d articles", query, len(articles))
        return articles

    except requests.exceptions.HTTPError as e:
        status_code = e.response.status_code if e.response is not None else 0
        if status_code == 429:
            log.warning("NewsAPI rate limit reached for market search '%s'", query)
        elif status_code == 401:
            log.error("NewsAPI authentication failed; invalid API key")
        else:
            log.error("NewsAPI market search HTTP error: %s", e)
    except requests.exceptions.Timeout:
        log.warning("NewsAPI market search timed out for '%s'", query)
    except requests.exceptions.RequestException as e:
        log.error("NewsAPI market search error for '%s': %s", query, e)
    except (ValueError, KeyError) as e:
        log.error("NewsAPI market search parsing error for '%s': %s", query, e)

    return []


def _deduplicate_articles(articles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove duplicate articles based on URL and title similarity.

    Articles are deduplicated by URL first (exact match), then by title
    (case-insensitive exact match). When duplicates from Finnhub share
    the same URL but different tickers, we merge the related_tickers lists.

    Args:
        articles: List of normalized article dicts.

    Returns:
        Deduplicated list of articles.
    """
    seen_urls: dict[str, int] = {}  # url -> index in unique list
    seen_titles: set[str] = set()
    unique: list[dict[str, Any]] = []

    for article in articles:
        url = article.get("url", "")
        title_key = article.get("title", "").strip().lower()

        # Merge tickers if same URL from Finnhub
        if url and url in seen_urls:
            existing_idx = seen_urls[url]
            existing_tickers = unique[existing_idx].get("related_tickers", [])
            new_tickers = article.get("related_tickers", [])
            merged = list(dict.fromkeys(existing_tickers + new_tickers))
            unique[existing_idx]["related_tickers"] = merged
            continue

        # Skip if title already seen (handles cross-source duplicates)
        if title_key and title_key in seen_titles:
            continue

        if url:
            seen_urls[url] = len(unique)
        if title_key:
            seen_titles.add(title_key)

        unique.append(article)

    log.info("Deduplication: %d -> %d articles", len(articles), len(unique))
    return unique


def _semantic_tokens(article: dict[str, Any]) -> set[str]:
    text = " ".join(
        [
            str(article.get("title", "")),
            str(article.get("summary", "")),
            " ".join(article.get("related_tickers", []) or []),
        ]
    ).lower()
    tokens = {
        token
        for token in re.findall(r"[a-z0-9]{3,}", text)
        if token not in {"with", "from", "that", "this", "have", "will", "their", "market", "stock"}
    }
    return tokens


def _similarity(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    intersection = len(left & right)
    union = len(left | right)
    if union == 0:
        return 0.0
    return intersection / union


def _post_process_articles(articles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep the article set diverse and bounded for downstream prompts."""
    diverse: list[dict[str, Any]] = []
    seen_tokens: list[set[str]] = []

    for article in articles:
        tokens = _semantic_tokens(article)
        if any(_similarity(tokens, existing) >= SEMANTIC_DUPLICATE_THRESHOLD for existing in seen_tokens):
            continue
        article["summary"] = str(article.get("summary", ""))[:ARTICLE_CONTENT_CAP]
        diverse.append(article)
        seen_tokens.append(tokens)

    return diverse


def fetch_all_news(
    tickers: list[str],
    finnhub_key: str | None,
    newsapi_key: str | None,
    headlines_only: bool = False,
) -> list[dict[str, Any]]:
    """Orchestrate fetching from all news sources, combine, deduplicate, and sort.

    Fetches from Finnhub (per-ticker company news) and NewsAPI (headlines +
    one market search query). Results are deduplicated by URL and title,
    then sorted by publication datetime descending.

    Args:
        tickers: List of stock ticker symbols from portfolio/watchlist.
        finnhub_key: Finnhub API key, or None to skip.
        newsapi_key: NewsAPI key, or None to skip.

    Returns:
        Combined, deduplicated, and sorted list of normalized article dicts.
    """
    all_articles: list[dict[str, Any]] = []

    # 1. Finnhub: per-ticker company news
    if finnhub_key:
        finnhub_articles = fetch_finnhub_news(tickers, finnhub_key, days=3)
        all_articles.extend(finnhub_articles)
        log.info("Finnhub contributed %d articles", len(finnhub_articles))
    else:
        log.info("Finnhub key not available; skipping Finnhub source")

    # 2. NewsAPI: business headlines (1 call)
    if newsapi_key:
        headlines = fetch_newsapi_headlines(newsapi_key)
        all_articles.extend(headlines)
        log.info("NewsAPI headlines contributed %d articles", len(headlines))

        if not headlines_only:
            # 3. NewsAPI: broad category searches to cover all finance-relevant topics
            broad_queries = [
                "economy OR inflation OR GDP OR unemployment OR recession",
                "tariff OR trade OR sanctions OR import OR export OR trade deal",
                "Federal Reserve OR interest rate OR central bank OR monetary policy",
                "earnings OR IPO OR merger OR acquisition OR stock market",
                "regulation OR SEC OR antitrust OR policy OR legislation",
                "China OR Taiwan OR semiconductor OR chip OR AI OR geopolitical",
                "oil OR energy OR commodity OR OPEC OR dollar OR currency",
            ]
            with ThreadPoolExecutor(max_workers=len(broad_queries)) as executor:
                futures = {
                    executor.submit(fetch_newsapi_market, newsapi_key, q): q
                    for q in broad_queries
                }
                for future in as_completed(futures):
                    q = futures[future]
                    try:
                        market_articles = future.result()
                        all_articles.extend(market_articles)
                        log.info("NewsAPI market search '%s': %d articles", q[:40], len(market_articles))
                    except Exception as e:
                        log.error("NewsAPI market search '%s' failed: %s", q[:40], e)
    else:
        log.info("NewsAPI key not available; skipping NewsAPI source")

    if not all_articles:
        log.warning("No articles fetched from any source")
        return []

    # Deduplicate
    unique_articles = _post_process_articles(_deduplicate_articles(all_articles))

    # Sort by datetime descending (most recent first)
    unique_articles.sort(key=lambda a: a.get("published_ts", 0), reverse=True)

    log.info("fetch_all_news complete: %d unique articles", len(unique_articles))
    return unique_articles
