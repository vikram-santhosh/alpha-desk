"""Main orchestrator for the AlphaDesk Alpha Scout agent.

Runs the full discovery pipeline: candidate sourcing, market data
fetching, multi-dimensional screening, Opus 4.6 synthesis, and
Telegram-formatted output.
"""

import asyncio
import time
from typing import Any

from src.shared.agent_bus import publish
from src.shared.config_loader import get_all_tickers, load_portfolio
from src.utils.logger import get_logger

from src.alpha_scout.candidate_sourcer import source_all_candidates
from src.alpha_scout.formatter import format_discovery_report
from src.alpha_scout.screener import screen_candidates
from src.alpha_scout.synthesizer import synthesize_recommendations

log = get_logger(__name__)

SOURCE_AGENT = "alpha_scout"


async def run() -> dict[str, Any]:
    """Orchestrate the full Alpha Scout discovery pipeline.

    Steps:
        1. Load config + existing tickers.
        2. Source candidates from all channels.
        3. Fetch market data for candidates.
        4. Multi-dimensional screening.
        5. Opus 4.6 synthesis (top N).
        6. Publish discovery signals to agent bus.
        7. Format Telegram output.

    Returns:
        Dict with keys:
            formatted: str — Telegram HTML report.
            signals: list — published signals.
            stats: dict — pipeline statistics.
            recommendations: dict — portfolio_recs + watchlist_recs.
    """
    pipeline_start = time.time()
    log.info("Alpha Scout pipeline starting")

    # ── Step 1: Load config + existing tickers ────────────────────────
    try:
        from src.shared.config_loader import load_scout_config
        config = load_scout_config()
    except Exception:
        log.exception("Failed to load scout config — using defaults")
        config = {
            "sources": {"agent_bus": True, "sector_peers": True, "sp500_index": True, "yfinance_screener": True},
            "screening": {"max_candidates": 50, "batch_size": 10, "top_n_for_synthesis": 20},
            "weights": {"technical": 0.30, "fundamental": 0.30, "sentiment": 0.20, "diversification": 0.20},
            "output": {"max_portfolio_recommendations": 5, "max_watchlist_recommendations": 10},
            "sector_peers": {},
        }

    try:
        portfolio_data = load_portfolio()
        holdings = portfolio_data.get("holdings", [])
        existing_tickers = get_all_tickers()
        portfolio_tickers = [h["ticker"] for h in holdings]
    except Exception:
        log.exception("Failed to load portfolio config")
        return {
            "formatted": "<b>Alpha Scout</b>\n\nError: could not load portfolio configuration.",
            "signals": [],
            "stats": {"error": "config_load_failed"},
            "recommendations": {"portfolio_recs": [], "watchlist_recs": []},
        }

    log.info(
        "Loaded %d holdings, %d existing tickers",
        len(holdings),
        len(existing_tickers),
    )

    # ── Step 2: Source candidates ──────────────────────────────────────
    step_start = time.time()
    try:
        candidates = source_all_candidates(existing_tickers, holdings, config)
    except Exception:
        log.exception("Failed to source candidates")
        candidates = []
    log.info("Step 2 (source candidates) completed in %.2fs — %d candidates", time.time() - step_start, len(candidates))

    if not candidates:
        return {
            "formatted": "<b>Alpha Scout</b>\n\n<i>No new candidates found this cycle.</i>",
            "signals": [],
            "stats": {"candidates_sourced": 0, "total_time_s": round(time.time() - pipeline_start, 1)},
            "recommendations": {"portfolio_recs": [], "watchlist_recs": []},
        }

    # ── Step 3: Fetch market data for candidates ──────────────────────
    candidate_tickers = [c["ticker"] for c in candidates]

    from src.portfolio_analyst.price_fetcher import (
        fetch_all_historical,
        fetch_current_prices,
    )
    from src.portfolio_analyst.fundamental_analyzer import fetch_all_fundamentals

    screening_config = config.get("screening", {})
    batch_size = screening_config.get("batch_size", 10)

    # Fetch in batches to avoid overwhelming APIs
    step_start = time.time()
    all_prices: dict[str, Any] = {}
    all_historical: dict[str, Any] = {}
    all_fundamentals: dict[str, Any] = {}

    for i in range(0, len(candidate_tickers), batch_size):
        batch = candidate_tickers[i : i + batch_size]
        log.info("Fetching data for batch %d-%d of %d", i + 1, min(i + batch_size, len(candidate_tickers)), len(candidate_tickers))

        try:
            prices = await asyncio.to_thread(fetch_current_prices, batch)
            all_prices.update(prices)
        except Exception:
            log.exception("Failed to fetch prices for batch %d", i)

        try:
            historical = await asyncio.to_thread(fetch_all_historical, batch)
            all_historical.update(historical)
        except Exception:
            log.exception("Failed to fetch historical for batch %d", i)

        try:
            fundamentals = await asyncio.to_thread(fetch_all_fundamentals, batch)
            all_fundamentals.update(fundamentals)
        except Exception:
            log.exception("Failed to fetch fundamentals for batch %d", i)

    log.info("Step 3 (market data) completed in %.2fs", time.time() - step_start)

    # Also fetch fundamentals for portfolio tickers (for sector weights in diversification scoring)
    step_start = time.time()
    try:
        portfolio_fundamentals = await asyncio.to_thread(fetch_all_fundamentals, portfolio_tickers)
    except Exception:
        log.exception("Failed to fetch portfolio fundamentals")
        portfolio_fundamentals = {}
    log.info("Portfolio fundamentals fetched in %.2fs", time.time() - step_start)

    # ── Step 4: Multi-dimensional screening ───────────────────────────
    step_start = time.time()

    from src.portfolio_analyst.technical_analyzer import analyze_all as run_technical_analysis

    try:
        technicals = run_technical_analysis(candidate_tickers, all_historical)
    except Exception:
        log.exception("Failed to run technical analysis")
        technicals = {}

    weights = config.get("weights", {"technical": 0.30, "fundamental": 0.30, "sentiment": 0.20, "diversification": 0.20})

    try:
        scored = screen_candidates(
            candidates=candidates,
            technicals=technicals,
            fundamentals=all_fundamentals,
            portfolio_tickers=portfolio_tickers,
            portfolio_fundamentals=portfolio_fundamentals,
            weights=weights,
        )
    except Exception:
        log.exception("Failed to screen candidates")
        scored = []

    log.info("Step 4 (screening) completed in %.2fs", time.time() - step_start)

    # ── Step 5: Opus 4.6 synthesis ────────────────────────────────────
    step_start = time.time()
    top_n = screening_config.get("top_n_for_synthesis", 20)
    output_config = config.get("output", {})
    max_portfolio = output_config.get("max_portfolio_recommendations", 5)
    max_watchlist = output_config.get("max_watchlist_recommendations", 10)

    try:
        synthesis = synthesize_recommendations(
            scored_candidates=scored,
            top_n=top_n,
            max_portfolio=max_portfolio,
            max_watchlist=max_watchlist,
        )
    except Exception:
        log.exception("Failed to synthesize recommendations")
        synthesis = {"portfolio_recs": [], "watchlist_recs": [], "raw_synthesis": ""}

    portfolio_recs = synthesis.get("portfolio_recs", [])
    watchlist_recs = synthesis.get("watchlist_recs", [])
    log.info(
        "Step 5 (synthesis) completed in %.2fs — %d portfolio, %d watchlist",
        time.time() - step_start,
        len(portfolio_recs),
        len(watchlist_recs),
    )

    # ── Step 6: Publish discovery signals to agent bus ─────────────────
    published_signals: list[dict[str, Any]] = []
    for rec in portfolio_recs + watchlist_recs:
        try:
            signal_id = publish(
                signal_type="discovery_recommendation",
                source_agent=SOURCE_AGENT,
                payload={
                    "ticker": rec["ticker"],
                    "category": rec.get("category", "watchlist"),
                    "conviction": rec.get("conviction", "medium"),
                    "thesis": rec.get("thesis", ""),
                    "scores": rec.get("scores", {}),
                },
            )
            published_signals.append({"id": signal_id, "ticker": rec["ticker"]})
        except Exception:
            log.exception("Failed to publish signal for %s", rec.get("ticker"))

    log.info("Published %d discovery signals", len(published_signals))

    # ── Step 7: Format Telegram output ─────────────────────────────────
    total_time = time.time() - pipeline_start
    stats = {
        "candidates_sourced": len(candidates),
        "candidates_screened": len(scored),
        "portfolio_recs": len(portfolio_recs),
        "watchlist_recs": len(watchlist_recs),
        "signals_published": len(published_signals),
        "total_time_s": round(total_time, 1),
    }

    try:
        formatted = format_discovery_report(portfolio_recs, watchlist_recs, stats)
    except Exception:
        log.exception("Failed to format report")
        formatted = "<b>Alpha Scout</b>\n\nError formatting report."

    log.info("Alpha Scout pipeline completed in %.2fs", total_time)

    return {
        "formatted": formatted,
        "signals": published_signals,
        "stats": stats,
        "recommendations": {
            "portfolio_recs": portfolio_recs,
            "watchlist_recs": watchlist_recs,
        },
    }
