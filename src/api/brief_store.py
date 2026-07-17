"""MySQL persistence for web-triggered brief runs."""
from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any, Optional

from src.shared.db import get_conn


def _run_cost(payload: dict[str, Any]) -> float:
    stats = payload.get("stats") if isinstance(payload.get("stats"), dict) else {}
    try:
        return float(stats.get("run_cost") or payload.get("cost_usd") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def save_brief_run(run_type: str, payload: dict[str, Any]) -> tuple[int, str]:
    created_at = datetime.now().isoformat()
    stored = dict(payload)
    stored["saved_at"] = created_at
    stored["run_type"] = run_type
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO daily_brief_runs (created_at, run_type, as_of, run_cost, payload)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (
                created_at,
                run_type,
                date.today().isoformat(),
                _run_cost(stored),
                json.dumps(stored),
            ),
        )
        run_id = int(cur.lastrowid)
        stored["run_id"] = run_id
        cur.execute(
            "UPDATE daily_brief_runs SET payload = %s WHERE id = %s",
            (json.dumps(stored), run_id),
        )
    return run_id, created_at


def latest_brief_run() -> Optional[dict[str, Any]]:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, created_at, payload
            FROM daily_brief_runs
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """
        )
        row = cur.fetchone()
    if not row:
        return None
    payload = json.loads(row["payload"])
    payload.setdefault("run_id", int(row["id"]))
    payload.setdefault("saved_at", row["created_at"])
    return payload
