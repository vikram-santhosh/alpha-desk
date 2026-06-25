#!/usr/bin/env python3
"""AlphaDesk score engine CLI.

Usage:
  python score.py --top 10
  python score.py --top 10 --snapshot 20260623_070000_abc123
  python score.py --top 10 --dry-run    (synthetic signals, no API calls)
  python score.py --list-snapshots
"""
from __future__ import annotations

import argparse
import asyncio
import sys


def _print_result(result) -> None:
    print(f"\n{'='*62}")
    print(f"  AlphaDesk Top Buys  (snapshot: {result.snapshot_id})")
    print(f"  weights: {result.weights_version}  |  {result.diagnostics['elapsed_s']}s")
    ok  = ", ".join(result.diagnostics["sensors_ok"])  or "none"
    bad = ", ".join(result.diagnostics["sensors_failed"]) or "none"
    print(f"  platforms: {ok}  |  failed: {bad}")
    print(f"{'='*62}")
    for i, ts in enumerate(result.top, 1):
        bar = "█" * int(ts.score) + "░" * (10 - int(ts.score))
        plat = ", ".join(ts.platforms_reporting) or "—"
        print(f"  {i:>2}. {ts.ticker:<6}  {ts.score:>5.2f}/10  [{bar}]  {plat}")
        for b in ts.breakdown:
            if b.get("direction", "NEUTRAL") != "NEUTRAL":
                arrow = "▲" if b["direction"] == "BULL" else "▼"
                print(f"        {arrow} {b['sensor']:<14} contrib={b['contribution']:+.3f}  {b['evidence']}")
    print()


def _run_dry(top_n: int) -> None:
    """Synthetic signals — proves the aggregator with no API calls."""
    from src.score_engine.aggregator import score_tickers
    from src.score_engine.signals import Direction, RunResult, TickerScore, TickerSignal
    from src.score_engine.snapshot import new_snapshot_id
    from src.score_engine.weights import WEIGHTS_VERSION, load_weights
    import time

    started = time.monotonic()
    signals = [
        TickerSignal("NVDA", "earnings", Direction.BULL,    0.9, 0.9, "Strong guidance + upside surprise", "2026-06-23"),
        TickerSignal("NVDA", "reddit",   Direction.BULL,    0.8, 0.7, "25 mentions, avg_sentiment=+1.60",   "2026-06-23"),
        TickerSignal("AMZN", "earnings", Direction.BULL,    0.7, 0.85,"AWS re-acceleration, raised guide",  "2026-06-23"),
        TickerSignal("AMZN", "reddit",   Direction.BULL,    0.5, 0.6, "12 mentions, avg_sentiment=+1.00",   "2026-06-23"),
        TickerSignal("GOOG", "earnings", Direction.BULL,    0.6, 0.8, "Cloud margin inflection",            "2026-06-23"),
        TickerSignal("GOOG", "reddit",   Direction.NEUTRAL, 0.2, 0.5, "4 mentions, avg_sentiment=+0.10",    "2026-06-23"),
        TickerSignal("META", "reddit",   Direction.BULL,    0.4, 0.55,"8 mentions, avg_sentiment=+0.80",    "2026-06-23"),
        TickerSignal("AVGO", "earnings", Direction.NEUTRAL, 0.3, 0.7, "Maintained guide, mixed tone",       "2026-06-23"),
        TickerSignal("MSFT", "earnings", Direction.BULL,    0.65, 0.8,"Azure +33% YoY, Copilot attach",     "2026-06-23"),
        TickerSignal("MRVL", "earnings", Direction.BEAR,    0.5, 0.7, "Miss + lowered guidance",            "2026-06-23"),
        TickerSignal("NFLX", "reddit",   Direction.BULL,    0.6, 0.65,"15 mentions, avg_sentiment=+1.20",   "2026-06-23"),
        TickerSignal("VRT",  "earnings", Direction.BULL,    0.7, 0.75,"Power/cooling demand raised guide",  "2026-06-23"),
    ]
    weights = load_weights()
    scores  = score_tickers(signals, weights, missing_sensors=[])
    ranked  = sorted(scores, key=lambda s: (-s.score, s.ticker))[:top_n]

    result = RunResult(
        top=ranked,
        snapshot_id="DRY_" + new_snapshot_id(),
        weights_version=WEIGHTS_VERSION + "_dry",
        diagnostics={
            "elapsed_s":         round(time.monotonic() - started, 3),
            "signals_collected": len(signals),
            "sensors_ok":        ["earnings", "reddit"],
            "sensors_failed":    [],
            "tickers_scored":    len(scores),
        },
    )
    _print_result(result)


def main() -> None:
    parser = argparse.ArgumentParser(description="AlphaDesk score engine")
    parser.add_argument("--top",              type=int,  default=10)
    parser.add_argument("--snapshot",         type=str,  default=None, help="Re-score snapshot ID")
    parser.add_argument("--dry-run",          action="store_true",    help="Synthetic signals, no API calls")
    parser.add_argument("--depth",            choices=["quick","standard","deep"], default="standard")
    parser.add_argument("--list-snapshots",   action="store_true")
    args = parser.parse_args()

    if args.list_snapshots:
        from src.score_engine.snapshot import list_snapshots
        rows = list_snapshots()
        if not rows:
            print("No snapshots yet.")
            return
        print(f"\n{'snapshot_id':<30}  {'created_at':<24}  weights_version")
        for r in rows:
            print(f"  {r['snapshot_id']:<28}  {r['created_at']:<24}  {r['weights_version']}")
        print()
        return

    if args.dry_run:
        _run_dry(args.top)
        return

    from src.score_engine.engine import run_scoring
    from src.score_engine.signals import RunRequest

    req    = RunRequest(top_n=args.top, snapshot_id=args.snapshot, depth=args.depth)
    result = asyncio.run(run_scoring(req))
    _print_result(result)


if __name__ == "__main__":
    main()
