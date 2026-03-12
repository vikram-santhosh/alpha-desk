from __future__ import annotations

import importlib
from datetime import datetime


def _reload_module(module_name: str, monkeypatch, data_dir):
    monkeypatch.setenv("ALPHADESK_DATA_DIR", str(data_dir))
    module = importlib.import_module(module_name)
    return importlib.reload(module)


def test_determine_run_profile_uses_schedule_and_auto_classification(monkeypatch):
    run_profile = importlib.import_module("src.advisor.run_profile")
    run_profile = importlib.reload(run_profile)

    monkeypatch.setattr(
        run_profile,
        "load_config",
        lambda name: {
            "schedule": {
                "market_days": [
                    {"time": "07:00", "run_type": "morning_full", "budget_usd": 11.0},
                    {"time": "19:00", "run_type": "evening_wrap", "budget_usd": 3.5},
                ],
                "weekends": [
                    {"time": "10:00", "run_type": "weekend", "budget_usd": 2.5},
                ],
            }
        },
    )
    monkeypatch.setattr(run_profile, "_hours_since_last_run", lambda now: 12.5)

    profile = run_profile.determine_run_profile(
        run_type="auto",
        now=datetime(2026, 3, 11, 19, 30),
    )

    assert profile.run_type == "evening_wrap"
    assert profile.run_id == "2026-03-11T19:00"
    assert profile.hours_since_last_run == 12.5
    assert profile.budget_usd == 3.5
    assert profile.report_format == "evening_summary"
    assert "delta_analyst" in profile.run_steps


def test_run_budget_context_is_enforced(monkeypatch, tmp_path):
    cost_tracker = _reload_module("src.shared.cost_tracker", monkeypatch, tmp_path)

    tokens = cost_tracker.set_run_context(run_id="2026-03-11T07:00", run_budget=0.001)
    try:
        cost_tracker.record_usage(
            "unit_test_agent",
            input_tokens=100_000,
            output_tokens=0,
            model="gemini-2.5-pro",
        )
        within_budget, spent, cap = cost_tracker.check_budget()
    finally:
        cost_tracker.reset_run_context(tokens)

    assert within_budget is False
    assert spent > cap
    assert cap == 0.001
    assert cost_tracker.get_run_cost("2026-03-11T07:00") == spent


def test_run_snapshots_persist_and_mirror_to_daily(monkeypatch, tmp_path):
    memory = _reload_module("src.advisor.memory", monkeypatch, tmp_path)

    snapshot = {"tickers": {"NVDA": {"price": 900.0}}}
    delta = {"summary": "Test delta"}
    memory.save_run_snapshot(
        run_id="2026-03-11T07:00",
        run_type="morning_full",
        date_str="2026-03-11",
        snapshot_data=snapshot,
        delta=delta,
        run_cost=1.23,
        run_duration=45.6,
        last_signal_id=17,
    )

    latest = memory.get_latest_run_snapshot()
    exact = memory.get_run_snapshot("2026-03-11T07:00")
    daily = memory.get_snapshot_for_date("2026-03-11")

    assert latest is not None
    assert latest["run_id"] == "2026-03-11T07:00"
    assert latest["run_cost_usd"] == 1.23
    assert latest["last_consumed_signal_id"] == 17
    assert latest["delta_from_previous"] == delta
    assert exact == latest
    assert daily == snapshot


def test_consume_since_returns_only_newer_signals(monkeypatch, tmp_path):
    agent_bus = _reload_module("src.shared.agent_bus", monkeypatch, tmp_path)

    first_id = agent_bus.publish("breaking_news", "news_desk", {"ticker": "NVDA"})
    agent_bus.publish("macro_event", "news_desk", {"ticker": "SPY"})
    agent_bus.publish("expert_thesis", "substack_ear", {"ticker": "AMZN"})

    newer = agent_bus.consume_since(first_id)
    remaining = agent_bus.consume(mark_consumed=False)

    assert [signal["id"] for signal in newer] == [first_id + 1, first_id + 2]
    assert [signal["id"] for signal in remaining] == [first_id]
