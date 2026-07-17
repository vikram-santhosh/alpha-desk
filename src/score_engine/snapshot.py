"""Snapshot persistence for the score engine.

A run = (snapshot_id → frozen signals → scores).
Storing both signals and scores lets any snapshot be rescored identically later.
"""
from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path

from src.score_engine.signals import Direction, TickerScore, TickerSignal

DB_PATH = Path(os.environ.get("ALPHADESK_DATA_DIR", "data")) / "score_engine.db"


def _get_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS snapshots (
            snapshot_id     TEXT PRIMARY KEY,
            created_at      TEXT NOT NULL,
            weights_version TEXT NOT NULL,
            tickers         TEXT NOT NULL,
            signals         TEXT NOT NULL,
            scores          TEXT
        );
    """)
    conn.commit()
    return conn


def new_snapshot_id() -> str:
    return datetime.now(UTC).strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]


def _signal_to_dict(sig: TickerSignal) -> dict:
    return {
        "ticker":     sig.ticker,
        "sensor":     sig.sensor,
        "direction":  sig.direction.name,
        "strength":   sig.strength,
        "confidence": sig.confidence,
        "evidence":   sig.evidence,
        "as_of":      sig.as_of,
    }


def _signal_from_dict(d: dict) -> TickerSignal:
    return TickerSignal(
        ticker=d["ticker"],
        sensor=d["sensor"],
        direction=Direction[d["direction"]],
        strength=d["strength"],
        confidence=d["confidence"],
        evidence=d["evidence"],
        as_of=d["as_of"],
    )


def _score_to_dict(ts: TickerScore) -> dict:
    return {
        "ticker":              ts.ticker,
        "score":               ts.score,
        "platforms_reporting": ts.platforms_reporting,
        "platforms_failed":    ts.platforms_failed,
        "breakdown":           ts.breakdown,
    }


def _score_from_dict(d: dict) -> TickerScore:
    return TickerScore(
        ticker=d["ticker"],
        score=d["score"],
        platforms_reporting=d["platforms_reporting"],
        platforms_failed=d["platforms_failed"],
        breakdown=d["breakdown"],
    )


def save_snapshot(
    snapshot_id: str,
    tickers: list[str],
    signals: list[TickerSignal],
    weights_version: str,
    scores: list[TickerScore] | None = None,
) -> None:
    """Upsert a snapshot row. Call once with signals, again to attach scores."""
    conn = _get_db()
    signals_json = json.dumps([_signal_to_dict(s) for s in signals])
    scores_json  = json.dumps([_score_to_dict(s)  for s in scores]) if scores is not None else None
    conn.execute(
        """
        INSERT INTO snapshots (snapshot_id, created_at, weights_version, tickers, signals, scores)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(snapshot_id) DO UPDATE SET scores = excluded.scores
        """,
        (
            snapshot_id,
            datetime.now(UTC).isoformat(),
            weights_version,
            json.dumps(tickers),
            signals_json,
            scores_json,
        ),
    )
    conn.commit()
    conn.close()


def load_snapshot(snapshot_id: str) -> dict | None:
    """Return a snapshot dict or None if not found.

    Keys: snapshot_id, created_at, weights_version, tickers (list),
          signals (list[TickerSignal]), scores (list[TickerScore] | None).
    """
    conn = _get_db()
    row = conn.execute(
        "SELECT * FROM snapshots WHERE snapshot_id = ?", (snapshot_id,)
    ).fetchone()
    conn.close()
    if row is None:
        return None
    return {
        "snapshot_id":     row["snapshot_id"],
        "created_at":      row["created_at"],
        "weights_version": row["weights_version"],
        "tickers":         json.loads(row["tickers"]),
        "signals":         [_signal_from_dict(d) for d in json.loads(row["signals"])],
        "scores":          [_score_from_dict(d)  for d in json.loads(row["scores"])]
                           if row["scores"] else None,
    }


def list_snapshots(limit: int = 20) -> list[dict]:
    """Return recent snapshots (metadata only, no signals/scores)."""
    conn = _get_db()
    rows = conn.execute(
        "SELECT snapshot_id, created_at, weights_version FROM snapshots ORDER BY created_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
