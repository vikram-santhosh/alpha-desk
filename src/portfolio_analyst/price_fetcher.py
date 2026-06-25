"""Price data fetching via yfinance for AlphaDesk Portfolio Analyst.

Fetches current and historical OHLCV data for portfolio holdings and
watchlist tickers. Handles per-ticker errors gracefully so one bad
ticker does not prevent the rest from loading.
"""

import time
from datetime import datetime, timedelta
from typing import Any

import pandas as pd
import yfinance as yf

from src.shared.security import sanitize_ticker
from src.utils.logger import get_logger

log = get_logger(__name__)


def fetch_current_prices(tickers: list[str]) -> dict[str, dict[str, Any]]:
    """Fetch current / latest prices for a list of tickers.

    Args:
        tickers: List of ticker symbols (e.g. ["AMZN", "GOOG"]).

    Returns:
        Dict mapping ticker -> {price, change, change_pct, volume, prev_close}.
        Tickers that fail to load are omitted with a warning logged.
    """
    results: dict[str, dict[str, Any]] = {}
    start = time.time()

    # Use explicit date range to bypass yfinance LRU cache.
    # period="2d" gets silently cached; explicit start/end forces a fresh HTTP call.
    today = datetime.now()
    start_date = (today - timedelta(days=5)).strftime("%Y-%m-%d")
    end_date = (today + timedelta(days=1)).strftime("%Y-%m-%d")

    for raw_ticker in tickers:
        try:
            ticker = sanitize_ticker(raw_ticker)
            t = yf.Ticker(ticker)
            hist = t.history(start=start_date, end=end_date)

            if hist.empty or len(hist) < 1:
                log.warning("No price data for %s — skipping", ticker)
                continue

            latest = hist.iloc[-1]
            price = float(latest["Close"])
            latest_date = hist.index[-1]

            # Staleness check: warn if latest data point is > 1 trading day old
            age_days = (today - latest_date.to_pydatetime().replace(tzinfo=None)).days
            if age_days > 2:
                log.warning(
                    "STALE DATA for %s: latest bar is %d days old (%s)",
                    ticker, age_days, latest_date.strftime("%Y-%m-%d"),
                )

            if len(hist) >= 2:
                prev_close = float(hist.iloc[-2]["Close"])
            else:
                prev_close = price

            change = price - prev_close
            change_pct = (change / prev_close * 100) if prev_close != 0 else 0.0

            results[ticker] = {
                "price": round(price, 2),
                "change": round(change, 2),
                "change_pct": round(change_pct, 2),
                "volume": int(latest.get("Volume", 0)),
                "prev_close": round(prev_close, 2),
                "price_date": latest_date.strftime("%Y-%m-%d"),
            }

        except Exception:
            log.exception("Error fetching current price for %s", raw_ticker)

    elapsed = time.time() - start
    log.info(
        "Fetched current prices for %d/%d tickers in %.2fs",
        len(results),
        len(tickers),
        elapsed,
    )

    # Summary staleness check
    if results:
        dates = [v.get("price_date", "") for v in results.values()]
        unique_dates = set(dates)
        today_str = today.strftime("%Y-%m-%d")
        if unique_dates and today_str not in unique_dates:
            log.warning(
                "STALENESS WARNING: No ticker has today's date (%s). Dates seen: %s",
                today_str, unique_dates,
            )

    return results


def fetch_historical(ticker: str, period: str = "1y") -> pd.DataFrame:
    """Fetch historical daily OHLCV data for a single ticker.

    Args:
        ticker: Ticker symbol.
        period: yfinance period string (default "1y").

    Returns:
        DataFrame with columns: Open, High, Low, Close, Volume.
        Returns empty DataFrame on error.
    """
    start = time.time()
    try:
        clean_ticker = sanitize_ticker(ticker)
        t = yf.Ticker(clean_ticker)
        df = t.history(period=period)

        if df.empty:
            log.warning("No historical data for %s (period=%s)", clean_ticker, period)
            return pd.DataFrame()

        # Keep only the standard OHLCV columns
        ohlcv_cols = ["Open", "High", "Low", "Close", "Volume"]
        available = [c for c in ohlcv_cols if c in df.columns]
        df = df[available]

        elapsed = time.time() - start
        log.info(
            "Fetched %d data points for %s (period=%s) in %.2fs",
            len(df),
            clean_ticker,
            period,
            elapsed,
        )
        return df

    except Exception:
        log.exception("Error fetching historical data for %s", ticker)
        return pd.DataFrame()


def fetch_all_historical(
    tickers: list[str], period: str = "1y"
) -> dict[str, pd.DataFrame]:
    """Fetch historical data for all tickers.

    Args:
        tickers: List of ticker symbols.
        period: yfinance period string (default "1y").

    Returns:
        Dict mapping ticker -> DataFrame of OHLCV data.
        Tickers that fail are omitted.
    """
    results: dict[str, pd.DataFrame] = {}
    start = time.time()

    for raw_ticker in tickers:
        try:
            ticker = sanitize_ticker(raw_ticker)
            df = fetch_historical(ticker, period=period)
            if not df.empty:
                results[ticker] = df
        except Exception:
            log.exception("Error in fetch_all_historical for %s", raw_ticker)

    elapsed = time.time() - start
    log.info(
        "Fetched historical data for %d/%d tickers in %.2fs",
        len(results),
        len(tickers),
        elapsed,
    )
    return results
