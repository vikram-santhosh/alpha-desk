from __future__ import annotations

import importlib
import sys
from types import SimpleNamespace


class _FakeGenerateContentConfig:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class _FakeUsageMetadata:
    prompt_token_count = 1_000_000
    candidates_token_count = 1_000_000


class _FakeResponse:
    text = "ok"
    usage_metadata = _FakeUsageMetadata()


def test_gemini_alias_costs_are_recorded_with_resolved_model(monkeypatch, tmp_path):
    captured: dict[str, object] = {}

    def generate_content(*, model, contents, config):
        captured["model"] = model
        captured["config"] = config
        return _FakeResponse()

    class FakeClient:
        def __init__(self, api_key):
            self.models = SimpleNamespace(generate_content=generate_content)

    fake_types = SimpleNamespace(
        Content=lambda role, parts: SimpleNamespace(role=role, parts=parts),
        Part=lambda text: SimpleNamespace(text=text),
        GenerateContentConfig=_FakeGenerateContentConfig,
    )
    fake_genai = SimpleNamespace(Client=FakeClient, types=fake_types)

    monkeypatch.setitem(sys.modules, "google", SimpleNamespace(genai=fake_genai))
    monkeypatch.setitem(sys.modules, "google.genai", fake_genai)
    monkeypatch.setitem(sys.modules, "google.genai.types", fake_types)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("ALPHADESK_DATA_DIR", str(tmp_path))

    gemini_compat = importlib.reload(importlib.import_module("src.shared.gemini_compat"))
    cost_tracker = importlib.reload(importlib.import_module("src.shared.cost_tracker"))
    monkeypatch.setattr(cost_tracker, "_load_daily_cap", lambda: 20.0)

    client = gemini_compat.Anthropic()
    response = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=128,
        messages=[{"role": "user", "content": "hello"}],
        response_mime_type="application/json",
        temperature=0.2,
    )

    assert captured["model"] == "gemini-2.5-pro"
    assert getattr(captured["config"], "response_mime_type") == "application/json"
    assert getattr(captured["config"], "temperature") == 0.2
    assert response.model == "gemini-2.5-pro"

    cost = cost_tracker.record_usage(
        "unit_test_agent",
        response.usage.input_tokens,
        response.usage.output_tokens,
        model=response.model,
    )

    assert cost == 11.25
    assert cost_tracker.get_budget_pressure() == 11.25 / 20.0
