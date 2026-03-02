#!/usr/bin/env python3
"""Historic Data Backtest for AlphaDesk v2 Pipeline.

Replays the last 5 trading days through the real pipeline with:
- Real historical prices from yfinance
- Real Anthropic API calls (analyst committee)
- Temp SQLite DB so production data is untouched
- Delta engine comparing real day-over-day changes

Usage:
    python tests/backtest_historic.py

Estimated cost: ~$3-4 for 5 days (committee + conviction/moonshot thesis generation)
Estimated time: ~3-5 minutes (yfinance fetches + LLM calls)
"""

import asyncio
import json
import os
import sqlite3
import sys
import tempfile
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

# ── Setup project path ────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

# Load .env if present
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import pandas as pd
import yfinance as yf

# ═══════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════

NUM_DAYS = 5
EXTRA_HISTORY_DAYS = 30  # Extra days for technical analysis lookback

# Visual separators
THICK_SEP = "\u2501" * 50
THIN_SEP = "\u2500" * 50


def _sanitize_for_json(obj):
    """Recursively convert numpy types to Python natives for JSON serialization."""
    import numpy as np
    if isinstance(obj, dict):
        return {k: _sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_for_json(v) for v in obj]
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    return obj


def load_config():
    """Load advisor config to get tickers and settings."""
    from src.shared.config_loader import load_config as _load
    config = _load("advisor")

    # Merge private portfolio if it exists
    private_path = PROJECT_ROOT / "private" / "portfolio.yaml"
    if private_path.exists():
        try:
            import yaml
            with open(private_path) as f:
                private = yaml.safe_load(f) or {}
            if "holdings" in private:
                config["holdings"] = private["holdings"]
        except Exception:
            pass

    return config


def get_tickers(config):
    """Extract all tracked tickers from config."""
    tickers = [h["ticker"] for h in config.get("holdings", [])]
    return list(dict.fromkeys(tickers))  # dedupe preserving order


def get_macro_symbols():
    """Macro tickers to download."""
    return ["^VIX", "SPY", "^TNX"]


# ═══════════════════════════════════════════════════════════════════
# TEMP DB ISOLATION (imported from shared module)
# ═══════════════════════════════════════════════════════════════════

from src.backtest.db_isolation import TempDBContext


# ═══════════════════════════════════════════════════════════════════
# DATA FETCHING
# ═══════════════════════════════════════════════════════════════════

def get_trading_days(num_days: int) -> list[date]:
    """Get the last N trading days (Mon-Fri, with data in SPY)."""
    # Download recent SPY data to find actual trading days
    end = date.today()
    start = end - timedelta(days=num_days * 3)  # generous lookback
    spy = yf.download("SPY", start=start.isoformat(), end=end.isoformat(),
                       progress=False, auto_adjust=True)
    if spy.empty:
        raise RuntimeError("Could not fetch SPY data to determine trading days")

    # Get the last N trading days
    trading_dates = [d.date() if hasattr(d, 'date') else d for d in spy.index]
    return trading_dates[-num_days:]


def fetch_all_historical_data(tickers: list[str], macro_symbols: list[str],
                               trading_days: list[date]) -> dict:
    """Pre-fetch all historical data in bulk."""
    first_day = trading_days[0]
    last_day = trading_days[-1]

    # Need extra history before first_day for technical analysis
    start_date = first_day - timedelta(days=EXTRA_HISTORY_DAYS + 5)
    end_date = last_day + timedelta(days=1)  # yfinance end is exclusive

    print(f"  Downloading price data: {start_date} to {end_date}")

    # Fetch holdings data
    all_symbols = tickers + macro_symbols
    data = yf.download(all_symbols, start=start_date.isoformat(),
                        end=end_date.isoformat(), progress=False,
                        auto_adjust=True, group_by="ticker")

    # Parse into per-ticker DataFrames
    ticker_dfs = {}
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
            print(f"    Warning: Could not parse data for {sym}: {e}")

    print(f"  Got data for {len(ticker_dfs)}/{len(all_symbols)} symbols")
    return ticker_dfs


def build_prices_for_day(ticker_dfs: dict, tickers: list[str],
                          day: date, prev_day: date | None) -> dict:
    """Build the prices dict for a specific day, matching fetch_current_prices format.

    Returns: {ticker: {price, change, change_pct, prev_close, volume}}
    """
    prices = {}
    for ticker in tickers:
        df = ticker_dfs.get(ticker)
        if df is None or df.empty:
            continue

        day_ts = pd.Timestamp(day)
        if day_ts not in df.index:
            continue

        row = df.loc[day_ts]
        close = float(row["Close"])

        # Get previous day's close for change calculation
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
            # Use the day before in the DataFrame
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


def build_macro_for_day(ticker_dfs: dict, day: date, prev_day: date | None) -> dict:
    """Build macro data dict for a specific day matching fetch_macro_data format.

    Returns: {sp500: {value, change_pct}, vix: {value, change_pct}, ...}
    """
    macro = {}
    day_ts = pd.Timestamp(day)

    # SPY → S&P 500 proxy
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

    # 10Y Treasury Yield (^TNX is in percentage points * 10... or just pct)
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


def build_historical_up_to_day(ticker_dfs: dict, tickers: list[str],
                                day: date) -> dict[str, pd.DataFrame]:
    """Truncate historical data to only include data up to (and including) the given day.

    Returns dict matching fetch_all_historical format: {ticker: DataFrame}.
    """
    result = {}
    day_ts = pd.Timestamp(day)

    for ticker in tickers:
        df = ticker_dfs.get(ticker)
        if df is None or df.empty:
            continue
        truncated = df[df.index <= day_ts].copy()
        if not truncated.empty:
            result[ticker] = truncated

    return result


# ═══════════════════════════════════════════════════════════════════
# PIPELINE PER DAY
# ═══════════════════════════════════════════════════════════════════

async def run_day(
    day_num: int,
    day: date,
    prev_day: date | None,
    config: dict,
    tickers: list[str],
    ticker_dfs: dict,
    fundamentals: dict,
    earnings_data: dict,
    superinvestor_data: dict,
    day_costs: list[float],
) -> dict:
    """Run the full pipeline for one historical day."""

    day_start = time.time()
    day_str = day.strftime("%A %b %d, %Y")

    print()
    print(THICK_SEP)
    print(f"  DAY {day_num}: {day_str}")
    print(THICK_SEP)
    print()

    # ── 1. Build price data for this day ──────────────────────────
    prices = build_prices_for_day(ticker_dfs, tickers, day, prev_day)

    # Print market data
    print(f"{THIN_SEP}")
    print("  MARKET DATA")
    print(f"{THIN_SEP}")
    for t in tickers[:12]:
        p = prices.get(t, {})
        if p.get("price"):
            chg = p.get("change_pct")
            chg_str = f"{chg:+.1f}%" if chg is not None else "N/A"
            print(f"  {t}: ${p['price']:.2f} ({chg_str})")
        else:
            print(f"  {t}: no data")

    # ── 2. Build macro data for this day ──────────────────────────
    macro_data = build_macro_for_day(ticker_dfs, day, prev_day)

    sp = macro_data.get("sp500", {})
    vix = macro_data.get("vix", {})
    tnx = macro_data.get("treasury_10y", {})
    sp_str = f"${sp.get('value', 'N/A')}" if sp.get("value") else "N/A"
    sp_chg = f" ({sp.get('change_pct', 0):+.1f}%)" if sp.get("change_pct") is not None else ""
    print(f"\n  S&P (SPY): {sp_str}{sp_chg} | VIX: {vix.get('value', 'N/A')} | 10Y: {tnx.get('value', 'N/A')}%")

    # ── 3. Build historical data truncated to this day ────────────
    historical = build_historical_up_to_day(ticker_dfs, tickers, day)

    # ── 4. Run technical analysis ─────────────────────────────────
    from src.portfolio_analyst.technical_analyzer import analyze_all as run_technical_analysis
    try:
        technicals = run_technical_analysis(tickers, historical)
    except Exception as e:
        print(f"  Warning: Technical analysis failed: {e}")
        technicals = {}

    # ── 5. Run holdings monitor ───────────────────────────────────
    from src.advisor.memory import (
        seed_holdings,
        seed_macro_theses,
        build_memory_context,
        save_daily_snapshot,
        get_latest_snapshot_before,
    )
    from src.advisor.holdings_monitor import monitor_holdings

    # Seed holdings/theses into temp DB (idempotent)
    seed_holdings(config.get("holdings", []))
    seed_macro_theses(config.get("macro_theses", []))

    # Sync entry_price from config
    from src.advisor.memory import update_holding
    for h in config.get("holdings", []):
        if h.get("entry_price"):
            try:
                update_holding(h["ticker"], entry_price=h["entry_price"])
            except Exception:
                pass

    memory = build_memory_context()

    # Enrich memory holdings with config data
    config_holdings_map = {h["ticker"]: h for h in config.get("holdings", [])}
    for h in memory["holdings"]:
        cfg = config_holdings_map.get(h["ticker"], {})
        if cfg.get("shares"):
            h["shares"] = cfg["shares"]
        if cfg.get("entry_price") and not h.get("entry_price"):
            h["entry_price"] = cfg["entry_price"]

    try:
        holdings_reports = monitor_holdings(
            holdings=memory["holdings"],
            prices=prices,
            fundamentals=fundamentals,
            signals=[],
            news_signals=[],
        )
    except Exception as e:
        print(f"  Warning: Holdings monitor failed: {e}")
        holdings_reports = []

    # ── 6. Delta Engine: snapshot + compute changes ───────────────
    from src.advisor.delta_engine import (
        build_snapshot,
        compute_deltas,
        generate_delta_summary,
        format_delta_for_prompt,
    )

    print(f"\n{THIN_SEP}")
    print("  DELTA ENGINE")
    print(f"{THIN_SEP}")

    try:
        today_snapshot = build_snapshot(
            holdings_reports=holdings_reports,
            fundamentals=fundamentals,
            technicals=technicals,
            macro_data=macro_data,
            conviction_list=memory.get("conviction_list", []),
            moonshot_list=memory.get("moonshot_list", []),
            strategy={},
            earnings_data=earnings_data if isinstance(earnings_data, dict) else {},
            superinvestor_data=superinvestor_data,
        )
        # Sanitize numpy types before JSON serialization
        today_snapshot = _sanitize_for_json(today_snapshot)
        # Save with the historical date (not today's date)
        save_daily_snapshot(day.isoformat(), today_snapshot)
    except Exception as e:
        print(f"  Warning: Snapshot build/save failed: {e}")
        today_snapshot = {}

    delta_report = None
    delta_prompt_section = ""
    try:
        yesterday_snapshot = get_latest_snapshot_before(day.isoformat())
        delta_report = compute_deltas(today_snapshot, yesterday_snapshot)
        # Patch the date to use the historical date
        delta_report.date = day.isoformat()

        # Generate summary (template-based to save cost on delta summary)
        delta_report.summary = generate_delta_summary(delta_report)
        delta_prompt_section = format_delta_for_prompt(delta_report)

        if delta_report.high_significance:
            for item in delta_report.high_significance:
                print(f"  HIGH: {item.narrative}")
        if delta_report.medium_significance:
            for item in delta_report.medium_significance[:5]:
                print(f"  MED:  {item.narrative}")
        if not delta_report.high_significance and not delta_report.medium_significance:
            print("  No significant changes detected")
        print(f"  Total: {delta_report.total_changes} changes "
              f"({len(delta_report.high_significance)} high, "
              f"{len(delta_report.medium_significance)} med, "
              f"{len(delta_report.low_significance)} low)")
    except Exception as e:
        print(f"  Warning: Delta computation failed: {e}")

    # ── 7. Catalyst tracking ──────────────────────────────────────
    catalyst_prompt_section = ""
    try:
        from src.advisor.catalyst_tracker import run_catalyst_tracking, format_catalysts_for_prompt
        catalyst_data = run_catalyst_tracking(tickers)
        catalyst_prompt_section = format_catalysts_for_prompt(catalyst_data.get("catalysts", []))
    except Exception as e:
        print(f"  Warning: Catalyst tracking failed: {e}")

    # ── 7b. Decision Engine ──────────────────────────────────────
    from src.advisor.valuation_engine import compute_target_price
    from src.advisor.conviction_manager import update_conviction_list
    from src.advisor.moonshot_manager import update_moonshot_list
    from src.advisor.strategy_engine import generate_strategy

    print(f"\n{THIN_SEP}")
    print("  DECISION ENGINE")
    print(f"{THIN_SEP}")

    # Step 6a: Compute valuations (pure math, $0)
    valuation_data = {}
    for ticker in tickers:
        try:
            fund = fundamentals.get(ticker, {})
            earn = earnings_data.get("per_ticker", {}).get(ticker) if isinstance(earnings_data, dict) else None
            val_result = compute_target_price(ticker, fund, earn)
            if not val_result.get("insufficient_data"):
                val_result["pe_trailing"] = fund.get("pe_trailing")
                val_result["pe_forward"] = fund.get("pe_forward")
            valuation_data[ticker] = val_result
        except Exception:
            pass

    val_count = sum(1 for v in valuation_data.values() if not v.get("insufficient_data"))
    print(f"  Valuations: {val_count}/{len(tickers)} computed")

    # Step 6b: Update conviction list
    conviction_result = {"current_list": [], "added": [], "removed": [], "upgraded": []}
    try:
        conviction_result = update_conviction_list(
            candidates=[],  # No Alpha Scout in backtest
            superinvestor_data=superinvestor_data,
            earnings_data=earnings_data if isinstance(earnings_data, dict) else {},
            prediction_data=[],
            valuation_data=valuation_data,
            config=config,
        )
        conv_list = conviction_result.get("current_list", [])
        print(f"  Conviction: {len(conv_list)} active, "
              f"+{len(conviction_result.get('added', []))} added, "
              f"-{len(conviction_result.get('removed', []))} removed")
    except Exception as e:
        print(f"  Warning: Conviction update failed: {e}")

    # Step 6c: Update moonshot list
    moonshot_result = {"current_list": [], "added": [], "removed": []}
    try:
        moonshot_result = update_moonshot_list(
            candidates=[],  # No Alpha Scout in backtest
            config=config,
            prediction_data=[],
            earnings_data=earnings_data if isinstance(earnings_data, dict) else {},
            valuation_data=valuation_data,
        )
        moon_list = moonshot_result.get("current_list", [])
        print(f"  Moonshots: {len(moon_list)} active, "
              f"+{len(moonshot_result.get('added', []))} added, "
              f"-{len(moonshot_result.get('removed', []))} removed")
    except Exception as e:
        print(f"  Warning: Moonshot update failed: {e}")

    # Step 6d: Generate strategy (rule-based, $0)
    updated_theses = memory.get("macro_theses", [])
    strategy = {"actions": [], "flags": [], "summary": "", "thesis_exposure": []}
    try:
        strategy = generate_strategy(
            holdings_reports=holdings_reports,
            macro_theses=updated_theses,
            valuation_data=valuation_data,
            config=config,
        )
        actions = strategy.get("actions", [])
        thesis_exp = strategy.get("thesis_exposure", [])
        print(f"  Strategy: {len(actions)} actions, {len(thesis_exp)} thesis exposures")
        for a in actions:
            print(f"    {a.get('action', '').upper()} {a.get('ticker')}: {a.get('reason', '')}")
    except Exception as e:
        print(f"  Warning: Strategy generation failed: {e}")

    # ── 8. Analyst Committee (real LLM calls) ─────────────────────
    from src.advisor.analyst_committee import run_analyst_committee

    print(f"\n{THIN_SEP}")
    print("  ANALYST COMMITTEE")
    print(f"{THIN_SEP}")

    # Build context strings for the committee
    _macro_ctx_parts = []
    for t in memory.get("macro_theses", []):
        _macro_ctx_parts.append(f"- {t.get('title')}: {t.get('status', 'intact')}")
    _macro_ctx_str = "\n".join(_macro_ctx_parts) if _macro_ctx_parts else "No macro theses."

    _holdings_ctx_str = "\n".join(
        f"- {h.get('ticker')}: ${h.get('price', 'N/A')} "
        f"({(h.get('change_pct') or 0):+.1f}% today) "
        f"thesis: {h.get('thesis_status', 'intact')}"
        for h in holdings_reports
    ) if holdings_reports else "No holdings data."

    _conviction_ctx_str = "\n".join(
        f"- {c.get('ticker')}: week {c.get('weeks_on_list', 1)}, "
        f"conviction: {c.get('conviction', 'medium')}, thesis: {c.get('thesis', '')}"
        for c in conviction_result.get("current_list", [])
    ) if conviction_result.get("current_list") else "Conviction list empty."

    _actions_ctx_str = "\n".join(
        f"- {a.get('action', '').upper()} {a.get('ticker')}: "
        f"{a.get('reason', '')} [urgency: {a.get('urgency', 'low')}]"
        for a in strategy.get("actions", [])
    ) if strategy.get("actions") else "No action recommended."

    # Build data context for committee analysts
    _data_context = {
        "fundamentals": fundamentals,
        "holdings_reports": holdings_reports,
        "valuation_data": valuation_data,
        "macro_data": macro_data,
        "strategy": strategy,
    }

    committee_result = {}
    committee_start = time.time()
    try:
        committee_result = await run_analyst_committee(
            tickers=tickers[:12],
            data_context=_data_context,
            delta_summary=delta_prompt_section,
            catalyst_section=catalyst_prompt_section,
            macro_context=_macro_ctx_str,
            holdings_context=_holdings_ctx_str,
            conviction_context=_conviction_ctx_str,
            strategy_context=_actions_ctx_str,
        )
        committee_time = time.time() - committee_start

        # Report analyst statuses
        growth_ok = "error" not in (committee_result.get("growth_report") or {})
        value_ok = "error" not in (committee_result.get("value_report") or {})
        risk_ok = "error" not in (committee_result.get("risk_report") or {})
        brief_ok = bool(committee_result.get("formatted_brief"))

        print(f"  Growth: {'OK' if growth_ok else 'FAIL'} | "
              f"Value: {'OK' if value_ok else 'FAIL'} | "
              f"Risk: {'OK' if risk_ok else 'FAIL'} | "
              f"Editor: {'OK' if brief_ok else 'FAIL'} "
              f"({committee_time:.1f}s)")
    except Exception as e:
        committee_time = time.time() - committee_start
        print(f"  Committee FAILED after {committee_time:.1f}s: {e}")

    # ── 9. Format full v2 output ─────────────────────────────────
    import re
    from src.advisor.formatter import (
        format_conviction_section,
        format_moonshot_section,
        format_strategy_section,
        format_thesis_exposure_section,
    )

    brief_text = committee_result.get("formatted_brief", "")

    # Build full v2 formatted output matching production main.py
    BRIEF_SEP = "\u2501" * 35
    from src.shared.cost_tracker import get_daily_cost as _get_daily_cost
    _today_cost = _get_daily_cost()

    conviction_section = format_conviction_section(conviction_result.get("current_list", []))
    moonshot_section = format_moonshot_section(moonshot_result.get("current_list", []))
    strategy_section = format_strategy_section(strategy)
    thesis_exposure_section = format_thesis_exposure_section(strategy.get("thesis_exposure", []))

    v2_sections = [
        f"ALPHADESK DAILY BRIEF — {day.strftime('%b %d, %Y')}",
        BRIEF_SEP,
        "",
    ]

    if brief_text:
        v2_sections.append(brief_text)
    else:
        v2_sections.append("(No committee brief generated)")

    if catalyst_prompt_section:
        v2_sections.extend(["", BRIEF_SEP, "", catalyst_prompt_section])

    if thesis_exposure_section:
        v2_sections.extend(["", BRIEF_SEP, "", thesis_exposure_section])

    v2_sections.extend(["", BRIEF_SEP, "", conviction_section])
    v2_sections.extend(["", BRIEF_SEP, "", moonshot_section])

    if strategy.get("actions"):
        v2_sections.extend(["", BRIEF_SEP, "", strategy_section])

    v2_sections.extend([
        "",
        BRIEF_SEP,
        f"AlphaDesk v2.0 | ${_today_cost:.2f} today",
    ])

    full_v2_output = "\n".join(v2_sections)

    # Print to terminal (strip HTML tags)
    clean_output = re.sub(r"<[^>]+>", "", full_v2_output)
    print(f"\n{THIN_SEP}")
    print("  DAILY BRIEF (v2)")
    print(f"{THIN_SEP}")
    for line in clean_output.split("\n"):
        print(f"  {line}")

    # ── 10. Cost tracking ─────────────────────────────────────────
    from src.shared.cost_tracker import get_daily_cost
    daily_cost = get_daily_cost()
    prev_cost = day_costs[-1] if day_costs else 0
    day_cost = daily_cost - prev_cost
    day_costs.append(daily_cost)

    print(f"\n{THIN_SEP}")
    print(f"  COST: ${day_cost:.2f} this day | ${daily_cost:.2f} cumulative")
    print(f"  TIME: {time.time() - day_start:.1f}s")
    print(f"{THIN_SEP}")

    # ── 11. Save brief to memory for next day's context ───────────
    try:
        from src.advisor.memory import save_daily_brief
        save_daily_brief(
            macro_summary=brief_text[:500] if brief_text else "No brief.",
            portfolio_actions=strategy.get("actions", []),
            conviction_changes=conviction_result.get("added", []) + conviction_result.get("removed", []),
            moonshot_changes=moonshot_result.get("added", []) + moonshot_result.get("removed", []),
        )
    except Exception:
        pass

    return {
        "day": day.isoformat(),
        "day_str": day_str,
        "prices": {t: prices.get(t, {}).get("price") for t in tickers if prices.get(t, {}).get("price")},
        "delta_high": len(delta_report.high_significance) if delta_report else 0,
        "delta_med": len(delta_report.medium_significance) if delta_report else 0,
        "delta_low": len(delta_report.low_significance) if delta_report else 0,
        "brief_length": len(brief_text),
        "cost": day_cost,
        "time_s": round(time.time() - day_start, 1),
        "committee_ok": bool(brief_text),
        "conviction_count": len(conviction_result.get("current_list", [])),
        "conviction_added": len(conviction_result.get("added", [])),
        "moonshot_count": len(moonshot_result.get("current_list", [])),
        "moonshot_added": len(moonshot_result.get("added", [])),
        "strategy_actions": len(strategy.get("actions", [])),
        "thesis_exposures": len(strategy.get("thesis_exposure", [])),
    }


# ═══════════════════════════════════════════════════════════════════
# SUMMARY TABLE
# ═══════════════════════════════════════════════════════════════════

def print_summary(results: list[dict], tickers: list[str], total_time: float):
    """Print the end-of-week summary table."""
    print()
    print()
    print(THICK_SEP)
    print("  WEEK SUMMARY")
    print(THICK_SEP)
    print()

    # Price performance table
    print("  PRICE PERFORMANCE:")
    header_parts = [f"  {'Ticker':<8}"]
    for r in results:
        day_label = datetime.strptime(r["day"], "%Y-%m-%d").strftime("%a")
        header_parts.append(f"{day_label:>8}")
    header_parts.append(f"{'Week':>8}")
    print("  ".join(header_parts))
    print("  " + "-" * (10 + 10 * (len(results) + 1)))

    for ticker in tickers[:12]:
        row = f"  {ticker:<8}"
        first_price = None
        last_price = None
        for r in results:
            p = r["prices"].get(ticker)
            if p is not None:
                if first_price is None:
                    first_price = p
                last_price = p
                row += f"  ${p:>7.2f}"
            else:
                row += f"  {'N/A':>8}"

        # Week change
        if first_price and last_price:
            week_chg = (last_price - first_price) / first_price * 100
            row += f"  {week_chg:>+7.1f}%"
        else:
            row += f"  {'N/A':>8}"
        print(row)

    # Delta summary
    print()
    print("  DELTA ENGINE SUMMARY:")
    print(f"  {'Day':<18}  {'High':>6}  {'Med':>6}  {'Low':>6}  {'Total':>6}")
    print("  " + "-" * 50)
    total_h, total_m, total_l = 0, 0, 0
    for r in results:
        day_label = datetime.strptime(r["day"], "%Y-%m-%d").strftime("%a %b %d")
        total = r["delta_high"] + r["delta_med"] + r["delta_low"]
        total_h += r["delta_high"]
        total_m += r["delta_med"]
        total_l += r["delta_low"]
        print(f"  {day_label:<18}  {r['delta_high']:>6}  {r['delta_med']:>6}  {r['delta_low']:>6}  {total:>6}")
    print("  " + "-" * 50)
    print(f"  {'TOTAL':<18}  {total_h:>6}  {total_m:>6}  {total_l:>6}  {total_h+total_m+total_l:>6}")

    # Decision engine summary
    print()
    print("  DECISION ENGINE SUMMARY:")
    print(f"  {'Day':<18}  {'Conv':>6}  {'+Add':>6}  {'Moon':>6}  {'+Add':>6}  {'Acts':>6}  {'Thesis':>6}")
    print("  " + "-" * 60)
    for r in results:
        day_label = datetime.strptime(r["day"], "%Y-%m-%d").strftime("%a %b %d")
        print(f"  {day_label:<18}  {r.get('conviction_count', 0):>6}  "
              f"{r.get('conviction_added', 0):>6}  {r.get('moonshot_count', 0):>6}  "
              f"{r.get('moonshot_added', 0):>6}  {r.get('strategy_actions', 0):>6}  "
              f"{r.get('thesis_exposures', 0):>6}")

    # Pipeline stats
    print()
    print("  PIPELINE STATS:")
    total_cost = sum(r["cost"] for r in results)
    briefs_ok = sum(1 for r in results if r["committee_ok"])
    total_day_time = sum(r["time_s"] for r in results)

    print(f"  Days processed:     {len(results)}/{NUM_DAYS}")
    print(f"  Briefs generated:   {briefs_ok}/{len(results)}")
    print(f"  Total cost:         ${total_cost:.2f}")
    print(f"  Avg cost/day:       ${total_cost / max(len(results), 1):.2f}")
    print(f"  Total pipeline time: {total_time:.1f}s")
    print(f"  Avg time/day:       {total_day_time / max(len(results), 1):.1f}s")
    print()
    print(THICK_SEP)


# ═══════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════

async def main():
    """Run the historic backtest."""
    overall_start = time.time()

    print()
    print(THICK_SEP)
    print("  ALPHADESK v2 HISTORIC BACKTEST")
    print(THICK_SEP)
    print()

    # Check API key
    if not os.getenv("GEMINI_API_KEY"):
        print("  ERROR: GEMINI_API_KEY not set. Add it to .env or environment.")
        sys.exit(1)

    # ── Load config ───────────────────────────────────────────────
    print("  Loading config...")
    config = load_config()
    tickers = get_tickers(config)
    macro_symbols = get_macro_symbols()
    print(f"  Tickers: {', '.join(tickers)}")
    print(f"  Macro: {', '.join(macro_symbols)}")

    # ── Determine trading days ────────────────────────────────────
    print(f"\n  Finding last {NUM_DAYS} trading days...")
    trading_days = get_trading_days(NUM_DAYS)
    print(f"  Trading days: {' | '.join(d.strftime('%a %b %d') for d in trading_days)}")

    # ── Pre-fetch all historical data ─────────────────────────────
    print(f"\n  Pre-fetching historical data...")
    fetch_start = time.time()
    ticker_dfs = fetch_all_historical_data(tickers, macro_symbols, trading_days)
    print(f"  Fetched in {time.time() - fetch_start:.1f}s")

    # ── Fetch fundamentals once (current snapshot, acceptable for 1 week) ──
    print("\n  Fetching fundamentals (one-time)...")
    from src.portfolio_analyst.fundamental_analyzer import fetch_all_fundamentals
    try:
        fundamentals = fetch_all_fundamentals(tickers)
        print(f"  Got fundamentals for {len(fundamentals)} tickers")
    except Exception as e:
        print(f"  Warning: Fundamentals fetch failed: {e}")
        fundamentals = {}

    # ── Fetch earnings data once ──────────────────────────────────
    print("  Fetching earnings data (one-time)...")
    earnings_data: dict = {}
    try:
        from src.advisor.earnings_analyzer import run_earnings_analysis
        earnings_data = run_earnings_analysis(tickers)
        print(f"  Got earnings data")
    except Exception as e:
        print(f"  Warning: Earnings fetch failed: {e}")

    # ── Fetch superinvestor data once ─────────────────────────────
    print("  Fetching superinvestor data (one-time)...")
    superinvestor_data: dict = {}
    try:
        from src.advisor.superinvestor_tracker import run_superinvestor_tracking
        raw_si = run_superinvestor_tracking(tickers, config)
        superinvestor_data = raw_si.get("smart_money_summaries", {}) if isinstance(raw_si, dict) else {}
        print(f"  Got superinvestor data for {len(superinvestor_data)} tickers")
    except Exception as e:
        print(f"  Warning: Superinvestor fetch failed: {e}")

    # ── Patch budget check to always allow ────────────────────────
    import src.shared.cost_tracker as cost_mod
    _original_check_budget = cost_mod.check_budget
    cost_mod.check_budget = lambda: (True, 0.0, 50.0)

    # Also patch in modules that import check_budget at module level
    import src.advisor.analyst_committee as committee_mod
    committee_mod.check_budget = lambda: (True, 0.0, 50.0)
    import src.advisor.conviction_manager as conviction_mod
    conviction_mod.check_budget = lambda: (True, 0.0, 50.0)
    import src.advisor.moonshot_manager as moonshot_mod
    moonshot_mod.check_budget = lambda: (True, 0.0, 50.0)

    # ── Run backtest in temp DB ───────────────────────────────────
    print(f"\n  Initializing temp DB...")
    results = []
    day_costs: list[float] = []

    with TempDBContext():
        for i, day in enumerate(trading_days):
            prev_day = trading_days[i - 1] if i > 0 else None
            try:
                result = await run_day(
                    day_num=i + 1,
                    day=day,
                    prev_day=prev_day,
                    config=config,
                    tickers=tickers,
                    ticker_dfs=ticker_dfs,
                    fundamentals=fundamentals,
                    earnings_data=earnings_data,
                    superinvestor_data=superinvestor_data,
                    day_costs=day_costs,
                )
                results.append(result)
            except Exception as e:
                print(f"\n  DAY {i+1} FAILED: {e}")
                import traceback
                traceback.print_exc()
                # Continue to next day
                day_costs.append(day_costs[-1] if day_costs else 0)

    # Restore budget check
    cost_mod.check_budget = _original_check_budget

    # ── Print summary ─────────────────────────────────────────────
    total_time = time.time() - overall_start
    if results:
        print_summary(results, tickers, total_time)
    else:
        print("\n  No results — all days failed.")

    print(f"\n  Backtest complete in {total_time:.1f}s")
    print()


if __name__ == "__main__":
    asyncio.run(main())
