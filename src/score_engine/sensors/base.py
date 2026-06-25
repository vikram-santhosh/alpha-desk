"""Sensor Protocol, registry, and parallel gather with health tracking."""
from __future__ import annotations

import asyncio
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
    """Run all sensors in parallel.

    Returns (signals, failed) where failed maps sensor_name → error string.
    A failing sensor is recorded and skipped — never propagates an exception.
    """
    results: list[TickerSignal] = []
    failed: dict[str, str] = {}
    lock = asyncio.Lock()

    async def _run_one(sensor: Sensor) -> None:
        try:
            votes = await sensor.vote(tickers, ctx)
            async with lock:
                results.extend(votes)
        except Exception as exc:
            async with lock:
                failed[sensor.name] = str(exc)

    await asyncio.gather(*[_run_one(s) for s in sensors])
    return results, failed
