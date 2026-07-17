"""Core data contracts for the score engine.

These dataclasses freeze in M0–M1 and all later milestones bolt onto them.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class Direction(Enum):
    BULL    =  1
    NEUTRAL =  0
    BEAR    = -1


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
    ticker:              str
    score:               float           # 0..10
    platforms_reporting: list[str]
    platforms_failed:    list[str]
    breakdown:           list[dict]      # per-sensor {sensor, direction, contribution, evidence}


@dataclass
class RunRequest:
    mode:            str = "score"
    depth:           str = "standard"    # "quick" | "standard" | "deep"
    top_n:           int = 10
    sensors:         list[str] | str = "auto"   # list of sensor names OR "auto"
    snapshot_id:     Optional[str] = None        # re-score an existing snapshot
    weights_version: Optional[str] = None        # pin a weights version
    tickers:         Optional[list[str]] = None  # override the default ticker universe


@dataclass
class RunResult:
    top:             list[TickerScore]
    snapshot_id:     str
    weights_version: str
    diagnostics:     dict   # sensor health, timing, cost
