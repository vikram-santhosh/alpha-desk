"""MySQL persistence for web-triggered capital-deployment plan runs."""
from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any, Optional

from src.shared.db import get_conn


def _capital(payload: dict[str, Any]) -> float:
    mandate = payload.get("mandate") if isinstance(payload.get("mandate"), dict) else {}
    try:
        return float(mandate.get("capital") or payload.get("capital") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _run_cost(payload: dict[str, Any]) -> float:
    try:
        return float(payload.get("cost_usd") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def save_deployment_run(payload: dict[str, Any]) -> tuple[int, str]:
    created_at = datetime.now().isoformat()
    stored = dict(payload)
    stored["saved_at"] = created_at
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO deployment_runs (created_at, as_of, capital, run_cost, payload)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (
                created_at,
                date.today().isoformat(),
                _capital(stored),
                _run_cost(stored),
                json.dumps(stored),
            ),
        )
        run_id = int(cur.lastrowid)
        stored["run_id"] = run_id
        cur.execute(
            "UPDATE deployment_runs SET payload = %s WHERE id = %s",
            (json.dumps(stored), run_id),
        )
    return run_id, created_at


def latest_deployment_run() -> Optional[dict[str, Any]]:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, created_at, payload
            FROM deployment_runs
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
