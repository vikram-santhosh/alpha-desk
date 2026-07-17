"""
LunarCrush v4 API client for AlphaDesk.

Provides social sentiment and trending data for stocks via the LunarCrush API.

Note: LunarCrush v4 endpoints are approximate and may need adjustment
based on live testing. The API surface can change; verify paths against
the current LunarCrush documentation if requests start failing.
"""

import os
from typing import Any

import requests

from src.utils.logger import get_logger

logger = get_logger(__name__)

BASE_URL = "https://lunarcrush.com/api4/public"
TIMEOUT = 10


def _get_headers() -> dict | None:
    """Return authorization headers, or None if no API key is configured.

    Accepts either ``LUNARCRUSH_API_KEY`` (canonical) or the legacy/alternate
    ``LUNAR_CRUSH_API`` name so a key set under either spelling is picked up.
    """
    api_key = os.getenv("LUNARCRUSH_API_KEY") or os.getenv("LUNAR_CRUSH_API")
    if not api_key:
        logger.warning(
            "LunarCrush API key not set (LUNARCRUSH_API_KEY / LUNAR_CRUSH_API) — calls will be skipped"
        )
        return None
    return {"Authorization": f"Bearer {api_key}"}


def get_stock_social_metrics(symbol: str) -> dict | None:
    """Get social metrics for a single stock.

    Endpoint: /coins/{symbol}/v1

    Args:
        symbol: Ticker symbol (e.g. "AAPL").

    Returns:
        Dict with galaxy_score, alt_rank, social_volume, social_score,
        or None on error / missing API key.

    Note:
        LunarCrush v4 endpoints are approximate and may need adjustment
        based on live testing.
    """
    headers = _get_headers()
    if headers is None:
        return None

    url = f"{BASE_URL}/coins/{symbol}/v1"
    try:
        resp = requests.get(url, headers=headers, timeout=TIMEOUT)
        resp.raise_for_status()
        payload = resp.json()
        # v4 nests the metrics under a top-level "data" object; fall back to the
        # root for forward/backward compatibility if the shape ever changes.
        data = payload.get("data", payload) if isinstance(payload, dict) else {}
        return {
            "galaxy_score": data.get("galaxy_score"),
            "alt_rank": data.get("alt_rank"),
            "social_volume": data.get("social_volume"),
            "social_score": data.get("social_score"),
        }
    except requests.RequestException as e:
        logger.error("LunarCrush request failed for %s: %s", symbol, e)
        return None


def get_trending_stocks(limit: int = 10) -> list[dict]:
    """Get trending stocks sorted by galaxy score.

    Endpoint: /coins/list/v1?sort=galaxy_score&limit={limit}

    Args:
        limit: Maximum number of results to return.

    Returns:
        List of dicts with symbol, galaxy_score, name.
        Returns empty list on error / missing API key.

    Note:
        LunarCrush v4 endpoints are approximate and may need adjustment
        based on live testing.
    """
    headers = _get_headers()
    if headers is None:
        return []

    url = f"{BASE_URL}/coins/list/v1"
    params = {"sort": "galaxy_score", "limit": limit}
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        items = data if isinstance(data, list) else data.get("data", [])
        return [
            {
                "symbol": item.get("symbol"),
                "galaxy_score": item.get("galaxy_score"),
                "name": item.get("name"),
            }
            for item in items
        ]
    except requests.RequestException as e:
        logger.error("LunarCrush trending stocks request failed: %s", e)
        return []


def get_trending_topics(limit: int = 10) -> list[dict]:
    """Get trending topics sorted by interactions.

    Endpoint: /topics/list/v1?sort=interactions&limit={limit}

    Args:
        limit: Maximum number of results to return.

    Returns:
        List of dicts with topic, interactions, sentiment.
        Returns empty list on error / missing API key.

    Note:
        LunarCrush v4 endpoints are approximate and may need adjustment
        based on live testing.
    """
    headers = _get_headers()
    if headers is None:
        return []

    url = f"{BASE_URL}/topics/list/v1"
    params = {"sort": "interactions", "limit": limit}
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        items = data if isinstance(data, list) else data.get("data", [])
        return [
            {
                "topic": item.get("topic"),
                "interactions": item.get("interactions"),
                "sentiment": item.get("sentiment"),
            }
            for item in items
        ]
    except requests.RequestException as e:
        logger.error("LunarCrush trending topics request failed: %s", e)
        return []


# ── Social feed (cross-platform posts/creators) ──────────────────────────────
# LunarCrush exposes a per-asset social feed that aggregates X/Twitter, Reddit,
# YouTube, TikTok, Instagram and news in one place — ranked by engagement and
# scored for sentiment (1-5 scale, 3 == neutral). For a stock we address it as a
# cashtag topic, e.g. "$nvda".

def _stock_topic(symbol: str) -> str:
    """Return the LunarCrush topic slug for a stock ticker (cashtag form)."""
    return f"${symbol.strip().lower()}"


def _topic_data(path: str, limit: int) -> list[dict]:
    """GET a topic sub-endpoint and return its `data` list (or [] on any failure)."""
    headers = _get_headers()
    if headers is None:
        return []
    url = f"{BASE_URL}/{path}"
    try:
        resp = requests.get(url, headers=headers, timeout=TIMEOUT)
        resp.raise_for_status()
        payload = resp.json()
        items = payload.get("data", payload) if isinstance(payload, dict) else payload
        if not isinstance(items, list):
            return []
        return items[:limit] if limit else items
    except requests.RequestException as e:
        logger.error("LunarCrush request failed for %s: %s", path, e)
        return []


def _sentiment_label(value: Any) -> str:
    """Map LunarCrush's 1-5 post sentiment to bullish/bearish/neutral."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "neutral"
    if v > 3.2:
        return "bullish"
    if v < 2.8:
        return "bearish"
    return "neutral"


def get_social_posts(symbol: str, limit: int = 20) -> list[dict]:
    """Get top social posts for a stock across platforms, ranked by engagement.

    Endpoint: /topic/${symbol}/posts/v1

    Returns a list of dicts with: platform, title, link, sentiment (label),
    sentiment_score (raw 1-5), creator, interactions, created. Empty on failure
    or missing API key.
    """
    posts = _topic_data(f"topic/{_stock_topic(symbol)}/posts/v1", limit)
    return [
        {
            "platform": p.get("post_type"),
            "title": p.get("post_title"),
            "link": p.get("post_link"),
            "sentiment": _sentiment_label(p.get("post_sentiment")),
            "sentiment_score": p.get("post_sentiment"),
            "creator": p.get("creator_name"),
            "interactions": p.get("interactions_24h") or p.get("interactions_total"),
            "created": p.get("post_created"),
        }
        for p in posts
    ]


def get_top_creators(symbol: str, limit: int = 10) -> list[dict]:
    """Get the most-engaged creators/influencers discussing a stock.

    Endpoint: /topic/${symbol}/creators/v1

    Returns dicts with: name, followers, rank, interactions. Empty on failure.
    """
    creators = _topic_data(f"topic/{_stock_topic(symbol)}/creators/v1", limit)
    return [
        {
            "name": c.get("creator_name"),
            "followers": c.get("creator_followers"),
            "rank": c.get("creator_rank"),
            "interactions": c.get("interactions_24h"),
        }
        for c in creators
    ]


def get_social_summary(symbol: str) -> dict | None:
    """Get the aggregate social snapshot for a stock (volume + bull/bear split).

    Endpoint: /topic/${symbol}/v1

    Returns a dict with interactions_24h, num_posts, num_contributors and a
    bullish/bearish/neutral percentage split derived from `types_sentiment`,
    or None on failure / missing key.
    """
    headers = _get_headers()
    if headers is None:
        return None
    url = f"{BASE_URL}/topic/{_stock_topic(symbol)}/v1"
    try:
        resp = requests.get(url, headers=headers, timeout=TIMEOUT)
        resp.raise_for_status()
        payload = resp.json()
        data = payload.get("data", payload) if isinstance(payload, dict) else {}
    except requests.RequestException as e:
        logger.error("LunarCrush social summary failed for %s: %s", symbol, e)
        return None

    return {
        "interactions_24h": data.get("interactions_24h"),
        "num_posts": data.get("num_posts"),
        "num_contributors": data.get("num_contributors"),
        "types_sentiment": data.get("types_sentiment"),
    }


def get_trending_social_stocks(limit: int = 25) -> list[dict]:
    """Get stocks ranked by 24h social interactions (a social-driven universe).

    Endpoint: /stocks/list/v1 (sorted by interactions_24h client-side).

    Returns dicts with symbol, name, interactions, percent_change_24h. Empty on
    failure / missing key.
    """
    rows = _topic_data("stocks/list/v1", 0)
    rows = [r for r in rows if r.get("symbol")]
    rows.sort(key=lambda r: r.get("interactions_24h") or 0, reverse=True)
    return [
        {
            "symbol": r.get("symbol"),
            "name": r.get("name"),
            "interactions": r.get("interactions_24h"),
            "percent_change_24h": r.get("percent_change_24h"),
        }
        for r in rows[:limit]
    ]
