"""Outcome scorer for AlphaDesk Advisor v2.

Scores past recommendations against actual outcomes by fetching current
prices and computing returns at various time horizons (1d, 1w, 1m, 3m).
Auto-closes expired recommendations and produces a scorecard.
"""

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


def _fetch_spy_return(start_date: str, end_date: str) -> float | None:
    """Fetch SPY return between two dates for alpha calculation."""
    try:
        spy = yf.Ticker("SPY")
        hist = spy.history(start=start_date, end=end_date)
        if len(hist) < 2:
            return None
        start_price = float(hist["Close"].iloc[0])
        end_price = float(hist["Close"].iloc[-1])
        return ((end_price - start_price) / start_price) * 100
    except Exception:
        log.debug("Failed to fetch SPY return")
        return None


def score_all_outcomes() -> dict:
    """Score all open recommendations against actual outcomes.

    For each open recommendation:
    - Fetches current price
    - Computes returns for each time horizon that's due
    - Checks invalidation (universal -20% stop)
    - Auto-closes recommendations older than 180 days

    Returns the scorecard dict.
    """
    open_recs = get_open_recommendations()
    log.info("Scoring %d open recommendations", len(open_recs))

    today = date.today()
    scored = 0
    closed = 0

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

        # Fetch current price
        current_price = _fetch_price(ticker)
        if current_price is None:
            # Ticker might be delisted
            if days_old > 30:
                close_recommendation(rec_id, "delisted_or_no_data")
                closed += 1
                log.warning("Closed %s: no price data after %d days", ticker, days_old)
            continue

        updates: dict[str, Any] = {}

        # Compute returns for each horizon
        return_pct = ((current_price - entry_price) / entry_price) * 100

        if days_old >= 1 and rec.get("price_1d") is None:
            updates["price_1d"] = current_price
            updates["return_1d_pct"] = round(return_pct, 2)

        if days_old >= 7 and rec.get("price_1w") is None:
            updates["price_1w"] = current_price
            updates["return_1w_pct"] = round(return_pct, 2)

        if days_old >= 30 and rec.get("price_1m") is None:
            updates["price_1m"] = current_price
            updates["return_1m_pct"] = round(return_pct, 2)

            # Compute SPY return for alpha
            spy_return = _fetch_spy_return(rec_date_str, today.isoformat())
            if spy_return is not None:
                updates["spy_return_1m_pct"] = round(spy_return, 2)
                updates["alpha_1m_pct"] = round(return_pct - spy_return, 2)

        if days_old >= 90 and rec.get("price_3m") is None:
            updates["price_3m"] = current_price
            updates["return_3m_pct"] = round(return_pct, 2)

        # Check universal invalidation: -20% from entry
        if return_pct <= -20 and not rec.get("invalidation_triggered"):
            updates["invalidation_triggered"] = 1
            updates["invalidation_detail"] = f"Down {return_pct:.1f}% from entry (${entry_price:.2f} → ${current_price:.2f})"
            log.warning("Invalidation triggered for %s: %+.1f%%", ticker, return_pct)

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
