"""Technical analysis engine for AlphaDesk Portfolio Analyst.

Computes moving averages, RSI, MACD, Bollinger Bands, and volume
analysis on OHLCV DataFrames. Detects actionable signals (golden/death
crosses, overbought/oversold, breakouts) and publishes them to the
agent bus.
"""

from typing import Any

import pandas as pd
import ta

from src.shared.agent_bus import publish
from src.utils.logger import get_logger

log = get_logger(__name__)

SOURCE_AGENT = "portfolio_analyst"

# Number of recent trading days to check for crossover events
CROSSOVER_LOOKBACK = 5


def compute_moving_averages(df: pd.DataFrame) -> dict[str, Any]:
    """Compute SMA 20, 50, 200 and detect golden / death crosses.

    A golden cross is when the SMA-50 crosses above the SMA-200.
    A death cross is when the SMA-50 crosses below the SMA-200.
    Crossovers are detected within the last 5 trading days.

    Args:
        df: OHLCV DataFrame with at least a 'Close' column.

    Returns:
        Dict with sma_20, sma_50, sma_200 (latest values),
        golden_cross (bool), death_cross (bool).
    """
    close = df["Close"]
    sma_20 = close.rolling(window=20).mean()
    sma_50 = close.rolling(window=50).mean()
    sma_200 = close.rolling(window=200).mean()

    result: dict[str, Any] = {
        "sma_20": round(sma_20.iloc[-1], 2) if len(sma_20.dropna()) > 0 else None,
        "sma_50": round(sma_50.iloc[-1], 2) if len(sma_50.dropna()) > 0 else None,
        "sma_200": round(sma_200.iloc[-1], 2) if len(sma_200.dropna()) > 0 else None,
        "golden_cross": False,
        "death_cross": False,
    }

    # Need at least 200 + CROSSOVER_LOOKBACK rows for meaningful cross detection
    if len(sma_50.dropna()) < CROSSOVER_LOOKBACK or len(sma_200.dropna()) < CROSSOVER_LOOKBACK:
        return result

    recent_50 = sma_50.dropna().iloc[-CROSSOVER_LOOKBACK:]
    recent_200 = sma_200.dropna().iloc[-CROSSOVER_LOOKBACK:]

    # Align indices for comparison
    common_idx = recent_50.index.intersection(recent_200.index)
    if len(common_idx) < 2:
        return result

    r50 = recent_50.loc[common_idx]
    r200 = recent_200.loc[common_idx]

    for i in range(1, len(common_idx)):
        prev_diff = r50.iloc[i - 1] - r200.iloc[i - 1]
        curr_diff = r50.iloc[i] - r200.iloc[i]

        if prev_diff <= 0 < curr_diff:
            result["golden_cross"] = True
        if prev_diff >= 0 > curr_diff:
            result["death_cross"] = True

    return result


def compute_rsi(df: pd.DataFrame, period: int = 14) -> dict[str, Any]:
    """Compute RSI and flag overbought / oversold conditions.

    Args:
        df: OHLCV DataFrame with a 'Close' column.
        period: RSI look-back period (default 14).

    Returns:
        Dict with rsi (float), overbought (bool), oversold (bool).
    """
    rsi_series = ta.momentum.RSIIndicator(close=df["Close"], window=period).rsi()
    current_rsi = rsi_series.iloc[-1] if len(rsi_series.dropna()) > 0 else None

    return {
        "rsi": round(current_rsi, 2) if current_rsi is not None else None,
        "overbought": current_rsi is not None and current_rsi > 70,
        "oversold": current_rsi is not None and current_rsi < 30,
    }


def compute_macd(df: pd.DataFrame) -> dict[str, Any]:
    """Compute MACD (12, 26, 9) and detect crossovers in last 5 days.

    Args:
        df: OHLCV DataFrame with a 'Close' column.

    Returns:
        Dict with macd_line, signal_line, histogram (latest values),
        bullish_crossover (bool), bearish_crossover (bool).
    """
    macd_indicator = ta.trend.MACD(
        close=df["Close"], window_slow=26, window_fast=12, window_sign=9
    )
    macd_line = macd_indicator.macd()
    signal_line = macd_indicator.macd_signal()
    histogram = macd_indicator.macd_diff()

    result: dict[str, Any] = {
        "macd_line": round(macd_line.iloc[-1], 4) if len(macd_line.dropna()) > 0 else None,
        "signal_line": round(signal_line.iloc[-1], 4) if len(signal_line.dropna()) > 0 else None,
        "histogram": round(histogram.iloc[-1], 4) if len(histogram.dropna()) > 0 else None,
        "bullish_crossover": False,
        "bearish_crossover": False,
    }

    if len(macd_line.dropna()) < CROSSOVER_LOOKBACK or len(signal_line.dropna()) < CROSSOVER_LOOKBACK:
        return result

    recent_macd = macd_line.dropna().iloc[-CROSSOVER_LOOKBACK:]
    recent_signal = signal_line.dropna().iloc[-CROSSOVER_LOOKBACK:]

    common_idx = recent_macd.index.intersection(recent_signal.index)
    if len(common_idx) < 2:
        return result

    rm = recent_macd.loc[common_idx]
    rs = recent_signal.loc[common_idx]

    for i in range(1, len(common_idx)):
        prev_diff = rm.iloc[i - 1] - rs.iloc[i - 1]
        curr_diff = rm.iloc[i] - rs.iloc[i]

        if prev_diff <= 0 < curr_diff:
            result["bullish_crossover"] = True
        if prev_diff >= 0 > curr_diff:
            result["bearish_crossover"] = True

    return result


def compute_bollinger_bands(
    df: pd.DataFrame, period: int = 20, std: int = 2
) -> dict[str, Any]:
    """Compute Bollinger Bands and flag breakouts.

    Args:
        df: OHLCV DataFrame with a 'Close' column.
        period: Moving average period (default 20).
        std: Number of standard deviations (default 2).

    Returns:
        Dict with upper_band, lower_band, middle_band (latest values),
        above_upper (bool), below_lower (bool).
    """
    bb = ta.volatility.BollingerBands(
        close=df["Close"], window=period, window_dev=std
    )
    upper = bb.bollinger_hband()
    lower = bb.bollinger_lband()
    middle = bb.bollinger_mavg()

    latest_close = df["Close"].iloc[-1]
    latest_upper = upper.iloc[-1] if len(upper.dropna()) > 0 else None
    latest_lower = lower.iloc[-1] if len(lower.dropna()) > 0 else None
    latest_middle = middle.iloc[-1] if len(middle.dropna()) > 0 else None

    return {
        "upper_band": round(latest_upper, 2) if latest_upper is not None else None,
        "lower_band": round(latest_lower, 2) if latest_lower is not None else None,
        "middle_band": round(latest_middle, 2) if latest_middle is not None else None,
        "above_upper": latest_upper is not None and latest_close > latest_upper,
        "below_lower": latest_lower is not None and latest_close < latest_lower,
    }


def compute_volume_analysis(df: pd.DataFrame) -> dict[str, Any]:
    """Analyse latest volume relative to 20-day average.

    Args:
        df: OHLCV DataFrame with a 'Volume' column.

    Returns:
        Dict with latest_volume, avg_volume_20d, volume_ratio,
        unusual_volume (bool, True if >2x average).
    """
    if "Volume" not in df.columns or len(df) < 2:
        return {
            "latest_volume": None,
            "avg_volume_20d": None,
            "volume_ratio": None,
            "unusual_volume": False,
        }

    latest_volume = int(df["Volume"].iloc[-1])
    avg_20 = df["Volume"].tail(20).mean()

    ratio = latest_volume / avg_20 if avg_20 > 0 else 0.0

    return {
        "latest_volume": latest_volume,
        "avg_volume_20d": int(round(avg_20)),
        "volume_ratio": round(ratio, 2),
        "unusual_volume": ratio > 2.0,
    }


def analyze_ticker(ticker: str, df: pd.DataFrame) -> dict[str, Any]:
    """Run all technical indicators on a single ticker.

    Args:
        ticker: Ticker symbol.
        df: OHLCV DataFrame for the ticker.

    Returns:
        Dict with all indicator values plus a signals_summary list of
        human-readable alert strings.
    """
    if df.empty or len(df) < 2:
        log.warning("Insufficient data for technical analysis of %s", ticker)
        return {"ticker": ticker, "error": "insufficient_data", "signals_summary": []}

    signals: list[str] = []

    # Moving averages
    ma = compute_moving_averages(df)
    if ma["golden_cross"]:
        signals.append("Golden Cross (SMA-50 crossed above SMA-200)")
    if ma["death_cross"]:
        signals.append("Death Cross (SMA-50 crossed below SMA-200)")

    # RSI
    rsi = compute_rsi(df)
    if rsi["overbought"]:
        signals.append(f"RSI overbought ({rsi['rsi']})")
    if rsi["oversold"]:
        signals.append(f"RSI oversold ({rsi['rsi']})")

    # MACD
    macd = compute_macd(df)
    if macd["bullish_crossover"]:
        signals.append("MACD bullish crossover")
    if macd["bearish_crossover"]:
        signals.append("MACD bearish crossover")

    # Bollinger Bands
    bb = compute_bollinger_bands(df)
    if bb["above_upper"]:
        signals.append("Price above upper Bollinger Band")
    if bb["below_lower"]:
        signals.append("Price below lower Bollinger Band")

    # Volume
    vol = compute_volume_analysis(df)
    if vol["unusual_volume"]:
        signals.append(f"Unusual volume ({vol['volume_ratio']}x avg)")

    return {
        "ticker": ticker,
        "moving_averages": ma,
        "rsi": rsi,
        "macd": macd,
        "bollinger_bands": bb,
        "volume": vol,
        "signals_summary": signals,
    }


def analyze_all(
    tickers: list[str], historical_data: dict[str, pd.DataFrame]
) -> dict[str, dict[str, Any]]:
    """Run technical analysis on all tickers and publish strong signals.

    Args:
        tickers: List of ticker symbols to analyse.
        historical_data: Dict mapping ticker -> OHLCV DataFrame.

    Returns:
        Dict mapping ticker -> analysis result dict.
    """
    results: dict[str, dict[str, Any]] = {}

    for ticker in tickers:
        df = historical_data.get(ticker)
        if df is None or df.empty:
            log.warning("No historical data for %s — skipping technical analysis", ticker)
            continue

        try:
            analysis = analyze_ticker(ticker, df)
            results[ticker] = analysis

            # Publish strong signals to the agent bus
            if analysis.get("signals_summary"):
                try:
                    publish(
                        signal_type="technical_signal",
                        source_agent=SOURCE_AGENT,
                        payload={
                            "ticker": ticker,
                            "signals": analysis["signals_summary"],
                        },
                    )
                except Exception:
                    log.exception(
                        "Failed to publish technical_signal for %s", ticker
                    )

        except Exception:
            log.exception("Error analysing %s", ticker)

    log.info(
        "Technical analysis complete: %d/%d tickers",
        len(results),
        len(tickers),
    )
    return results
