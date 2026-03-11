from __future__ import annotations

import sys

import run_daily


def test_run_daily_evening_wrap_cli(monkeypatch) -> None:
    called: dict[str, str] = {}

    async def fake_run(*, run_type: str = "auto"):
        called["run_type"] = run_type
        return {
            "formatted": "evening",
            "signals": [{"id": 1}],
            "run_profile": {"run_type": run_type, "run_id": "2026-03-10T19:00"},
            "stats": {"total_time_s": 1.2, "run_cost": 0.2, "daily_cost": 1.5, "holdings_count": 3},
        }

    monkeypatch.setattr(run_daily, "_sync_down", lambda: None)
    monkeypatch.setattr(run_daily, "_sync_up", lambda: None)
    monkeypatch.setattr("src.advisor.main.run", fake_run)
    monkeypatch.setattr(sys, "argv", ["run_daily.py", "--run-type=evening_wrap"])

    run_daily.main()

    assert called["run_type"] == "evening_wrap"


def test_run_daily_weekend_cli(monkeypatch) -> None:
    called: dict[str, str] = {}

    async def fake_run(*, run_type: str = "auto"):
        called["run_type"] = run_type
        return {
            "formatted": "weekend",
            "signals": [],
            "run_profile": {"run_type": run_type, "run_id": "2026-03-14T10:00"},
            "stats": {"total_time_s": 0.8, "run_cost": 0.1, "daily_cost": 0.1, "holdings_count": 3},
        }

    monkeypatch.setattr(run_daily, "_sync_down", lambda: None)
    monkeypatch.setattr(run_daily, "_sync_up", lambda: None)
    monkeypatch.setattr("src.advisor.main.run", fake_run)
    monkeypatch.setattr(sys, "argv", ["run_daily.py", "--run-type=weekend"])

    run_daily.main()

    assert called["run_type"] == "weekend"
