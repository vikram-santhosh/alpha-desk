from __future__ import annotations

import asyncio

from src.advisor.delta_engine import DeltaReport
from src.advisor.run_orchestrator import RunOrchestrator
from src.advisor.run_profile import RunProfile
from src.shared.context_manager import ContextBudget
from src.shared.prompt_loader import load_prompt


def test_context_budget_preserves_high_priority_sections() -> None:
    budget = ContextBudget(token_budget=40)
    budget.add_section("Low", "low " * 200, "substack")
    budget.add_section("High", "high " * 40, "mandate_breaches")

    rendered = budget.render()

    assert "High" in rendered
    assert "high" in rendered


def test_prompt_loader_uses_externalized_templates() -> None:
    prompt = load_prompt(
        "delta_analyst",
        morning_brief="Morning brief",
        delta_summary="Delta summary",
        holdings_context="Holdings",
        news_context="News",
        citations="[1] Source",
    )

    assert "Morning CIO brief" in prompt
    assert "Morning brief" in prompt
    assert "Delta summary" in prompt


def test_evening_wrap_execution(monkeypatch) -> None:
    profile = RunProfile(
        run_type="evening_wrap",
        run_id="2026-03-10T19:00",
        market_open=True,
        hours_since_last_run=12.0,
        run_steps={"news_desk_headlines", "market_data_prices", "delta_analyst"},
        report_format="evening_summary",
        budget_usd=3.0,
    )
    saved: dict[str, object] = {}

    monkeypatch.setattr("src.advisor.run_orchestrator.determine_run_profile", lambda run_type="auto": profile)
    monkeypatch.setattr(RunOrchestrator, "_load_config", lambda self: {"holdings": [{"ticker": "NVDA", "entry_price": 100.0, "shares": 1}]})
    monkeypatch.setattr(
        RunOrchestrator,
        "_load_memory",
        lambda self, config: {"holdings": [{"ticker": "NVDA", "entry_price": 100.0, "shares": 1}], "conviction_list": [], "moonshot_list": []},
    )
    monkeypatch.setattr("src.advisor.run_orchestrator.consume_since", lambda since_id, mark_consumed=False: [])
    monkeypatch.setattr("src.advisor.run_orchestrator.consume", lambda mark_consumed=False: [])
    monkeypatch.setattr("src.advisor.run_orchestrator.get_latest_signal_id", lambda: 7)

    async def fake_news_run(headlines_only: bool = False):
        assert headlines_only is True
        return {
            "top_articles": [
                {
                    "title": "NVDA closes higher on AI demand",
                    "summary": "Demand stayed firm through the close.",
                    "related_tickers": ["NVDA"],
                    "source": "Reuters",
                    "url": "https://example.com/nvda",
                    "published_at": "2026-03-10T18:00:00",
                }
            ]
        }

    monkeypatch.setattr("src.news_desk.main.run", fake_news_run)
    monkeypatch.setattr(
        "src.portfolio_analyst.price_fetcher.fetch_current_prices",
        lambda tickers: {"NVDA": {"price": 110.0, "change_pct": 1.5}},
    )
    monkeypatch.setattr(
        "src.advisor.holdings_monitor.monitor_holdings",
        lambda holdings, prices, fundamentals, signals, news_signals: [
            {
                "ticker": "NVDA",
                "price": 110.0,
                "change_pct": 1.5,
                "position_pct": 100.0,
                "thesis_status": "intact",
                "recent_trend": "up",
            }
        ],
    )
    monkeypatch.setattr(
        "src.advisor.delta_engine.build_snapshot",
        lambda **kwargs: {"tickers": {"NVDA": {"price": 110.0, "thesis_status": "intact"}}},
    )
    monkeypatch.setattr(
        "src.advisor.delta_engine.compute_deltas",
        lambda today, reference: DeltaReport(date="2026-03-10"),
    )
    monkeypatch.setattr(
        "src.advisor.delta_engine.generate_delta_summary",
        lambda report: "NVDA finished higher versus the morning run.",
    )
    monkeypatch.setattr(
        "src.advisor.memory.get_latest_run_snapshot",
        lambda run_type=None, date_str=None: {
            "snapshot_data": {"brief_text": "Morning brief", "tickers": {"NVDA": {"price": 100.0, "thesis_status": "intact"}}},
            "last_consumed_signal_id": 5,
        },
    )
    monkeypatch.setattr(
        "src.advisor.memory.save_run_snapshot",
        lambda **kwargs: saved.update(kwargs),
    )

    async def fake_delta_analyst(self, **kwargs):
        return {
            "raw_text": "1. Scorecard\nMorning calls held.\n2. What Changed\nNVDA finished higher.\n3. After-Hours / Tomorrow\nWatch CPI tomorrow.",
            "cost_usd": 0.02,
        }

    async def fake_catalysts(self, tickers):
        return [{"description": "CPI", "date": "2026-03-11"}]

    monkeypatch.setattr(RunOrchestrator, "_run_delta_analyst", fake_delta_analyst)
    monkeypatch.setattr(RunOrchestrator, "_load_catalysts", fake_catalysts)

    result = asyncio.run(RunOrchestrator().execute("evening_wrap"))

    assert "EVENING WRAP" in result["formatted"]
    assert result["run_profile"]["run_type"] == "evening_wrap"
    assert saved["run_type"] == "evening_wrap"
    assert saved["run_id"] == "2026-03-10T19:00"


def test_weekend_review_execution(monkeypatch) -> None:
    profile = RunProfile(
        run_type="weekend",
        run_id="2026-03-14T10:00",
        market_open=False,
        hours_since_last_run=15.0,
        run_steps={"load_memory", "thesis_review", "report_generation_telegram"},
        report_format="weekend_review",
        budget_usd=2.0,
    )
    saved: dict[str, object] = {}

    monkeypatch.setattr("src.advisor.run_orchestrator.determine_run_profile", lambda run_type="auto": profile)
    monkeypatch.setattr(RunOrchestrator, "_load_config", lambda self: {"holdings": [{"ticker": "NVDA"}]})
    monkeypatch.setattr(
        RunOrchestrator,
        "_load_memory",
        lambda self, config: {"holdings": [{"ticker": "NVDA"}], "conviction_list": [], "moonshot_list": []},
    )
    monkeypatch.setattr("src.advisor.run_orchestrator.get_latest_signal_id", lambda: 11)
    monkeypatch.setattr(
        "src.advisor.memory.list_run_snapshots",
        lambda limit=8, run_type=None: [
            {
                "run_type": "evening_wrap",
                "run_id": "2026-03-13T19:00",
                "snapshot_data": {"tickers": {"NVDA": {"thesis_status": "weakening"}}},
                "delta_from_previous": {"high_significance": [{"narrative": "NVDA sold off after export headlines"}]},
            },
            {
                "run_type": "morning_full",
                "run_id": "2026-03-13T07:00",
                "snapshot_data": {"tickers": {"NVDA": {"thesis_status": "intact"}}},
                "delta_from_previous": {"medium_significance": [{"narrative": "AI infra thesis stayed intact"}]},
            },
        ],
    )
    monkeypatch.setattr("src.advisor.memory.save_run_snapshot", lambda **kwargs: saved.update(kwargs))

    async def fake_catalysts(self, tickers):
        return [{"description": "FOMC decision", "date": "2026-03-18"}]

    monkeypatch.setattr(RunOrchestrator, "_load_catalysts", fake_catalysts)

    result = asyncio.run(RunOrchestrator().execute("weekend"))

    assert "WEEKEND REVIEW" in result["formatted"]
    assert "NVDA: intact" in result["formatted"] or "NVDA: intact → weakening" in result["formatted"]
    assert result["run_profile"]["run_type"] == "weekend"
    assert saved["run_type"] == "weekend"
