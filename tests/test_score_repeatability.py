"""Repeatability guarantee: same snapshot → byte-identical scores and order."""
from __future__ import annotations

import importlib

import pytest

from src.score_engine.aggregator import score_tickers
from src.score_engine.signals import Direction, TickerSignal
from src.score_engine.weights import WEIGHTS_VERSION, load_weights

SIGNALS = [
    TickerSignal("NVDA", "earnings", Direction.BULL,    0.9, 0.9, "Strong guide",    "2026-06-23"),
    TickerSignal("NVDA", "reddit",   Direction.BULL,    0.8, 0.7, "25 mentions",     "2026-06-23"),
    TickerSignal("AMZN", "earnings", Direction.BULL,    0.7, 0.8, "AWS",             "2026-06-23"),
    TickerSignal("AMZN", "reddit",   Direction.NEUTRAL, 0.3, 0.5, "mixed",           "2026-06-23"),
    TickerSignal("GOOG", "reddit",   Direction.BEAR,    0.6, 0.6, "negative",        "2026-06-23"),
    TickerSignal("META", "earnings", Direction.BULL,    0.5, 0.7, "ad revenue up",   "2026-06-23"),
]


def test_identical_scores_same_inputs():
    """Running aggregator twice on same signals produces identical results."""
    weights = load_weights()
    run1 = score_tickers(SIGNALS, weights, missing_sensors=[])
    run2 = score_tickers(SIGNALS, weights, missing_sensors=[])
    assert [(s.ticker, s.score) for s in run1] == [(s.ticker, s.score) for s in run2]


def test_identical_order_same_inputs():
    """Order is deterministic, not just scores."""
    weights = load_weights()
    run1 = score_tickers(SIGNALS, weights, missing_sensors=[])
    run2 = score_tickers(SIGNALS, weights, missing_sensors=[])
    assert [s.ticker for s in run1] == [s.ticker for s in run2]


def test_stable_sort_tie_breaking():
    """Tickers with identical scores sort alphabetically."""
    weights = {"earnings": 1.0}
    signals = [
        TickerSignal("ZZZ", "earnings", Direction.BULL, 0.5, 0.5, "x", "2026-06-23"),
        TickerSignal("AAA", "earnings", Direction.BULL, 0.5, 0.5, "x", "2026-06-23"),
        TickerSignal("MMM", "earnings", Direction.BULL, 0.5, 0.5, "x", "2026-06-23"),
    ]
    result = score_tickers(signals, weights, [])
    tickers = [s.ticker for s in result]
    assert tickers == sorted(tickers), f"Expected alphabetical tie-break, got {tickers}"


def test_snapshot_rescore_identical(tmp_path, monkeypatch):
    """Re-scoring from a persisted snapshot reproduces the same scores."""
    monkeypatch.setenv("ALPHADESK_DATA_DIR", str(tmp_path))

    # Reload snapshot module so DB_PATH picks up the monkeypatched env var
    import src.score_engine.snapshot as snap_mod
    importlib.reload(snap_mod)

    from src.score_engine.snapshot import load_snapshot, save_snapshot

    weights = load_weights()
    scores1 = score_tickers(SIGNALS, weights, [])

    snap_id = "test_repeatability_001"
    snap_mod.save_snapshot(snap_id, ["NVDA", "AMZN", "GOOG", "META"], SIGNALS, WEIGHTS_VERSION, scores1)

    snap = snap_mod.load_snapshot(snap_id)
    assert snap is not None, "Snapshot not found after save"

    scores2 = score_tickers(snap["signals"], weights, [])
    assert [(s.ticker, s.score) for s in scores1] == [(s.ticker, s.score) for s in scores2]


def test_dedup_keeps_highest_confidence():
    """When two signals share (ticker, sensor), the higher-confidence one wins."""
    weights = {"earnings": 1.0}
    # Two earnings signals for NVDA — second has higher confidence
    signals = [
        TickerSignal("NVDA", "earnings", Direction.BULL, 0.5, 0.4, "low conf",  "2026-06-23"),
        TickerSignal("NVDA", "earnings", Direction.BULL, 0.8, 0.9, "high conf", "2026-06-23"),
    ]
    result = score_tickers(signals, weights, [])
    nvda = next(s for s in result if s.ticker == "NVDA")
    # Only one breakdown entry (dedup happened)
    assert len(nvda.breakdown) == 1
    assert nvda.breakdown[0]["confidence"] == 0.9
