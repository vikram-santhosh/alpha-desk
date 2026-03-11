"""Persistent memory layer for AlphaDesk Advisor.

SQLite database that stores holdings, snapshots, macro theses, conviction list,
moonshot list, strategy flags, superinvestor positions, earnings calls,
cross-company mentions, prediction market data, and daily brief history.

This is the foundation — every other advisor module reads/writes through here.
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Any

from src.utils.logger import get_logger

log = get_logger(__name__)

DB_PATH = Path(os.environ.get("ALPHADESK_DATA_DIR", "data")) / "advisor_memory.db"


def _get_db() -> sqlite3.Connection:
    """Get or create the advisor memory database with all tables."""
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS holdings (
            id INTEGER PRIMARY KEY,
            ticker TEXT NOT NULL UNIQUE,
            tracking_since TEXT NOT NULL,
            entry_price REAL,
            thesis TEXT NOT NULL,
            thesis_status TEXT DEFAULT 'intact',
            category TEXT DEFAULT 'core',
            notes TEXT,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS holding_snapshots (
            id INTEGER PRIMARY KEY,
            ticker TEXT NOT NULL,
            date TEXT NOT NULL,
            price REAL NOT NULL,
            change_pct REAL,
            cumulative_return_pct REAL,
            thesis_status TEXT,
            daily_narrative TEXT,
            key_event TEXT,
            UNIQUE(ticker, date)
        );

        CREATE TABLE IF NOT EXISTS macro_theses (
            id INTEGER PRIMARY KEY,
            title TEXT NOT NULL UNIQUE,
            description TEXT NOT NULL,
            status TEXT DEFAULT 'intact',
            created_date TEXT NOT NULL,
            last_updated TEXT NOT NULL,
            affected_tickers TEXT,
            evidence_log TEXT
        );

        CREATE TABLE IF NOT EXISTS conviction_list (
            id INTEGER PRIMARY KEY,
            ticker TEXT NOT NULL UNIQUE,
            date_added TEXT NOT NULL,
            weeks_on_list INTEGER DEFAULT 1,
            conviction TEXT DEFAULT 'medium',
            thesis TEXT NOT NULL,
            pros TEXT,
            cons TEXT,
            superinvestor_activity TEXT,
            status TEXT DEFAULT 'active',
            removal_reason TEXT,
            removal_date TEXT,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS moonshot_list (
            id INTEGER PRIMARY KEY,
            ticker TEXT NOT NULL UNIQUE,
            date_added TEXT NOT NULL,
            months_on_list INTEGER DEFAULT 1,
            conviction TEXT DEFAULT 'medium',
            thesis TEXT NOT NULL,
            upside_case TEXT,
            downside_case TEXT,
            key_milestone TEXT,
            max_position_pct REAL DEFAULT 3.0,
            status TEXT DEFAULT 'active',
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS strategy_flags (
            id INTEGER PRIMARY KEY,
            ticker TEXT NOT NULL,
            flag_type TEXT NOT NULL,
            flag_date TEXT NOT NULL,
            description TEXT NOT NULL,
            trigger_condition TEXT,
            resolved INTEGER DEFAULT 0,
            resolved_date TEXT,
            resolved_action TEXT,
            UNIQUE(ticker, flag_type, resolved)
        );

        CREATE TABLE IF NOT EXISTS superinvestor_positions (
            id INTEGER PRIMARY KEY,
            investor_name TEXT NOT NULL,
            ticker TEXT NOT NULL,
            quarter TEXT NOT NULL,
            action TEXT,
            shares INTEGER,
            value_usd REAL,
            pct_of_portfolio REAL,
            UNIQUE(investor_name, ticker, quarter)
        );

        CREATE TABLE IF NOT EXISTS earnings_calls (
            id INTEGER PRIMARY KEY,
            ticker TEXT NOT NULL,
            quarter TEXT NOT NULL,
            call_date TEXT NOT NULL,
            revenue_actual REAL,
            revenue_estimate REAL,
            eps_actual REAL,
            eps_estimate REAL,
            guidance_revenue_low REAL,
            guidance_revenue_high REAL,
            guidance_eps_low REAL,
            guidance_eps_high REAL,
            guidance_sentiment TEXT,
            key_quotes TEXT,
            capex_guidance REAL,
            mentioned_companies TEXT,
            management_tone TEXT,
            transcript_summary TEXT,
            UNIQUE(ticker, quarter)
        );

        CREATE TABLE IF NOT EXISTS cross_mentions (
            id INTEGER PRIMARY KEY,
            source_ticker TEXT NOT NULL,
            mentioned_ticker TEXT NOT NULL,
            quarter TEXT NOT NULL,
            context TEXT NOT NULL,
            sentiment TEXT,
            category TEXT,
            UNIQUE(source_ticker, mentioned_ticker, quarter)
        );

        CREATE TABLE IF NOT EXISTS prediction_markets (
            id INTEGER PRIMARY KEY,
            date TEXT NOT NULL,
            platform TEXT NOT NULL,
            market_title TEXT NOT NULL,
            category TEXT,
            probability REAL NOT NULL,
            prev_probability REAL,
            volume_usd REAL,
            affected_tickers TEXT,
            url TEXT,
            UNIQUE(date, platform, market_title)
        );

        CREATE TABLE IF NOT EXISTS daily_briefs (
            id INTEGER PRIMARY KEY,
            date TEXT NOT NULL UNIQUE,
            macro_summary TEXT,
            portfolio_actions TEXT,
            conviction_changes TEXT,
            moonshot_changes TEXT,
            full_brief_hash TEXT
        );

        CREATE TABLE IF NOT EXISTS daily_snapshots (
            id INTEGER PRIMARY KEY,
            date TEXT NOT NULL UNIQUE,
            snapshot_data TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS run_snapshots (
            run_id TEXT NOT NULL UNIQUE,
            run_type TEXT,
            date TEXT,
            snapshot_data TEXT,
            delta_from_previous TEXT,
            run_cost_usd REAL,
            run_duration_s REAL,
            last_consumed_signal_id INTEGER
        );

        CREATE TABLE IF NOT EXISTS recommendation_outcomes (
            id INTEGER PRIMARY KEY,
            ticker TEXT NOT NULL,
            recommendation_date TEXT NOT NULL,
            action TEXT NOT NULL,
            conviction TEXT NOT NULL,
            entry_price REAL NOT NULL,
            target_price REAL,
            thesis_summary TEXT,
            bear_case_summary TEXT,
            invalidation_conditions TEXT,
            evidence_quality_score REAL,
            composite_score REAL,
            source TEXT,
            category TEXT,
            price_1d REAL, return_1d_pct REAL,
            price_1w REAL, return_1w_pct REAL,
            price_1m REAL, return_1m_pct REAL,
            price_3m REAL, return_3m_pct REAL,
            spy_return_1m_pct REAL,
            alpha_1m_pct REAL,
            thesis_played_out INTEGER,
            invalidation_triggered INTEGER DEFAULT 0,
            invalidation_detail TEXT,
            user_rating INTEGER,
            status TEXT DEFAULT 'open',
            closed_date TEXT,
            closed_reason TEXT,
            updated_at TEXT NOT NULL,
            UNIQUE(ticker, recommendation_date, action)
        );

        CREATE TABLE IF NOT EXISTS thesis_actions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            thesis_id INTEGER,
            action_date TEXT NOT NULL,
            action_type TEXT NOT NULL,
            ticker TEXT NOT NULL,
            outcome_30d TEXT,
            notes TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_snapshots_ticker_date ON holding_snapshots(ticker, date);
        CREATE INDEX IF NOT EXISTS idx_daily_snapshots_date ON daily_snapshots(date);
        CREATE INDEX IF NOT EXISTS idx_run_snapshots_date ON run_snapshots(date);
        CREATE INDEX IF NOT EXISTS idx_run_snapshots_type ON run_snapshots(run_type);
        CREATE INDEX IF NOT EXISTS idx_rec_outcomes_ticker ON recommendation_outcomes(ticker);
        CREATE INDEX IF NOT EXISTS idx_rec_outcomes_status ON recommendation_outcomes(status);
        CREATE INDEX IF NOT EXISTS idx_earnings_ticker ON earnings_calls(ticker);
        CREATE INDEX IF NOT EXISTS idx_cross_mentions_mentioned ON cross_mentions(mentioned_ticker);
        CREATE INDEX IF NOT EXISTS idx_prediction_date ON prediction_markets(date);
        CREATE INDEX IF NOT EXISTS idx_superinvestor_ticker ON superinvestor_positions(ticker);
        CREATE INDEX IF NOT EXISTS idx_strategy_flags_active ON strategy_flags(ticker, resolved);
    """)
    conn.commit()
    return conn


# ═══════════════════════════════════════════════════════
# HOLDINGS
# ═══════════════════════════════════════════════════════

def seed_holdings(holdings_config: list[dict[str, Any]]) -> None:
    """Seed holdings from config. Only inserts new tickers, doesn't overwrite existing."""
    conn = _get_db()
    now = datetime.now().isoformat()
    today = date.today().isoformat()
    for h in holdings_config:
        try:
            conn.execute("""
                INSERT OR IGNORE INTO holdings (ticker, tracking_since, thesis, thesis_status, category, updated_at)
                VALUES (?, ?, ?, 'intact', ?, ?)
            """, (h["ticker"], today, h.get("thesis", ""), h.get("category", "core"), now))
        except Exception:
            log.exception("Failed to seed holding %s", h.get("ticker"))
    conn.commit()
    conn.close()
    log.info("Seeded %d holdings", len(holdings_config))


def get_all_holdings() -> list[dict[str, Any]]:
    """Get all tracked holdings."""
    conn = _get_db()
    rows = conn.execute("SELECT * FROM holdings ORDER BY category, ticker").fetchall()
    cols = [d[0] for d in conn.execute("SELECT * FROM holdings LIMIT 0").description]
    conn.close()
    return [dict(zip(cols, row)) for row in rows]


_HOLDING_FIELDS = frozenset({
    "tracking_since", "entry_price", "thesis", "thesis_status",
    "category", "notes", "updated_at",
})


def update_holding(ticker: str, **kwargs) -> None:
    """Update a holding's fields. Only whitelisted field names are accepted."""
    # Validate field names to prevent SQL injection
    invalid = set(kwargs.keys()) - _HOLDING_FIELDS - {"updated_at"}
    if invalid:
        raise ValueError(f"Invalid holding fields: {invalid}. Allowed: {_HOLDING_FIELDS}")
    conn = _get_db()
    kwargs["updated_at"] = datetime.now().isoformat()
    sets = ", ".join(f"{k} = ?" for k in kwargs)
    vals = list(kwargs.values()) + [ticker]
    conn.execute(f"UPDATE holdings SET {sets} WHERE ticker = ?", vals)
    conn.commit()
    conn.close()


def record_snapshot(ticker: str, price: float, change_pct: float | None,
                    cumulative_return_pct: float | None, thesis_status: str | None,
                    daily_narrative: str | None, key_event: str | None) -> None:
    """Record a daily snapshot for a holding."""
    conn = _get_db()
    today = date.today().isoformat()
    conn.execute("""
        INSERT OR REPLACE INTO holding_snapshots
        (ticker, date, price, change_pct, cumulative_return_pct, thesis_status, daily_narrative, key_event)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (ticker, today, price, change_pct, cumulative_return_pct, thesis_status, daily_narrative, key_event))
    conn.commit()
    conn.close()


def get_recent_snapshots(ticker: str, days: int = 7) -> list[dict[str, Any]]:
    """Get recent snapshots for a holding."""
    conn = _get_db()
    rows = conn.execute("""
        SELECT * FROM holding_snapshots WHERE ticker = ?
        ORDER BY date DESC LIMIT ?
    """, (ticker, days)).fetchall()
    cols = [d[0] for d in conn.execute("SELECT * FROM holding_snapshots LIMIT 0").description]
    conn.close()
    return [dict(zip(cols, row)) for row in rows]


# ═══════════════════════════════════════════════════════
# MACRO THESES
# ═══════════════════════════════════════════════════════

def seed_macro_theses(theses_config: list[dict[str, Any]]) -> None:
    """Seed macro theses from config. Only inserts new titles."""
    conn = _get_db()
    now = datetime.now().isoformat()
    today = date.today().isoformat()
    for t in theses_config:
        try:
            conn.execute("""
                INSERT OR IGNORE INTO macro_theses
                (title, description, status, created_date, last_updated, affected_tickers, evidence_log)
                VALUES (?, ?, 'intact', ?, ?, ?, '[]')
            """, (t["title"], t.get("description", ""),
                  today, now, json.dumps(t.get("affected_tickers", []))))
        except Exception:
            log.exception("Failed to seed macro thesis: %s", t.get("title"))
    conn.commit()
    conn.close()


def get_all_macro_theses() -> list[dict[str, Any]]:
    """Get all macro theses."""
    conn = _get_db()
    rows = conn.execute("SELECT * FROM macro_theses ORDER BY id").fetchall()
    cols = [d[0] for d in conn.execute("SELECT * FROM macro_theses LIMIT 0").description]
    conn.close()
    results = []
    for row in rows:
        d = dict(zip(cols, row))
        d["affected_tickers"] = json.loads(d["affected_tickers"] or "[]")
        d["evidence_log"] = json.loads(d["evidence_log"] or "[]")
        results.append(d)
    return results


def update_macro_thesis(title: str, status: str, evidence: str | None = None) -> None:
    """Update a macro thesis status and optionally add evidence."""
    conn = _get_db()
    now = datetime.now().isoformat()
    conn.execute(
        "UPDATE macro_theses SET status = ?, last_updated = ? WHERE title = ?",
        (status, now, title),
    )
    if evidence:
        row = conn.execute(
            "SELECT evidence_log FROM macro_theses WHERE title = ?", (title,)
        ).fetchone()
        if row:
            log_entries = json.loads(row[0] or "[]")
            log_entries.append({"date": date.today().isoformat(), "evidence": evidence})
            # Keep last 30 entries
            log_entries = log_entries[-30:]
            conn.execute(
                "UPDATE macro_theses SET evidence_log = ? WHERE title = ?",
                (json.dumps(log_entries), title),
            )
    conn.commit()
    conn.close()


# ═══════════════════════════════════════════════════════
# CONVICTION LIST
# ═══════════════════════════════════════════════════════

def get_conviction_list(active_only: bool = True) -> list[dict[str, Any]]:
    """Get conviction list entries."""
    conn = _get_db()
    query = "SELECT * FROM conviction_list"
    if active_only:
        query += " WHERE status = 'active'"
    query += " ORDER BY conviction DESC, weeks_on_list DESC"
    rows = conn.execute(query).fetchall()
    cols = [d[0] for d in conn.execute("SELECT * FROM conviction_list LIMIT 0").description]
    conn.close()
    results = []
    for row in rows:
        d = dict(zip(cols, row))
        d["pros"] = json.loads(d["pros"] or "[]")
        d["cons"] = json.loads(d["cons"] or "[]")
        results.append(d)
    return results


def upsert_conviction(ticker: str, conviction: str, thesis: str,
                      pros: list[str] | None = None, cons: list[str] | None = None,
                      superinvestor_activity: str | None = None,
                      source: str | None = None) -> None:
    """Add or update a conviction list entry."""
    conn = _get_db()
    now = datetime.now().isoformat()
    today = date.today().isoformat()

    # Gracefully add source column if it doesn't exist yet
    try:
        conn.execute("SELECT source FROM conviction_list LIMIT 0")
    except sqlite3.OperationalError:
        conn.execute("ALTER TABLE conviction_list ADD COLUMN source TEXT")
        conn.commit()

    existing = conn.execute("SELECT id FROM conviction_list WHERE ticker = ?", (ticker,)).fetchone()
    if existing:
        conn.execute("""
            UPDATE conviction_list SET conviction = ?, thesis = ?, pros = ?, cons = ?,
            superinvestor_activity = ?, source = ?, status = 'active', removal_reason = NULL,
            removal_date = NULL, updated_at = ? WHERE ticker = ?
        """, (conviction, thesis, json.dumps(pros or []), json.dumps(cons or []),
              superinvestor_activity, source, now, ticker))
    else:
        conn.execute("""
            INSERT INTO conviction_list
            (ticker, date_added, weeks_on_list, conviction, thesis, pros, cons,
             superinvestor_activity, source, status, updated_at)
            VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?, 'active', ?)
        """, (ticker, today, conviction, thesis, json.dumps(pros or []),
              json.dumps(cons or []), superinvestor_activity, source, now))
    conn.commit()
    conn.close()


def remove_conviction(ticker: str, reason: str) -> None:
    """Remove a ticker from the conviction list with a reason."""
    conn = _get_db()
    now = datetime.now().isoformat()
    today = date.today().isoformat()
    conn.execute("""
        UPDATE conviction_list SET status = 'removed', removal_reason = ?,
        removal_date = ?, updated_at = ? WHERE ticker = ?
    """, (reason, today, now, ticker))
    conn.commit()
    conn.close()


def increment_conviction_weeks() -> None:
    """Increment weeks_on_list for all active conviction entries. Call once per week."""
    conn = _get_db()
    conn.execute("UPDATE conviction_list SET weeks_on_list = weeks_on_list + 1 WHERE status = 'active'")
    conn.commit()
    conn.close()


# ═══════════════════════════════════════════════════════
# MOONSHOT LIST
# ═══════════════════════════════════════════════════════

def get_moonshot_list(active_only: bool = True) -> list[dict[str, Any]]:
    """Get moonshot list entries."""
    conn = _get_db()
    query = "SELECT * FROM moonshot_list"
    if active_only:
        query += " WHERE status = 'active'"
    query += " ORDER BY conviction DESC"
    rows = conn.execute(query).fetchall()
    cols = [d[0] for d in conn.execute("SELECT * FROM moonshot_list LIMIT 0").description]
    conn.close()
    return [dict(zip(cols, row)) for row in rows]


def upsert_moonshot(ticker: str, conviction: str, thesis: str,
                    upside_case: str | None = None, downside_case: str | None = None,
                    key_milestone: str | None = None, max_position_pct: float = 3.0,
                    source: str | None = None) -> None:
    """Add or update a moonshot entry."""
    conn = _get_db()
    now = datetime.now().isoformat()
    today = date.today().isoformat()

    # Gracefully add source column if it doesn't exist yet
    try:
        conn.execute("SELECT source FROM moonshot_list LIMIT 0")
    except sqlite3.OperationalError:
        conn.execute("ALTER TABLE moonshot_list ADD COLUMN source TEXT")
        conn.commit()

    existing = conn.execute("SELECT id FROM moonshot_list WHERE ticker = ?", (ticker,)).fetchone()
    if existing:
        conn.execute("""
            UPDATE moonshot_list SET conviction = ?, thesis = ?, upside_case = ?,
            downside_case = ?, key_milestone = ?, max_position_pct = ?, source = ?, updated_at = ?
            WHERE ticker = ?
        """, (conviction, thesis, upside_case, downside_case, key_milestone, max_position_pct, source, now, ticker))
    else:
        conn.execute("""
            INSERT INTO moonshot_list
            (ticker, date_added, conviction, thesis, upside_case, downside_case,
             key_milestone, max_position_pct, source, status, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?)
        """, (ticker, today, conviction, thesis, upside_case, downside_case,
              key_milestone, max_position_pct, source, now))
    conn.commit()
    conn.close()


def remove_moonshot(ticker: str, reason: str = "") -> None:
    """Remove a moonshot from the active list."""
    conn = _get_db()
    now = datetime.now().isoformat()
    conn.execute(
        "UPDATE moonshot_list SET status = 'removed', updated_at = ? WHERE ticker = ? AND status = 'active'",
        (now, ticker),
    )
    conn.commit()
    conn.close()
    log.info("Removed moonshot %s: %s", ticker, reason)


# ═══════════════════════════════════════════════════════
# STRATEGY FLAGS
# ═══════════════════════════════════════════════════════

def get_active_flags(ticker: str | None = None) -> list[dict[str, Any]]:
    """Get active (unresolved) strategy flags."""
    conn = _get_db()
    query = "SELECT * FROM strategy_flags WHERE resolved = 0"
    params: list[Any] = []
    if ticker:
        query += " AND ticker = ?"
        params.append(ticker)
    query += " ORDER BY flag_date DESC"
    rows = conn.execute(query, params).fetchall()
    cols = [d[0] for d in conn.execute("SELECT * FROM strategy_flags LIMIT 0").description]
    conn.close()
    return [dict(zip(cols, row)) for row in rows]


def add_flag(ticker: str, flag_type: str, description: str,
             trigger_condition: str | None = None) -> None:
    """Add a strategy flag. Silently ignores if duplicate active flag exists."""
    conn = _get_db()
    today = date.today().isoformat()
    try:
        conn.execute("""
            INSERT OR IGNORE INTO strategy_flags (ticker, flag_type, flag_date, description, trigger_condition)
            VALUES (?, ?, ?, ?, ?)
        """, (ticker, flag_type, today, description, trigger_condition))
        conn.commit()
    except Exception:
        log.exception("Failed to add flag for %s", ticker)
    conn.close()


def resolve_flag(ticker: str, flag_type: str, action: str) -> None:
    """Resolve a strategy flag."""
    conn = _get_db()
    today = date.today().isoformat()
    conn.execute("""
        UPDATE strategy_flags SET resolved = 1, resolved_date = ?, resolved_action = ?
        WHERE ticker = ? AND flag_type = ? AND resolved = 0
    """, (today, action, ticker, flag_type))
    conn.commit()
    conn.close()


# ═══════════════════════════════════════════════════════
# SUPERINVESTOR POSITIONS
# ═══════════════════════════════════════════════════════

def upsert_superinvestor_position(investor_name: str, ticker: str, quarter: str,
                                  action: str | None = None, shares: int | None = None,
                                  value_usd: float | None = None,
                                  pct_of_portfolio: float | None = None) -> None:
    """Record a superinvestor position."""
    conn = _get_db()
    conn.execute("""
        INSERT OR REPLACE INTO superinvestor_positions
        (investor_name, ticker, quarter, action, shares, value_usd, pct_of_portfolio)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (investor_name, ticker, quarter, action, shares, value_usd, pct_of_portfolio))
    conn.commit()
    conn.close()


def get_superinvestor_activity(ticker: str) -> list[dict[str, Any]]:
    """Get all superinvestor activity for a ticker."""
    conn = _get_db()
    rows = conn.execute("""
        SELECT * FROM superinvestor_positions WHERE ticker = ?
        ORDER BY quarter DESC, investor_name
    """, (ticker,)).fetchall()
    cols = [d[0] for d in conn.execute("SELECT * FROM superinvestor_positions LIMIT 0").description]
    conn.close()
    return [dict(zip(cols, row)) for row in rows]


def get_all_superinvestor_positions(quarter: str | None = None) -> list[dict[str, Any]]:
    """Get all superinvestor positions, optionally filtered by quarter."""
    conn = _get_db()
    if quarter:
        rows = conn.execute(
            "SELECT * FROM superinvestor_positions WHERE quarter = ? ORDER BY investor_name, ticker",
            (quarter,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM superinvestor_positions ORDER BY quarter DESC, investor_name, ticker"
        ).fetchall()
    cols = [d[0] for d in conn.execute("SELECT * FROM superinvestor_positions LIMIT 0").description]
    conn.close()
    return [dict(zip(cols, row)) for row in rows]


# ═══════════════════════════════════════════════════════
# EARNINGS CALLS
# ═══════════════════════════════════════════════════════

def upsert_earnings_call(data: dict[str, Any]) -> None:
    """Record earnings call data."""
    conn = _get_db()
    conn.execute("""
        INSERT OR REPLACE INTO earnings_calls
        (ticker, quarter, call_date, revenue_actual, revenue_estimate, eps_actual, eps_estimate,
         guidance_revenue_low, guidance_revenue_high, guidance_eps_low, guidance_eps_high,
         guidance_sentiment, key_quotes, capex_guidance, mentioned_companies,
         management_tone, transcript_summary)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        data["ticker"], data["quarter"], data["call_date"],
        data.get("revenue_actual"), data.get("revenue_estimate"),
        data.get("eps_actual"), data.get("eps_estimate"),
        data.get("guidance_revenue_low"), data.get("guidance_revenue_high"),
        data.get("guidance_eps_low"), data.get("guidance_eps_high"),
        data.get("guidance_sentiment"),
        json.dumps(data.get("key_quotes", [])),
        data.get("capex_guidance"),
        json.dumps(data.get("mentioned_companies", [])),
        data.get("management_tone"), data.get("transcript_summary"),
    ))
    conn.commit()
    conn.close()


def get_earnings_history(ticker: str, quarters: int = 4) -> list[dict[str, Any]]:
    """Get earnings call history for a ticker."""
    conn = _get_db()
    rows = conn.execute("""
        SELECT * FROM earnings_calls WHERE ticker = ?
        ORDER BY quarter DESC LIMIT ?
    """, (ticker, quarters)).fetchall()
    cols = [d[0] for d in conn.execute("SELECT * FROM earnings_calls LIMIT 0").description]
    conn.close()
    results = []
    for row in rows:
        d = dict(zip(cols, row))
        d["key_quotes"] = json.loads(d["key_quotes"] or "[]")
        d["mentioned_companies"] = json.loads(d["mentioned_companies"] or "[]")
        results.append(d)
    return results


# ═══════════════════════════════════════════════════════
# CROSS-COMPANY MENTIONS
# ═══════════════════════════════════════════════════════

def upsert_cross_mention(source_ticker: str, mentioned_ticker: str, quarter: str,
                         context: str, sentiment: str | None = None,
                         category: str | None = None) -> None:
    """Record a cross-company mention from an earnings call."""
    conn = _get_db()
    conn.execute("""
        INSERT OR REPLACE INTO cross_mentions
        (source_ticker, mentioned_ticker, quarter, context, sentiment, category)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (source_ticker, mentioned_ticker, quarter, context, sentiment, category))
    conn.commit()
    conn.close()


def get_cross_mentions_for(ticker: str) -> list[dict[str, Any]]:
    """Get all cross-mentions where this ticker was mentioned by others."""
    conn = _get_db()
    rows = conn.execute("""
        SELECT * FROM cross_mentions WHERE mentioned_ticker = ?
        ORDER BY quarter DESC
    """, (ticker,)).fetchall()
    cols = [d[0] for d in conn.execute("SELECT * FROM cross_mentions LIMIT 0").description]
    conn.close()
    return [dict(zip(cols, row)) for row in rows]


# ═══════════════════════════════════════════════════════
# PREDICTION MARKETS
# ═══════════════════════════════════════════════════════

def record_prediction_market(platform: str, market_title: str, probability: float,
                             category: str | None = None, volume_usd: float | None = None,
                             affected_tickers: list[str] | None = None,
                             url: str | None = None) -> None:
    """Record prediction market data point."""
    conn = _get_db()
    today = date.today().isoformat()
    # Get yesterday's probability for delta tracking
    prev = conn.execute("""
        SELECT probability FROM prediction_markets
        WHERE platform = ? AND market_title = ? AND date < ?
        ORDER BY date DESC LIMIT 1
    """, (platform, market_title, today)).fetchone()
    prev_prob = prev[0] if prev else None

    conn.execute("""
        INSERT OR REPLACE INTO prediction_markets
        (date, platform, market_title, category, probability, prev_probability,
         volume_usd, affected_tickers, url)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (today, platform, market_title, category, probability, prev_prob,
          volume_usd, json.dumps(affected_tickers or []), url))
    conn.commit()
    conn.close()


def get_prediction_markets(date_str: str | None = None) -> list[dict[str, Any]]:
    """Get prediction market data for a date (defaults to today)."""
    conn = _get_db()
    d = date_str or date.today().isoformat()
    rows = conn.execute("""
        SELECT * FROM prediction_markets WHERE date = ?
        ORDER BY category, market_title
    """, (d,)).fetchall()
    cols = [d_col[0] for d_col in conn.execute("SELECT * FROM prediction_markets LIMIT 0").description]
    conn.close()
    results = []
    for row in rows:
        entry = dict(zip(cols, row))
        entry["affected_tickers"] = json.loads(entry["affected_tickers"] or "[]")
        results.append(entry)
    return results


def get_prediction_market_deltas(min_delta: float = 0.05) -> list[dict[str, Any]]:
    """Get prediction markets with significant probability changes."""
    conn = _get_db()
    today = date.today().isoformat()
    rows = conn.execute("""
        SELECT * FROM prediction_markets
        WHERE date = ? AND prev_probability IS NOT NULL
        AND ABS(probability - prev_probability) >= ?
        ORDER BY ABS(probability - prev_probability) DESC
    """, (today, min_delta)).fetchall()
    cols = [d[0] for d in conn.execute("SELECT * FROM prediction_markets LIMIT 0").description]
    conn.close()
    results = []
    for row in rows:
        entry = dict(zip(cols, row))
        entry["affected_tickers"] = json.loads(entry["affected_tickers"] or "[]")
        entry["delta"] = entry["probability"] - (entry["prev_probability"] or 0)
        results.append(entry)
    return results


# ═══════════════════════════════════════════════════════
# DAILY BRIEFS
# ═══════════════════════════════════════════════════════

def save_daily_brief(macro_summary: str | None = None,
                     portfolio_actions: list[dict] | None = None,
                     conviction_changes: list[dict] | None = None,
                     moonshot_changes: list[dict] | None = None) -> None:
    """Save today's brief summary for tomorrow's context."""
    conn = _get_db()
    today = date.today().isoformat()
    conn.execute("""
        INSERT OR REPLACE INTO daily_briefs
        (date, macro_summary, portfolio_actions, conviction_changes, moonshot_changes)
        VALUES (?, ?, ?, ?, ?)
    """, (today, macro_summary,
          json.dumps(portfolio_actions or []),
          json.dumps(conviction_changes or []),
          json.dumps(moonshot_changes or [])))
    conn.commit()
    conn.close()


def get_yesterday_brief() -> dict[str, Any] | None:
    """Get yesterday's brief summary."""
    conn = _get_db()
    today = date.today().isoformat()
    row = conn.execute("""
        SELECT * FROM daily_briefs WHERE date < ? ORDER BY date DESC LIMIT 1
    """, (today,)).fetchone()
    if not row:
        conn.close()
        return None
    cols = [d[0] for d in conn.execute("SELECT * FROM daily_briefs LIMIT 0").description]
    conn.close()
    d = dict(zip(cols, row))
    d["portfolio_actions"] = json.loads(d["portfolio_actions"] or "[]")
    d["conviction_changes"] = json.loads(d["conviction_changes"] or "[]")
    d["moonshot_changes"] = json.loads(d["moonshot_changes"] or "[]")
    return d


# ═══════════════════════════════════════════════════════
# AGGREGATE CONTEXT FOR OPUS PROMPT
# ═══════════════════════════════════════════════════════

def build_memory_context() -> dict[str, Any]:
    """Build the complete memory context for the Opus synthesis prompt.

    Returns a dict with all memory state needed for the daily brief.
    """
    return {
        "holdings": get_all_holdings(),
        "macro_theses": get_all_macro_theses(),
        "conviction_list": get_conviction_list(active_only=True),
        "moonshot_list": get_moonshot_list(active_only=True),
        "active_flags": get_active_flags(),
        "yesterday_brief": get_yesterday_brief(),
    }


# ═══════════════════════════════════════════════════════
# SNAPSHOTS (Delta Engine & Multi-Run)
# ═══════════════════════════════════════════════════════

def save_daily_snapshot(date_str: str, snapshot_data: dict) -> None:
    """Insert or replace a daily snapshot for delta engine comparison."""
    conn = _get_db()
    conn.execute("""
        INSERT OR REPLACE INTO daily_snapshots (date, snapshot_data, created_at)
        VALUES (?, ?, ?)
    """, (date_str, json.dumps(snapshot_data), datetime.now().isoformat()))
    conn.commit()
    conn.close()
    log.info("Saved daily snapshot for %s", date_str)


def save_run_snapshot(run_id: str, run_type: str, date_str: str, snapshot_data: dict,
                      delta: dict | None = None, run_cost: float = 0.0,
                      run_duration: float = 0.0, last_signal_id: int = 0,
                      mirror_to_daily: bool = True) -> None:
    """Save a per-run snapshot and optionally mirror it to daily_snapshots."""
    conn = _get_db()
    conn.execute("""
        INSERT OR REPLACE INTO run_snapshots
        (run_id, run_type, date, snapshot_data, delta_from_previous, run_cost_usd, run_duration_s, last_consumed_signal_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (run_id, run_type, date_str, json.dumps(snapshot_data),
          json.dumps(delta) if delta else None, run_cost, run_duration, last_signal_id))
    conn.commit()
    conn.close()

    if mirror_to_daily and run_type == "morning_full":
        save_daily_snapshot(date_str, snapshot_data)

    log.info("Saved run snapshot for %s (%s)", run_id, run_type)


def get_run_snapshot(run_id: str) -> dict[str, Any] | None:
    """Fetch a run snapshot by its run identifier."""
    conn = _get_db()
    row = conn.execute("""
        SELECT * FROM run_snapshots WHERE run_id = ?
    """, (run_id,)).fetchone()
    if not row:
        conn.close()
        return None
    cols = [d[0] for d in conn.execute("SELECT * FROM run_snapshots LIMIT 0").description]
    conn.close()

    return _decode_run_snapshot(dict(zip(cols, row)))


def get_latest_run_snapshot(
    run_type: str | None = None,
    date_str: str | None = None,
) -> dict[str, Any] | None:
    """Get the most recent run snapshot, optionally filtered by type/date."""
    conn = _get_db()
    query = "SELECT * FROM run_snapshots WHERE 1=1"
    params: list[Any] = []

    if run_type:
        query += " AND run_type = ?"
        params.append(run_type)
    if date_str:
        query += " AND date = ?"
        params.append(date_str)

    query += " ORDER BY run_id DESC LIMIT 1"
    row = conn.execute(query, params).fetchone()
    if not row:
        conn.close()
        return None
    cols = [d[0] for d in conn.execute("SELECT * FROM run_snapshots LIMIT 0").description]
    conn.close()

    return _decode_run_snapshot(dict(zip(cols, row)))


def list_run_snapshots(limit: int = 10, run_type: str | None = None) -> list[dict[str, Any]]:
    """List recent run snapshots for operational status and Telegram /runs."""
    conn = _get_db()
    query = "SELECT * FROM run_snapshots"
    params: list[Any] = []
    if run_type:
        query += " WHERE run_type = ?"
        params.append(run_type)
    query += " ORDER BY run_id DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(query, params).fetchall()
    cols = [d[0] for d in conn.execute("SELECT * FROM run_snapshots LIMIT 0").description]
    conn.close()
    return [_decode_run_snapshot(dict(zip(cols, row))) for row in rows]


def _decode_run_snapshot(row: dict[str, Any]) -> dict[str, Any]:
    """Decode JSON payload columns from the run snapshot table."""
    row["snapshot_data"] = json.loads(row["snapshot_data"] or "{}")
    row["delta_from_previous"] = (
        json.loads(row["delta_from_previous"] or "{}")
        if row.get("delta_from_previous")
        else None
    )
    return row


def get_latest_snapshot_before(date_str: str) -> dict | None:
    """Get the most recent daily snapshot before the given date."""
    conn = _get_db()
    row = conn.execute("""
        SELECT snapshot_data FROM daily_snapshots
        WHERE date < ? ORDER BY date DESC LIMIT 1
    """, (date_str,)).fetchone()
    conn.close()
    if not row:
        return None
    try:
        return json.loads(row[0])
    except (json.JSONDecodeError, TypeError):
        log.exception("Failed to parse snapshot data")
        return None


def get_snapshot_for_date(date_str: str) -> dict | None:
    """Get the daily snapshot for an exact date."""
    conn = _get_db()
    row = conn.execute("""
        SELECT snapshot_data FROM daily_snapshots WHERE date = ?
    """, (date_str,)).fetchone()
    conn.close()
    if not row:
        return None
    try:
        return json.loads(row[0])
    except (json.JSONDecodeError, TypeError):
        log.exception("Failed to parse snapshot data for %s", date_str)
        return None


# ═══════════════════════════════════════════════════════
# RECOMMENDATION OUTCOMES (Outcome Tracking)
# ═══════════════════════════════════════════════════════

def record_recommendation(rec) -> None:
    """Record a recommendation for outcome tracking.

    Args:
        rec: A Recommendation dataclass or dict with required fields.
    """
    conn = _get_db()
    now = datetime.now().isoformat()

    # Handle both Recommendation objects and dicts
    if hasattr(rec, "to_dict"):
        d = rec.to_dict()
    else:
        d = rec

    ticker = d.get("ticker", "")
    rec_date = d.get("recommendation_date", date.today().isoformat())
    action = d.get("action", "WATCH")
    conviction = d.get("conviction_level", d.get("conviction", "medium"))
    entry_price = d.get("valuation", {}).get("current_price", 0.0)
    target_price = d.get("valuation", {}).get("target_price")
    thesis_summary = d.get("thesis", {}).get("core_argument", "") if isinstance(d.get("thesis"), dict) else str(d.get("thesis", ""))
    bear_case = d.get("bear_case", {}).get("primary_risk", "") if isinstance(d.get("bear_case"), dict) else ""
    invalidation = json.dumps(d.get("invalidation_conditions", []))
    evidence_score = d.get("thesis", {}).get("evidence_quality_score", 0.0) if isinstance(d.get("thesis"), dict) else 0.0
    composite = d.get("analyst_scores", {}).get("composite_score", 0.0) if isinstance(d.get("analyst_scores"), dict) else 0.0
    source = d.get("source", "")
    category = d.get("category", "")

    try:
        conn.execute("""
            INSERT OR REPLACE INTO recommendation_outcomes
            (ticker, recommendation_date, action, conviction, entry_price,
             target_price, thesis_summary, bear_case_summary, invalidation_conditions,
             evidence_quality_score, composite_score, source, category, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (ticker, rec_date, action, conviction, entry_price,
              target_price, thesis_summary, bear_case, invalidation,
              evidence_score, composite, source, category, now))
        conn.commit()
        log.info("Recorded recommendation outcome for %s", ticker)
    except Exception:
        log.exception("Failed to record recommendation for %s", ticker)
    conn.close()


def get_open_recommendations() -> list[dict[str, Any]]:
    """Return all recommendations where status='open'."""
    conn = _get_db()
    rows = conn.execute("""
        SELECT * FROM recommendation_outcomes WHERE status = 'open'
        ORDER BY recommendation_date DESC
    """).fetchall()
    cols = [d[0] for d in conn.execute("SELECT * FROM recommendation_outcomes LIMIT 0").description]
    conn.close()
    return [dict(zip(cols, row)) for row in rows]


def get_recommendations_by_ticker(ticker: str) -> list[dict[str, Any]]:
    """Return all recommendations for a ticker, newest first."""
    conn = _get_db()
    rows = conn.execute("""
        SELECT * FROM recommendation_outcomes WHERE ticker = ?
        ORDER BY recommendation_date DESC
    """, (ticker,)).fetchall()
    cols = [d[0] for d in conn.execute("SELECT * FROM recommendation_outcomes LIMIT 0").description]
    conn.close()
    return [dict(zip(cols, row)) for row in rows]


_OUTCOME_FIELDS = frozenset({
    "price_1d", "return_1d_pct", "price_1w", "return_1w_pct",
    "price_1m", "return_1m_pct", "price_3m", "return_3m_pct",
    "spy_return_1m_pct", "alpha_1m_pct",
    "thesis_played_out", "invalidation_triggered", "invalidation_detail",
    "user_rating", "status", "closed_date", "closed_reason", "updated_at",
})


def update_recommendation_outcome(rec_id: int, **kwargs) -> None:
    """Update outcome fields for a recommendation. Only whitelisted fields accepted."""
    if not kwargs:
        return
    invalid = set(kwargs.keys()) - _OUTCOME_FIELDS - {"updated_at"}
    if invalid:
        raise ValueError(f"Invalid outcome fields: {invalid}. Allowed: {_OUTCOME_FIELDS}")
    conn = _get_db()
    kwargs["updated_at"] = datetime.now().isoformat()
    sets = ", ".join(f"{k} = ?" for k in kwargs)
    vals = list(kwargs.values()) + [rec_id]
    conn.execute(f"UPDATE recommendation_outcomes SET {sets} WHERE id = ?", vals)
    conn.commit()
    conn.close()


def close_recommendation(rec_id: int, reason: str) -> None:
    """Close a recommendation with a reason."""
    conn = _get_db()
    now = datetime.now().isoformat()
    conn.execute("""
        UPDATE recommendation_outcomes SET status = 'closed', closed_date = ?,
        closed_reason = ?, updated_at = ? WHERE id = ?
    """, (date.today().isoformat(), reason, now, rec_id))
    conn.commit()
    conn.close()


def get_recommendation_scorecard(lookback_days: int = 30) -> dict:
    """Compute aggregate metrics for recommendation outcomes.

    Returns dict with: total_recommendations, hit_rate_1m, avg_return_1m_pct,
    avg_alpha_1m_pct, false_positive_rate, hit_rate_by_source,
    hit_rate_by_conviction, best_recommendation, worst_recommendation.
    """
    conn = _get_db()
    cutoff = date.today().isoformat()  # Get all since we filter by lookback
    rows = conn.execute("""
        SELECT * FROM recommendation_outcomes
        WHERE recommendation_date >= date(?, '-' || ? || ' days')
        ORDER BY recommendation_date DESC
    """, (cutoff, lookback_days)).fetchall()
    cols = [d[0] for d in conn.execute("SELECT * FROM recommendation_outcomes LIMIT 0").description]
    conn.close()

    recs = [dict(zip(cols, row)) for row in rows]
    total = len(recs)

    if total == 0:
        return {"total_recommendations": 0, "hit_rate_1m": 0, "avg_return_1m_pct": 0,
                "avg_alpha_1m_pct": 0, "false_positive_rate": 0}

    # 1-month hit rate
    recs_with_1m = [r for r in recs if r.get("return_1m_pct") is not None]
    hits_1m = sum(1 for r in recs_with_1m if r["return_1m_pct"] > 0)
    hit_rate_1m = (hits_1m / len(recs_with_1m) * 100) if recs_with_1m else 0

    # Average return
    avg_return_1m = (sum(r["return_1m_pct"] for r in recs_with_1m) / len(recs_with_1m)) if recs_with_1m else 0

    # Average alpha
    recs_with_alpha = [r for r in recs if r.get("alpha_1m_pct") is not None]
    avg_alpha = (sum(r["alpha_1m_pct"] for r in recs_with_alpha) / len(recs_with_alpha)) if recs_with_alpha else 0

    # False positive rate (high conviction with return < -10%)
    high_conv = [r for r in recs_with_1m if r.get("conviction") == "high"]
    false_positives = sum(1 for r in high_conv if r["return_1m_pct"] < -10)
    fp_rate = (false_positives / len(high_conv) * 100) if high_conv else 0

    # Best/worst
    best = max(recs_with_1m, key=lambda r: r["return_1m_pct"]) if recs_with_1m else None
    worst = min(recs_with_1m, key=lambda r: r["return_1m_pct"]) if recs_with_1m else None

    # By source
    from collections import defaultdict
    source_hits: dict[str, list] = defaultdict(list)
    for r in recs_with_1m:
        src = (r.get("source") or "unknown").split("/")[0]
        source_hits[src].append(r["return_1m_pct"] > 0)
    hit_by_source = {s: sum(v) / len(v) * 100 for s, v in source_hits.items() if v}

    # By conviction
    conv_hits: dict[str, list] = defaultdict(list)
    for r in recs_with_1m:
        conv_hits[r.get("conviction", "unknown")].append(r["return_1m_pct"] > 0)
    hit_by_conviction = {c: sum(v) / len(v) * 100 for c, v in conv_hits.items() if v}

    return {
        "total_recommendations": total,
        "hit_rate_1m": round(hit_rate_1m, 1),
        "avg_return_1m_pct": round(avg_return_1m, 2),
        "avg_alpha_1m_pct": round(avg_alpha, 2),
        "false_positive_rate": round(fp_rate, 1),
        "hit_rate_by_source": hit_by_source,
        "hit_rate_by_conviction": hit_by_conviction,
        "best_recommendation": {"ticker": best["ticker"], "return_pct": best["return_1m_pct"]} if best else None,
        "worst_recommendation": {"ticker": worst["ticker"], "return_pct": worst["return_1m_pct"]} if worst else None,
    }


# ═══════════════════════════════════════════════════════
# THESIS ACTIONS
# ═══════════════════════════════════════════════════════

def record_thesis_action(
    thesis_id: int | None,
    action_type: str,
    ticker: str,
    notes: str = "",
) -> None:
    """Record an action taken on an investment thesis.

    Args:
        thesis_id: ID from substack_tracker.theses or narrative_tracker.
        action_type: One of 'added_to_watchlist', 'bought', 'increased', 'ignored'.
        ticker: The ticker symbol acted upon.
        notes: Optional notes about the action.
    """
    conn = _get_db()
    today = date.today().isoformat()
    conn.execute(
        "INSERT INTO thesis_actions (thesis_id, action_date, action_type, ticker, notes) "
        "VALUES (?, ?, ?, ?, ?)",
        (thesis_id, today, action_type, ticker.upper(), notes),
    )
    conn.commit()
    conn.close()
    log.info("Recorded thesis action: %s %s (thesis_id=%s)", action_type, ticker, thesis_id)


def get_thesis_actions(lookback_days: int = 30) -> list[dict[str, Any]]:
    """Get recent thesis actions for performance review.

    Args:
        lookback_days: Number of days to look back.

    Returns:
        List of thesis action dicts.
    """
    conn = _get_db()
    cutoff = date.today().isoformat()
    rows = conn.execute("""
        SELECT id, thesis_id, action_date, action_type, ticker, outcome_30d, notes
        FROM thesis_actions
        WHERE action_date >= date(?, '-' || ? || ' days')
        ORDER BY action_date DESC
    """, (cutoff, lookback_days)).fetchall()
    conn.close()

    return [
        {
            "id": r[0],
            "thesis_id": r[1],
            "action_date": r[2],
            "action_type": r[3],
            "ticker": r[4],
            "outcome_30d": r[5],
            "notes": r[6],
        }
        for r in rows
    ]


def update_thesis_outcome(action_id: int, outcome_30d: str) -> None:
    """Update the 30-day outcome of a thesis action.

    Args:
        action_id: The thesis_actions row ID.
        outcome_30d: One of 'profitable', 'loss', 'flat'.
    """
    conn = _get_db()
    conn.execute(
        "UPDATE thesis_actions SET outcome_30d = ? WHERE id = ?",
        (outcome_30d, action_id),
    )
    conn.commit()
    conn.close()
    log.info("Updated thesis action %d outcome: %s", action_id, outcome_30d)
