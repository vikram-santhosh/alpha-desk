"""Candidate sourcing for Alpha Scout.

Sources new ticker candidates from multiple channels:
- Agent bus signals (Reddit mentions, news mentions, technical signals)
- Sector peers of current holdings
- S&P 500 components
- yfinance screeners (day_gainers, undervalued_growth_stocks, etc.)
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from functools import partial
from io import StringIO
from typing import Any

import pandas as pd
import requests

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
        response = requests.get(
            "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
            headers={"User-Agent": "AlphaDesk/1.0 (+https://localhost)"},
            timeout=15,
        )
        response.raise_for_status()
        tables = pd.read_html(StringIO(response.text), match="Symbol")
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
        import yfinance as yf

        for name in screener_names:
            try:
                if hasattr(yf, "Screener"):
                    sc = yf.Screener()
                    sc.set_default(name)
                    response = sc.response
                else:
                    response = yf.screen(name, count=25)

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


def _source_from_existing_universe(
    existing_tickers: list[str],
    holdings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Seed top-buy runs with holdings and watchlist names."""
    holding_tickers = {str(h.get("ticker", "")).upper().strip() for h in holdings}
    candidates: list[dict[str, Any]] = []
    for ticker in existing_tickers:
        ticker_upper = str(ticker).upper().strip()
        if not ticker_upper:
            continue
        cohort = "portfolio" if ticker_upper in holding_tickers else "watchlist"
        candidates.append({
            "ticker": ticker_upper,
            "source": f"existing_{cohort}",
            "signal_type": cohort,
            "signal_data": {"cohort": cohort},
        })
    return candidates


def source_all_candidates(
    existing_tickers: list[str],
    holdings: list[dict[str, Any]],
    config: dict[str, Any],
    *,
    include_existing: bool = False,
    audit: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Source candidates from all enabled channels, deduplicate, and cap.

    Args:
        existing_tickers: Tickers already in portfolio/watchlist.
        holdings: Portfolio holdings list.
        config: Scout config dict (from scout.yaml).
        include_existing: When true, seed and keep portfolio/watchlist tickers.
            When false, preserve the discovery-only behavior and exclude them.
        audit: Optional dict populated with source counts and exclusion reasons.

    Returns:
        List of candidate dicts (ticker, source, signal_type, signal_data),
        deduplicated and capped at max_candidates.
    """
    sources_config = config.get("sources", {})
    screening = config.get("screening", {})
    max_candidates = screening.get("max_candidates", 50)

    all_candidates: list[dict[str, Any]] = []
    source_jobs: list[tuple[str, Any, str]] = []
    exclude_for_discovery = set(existing_tickers) if not include_existing else set()

    if audit is not None:
        audit["mode"] = "top_buys" if include_existing else "new_discoveries"
        audit["source_counts"] = {}
        audit["excluded_existing"] = []
        audit["duplicates"] = []
        audit["invalid_candidates"] = 0

    if include_existing:
        existing_candidates = _source_from_existing_universe(existing_tickers, holdings)
        all_candidates.extend(existing_candidates)
        if audit is not None:
            audit["source_counts"]["existing universe"] = len(existing_candidates)

    # Agent bus signals
    if sources_config.get("agent_bus", True):
        source_jobs.append(("agent bus", _source_from_agent_bus, "Agent bus candidate sourcing failed"))

    # Reddit moonshot candidates (small-cap/value subs)
    if sources_config.get("reddit_moonshot", True):
        try:
            from src.alpha_scout.reddit_moonshot_sourcer import source_moonshot_candidates
            moonshot_exclude = exclude_for_discovery | {h["ticker"] for h in holdings if not include_existing}
            source_jobs.append((
                "reddit moonshot",
                partial(
                    source_moonshot_candidates,
                    exclude_tickers=moonshot_exclude,
                    config=None,  # Will use default subreddits
                ),
                "Reddit moonshot sourcing failed",
            ))
        except Exception:
            log.exception("Reddit moonshot sourcing failed")

    # Supply chain (v2 — high quality, before sector peers)
    if sources_config.get("supply_chain", True):
        try:
            from src.alpha_scout.supply_chain_sourcer import source_from_supply_chain
            existing_set_for_chain = {t.upper() for t in exclude_for_discovery}
            source_jobs.append((
                "supply chain",
                partial(source_from_supply_chain, holdings, existing_set_for_chain),
                "Supply chain sourcing failed",
            ))
        except Exception:
            log.exception("Supply chain sourcing failed")

    # Thematic scanner (v2 — discovers emerging themes from news/Reddit)
    if sources_config.get("thematic_scanner", True):
        try:
            from src.alpha_scout.thematic_scanner import themes_to_candidates
            # Themes may be passed in config by the advisor pipeline
            themes = config.get("_themes", [])
            if themes:
                existing_set_for_themes = {t.upper() for t in exclude_for_discovery}
                source_jobs.append((
                    "thematic scanner",
                    partial(themes_to_candidates, themes, existing_set_for_themes),
                    "Thematic candidate sourcing failed",
                ))
        except Exception:
            log.exception("Thematic candidate sourcing failed")

    # Sector peers
    if sources_config.get("sector_peers", True):
        sector_peers = config.get("sector_peers", {})
        source_jobs.append((
            "sector peers",
            partial(_source_from_sector_peers, holdings, sector_peers),
            "Sector peer sourcing failed",
        ))

    # S&P 500 index
    if sources_config.get("sp500_index", True):
        source_jobs.append(("S&P 500", _source_from_sp500, "S&P 500 candidate sourcing failed"))

    # Superinvestor 13F new positions (v2 — full universe scan)
    if sources_config.get("superinvestor_13f", True):
        try:
            from src.advisor.superinvestor_tracker import get_new_positions_as_candidates
            source_jobs.append((
                "superinvestor 13F",
                partial(get_new_positions_as_candidates, config),
                "Superinvestor 13F candidate sourcing failed",
            ))
        except ImportError:
            log.debug("get_new_positions_as_candidates not available yet")
        except Exception:
            log.exception("Superinvestor 13F candidate sourcing failed")

    # Filing scanner — enriched 13F new position detection
    if sources_config.get("filing_scanner", True):
        try:
            from src.alpha_scout.filing_scanner import scan_new_positions
            filing_exclude = exclude_for_discovery | {h["ticker"] for h in holdings if not include_existing}
            source_jobs.append((
                "filing scanner",
                partial(scan_new_positions, config, exclude_tickers=filing_exclude),
                "Filing scanner failed",
            ))
        except Exception:
            log.exception("Filing scanner failed")

    # yfinance screeners
    if sources_config.get("yfinance_screener", True):
        screener_names = config.get("yfinance_screeners", ["undervalued_growth_stocks", "most_actives"])
        source_jobs.append((
            "yfinance screener",
            partial(_source_from_yfinance_screeners, screener_names),
            "yfinance screener sourcing failed",
        ))

    if source_jobs:
        max_workers = min(len(source_jobs), 8)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [
                (name, error_message, executor.submit(job))
                for name, job, error_message in source_jobs
            ]
            for name, error_message, future in futures:
                try:
                    sourced = future.result()
                    if sourced:
                        all_candidates.extend(sourced)
                    if audit is not None:
                        audit["source_counts"][name] = len(sourced or [])
                except Exception:
                    log.exception(error_message)
                    if audit is not None:
                        audit.setdefault("source_errors", []).append({"source": name, "error": error_message})
                else:
                    log.info(
                        "Candidate source complete: %s (%d candidates)",
                        name,
                        len(sourced or []),
                    )

    # Deduplicate by ticker, keeping the first occurrence (preserves priority order)
    existing_set = {t.upper() for t in existing_tickers}
    seen: set[str] = set()
    unique_candidates: list[dict[str, Any]] = []

    for candidate in all_candidates:
        try:
            ticker = sanitize_ticker(candidate["ticker"])
        except Exception:
            if audit is not None:
                audit["invalid_candidates"] = int(audit.get("invalid_candidates", 0)) + 1
            continue

        ticker_upper = ticker.upper()
        if ticker_upper in seen:
            if audit is not None:
                audit["duplicates"].append(ticker_upper)
            continue
        if not include_existing and ticker_upper in existing_set:
            if audit is not None:
                audit["excluded_existing"].append({
                    "ticker": ticker_upper,
                    "source": candidate.get("source", "unknown"),
                    "reason": "already in portfolio/watchlist",
                })
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
    if audit is not None:
        audit["raw_candidates"] = len(all_candidates)
        audit["unique_candidates"] = len(unique_candidates)
        audit["capped_candidates"] = len(capped)
        audit["existing_universe_count"] = len(existing_set)
        audit["include_existing"] = include_existing
    return capped
