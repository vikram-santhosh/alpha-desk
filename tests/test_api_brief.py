from __future__ import annotations

import importlib

from fastapi.testclient import TestClient


def test_brief_run_persists_payload(monkeypatch):
    api_app = importlib.reload(importlib.import_module("src.api.app"))

    async def fake_run(run_type: str):
        return {
            "formatted": "Daily brief body",
            "run_profile": {"run_type": run_type},
            "sections": {"macro": {"call": "risk-on"}},
            "stats": {"total_time_s": 1.2, "run_cost": 0.03},
            "degraded_reasons": [],
        }

    monkeypatch.setattr("src.advisor.main.run", fake_run)
    monkeypatch.setattr(api_app.brief_store, "save_brief_run", lambda run_type, payload: (7, "2026-06-27T09:00:00"))
    client = TestClient(api_app.app)

    response = client.post("/api/brief/run", json={"run_type": "morning_full"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["run_id"] == 7
    assert payload["run_type"] == "morning_full"
    assert payload["formatted"] == "Daily brief body"
    assert payload["stats"]["run_cost"] == 0.03


def test_latest_brief_404(monkeypatch):
    api_app = importlib.reload(importlib.import_module("src.api.app"))
    monkeypatch.setattr(api_app.brief_store, "latest_brief_run", lambda: None)
    client = TestClient(api_app.app)

    response = client.get("/api/brief/runs/latest")

    assert response.status_code == 404
    assert response.json()["detail"] == "No saved brief run found."
