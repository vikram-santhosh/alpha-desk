"""Outcome scorer for AlphaDesk Advisor v2.

Scores past recommendations against actual outcomes by fetching current
prices and computing returns at various time horizons (1d, 1w, 1m, 3m).
Auto-closes expired recommendations and produces a scorecard.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

import yfinance as yf

from src.advisor.memory import (
    get_open_recommendations,
    update_recommendation_outcome,
    close_recommendation,
    get_recommendation_scorecard,
)
from src.utils.logger import get_logger

log = get_logger(__name__)


def _fetch_price(ticker: str) -> float | None:
    """Fetch current price for a ticker via yfinance."""
    try:
        t = yf.Ticker(ticker)
        hist = t.history(period="5d")
        if hist.empty:
            return None
        return float(hist["Close"].iloc[-1])
    except Exception:
        log.debug("Failed to fetch price for %s", ticker)
        return None


def _fetch_price_as_of(ticker: str, target_date: date) -> float | None:
    """Fetch the closing price for a ticker on or before a specific date."""
    try:
        t = yf.Ticker(ticker)
        # Look back a few days to ensure we capture a trading day <= target_date
        start = target_date - timedelta(days=7)
        hist = t.history(
            start=start.isoformat(),
            end=(target_date + timedelta(days=1)).isoformat(),
        )
        if hist.empty:
            return None
        # yfinance returns a DatetimeIndex; use only rows on or before target_date
        valid = hist[hist.index.date <= target_date]
        if valid.empty:
            return None
        return float(valid["Close"].iloc[-1])
    except Exception:
        log.debug("Failed to fetch %s price as of %s", ticker, target_date)
        return None


def _compute_spy_return(start_date: date, end_date: date) -> float | None:
    """Compute SPY return (%) between start and end dates, inclusive."""
    start_price = _fetch_price_as_of("SPY", start_date)
    end_price = _fetch_price_as_of("SPY", end_date)
    if start_price is None or end_price is None or start_price <= 0:
        return None
    return ((end_price - start_price) / start_price) * 100


def score_all_outcomes() -> dict:
    """Score all open recommendations against actual outcomes.

    For each open recommendation:
    - Fetches current price (used only for invalidation and very recent recs)
    - Computes horizon returns using the price as of each horizon date
    - Computes SPY/alpha over the matching window for each horizon
    - Checks invalidation (universal -20% stop)
    - Auto-closes recommendations older than 180 days

    Returns the scorecard dict.
    """
    open_recs = get_open_recommendations()
    log.info("Scoring %d open recommendations", len(open_recs))

    today = date.today()
    scored = 0
    closed = 0

    # (horizon_days, price_column, return_column, spy_column, alpha_column)
    horizons = [
        (1, "price_1d", "return_1d_pct", "spy_return_1d_pct", "alpha_1d_pct"),
        (7, "price_1w", "return_1w_pct", "spy_return_1w_pct", "alpha_1w_pct"),
        (30, "price_1m", "return_1m_pct", "spy_return_1m_pct", "alpha_1m_pct"),
        (90, "price_3m", "return_3m_pct", "spy_return_3m_pct", "alpha_3m_pct"),
    ]

    for rec in open_recs:
        rec_id = rec.get("id")
        ticker = rec.get("ticker", "")
        entry_price = rec.get("entry_price", 0)
        rec_date_str = rec.get("recommendation_date", "")

        if not rec_id or not ticker or not entry_price:
            log.warning("Skipping invalid recommendation: id=%s ticker=%s", rec_id, ticker)
            continue

        try:
            rec_date = datetime.strptime(rec_date_str, "%Y-%m-%d").date()
        except (ValueError, TypeError):
            log.warning("Invalid recommendation date for %s: %s", ticker, rec_date_str)
            continue

        days_old = (today - rec_date).days

        # Auto-close if older than 180 days
        if days_old > 180:
            close_recommendation(rec_id, "expired")
            closed += 1
            log.info("Auto-closed expired recommendation: %s (age %d days)", ticker, days_old)
            continue

        # Fetch current price for invalidation and very recent recs without a horizon price
        current_price = _fetch_price(ticker)
        if current_price is None:
            if days_old > 30:
                close_recommendation(rec_id, "delisted_or_no_data")
                closed += 1
                log.warning("Closed %s: no price data after %d days", ticker, days_old)
            continue

        current_return_pct = ((current_price - entry_price) / entry_price) * 100
        updates: dict[str, Any] = {}

        for horizon_days, price_col, return_col, spy_col, alpha_col in horizons:
            if days_old < horizon_days or rec.get(price_col) is not None:
                continue

            horizon_date = rec_date + timedelta(days=horizon_days)
            horizon_price = _fetch_price_as_of(ticker, horizon_date)
            if horizon_price is None:
                # Don't backfill with today's price; leave the column null until data is available
                log.debug(
                    "No %s price as of %s for %s; leaving %s null",
                    ticker, horizon_date, ticker, return_col,
                )
                continue

            horizon_return = ((horizon_price - entry_price) / entry_price) * 100
            updates[price_col] = horizon_price
            updates[return_col] = round(horizon_return, 2)

            spy_return = _compute_spy_return(rec_date, horizon_date)
            if spy_return is not None:
                updates[spy_col] = round(spy_return, 2)
                updates[alpha_col] = round(horizon_return - spy_return, 2)

        # Check universal invalidation: -20% from entry using the latest price
        if current_return_pct <= -20 and not rec.get("invalidation_triggered"):
            updates["invalidation_triggered"] = 1
            updates["invalidation_detail"] = f"Down {current_return_pct:.1f}% from entry (${entry_price:.2f} → ${current_price:.2f})"
            log.warning("Invalidation triggered for %s: %+.1f%%", ticker, current_return_pct)

        if updates:
            update_recommendation_outcome(rec_id, **updates)
            scored += 1

    log.info("Scored %d recommendations, closed %d", scored, closed)

    # Generate scorecard
    scorecard = get_recommendation_scorecard(lookback_days=30)
    log.info("Scorecard: hit_rate=%.1f%%, avg_return=%.2f%%, alpha=%.2f%%",
             scorecard.get("hit_rate_1m", 0),
             scorecard.get("avg_return_1m_pct", 0),
             scorecard.get("avg_alpha_1m_pct", 0))

    return scorecard


def format_scorecard(scorecard: dict) -> str:
    """Format the scorecard for Telegram display."""
    if scorecard.get("total_recommendations", 0) == 0:
        return "<b>Recommendation Scorecard</b>\n\nNo recommendations tracked yet."

    lines = [
        "<b>Recommendation Scorecard (30d)</b>",
        "",
        f"Total: {scorecard['total_recommendations']} recommendations",
        f"Hit rate (1m): <b>{scorecard['hit_rate_1m']:.0f}%</b>",
        f"Avg return (1m): {scorecard['avg_return_1m_pct']:+.1f}%",
        f"Avg alpha (1m): {scorecard['avg_alpha_1m_pct']:+.1f}%",
        f"False positive rate: {scorecard['false_positive_rate']:.0f}%",
    ]

    best = scorecard.get("best_recommendation")
    worst = scorecard.get("worst_recommendation")
    if best:
        lines.append(f"\nBest: {best['ticker']} ({best['return_pct']:+.1f}%)")
    if worst:
        lines.append(f"Worst: {worst['ticker']} ({worst['return_pct']:+.1f}%)")

    # By conviction
    by_conv = scorecard.get("hit_rate_by_conviction", {})
    if by_conv:
        lines.append("\n<b>By Conviction:</b>")
        for conv, rate in sorted(by_conv.items()):
            lines.append(f"  {conv}: {rate:.0f}% hit rate")

    # By source
    by_source = scorecard.get("hit_rate_by_source", {})
    if by_source:
        lines.append("\n<b>By Source:</b>")
        for src, rate in sorted(by_source.items(), key=lambda x: -x[1]):
            lines.append(f"  {src}: {rate:.0f}% hit rate")

    return "\n".join(lines)
