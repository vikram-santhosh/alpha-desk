from __future__ import annotations

import importlib

from fastapi.testclient import TestClient


def test_research_from_council_runs_maps_payload():
    app = importlib.import_module("src.api.app")
    payloads = [
        {
            "run_id": 5,
            "saved_at": "2026-06-28T00:00:00",
            "verdict": {
                "ticker": "NVDA",
                "rating": "Buy",
                "conviction": 0.72,
                "conviction_label": "High conviction",
                "catalysts": ["Blackwell ramp"],
                "risks": ["Valuation"],
                "scenarios": [{"name": "Bull", "probability": 0.4, "ret_pct": 30}],
            },
            "judge": {"consensus": ["Strong AI demand"], "contradictions": ["Valuation debate"], "blind_spots": ["China"]},
            "panel": [{"thesis": "Compute leader"}],
        }
    ]
    out = app._research_from_council_runs(payloads)
    assert len(out) == 1
    report = out[0]
    assert report.tickers == ["NVDA"]
    assert report.title.startswith("NVDA")
    assert report.verdict == "Buy · High conviction"
    assert report.confidence == 72.0
    assert report.summary == "Strong AI demand"
    headings = [s.heading for s in report.sections]
    assert "Consensus" in headings and "Catalysts" in headings and "Scenarios" in headings


def test_research_endpoint(monkeypatch):
    app = importlib.reload(importlib.import_module("src.api.app"))
    monkeypatch.setattr(
        app.run_store,
        "list_council_payloads",
        lambda limit: [
            {
                "run_id": 1,
                "saved_at": "2026",
                "verdict": {"ticker": "MSFT", "rating": "Overweight", "conviction": 0.6, "conviction_label": "Moderate"},
                "judge": {"consensus": ["x"]},
                "panel": [],
            }
        ],
    )
    client = TestClient(app.app)
    response = client.get("/api/research")
    assert response.status_code == 200
    data = response.json()
    assert data[0]["tickers"] == ["MSFT"]
    assert data[0]["verdict"] == "Overweight · Moderate"
