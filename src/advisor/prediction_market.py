"""Prediction market data fetcher for AlphaDesk Advisor.

Fetches crowd sentiment / probability data from Polymarket (public API)
and Kalshi (optional API key), filters for finance/macro-relevant markets,
stores data via memory layer, and detects significant probability shifts.
"""

import json
import os
import re
import urllib3

import requests

# Suppress only the specific InsecureRequestWarning from urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from src.advisor.memory import (
    get_prediction_market_deltas,
    get_prediction_markets,
    record_prediction_market,
)
from src.utils.logger import get_logger

log = get_logger(__name__)

POLYMARKET_URL = "https://gamma-api.polymarket.com/events"
KALSHI_URL = "https://api.elections.kalshi.com/trade-api/v2/markets"

# Keywords that signal a market is relevant to macro / finance
RELEVANCE_KEYWORDS = [
    # Fed / monetary policy
    "fed", "federal reserve", "interest rate", "rate cut", "rate hike",
    "fomc", "monetary policy", "inflation", "cpi", "pce",
    # Economic outlook
    "recession", "gdp", "unemployment", "jobs", "nonfarm", "payroll",
    "economic", "economy",
    # Government / fiscal
    "government shutdown", "debt ceiling", "deficit", "fiscal",
    "stimulus", "tax", "tariff", "trade war", "sanctions",
    # Regulation / tech
    "regulation", "antitrust", "sec ", "ftc ", "doj ",
    "big tech", "ai regulation", "crypto regulation",
    # Markets / sectors
    "s&p", "nasdaq", "stock market", "oil price", "crude",
    "bitcoin", "treasury", "bond", "yield",
]

# Map keywords in market titles to potentially affected tickers
KEYWORD_TICKER_MAP = {
    "fed": ["NVDA", "AMZN", "GOOG", "META", "NFLX"],
    "rate cut": ["NVDA", "AMZN", "GOOG", "META", "NFLX"],
    "rate hike": ["NVDA", "AMZN", "GOOG", "META", "NFLX"],
    "recession": ["NVDA", "AMZN", "GOOG", "META", "MSFT", "AVGO", "NFLX"],
    "tariff": ["NVDA", "AVGO", "MRVL"],
    "trade war": ["NVDA", "AVGO", "MRVL"],
    "antitrust": ["GOOG", "META"],
    "big tech": ["GOOG", "META", "AMZN", "MSFT"],
    "ai regulation": ["NVDA", "MSFT", "GOOG", "META"],
    "inflation": ["NVDA", "AMZN", "GOOG", "META", "NFLX"],
    "government shutdown": ["MSFT"],
}

# Map market titles to categories
CATEGORY_PATTERNS = [
    (r"fed|fomc|rate cut|rate hike|interest rate|monetary", "fed_policy"),
    (r"recession|gdp|unemployment|jobs|economic|economy", "recession"),
    (r"regulation|antitrust|sec |ftc |doj |ai regulation", "regulation"),
    (r"tariff|trade war|sanctions|china", "trade_war"),
    (r"tax|stimulus|fiscal|debt ceiling|government shutdown|deficit", "fiscal_policy"),
    (r"inflation|cpi|pce", "inflation"),
    (r"bitcoin|crypto", "crypto"),
    (r"oil|crude|energy", "energy"),
]


def _is_relevant(title: str) -> bool:
    """Check if a market title is relevant to finance/macro."""
    title_lower = title.lower()
    return any(kw in title_lower for kw in RELEVANCE_KEYWORDS)


def _categorize_market(title: str) -> str | None:
    """Assign a category to a market based on its title."""
    title_lower = title.lower()
    for pattern, category in CATEGORY_PATTERNS:
        if re.search(pattern, title_lower):
            return category
    return None


def _map_affected_tickers(title: str) -> list[str]:
    """Map a market title to potentially affected tickers."""
    title_lower = title.lower()
    tickers = set()
    for keyword, ticker_list in KEYWORD_TICKER_MAP.items():
        if keyword in title_lower:
            tickers.update(ticker_list)
    return sorted(tickers)


def _fetch_polymarket() -> list[dict]:
    """Fetch relevant markets from Polymarket (public, no key needed)."""
    markets = []
    try:
        try:
            resp = requests.get(
                POLYMARKET_URL,
                params={"closed": "false", "limit": 50},
                timeout=15,
            )
            resp.raise_for_status()
        except requests.exceptions.SSLError:
            log.warning("Polymarket SSL error — retrying with verify=False")
            resp = requests.get(
                POLYMARKET_URL,
                params={"closed": "false", "limit": 50},
                timeout=15,
                verify=False,
            )
            resp.raise_for_status()
        events = resp.json()

        for event in events:
            try:
                title = event.get("title", "")
                if not _is_relevant(title):
                    continue

                # Polymarket events contain multiple markets (outcomes)
                event_markets = event.get("markets", [])
                if not event_markets:
                    # Single-outcome event; use top-level data
                    prob = None
                    # Try to extract probability from outcomePrices
                    prices = event.get("outcomePrices", "")
                    if prices:
                        try:
                            import json
                            price_list = json.loads(prices)
                            if price_list:
                                prob = float(price_list[0])
                        except (ValueError, IndexError, TypeError):
                            pass

                    volume = 0.0
                    try:
                        volume = float(event.get("volume", 0) or 0)
                    except (ValueError, TypeError):
                        pass

                    if prob is not None:
                        markets.append({
                            "platform": "polymarket",
                            "title": title,
                            "probability": max(0.0, min(1.0, prob)),
                            "volume_usd": volume,
                            "category": _categorize_market(title),
                            "affected_tickers": _map_affected_tickers(title),
                            "url": event.get("slug", ""),
                        })
                else:
                    # Use the first (usually "Yes") market
                    for mkt in event_markets:
                        mkt_title = mkt.get("question", title)
                        if not _is_relevant(mkt_title):
                            continue

                        prob = None
                        prices = mkt.get("outcomePrices", "")
                        if prices:
                            try:
                                import json
                                price_list = json.loads(prices)
                                if price_list:
                                    prob = float(price_list[0])
                            except (ValueError, IndexError, TypeError):
                                pass

                        volume = 0.0
                        try:
                            volume = float(mkt.get("volume", 0) or 0)
                        except (ValueError, TypeError):
                            pass

                        if prob is not None:
                            markets.append({
                                "platform": "polymarket",
                                "title": mkt_title,
                                "probability": max(0.0, min(1.0, prob)),
                                "volume_usd": volume,
                                "category": _categorize_market(mkt_title),
                                "affected_tickers": _map_affected_tickers(mkt_title),
                                "url": mkt.get("slug", ""),
                            })

            except Exception:
                log.exception("Failed to parse Polymarket event: %s", event.get("title", "?"))

        log.info("Polymarket: %d relevant markets found", len(markets))

    except requests.RequestException:
        log.exception("Polymarket API request failed")
    except Exception:
        log.exception("Unexpected error fetching Polymarket data")

    return markets


def _fetch_kalshi() -> list[dict]:
    """Fetch relevant markets from Kalshi. Uses API key if available."""
    api_key = os.getenv("KALSHI_API_KEY", "")
    markets = []

    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        try:
            resp = requests.get(
                KALSHI_URL,
                params={"status": "open", "limit": 50},
                headers=headers,
                timeout=15,
            )
            resp.raise_for_status()
        except requests.exceptions.SSLError:
            log.warning("Kalshi SSL error — retrying with verify=False")
            resp = requests.get(
                KALSHI_URL,
                params={"status": "open", "limit": 50},
                headers=headers,
                timeout=15,
                verify=False,
            )
            resp.raise_for_status()
        data = resp.json()

        for mkt in data.get("markets", []):
            try:
                title = mkt.get("title", "")
                if not _is_relevant(title):
                    continue

                # Kalshi uses yes_price (0-100 cents) as probability
                yes_price = mkt.get("yes_price") or mkt.get("last_price")
                if yes_price is None:
                    continue

                prob = float(yes_price) / 100.0 if float(yes_price) > 1.0 else float(yes_price)

                volume = 0.0
                try:
                    volume = float(mkt.get("volume", 0) or 0)
                except (ValueError, TypeError):
                    pass

                market_url = mkt.get("url", "") or mkt.get("ticker_name", "")

                markets.append({
                    "platform": "kalshi",
                    "title": title,
                    "probability": round(prob, 4),
                    "volume_usd": volume,
                    "category": _categorize_market(title),
                    "affected_tickers": _map_affected_tickers(title),
                    "url": market_url,
                })

            except Exception:
                log.exception("Failed to parse Kalshi market: %s", mkt.get("title", "?"))

        log.info("Kalshi: %d relevant markets found", len(markets))

    except requests.RequestException:
        log.exception("Kalshi API request failed")
    except Exception:
        log.exception("Unexpected error fetching Kalshi data")

    return markets


def fetch_prediction_markets(config: dict) -> list[dict]:
    """Fetch prediction market data from all configured platforms.

    Filters by relevance, optionally by minimum volume, stores each
    data point via memory.record_prediction_market(), and returns
    the combined list.

    Args:
        config: The prediction_markets section from advisor.yaml, e.g.:
                {"polymarket": true, "kalshi": true, "min_volume_usd": 100000, ...}

    Returns:
        List of market dicts with keys: platform, title, probability,
        volume_usd, category, affected_tickers, url.
    """
    log.info("Fetching prediction market data")
    all_markets = []

    # Polymarket (public, always available)
    if config.get("polymarket", True):
        poly_markets = _fetch_polymarket()
        all_markets.extend(poly_markets)

    # Kalshi (optional key, try anyway)
    if config.get("kalshi", True):
        kalshi_markets = _fetch_kalshi()
        all_markets.extend(kalshi_markets)

    # Filter by minimum volume if configured
    min_volume = config.get("min_volume_usd", 0)
    if min_volume > 0:
        before = len(all_markets)
        all_markets = [m for m in all_markets if m.get("volume_usd", 0) >= min_volume]
        log.info("Volume filter ($%s min): %d -> %d markets",
                 min_volume, before, len(all_markets))

    # Filter by tracked categories if configured
    tracked_categories = config.get("tracked_categories", [])
    if tracked_categories:
        before = len(all_markets)
        all_markets = [
            m for m in all_markets
            if m.get("category") in tracked_categories or m.get("category") is None
        ]
        log.info("Category filter: %d -> %d markets", before, len(all_markets))

    # Store each market in memory for delta tracking
    for market in all_markets:
        try:
            record_prediction_market(
                platform=market["platform"],
                market_title=market["title"],
                probability=market["probability"],
                category=market.get("category"),
                volume_usd=market.get("volume_usd"),
                affected_tickers=market.get("affected_tickers"),
                url=market.get("url"),
            )
        except Exception:
            log.exception("Failed to record prediction market: %s", market.get("title"))

    log.info("Total prediction markets fetched and stored: %d", len(all_markets))
    return all_markets


def detect_significant_shifts(min_delta_pct: float = 10.0) -> list[dict]:
    """Detect significant probability shifts in prediction markets.

    Uses memory to compare today's probabilities against previous readings.

    Args:
        min_delta_pct: Minimum percentage point shift to flag (e.g. 10 = 10pp).

    Returns:
        List of market dicts with delta information, sorted by absolute shift.
    """
    min_delta = min_delta_pct / 100.0  # Convert pp to decimal
    shifts = get_prediction_market_deltas(min_delta=min_delta)

    for shift in shifts:
        shift["delta_pct"] = round(shift.get("delta", 0) * 100, 1)
        shift["direction"] = "up" if shift.get("delta", 0) > 0 else "down"

    if shifts:
        log.info("Detected %d significant prediction market shifts (>%spp)",
                 len(shifts), min_delta_pct)
    else:
        log.info("No significant prediction market shifts detected")

    return shifts
