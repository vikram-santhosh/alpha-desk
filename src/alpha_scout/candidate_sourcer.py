"""Candidate sourcing for Alpha Scout.

Sources new ticker candidates from multiple channels:
- Agent bus signals (Reddit mentions, news mentions, technical signals)
- Sector peers of current holdings
- S&P 500 components
- yfinance screeners (day_gainers, undervalued_growth_stocks, etc.)
"""

from typing import Any

import pandas as pd

from src.shared.agent_bus import consume
from src.shared.security import sanitize_ticker
from src.utils.logger import get_logger

log = get_logger(__name__)


def _source_from_agent_bus() -> list[dict[str, Any]]:
    """Pull ticker candidates from unconsumed agent bus signals.

    Reads signals without consuming them so Portfolio Analyst
    can still process them downstream.
    """
    candidates: list[dict[str, Any]] = []
    seen_tickers: set[str] = set()

    for source in ("street_ear", "news_desk", "portfolio_analyst"):
        try:
            signals = consume(source_agent=source, mark_consumed=False)
            for signal in signals:
                payload = signal.get("payload", {})
                ticker = payload.get("ticker")
                if not ticker:
                    # Some signals carry tickers in a list
                    tickers_list = payload.get("tickers", [])
                    for t in tickers_list:
                        if t and t not in seen_tickers:
                            seen_tickers.add(t)
                            candidates.append({
                                "ticker": t,
                                "source": f"agent_bus/{source}",
                                "signal_type": signal.get("signal_type", ""),
                                "signal_data": payload,
                            })
                    continue

                if ticker in seen_tickers:
                    continue
                seen_tickers.add(ticker)
                candidates.append({
                    "ticker": ticker,
                    "source": f"agent_bus/{source}",
                    "signal_type": signal.get("signal_type", ""),
                    "signal_data": payload,
                })
        except Exception:
            log.exception("Error reading agent bus signals from %s", source)

    log.info("Sourced %d candidates from agent bus", len(candidates))
    return candidates


def _source_from_sector_peers(
    holdings: list[dict[str, Any]],
    sector_peers: dict[str, list[str]],
    fundamentals_cache: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Pull sector peers of current holdings from config map.

    Args:
        holdings: Portfolio holdings list.
        sector_peers: Mapping of sector -> ticker list from scout.yaml.
        fundamentals_cache: Optional cached fundamentals to look up sectors.
    """
    candidates: list[dict[str, Any]] = []
    holding_tickers = {h["ticker"] for h in holdings}

    # Determine which sectors our holdings are in
    portfolio_sectors: set[str] = set()
    for sector, peers in sector_peers.items():
        if holding_tickers & set(peers):
            portfolio_sectors.add(sector)

    # Also check fundamentals cache for sector info
    if fundamentals_cache:
        for ticker in holding_tickers:
            fund = fundamentals_cache.get(ticker, {})
            sector = fund.get("sector")
            if sector:
                portfolio_sectors.add(sector)

    # Collect peers from relevant sectors
    for sector in portfolio_sectors:
        peers = sector_peers.get(sector, [])
        for peer in peers:
            candidates.append({
                "ticker": peer,
                "source": f"sector_peer/{sector}",
                "signal_type": "sector_peer",
                "signal_data": {"sector": sector},
            })

    log.info(
        "Sourced %d candidates from sector peers (%d sectors)",
        len(candidates),
        len(portfolio_sectors),
    )
    return candidates


def _source_from_sp500() -> list[dict[str, Any]]:
    """Pull S&P 500 component tickers from Wikipedia."""
    candidates: list[dict[str, Any]] = []

    try:
        tables = pd.read_html(
            "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
            match="Symbol",
        )
        if tables:
            df = tables[0]
            # The symbol column may be named "Symbol" or "Ticker symbol"
            symbol_col = None
            for col in df.columns:
                if "symbol" in str(col).lower() or "ticker" in str(col).lower():
                    symbol_col = col
                    break

            if symbol_col is not None:
                for _, row in df.iterrows():
                    ticker = str(row[symbol_col]).strip().replace(".", "-")
                    if ticker:
                        candidates.append({
                            "ticker": ticker,
                            "source": "sp500_index",
                            "signal_type": "index_component",
                            "signal_data": {},
                        })
    except Exception:
        log.exception("Failed to fetch S&P 500 components from Wikipedia")

    log.info("Sourced %d candidates from S&P 500 index", len(candidates))
    return candidates


def _source_from_yfinance_screeners(screener_names: list[str]) -> list[dict[str, Any]]:
    """Pull candidates from yfinance screeners.

    Args:
        screener_names: List of yfinance screener names
            (e.g. undervalued_growth_stocks, most_actives).
    """
    candidates: list[dict[str, Any]] = []

    try:
        from yfinance import Screener

        for name in screener_names:
            try:
                sc = Screener()
                sc.set_default(name)
                response = sc.response

                quotes = response.get("quotes", [])
                for quote in quotes:
                    ticker = quote.get("symbol")
                    if ticker:
                        candidates.append({
                            "ticker": ticker,
                            "source": f"yf_screener/{name}",
                            "signal_type": "screener_hit",
                            "signal_data": {
                                "screener": name,
                                "short_name": quote.get("shortName", ""),
                            },
                        })
            except Exception:
                log.exception("Failed to run yfinance screener: %s", name)
    except ImportError:
        log.warning("yfinance Screener not available — skipping screener source")
    except Exception:
        log.exception("Unexpected error with yfinance screeners")

    log.info("Sourced %d candidates from yfinance screeners", len(candidates))
    return candidates


def source_all_candidates(
    existing_tickers: list[str],
    holdings: list[dict[str, Any]],
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    """Source candidates from all enabled channels, deduplicate, and cap.

    Args:
        existing_tickers: Tickers already in portfolio/watchlist to exclude.
        holdings: Portfolio holdings list.
        config: Scout config dict (from scout.yaml).

    Returns:
        List of candidate dicts (ticker, source, signal_type, signal_data),
        deduplicated and capped at max_candidates.
    """
    sources_config = config.get("sources", {})
    screening = config.get("screening", {})
    max_candidates = screening.get("max_candidates", 50)

    all_candidates: list[dict[str, Any]] = []

    # Agent bus signals
    if sources_config.get("agent_bus", True):
        all_candidates.extend(_source_from_agent_bus())

    # Sector peers
    if sources_config.get("sector_peers", True):
        sector_peers = config.get("sector_peers", {})
        all_candidates.extend(_source_from_sector_peers(holdings, sector_peers))

    # S&P 500 index
    if sources_config.get("sp500_index", True):
        all_candidates.extend(_source_from_sp500())

    # yfinance screeners
    if sources_config.get("yfinance_screener", True):
        screener_names = config.get("yfinance_screeners", ["undervalued_growth_stocks", "most_actives"])
        all_candidates.extend(_source_from_yfinance_screeners(screener_names))

    # Deduplicate by ticker, keeping the first occurrence (preserves priority order)
    existing_set = {t.upper() for t in existing_tickers}
    seen: set[str] = set()
    unique_candidates: list[dict[str, Any]] = []

    for candidate in all_candidates:
        try:
            ticker = sanitize_ticker(candidate["ticker"])
        except Exception:
            continue

        ticker_upper = ticker.upper()
        if ticker_upper in seen or ticker_upper in existing_set:
            continue

        seen.add(ticker_upper)
        candidate["ticker"] = ticker
        unique_candidates.append(candidate)

    # Cap at max
    capped = unique_candidates[:max_candidates]

    log.info(
        "Candidate sourcing: %d raw → %d unique (excl. %d existing) → %d capped",
        len(all_candidates),
        len(unique_candidates),
        len(existing_set),
        len(capped),
    )
    return capped
