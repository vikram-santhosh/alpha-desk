# AlphaDesk — Score Engine: M0 + M1 Implementation Task

**Branch:** `feat/score-engine` (already cut from `main`).
**Goal:** Implement Milestones M0 + M1 of the score engine — the smallest slice
that produces a real, reproducible 0–10 ranked buy list with platform breakdowns.

---

## 0. Background (read this first)

AlphaDesk is a Python multi-agent investment pipeline that emits a daily
Telegram/email brief. The existing pipeline (`src/advisor/main.py`,
`src/advisor/run_orchestrator.py`) is **left completely untouched** by this
task. The score engine is a **new layer** that runs as a new mode.

An end-to-end audit (`docs/flow_audit.md`) found that the pipeline's config
weights are never actually used (F3, F5), signal degradation is silent (F11),
and scoring is non-deterministic. The score engine fixes all three by
construction.

---

## 1. What to build (M0 + M1)

### M0 — Scaffold & contracts
Create the `src/score_engine/` package with the data contracts that every
later milestone bolts onto. No logic yet beyond weight loading.

### M1 — Deterministic core
Implement the aggregator (weighted, breadth-gated, 0–10, stable sort), snapshot
persistence, and two sensors (earnings + Reddit) as thin adapters over the
existing agents. Ship `test_score_repeatability` and `test_breadth_gate`.

**Demoable outcome:** `python score.py --top 10` prints a ranked list of tickers
with 0–10 scores and a per-platform breakdown, reproducible on a fixed snapshot.

---

## 2. Repository layout (existing, do not modify)

```
alpha-desk/
  config/
    advisor.yaml          ← holds conviction_weights, evidence_weighting, strategy params
    subreddits.yaml       ← list of subreddits for Reddit sensor
  src/
    advisor/
      earnings_analyzer.py   ← analyze_earnings_call(), _analyze_earnings_with_llm()
      memory.py              ← SQLite persistence layer (advisor_memory.db)
      run_orchestrator.py    ← RunOrchestrator.execute(run_type) — ADD "score" mode here
    street_ear/
      analyzer.py            ← analyze_reddit_posts(posts, tickers) → dict
      reddit_fetcher.py      ← fetch_posts() → list[dict]
    shared/
      agent_bus.py           ← SQLite pub/sub for inter-agent signals
      cost_tracker.py        ← set_run_context(), record_usage(), check_budget()
      config_loader.py       ← load_config(name) → dict
      schemas.py             ← BASE_WEIGHTS dict (evidence weighting seed)
  tests/                     ← existing tests (don't break them)
  run_daily.py               ← entry point for Cloud Run — add --run-type=score support
  requirements.txt           ← add nothing new; all imports are already present
  docs/
    end_to_end_plan.md       ← master roadmap
    score_engine_plan.md     ← component-level detail
    flow_audit.md            ← audit findings (read-only reference)
```

---

## 3. New files to create

```
src/score_engine/
  __init__.py
  signals.py        # TickerSignal, TickerScore, Direction, RunRequest, RunResult
  weights.py        # load_weights() → dict  (reads config/advisor.yaml)
  sensors/
    __init__.py
    base.py         # Sensor Protocol, SensorRegistry, gather_all_votes()
    earnings.py     # EarningsSensor — adapter over src/advisor/earnings_analyzer
    reddit.py       # RedditSensor — adapter over src/street_ear
  aggregator.py     # score_tickers() — pure, deterministic
  snapshot.py       # save_snapshot(), load_snapshot() — uses score_engine.db
  engine.py         # run_scoring(RunRequest) → RunResult
tests/
  test_score_repeatability.py
  test_breadth_gate.py
score.py            # CLI: python score.py --top 10 [--snapshot <id>] [--dry-run]
```

---

## 4. Stable contracts (implement exactly as specified)

### `src/score_engine/signals.py`

```python
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

class Direction(Enum):
    BULL   =  1
    NEUTRAL = 0
    BEAR   = -1

@dataclass(frozen=True)
class TickerSignal:
    ticker:     str
    sensor:     str        # "earnings" | "reddit" | "news" | ...
    direction:  Direction
    strength:   float      # 0..1 — magnitude within this platform
    confidence: float      # 0..1 — data quality / sample size
    evidence:   str        # one-liner for the report
    as_of:      str        # ISO date string

@dataclass
class TickerScore:
    ticker:               str
    score:                float          # 0..10
    platforms_reporting:  list[str]
    platforms_failed:     list[str]
    breakdown:            list[dict]    # per-sensor: {sensor, direction, contribution, evidence}

@dataclass
class RunRequest:
    mode:             str = "score"
    depth:            str = "standard"   # "quick" | "standard" | "deep"
    top_n:            int = 10
    sensors:          list[str] | str = "auto"   # list of sensor names OR "auto"
    snapshot_id:      Optional[str] = None        # re-score an existing snapshot
    weights_version:  Optional[str] = None        # pin a weights version

@dataclass
class RunResult:
    top:              list[TickerScore]
    snapshot_id:      str
    weights_version:  str
    diagnostics:      dict   # sensor health, timing, cost
```

### `src/score_engine/sensors/base.py`

```python
from __future__ import annotations
from typing import Protocol, runtime_checkable
from src.score_engine.signals import TickerSignal

@runtime_checkable
class Sensor(Protocol):
    name:       str
    weight_key: str    # key into the weights dict

    async def vote(self, tickers: list[str], ctx: dict) -> list[TickerSignal]:
        ...

class SensorRegistry:
    def __init__(self):
        self._sensors: dict[str, Sensor] = {}

    def register(self, sensor: Sensor) -> None:
        self._sensors[sensor.name] = sensor

    def get(self, name: str) -> Sensor | None:
        return self._sensors.get(name)

    def all(self) -> list[Sensor]:
        return list(self._sensors.values())

REGISTRY = SensorRegistry()

async def gather_all_votes(
    sensors: list[Sensor],
    tickers: list[str],
    ctx: dict,
) -> tuple[list[TickerSignal], dict[str, str]]:
    """Run all sensors in parallel. Returns (signals, failed_sensors).
    
    failed_sensors maps sensor_name → error_string.
    A failing sensor is recorded and skipped — never raises.
    """
    import asyncio
    results: list[TickerSignal] = []
    failed: dict[str, str] = {}
    
    async def _run_one(sensor: Sensor):
        try:
            votes = await sensor.vote(tickers, ctx)
            results.extend(votes)
        except Exception as exc:
            failed[sensor.name] = str(exc)
    
    await asyncio.gather(*[_run_one(s) for s in sensors], return_exceptions=False)
    return results, failed
```

### `src/score_engine/aggregator.py`

```python
from __future__ import annotations
from src.score_engine.signals import TickerSignal, TickerScore, Direction

# Open decisions (settled here):
BREADTH_MIN = 2          # minimum platforms for a name to reach score >= 7.0
TOP_TIER_MIN = 3         # platforms required to reach 8–10 band
SCORE_SCALE = 10.0

def score_tickers(
    signals: list[TickerSignal],
    weights: dict[str, float],
    missing_sensors: list[str],
) -> list[TickerScore]:
    """Pure, deterministic scoring. Same inputs → identical output.
    
    Algorithm:
      1. One vote per (ticker, sensor) — deduplicate by keeping last if dupes exist.
      2. raw_score = Σ weight[sensor] × direction × strength × confidence
      3. Normalize raw_score to 0–10 via a sigmoid-like clamp (cap at SCORE_SCALE).
      4. Apply breadth gate: if bull_platform_count < BREADTH_MIN, cap score at 6.9.
         If bull_platform_count >= BREADTH_MIN but < TOP_TIER_MIN, cap at 7.9.
      5. Stable sort: (-score, ticker) so ties are deterministic.
    
    weights: dict mapping sensor name → float weight (default 1.0 if missing).
    missing_sensors: list of sensor names that failed this run (for diagnostics).
    """
    ...  # implement
```

**Important implementation notes:**
- `direction` is `Direction.BULL=1`, `Direction.NEUTRAL=0`, `Direction.BEAR=-1` — use `.value`
- Deduplicate `(ticker, sensor)` pairs **before** scoring — if two signals have the same ticker+sensor, keep the one with higher `confidence`
- Round final scores to 2 decimal places
- `breakdown` list on each `TickerScore` should have one entry per sensor that voted, containing: `{sensor, direction, strength, confidence, weight, contribution, evidence}`
- `platforms_reporting` = sensors that returned ≥1 signal for this ticker
- `platforms_failed` = `missing_sensors` list (same for every ticker in this run)

---

## 5. Weights loading (`src/score_engine/weights.py`)

Read source weights from `config/advisor.yaml`. The config has `conviction_weights`
(the intent was to weight different evidence types) but those keys
(`company_guidance`, `crowd_sentiment`, etc.) don't map to sensor names.

For M0/M1, create a **new `score_engine:` block** in `config/advisor.yaml` and
read from there. If the block is absent, fall back to sensible defaults.

Add to `config/advisor.yaml` at the bottom:

```yaml
# Score Engine — sensor weights and tier thresholds
score_engine:
  breadth_min: 2          # platforms required to score >= 7.0
  top_tier_min: 3         # platforms required to score 8–10
  top_n: 10
  weights:
    earnings:       1.8   # high-weight: guidance is signal-rich
    reddit:         0.8   # lower-weight: crowd sentiment, noisy
    news:           1.0
    superinvestor:  1.5   # 13F / smart money
    valuation:      1.4
    prediction:     1.2
    youtube:        0.7
    substack:       1.0
    x:              0.6
```

```python
# src/score_engine/weights.py
from __future__ import annotations
from src.shared.config_loader import load_config

DEFAULT_WEIGHTS = {
    "earnings":      1.8,
    "reddit":        0.8,
    "news":          1.0,
    "superinvestor": 1.5,
    "valuation":     1.4,
    "prediction":    1.2,
    "youtube":       0.7,
    "substack":      1.0,
    "x":             0.6,
}

WEIGHTS_VERSION = "v1-config"   # bump when weights change

def load_weights() -> dict[str, float]:
    """Load sensor weights from config/advisor.yaml score_engine block."""
    cfg = load_config("advisor")
    se = cfg.get("score_engine", {})
    return {**DEFAULT_WEIGHTS, **se.get("weights", {})}

def load_score_engine_config() -> dict:
    """Load full score_engine config block with defaults."""
    cfg = load_config("advisor")
    se = cfg.get("score_engine", {})
    return {
        "breadth_min":  se.get("breadth_min", 2),
        "top_tier_min": se.get("top_tier_min", 3),
        "top_n":        se.get("top_n", 10),
        "weights":      load_weights(),
    }
```

---

## 6. Snapshot persistence (`src/score_engine/snapshot.py`)

Use a separate SQLite DB `score_engine.db` (same directory pattern as
`advisor_memory.db` — read `ALPHADESK_DATA_DIR` env var, fall back to `"data"`).

```python
# src/score_engine/snapshot.py
from __future__ import annotations
import json
import os
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from src.score_engine.signals import TickerSignal, TickerScore

DB_PATH = Path(os.environ.get("ALPHADESK_DATA_DIR", "data")) / "score_engine.db"

def _get_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS snapshots (
            snapshot_id TEXT PRIMARY KEY,
            created_at  TEXT NOT NULL,
            weights_version TEXT NOT NULL,
            tickers     TEXT NOT NULL,   -- JSON list
            signals     TEXT NOT NULL,   -- JSON list of TickerSignal dicts
            scores      TEXT            -- JSON list of TickerScore dicts (null until scored)
        );
    """)
    conn.commit()
    return conn

def new_snapshot_id() -> str:
    return datetime.utcnow().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]

def save_snapshot(
    snapshot_id: str,
    tickers: list[str],
    signals: list[TickerSignal],
    weights_version: str,
    scores: list[TickerScore] | None = None,
) -> None:
    """Persist a snapshot. Call twice: once with signals (scores=None),
    then update with scores after aggregation."""
    ...

def load_snapshot(snapshot_id: str) -> dict | None:
    """Return the snapshot dict or None if not found.
    
    Returns: {snapshot_id, created_at, weights_version, tickers, signals, scores}
    """
    ...

def update_snapshot_scores(snapshot_id: str, scores: list[TickerScore]) -> None:
    """Write scores back to an existing snapshot row."""
    ...
```

---

## 7. Sensors

### 7a. Earnings sensor (`src/score_engine/sensors/earnings.py`)

Wrap `src/advisor/earnings_analyzer.py`. The existing function
`analyze_earnings_call(ticker)` returns a dict with keys like
`guidance_sentiment` (`positive`/`negative`/`neutral`/`mixed`),
`management_tone` (`confident`/`cautious`/`defensive`), `surprise_pct` (float),
`key_takeaways` (str).

```python
from __future__ import annotations
import asyncio
from src.score_engine.signals import TickerSignal, Direction
from src.score_engine.sensors.base import Sensor

class EarningsSensor:
    name = "earnings"
    weight_key = "earnings"

    async def vote(self, tickers: list[str], ctx: dict) -> list[TickerSignal]:
        signals = []
        for ticker in tickers:
            try:
                data = await asyncio.to_thread(self._fetch, ticker)
                if data:
                    signals.append(self._to_signal(ticker, data))
            except Exception:
                pass   # individual ticker failure → skip, not crash
        return signals

    def _fetch(self, ticker: str) -> dict | None:
        from src.advisor.earnings_analyzer import analyze_earnings_call
        return analyze_earnings_call(ticker)

    def _to_signal(self, ticker: str, data: dict) -> TickerSignal:
        guidance = data.get("guidance_sentiment", "neutral")
        tone = data.get("management_tone", "neutral")
        surprise = data.get("surprise_pct") or 0.0

        # Map to direction
        if guidance in ("positive",) or (surprise > 3):
            direction = Direction.BULL
        elif guidance in ("negative",) or (surprise < -3):
            direction = Direction.BEAR
        else:
            direction = Direction.NEUTRAL

        # strength: surprise magnitude drives it (capped at 1.0)
        strength = min(abs(surprise) / 10.0, 1.0) if surprise else 0.5

        # confidence: higher if both guidance and tone are unambiguous
        ambiguous = guidance in ("mixed", "neutral") or tone in ("cautious",)
        confidence = 0.6 if ambiguous else 0.85

        evidence = (data.get("key_takeaways") or
                    f"guidance={guidance}, tone={tone}, surprise={surprise:+.1f}%")[:120]
        return TickerSignal(
            ticker=ticker,
            sensor="earnings",
            direction=direction,
            strength=strength,
            confidence=confidence,
            evidence=evidence,
            as_of=data.get("as_of", ""),
        )
```

### 7b. Reddit sensor (`src/score_engine/sensors/reddit.py`)

Wrap `src/street_ear/analyzer.py`. The existing `analyze_reddit_posts(posts, tickers)`
returns a dict keyed by ticker with `sentiment` (float -1..+1), `mention_count` (int),
`bullish_posts` / `bearish_posts` lists, `confidence` (float 0..1).

```python
from __future__ import annotations
import asyncio
from src.score_engine.signals import TickerSignal, Direction
from src.score_engine.sensors.base import Sensor

class RedditSensor:
    name = "reddit"
    weight_key = "reddit"

    async def vote(self, tickers: list[str], ctx: dict) -> list[TickerSignal]:
        posts = await asyncio.to_thread(self._fetch_posts)
        analysis = await asyncio.to_thread(self._analyze, posts, tickers)
        signals = []
        for ticker, data in analysis.items():
            if ticker not in tickers:
                continue
            sig = self._to_signal(ticker, data)
            if sig:
                signals.append(sig)
        return signals

    def _fetch_posts(self) -> list[dict]:
        from src.street_ear.reddit_fetcher import fetch_posts
        return fetch_posts()

    def _analyze(self, posts: list[dict], tickers: list[str]) -> dict:
        from src.street_ear.analyzer import analyze_reddit_posts
        return analyze_reddit_posts(posts, tickers)

    def _to_signal(self, ticker: str, data: dict) -> TickerSignal | None:
        sentiment = data.get("sentiment", 0.0)
        mention_count = data.get("mention_count", 0)
        confidence = min(data.get("confidence", 0.5), 1.0)

        if mention_count < 2:
            return None   # too few mentions to be meaningful

        if sentiment > 0.2:
            direction = Direction.BULL
        elif sentiment < -0.2:
            direction = Direction.BEAR
        else:
            direction = Direction.NEUTRAL

        strength = min(abs(sentiment), 1.0)
        evidence = f"{mention_count} mentions, sentiment={sentiment:+.2f}"

        from datetime import date
        return TickerSignal(
            ticker=ticker,
            sensor="reddit",
            direction=direction,
            strength=strength,
            confidence=confidence,
            evidence=evidence,
            as_of=date.today().isoformat(),
        )
```

---

## 8. Engine (`src/score_engine/engine.py`)

```python
from __future__ import annotations
import asyncio
import time
from src.score_engine.signals import RunRequest, RunResult, TickerSignal
from src.score_engine.sensors.base import REGISTRY, gather_all_votes
from src.score_engine.sensors.earnings import EarningsSensor
from src.score_engine.sensors.reddit import RedditSensor
from src.score_engine.aggregator import score_tickers
from src.score_engine.snapshot import new_snapshot_id, save_snapshot, load_snapshot
from src.score_engine.weights import load_weights, load_score_engine_config, WEIGHTS_VERSION
from src.shared.config_loader import load_config

# Register built-in sensors (M1 has 2; M2+ adds more)
REGISTRY.register(EarningsSensor())
REGISTRY.register(RedditSensor())


def _get_tickers() -> list[str]:
    """Get the list of tickers to score from advisor.yaml holdings."""
    cfg = load_config("advisor")
    holdings = cfg.get("holdings", [])
    return [h["ticker"] for h in holdings]


async def run_scoring(req: RunRequest) -> RunResult:
    """Main entry point: gather → snapshot → aggregate → rank → return."""
    started = time.monotonic()
    se_cfg = load_score_engine_config()
    weights = load_weights()

    # Re-score an existing snapshot if requested
    if req.snapshot_id:
        snap = load_snapshot(req.snapshot_id)
        if snap is None:
            raise ValueError(f"Snapshot {req.snapshot_id!r} not found")
        signals = [TickerSignal(**s) for s in snap["signals"]]
        tickers = snap["tickers"]
        missing = []
    else:
        # Determine which sensors to run
        tickers = _get_tickers()
        if req.sensors == "auto":
            sensors = REGISTRY.all()
        else:
            sensors = [s for s in REGISTRY.all() if s.name in req.sensors]

        ctx = {"depth": req.depth}
        signals, failed = await gather_all_votes(sensors, tickers, ctx)
        missing = list(failed.keys())

        # Persist snapshot
        snapshot_id = new_snapshot_id()
        save_snapshot(snapshot_id, tickers, signals, WEIGHTS_VERSION)
    
    snapshot_id = req.snapshot_id or snapshot_id

    # Score (pure, deterministic)
    scores = score_tickers(signals, weights, missing)

    # Save scores back to snapshot
    save_snapshot(snapshot_id, tickers, signals, WEIGHTS_VERSION, scores)

    # Stable rank and take top-N
    ranked = sorted(scores, key=lambda s: (-s.score, s.ticker))
    top = ranked[:req.top_n]

    elapsed = round(time.monotonic() - started, 2)
    return RunResult(
        top=top,
        snapshot_id=snapshot_id,
        weights_version=WEIGHTS_VERSION,
        diagnostics={
            "elapsed_s": elapsed,
            "signals_collected": len(signals),
            "sensors_ok": [s.name for s in REGISTRY.all() if s.name not in missing],
            "sensors_failed": missing,
            "tickers_scored": len(scores),
        },
    )
```

---

## 9. CLI entry point (`score.py` in repo root)

```python
#!/usr/bin/env python3
"""AlphaDesk score engine CLI.

Usage:
  python score.py --top 10
  python score.py --top 10 --snapshot 20260623_070000_abc123
  python score.py --top 10 --dry-run    (uses synthetic signals, no API calls)
"""
from __future__ import annotations

import argparse
import asyncio
import sys

def main():
    parser = argparse.ArgumentParser(description="AlphaDesk score engine")
    parser.add_argument("--top", type=int, default=10, help="Number of top names to show")
    parser.add_argument("--snapshot", type=str, default=None, help="Re-score an existing snapshot ID")
    parser.add_argument("--dry-run", action="store_true", help="Use synthetic signals (no API calls)")
    parser.add_argument("--depth", choices=["quick", "standard", "deep"], default="standard")
    args = parser.parse_args()

    if args.dry_run:
        _run_dry(args.top)
        return

    from src.score_engine.signals import RunRequest
    from src.score_engine.engine import run_scoring

    req = RunRequest(
        top_n=args.top,
        snapshot_id=args.snapshot,
        depth=args.depth,
    )
    result = asyncio.run(run_scoring(req))
    _print_result(result)


def _print_result(result):
    from src.score_engine.signals import Direction
    print(f"\n{'='*60}")
    print(f"  AlphaDesk Top Buys  (snapshot: {result.snapshot_id})")
    print(f"  weights: {result.weights_version}  |  {result.diagnostics['elapsed_s']}s")
    print(f"  platforms: {', '.join(result.diagnostics['sensors_ok'])}  |  "
          f"failed: {result.diagnostics['sensors_failed'] or 'none'}")
    print(f"{'='*60}")
    for i, ts in enumerate(result.top, 1):
        bar = "█" * int(ts.score) + "░" * (10 - int(ts.score))
        platforms = ", ".join(ts.platforms_reporting) or "—"
        print(f"  {i:>2}. {ts.ticker:<6} {ts.score:>5.2f}/10  [{bar}]  {platforms}")
        for b in ts.breakdown:
            if b.get("direction") and b["direction"] != "NEUTRAL":
                arrow = "▲" if b["direction"] == "BULL" else "▼"
                print(f"        {arrow} {b['sensor']:<14} +{b['contribution']:.2f}  {b['evidence']}")
    print()


def _run_dry(top_n: int):
    """Synthetic signals — no API calls. Proves the aggregator works."""
    from src.score_engine.signals import TickerSignal, Direction, RunResult, TickerScore
    from src.score_engine.aggregator import score_tickers
    from src.score_engine.snapshot import new_snapshot_id
    from src.score_engine.weights import load_weights, WEIGHTS_VERSION

    tickers = ["NVDA", "AMZN", "GOOG", "META", "AVGO", "VRT", "MRVL", "NFLX", "MSFT"]
    signals = [
        TickerSignal("NVDA", "earnings", Direction.BULL, 0.9, 0.9, "Strong guidance", "2026-06-23"),
        TickerSignal("NVDA", "reddit",   Direction.BULL, 0.8, 0.7, "25 mentions, +0.82", "2026-06-23"),
        TickerSignal("AMZN", "earnings", Direction.BULL, 0.7, 0.85,"AWS re-accel", "2026-06-23"),
        TickerSignal("AMZN", "reddit",   Direction.BULL, 0.5, 0.6, "12 mentions, +0.55", "2026-06-23"),
        TickerSignal("GOOG", "earnings", Direction.BULL, 0.6, 0.8, "Cloud margin up", "2026-06-23"),
        TickerSignal("META", "reddit",   Direction.BULL, 0.4, 0.55,"8 mentions", "2026-06-23"),
        TickerSignal("AVGO", "earnings", Direction.NEUTRAL, 0.3, 0.7,"Mixed signals", "2026-06-23"),
        TickerSignal("MRVL", "earnings", Direction.BEAR,  0.5, 0.7, "Miss + lower guide", "2026-06-23"),
    ]
    weights = load_weights()
    scores = score_tickers(signals, weights, missing_sensors=[])
    ranked = sorted(scores, key=lambda s: (-s.score, s.ticker))[:top_n]

    result = RunResult(
        top=ranked,
        snapshot_id="DRY_" + new_snapshot_id(),
        weights_version=WEIGHTS_VERSION + "_dry",
        diagnostics={"elapsed_s": 0.0, "signals_collected": len(signals),
                     "sensors_ok": ["earnings","reddit"], "sensors_failed": [],
                     "tickers_scored": len(scores)},
    )
    _print_result(result)


if __name__ == "__main__":
    main()
```

---

## 10. Tests

### `tests/test_score_repeatability.py`

```python
"""Repeatability guarantee: same snapshot → byte-identical scores and order."""
import pytest
from src.score_engine.signals import TickerSignal, Direction
from src.score_engine.aggregator import score_tickers
from src.score_engine.weights import load_weights

SIGNALS = [
    TickerSignal("NVDA", "earnings", Direction.BULL,    0.9, 0.9, "Strong guide", "2026-06-23"),
    TickerSignal("NVDA", "reddit",   Direction.BULL,    0.8, 0.7, "25 mentions", "2026-06-23"),
    TickerSignal("AMZN", "earnings", Direction.BULL,    0.7, 0.8, "AWS", "2026-06-23"),
    TickerSignal("AMZN", "reddit",   Direction.NEUTRAL, 0.3, 0.5, "mixed", "2026-06-23"),
    TickerSignal("GOOG", "reddit",   Direction.BEAR,    0.6, 0.6, "negative", "2026-06-23"),
    TickerSignal("META", "earnings", Direction.BULL,    0.5, 0.7, "ad revenue", "2026-06-23"),
]

def test_identical_scores_same_inputs():
    weights = load_weights()
    run1 = score_tickers(SIGNALS, weights, missing_sensors=[])
    run2 = score_tickers(SIGNALS, weights, missing_sensors=[])
    assert [(s.ticker, s.score) for s in run1] == [(s.ticker, s.score) for s in run2]

def test_stable_sort_tie_breaking():
    """Tickers with identical scores must always sort alphabetically."""
    weights = {"earnings": 1.0, "reddit": 1.0}
    # Two tickers with identical signals
    signals = [
        TickerSignal("ZZZ", "earnings", Direction.BULL, 0.5, 0.5, "x", "2026-06-23"),
        TickerSignal("AAA", "earnings", Direction.BULL, 0.5, 0.5, "x", "2026-06-23"),
    ]
    result = score_tickers(signals, weights, [])
    assert result[0].ticker == "AAA"
    assert result[1].ticker == "ZZZ"

def test_snapshot_rescore_identical(tmp_path, monkeypatch):
    """Re-scoring from the same snapshot produces the same result."""
    import os
    monkeypatch.setenv("ALPHADESK_DATA_DIR", str(tmp_path))
    # Re-import snapshot after env var is set
    import importlib
    import src.score_engine.snapshot as snap_mod
    importlib.reload(snap_mod)

    from src.score_engine.snapshot import save_snapshot, load_snapshot
    from src.score_engine.weights import WEIGHTS_VERSION

    weights = load_weights()
    scores1 = score_tickers(SIGNALS, weights, [])
    
    snap_id = "test_snap_001"
    save_snapshot(snap_id, ["NVDA","AMZN","GOOG","META"], SIGNALS, WEIGHTS_VERSION, scores1)

    snap = load_snapshot(snap_id)
    assert snap is not None
    reloaded_signals = [TickerSignal(**s) for s in snap["signals"]]
    scores2 = score_tickers(reloaded_signals, weights, [])

    assert [(s.ticker, s.score) for s in scores1] == [(s.ticker, s.score) for s in scores2]
```

### `tests/test_breadth_gate.py`

```python
"""Breadth gate: a single loud platform cannot reach the top tier."""
from src.score_engine.signals import TickerSignal, Direction
from src.score_engine.aggregator import score_tickers, BREADTH_MIN, TOP_TIER_MIN

def test_single_platform_capped_below_7():
    """One platform (even maximal strength) → score < 7.0."""
    signals = [
        TickerSignal("NVDA", "earnings", Direction.BULL, 1.0, 1.0, "perfect", "2026-06-23"),
    ]
    weights = {"earnings": 2.0}
    result = score_tickers(signals, weights, [])
    nvda = next(s for s in result if s.ticker == "NVDA")
    assert nvda.score < 7.0, f"Expected <7.0 with 1 platform, got {nvda.score}"

def test_two_platforms_can_reach_7():
    """BREADTH_MIN (2) agreeing platforms → can score >= 7.0."""
    signals = [
        TickerSignal("NVDA", "earnings", Direction.BULL, 0.9, 0.9, "strong guide", "2026-06-23"),
        TickerSignal("NVDA", "reddit",   Direction.BULL, 0.8, 0.8, "high mentions", "2026-06-23"),
    ]
    weights = {"earnings": 1.8, "reddit": 0.8}
    result = score_tickers(signals, weights, [])
    nvda = next(s for s in result if s.ticker == "NVDA")
    assert nvda.score >= 7.0, f"Expected >=7.0 with {BREADTH_MIN} platforms, got {nvda.score}"

def test_top_tier_requires_three_platforms():
    """Scores 8–10 require TOP_TIER_MIN (3) platforms."""
    # Two platforms: should stay below 8.0
    two_platform = [
        TickerSignal("NVDA", "earnings", Direction.BULL, 1.0, 1.0, "guide", "2026-06-23"),
        TickerSignal("NVDA", "reddit",   Direction.BULL, 1.0, 1.0, "reddit", "2026-06-23"),
    ]
    # Three platforms: eligible for 8+
    three_platform = two_platform + [
        TickerSignal("NVDA", "news", Direction.BULL, 1.0, 1.0, "news", "2026-06-23"),
    ]
    weights = {"earnings": 2.0, "reddit": 1.0, "news": 1.0}

    r2 = score_tickers(two_platform, weights, [])
    r3 = score_tickers(three_platform, weights, [])

    nvda2 = next(s for s in r2 if s.ticker == "NVDA")
    nvda3 = next(s for s in r3 if s.ticker == "NVDA")

    assert nvda2.score < 8.0, f"2 platforms should not reach top tier, got {nvda2.score}"
    assert nvda3.score >= 8.0, f"3 strong platforms should reach top tier, got {nvda3.score}"

def test_bear_signal_lowers_score():
    """A BEAR signal subtracts from the score."""
    bull_only = [TickerSignal("AMZN", "earnings", Direction.BULL, 0.8, 0.8, "ok", "2026-06-23")]
    mixed = bull_only + [TickerSignal("AMZN", "reddit", Direction.BEAR, 0.8, 0.8, "neg", "2026-06-23")]
    weights = {"earnings": 1.0, "reddit": 1.0}

    r_bull = score_tickers(bull_only, weights, [])
    r_mixed = score_tickers(mixed, weights, [])

    amzn_bull  = next(s for s in r_bull  if s.ticker == "AMZN")
    amzn_mixed = next(s for s in r_mixed if s.ticker == "AMZN")
    assert amzn_mixed.score < amzn_bull.score
```

---

## 11. Wire into RunOrchestrator

In `src/advisor/run_orchestrator.py`, add the `"score"` mode to `execute()`.
Find the block:

```python
if profile.run_type == "morning_full":
    from src.advisor.main import _run_pipeline
    return await _run_pipeline(profile)
if profile.run_type == "evening_wrap":
    return await self._execute_evening_wrap(profile)
return await self._execute_weekend_review(profile)
```

Add **before** the final `return`:

```python
if profile.run_type == "score":
    from src.score_engine.signals import RunRequest
    from src.score_engine.engine import run_scoring
    result = await run_scoring(RunRequest(top_n=profile.top_n if hasattr(profile, "top_n") else 10))
    return {"score_result": result, "run_type": "score", "run_id": profile.run_id}
```

And in `run_daily.py`, the `--run-type` argument already accepts free strings —
add `"score"` to the help text choices. No other changes needed.

---

## 12. Add `score_engine:` block to `config/advisor.yaml`

Append at the very end of `config/advisor.yaml`:

```yaml
# Score Engine — sensor weights and tier thresholds
score_engine:
  breadth_min: 2
  top_tier_min: 3
  top_n: 10
  weights:
    earnings:       1.8
    reddit:         0.8
    news:           1.0
    superinvestor:  1.5
    valuation:      1.4
    prediction:     1.2
    youtube:        0.7
    substack:       1.0
    x:              0.6
```

---

## 13. Add `scratch/` to `.gitignore`

The audit harness in `scratch/` should not ship. Add to `.gitignore`:

```
scratch/
```

---

## 14. Verification checklist (run these after implementation)

```bash
# 1. Dry run (no API keys needed)
python score.py --top 10 --dry-run

# 2. Run it twice, confirm output is identical
python score.py --top 10 --dry-run > /tmp/run1.txt
python score.py --top 10 --dry-run > /tmp/run2.txt
diff /tmp/run1.txt /tmp/run2.txt   # must be empty

# 3. Tests
python -m pytest tests/test_score_repeatability.py tests/test_breadth_gate.py -v

# 4. Re-score a snapshot (grab the ID from a previous run)
python score.py --snapshot <id from run 1>
```

---

## 15. Hard constraints (do not violate)

1. **Do NOT modify** any file under `src/advisor/`, `src/alpha_scout/`,
   `src/street_ear/`, `src/shared/`, etc. **except** `src/advisor/run_orchestrator.py`
   (one small addition in §11 above) and `config/advisor.yaml` (append §12).
2. **No new dependencies** — everything needed is already in `requirements.txt`.
3. **LLMs are banned from the scoring/ranking path.** Only sensors may call LLMs
   (at temp 0, for extraction), and only the narrator (M4) writes prose.
4. **The aggregator must be a pure function** — no I/O, no globals, same inputs
   → same outputs always.
5. **`score.py --dry-run` must work without any API keys** — it uses synthetic
   signals and exercises the full aggregator + output path.

---

## 16. Open decisions already settled

| Decision | Value chosen |
|---|---|
| `breadth_min` K | **2** (two platforms to cross 7.0; 3 for top tier 8–10) |
| Probation weight | 0.5 (half the normal weight; set in M8) |
| Credit attribution | Directional hit-rate (Brier refinement deferred to M8) |
| Score normalization | `raw / max_possible * 10`, capped per breadth tier |
| Tie-breaking | Stable sort: `(-score, ticker)` alphabetical on ticker |
| Snapshot DB | `score_engine.db` separate from `advisor_memory.db` |

---

## 17. Files summary (what to create vs modify)

| Action | File |
|---|---|
| **CREATE** | `src/score_engine/__init__.py` |
| **CREATE** | `src/score_engine/signals.py` |
| **CREATE** | `src/score_engine/weights.py` |
| **CREATE** | `src/score_engine/sensors/__init__.py` |
| **CREATE** | `src/score_engine/sensors/base.py` |
| **CREATE** | `src/score_engine/sensors/earnings.py` |
| **CREATE** | `src/score_engine/sensors/reddit.py` |
| **CREATE** | `src/score_engine/aggregator.py` |
| **CREATE** | `src/score_engine/snapshot.py` |
| **CREATE** | `src/score_engine/engine.py` |
| **CREATE** | `score.py` |
| **CREATE** | `tests/test_score_repeatability.py` |
| **CREATE** | `tests/test_breadth_gate.py` |
| **MODIFY** | `config/advisor.yaml` — append `score_engine:` block |
| **MODIFY** | `src/advisor/run_orchestrator.py` — add `"score"` mode (4 lines) |
| **MODIFY** | `.gitignore` — add `scratch/` |
| **DO NOT TOUCH** | Everything else |
