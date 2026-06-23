from __future__ import annotations

import asyncio

from src.advisor.deep_researcher import MultiStepDeepResearcher
from src.advisor.research_planner import ResearchPlanner, ResearchTask
from src.shared import web_search
from src.shared.citations import CitationRegistry


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_deep_research_web_search_populates_observations_and_citations(monkeypatch):
    captured: dict[str, object] = {}

    def fake_search(query: str, *, max_results: int):
        captured["query"] = query
        captured["max_results"] = max_results
        return [
            {
                "title": "NVIDIA announces updated data center guidance",
                "url": "https://example.com/nvda-guidance",
                "snippet": "Management raised data center revenue guidance after Blackwell demand.",
                "published": "2026-06-20",
            }
        ]

    monkeypatch.setattr(web_search, "search", fake_search)
    monkeypatch.setattr("src.advisor.deep_researcher.get_ticker_deep_context", lambda ticker: {})

    researcher = MultiStepDeepResearcher(web_search_enabled=True, web_search_max_results=3)
    task = ResearchTask(
        ticker="NVDA",
        research_question="What changed for NVDA?",
        task_type="thesis_validation",
        priority=5,
        data_needs=["web_search"],
    )
    registry = CitationRegistry()

    result = _run(
        researcher._gather(
            task,
            {
                "holdings_reports": [
                    {
                        "ticker": "NVDA",
                        "company": "NVIDIA",
                        "change_pct": 3.2,
                        "thesis": "AI accelerator demand remains strong",
                    }
                ]
            },
            registry,
        )
    )

    assert captured["max_results"] == 3
    assert "NVDA NVIDIA earnings guidance catalysts stock move +3.2%" in captured["query"]
    assert any("Web search: NVIDIA announces updated data center guidance" in obs for obs in result["observations"])
    assert registry.as_list() == [
        {
            "citation_id": 1,
            "url": "https://example.com/nvda-guidance",
            "title": "NVIDIA announces updated data center guidance",
            "source_agent": "web_search",
            "published_at": "2026-06-20",
        }
    ]


def test_deep_research_web_search_disabled_is_noop(monkeypatch):
    def fail_search(query: str, *, max_results: int):
        raise AssertionError("search should not be called when disabled")

    monkeypatch.setattr(web_search, "search", fail_search)
    monkeypatch.setattr("src.advisor.deep_researcher.get_ticker_deep_context", lambda ticker: {})

    researcher = MultiStepDeepResearcher(web_search_enabled=False)
    task = ResearchTask(
        ticker="MSFT",
        research_question="What changed for MSFT?",
        task_type="thesis_validation",
        priority=5,
        data_needs=["web_search"],
    )
    registry = CitationRegistry()

    result = _run(researcher._gather(task, {"holdings_reports": []}, registry))

    assert result["observations"] == []
    assert registry.as_list() == []


def test_deep_research_web_search_backend_failure_is_graceful(monkeypatch):
    def raising_search(query: str, *, max_results: int):
        raise RuntimeError("provider down")

    monkeypatch.setattr(web_search, "search", raising_search)
    monkeypatch.setattr("src.advisor.deep_researcher.get_ticker_deep_context", lambda ticker: {})

    researcher = MultiStepDeepResearcher(web_search_enabled=True)
    task = ResearchTask(
        ticker="AMZN",
        research_question="What changed for AMZN?",
        task_type="thesis_validation",
        priority=5,
        data_needs=["web_search"],
    )
    registry = CitationRegistry()

    result = _run(researcher._gather(task, {"holdings_reports": []}, registry))

    assert result["observations"] == []
    assert registry.as_list() == []


def test_research_planner_adds_web_search_to_default_data_needs():
    planner = ResearchPlanner()
    plan = planner.plan(
        tickers=["META"],
        holdings_reports=[{"ticker": "META", "change_pct": 2.5}],
        news_articles=[],
        signals=[],
        max_tasks=1,
    )

    assert plan.tasks
    assert "web_search" in plan.tasks[0].data_needs
