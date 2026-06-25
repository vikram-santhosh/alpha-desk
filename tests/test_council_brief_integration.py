from __future__ import annotations

import asyncio
import importlib
from types import SimpleNamespace

from src.advisor.council import CouncilResponse
from src.shared.model_registry import CouncilProvider


def _run(coro):
    return asyncio.run(coro)


def _install_committee_fakes(monkeypatch, committee, captured: dict):
    monkeypatch.setattr(committee, "select_model", lambda preferred, allow_downgrade=True: preferred)

    def fake_json_agent(agent_name: str, model: str, max_tokens: int):
        async def runner(prompt: str):
            return {
                "data": {
                    "analyst": agent_name,
                    "analyses": {
                        "NVDA": {
                            "summary": f"{agent_name} sees durable demand.",
                            "rating": "buy",
                        }
                    },
                },
                "cost_usd": 0.0,
                "elapsed_s": 0.0,
            }

        return runner

    def fake_text_agent(agent_name: str, model: str, max_tokens: int):
        async def runner(prompt: str):
            captured["editor_prompt"] = prompt
            return {"raw_text": "CIO synthesized brief"}

        return runner

    class EmptyPlanner:
        def plan(self, *args, **kwargs):
            return SimpleNamespace(tasks=[])

    monkeypatch.setattr(committee, "_make_json_agent", fake_json_agent)
    monkeypatch.setattr(committee, "_make_text_agent", fake_text_agent)
    monkeypatch.setattr(committee, "ResearchPlanner", lambda: EmptyPlanner())
    monkeypatch.setattr(committee.cost_tracker, "check_budget", lambda: (True, 0.0, 10.0))
    monkeypatch.setattr(committee.cost_tracker, "get_current_run_budget", lambda: None)
    monkeypatch.setattr(committee.cost_tracker, "get_run_cost", lambda: 0.0)


def _committee_kwargs():
    return {
        "tickers": ["NVDA", "META", "MSFT"],
        "data_context": {
            "fundamentals": {
                "NVDA": {"current_price": 900, "revenue_growth": 0.22, "pe_forward": 31},
                "META": {"current_price": 610, "revenue_growth": 0.18, "pe_forward": 24},
            },
            "valuation_data": {
                "NVDA": {"target_price": 1100, "implied_cagr": 0.19, "margin_of_safety": 0.12},
                "META": {"target_price": 760, "implied_cagr": 0.17, "margin_of_safety": 0.10},
            },
            "news_articles": [{"title": "AI capex remains elevated"}],
            "prediction_markets": {"fed_cut_probability": 0.35},
        },
        "conviction_context": (
            "- NVDA: week 4, conviction: high, thesis: accelerator demand remains strong\n"
            "- META: week 2, conviction: high, thesis: AI ads and cost discipline support upside"
        ),
        "strategy_context": "- ADD NVDA: role-dependent gate passed [urgency: medium]",
        "macro_context": "- Fed Policy Direction: intact | prediction markets: next cut 35%",
        "holdings_context": "- NVDA: $900 (+1.2% today, +45.0% total) thesis: intact",
        "causal_context": "Causal context already prepared.",
        "supplementary_research": "No open gaps.",
        "config": {"output": {"max_conviction_list": 2}},
        "run_type": "morning_full",
    }


def test_morning_full_council_context_feeds_cio_editor(monkeypatch):
    committee = importlib.reload(importlib.import_module("src.advisor.analyst_committee"))
    captured: dict = {}
    _install_committee_fakes(monkeypatch, committee, captured)
    monkeypatch.setenv("COUNCIL_ENABLED", "true")
    monkeypatch.setenv("COUNCIL_COST_CAP_USD", "10")

    class FakeCouncilClient:
        async def deliberate(self, request):
            captured["council_prompt"] = request.prompt
            captured["council_max_tokens"] = request.max_tokens
            return [
                CouncilResponse(
                    provider=CouncilProvider.GCP_GEMINI,
                    model="gemini-test",
                    label="Gemini",
                    text="Add NVDA. Accepts AI demand, rejects weak valuation comfort.",
                    input_tokens=1000,
                    output_tokens=500,
                ),
                CouncilResponse(
                    provider=CouncilProvider.GCP_GROK,
                    model="grok-test",
                    label="Grok",
                    text="Hold META and wait. Crowded AI narrative deserves a haircut.",
                    input_tokens=900,
                    output_tokens=450,
                ),
            ]

    monkeypatch.setattr(committee, "GCPCouncilClient", FakeCouncilClient)
    monkeypatch.setattr(committee.cost_tracker, "record_usage", lambda *args, **kwargs: 0.05)

    result = _run(committee.run_analyst_committee(**_committee_kwargs()))

    assert result["formatted_brief"] == "CIO synthesized brief"
    assert result["council"]["mode"] == "completed"
    assert result["council"]["selected_tickers"] == ["NVDA", "META"]
    assert captured["council_max_tokens"] == 3500
    assert "Top conviction names: NVDA, META" in captured["council_prompt"]
    assert "## Model Council" in captured["editor_prompt"]
    assert "Council disagreement detected" in captured["editor_prompt"]
    assert "Gemini" in captured["editor_prompt"]
    assert "Grok" in captured["editor_prompt"]


def test_council_disabled_keeps_editor_prompt_without_council(monkeypatch):
    committee = importlib.reload(importlib.import_module("src.advisor.analyst_committee"))
    captured: dict = {}
    _install_committee_fakes(monkeypatch, committee, captured)
    monkeypatch.delenv("COUNCIL_ENABLED", raising=False)

    class FailingCouncilClient:
        async def deliberate(self, request):
            raise AssertionError("council should not run when COUNCIL_ENABLED is false")

    monkeypatch.setattr(committee, "GCPCouncilClient", FailingCouncilClient)

    result = _run(committee.run_analyst_committee(**_committee_kwargs()))

    assert "council" not in result
    assert "degraded_reasons" not in result
    assert "## Model Council" not in captured["editor_prompt"]


def test_council_cost_cap_falls_back_without_feeding_editor(monkeypatch):
    committee = importlib.reload(importlib.import_module("src.advisor.analyst_committee"))
    captured: dict = {}
    _install_committee_fakes(monkeypatch, committee, captured)
    monkeypatch.setenv("COUNCIL_ENABLED", "true")
    monkeypatch.setenv("COUNCIL_COST_CAP_USD", "1")

    class ExpensiveCouncilClient:
        async def deliberate(self, request):
            return [
                CouncilResponse(
                    provider=CouncilProvider.GCP_CLAUDE,
                    model="claude-expensive",
                    label="Claude",
                    text="Add NVDA, but only after checking valuation.",
                    input_tokens=2000,
                    output_tokens=2000,
                )
            ]

    monkeypatch.setattr(committee, "GCPCouncilClient", ExpensiveCouncilClient)
    monkeypatch.setattr(committee.cost_tracker, "record_usage", lambda *args, **kwargs: 5.0)

    result = _run(committee.run_analyst_committee(**_committee_kwargs()))

    assert result["council"]["mode"] == "cost_cap_exceeded"
    assert result["council"]["cost_usd"] == 5.0
    assert "COUNCIL_COST_CAP_USD" in result["degraded_reasons"][0]
    assert "## Model Council" not in captured["editor_prompt"]
