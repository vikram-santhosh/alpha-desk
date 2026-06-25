"""Score engine entry point: gather → snapshot → aggregate → rank → return."""
from __future__ import annotations

import time

from src.score_engine.aggregator import score_tickers
from src.score_engine.sensors.base import REGISTRY, gather_all_votes
from src.score_engine.sensors.earnings import EarningsSensor
from src.score_engine.sensors.news import NewsSensor
from src.score_engine.sensors.prediction import PredictionSensor
from src.score_engine.sensors.reddit import RedditSensor
from src.score_engine.sensors.substack import SubstackSensor
from src.score_engine.sensors.superinvestor import SuperinvestorSensor
from src.score_engine.sensors.valuation import ValuationSensor
from src.score_engine.sensors.youtube import YouTubeSensor
from src.score_engine.signals import RunRequest, RunResult, TickerSignal
from src.score_engine.snapshot import load_snapshot, new_snapshot_id, save_snapshot
from src.score_engine.weights import WEIGHTS_VERSION, load_score_engine_config, load_weights

# Register built-in sensors (M1: earnings + reddit; M2 adds the rest)
# Built-in sensors (M2: full multi-platform corroboration).
REGISTRY.register(EarningsSensor())
REGISTRY.register(RedditSensor())
REGISTRY.register(SuperinvestorSensor())
REGISTRY.register(ValuationSensor())
REGISTRY.register(NewsSensor())
REGISTRY.register(PredictionSensor())
REGISTRY.register(YouTubeSensor())
REGISTRY.register(SubstackSensor())


def _get_tickers() -> list[str]:
    from src.shared.config_loader import load_config
    cfg = load_config("advisor")
    return [h["ticker"] for h in cfg.get("holdings", [])]


async def run_scoring(req: RunRequest) -> RunResult:
    """Full scoring pipeline: gather → snapshot → aggregate → rank."""
    started = time.monotonic()
    se_cfg  = load_score_engine_config()
    weights = load_weights()

    ran_sensor_names: set[str] | None = None
    if req.snapshot_id:
        # Re-score an existing frozen snapshot
        snap = load_snapshot(req.snapshot_id)
        if snap is None:
            raise ValueError(f"Snapshot {req.snapshot_id!r} not found")
        signals:      list[TickerSignal] = snap["signals"]
        tickers:      list[str]          = snap["tickers"]
        missing:      list[str]          = []
        snapshot_id:  str                = req.snapshot_id
    else:
        tickers = _get_tickers()

        if req.sensors == "auto":
            sensors = REGISTRY.all()
        else:
            sensors = [s for s in REGISTRY.all() if s.name in req.sensors]

        ctx = {"depth": req.depth}
        signals, failed = await gather_all_votes(sensors, tickers, ctx)
        missing = list(failed.keys())
        ran_sensor_names = {s.name for s in sensors}

        snapshot_id = new_snapshot_id()
        save_snapshot(snapshot_id, tickers, signals, WEIGHTS_VERSION)

    # Pure deterministic scoring
    scores = score_tickers(signals, weights, missing)

    # Persist scores back onto the snapshot
    save_snapshot(snapshot_id, tickers, signals, WEIGHTS_VERSION, scores)

    # Stable rank, take top-N
    top_n  = req.top_n or se_cfg["top_n"]
    ranked = sorted(scores, key=lambda s: (-s.score, s.ticker))
    top    = ranked[:top_n]

    elapsed = round(time.monotonic() - started, 2)

    # Honest degradation: distinguish sensors that produced signals (ok) from
    # those that ran without error but emitted nothing (empty) and those that
    # raised (failed). A dead platform must never hide behind "ok".
    reporting = sorted({sig.sensor for sig in signals})
    if ran_sensor_names is not None:
        empty = sorted(ran_sensor_names - set(reporting) - set(missing))
    else:
        empty = []   # rescore path: original sensor set is unknown

    return RunResult(
        top=top,
        snapshot_id=snapshot_id,
        weights_version=WEIGHTS_VERSION,
        diagnostics={
            "elapsed_s":         elapsed,
            "signals_collected": len(signals),
            "sensors_ok":        reporting,
            "sensors_empty":     empty,
            "sensors_failed":    missing,
            "tickers_scored":    len(scores),
        },
    )
