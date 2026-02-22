"""Main orchestrator for the AlphaDesk Portfolio Analyst agent.

Runs the full analysis pipeline: price fetching, technical analysis,
fundamental analysis, risk assessment, signal integration, and
Telegram-formatted output.
"""

import asyncio
import time
from typing import Any

from src.shared.agent_bus import consume
from src.shared.config_loader import get_all_tickers, load_portfolio
from src.utils.logger import get_logger

from src.portfolio_analyst.formatter import format_full_report
from src.portfolio_analyst.fundamental_analyzer import (
    detect_fundamental_alerts,
    fetch_all_fundamentals,
)
from src.portfolio_analyst.price_fetcher import (
    fetch_all_historical,
    fetch_current_prices,
)
from src.portfolio_analyst.risk_analyzer import (
    analyze_concentration,
    analyze_sector_exposure,
    compute_portfolio_summary,
    integrate_signals,
)
from src.portfolio_analyst.technical_analyzer import analyze_all as run_technical_analysis

log = get_logger(__name__)


async def run() -> dict[str, Any]:
    """Orchestrate the full Portfolio Analyst pipeline.

    Steps:
        1. Load portfolio config and resolve all tickers.
        2. Fetch current prices and historical data.
        3. Run technical analysis on all tickers.
        4. Fetch fundamental data for all tickers.
        5. Run risk analysis (concentration, sector, P&L).
        6. Consume signals from the agent bus (street_ear, news_desk).
        7. Cross-reference external signals with portfolio context.
        8. Format Telegram-ready report.

    Returns:
        Dict with keys:
            formatted: str — Telegram HTML report.
            signals: list — integrated signals from other agents.
            portfolio_summary: dict — value, cost, P&L breakdown.
            technicals: dict — per-ticker technical analysis results.
    """
    pipeline_start = time.time()
    log.info("Portfolio Analyst pipeline starting")

    # ── Step 0: Load config ──────────────────────────────────────────
    try:
        portfolio = load_portfolio()
        holdings = portfolio.get("holdings", [])
        all_tickers = get_all_tickers()
        portfolio_tickers = [h["ticker"] for h in holdings]
    except Exception:
        log.exception("Failed to load portfolio config")
        return {
            "formatted": "<b>Portfolio Analyst</b>\n\nError: could not load portfolio configuration.",
            "signals": [],
            "portfolio_summary": {},
            "technicals": {},
        }

    log.info(
        "Loaded %d holdings, %d total tickers (incl. watchlist)",
        len(holdings),
        len(all_tickers),
    )

    # ── Step 1: Fetch current prices ─────────────────────────────────
    step_start = time.time()
    try:
        prices = await asyncio.to_thread(fetch_current_prices, all_tickers)
    except Exception:
        log.exception("Failed to fetch current prices")
        prices = {}
    log.info("Step 1 (current prices) completed in %.2fs", time.time() - step_start)

    # ── Step 2: Fetch historical data ────────────────────────────────
    step_start = time.time()
    try:
        historical = await asyncio.to_thread(fetch_all_historical, all_tickers)
    except Exception:
        log.exception("Failed to fetch historical data")
        historical = {}
    log.info("Step 2 (historical data) completed in %.2fs", time.time() - step_start)

    # ── Step 3: Technical analysis ───────────────────────────────────
    step_start = time.time()
    try:
        technicals = run_technical_analysis(all_tickers, historical)
    except Exception:
        log.exception("Failed to run technical analysis")
        technicals = {}
    log.info("Step 3 (technical analysis) completed in %.2fs", time.time() - step_start)

    # ── Step 4: Fundamental analysis ─────────────────────────────────
    step_start = time.time()
    try:
        fundamentals = await asyncio.to_thread(fetch_all_fundamentals, all_tickers)
    except Exception:
        log.exception("Failed to fetch fundamentals")
        fundamentals = {}
    log.info("Step 4 (fundamentals) completed in %.2fs", time.time() - step_start)

    # ── Step 5: Risk analysis ────────────────────────────────────────
    step_start = time.time()
    try:
        portfolio_summary = compute_portfolio_summary(holdings, prices)
    except Exception:
        log.exception("Failed to compute portfolio summary")
        portfolio_summary = {
            "total_value": 0,
            "total_cost": 0,
            "total_pnl": 0,
            "total_pnl_pct": 0,
            "holdings": [],
        }

    try:
        concentration = analyze_concentration(holdings, prices)
    except Exception:
        log.exception("Failed to analyse concentration")
        concentration = {"positions": [], "total_value": 0, "warnings": []}

    try:
        sector_exposure = analyze_sector_exposure(fundamentals)
    except Exception:
        log.exception("Failed to analyse sector exposure")
        sector_exposure = {"sectors": {}, "total_tickers": 0, "warnings": []}

    log.info("Step 5 (risk analysis) completed in %.2fs", time.time() - step_start)

    # ── Step 6: Consume external signals ─────────────────────────────
    step_start = time.time()
    external_signals: list[dict[str, Any]] = []
    for source in ("street_ear", "news_desk"):
        try:
            signals = consume(source_agent=source, mark_consumed=True)
            external_signals.extend(signals)
        except Exception:
            log.exception("Failed to consume signals from %s", source)
    log.info(
        "Step 6 (consume signals) completed in %.2fs — %d signals",
        time.time() - step_start,
        len(external_signals),
    )

    # ── Step 7: Signal integration ───────────────────────────────────
    step_start = time.time()
    try:
        integrated = integrate_signals(external_signals, technicals, fundamentals)
    except Exception:
        log.exception("Failed to integrate signals")
        integrated = []
    log.info("Step 7 (signal integration) completed in %.2fs", time.time() - step_start)

    # ── Step 8: Detect fundamental alerts ────────────────────────────
    step_start = time.time()
    try:
        fundamental_alerts = detect_fundamental_alerts(fundamentals)
    except Exception:
        log.exception("Failed to detect fundamental alerts")
        fundamental_alerts = []
    log.info("Step 8 (fundamental alerts) completed in %.2fs", time.time() - step_start)

    # ── Step 9: Format output ────────────────────────────────────────
    step_start = time.time()
    try:
        formatted = format_full_report(
            portfolio_summary=portfolio_summary,
            technicals=technicals,
            fundamentals=fundamentals,
            fundamental_alerts=fundamental_alerts,
            concentration=concentration,
            sector_exposure=sector_exposure,
            integrated_signals=integrated,
        )
    except Exception:
        log.exception("Failed to format report")
        formatted = "<b>Portfolio Analyst</b>\n\nError formatting report."
    log.info("Step 9 (formatting) completed in %.2fs", time.time() - step_start)

    total_elapsed = time.time() - pipeline_start
    log.info("Portfolio Analyst pipeline completed in %.2fs", total_elapsed)

    return {
        "formatted": formatted,
        "signals": integrated,
        "portfolio_summary": portfolio_summary,
        "technicals": technicals,
    }
