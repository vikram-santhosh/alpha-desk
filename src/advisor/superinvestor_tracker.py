"""Superinvestor and institutional tracking for AlphaDesk Advisor.

Tracks what hedge funds, superinvestors, and insiders are doing:
- Insider buy/sell transactions via yfinance
- Top institutional holders via yfinance
- SEC 13F filings via EDGAR full-text search API
- Combines all data into a smart-money summary per ticker
"""

from datetime import datetime, timedelta
from typing import Any

import requests
import yfinance as yf

from src.advisor.memory import (
    get_superinvestor_activity,
    upsert_superinvestor_position,
)
from src.utils.logger import get_logger

log = get_logger(__name__)

SEC_EDGAR_SEARCH_URL = "https://efts.sec.gov/LATEST/search-index"
SEC_USER_AGENT = "AlphaDesk/1.0 (contact@example.com)"


def fetch_insider_transactions(tickers: list[str]) -> dict[str, list[dict]]:
    """Fetch recent insider transactions for each ticker via yfinance.

    Args:
        tickers: List of ticker symbols.

    Returns:
        Dict mapping ticker -> list of insider transaction dicts.
        Each dict has: name, title, transaction_type, shares, value, date.
    """
    results: dict[str, list[dict]] = {}

    for ticker in tickers:
        try:
            t = yf.Ticker(ticker)
            txns = t.insider_transactions

            if txns is None or (hasattr(txns, "empty") and txns.empty):
                log.debug("No insider transactions for %s", ticker)
                results[ticker] = []
                continue

            records: list[dict] = []
            # insider_transactions returns a DataFrame
            for _, row in txns.iterrows():
                record = {
                    "name": str(row.get("Insider", row.get("insider", ""))),
                    "title": str(row.get("Position", row.get("position", ""))),
                    "transaction_type": str(
                        row.get("Transaction", row.get("transaction", ""))
                    ),
                    "shares": _safe_int(
                        row.get("Shares", row.get("shares"))
                    ),
                    "value": _safe_float(
                        row.get("Value", row.get("value"))
                    ),
                    "date": str(
                        row.get("Start Date", row.get("startDate", ""))
                    ),
                }
                records.append(record)

            results[ticker] = records
            log.info(
                "Fetched %d insider transactions for %s",
                len(records),
                ticker,
            )

        except Exception:
            log.exception("Error fetching insider transactions for %s", ticker)
            results[ticker] = []

    return results


def fetch_institutional_holders(tickers: list[str]) -> dict[str, list[dict]]:
    """Fetch top institutional holders and ownership breakdown for each ticker.

    Args:
        tickers: List of ticker symbols.

    Returns:
        Dict mapping ticker -> holder data dict with keys:
        - top_holders: list of {name, shares, pct_held, value, date}
        - major_holders: dict with ownership breakdown percentages
    """
    results: dict[str, list[dict]] = {}

    for ticker in tickers:
        try:
            t = yf.Ticker(ticker)
            holder_data: dict[str, Any] = {"top_holders": [], "major_holders": {}}

            # Top institutional holders
            inst = t.institutional_holders
            if inst is not None and not inst.empty:
                holders = []
                for _, row in inst.iterrows():
                    holders.append({
                        "name": str(row.get("Holder", "")),
                        "shares": _safe_int(row.get("Shares", row.get("shares"))),
                        "pct_held": _safe_float(
                            row.get("pctHeld", row.get("% Out"))
                        ),
                        "value": _safe_float(row.get("Value", row.get("value"))),
                        "date": str(row.get("Date Reported", "")),
                    })
                holder_data["top_holders"] = holders

            # Major holders breakdown (insider %, institutional %, float %)
            major = t.major_holders
            if major is not None and not major.empty:
                breakdown = {}
                for _, row in major.iterrows():
                    label = str(row.iloc[-1]) if len(row) > 1 else ""
                    value = row.iloc[0] if len(row) > 0 else None
                    if "insider" in label.lower():
                        breakdown["insider_pct"] = _safe_float(value)
                    elif "institution" in label.lower() and "float" not in label.lower():
                        breakdown["institutional_pct"] = _safe_float(value)
                    elif "float" in label.lower():
                        breakdown["float_pct"] = _safe_float(value)
                holder_data["major_holders"] = breakdown

            results[ticker] = holder_data
            log.info(
                "Fetched %d institutional holders for %s",
                len(holder_data.get("top_holders", [])),
                ticker,
            )

        except Exception:
            log.exception(
                "Error fetching institutional holders for %s", ticker
            )
            results[ticker] = {"top_holders": [], "major_holders": {}}

    return results


def fetch_13f_positions(superinvestors_config: list[dict]) -> list[dict]:
    """Search SEC EDGAR for recent 13F-HR filings from tracked superinvestors.

    This is best-effort: 13F-HR XML parsing is complex, so we detect whether
    a recent filing exists and record its date. Full position parsing can be
    added later.

    Args:
        superinvestors_config: List of dicts with 'name' and 'cik' keys.

    Returns:
        List of filing detection dicts with: investor_name, cik, filing_date,
        filing_url, quarter.
    """
    filings_found: list[dict] = []

    # Look back 90 days for recent 13F filings
    start_date = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
    end_date = datetime.now().strftime("%Y-%m-%d")

    headers = {"User-Agent": SEC_USER_AGENT}

    for investor in superinvestors_config:
        name = investor.get("name", "Unknown")
        cik = investor.get("cik", "")

        if not cik:
            log.warning("No CIK for superinvestor %s, skipping", name)
            continue

        try:
            params = {
                "q": f'"13F" AND "{cik}"',
                "dateRange": "custom",
                "startdt": start_date,
                "enddt": end_date,
                "forms": "13F-HR",
                "from": 0,
                "size": 5,
            }

            resp = requests.get(
                SEC_EDGAR_SEARCH_URL,
                params=params,
                headers=headers,
                timeout=15,
            )

            if resp.status_code != 200:
                log.warning(
                    "SEC EDGAR returned %d for %s (CIK: %s)",
                    resp.status_code,
                    name,
                    cik,
                )
                continue

            data = resp.json()
            hits = data.get("hits", {}).get("hits", [])

            if not hits:
                log.debug("No recent 13F filings found for %s", name)
                continue

            for hit in hits:
                source = hit.get("_source", {})
                filing_date = source.get("file_date", "")
                filing_url = source.get("file_url", "")

                # Determine the quarter this filing covers
                quarter = _filing_date_to_quarter(filing_date)

                filing_info = {
                    "investor_name": name,
                    "cik": cik,
                    "filing_date": filing_date,
                    "filing_url": filing_url,
                    "quarter": quarter,
                }
                filings_found.append(filing_info)

                # Record in memory that this investor filed for this quarter
                upsert_superinvestor_position(
                    investor_name=name,
                    ticker="__13F_FILING__",
                    quarter=quarter,
                    action="filed",
                )

            log.info(
                "Found %d 13F filings for %s", len(hits), name
            )

        except requests.RequestException:
            log.exception(
                "Network error fetching 13F for %s (CIK: %s)", name, cik
            )
        except Exception:
            log.exception(
                "Error processing 13F for %s (CIK: %s)", name, cik
            )

    log.info(
        "13F search complete: found %d filings across %d superinvestors",
        len(filings_found),
        len(superinvestors_config),
    )
    return filings_found


def get_smart_money_summary(ticker: str) -> dict[str, Any]:
    """Build a combined smart-money summary for a single ticker.

    Combines insider transactions, institutional holders, and superinvestor
    positions from memory.

    Args:
        ticker: Stock ticker symbol.

    Returns:
        Dict with: insider_net_buying, top_institutional_holders,
        superinvestors_holding, superinvestor_activity.
    """
    summary: dict[str, Any] = {
        "ticker": ticker,
        "insider_net_buying": False,
        "top_institutional_holders": [],
        "superinvestors_holding": [],
        "superinvestor_activity": [],
    }

    # Insider transactions
    try:
        insider_data = fetch_insider_transactions([ticker])
        transactions = insider_data.get(ticker, [])

        net_buy_shares = 0
        for txn in transactions:
            txn_type = (txn.get("transaction_type") or "").lower()
            shares = txn.get("shares") or 0
            if "purchase" in txn_type or "buy" in txn_type:
                net_buy_shares += shares
            elif "sale" in txn_type or "sell" in txn_type:
                net_buy_shares -= shares

        summary["insider_net_buying"] = net_buy_shares > 0
    except Exception:
        log.exception("Error getting insider data for %s", ticker)

    # Institutional holders
    try:
        inst_data = fetch_institutional_holders([ticker])
        holder_info = inst_data.get(ticker, {})
        top_holders = holder_info.get("top_holders", []) if isinstance(holder_info, dict) else []
        # Return top 5 institutional holders
        summary["top_institutional_holders"] = [
            {"name": h.get("name"), "pct_held": h.get("pct_held")}
            for h in top_holders[:5]
        ]
    except Exception:
        log.exception("Error getting institutional holders for %s", ticker)

    # Superinvestor positions from memory
    try:
        positions = get_superinvestor_activity(ticker)
        # Filter out the filing sentinel records
        real_positions = [
            p for p in positions if p.get("ticker") != "__13F_FILING__"
        ]

        holding_names = list({p["investor_name"] for p in real_positions})
        summary["superinvestors_holding"] = holding_names

        # Recent activity (last 2 quarters)
        recent = real_positions[:10]  # already sorted by quarter DESC
        activity = []
        for p in recent:
            activity.append({
                "investor": p["investor_name"],
                "quarter": p["quarter"],
                "action": p.get("action"),
                "shares": p.get("shares"),
                "value_usd": p.get("value_usd"),
            })
        summary["superinvestor_activity"] = activity

    except Exception:
        log.exception(
            "Error getting superinvestor positions for %s", ticker
        )

    return summary


def run_superinvestor_tracking(
    tickers: list[str], config: dict[str, Any]
) -> dict[str, Any]:
    """Main entry point: run all superinvestor/institutional data fetches.

    Args:
        tickers: List of ticker symbols to track.
        config: Advisor config dict (should have 'superinvestors' key).

    Returns:
        Dict with: insider_transactions, institutional_holders,
        filings_13f, smart_money_summaries.
    """
    log.info("Starting superinvestor tracking for %d tickers", len(tickers))

    # Fetch insider transactions for all tickers
    insider_txns = fetch_insider_transactions(tickers)

    # Fetch institutional holders for all tickers
    inst_holders = fetch_institutional_holders(tickers)

    # Search for 13F filings
    superinvestors_list = config.get("superinvestors", [])
    filings = fetch_13f_positions(superinvestors_list)

    # Build per-ticker smart money summaries
    summaries: dict[str, dict] = {}
    for ticker in tickers:
        try:
            summaries[ticker] = get_smart_money_summary(ticker)
        except Exception:
            log.exception(
                "Error building smart money summary for %s", ticker
            )

    result = {
        "insider_transactions": insider_txns,
        "institutional_holders": inst_holders,
        "filings_13f": filings,
        "smart_money_summaries": summaries,
    }

    log.info("Superinvestor tracking complete for %d tickers", len(tickers))
    return result


# ═══════════════════════════════════════════════════════
# v2: FULL-UNIVERSE 13F SCANNING
# ═══════════════════════════════════════════════════════

def _ensure_filings_table():
    """Create superinvestor_filings table if needed."""
    from src.advisor.memory import _get_db
    conn = _get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS superinvestor_filings (
            id INTEGER PRIMARY KEY,
            investor_name TEXT NOT NULL,
            cik TEXT NOT NULL,
            filing_date TEXT NOT NULL,
            positions TEXT NOT NULL,
            new_positions TEXT,
            exited_positions TEXT,
            created_at TEXT NOT NULL,
            UNIQUE(cik, filing_date)
        )
    """)
    conn.commit()
    conn.close()


def get_new_superinvestor_positions(
    cik: str, investor_name: str, fmp_api_key: str | None = None,
) -> list[dict]:
    """Fetch latest 13F and identify new/increased positions via FMP API.

    Returns list of position change dicts.
    """
    import json as _json
    import os
    import time

    fmp_key = fmp_api_key or os.getenv("FMP_API_KEY", "")
    changes: list[dict] = []

    if not fmp_key:
        log.debug("No FMP_API_KEY — skipping full 13F scan for %s", investor_name)
        return changes

    _ensure_filings_table()

    try:
        time.sleep(0.2)  # SEC rate limit

        resp = requests.get(
            f"https://financialmodelingprep.com/api/v3/cik/{cik}",
            params={"apikey": fmp_key},
            timeout=15,
        )
        if resp.status_code != 200:
            log.warning("FMP returned %d for CIK %s", resp.status_code, cik)
            return changes

        positions = resp.json()
        if not isinstance(positions, list):
            return changes

        # Get previous filing from memory
        from src.advisor.memory import _get_db
        conn = _get_db()
        prev = conn.execute("""
            SELECT positions FROM superinvestor_filings
            WHERE cik = ? ORDER BY filing_date DESC LIMIT 1
        """, (cik,)).fetchone()
        conn.close()

        prev_tickers = set()
        if prev:
            try:
                prev_data = _json.loads(prev[0])
                prev_tickers = {p.get("ticker", "").upper() for p in prev_data}
            except (ValueError, TypeError):
                pass

        current_tickers = set()
        filing_date = datetime.now().strftime("%Y-%m-%d")

        for pos in positions[:100]:
            ticker = pos.get("symbol", pos.get("ticker", ""))
            if not ticker:
                continue
            current_tickers.add(ticker.upper())

            if ticker.upper() not in prev_tickers:
                changes.append({
                    "ticker": ticker, "investor": investor_name,
                    "change_type": "new_position", "filing_date": filing_date,
                    "shares": pos.get("shares"), "value_usd": pos.get("value"),
                })

        for prev_t in prev_tickers:
            if prev_t not in current_tickers and prev_t != "__13F_FILING__":
                changes.append({
                    "ticker": prev_t, "investor": investor_name,
                    "change_type": "exited", "filing_date": filing_date,
                })

        # Save filing
        conn = _get_db()
        conn.execute("""
            INSERT OR REPLACE INTO superinvestor_filings
            (investor_name, cik, filing_date, positions, new_positions, exited_positions, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            investor_name, cik, filing_date,
            _json.dumps([{"ticker": p.get("symbol", ""), "shares": p.get("shares"), "value": p.get("value")} for p in positions[:100]]),
            _json.dumps([c["ticker"] for c in changes if c["change_type"] == "new_position"]),
            _json.dumps([c["ticker"] for c in changes if c["change_type"] == "exited"]),
            datetime.now().isoformat(),
        ))
        conn.commit()
        conn.close()

        log.info("%s: %d new, %d exited",
                 investor_name,
                 sum(1 for c in changes if c["change_type"] == "new_position"),
                 sum(1 for c in changes if c["change_type"] == "exited"))

    except requests.RequestException:
        log.exception("Network error fetching 13F for %s", investor_name)
    except Exception:
        log.exception("Error processing full 13F for %s", investor_name)

    return changes


def get_new_positions_as_candidates(config: dict[str, Any]) -> list[dict]:
    """Fetch all superinvestors' new positions as candidate dicts for sourcer."""
    superinvestors = config.get("superinvestors", [])
    candidates: list[dict] = []

    for investor in superinvestors:
        name = investor.get("name", "Unknown")
        cik = investor.get("cik", "")
        if not cik:
            continue
        try:
            changes = get_new_superinvestor_positions(cik, name)
            for change in changes:
                if change["change_type"] == "new_position":
                    candidates.append({
                        "ticker": change["ticker"],
                        "source": f"superinvestor_13f/{name.replace(' ', '_')}",
                        "signal_type": "superinvestor_new_position",
                        "signal_data": {
                            "investor": name,
                            "shares": change.get("shares"),
                            "value_usd": change.get("value_usd"),
                        },
                    })
        except Exception:
            log.exception("Failed to get new positions for %s", name)

    log.info("13F sourcing: %d new position candidates", len(candidates))
    return candidates


# ═══════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════

def _safe_int(value: Any) -> int | None:
    """Safely convert a value to int."""
    if value is None:
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def _safe_float(value: Any) -> float | None:
    """Safely convert a value to float."""
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def _filing_date_to_quarter(filing_date: str) -> str:
    """Convert a filing date to the quarter it likely covers.

    13F filings are due 45 days after quarter end, so a filing in
    Feb 2026 covers Q4 2025, a filing in May covers Q1 2026, etc.

    Args:
        filing_date: Date string in YYYY-MM-DD format.

    Returns:
        Quarter string like '2025Q4'.
    """
    if not filing_date:
        return "unknown"

    try:
        dt = datetime.strptime(filing_date[:10], "%Y-%m-%d")
        # The filing covers the quarter that ended ~45 days before
        report_date = dt - timedelta(days=45)
        year = report_date.year
        month = report_date.month

        if month <= 3:
            return f"{year}Q1"
        elif month <= 6:
            return f"{year}Q2"
        elif month <= 9:
            return f"{year}Q3"
        else:
            return f"{year}Q4"

    except (ValueError, IndexError):
        log.debug("Could not parse filing date: %s", filing_date)
        return "unknown"
