from __future__ import annotations

import importlib


def test_health_returns_process_fingerprint():
    app = importlib.import_module("src.api.app")
    from fastapi.testclient import TestClient

    client = TestClient(app.app)
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["db_backend"] in ("mysql", "sqlite")
    assert isinstance(body["model_allowlist"], list) and body["model_allowlist"]
    assert "git_sha" in body and "started_at" in body
