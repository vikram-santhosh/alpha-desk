from __future__ import annotations

import importlib
import json
import sys
from types import SimpleNamespace

from fastapi.testclient import TestClient


def _sample_result(ticker: str = "NVDA") -> dict:
    return {
        "panel": [
            {
                "model_id": "anthropic/claude-opus-4.8",
                "label": "Claude Opus 4.8",
                "rating": "Buy",
                "confidence": 0.82,
                "thesis": "AI infrastructure demand remains durable.",
                "dissent": False,
            },
            {
                "model_id": "x-ai/grok-4.3",
                "label": "Grok 4.3",
                "rating": "Hold",
                "confidence": 0.61,
                "thesis": "Upside is real, but valuation is crowded.",
                "dissent": True,
            },
        ],
        "judge": {
            "consensus": ["AI demand remains the core driver."],
            "contradictions": ["Valuation support split the panel."],
            "blind_spots": ["Export controls need more detail."],
            "crowded_narrative_flag": {
                "topic": "AI infrastructure",
                "note": "Consensus leans on a crowded narrative.",
            },
        },
        "verdict": {
            "ticker": ticker,
            "rating": "Buy",
            "conviction": 0.74,
            "conviction_label": "High — with a timing caveat",
            "scenarios": [
                {"name": "Bull", "probability": 0.3, "ret_pct": 35.0},
                {"name": "Base", "probability": 0.5, "ret_pct": 12.0},
                {"name": "Bear", "probability": 0.2, "ret_pct": -18.0},
            ],
            "catalysts": ["Next earnings call"],
            "risks": ["Multiple compression"],
        },
        "cost_usd": 0.42,
        "degraded_reasons": [],
    }


def _parse_sse(body: str) -> list[tuple[str, dict]]:
    events = []
    for chunk in body.strip().split("\n\n"):
        event_name = None
        data = None
        for line in chunk.splitlines():
            if line.startswith("event: "):
                event_name = line.removeprefix("event: ")
            if line.startswith("data: "):
                data = json.loads(line.removeprefix("data: "))
        if event_name and data is not None:
            events.append((event_name, data))
    return events


def test_council_run_returns_full_result(monkeypatch):
    api_app = importlib.reload(importlib.import_module("src.api.app"))

    async def fake_deliberate(prompt, max_tokens):
        return _sample_result("NVDA")

    monkeypatch.setattr(api_app.council, "deliberate", fake_deliberate)
    client = TestClient(api_app.app)

    response = client.post(
        "/api/council/run",
        json={"ticker": "nvda", "models": ["anthropic/claude-opus-4.8", "x-ai/grok-4.3"]},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["verdict"]["ticker"] == "NVDA"
    assert payload["panel"][1]["dissent"] is True
    assert payload["judge"]["crowded_narrative_flag"]["topic"] == "AI infrastructure"


def test_council_stream_emits_events_in_order(monkeypatch):
    api_app = importlib.reload(importlib.import_module("src.api.app"))

    async def fake_deliberate(prompt, max_tokens):
        return _sample_result("AMZN")

    monkeypatch.setattr(api_app.council, "deliberate", fake_deliberate)
    client = TestClient(api_app.app)

    response = client.get("/api/council/stream?ticker=amzn&models=claude,grok")

    assert response.status_code == 200
    events = _parse_sse(response.text)
    assert [name for name, _ in events] == [
        "panel_started",
        "panel_model_result",
        "panel_model_result",
        "judge_result",
        "verdict",
        "done",
    ]
    assert events[0][1] == {"ticker": "AMZN", "models": ["claude", "grok"]}
    assert events[-1][1] == {"cost_usd": 0.42, "degraded_reasons": []}


def test_council_stream_surfaces_cost_cap_without_silent_failure(monkeypatch):
    api_app = importlib.reload(importlib.import_module("src.api.app"))
    monkeypatch.setenv("COUNCIL_COST_CAP_USD", "0")

    async def fail_if_called(prompt, max_tokens):
        raise AssertionError("council should not run when the cap is zero")

    monkeypatch.setattr(api_app.council, "deliberate", fail_if_called)
    client = TestClient(api_app.app)

    response = client.get("/api/council/stream?ticker=NVDA&models=claude")

    assert response.status_code == 200
    events = _parse_sse(response.text)
    assert [name for name, _ in events] == ["panel_started", "done"]
    assert "COUNCIL_COST_CAP_USD is 0" in events[-1][1]["degraded_reasons"][0]


def test_council_stream_times_out_without_silent_failure(monkeypatch):
    api_app = importlib.reload(importlib.import_module("src.api.app"))
    monkeypatch.setenv("COUNCIL_STREAM_TIMEOUT_S", "0.01")

    async def slow_run_council(ticker, models):
        await api_app.asyncio.sleep(1)
        return _sample_result(ticker)

    monkeypatch.setattr(api_app, "_run_council", slow_run_council)
    client = TestClient(api_app.app)

    response = client.get("/api/council/stream?ticker=NVDA&models=claude")

    assert response.status_code == 200
    events = _parse_sse(response.text)
    assert [name for name, _ in events] == ["panel_started", "done"]
    assert events[-1][1]["degraded_reasons"] == ["Council timed out before completion."]


def test_portfolio_endpoint_flags_concentration(monkeypatch):
    api_app = importlib.reload(importlib.import_module("src.api.app"))

    def fake_load_config(name):
        if name == "portfolio":
            return {
                "holdings": [
                    {"ticker": "NVDA", "weight_pct": 70},
                    {"ticker": "AMZN", "weight_pct": 20},
                    {"ticker": "MSFT", "weight_pct": 10},
                ]
            }
        if name == "advisor":
            return {"strategy": {"max_position_pct": 25}}
        return {}

    monkeypatch.setattr(api_app, "load_config", fake_load_config)
    client = TestClient(api_app.app)

    response = client.get("/api/portfolio")

    assert response.status_code == 200
    payload = response.json()
    assert payload["positions"][0]["ticker"] == "NVDA"
    assert payload["top_holding_pct"] == 70.0
    assert payload["concentration_flag"] is True


def test_council_models_return_openrouter_roster_when_fusion_is_configured(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    api_app = importlib.reload(importlib.import_module("src.api.app"))
    client = TestClient(api_app.app)

    response = client.get("/api/council/models")

    assert response.status_code == 200
    payload = response.json()
    assert [model["model_id"] for model in payload] == [
        "anthropic/claude-opus-4.8",
        "google/gemini-3.1-pro-preview",
        "x-ai/grok-4.3",
    ]


def test_council_models_allow_openrouter_roster_override(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv(
        "OPENROUTER_ANALYSIS_MODELS",
        "anthropic/claude-opus-4.8-fast,google/gemini-3.1-flash-lite,x-ai/grok-4.20",
    )
    api_app = importlib.reload(importlib.import_module("src.api.app"))
    client = TestClient(api_app.app)

    response = client.get("/api/council/models")

    assert response.status_code == 200
    payload = response.json()
    assert [model["model_id"] for model in payload] == [
        "anthropic/claude-opus-4.8-fast",
        "google/gemini-3.1-flash-lite",
        "x-ai/grok-4.20",
    ]
    assert payload[0]["label"] == "Claude Opus 4 8 Fast"


def test_openrouter_fusion_adapter_uses_selected_models(monkeypatch):
    api_app = importlib.reload(importlib.import_module("src.api.app"))
    captured = {}

    class FakeCompletions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content="```json\n" + json.dumps(_sample_result("RKLB")) + "\n```"
                        )
                    )
                ],
                usage=SimpleNamespace(cost=0.31),
            )

    class FakeClient:
        def __init__(self, **kwargs):
            captured["client"] = kwargs
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=FakeClient))

    result = api_app._run_openrouter_fusion_sync(
        "RKLB",
        ["anthropic/claude-opus-4.8", "x-ai/grok-4.3"],
    )

    assert result.verdict.ticker == "RKLB"
    assert result.cost_usd == 0.31
    assert captured["model"] == "openrouter/fusion"
    assert captured["response_format"]["type"] == "json_schema"
    assert captured["response_format"]["json_schema"]["strict"] is True
    assert captured["max_tokens"] == 2400
    assert captured["extra_body"]["tool_choice"] == "required"
    assert captured["extra_body"]["plugins"] == [{"id": "response-healing"}]
    assert captured["extra_body"]["tools"][0]["parameters"]["analysis_models"] == [
        "anthropic/claude-opus-4.8",
        "x-ai/grok-4.3",
    ]


def test_openrouter_fusion_maps_gcp_model_ids(monkeypatch):
    api_app = importlib.reload(importlib.import_module("src.api.app"))
    captured = {}

    class FakeCompletions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content=json.dumps(_sample_result("NVDA")))
                    )
                ],
                usage=SimpleNamespace(cost=0.12),
            )

    class FakeClient:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=FakeClient))

    api_app._run_openrouter_fusion_sync(
        "NVDA",
        ["claude-opus-4-8", "gemini-3.1-pro-preview", "xai/grok-4.20-reasoning", "openrouter/fusion"],
    )

    assert captured["extra_body"]["tools"][0]["parameters"]["analysis_models"] == [
        "anthropic/claude-opus-4.8",
        "google/gemini-3.1-pro-preview",
        "x-ai/grok-4.3",
    ]


def test_openrouter_fusion_repairs_partial_payload(monkeypatch):
    api_app = importlib.reload(importlib.import_module("src.api.app"))
    partial = _sample_result("NVDA")
    partial.pop("cost_usd")
    partial["verdict"].pop("catalysts")
    partial["verdict"].pop("risks")

    captured = {}

    class FakeCompletions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(partial)))],
                usage=SimpleNamespace(cost=0.18),
            )

    class FakeClient:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=FakeClient))

    result = api_app._run_openrouter_fusion_sync("NVDA", ["x-ai/grok-4.3"])

    assert result.cost_usd == 0.18
    assert result.verdict.catalysts == []
    assert result.verdict.risks == []
    assert any("omitted verdict.catalysts" in reason for reason in result.degraded_reasons)


def test_openrouter_fusion_repairs_panel_only_payload(monkeypatch):
    api_app = importlib.reload(importlib.import_module("src.api.app"))
    partial = {
        "panel": [
            {
                "model_id": "x-ai/grok-4.20",
                "label": "Grok",
                "rating": "Overweight",
                "dissent": False,
            }
        ]
    }

    class FakeCompletions:
        def create(self, **kwargs):
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(partial)))],
                usage=SimpleNamespace(cost=0.09),
            )

    class FakeClient:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=FakeClient))

    result = api_app._run_openrouter_fusion_sync("NVDA", ["x-ai/grok-4.20"])

    assert result.panel[0].confidence == 0.0
    assert result.panel[0].thesis == "Fusion returned an incomplete panel entry."
    assert result.verdict.ticker == "NVDA"
    assert result.verdict.rating == "Overweight"
    assert result.judge.blind_spots == ["Fusion omitted structured judge analysis."]
    assert any("structured verdict" in reason for reason in result.degraded_reasons)
