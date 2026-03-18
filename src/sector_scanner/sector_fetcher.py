"""Sector Scanner — fetch news for thematic sector tickers via Finnhub.

Reads thematic_sectors from config/advisor.yaml, picks 2 tickers per sector
(excluding portfolio/watchlist tickers), and fetches Finnhub company news.
Reuses fetch_finnhub_news from the News Desk agent.
"""
from __future__ import annotations

import os
import random
from typing import Any

from src.shared.config_loader import load_config
from src.utils.logger import get_logger

log = get_logger(__name__)


def _get_sector_tickers(
    config: dict[str, Any],
    tickers_per_sector: int = 2,
    exclude_tickers: set[str] | None = None,
) -> dict[str, list[str]]:
    """Pick tickers per sector, excluding portfolio/watchlist tickers.

    Returns:
        Dict mapping sector name to list of selected tickers.
    """
    exclude = {t.upper() for t in (exclude_tickers or set())}
    moonshot = config.get("moonshot", {})
    thematic = moonshot.get("thematic_sectors", {})

    sector_picks: dict[str, list[str]] = {}
    for sector_name, ticker_list in thematic.items():
        if not isinstance(ticker_list, list):
            continue
        available = [t for t in ticker_list if t.upper() not in exclude]
        if not available:
            continue
        picked = random.sample(available, min(tickers_per_sector, len(available)))
        sector_picks[sector_name] = picked

    return sector_picks


def fetch_sector_news(
    config: dict[str, Any] | None = None,
    exclude_tickers: set[str] | None = None,
) -> dict[str, Any]:
    """Fetch Finnhub news for thematic sector tickers.

    Args:
        config: Advisor config dict. Loaded from disk if not provided.
        exclude_tickers: Tickers to exclude (portfolio + watchlist).

    Returns:
        Dict with keys:
        - articles: list of normalized article dicts
        - sector_picks: dict mapping sector -> selected tickers
        - stats: fetch statistics
    """
    if config is None:
        config = load_config("advisor")

    scanner_cfg = config.get("sector_scanner", {})
    tickers_per_sector = scanner_cfg.get("tickers_per_sector", 2)
    max_articles = scanner_cfg.get("max_articles", 60)

    sector_picks = _get_sector_tickers(
        config,
        tickers_per_sector=tickers_per_sector,
        exclude_tickers=exclude_tickers,
    )

    all_tickers = []
    for tickers in sector_picks.values():
        all_tickers.extend(tickers)

    if not all_tickers:
        log.warning("No sector tickers to fetch news for")
        return {"articles": [], "sector_picks": {}, "stats": {"tickers_scanned": 0}}

    log.info(
        "Fetching sector news for %d tickers across %d sectors",
        len(all_tickers),
        len(sector_picks),
    )

    finnhub_key = os.environ.get("FINNHUB_API_KEY", "")
    if not finnhub_key:
        log.warning("FINNHUB_API_KEY not set — skipping sector news fetch")
        return {"articles": [], "sector_picks": sector_picks, "stats": {"tickers_scanned": 0}}

    from src.news_desk.news_fetcher import fetch_finnhub_news

    articles = fetch_finnhub_news(all_tickers, finnhub_key, days=3)

    # Tag each article with its sector
    ticker_to_sector: dict[str, str] = {}
    for sector, tickers in sector_picks.items():
        for t in tickers:
            ticker_to_sector[t.upper()] = sector

    for article in articles:
        related = article.get("related_tickers", [])
        for t in related:
            if t.upper() in ticker_to_sector:
                article["sector"] = ticker_to_sector[t.upper()]
                break
        else:
            article["sector"] = "unknown"

    # Cap total articles
    articles = articles[:max_articles]

    log.info("Sector fetcher: %d articles for %d tickers", len(articles), len(all_tickers))

    return {
        "articles": articles,
        "sector_picks": sector_picks,
        "stats": {
            "tickers_scanned": len(all_tickers),
            "sectors_scanned": len(sector_picks),
            "articles_fetched": len(articles),
        },
    }
