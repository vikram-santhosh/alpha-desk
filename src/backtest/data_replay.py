"""Data replay provider for backtesting.

Provides functions to build historical data for a specific day from
pre-fetched yfinance DataFrames. Used by the BacktestRunner to replay
the pipeline with historical prices.
"""

from datetime import date, timedelta
from typing import Any

import pandas as pd
import yfinance as yf

from src.utils.logger import get_logger

log = get_logger(__name__)

EXTRA_HISTORY_DAYS = 30  # Extra days before first trading day for tech analysis lookback


def get_trading_days(num_days: int) -> list[date]:
    """Get the last N trading days (Mon-Fri, with data in SPY)."""
    end = date.today()
    start = end - timedelta(days=num_days * 3)
    spy = yf.download("SPY", start=start.isoformat(), end=end.isoformat(),
                       progress=False, auto_adjust=True)
    if spy.empty:
        raise RuntimeError("Could not fetch SPY data to determine trading days")
    trading_dates = [d.date() if hasattr(d, 'date') else d for d in spy.index]
    return trading_dates[-num_days:]


def fetch_all_historical_data(
    tickers: list[str],
    macro_symbols: list[str],
    trading_days: list[date],
) -> dict[str, pd.DataFrame]:
    """Pre-fetch all historical data in bulk.

    Downloads price data from before the first trading day (for tech analysis
    lookback) through the last trading day + forward-looking days for outcome
    tracking.
    """
    first_day = trading_days[0]
    last_day = trading_days[-1]

    start_date = first_day - timedelta(days=EXTRA_HISTORY_DAYS + 5)
    # Fetch extra days after last_day for forward-looking outcome tracking
    end_date = last_day + timedelta(days=10)

    log.info("Downloading price data: %s to %s", start_date, end_date)

    all_symbols = tickers + macro_symbols
    data = yf.download(
        all_symbols,
        start=start_date.isoformat(),
        end=end_date.isoformat(),
        progress=False,
        auto_adjust=True,
        group_by="ticker",
    )

    ticker_dfs: dict[str, pd.DataFrame] = {}
    for sym in all_symbols:
        try:
            if len(all_symbols) == 1:
                df = data.copy()
            else:
                df = data[sym].copy() if sym in data.columns.get_level_values(0) else pd.DataFrame()
            df = df.dropna(how="all")
            if not df.empty:
                ticker_dfs[sym] = df
        except Exception as e:
            log.warning("Could not parse data for %s: %s", sym, e)

    log.info("Got data for %d/%d symbols", len(ticker_dfs), len(all_symbols))
    return ticker_dfs


def build_prices_for_day(
    ticker_dfs: dict[str, pd.DataFrame],
    tickers: list[str],
    day: date,
    prev_day: date | None,
) -> dict[str, dict]:
    """Build the prices dict for a specific day, matching fetch_current_prices format."""
    prices: dict[str, dict] = {}
    for ticker in tickers:
        df = ticker_dfs.get(ticker)
        if df is None or df.empty:
            continue

        day_ts = pd.Timestamp(day)
        if day_ts not in df.index:
            continue

        row = df.loc[day_ts]
        close = float(row["Close"])

        prev_close = None
        change = None
        change_pct = None

        if prev_day is not None:
            prev_ts = pd.Timestamp(prev_day)
            if prev_ts in df.index:
                prev_close = float(df.loc[prev_ts]["Close"])
                change = close - prev_close
                change_pct = (change / prev_close * 100) if prev_close != 0 else 0
        else:
            day_idx = df.index.get_loc(day_ts)
            if day_idx > 0:
                prev_row = df.iloc[day_idx - 1]
                prev_close = float(prev_row["Close"])
                change = close - prev_close
                change_pct = (change / prev_close * 100) if prev_close != 0 else 0

        volume = float(row["Volume"]) if "Volume" in row and pd.notna(row["Volume"]) else 0

        prices[ticker] = {
            "price": round(close, 2),
            "change": round(change, 2) if change is not None else None,
            "change_pct": round(change_pct, 2) if change_pct is not None else None,
            "prev_close": round(prev_close, 2) if prev_close is not None else None,
            "volume": int(volume),
        }

    return prices


def build_macro_for_day(
    ticker_dfs: dict[str, pd.DataFrame],
    day: date,
    prev_day: date | None,
) -> dict[str, Any]:
    """Build macro data dict for a specific day matching fetch_macro_data format."""
    macro: dict[str, Any] = {}
    day_ts = pd.Timestamp(day)

    # SPY -> S&P 500 proxy
    spy_df = ticker_dfs.get("SPY")
    if spy_df is not None and day_ts in spy_df.index:
        spy_close = float(spy_df.loc[day_ts]["Close"])
        spy_chg = None
        if prev_day is not None:
            prev_ts = pd.Timestamp(prev_day)
            if prev_ts in spy_df.index:
                prev = float(spy_df.loc[prev_ts]["Close"])
                spy_chg = round((spy_close - prev) / prev * 100, 2) if prev != 0 else 0
        macro["sp500"] = {"value": round(spy_close, 2), "change_pct": spy_chg}

    # VIX
    vix_df = ticker_dfs.get("^VIX")
    if vix_df is not None and day_ts in vix_df.index:
        vix_close = float(vix_df.loc[day_ts]["Close"])
        vix_chg = None
        if prev_day is not None:
            prev_ts = pd.Timestamp(prev_day)
            if prev_ts in vix_df.index:
                prev = float(vix_df.loc[prev_ts]["Close"])
                vix_chg = round((vix_close - prev) / prev * 100, 2) if prev != 0 else 0
        macro["vix"] = {"value": round(vix_close, 2), "change_pct": vix_chg}

    # 10Y Treasury Yield
    tnx_df = ticker_dfs.get("^TNX")
    if tnx_df is not None and day_ts in tnx_df.index:
        tnx_close = float(tnx_df.loc[day_ts]["Close"])
        tnx_chg = None
        if prev_day is not None:
            prev_ts = pd.Timestamp(prev_day)
            if prev_ts in tnx_df.index:
                prev = float(tnx_df.loc[prev_ts]["Close"])
                tnx_chg = round(tnx_close - prev, 3)
        macro["treasury_10y"] = {"value": round(tnx_close, 3), "change_pct": tnx_chg}

    return macro


def build_historical_up_to_day(
    ticker_dfs: dict[str, pd.DataFrame],
    tickers: list[str],
    day: date,
) -> dict[str, pd.DataFrame]:
    """Truncate historical data to only include data up to (and including) the given day."""
    result: dict[str, pd.DataFrame] = {}
    day_ts = pd.Timestamp(day)

    for ticker in tickers:
        df = ticker_dfs.get(ticker)
        if df is None or df.empty:
            continue
        truncated = df[df.index <= day_ts].copy()
        if not truncated.empty:
            result[ticker] = truncated

    return result


def get_macro_symbols() -> list[str]:
    """Standard macro tickers to download."""
    return ["^VIX", "SPY", "^TNX"]
