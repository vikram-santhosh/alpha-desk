#!/usr/bin/env python3
"""AlphaDesk API server — serves the dashboard at http://127.0.0.1:8000.

Run with:  uvicorn server:app --reload
Or:        python server.py
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import asdict
from datetime import date
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="AlphaDesk API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _serialise(obj: Any) -> Any:
    """Recursively convert dataclasses / enums to JSON-safe dicts."""
    if hasattr(obj, "__dataclass_fields__"):
        return {k: _serialise(v) for k, v in asdict(obj).items()}
    if hasattr(obj, "value"):  # Enum
        return obj.value
    if isinstance(obj, list):
        return [_serialise(i) for i in obj]
    if isinstance(obj, dict):
        return {k: _serialise(v) for k, v in obj.items()}
    return obj


def _result_to_dict(result) -> dict:
    from src.score_engine.signals import Direction
    top = []
    for ts in result.top:
        breakdown = []
        for b in ts.breakdown:
            bd = dict(b)
            if isinstance(bd.get("direction"), Direction):
                bd["direction"] = bd["direction"].name
            breakdown.append(bd)
        top.append({
            "ticker":               ts.ticker,
            "score":                ts.score,
            "platforms_reporting":  ts.platforms_reporting,
            "platforms_failed":     ts.platforms_failed,
            "breakdown":            breakdown,
        })
    return {
        "top":              top,
        "snapshot_id":      result.snapshot_id,
        "weights_version":  result.weights_version,
        "diagnostics":      result.diagnostics,
    }


# ── Score endpoints ───────────────────────────────────────────────────────────

@app.get("/api/score/top-buys")
async def get_top_buys():
    """Return the most recent saved snapshot (fast, no LLM calls)."""
    from src.score_engine.snapshot import list_snapshots, load_snapshot
    from src.score_engine.aggregator import score_tickers
    from src.score_engine.weights import load_weights, WEIGHTS_VERSION

    rows = list_snapshots(limit=1)
    if not rows:
        raise HTTPException(status_code=404, detail="No snapshots found — run the score engine first")

    snap = load_snapshot(rows[0]["snapshot_id"])
    if snap is None:
        raise HTTPException(status_code=404, detail="Snapshot not found")

    if snap["scores"]:
        scores = snap["scores"]
    else:
        weights = load_weights()
        scores = score_tickers(snap["signals"], weights, [])

    ranked = sorted(scores, key=lambda s: (-s.score, s.ticker))[:10]

    from src.score_engine.signals import RunResult, Direction
    result = RunResult(
        top=ranked,
        snapshot_id=snap["snapshot_id"],
        weights_version=snap["weights_version"],
        diagnostics={
            "elapsed_s":         0.0,
            "signals_collected": len(snap["signals"]),
            "sensors_ok":        sorted({sig.sensor for sig in snap["signals"]}),
            "sensors_empty":     [],
            "sensors_failed":    [],
            "tickers_scored":    len(scores),
        },
    )
    return _result_to_dict(result)


class ScoreRunRequest(BaseModel):
    top_n: int = 10
    depth: str = "standard"


@app.post("/api/score/run")
async def run_score(req: ScoreRunRequest):
    """Run the full score engine (takes 10–30s for real API calls)."""
    from src.score_engine.engine import run_scoring
    from src.score_engine.signals import RunRequest

    request = RunRequest(top_n=req.top_n, depth=req.depth)
    result = await run_scoring(request)
    return _result_to_dict(result)


# ── Existing endpoints (stubs for dashboard compatibility) ────────────────────

@app.get("/api/portfolio")
async def get_portfolio():
    from src.shared.config_loader import load_config
    cfg = load_config("advisor")
    holdings = cfg.get("holdings", [])
    return {
        "positions": [{"ticker": h["ticker"], "weight_pct": round(100 / len(holdings), 1)} for h in holdings],
        "top_holding_pct": round(100 / max(len(holdings), 1), 1),
        "top3_pct": round(300 / max(len(holdings), 1), 1),
        "concentration_flag": False,
    }


@app.get("/api/council/models")
async def get_council_models():
    return [
        {"model_id": "claude-opus-4-6",   "label": "Opus 4.6",   "provider": "Anthropic", "enabled": True},
        {"model_id": "claude-sonnet-4-6",  "label": "Sonnet 4.6", "provider": "Anthropic", "enabled": True},
        {"model_id": "gemini-2.5-pro",     "label": "Gemini 2.5 Pro", "provider": "Google", "enabled": True},
    ]


@app.get("/api/council/runs/latest")
async def get_latest_council(ticker: str | None = None):
    raise HTTPException(status_code=404, detail="No council runs saved yet")


@app.get("/api/ideas/runs/latest")
async def get_latest_ideas(mode: str | None = None):
    raise HTTPException(status_code=404, detail="No idea scout runs saved yet")


@app.get("/api/macro")
async def get_macro():
    return {
        "regime": {
            "call": "Risk-On",
            "score": 62,
            "confidence": 70,
            "rationale": "Hyperscaler CapEx boom continues; AI infrastructure build-out accelerating.",
            "agent": "MacroAnalyst",
            "scannedAt": date.today().isoformat(),
            "source": "backend",
            "sourceDetail": "AlphaDesk macro config",
            "degradedReasons": [],
        },
        "themes": [],
        "degraded_reasons": [],
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="127.0.0.1", port=8000, reload=True)
