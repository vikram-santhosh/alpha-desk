from __future__ import annotations

import importlib
import json
import sys
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def isolate_api_data_dir(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("ALPHADESK_DATA_DIR", str(tmp_path))


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
    assert events[-1][1]["cost_usd"] == 0.42
    assert events[-1][1]["degraded_reasons"] == []
    assert events[-1][1]["council_mode"] == "unknown"
    assert isinstance(events[-1][1]["run_id"], int)
    assert events[-1][1]["saved_at"]


def test_council_run_persists_latest_run_to_sqlite(monkeypatch, tmp_path: Path):
    api_app = importlib.reload(importlib.import_module("src.api.app"))
    monkeypatch.setattr(api_app.run_store, "DB_PATH", tmp_path / "cockpit_runs.db")

    async def fake_deliberate(prompt, max_tokens):
        return _sample_result("AMD")

    monkeypatch.setattr(api_app.council, "deliberate", fake_deliberate)
    client = TestClient(api_app.app)

    run_response = client.post(
        "/api/council/run",
        json={"ticker": "amd", "models": ["claude", "grok"]},
    )

    assert run_response.status_code == 200
    run_payload = run_response.json()
    assert run_payload["run_id"] == 1
    assert run_payload["saved_at"]

    latest_response = client.get("/api/council/runs/latest?ticker=AMD")
    assert latest_response.status_code == 200
    latest_payload = latest_response.json()
    assert latest_payload["run_id"] == run_payload["run_id"]
    assert latest_payload["verdict"]["ticker"] == "AMD"
    assert latest_payload["panel"][0]["thesis"] == "AI infrastructure demand remains durable."

    summary_response = client.get("/api/council/runs?limit=5")
    assert summary_response.status_code == 200
    summaries = summary_response.json()
    assert summaries == [
        {
            "run_id": 1,
            "saved_at": run_payload["saved_at"],
            "ticker": "AMD",
            "models": ["claude", "grok"],
            "panel_count": 2,
            "cost_usd": 0.42,
            "execution_mode": "unknown",
        }
    ]


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
    assert events[-1][1]["council_mode"] == "skipped"


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
    assert events[-1][1]["council_mode"] == "timeout"


def test_openrouter_stream_emits_panel_results_before_synthesis(monkeypatch):
    api_app = importlib.reload(importlib.import_module("src.api.app"))
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("OPENROUTER_MOCK", "1")
    client = TestClient(api_app.app)

    response = client.get(
        "/api/council/stream"
        "?ticker=NVDA&models=z-ai/glm-5.2,moonshotai/kimi-k2.7-code"
    )

    assert response.status_code == 200
    events = _parse_sse(response.text)
    names = [name for name, _ in events]
    assert names[0] == "panel_started"
    assert "progress" in names
    assert names.index("panel_model_result") < names.index("judge_result")
    assert names.index("judge_result") < names.index("verdict")
    assert names[-1] == "done"
    assert events[-1][1]["council_mode"] == "openrouter_mock"
    assert isinstance(events[-1][1]["run_id"], int)


def test_openrouter_stream_keeps_partial_panel_when_one_model_times_out(monkeypatch):
    api_app = importlib.reload(importlib.import_module("src.api.app"))
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.delenv("OPENROUTER_MOCK", raising=False)
    monkeypatch.setenv("COUNCIL_MODEL_TIMEOUT_S", "0.01")

    async def fake_panel(ticker, model_id):
        if model_id == "slow-model":
            await api_app.asyncio.sleep(0.05)
        return (
            api_app.PanelVerdict(
                model_id=model_id,
                label=api_app._label_from_model_id(model_id),
                rating="Buy",
                confidence=0.8,
                thesis=f"{ticker} has a durable upside thesis from {model_id}.",
                dissent=False,
                accepted_claims=["Revenue growth supports the thesis."],
                rejected_claims=[],
                challenges=["Validate valuation sensitivity."],
            ),
            0.02,
        )

    async def fake_cross_exam(ticker, model_id, own_verdict, panel):
        return own_verdict, 0.01

    monkeypatch.setattr(api_app, "_run_openrouter_panel_model_async", fake_panel)
    monkeypatch.setattr(api_app, "_run_openrouter_cross_exam_async", fake_cross_exam)
    client = TestClient(api_app.app)

    response = client.get("/api/council/stream?ticker=AFRM&models=fast-model,slow-model")

    assert response.status_code == 200
    events = _parse_sse(response.text)
    panel_events = [data for name, data in events if name == "panel_model_result"]
    done = events[-1][1]
    assert events[-1][0] == "done"
    assert done["council_mode"] == "openrouter_live"
    assert isinstance(done["run_id"], int)
    assert any(item["model_id"] == "fast-model" and item["confidence"] == 0.8 for item in panel_events)
    slow = next(item for item in panel_events if item["model_id"] == "slow-model")
    assert slow["confidence"] == 0.0
    assert "did not return a reliable thesis" in slow["thesis"]
    assert any("Slow Model failed" in reason for reason in done["degraded_reasons"])
    assert "timeout" not in done["council_mode"]


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


def test_macro_endpoint_returns_backend_dashboard(monkeypatch):
    api_app = importlib.reload(importlib.import_module("src.api.app"))

    monkeypatch.setattr(
        api_app,
        "_fetch_live_macro_data",
        lambda: {
            "vix": {"value": 17.5, "change_pct": -2.0, "date": "2026-06-18"},
            "sp500": {"value": 6100.0, "change_pct": 0.8, "date": "2026-06-18"},
            "treasury_10y": {"value": 4.1, "date": "2026-06-18"},
            "yield_curve_spread_calculated": 0.2,
            "fetched_at": "2026-06-18T12:00:00",
            "date": "2026-06-18",
        },
    )
    monkeypatch.setattr(
        api_app,
        "_macro_theses_from_memory_or_config",
        lambda degraded: [
            {
                "title": "AI Infrastructure Build-Out",
                "description": "GPU, networking, power, and foundry demand accelerating.",
                "status": "intact",
                "affected_tickers": ["NVDA", "VRT"],
                "evidence_log": [],
            }
        ],
    )
    client = TestClient(api_app.app)

    response = client.get("/api/macro")

    assert response.status_code == 200
    payload = response.json()
    assert payload["regime"]["source"] == "backend"
    assert payload["regime"]["agent"] == "Backend Macro Scanner"
    assert payload["regime"]["scannedAt"] == "2026-06-18T12:00:00"
    assert payload["regime"]["score"] > 50
    assert payload["themes"][0]["title"] == "AI Infrastructure Build-Out"
    assert payload["themes"][0]["status"] == "risk_on"
    assert "NVDA" in payload["themes"][0]["bullets"][1]


def test_today_ideas_endpoint_returns_mock_research_candidates(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("OPENROUTER_MOCK", "1")
    monkeypatch.setenv("ALPHA_SCOUT_MOCK", "1")
    api_app = importlib.reload(importlib.import_module("src.api.app"))
    client = TestClient(api_app.app)

    response = client.get("/api/ideas/today?limit=10")

    assert response.status_code == 200
    payload = response.json()
    assert payload["universe"] == "US-listed liquid equities and ADRs"
    assert payload["scout_mode"] == "mock"
    assert len(payload["ideas"]) == 10
    assert payload["ideas"][0]["rank"] == 1
    assert payload["ideas"][0]["ticker"] == "NVDA"
    assert payload["ideas"][0]["score"] > payload["ideas"][-1]["score"]
    checks = {item["source"]: item for item in payload["data_source_checks"]}
    assert checks["OpenRouter scout"]["status"] == "configured"
    assert checks["YFinance screeners"]["status"] in {"configured", "unavailable"}
    assert checks["Reddit moonshot"]["status"] in {"configured", "unavailable"}
    assert checks["Kalshi prediction markets"]["status"] in {"configured", "unavailable"}
    assert checks["Council roster"]["status"] == "validated"
    assert "Research candidates only" in payload["disclaimer"]
    assert payload["cost_usd"] == 0.0


def test_today_ideas_persists_latest_run_to_sqlite(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("OPENROUTER_MOCK", "1")
    monkeypatch.setenv("ALPHA_SCOUT_MOCK", "1")
    api_app = importlib.reload(importlib.import_module("src.api.app"))
    monkeypatch.setattr(api_app.run_store, "DB_PATH", tmp_path / "cockpit_runs.db")
    client = TestClient(api_app.app)

    run_response = client.get("/api/ideas/today?limit=10&mode=top_buys")

    assert run_response.status_code == 200
    run_payload = run_response.json()
    assert run_payload["run_id"] == 1
    assert run_payload["saved_at"]

    latest_response = client.get("/api/ideas/runs/latest?mode=top_buys")
    assert latest_response.status_code == 200
    latest_payload = latest_response.json()
    assert latest_payload["run_id"] == run_payload["run_id"]
    assert latest_payload["ideas"][0]["ticker"] == "NVDA"

    summary_response = client.get("/api/ideas/runs?limit=5")
    assert summary_response.status_code == 200
    summaries = summary_response.json()
    assert summaries == [
        {
            "run_id": 1,
            "saved_at": run_payload["saved_at"],
            "scout_mode": "top_buys",
            "as_of": run_payload["as_of"],
            "idea_count": 10,
            "cost_usd": 0.0,
        }
    ]


def test_today_ideas_endpoint_runs_alpha_scout_pipeline(monkeypatch):
    api_app = importlib.reload(importlib.import_module("src.api.app"))

    async def fake_alpha_scout_pipeline(mode="top_buys"):
        return {
            "formatted": "<b>Alpha Scout</b>",
            "signals": [{"id": 1, "ticker": "SHOP"}],
            "stats": {
                "mode": mode,
                "candidates_sourced": 25,
                "candidates_screened": 20,
                "portfolio_recs": 1,
                "watchlist_recs": 1,
                "signals_published": 2,
                "total_time_s": 4.2,
                "candidate_audit": {
                    "mode": mode,
                    "source_counts": {"existing universe": 3, "sector peers": 12},
                    "raw_candidates": 25,
                    "unique_candidates": 20,
                    "capped_candidates": 20,
                    "existing_universe_count": 3,
                    "excluded_existing": [],
                },
                "tracked_ticker_checks": {
                    "AMZN": {"included": True, "source": "existing_portfolio", "mode": mode},
                    "META": {"included": True, "source": "existing_watchlist", "mode": mode},
                    "AVGO": {"included": True, "source": "existing_watchlist", "mode": mode},
                },
            },
            "recommendations": {
                "portfolio_recs": [
                    {
                        "ticker": "SHOP",
                        "category": "portfolio",
                        "conviction": "high",
                        "thesis": "Commerce software demand is reaccelerating.",
                        "scores": {"composite": 82.0, "fundamental": 78, "technical": 72},
                        "fundamentals_summary": {"sector": "Technology"},
                        "source": "alpha_scout/yfinance",
                    }
                ],
                "watchlist_recs": [
                    {
                        "ticker": "CELH",
                        "category": "watchlist",
                        "conviction": "medium",
                        "thesis": "Distribution resets need confirmation.",
                        "scores": {"composite": 64.0},
                        "fundamentals_summary": {"sector": "Consumer Defensive"},
                    }
                ],
            },
        }

    monkeypatch.setattr(api_app, "_run_alpha_scout_pipeline", fake_alpha_scout_pipeline)
    client = TestClient(api_app.app)

    response = client.get("/api/ideas/today?limit=10")

    assert response.status_code == 200
    payload = response.json()
    assert payload["universe"] == "Alpha Scout top-buy pipeline"
    assert payload["scout_mode"] == "top_buys"
    assert payload["audit"]["tracked_ticker_checks"]["META"]["included"] is True
    assert [idea["ticker"] for idea in payload["ideas"]] == ["SHOP", "CELH"]
    assert payload["ideas"][0]["score"] == 0.82
    assert payload["ideas"][0]["theme"] == "Portfolio · Technology"
    checks = {item["source"]: item for item in payload["data_source_checks"]}
    assert checks["Alpha Scout pipeline"]["status"] == "validated"
    assert "25 sourced" in checks["Alpha Scout pipeline"]["detail"]


def test_today_ideas_top_buy_coverage_keeps_high_scoring_tracked_names(monkeypatch):
    api_app = importlib.reload(importlib.import_module("src.api.app"))

    def scored(ticker, composite, source):
        return {
            "ticker": ticker,
            "category": "watchlist",
            "conviction": "medium",
            "thesis": f"{ticker} scored {composite}.",
            "source": source,
            "scores": {"composite": composite},
            "fundamentals_summary": {"sector": "Technology"},
        }

    async def fake_alpha_scout_pipeline(mode="top_buys"):
        return {
            "formatted": "<b>Alpha Scout</b>",
            "signals": [],
            "stats": {
                "mode": mode,
                "candidates_sourced": 20,
                "candidates_screened": 20,
                "portfolio_recs": 5,
                "watchlist_recs": 7,
                "signals_published": 0,
                "candidate_audit": {
                    "mode": mode,
                    "source_counts": {"existing universe": 4, "agent bus": 12},
                    "raw_candidates": 20,
                    "unique_candidates": 20,
                    "capped_candidates": 20,
                    "existing_universe_count": 4,
                    "excluded_existing": [],
                },
                "tracked_ticker_checks": {
                    "AMZN": {"included": True, "source": "existing_portfolio", "mode": mode},
                    "META": {"included": True, "source": "existing_watchlist", "mode": mode},
                    "AVGO": {"included": True, "source": "existing_watchlist", "mode": mode},
                },
            },
            "recommendations": {
                "portfolio_recs": [scored(f"NOISY{i}", 80 - i, "agent_bus/portfolio_analyst") for i in range(5)],
                "watchlist_recs": [scored(f"CHAT{i}", 75 - i, "agent_bus/portfolio_analyst") for i in range(7)],
            },
            "scored_candidates": [
                scored("AMZN", 63, "existing_portfolio"),
                scored("META", 62, "existing_watchlist"),
                scored("AVGO", 64, "existing_watchlist"),
                scored("NVDA", 65, "existing_watchlist"),
            ],
        }

    monkeypatch.setattr(api_app, "_run_alpha_scout_pipeline", fake_alpha_scout_pipeline)
    client = TestClient(api_app.app)

    response = client.get("/api/ideas/today?limit=12&mode=top_buys")

    assert response.status_code == 200
    tickers = [idea["ticker"] for idea in response.json()["ideas"]]
    assert "AMZN" in tickers
    assert "META" in tickers
    assert "AVGO" in tickers


def test_openrouter_mock_council_is_reported_as_deterministic(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("OPENROUTER_MOCK", "1")
    api_app = importlib.reload(importlib.import_module("src.api.app"))
    client = TestClient(api_app.app)

    response = client.post(
        "/api/council/run",
        json={"ticker": "meta", "models": ["google/gemini-3.5-flash"]},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["execution_mode"] == "openrouter_mock"
    assert "deterministic test data" in payload["degraded_reasons"][0]


def test_today_ideas_repair_normalizes_partial_openrouter_payload(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    api_app = importlib.reload(importlib.import_module("src.api.app"))

    payload = {
        "ideas": [
            {
                "rank": 99,
                "ticker": " msft ",
                "company": "Microsoft",
                "theme": "AI platform",
                "score": "HIGH",
                "thesis": "Azure AI demand supports durable compounding.",
            },
            "bad idea",
        ],
        "data_source_checks": [
            {
                "source": "Fixture",
                "status": "validated",
                "detail": "Fixture source check.",
                "checked_at": "2026-06-17",
            }
        ],
    }

    result, reasons = api_app._repair_idea_scout_payload(payload, 10)

    assert result.ideas[0].rank == 12
    assert result.ideas[0].ticker == "MSFT"
    assert result.ideas[0].score == 0.82
    assert result.ideas[0].horizon == "6-18 months"
    assert result.ideas[0].catalysts == ["Next company update"]
    assert result.ideas[0].risks == ["Valuation or macro risk"]
    assert result.data_source_checks[0].source == "Fixture"
    assert result.data_source_checks[0].status == "validated"
    assert reasons == ["Idea scout returned a non-object idea; skipped it."]


def test_council_models_return_openrouter_roster_when_fusion_is_configured(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    api_app = importlib.reload(importlib.import_module("src.api.app"))
    client = TestClient(api_app.app)

    response = client.get("/api/council/models")

    assert response.status_code == 200
    payload = response.json()
    assert [model["model_id"] for model in payload] == [
        "z-ai/glm-5.2",
        "moonshotai/kimi-k2.6",
        "deepseek/deepseek-v4-pro",
        "google/gemini-3.5-flash",
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
        "google/gemini-3.1-flash-lite",
        "x-ai/grok-4.20",
    ]
    assert payload[0]["label"] == "Gemini 3 1 Flash Lite"


def test_openrouter_direct_council_calls_selected_models(monkeypatch):
    api_app = importlib.reload(importlib.import_module("src.api.app"))
    captured_models = []

    def fake_completion(request_body, request_headers, timeout_s):
        captured_models.append(request_body["model"])
        result = {
            "model_id": request_body["model"],
            "label": request_body["model"],
            "rating": "Overweight" if "gemini" in request_body["model"] else "Hold",
            "confidence": 0.7 if "gemini" in request_body["model"] else 0.55,
            "thesis": f"{request_body['model']} sees balanced upside with valuation risk.",
            "dissent": False,
        }
        return {
            "choices": [{"message": {"content": json.dumps(result)}}],
            "usage": {"cost": 0.01},
        }

    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setattr(api_app, "_openrouter_completion_raw", fake_completion)

    result = api_app.asyncio.run(
        api_app._run_openrouter_council(
            "NVDA",
            ["google/gemini-3.5-flash", "moonshotai/kimi-k2.7-code"],
        )
    )

    assert Counter(captured_models) == Counter(
        {
            "google/gemini-3.5-flash": 2,
            "moonshotai/kimi-k2.7-code": 2,
        }
    )
    assert result.cost_usd == 0.04
    assert result.verdict.ticker == "NVDA"
    assert result.verdict.rating == "Overweight"
    assert result.panel[1].dissent is True


def test_degraded_cross_exam_does_not_overwrite_initial_panel(monkeypatch):
    api_app = importlib.reload(importlib.import_module("src.api.app"))
    initial = api_app.PanelVerdict(
        model_id="moonshotai/kimi-k2.7-code",
        label="Kimi K2.7 Code",
        rating="Overweight",
        confidence=0.78,
        thesis="Kimi returned a valid first-pass thesis.",
        dissent=False,
        accepted_claims=["AI demand remains durable."],
        rejected_claims=["Valuation is not cheap."],
        challenges=["Quantify capex digestion risk."],
    )
    degraded = api_app.PanelVerdict(
        model_id="moonshotai/kimi-k2.7-code",
        label="Kimi K2.7 Code",
        rating="Hold",
        confidence=0.35,
        thesis="moonshotai/kimi-k2.7-code returned an empty response.",
        dissent=False,
        accepted_claims=[],
        rejected_claims=["Empty model response cannot validate other seats' claims."],
        challenges=["Retry this model or inspect provider availability before relying on it."],
    )

    merged = api_app._merge_cross_exam_verdict(initial, degraded)

    assert merged == initial
    assert "Empty model response" not in " ".join(merged.rejected_claims)
    assert "Retry this model" not in " ".join(merged.challenges)


def test_truncated_panel_json_is_not_rendered_as_thesis():
    api_app = importlib.reload(importlib.import_module("src.api.app"))

    parsed = api_app._plain_panel_from_text(
        "NVDA",
        "google/gemini-3.5-flash",
        '{"model_id":"google/gemini-3.5-flash","label":"NVIDIA Corporation (NVDA',
    )

    assert not parsed["thesis"].startswith("{")
    assert "incomplete structured output" in parsed["thesis"]
    assert parsed["challenges"] == []


def test_openrouter_mock_council_finishes_without_network(monkeypatch):
    api_app = importlib.reload(importlib.import_module("src.api.app"))

    def fail_if_network_called(request_body, request_headers, timeout_s):
        raise AssertionError("mock OpenRouter council should not call the network")

    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("OPENROUTER_MOCK", "1")
    monkeypatch.setattr(api_app, "_openrouter_completion_raw", fail_if_network_called)

    result = api_app.asyncio.run(
        api_app._run_openrouter_council(
            "NVDA",
            [
                "google/gemini-3.5-flash",
                "moonshotai/kimi-k2.7-code",
                "deepseek/deepseek-v4-pro",
                "z-ai/glm-5.2",
            ],
        )
    )

    assert result.verdict.ticker == "NVDA"
    assert result.cost_usd == 0.0
    assert [item.model_id for item in result.panel] == [
        "google/gemini-3.5-flash",
        "moonshotai/kimi-k2.7-code",
        "deepseek/deepseek-v4-pro",
        "z-ai/glm-5.2",
    ]
    assert any(item.dissent for item in result.panel)


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
        "x-ai/grok-4.3",
    ]


def test_openrouter_fusion_reads_tool_call_arguments_when_content_is_empty(monkeypatch):
    api_app = importlib.reload(importlib.import_module("src.api.app"))
    captured = {}

    class FakeCompletions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content="",
                            tool_calls=[
                                SimpleNamespace(
                                    function=SimpleNamespace(arguments=json.dumps(_sample_result("TSLA")))
                                )
                            ],
                        )
                    )
                ],
                usage=SimpleNamespace(cost=0.29),
            )

    class FakeClient:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=FakeClient))

    result = api_app._run_openrouter_fusion_sync("TSLA", ["anthropic/claude-opus-4.8"])

    assert result.verdict.ticker == "TSLA"
    assert result.cost_usd == 0.29
    assert captured["model"] == "openrouter/fusion"


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

    # Legacy / GCP model ids all collapse onto the four allowed OpenRouter models.
    assert captured["extra_body"]["tools"][0]["parameters"]["analysis_models"] == [
        "moonshotai/kimi-k2.6",
        "google/gemini-3.5-flash",
        "z-ai/glm-5.2",
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


def test_openrouter_fusion_uses_raw_http_fallback_when_sdk_fails(monkeypatch):
    api_app = importlib.reload(importlib.import_module("src.api.app"))

    class FailingCompletions:
        def create(self, **kwargs):
            raise RuntimeError("sdk parse failed")

    class FailingClient:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=FailingCompletions())

    raw_payload = {
        "choices": [
            {
                "message": {
                    "content": json.dumps(_sample_result("AMD")),
                }
            }
        ],
        "usage": {"cost": 0.22},
    }
    body = json.dumps(raw_payload).encode("utf-8")

    class FakeHeaders:
        def get_content_charset(self):
            return "utf-8"

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return body

        headers = FakeHeaders()

    def fake_urlopen(request, timeout):
        return FakeResponse()

    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=FailingClient))
    monkeypatch.setattr(api_app.urllib.request, "urlopen", fake_urlopen)

    result = api_app._run_openrouter_fusion_sync("AMD", ["x-ai/grok-4.3"])

    assert result.verdict.ticker == "AMD"
    assert result.cost_usd == 0.22
    assert result.panel[0].rating == "Buy"


def test_openrouter_fusion_maps_investment_council_envelope(monkeypatch):
    api_app = importlib.reload(importlib.import_module("src.api.app"))
    envelope = {
        "portfolio_id": "ALPHADESK-TACTICAL-EQ",
        "ticker": "NVDA",
        "issuer_name": "NVIDIA Corporation",
        "analysis_date": "2025-05-20",
        "market_context": {"current_price_usd": 135.5},
        "investment_council": {
            "consensus_rating": "OVERWEIGHT",
            "consensus_conviction_score": 0.74,
            "consensus_price_target": 167.5,
            "time_horizon": "12 Months",
            "implied_return_pct": 23.6,
            "seats": [
                {
                    "role": "Secular Growth Bull",
                    "stance": "BUY",
                    "price_target_12m": 210,
                    "conviction_score": 0.9,
                    "thesis_summary": "Blackwell demand and system-level integration keep growth strong.",
                    "core_arguments": [
                        "Unprecedented demand backlog for GB200 NVL72 architectures.",
                        "High attach rates for proprietary networking."
                    ],
                },
                {
                    "role": "Value & Quantitative Strategist",
                    "stance": "BUY",
                    "price_target_12m": 165,
                    "conviction_score": 0.75,
                    "thesis_summary": "ROIC and PEG justify the premium.",
                    "core_arguments": ["Forward P/E remains reasonable given growth."]
                },
                {
                    "role": "Risk Manager",
                    "stance": "HOLD",
                    "price_target_12m": 145,
                    "conviction_score": 0.62,
                    "thesis_summary": "Concentration and custom silicon risks merit caution.",
                    "core_arguments": ["Customer concentration is high."]
                }
            ],
        }
    }

    class FakeCompletions:
        def create(self, **kwargs):
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(envelope)))],
                usage=SimpleNamespace(cost=0.91),
            )

    class FakeClient:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=FakeClient))

    result = api_app._run_openrouter_fusion_sync(
        "NVDA",
        ["anthropic/claude-opus-4.8-fast", "google/gemini-3.1-flash-lite", "x-ai/grok-4.20"],
    )

    assert result.verdict.rating == "Overweight"
    assert result.verdict.conviction == 0.74
    assert result.verdict.scenarios[1].ret_pct == 23.6
    assert result.panel[0].model_id == "google/gemini-3.1-flash-lite"
    assert result.panel[0].label == "Secular Growth Bull"
    assert result.panel[2].dissent is True
    assert result.judge.crowded_narrative_flag is not None
