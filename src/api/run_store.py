"""SQLite persistence for interactive cockpit run payloads."""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

DB_PATH = Path(os.environ.get("ALPHADESK_DATA_DIR", "data")) / "cockpit_runs.db"


def _get_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS idea_scout_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            mode TEXT NOT NULL,
            as_of TEXT NOT NULL,
            idea_count INTEGER NOT NULL,
            cost_usd REAL NOT NULL,
            payload TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_idea_scout_runs_mode_created
        ON idea_scout_runs (mode, created_at DESC)
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS council_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            ticker TEXT NOT NULL,
            models TEXT NOT NULL,
            panel_count INTEGER NOT NULL,
            cost_usd REAL NOT NULL,
            execution_mode TEXT NOT NULL,
            payload TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_council_runs_ticker_created
        ON council_runs (ticker, created_at DESC)
    """)
    conn.commit()
    return conn


def save_idea_scout_run(mode: str, payload: dict[str, Any]) -> tuple[int, str]:
    created_at = datetime.now().isoformat()
    stored_payload = dict(payload)
    stored_payload["saved_at"] = created_at
    ideas = stored_payload.get("ideas") if isinstance(stored_payload.get("ideas"), list) else []
    conn = _get_db()
    cursor = conn.execute(
        """
        INSERT INTO idea_scout_runs (created_at, mode, as_of, idea_count, cost_usd, payload)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            created_at,
            mode,
            str(stored_payload.get("as_of") or ""),
            len(ideas),
            float(stored_payload.get("cost_usd") or 0.0),
            json.dumps(stored_payload),
        ),
    )
    run_id = int(cursor.lastrowid)
    stored_payload["run_id"] = run_id
    conn.execute(
        "UPDATE idea_scout_runs SET payload = ? WHERE id = ?",
        (json.dumps(stored_payload), run_id),
    )
    conn.commit()
    conn.close()
    return run_id, created_at


def latest_idea_scout_run(mode: Optional[str] = None) -> Optional[dict[str, Any]]:
    conn = _get_db()
    if mode:
        row = conn.execute(
            """
            SELECT id, created_at, payload
            FROM idea_scout_runs
            WHERE mode = ?
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            (mode,),
        ).fetchone()
    else:
        row = conn.execute(
            """
            SELECT id, created_at, payload
            FROM idea_scout_runs
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """
        ).fetchone()
    conn.close()
    if row is None:
        return None
    payload = json.loads(row[2])
    payload.setdefault("run_id", int(row[0]))
    payload.setdefault("saved_at", row[1])
    return payload


def list_idea_scout_runs(limit: int = 20, mode: Optional[str] = None) -> list[dict[str, Any]]:
    limit = max(1, min(100, int(limit)))
    conn = _get_db()
    if mode:
        rows = conn.execute(
            """
            SELECT id, created_at, mode, as_of, idea_count, cost_usd
            FROM idea_scout_runs
            WHERE mode = ?
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (mode, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT id, created_at, mode, as_of, idea_count, cost_usd
            FROM idea_scout_runs
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    conn.close()
    return [
        {
            "run_id": int(row[0]),
            "saved_at": row[1],
            "scout_mode": row[2],
            "as_of": row[3],
            "idea_count": int(row[4]),
            "cost_usd": float(row[5]),
        }
        for row in rows
    ]


def save_council_run(ticker: str, models: list[str], payload: dict[str, Any]) -> tuple[int, str]:
    created_at = datetime.now().isoformat()
    stored_payload = dict(payload)
    stored_payload["saved_at"] = created_at
    normalized_ticker = str(ticker or stored_payload.get("verdict", {}).get("ticker") or "").upper()
    panel = stored_payload.get("panel") if isinstance(stored_payload.get("panel"), list) else []
    execution_mode = str(stored_payload.get("execution_mode") or "unknown")
    conn = _get_db()
    cursor = conn.execute(
        """
        INSERT INTO council_runs (created_at, ticker, models, panel_count, cost_usd, execution_mode, payload)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            created_at,
            normalized_ticker,
            json.dumps(models),
            len(panel),
            float(stored_payload.get("cost_usd") or 0.0),
            execution_mode,
            json.dumps(stored_payload),
        ),
    )
    run_id = int(cursor.lastrowid)
    stored_payload["run_id"] = run_id
    conn.execute(
        "UPDATE council_runs SET payload = ? WHERE id = ?",
        (json.dumps(stored_payload), run_id),
    )
    conn.commit()
    conn.close()
    return run_id, created_at


def latest_council_run(ticker: Optional[str] = None) -> Optional[dict[str, Any]]:
    normalized_ticker = str(ticker or "").upper().strip()
    conn = _get_db()
    if normalized_ticker:
        row = conn.execute(
            """
            SELECT id, created_at, payload
            FROM council_runs
            WHERE ticker = ?
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            (normalized_ticker,),
        ).fetchone()
    else:
        row = conn.execute(
            """
            SELECT id, created_at, payload
            FROM council_runs
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """
        ).fetchone()
    conn.close()
    if row is None:
        return None
    payload = json.loads(row[2])
    payload.setdefault("run_id", int(row[0]))
    payload.setdefault("saved_at", row[1])
    return payload


def list_council_runs(limit: int = 20, ticker: Optional[str] = None) -> list[dict[str, Any]]:
    limit = max(1, min(100, int(limit)))
    normalized_ticker = str(ticker or "").upper().strip()
    conn = _get_db()
    if normalized_ticker:
        rows = conn.execute(
            """
            SELECT id, created_at, ticker, models, panel_count, cost_usd, execution_mode
            FROM council_runs
            WHERE ticker = ?
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (normalized_ticker, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT id, created_at, ticker, models, panel_count, cost_usd, execution_mode
            FROM council_runs
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    conn.close()
    summaries = []
    for row in rows:
        try:
            models = json.loads(row[3])
        except json.JSONDecodeError:
            models = []
        summaries.append(
            {
                "run_id": int(row[0]),
                "saved_at": row[1],
                "ticker": row[2],
                "models": models if isinstance(models, list) else [],
                "panel_count": int(row[4]),
                "cost_usd": float(row[5]),
                "execution_mode": row[6],
            }
        )
    return summaries
