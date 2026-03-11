"""Narrative Propagation Tracker — tracks how investment theses propagate across sources.

Monitors thesis flow from expert sources (Substack) through amplification (YouTube)
to mainstream adoption (Reddit). Records signal outcomes and source reliability
for continuous improvement of signal quality.
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from src.shared.agent_bus import publish
from src.utils.logger import get_logger

log = get_logger(__name__)

DB_PATH = Path(os.environ.get("ALPHADESK_DATA_DIR", "data")) / "narrative_tracker.db"
AGENT_NAME = "narrative_tracker"

# Propagation stage ordering and platform mapping
STAGE_ORDER = {"expert": 0, "amplified": 1, "mainstream": 2}
PLATFORM_TO_STAGE = {
    "substack": "expert",
    "youtube": "amplified",
    "reddit": "mainstream",
}

# Minimum word length for significant-word matching
_MIN_WORD_LEN = 5
# Stop words to exclude from narrative matching
_STOP_WORDS = frozenset({
    "about", "could", "would", "should", "their", "there", "these",
    "those", "which", "where", "while", "after", "before", "being",
    "between", "during", "other", "under", "through", "stock", "market",
    "price", "share", "company", "invest", "trading",
})


def _get_db() -> sqlite3.Connection:
    """Get or create the narrative tracker database."""
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS narrative_propagation (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            narrative TEXT NOT NULL,
            first_seen_source TEXT NOT NULL,
            first_seen_date TEXT NOT NULL,
            first_seen_detail TEXT NOT NULL,
            current_stage TEXT NOT NULL DEFAULT 'expert',
            affected_tickers TEXT NOT NULL,
            stage_history TEXT NOT NULL DEFAULT '[]',
            confidence REAL DEFAULT 0.5,
            last_updated TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS signal_outcomes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            signal_id INTEGER NOT NULL,
            signal_type TEXT NOT NULL,
            ticker TEXT NOT NULL,
            signal_date TEXT NOT NULL,
            price_at_signal REAL,
            price_after_1d REAL,
            price_after_5d REAL,
            price_after_20d REAL,
            outcome TEXT,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS source_reliability (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_name TEXT NOT NULL,
            source_platform TEXT NOT NULL,
            total_signals INTEGER DEFAULT 0,
            correct_signals INTEGER DEFAULT 0,
            hit_rate REAL DEFAULT 0.0,
            avg_lead_time_hours REAL,
            last_updated TEXT NOT NULL,
            UNIQUE(source_name, source_platform)
        );

        CREATE INDEX IF NOT EXISTS idx_narrative_stage
            ON narrative_propagation(current_stage);
        CREATE INDEX IF NOT EXISTS idx_narrative_updated
            ON narrative_propagation(last_updated);
        CREATE INDEX IF NOT EXISTS idx_signal_outcomes_ticker
            ON signal_outcomes(ticker);
        CREATE INDEX IF NOT EXISTS idx_signal_outcomes_date
            ON signal_outcomes(signal_date);
        CREATE INDEX IF NOT EXISTS idx_source_reliability_platform
            ON source_reliability(source_platform);
    """)
    conn.commit()
    return conn


# ---------------------------------------------------------------
# Fuzzy narrative matching
# ---------------------------------------------------------------

def _significant_words(text: str) -> set[str]:
    """Extract significant words (>4 chars, not stop words) from text."""
    words = set()
    for word in text.lower().split():
        cleaned = "".join(c for c in word if c.isalnum())
        if len(cleaned) >= _MIN_WORD_LEN and cleaned not in _STOP_WORDS:
            words.add(cleaned)
    return words


def _ticker_overlap(tickers_a: list[str], tickers_b: list[str]) -> float:
    """Return the fraction of overlap between two ticker lists (0.0 - 1.0)."""
    if not tickers_a or not tickers_b:
        return 0.0
    set_a = set(t.upper() for t in tickers_a)
    set_b = set(t.upper() for t in tickers_b)
    intersection = set_a & set_b
    smaller = min(len(set_a), len(set_b))
    return len(intersection) / smaller if smaller > 0 else 0.0


def _narratives_match(
    existing_narrative: str,
    existing_tickers: list[str],
    new_narrative: str,
    new_tickers: list[str],
) -> bool:
    """Check if two narratives are about the same topic.

    Match if:
    1. >50% ticker overlap, AND
    2. 2+ significant words from new narrative appear in existing
    """
    if _ticker_overlap(existing_tickers, new_tickers) <= 0.5:
        return False

    new_words = _significant_words(new_narrative)
    existing_words = _significant_words(existing_narrative)
    common = new_words & existing_words
    return len(common) >= 2


# ---------------------------------------------------------------
# Core narrative tracking
# ---------------------------------------------------------------

def record_narrative(
    narrative: str,
    source_platform: str,
    source_detail: str,
    affected_tickers: list[str],
    conviction: str = "medium",
) -> int:
    """Record a new narrative or update propagation stage of existing one.

    If a similar narrative already exists (fuzzy match on title + tickers overlap),
    update its propagation stage instead of creating a new record.

    Stage progression:
        - First seen on Substack -> stage = "expert"
        - Later seen on YouTube -> stage = "amplified"
        - Later seen on Reddit -> stage = "mainstream"

    Returns: narrative_id
    """
    now = datetime.now().isoformat()
    today = date.today().isoformat()
    new_stage = PLATFORM_TO_STAGE.get(source_platform.lower(), "expert")
    confidence_map = {"low": 0.3, "medium": 0.5, "high": 0.8}
    confidence = confidence_map.get(conviction, 0.5)

    conn = _get_db()
    try:
        # Check for existing matching narratives
        rows = conn.execute(
            "SELECT id, narrative, affected_tickers, current_stage, stage_history, confidence "
            "FROM narrative_propagation ORDER BY last_updated DESC"
        ).fetchall()

        matched_id = None
        for row in rows:
            existing_tickers = json.loads(row[2])
            if _narratives_match(row[1], existing_tickers, narrative, affected_tickers):
                matched_id = row[0]
                current_stage = row[3]
                stage_history = json.loads(row[4])
                current_confidence = row[5]
                break

        if matched_id is not None:
            # Update existing narrative
            old_stage_order = STAGE_ORDER.get(current_stage, 0)
            new_stage_order = STAGE_ORDER.get(new_stage, 0)

            if new_stage_order > old_stage_order:
                # Stage promotion
                stage_history.append({
                    "stage": new_stage,
                    "date": today,
                    "source": f"{source_platform}:{source_detail}",
                })
                updated_confidence = min(1.0, current_confidence + 0.15)
                conn.execute(
                    "UPDATE narrative_propagation SET current_stage = ?, stage_history = ?, "
                    "confidence = ?, last_updated = ? WHERE id = ?",
                    (new_stage, json.dumps(stage_history), updated_confidence, now, matched_id),
                )
                conn.commit()

                # Publish propagation signal
                if new_stage == "amplified":
                    signal_type = "thesis_propagation"
                else:
                    signal_type = "thesis_confirmed"

                try:
                    publish(
                        signal_type=signal_type,
                        source_agent=AGENT_NAME,
                        payload={
                            "narrative_id": matched_id,
                            "narrative": narrative,
                            "from_stage": current_stage,
                            "to_stage": new_stage,
                            "source": f"{source_platform}:{source_detail}",
                            "tickers": affected_tickers,
                            "confidence": updated_confidence,
                        },
                    )
                except ValueError:
                    log.warning("Signal type %s not registered in agent bus", signal_type)

                log.info(
                    "Narrative %d promoted: %s -> %s (%s)",
                    matched_id, current_stage, new_stage, narrative[:60],
                )
            else:
                # Same or lower stage — update confidence and recency
                updated_confidence = min(1.0, current_confidence + 0.05)
                conn.execute(
                    "UPDATE narrative_propagation SET confidence = ?, last_updated = ? "
                    "WHERE id = ?",
                    (updated_confidence, now, matched_id),
                )
                conn.commit()

            return matched_id
        else:
            # Insert new narrative
            stage_history = [{"stage": new_stage, "date": today, "source": f"{source_platform}:{source_detail}"}]
            cursor = conn.execute(
                "INSERT INTO narrative_propagation "
                "(narrative, first_seen_source, first_seen_date, first_seen_detail, "
                "current_stage, affected_tickers, stage_history, confidence, last_updated) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    narrative,
                    source_platform.lower(),
                    today,
                    source_detail,
                    new_stage,
                    json.dumps([t.upper() for t in affected_tickers]),
                    json.dumps(stage_history),
                    confidence,
                    now,
                ),
            )
            narrative_id = cursor.lastrowid
            conn.commit()
            log.info("New narrative %d recorded: %s (stage=%s)", narrative_id, narrative[:60], new_stage)
            return narrative_id
    finally:
        conn.close()


def get_propagating_narratives(min_stage: str = "amplified") -> list[dict]:
    """Get narratives that have propagated beyond initial source.

    Returns narratives with stage >= min_stage, ordered by recency.
    """
    min_order = STAGE_ORDER.get(min_stage, 1)
    conn = _get_db()
    rows = conn.execute(
        "SELECT * FROM narrative_propagation ORDER BY last_updated DESC"
    ).fetchall()
    cols = [d[0] for d in conn.execute("SELECT * FROM narrative_propagation LIMIT 0").description]
    conn.close()

    results = []
    for row in rows:
        d = dict(zip(cols, row))
        if STAGE_ORDER.get(d["current_stage"], 0) >= min_order:
            d["affected_tickers"] = json.loads(d["affected_tickers"])
            d["stage_history"] = json.loads(d["stage_history"])
            results.append(d)
    return results


def get_recent_narratives(days: int = 7) -> list[dict]:
    """Get all narratives from the last N days."""
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    conn = _get_db()
    rows = conn.execute(
        "SELECT * FROM narrative_propagation WHERE last_updated >= ? "
        "ORDER BY last_updated DESC",
        (cutoff,),
    ).fetchall()
    cols = [d[0] for d in conn.execute("SELECT * FROM narrative_propagation LIMIT 0").description]
    conn.close()

    results = []
    for row in rows:
        d = dict(zip(cols, row))
        d["affected_tickers"] = json.loads(d["affected_tickers"])
        d["stage_history"] = json.loads(d["stage_history"])
        results.append(d)
    return results


# ---------------------------------------------------------------
# Signal outcome tracking
# ---------------------------------------------------------------

def record_signal_outcome(
    signal_id: int,
    signal_type: str,
    ticker: str,
    price_at_signal: float | None = None,
) -> None:
    """Record a signal for later outcome tracking."""
    now = datetime.now().isoformat()
    today = date.today().isoformat()
    conn = _get_db()
    conn.execute(
        "INSERT INTO signal_outcomes "
        "(signal_id, signal_type, ticker, signal_date, price_at_signal, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (signal_id, signal_type, ticker.upper(), today, price_at_signal, now),
    )
    conn.commit()
    conn.close()
    log.info("Recorded signal outcome for %s (signal_id=%d)", ticker, signal_id)


def update_signal_outcomes(ticker: str, current_price: float) -> None:
    """Update price_after fields for open signals on this ticker.

    Called by portfolio_analyst during daily price fetch.
    Fills in price_after_1d, price_after_5d, price_after_20d based on
    signal_date vs today's date.
    """
    today = date.today()
    conn = _get_db()
    rows = conn.execute(
        "SELECT id, signal_date FROM signal_outcomes "
        "WHERE ticker = ? AND outcome IS NULL",
        (ticker.upper(),),
    ).fetchall()

    for row in rows:
        signal_id = row[0]
        try:
            signal_date = date.fromisoformat(row[1])
        except (ValueError, TypeError):
            continue

        days_elapsed = (today - signal_date).days
        updates: dict[str, Any] = {}

        if days_elapsed >= 1 and updates is not None:
            # Check if 1d price is not yet filled
            existing = conn.execute(
                "SELECT price_after_1d, price_after_5d, price_after_20d "
                "FROM signal_outcomes WHERE id = ?",
                (signal_id,),
            ).fetchone()

            if existing[0] is None and days_elapsed >= 1:
                updates["price_after_1d"] = current_price
            if existing[1] is None and days_elapsed >= 5:
                updates["price_after_5d"] = current_price
            if existing[2] is None and days_elapsed >= 20:
                updates["price_after_20d"] = current_price

        if updates:
            sets = ", ".join(f"{k} = ?" for k in updates)
            vals = list(updates.values()) + [signal_id]
            conn.execute(f"UPDATE signal_outcomes SET {sets} WHERE id = ?", vals)

    conn.commit()
    conn.close()


# ---------------------------------------------------------------
# Source reliability
# ---------------------------------------------------------------

def update_source_reliability(source_name: str, source_platform: str) -> None:
    """Recalculate hit rate for a source based on signal_outcomes.

    A signal is "correct" if price moved in the expected direction
    within 5 trading days.
    """
    now = datetime.now().isoformat()
    conn = _get_db()

    # Count signals that have 5-day outcomes
    rows = conn.execute(
        "SELECT price_at_signal, price_after_5d FROM signal_outcomes "
        "WHERE signal_type LIKE ? AND price_at_signal IS NOT NULL "
        "AND price_after_5d IS NOT NULL",
        (f"%{source_name}%",),
    ).fetchall()

    total = len(rows)
    correct = 0
    for row in rows:
        price_at = row[0]
        price_after = row[1]
        if price_at and price_after and price_after > price_at:
            correct += 1

    hit_rate = correct / total if total > 0 else 0.0

    conn.execute(
        "INSERT INTO source_reliability "
        "(source_name, source_platform, total_signals, correct_signals, hit_rate, last_updated) "
        "VALUES (?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(source_name, source_platform) DO UPDATE SET "
        "total_signals = ?, correct_signals = ?, hit_rate = ?, last_updated = ?",
        (source_name, source_platform, total, correct, hit_rate, now,
         total, correct, hit_rate, now),
    )
    conn.commit()
    conn.close()

    if total > 0:
        try:
            publish(
                signal_type="source_quality_update",
                source_agent=AGENT_NAME,
                payload={
                    "source_name": source_name,
                    "source_platform": source_platform,
                    "hit_rate": round(hit_rate, 3),
                    "total_signals": total,
                },
            )
        except ValueError:
            log.warning("Signal type source_quality_update not registered in agent bus")

    log.info(
        "Source reliability updated: %s/%s — %d/%d (%.1f%%)",
        source_name, source_platform, correct, total, hit_rate * 100,
    )


def get_source_reliability(
    source_platform: str | None = None,
    min_signals: int = 5,
) -> list[dict]:
    """Get source reliability scores, filtered by platform and minimum sample size."""
    conn = _get_db()
    query = "SELECT * FROM source_reliability WHERE total_signals >= ?"
    params: list[Any] = [min_signals]

    if source_platform:
        query += " AND source_platform = ?"
        params.append(source_platform)

    query += " ORDER BY hit_rate DESC"
    rows = conn.execute(query, params).fetchall()
    cols = [d[0] for d in conn.execute("SELECT * FROM source_reliability LIMIT 0").description]
    conn.close()

    return [dict(zip(cols, row)) for row in rows]


# ---------------------------------------------------------------
# Context builder for Opus synthesis
# ---------------------------------------------------------------

def build_narrative_context() -> str:
    """Build a narrative propagation context string for the Opus synthesis prompt.

    Returns human-readable summary of actively propagating narratives,
    e.g.: "AI CapEx thesis (expert->amplified): first seen on Fabricated Knowledge,
    now discussed by Patrick Boyle on YouTube"
    """
    narratives = get_propagating_narratives(min_stage="amplified")
    if not narratives:
        return "No actively propagating narratives detected."

    lines = []
    for n in narratives[:10]:  # Limit to top 10
        tickers = ", ".join(n["affected_tickers"][:5])
        history = n["stage_history"]

        # Build source trail
        sources = []
        for entry in history:
            sources.append(f"{entry.get('source', 'unknown')} ({entry.get('date', '')})")
        source_trail = " -> ".join(sources)

        stage_display = n["current_stage"]
        confidence_pct = round(n["confidence"] * 100)

        lines.append(
            f"- {n['narrative'][:100]} [{tickers}] "
            f"(stage: {stage_display}, confidence: {confidence_pct}%): "
            f"{source_trail}"
        )

    return "Propagating Narratives:\n" + "\n".join(lines)
