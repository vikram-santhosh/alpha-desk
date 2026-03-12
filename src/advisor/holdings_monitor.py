"""Daily holdings check-in with memory context for AlphaDesk Advisor.

Produces per-holding reports with price data, cumulative returns,
trend narratives from recent snapshots, key events, and thesis status.
Also builds a human-readable summary for the Opus synthesis prompt.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from src.advisor.memory import (
    get_all_holdings,
    get_recent_snapshots,
    record_snapshot,
)
from src.utils.logger import get_logger

log = get_logger(__name__)


def monitor_holdings(
    holdings: list[dict],
    prices: dict[str, dict[str, Any]],
    fundamentals: dict[str, dict[str, Any]],
    signals: list[dict],
    news_signals: list[dict],
) -> list[dict]:
    """Produce the daily holdings check-in with memory context.

    For each holding:
    - Gets current price and computes day change / cumulative return
    - Retrieves last 7 days of snapshots for trend narrative
    - Checks for key events (earnings, news, signals)
    - Records today's snapshot to memory
    - Builds a holding_report dict

    Args:
        holdings: List of holding dicts from memory (get_all_holdings).
        prices: Dict mapping ticker -> price data (from fetch_current_prices).
        fundamentals: Dict mapping ticker -> fundamentals (from fetch_fundamentals).
        signals: List of technical/fundamental signal dicts.
        news_signals: List of news signal dicts.

    Returns:
        List of holding_report dicts.
    """
    reports: list[dict] = []

    # Index signals by ticker for fast lookup
    signals_by_ticker: dict[str, list[dict]] = {}
    for sig in signals:
        t = sig.get("ticker") or sig.get("payload", {}).get("ticker", "")
        if t:
            signals_by_ticker.setdefault(t, []).append(sig)

    news_by_ticker: dict[str, list[dict]] = {}
    for ns in news_signals:
        # Index by primary ticker
        t = ns.get("ticker") or ns.get("payload", {}).get("ticker", "")
        if t:
            news_by_ticker.setdefault(t, []).append(ns)
        # Also index by all tickers mentioned in the article's tickers list
        for extra_t in ns.get("tickers", []):
            if extra_t and extra_t != t:
                news_by_ticker.setdefault(extra_t, []).append(ns)

    for holding in holdings:
        ticker = holding.get("ticker", "")
        if not ticker:
            continue

        try:
            report = _build_holding_report(
                holding, prices, fundamentals, signals_by_ticker, news_by_ticker
            )
            reports.append(report)
        except Exception:
            log.exception("Error building report for %s", ticker)

    # Compute position weights from shares * current price
    total_value = 0.0
    for r in reports:
        p = r.get("price")
        shares = r.get("shares") or 1
        if p is not None and p > 0:
            r["_market_value"] = p * shares
            total_value += r["_market_value"]

    if total_value > 0:
        for r in reports:
            mv = r.pop("_market_value", None)
            if mv is not None and mv > 0:
                r["position_pct"] = round(mv / total_value * 100, 1)
            else:
                r["position_pct"] = None

    # Sector concentration check
    sector_weight: dict[str, float] = {}
    for r in reports:
        sector = r.get("sector") or "Unknown"
        pct = r.get("position_pct") or 0
        sector_weight[sector] = sector_weight.get(sector, 0) + pct

    for sector, weight in sector_weight.items():
        if weight >= 80:
            for r in reports:
                r_sector = r.get("sector") or "Unknown"
                if r_sector == sector:
                    r.setdefault("key_events", []).append(
                        f"WARNING: {sector} sector concentration {weight:.0f}% of portfolio"
                    )
            log.warning("Sector concentration: %s = %.0f%%", sector, weight)

    log.info("Built %d holding reports", len(reports))
    return reports


def build_holdings_narrative(holding_reports: list[dict]) -> str:
    """Build a human-readable summary of all holdings for the Opus prompt.

    Not HTML formatted -- this is plain text for the synthesis prompt input.
    Includes memory context like trend narratives.

    Args:
        holding_reports: List of holding report dicts from monitor_holdings.

    Returns:
        Multi-line string summarizing all holdings.
    """
    if not holding_reports:
        return "No holdings to report."

    lines: list[str] = []
    lines.append("YOUR PORTFOLIO -- Holdings Check-in")
    lines.append("")

    for r in holding_reports:
        ticker = r.get("ticker", "???")
        price = r.get("price")
        change_pct = r.get("change_pct")
        cum_return = r.get("cumulative_return_pct")
        thesis = r.get("thesis", "")
        thesis_status = r.get("thesis_status", "intact")
        recent_trend = r.get("recent_trend", "")
        key_events = r.get("key_events", [])
        category = r.get("category", "core")
        tracking_since = r.get("tracking_since", "")

        # Header line: TICKER  $price  +X.X% today  |  +XX.X% since tracking
        price_str = f"${price:.2f}" if price is not None else "N/A"
        change_str = _format_pct(change_pct, "today")
        cum_str = _format_cum_return(cum_return, tracking_since, category)

        lines.append(f"  {ticker:<6}  {price_str}  {change_str}  |  {cum_str}")

        # Thesis line
        status_icon = _thesis_status_icon(thesis_status)
        lines.append(f"          Thesis: {thesis}. {thesis_status.upper()} {status_icon}")

        # Key events
        for event in key_events:
            lines.append(f"          {event}")

        # Recent trend (memory context)
        if recent_trend:
            lines.append(f"          Memory: {recent_trend}")

        # 52-week proximity
        if r.get("near_52w_high"):
            lines.append(
                f"          Note: Approaching 52-week high ({r.get('high_52w', 'N/A')})."
            )
        if r.get("near_52w_low"):
            lines.append(
                f"          Warning: Near 52-week low ({r.get('low_52w', 'N/A')})."
            )

        # Earnings approaching
        if r.get("earnings_approaching"):
            lines.append(
                f"          Earnings: {r.get('earnings_date', 'upcoming')} "
                f"-- {r.get('earnings_days_out', '?')} days out."
            )

        lines.append("")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════
# INTERNAL HELPERS
# ═══════════════════════════════════════════════════════

def _build_holding_report(
    holding: dict,
    prices: dict[str, dict[str, Any]],
    fundamentals: dict[str, dict[str, Any]],
    signals_by_ticker: dict[str, list[dict]],
    news_by_ticker: dict[str, list[dict]],
) -> dict[str, Any]:
    """Build a single holding report dict."""
    ticker = holding["ticker"]
    entry_price = holding.get("entry_price")
    shares = holding.get("shares")
    if shares is None:
        shares = 1
    tracking_since = holding.get("tracking_since", "")
    thesis = holding.get("thesis", "")
    thesis_status = holding.get("thesis_status", "intact")
    category = holding.get("category", "core")

    # Current price data
    price_data = prices.get(ticker, {})
    price = price_data.get("price")
    change_pct = price_data.get("change_pct")

    # Cumulative return since tracking started
    cumulative_return_pct = None
    if price is not None and entry_price is not None and entry_price > 0:
        cumulative_return_pct = round(
            (price - entry_price) / entry_price * 100, 2
        )

    # Recent snapshots for trend narrative (last 7 days)
    recent = get_recent_snapshots(ticker, days=7)
    recent_trend = _compute_trend_narrative(ticker, recent)

    # Drawdown from recent peak (last 7 snapshots)
    drawdown_from_peak_pct = None
    if price is not None and recent:
        peak_price = max(
            (s.get("price") or 0 for s in recent),
            default=0,
        )
        if peak_price > 0 and price < peak_price:
            drawdown_from_peak_pct = round(
                (price - peak_price) / peak_price * 100, 2
            )

    # Count positive/negative days in last 7
    positive_days = sum(
        1 for s in recent if (s.get("change_pct") or 0) > 0
    )
    negative_days = sum(
        1 for s in recent if (s.get("change_pct") or 0) < 0
    )

    # Key events
    key_events: list[str] = []

    # Check technical/fundamental signals
    ticker_signals = signals_by_ticker.get(ticker, [])
    for sig in ticker_signals:
        msg = sig.get("message") or sig.get("payload", {}).get("message", "")
        if msg:
            key_events.append(f"Signal: {msg}")

    # Check news signals — extract clean headlines
    ticker_news = news_by_ticker.get(ticker, [])
    seen_headlines: set[str] = set()
    for ns in ticker_news:
        headline = (
            ns.get("headline")
            or ns.get("title", "")
            or ns.get("payload", {}).get("headline", "")
        )
        if headline:
            headline_clean = headline.strip()
            if headline_clean.lower() not in seen_headlines:
                seen_headlines.add(headline_clean.lower())
                key_events.append(headline_clean)

    # Fundamentals data
    fund_data = fundamentals.get(ticker, {})

    # 52-week high/low proximity
    near_52w_high = False
    near_52w_low = False
    high_52w = fund_data.get("fifty_two_week_high")
    low_52w = fund_data.get("fifty_two_week_low")
    pct_from_high = fund_data.get("pct_from_52w_high")
    pct_from_low = fund_data.get("pct_from_52w_low")

    if pct_from_high is not None and abs(pct_from_high) <= 5:
        near_52w_high = True
    if pct_from_low is not None and pct_from_low <= 5:
        near_52w_low = True

    # Earnings approaching
    earnings_approaching = False
    earnings_date = fund_data.get("next_earnings_date")
    earnings_days_out = None
    if earnings_date:
        try:
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"):
                try:
                    ed = datetime.strptime(
                        str(earnings_date).split("+")[0].strip(), fmt
                    )
                    break
                except ValueError:
                    continue
            else:
                ed = None

            if ed is not None:
                days_out = (ed.date() - datetime.now().date()).days
                if 0 <= days_out <= 30:
                    earnings_approaching = True
                    earnings_days_out = days_out
        except Exception:
            log.debug("Could not parse earnings date for %s", ticker)

    # Record today's snapshot to memory — skip if price data is missing
    if price is not None:
        try:
            key_event_str = "; ".join(key_events) if key_events else None
            record_snapshot(
                ticker=ticker,
                price=price,
                change_pct=change_pct,
                cumulative_return_pct=cumulative_return_pct,
                thesis_status=thesis_status,
                daily_narrative=None,  # Opus fills this in during synthesis
                key_event=key_event_str,
            )
        except Exception:
            log.exception("Failed to record snapshot for %s", ticker)
    else:
        log.warning("Skipping snapshot for %s — no price data", ticker)

    return {
        "ticker": ticker,
        "price": price,
        "change_pct": change_pct,
        "cumulative_return_pct": cumulative_return_pct,
        "entry_price": entry_price,
        "tracking_since": tracking_since,
        "thesis": thesis,
        "thesis_status": thesis_status,
        "category": category,
        "recent_trend": recent_trend,
        "positive_days_7": positive_days,
        "negative_days_7": negative_days,
        "key_events": key_events,
        "near_52w_high": near_52w_high,
        "near_52w_low": near_52w_low,
        "high_52w": high_52w,
        "low_52w": low_52w,
        "earnings_approaching": earnings_approaching,
        "earnings_date": str(earnings_date) if earnings_date else None,
        "earnings_days_out": earnings_days_out,
        "shares": shares,
        "sector": fund_data.get("sector"),
        "industry": fund_data.get("industry"),
        "drawdown_from_peak_pct": drawdown_from_peak_pct,
    }


def _compute_trend_narrative(
    ticker: str, snapshots: list[dict]
) -> str:
    """Build a short trend narrative from recent snapshots.

    Args:
        ticker: Ticker symbol (for logging).
        snapshots: Recent snapshots, newest first.

    Returns:
        A string like "Up 5 of last 7 sessions. Momentum strong."
    """
    if not snapshots:
        return ""

    n = len(snapshots)

    # Need at least 3 data points for a meaningful trend narrative
    if n < 3:
        return ""

    up_days = sum(1 for s in snapshots if (s.get("change_pct") or 0) > 0)
    down_days = sum(1 for s in snapshots if (s.get("change_pct") or 0) < 0)

    # Streak detection (snapshots are newest-first)
    streak_type = None
    streak_count = 0
    for s in snapshots:
        change = s.get("change_pct") or 0
        if streak_type is None:
            streak_type = "up" if change > 0 else "down" if change < 0 else "flat"
            streak_count = 1
        elif (streak_type == "up" and change > 0) or (
            streak_type == "down" and change < 0
        ):
            streak_count += 1
        else:
            break

    parts: list[str] = []

    # Momentum qualifier (only with enough data)
    if up_days >= n * 0.7:
        parts.append(f"Strong: up {up_days}/{n} sessions.")
    elif down_days >= n * 0.7:
        parts.append(f"Weak: down {down_days}/{n} sessions.")
    elif abs(up_days - down_days) <= 1:
        parts.append(f"Sideways ({up_days} up, {down_days} down of {n}).")
    else:
        parts.append(f"Up {up_days}/{n} sessions.")

    # Notable streak
    if streak_count >= 3:
        parts.append(f"{streak_count}-day {streak_type} streak.")

    return " ".join(parts)


def _format_pct(pct: float | None, suffix: str = "") -> str:
    """Format a percentage for display."""
    if pct is None:
        return "N/A"
    sign = "+" if pct >= 0 else ""
    txt = f"{sign}{pct:.1f}%"
    if suffix:
        txt += f" {suffix}"
    return txt


def _format_cum_return(
    cum_pct: float | None, tracking_since: str, category: str
) -> str:
    """Format cumulative return with tracking context."""
    if cum_pct is None:
        if category == "new_position":
            return f"NEW POSITION (tracking since {tracking_since})"
        return "N/A"

    sign = "+" if cum_pct >= 0 else ""
    since_str = f" since tracking ({tracking_since})" if tracking_since else ""
    return f"{sign}{cum_pct:.1f}%{since_str}"


def _thesis_status_icon(status: str) -> str:
    """Map thesis status to a simple text indicator."""
    mapping = {
        "intact": "[OK]",
        "strengthening": "[STRONG]",
        "evolving": "[WATCH]",
        "weakening": "[CAUTION]",
        "invalidated": "[INVALID]",
    }
    return mapping.get(status.lower(), "[?]")
