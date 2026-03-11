"""Fundamental analysis engine for AlphaDesk Portfolio Analyst.

Fetches valuation, profitability, and growth metrics from yfinance and
detects conditions that warrant alerts (extreme P/E, 52-week
proximity, upcoming earnings, negative margins).
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import yfinance as yf

from src.shared.agent_bus import publish
from src.shared.security import sanitize_ticker
from src.utils.logger import get_logger

log = get_logger(__name__)

SOURCE_AGENT = "portfolio_analyst"

# yfinance .info key mapping
_KEY_MAP: dict[str, str] = {
    "pe_trailing": "trailingPE",
    "pe_forward": "forwardPE",
    "eps_trailing": "trailingEps",
    "eps_forward": "forwardEps",
    "revenue": "totalRevenue",
    "revenue_growth": "revenueGrowth",
    "gross_margin": "grossMargins",
    "operating_margin": "operatingMargins",
    "net_margin": "profitMargins",
    "market_cap": "marketCap",
    "beta": "beta",
    "fifty_two_week_high": "fiftyTwoWeekHigh",
    "fifty_two_week_low": "fiftyTwoWeekLow",
    "sector": "sector",
    "industry": "industry",
    "short_name": "shortName",
}


def _safe_pct(current: float | None, reference: float | None) -> float | None:
    """Compute percentage distance: (current - reference) / reference * 100."""
    if current is None or reference is None or reference == 0:
        return None
    return round((current - reference) / reference * 100, 2)


def fetch_fundamentals(ticker: str) -> dict[str, Any]:
    """Fetch fundamental data for a single ticker.

    Args:
        ticker: Stock ticker symbol.

    Returns:
        Dict of fundamental metrics. Keys with unavailable data are set
        to None.
    """
    clean = sanitize_ticker(ticker)
    t = yf.Ticker(clean)
    info: dict[str, Any] = t.info or {}

    result: dict[str, Any] = {"ticker": clean}

    # Map standard keys
    for our_key, yf_key in _KEY_MAP.items():
        result[our_key] = info.get(yf_key)

    # Compute derived fields
    price = info.get("currentPrice") or info.get("regularMarketPrice")
    result["current_price"] = price
    result["pct_from_52w_high"] = _safe_pct(price, result["fifty_two_week_high"])
    result["pct_from_52w_low"] = _safe_pct(price, result["fifty_two_week_low"])

    # Next earnings date — yfinance exposes this via .calendar
    next_earnings: str | None = None
    try:
        cal = t.calendar
        if cal is not None:
            # calendar can be a DataFrame or a dict depending on yfinance version
            if hasattr(cal, "get"):
                earnings_dates = cal.get("Earnings Date")
                if isinstance(earnings_dates, list) and earnings_dates:
                    next_earnings = str(earnings_dates[0])
                elif earnings_dates is not None:
                    next_earnings = str(earnings_dates)
            elif hasattr(cal, "columns"):
                if "Earnings Date" in cal.columns:
                    next_earnings = str(cal["Earnings Date"].iloc[0])
    except Exception:
        log.debug("Could not retrieve earnings calendar for %s", clean)

    result["next_earnings_date"] = next_earnings

    log.info("Fetched fundamentals for %s", clean)
    return result


def fetch_all_fundamentals(tickers: list[str]) -> dict[str, dict[str, Any]]:
    """Fetch fundamental data for all tickers, handling errors per-ticker.

    Args:
        tickers: List of ticker symbols.

    Returns:
        Dict mapping ticker -> fundamentals dict.
    """
    results: dict[str, dict[str, Any]] = {}

    for raw_ticker in tickers:
        try:
            ticker = sanitize_ticker(raw_ticker)
            data = fetch_fundamentals(ticker)
            results[ticker] = data
        except Exception:
            log.exception("Error fetching fundamentals for %s", raw_ticker)

    log.info(
        "Fetched fundamentals for %d/%d tickers",
        len(results),
        len(tickers),
    )
    return results


def detect_fundamental_alerts(
    fundamentals: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Detect noteworthy fundamental conditions and publish alerts.

    Checks:
        - P/E > 50 or P/E < 5 (extreme valuation)
        - Price within 5% of 52-week high or low
        - Earnings within 7 days
        - Negative gross, operating, or net margin

    Args:
        fundamentals: Dict mapping ticker -> fundamentals dict
            (as returned by fetch_fundamentals).

    Returns:
        List of alert dicts with keys: ticker, alert_type, message.
    """
    alerts: list[dict[str, Any]] = []

    for ticker, data in fundamentals.items():
        ticker_alerts: list[str] = []

        # Extreme P/E
        pe = data.get("pe_trailing")
        if pe is not None:
            if pe > 50:
                ticker_alerts.append(f"High trailing P/E: {pe:.1f}")
            elif 0 < pe < 5:
                ticker_alerts.append(f"Low trailing P/E: {pe:.1f}")

        pe_fwd = data.get("pe_forward")
        if pe_fwd is not None:
            if pe_fwd > 50:
                ticker_alerts.append(f"High forward P/E: {pe_fwd:.1f}")
            elif 0 < pe_fwd < 5:
                ticker_alerts.append(f"Low forward P/E: {pe_fwd:.1f}")

        # 52-week proximity
        pct_high = data.get("pct_from_52w_high")
        pct_low = data.get("pct_from_52w_low")

        if pct_high is not None and abs(pct_high) <= 5:
            ticker_alerts.append(
                f"Within {abs(pct_high):.1f}% of 52-week high"
            )

        if pct_low is not None and pct_low <= 5:
            ticker_alerts.append(
                f"Within {abs(pct_low):.1f}% of 52-week low"
            )

        # Earnings within 7 days
        next_earnings = data.get("next_earnings_date")
        if next_earnings:
            try:
                # Handle various date string formats
                for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"):
                    try:
                        ed = datetime.strptime(str(next_earnings).split("+")[0].strip(), fmt)
                        break
                    except ValueError:
                        continue
                else:
                    ed = None

                if ed is not None:
                    days_until = (ed.date() - datetime.now().date()).days
                    if 0 <= days_until <= 7:
                        ticker_alerts.append(
                            f"Earnings in {days_until} day(s) ({ed.strftime('%Y-%m-%d')})"
                        )
            except Exception:
                log.debug("Could not parse earnings date '%s' for %s", next_earnings, ticker)

        # Negative margins
        for margin_key, label in [
            ("gross_margin", "Gross margin"),
            ("operating_margin", "Operating margin"),
            ("net_margin", "Net margin"),
        ]:
            margin = data.get(margin_key)
            if margin is not None and margin < 0:
                ticker_alerts.append(f"Negative {label}: {margin * 100:.1f}%")

        # Collect and publish
        for msg in ticker_alerts:
            alert = {"ticker": ticker, "alert_type": "fundamental", "message": msg}
            alerts.append(alert)

        if ticker_alerts:
            try:
                publish(
                    signal_type="fundamental_alert",
                    source_agent=SOURCE_AGENT,
                    payload={
                        "ticker": ticker,
                        "alerts": ticker_alerts,
                    },
                )
            except Exception:
                log.exception("Failed to publish fundamental_alert for %s", ticker)

    log.info("Detected %d fundamental alerts across %d tickers", len(alerts), len(fundamentals))
    return alerts
