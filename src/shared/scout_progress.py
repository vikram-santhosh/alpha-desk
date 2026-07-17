"""Live progress tracker for the Alpha Scout pipeline.

A thread-safe, process-local singleton: the pipeline (writer) marks each stage as
it runs, and the cockpit API (reader) snapshots it for a live stage view. It is
best-effort and must never raise into the pipeline — progress reporting is purely
observational.

Usage (writer):
    scout_progress.start("top_buys")
    scout_progress.stage("source", "sourcing candidates…")
    ...
    scout_progress.finish()              # success
    scout_progress.finish(error="...")   # failure

Usage (reader):
    snap = scout_progress.snapshot()
"""
from __future__ import annotations

import threading
import time
from typing import Any

# Ordered pipeline stages: (key, human-readable label).
STAGES: list[tuple[str, str]] = [
    ("config", "Load config & universe"),
    ("source", "Source candidates"),
    ("market_data", "Fetch market data"),
    ("screening", "Screen & score"),
    ("synthesis", "Synthesize ideas"),
    ("publish", "Publish signals"),
]

_lock = threading.Lock()
_state: dict[str, Any] = {
    "active": False,
    "mode": None,
    "run_id": None,
    "started_at": None,
    "updated_at": None,
    "finished_at": None,
    "current": None,
    "error": None,
    "stages": [],
}


def _blank_stages() -> list[dict[str, Any]]:
    return [
        {"key": key, "label": label, "status": "pending", "detail": "", "ts": None}
        for key, label in STAGES
    ]


def start(mode: str) -> None:
    """Begin a new run, resetting all stages to pending."""
    with _lock:
        now = time.time()
        _state.update(
            {
                "active": True,
                "mode": mode,
                "run_id": str(int(now * 1000)),
                "started_at": now,
                "updated_at": now,
                "finished_at": None,
                "current": None,
                "error": None,
                "stages": _blank_stages(),
            }
        )


def stage(key: str, detail: str = "") -> None:
    """Begin a stage. Implicitly completes every earlier stage. Unknown keys
    are ignored. Never raises."""
    try:
        with _lock:
            now = time.time()
            _state["updated_at"] = now
            seen_target = False
            for s in _state["stages"]:
                if s["key"] == key:
                    s["status"] = "running"
                    s["detail"] = detail
                    s["ts"] = now
                    seen_target = True
                    _state["current"] = key
                elif not seen_target:
                    if s["status"] in ("pending", "running"):
                        s["status"] = "done"
                        if s["ts"] is None:
                            s["ts"] = now
    except Exception:  # pragma: no cover - observational only
        pass


def finish(error: str | None = None) -> None:
    """Mark the run complete. Any still-running stage is finalized (done, or
    error when an error is supplied). Never raises."""
    try:
        with _lock:
            now = time.time()
            for s in _state["stages"]:
                if s["status"] in ("pending", "running"):
                    if error:
                        s["status"] = "error" if s["status"] == "running" else "skipped"
                    elif s["status"] == "running":
                        s["status"] = "done"
            _state["active"] = False
            _state["finished_at"] = now
            _state["updated_at"] = now
            _state["current"] = None
            _state["error"] = error
    except Exception:  # pragma: no cover - observational only
        pass


def snapshot() -> dict[str, Any]:
    """Return a deep-ish copy of the current progress state (safe to serialize)."""
    with _lock:
        return {
            "active": _state["active"],
            "mode": _state["mode"],
            "run_id": _state["run_id"],
            "started_at": _state["started_at"],
            "updated_at": _state["updated_at"],
            "finished_at": _state["finished_at"],
            "current": _state["current"],
            "error": _state["error"],
            "stages": [dict(s) for s in _state["stages"]],
        }
