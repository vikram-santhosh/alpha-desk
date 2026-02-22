"""Catalyst Calendar for AlphaDesk Advisor v2.

Tracks upcoming events for all tracked tickers and computes catalyst
proximity scores. Adds "why now" timing intelligence to recommendations.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Any

import yfinance as yf

from src.shared.schemas import CatalystEvent
from src.utils.logger import get_logger

log = get_logger(__name__)

# Year validation — warn if hardcoded dates are stale
if date.today().year > 2026:
    log.error(
        "Catalyst calendar dates are hardcoded for 2026 and now stale (current year: %d). "
        "Update FOMC_DATES, CPI_DATES, JOBS_REPORT_DATES, GDP_DATES in catalyst_tracker.py.",
        date.today().year,
    )

# ═══════════════════════════════════════════════════════
# HARDCODED CALENDAR DATA
# ═══════════════════════════════════════════════════════

FOMC_DATES_2026 = [
    "2026-01-29", "2026-03-19", "2026-05-07", "2026-06-18",
    "2026-07-30", "2026-09-17", "2026-11-05", "2026-12-17",
]

# CPI dates are approximately the 12th of each month
CPI_DATES_2026 = [
    f"2026-{m:02d}-12" for m in range(1, 13)
]

# Jobs report: first Friday of each month (approximate)
JOBS_REPORT_DATES_2026 = [
    "2026-01-02", "2026-02-06", "2026-03-06", "2026-04-03",
    "2026-05-01", "2026-06-05", "2026-07-03", "2026-08-07",
    "2026-09-04", "2026-10-02", "2026-11-06", "2026-12-04",
]

# GDP: quarterly release dates (approximate)
GDP_DATES_2026 = [
    "2026-01-29", "2026-04-29", "2026-07-30", "2026-10-29",
]


# ═══════════════════════════════════════════════════════
# DB TABLE (added to memory.py schema if needed)
# ═══════════════════════════════════════════════════════

def _ensure_catalysts_table():
    """Create catalysts table if it doesn't exist."""
    from src.advisor.memory import _get_db
    conn = _get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS catalysts (
            id INTEGER PRIMARY KEY,
            ticker TEXT NOT NULL,
            event_type TEXT NOT NULL,
            event_date TEXT,
            description TEXT NOT NULL,
            impact_estimate TEXT DEFAULT 'medium',
            source TEXT,
            status TEXT DEFAULT 'upcoming',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(ticker, event_type, event_date)
        )
    """)
    conn.commit()
    conn.close()


def save_catalysts(catalysts: list[CatalystEvent], ticker: str = "$MACRO") -> None:
    """Save catalysts to the database."""
    _ensure_catalysts_table()
    from src.advisor.memory import _get_db
    conn = _get_db()
    now = datetime.now().isoformat()
    for cat in catalysts:
        t = ticker if cat.event_type in ("fomc", "cpi", "jobs_report", "gdp") else ticker
        try:
            conn.execute("""
                INSERT OR REPLACE INTO catalysts
                (ticker, event_type, event_date, description, impact_estimate, source, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 'upcoming', ?, ?)
            """, (t, cat.event_type, cat.date, cat.description,
                  cat.impact_estimate, "catalyst_tracker", now, now))
        except Exception:
            log.debug("Failed to save catalyst: %s %s", t, cat.event_type)
    conn.commit()
    conn.close()


def get_upcoming_catalysts(days_ahead: int = 30) -> list[dict]:
    """Get upcoming catalysts within the specified number of days."""
    _ensure_catalysts_table()
    from src.advisor.memory import _get_db
    conn = _get_db()
    cutoff = (date.today() + timedelta(days=days_ahead)).isoformat()
    rows = conn.execute("""
        SELECT * FROM catalysts
        WHERE event_date >= ? AND event_date <= ? AND status = 'upcoming'
        ORDER BY event_date ASC
    """, (date.today().isoformat(), cutoff)).fetchall()
    cols = [d[0] for d in conn.execute("SELECT * FROM catalysts LIMIT 0").description]
    conn.close()
    return [dict(zip(cols, row)) for row in rows]


# ═══════════════════════════════════════════════════════
# DATA SOURCES
# ═══════════════════════════════════════════════════════

def fetch_earnings_dates(tickers: list[str]) -> list[CatalystEvent]:
    """Fetch next earnings dates for each ticker via yfinance."""
    catalysts = []
    today = date.today()

    for ticker in tickers:
        try:
            t = yf.Ticker(ticker)
            cal = t.calendar
            if cal is None:
                continue

            # yfinance calendar returns a dict or DataFrame
            earnings_date = None
            if isinstance(cal, dict):
                earnings_date = cal.get("Earnings Date")
                if isinstance(earnings_date, list) and earnings_date:
                    earnings_date = str(earnings_date[0])[:10]
                elif earnings_date:
                    earnings_date = str(earnings_date)[:10]
            elif hasattr(cal, "iloc"):
                # DataFrame format
                try:
                    earnings_date = str(cal.iloc[0, 0])[:10]
                except (IndexError, KeyError):
                    pass

            if earnings_date:
                try:
                    ed = datetime.strptime(earnings_date, "%Y-%m-%d").date()
                    days_away = (ed - today).days
                    if days_away >= 0:
                        catalysts.append(CatalystEvent(
                            event_type="earnings",
                            date=earnings_date,
                            description=f"{ticker} earnings report",
                            days_away=days_away,
                            impact_estimate="high",
                        ))
                        # Save with ticker reference
                        save_catalysts([catalysts[-1]], ticker=ticker)
                except ValueError:
                    pass

        except Exception:
            log.debug("Failed to fetch earnings date for %s", ticker)

    log.info("Fetched earnings dates for %d tickers, found %d upcoming", len(tickers), len(catalysts))
    return catalysts


def fetch_fomc_dates() -> list[CatalystEvent]:
    """Return upcoming FOMC meeting dates for 2026."""
    catalysts = []
    today = date.today()

    for date_str in FOMC_DATES_2026:
        try:
            fomc_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            days_away = (fomc_date - today).days
            if days_away >= 0:
                catalysts.append(CatalystEvent(
                    event_type="fomc",
                    date=date_str,
                    description=f"FOMC meeting — interest rate decision",
                    days_away=days_away,
                    impact_estimate="high",
                ))
        except ValueError:
            continue

    save_catalysts(catalysts, ticker="$MACRO")
    return catalysts


def fetch_economic_calendar() -> list[CatalystEvent]:
    """Return upcoming economic events (CPI, jobs, GDP)."""
    catalysts = []
    today = date.today()

    for date_str in CPI_DATES_2026:
        try:
            d = datetime.strptime(date_str, "%Y-%m-%d").date()
            days_away = (d - today).days
            if 0 <= days_away <= 60:
                catalysts.append(CatalystEvent(
                    event_type="cpi",
                    date=date_str,
                    description="CPI inflation report",
                    days_away=days_away,
                    impact_estimate="medium",
                ))
        except ValueError:
            continue

    for date_str in JOBS_REPORT_DATES_2026:
        try:
            d = datetime.strptime(date_str, "%Y-%m-%d").date()
            days_away = (d - today).days
            if 0 <= days_away <= 60:
                catalysts.append(CatalystEvent(
                    event_type="jobs_report",
                    date=date_str,
                    description="Non-farm payrolls / jobs report",
                    days_away=days_away,
                    impact_estimate="medium",
                ))
        except ValueError:
            continue

    for date_str in GDP_DATES_2026:
        try:
            d = datetime.strptime(date_str, "%Y-%m-%d").date()
            days_away = (d - today).days
            if 0 <= days_away <= 90:
                catalysts.append(CatalystEvent(
                    event_type="gdp",
                    date=date_str,
                    description="GDP quarterly release",
                    days_away=days_away,
                    impact_estimate="high",
                ))
        except ValueError:
            continue

    save_catalysts(catalysts, ticker="$MACRO")
    return catalysts


# ═══════════════════════════════════════════════════════
# PROXIMITY SCORING
# ═══════════════════════════════════════════════════════

def compute_catalyst_proximity_score(
    ticker: str, all_catalysts: list[CatalystEvent],
) -> int:
    """Score 0-100 based on proximity to nearest catalyst.

    Scoring:
        - High-impact catalyst within 7 days: 100
        - High-impact catalyst within 14 days: 80
        - High-impact catalyst within 30 days: 60
        - Medium-impact catalyst within 14 days: 50
        - Any catalyst within 30 days: 40
        - Catalyst within 60 days: 25
        - No catalyst within 60 days: 10
        - FOMC within 7 days adds +20 to any ticker's score.
    """
    score = 10  # Default

    # Filter catalysts for this ticker and $MACRO
    relevant = [c for c in all_catalysts if c.days_away >= 0]

    # Check FOMC bonus
    fomc_bonus = 0
    for cat in relevant:
        if cat.event_type == "fomc" and cat.days_away <= 7:
            fomc_bonus = 20
            break

    # Find closest ticker-specific catalyst
    # (earnings events are per-ticker, saved with the ticker)
    for cat in sorted(relevant, key=lambda c: c.days_away):
        # Skip macro events when looking for ticker-specific
        if cat.event_type in ("fomc", "cpi", "jobs_report", "gdp"):
            # These affect all tickers equally
            if cat.impact_estimate == "high" and cat.days_away <= 7:
                score = max(score, 80)
            elif cat.impact_estimate == "high" and cat.days_away <= 14:
                score = max(score, 60)
            elif cat.days_away <= 30:
                score = max(score, 40)
            continue

        # Ticker-specific catalysts (earnings, product launches, etc.)
        # Use word-boundary match to avoid substring false positives (e.g., "A" matching "AMZN")
        desc_words = cat.description.upper().split()
        if ticker.upper() in desc_words:
            if cat.impact_estimate == "high" and cat.days_away <= 7:
                score = max(score, 100)
            elif cat.impact_estimate == "high" and cat.days_away <= 14:
                score = max(score, 80)
            elif cat.impact_estimate == "high" and cat.days_away <= 30:
                score = max(score, 60)
            elif cat.impact_estimate == "medium" and cat.days_away <= 14:
                score = max(score, 50)
            elif cat.days_away <= 30:
                score = max(score, 40)
            elif cat.days_away <= 60:
                score = max(score, 25)

    return min(score + fomc_bonus, 100)


# ═══════════════════════════════════════════════════════
# RUN ALL + FORMAT
# ═══════════════════════════════════════════════════════

def run_catalyst_tracking(tickers: list[str]) -> dict:
    """Run all catalyst data fetches and compute proximity scores.

    Returns dict with: catalysts (list), proximity_scores (dict), formatted (str).
    """
    all_catalysts: list[CatalystEvent] = []

    # Fetch from all sources
    try:
        earnings = fetch_earnings_dates(tickers)
        all_catalysts.extend(earnings)
    except Exception:
        log.exception("Failed to fetch earnings dates")

    try:
        fomc = fetch_fomc_dates()
        all_catalysts.extend(fomc)
    except Exception:
        log.exception("Failed to fetch FOMC dates")

    try:
        econ = fetch_economic_calendar()
        all_catalysts.extend(econ)
    except Exception:
        log.exception("Failed to fetch economic calendar")

    # Compute proximity scores
    scores = {}
    for ticker in tickers:
        scores[ticker] = compute_catalyst_proximity_score(ticker, all_catalysts)

    log.info("Catalyst tracking: %d catalysts, %d tickers scored", len(all_catalysts), len(scores))

    return {
        "catalysts": all_catalysts,
        "proximity_scores": scores,
        "formatted": format_catalysts_section(all_catalysts),
    }


def format_catalysts_section(catalysts: list[CatalystEvent], days_ahead: int = 30) -> str:
    """Format upcoming catalysts as Telegram HTML."""
    upcoming = [c for c in catalysts if 0 <= c.days_away <= days_ahead]
    upcoming.sort(key=lambda c: c.days_away)

    if not upcoming:
        return "<b>Upcoming Catalysts</b>\n<i>No major catalysts in the next 30 days.</i>"

    lines = ["<b>Upcoming Catalysts (30d)</b>", ""]

    # Next 7 days — prominent
    this_week = [c for c in upcoming if c.days_away <= 7]
    if this_week:
        lines.append("<b>This Week:</b>")
        for cat in this_week:
            impact = "HIGH" if cat.impact_estimate == "high" else "med"
            lines.append(f"  {cat.date} [{impact}] {cat.description} ({cat.days_away}d)")
        lines.append("")

    # 8-30 days
    later = [c for c in upcoming if c.days_away > 7]
    if later:
        lines.append("<b>Coming Up:</b>")
        for cat in later[:10]:
            lines.append(f"  {cat.date} {cat.description} ({cat.days_away}d)")

    return "\n".join(lines)


def format_catalysts_for_prompt(catalysts: list[CatalystEvent]) -> str:
    """Format catalysts for inclusion in the Opus synthesis prompt."""
    upcoming = [c for c in catalysts if 0 <= c.days_away <= 30]
    upcoming.sort(key=lambda c: c.days_away)

    if not upcoming:
        return ""

    lines = ["## UPCOMING CATALYSTS"]
    for cat in upcoming[:15]:
        lines.append(f"- {cat.date} [{cat.impact_estimate.upper()}] {cat.description} ({cat.days_away}d away)")

    lines.append("")
    lines.append("INSTRUCTION: If a holding or conviction name has an earnings report, FOMC meeting, or other high-impact catalyst within the next 7 days, FLAG IT prominently in your brief.")
    return "\n".join(lines)
