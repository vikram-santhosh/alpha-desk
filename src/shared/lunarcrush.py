"""
LunarCrush v4 API client for AlphaDesk.

Provides social sentiment and trending data for stocks via the LunarCrush API.

Note: LunarCrush v4 endpoints are approximate and may need adjustment
based on live testing. The API surface can change; verify paths against
the current LunarCrush documentation if requests start failing.
"""

import os

import requests

from src.utils.logger import get_logger

logger = get_logger(__name__)

BASE_URL = "https://lunarcrush.com/api4/public"
TIMEOUT = 10


def _get_headers() -> dict | None:
    """Return authorization headers, or None if no API key is configured."""
    api_key = os.getenv("LUNARCRUSH_API_KEY")
    if not api_key:
        logger.warning("LUNARCRUSH_API_KEY not set — LunarCrush calls will be skipped")
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
        data = resp.json()
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
