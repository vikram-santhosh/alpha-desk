"""Outcome tracker for backtesting.

Computes forward-looking 1d/3d/7d returns from pre-fetched price data
and builds per-agent performance metrics.
"""

from datetime import date, timedelta
from typing import Any

import pandas as pd

from src.backtest.signal_capture import CapturedSignal
from src.utils.logger import get_logger

log = get_logger(__name__)


def compute_forward_returns(
    ticker: str,
    signal_date: date,
    ticker_dfs: dict[str, pd.DataFrame],
    horizons: tuple[int, ...] = (1, 3, 7),
) -> dict[str, float | None]:
    """Compute forward-looking returns at given horizons from signal date.

    Args:
        ticker: Stock ticker.
        signal_date: Date of the signal.
        ticker_dfs: Pre-fetched DataFrames keyed by ticker.
        horizons: Tuple of day counts for return computation.

    Returns:
        Dict mapping "return_{n}d" to percentage return, or None if data unavailable.
    """
    df = ticker_dfs.get(ticker)
    if df is None or df.empty:
        return {f"return_{h}d": None for h in horizons}

    signal_ts = pd.Timestamp(signal_date)
    if signal_ts not in df.index:
        return {f"return_{h}d": None for h in horizons}

    entry_price = float(df.loc[signal_ts]["Close"])
    if entry_price == 0:
        return {f"return_{h}d": None for h in horizons}

    returns: dict[str, float | None] = {}
    for h in horizons:
        target_date = signal_date + timedelta(days=h)
        # Find the nearest trading day at or after target_date
        future_dates = df.index[df.index >= pd.Timestamp(target_date)]
        if len(future_dates) == 0:
            returns[f"return_{h}d"] = None
            continue
        nearest = future_dates[0]
        exit_price = float(df.loc[nearest]["Close"])
        ret = ((exit_price - entry_price) / entry_price) * 100
        returns[f"return_{h}d"] = round(ret, 2)

    return returns


def score_signal(signal: CapturedSignal, forward_returns: dict[str, float | None]) -> dict[str, Any]:
    """Score a single signal against its forward returns.

    Returns dict with signal info, returns, and classification
    (TP, FP, TN, FN for the 7d horizon).
    """
    ret_7d = forward_returns.get("return_7d")
    is_bullish = signal.signal_type == "bullish"

    classification = "N/A"
    if ret_7d is not None:
        positive_return = ret_7d > 0
        if is_bullish and positive_return:
            classification = "TP"  # True positive: bullish + positive return
        elif is_bullish and not positive_return:
            classification = "FP"  # False positive: bullish + negative return
        elif not is_bullish and not positive_return:
            classification = "TN"  # True negative: bearish/neutral + negative return
        elif not is_bullish and positive_return:
            classification = "FN"  # False negative: bearish/neutral + positive return

    return {
        "date": signal.date,
        "agent": signal.agent,
        "ticker": signal.ticker,
        "signal_type": signal.signal_type,
        "conviction": signal.conviction,
        "reasoning": signal.reasoning,
        "return_1d": forward_returns.get("return_1d"),
        "return_3d": forward_returns.get("return_3d"),
        "return_7d": forward_returns.get("return_7d"),
        "classification_7d": classification,
    }


def build_agent_metrics(scored_signals: list[dict]) -> dict[str, dict]:
    """Build per-agent performance metrics from scored signals.

    Returns dict keyed by agent name with metrics:
    - total_signals, bullish_signals, bearish_signals
    - hit_rate (bullish signals with positive 7d return)
    - avg_return_1d, avg_return_3d, avg_return_7d
    - false_positive_rate
    - confusion_matrix: {TP, FP, TN, FN}
    """
    from collections import defaultdict

    by_agent: dict[str, list[dict]] = defaultdict(list)
    for s in scored_signals:
        by_agent[s["agent"]].append(s)

    metrics: dict[str, dict] = {}
    for agent, signals in by_agent.items():
        bullish = [s for s in signals if s["signal_type"] == "bullish"]
        bearish = [s for s in signals if s["signal_type"] in ("bearish", "neutral")]

        # Hit rate: bullish signals with positive 7d return
        bullish_with_7d = [s for s in bullish if s["return_7d"] is not None]
        hits = sum(1 for s in bullish_with_7d if s["return_7d"] > 0)
        hit_rate = (hits / len(bullish_with_7d) * 100) if bullish_with_7d else 0

        # Average returns
        def _avg(signals_list: list[dict], key: str) -> float | None:
            vals = [s[key] for s in signals_list if s[key] is not None]
            return round(sum(vals) / len(vals), 2) if vals else None

        all_with_returns = [s for s in signals if s["return_7d"] is not None]

        # Confusion matrix
        cm = {"TP": 0, "FP": 0, "TN": 0, "FN": 0}
        for s in signals:
            cls = s.get("classification_7d", "N/A")
            if cls in cm:
                cm[cls] += 1

        # False positive rate
        total_positives = cm["TP"] + cm["FP"]
        fp_rate = (cm["FP"] / total_positives * 100) if total_positives > 0 else 0

        metrics[agent] = {
            "total_signals": len(signals),
            "bullish_signals": len(bullish),
            "bearish_signals": len(bearish),
            "hit_rate": round(hit_rate, 1),
            "avg_return_1d": _avg(all_with_returns, "return_1d"),
            "avg_return_3d": _avg(all_with_returns, "return_3d"),
            "avg_return_7d": _avg(all_with_returns, "return_7d"),
            "false_positive_rate": round(fp_rate, 1),
            "confusion_matrix": cm,
        }

    return metrics


def build_overall_metrics(scored_signals: list[dict]) -> dict[str, Any]:
    """Build overall backtest metrics from all scored signals."""
    total = len(scored_signals)
    if total == 0:
        return {"total_signals": 0}

    bullish = [s for s in scored_signals if s["signal_type"] == "bullish"]
    with_7d = [s for s in scored_signals if s["return_7d"] is not None]
    bullish_with_7d = [s for s in bullish if s["return_7d"] is not None]

    hits = sum(1 for s in bullish_with_7d if s["return_7d"] > 0)
    hit_rate = (hits / len(bullish_with_7d) * 100) if bullish_with_7d else 0

    def _avg(lst: list[dict], key: str) -> float | None:
        vals = [s[key] for s in lst if s[key] is not None]
        return round(sum(vals) / len(vals), 2) if vals else None

    return {
        "total_signals": total,
        "bullish_signals": len(bullish),
        "signals_with_outcomes": len(with_7d),
        "overall_hit_rate": round(hit_rate, 1),
        "avg_return_1d": _avg(with_7d, "return_1d"),
        "avg_return_3d": _avg(with_7d, "return_3d"),
        "avg_return_7d": _avg(with_7d, "return_7d"),
    }
