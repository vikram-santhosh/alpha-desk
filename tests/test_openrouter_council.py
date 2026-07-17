from __future__ import annotations

import asyncio
import importlib


def _reload_registry(monkeypatch):
    monkeypatch.setenv("COUNCIL_ENABLED", "true")
    module = importlib.import_module("src.shared.model_registry")
    return importlib.reload(module)


def test_openrouter_council_roster_defaults_to_three_models(monkeypatch):
    registry = _reload_registry(monkeypatch)

    roster = registry.enabled_roster()

    assert [spec.provider for spec in roster] == [
        registry.CouncilProvider.OPENROUTER,
        registry.CouncilProvider.OPENROUTER,
        registry.CouncilProvider.OPENROUTER,
    ]
    assert [spec.model_id for spec in roster] == [
        "z-ai/glm-5.2",
        "moonshotai/kimi-k2.6",
        "deepseek/deepseek-v4-pro",
    ]


def test_council_default_path_requires_enabled_flag(monkeypatch):
    registry = _reload_registry(monkeypatch)
    monkeypatch.setenv("COUNCIL_ENABLED", "false")
    importlib.reload(registry)
    council = importlib.reload(importlib.import_module("src.advisor.council"))

    try:
        asyncio.get_event_loop().run_until_complete(
            council.CouncilClient(timeout_s=1).deliberate(
                council.CouncilRequest(prompt="Rate NVDA"),
            )
        )
    except RuntimeError as exc:
        assert "COUNCIL_ENABLED=true" in str(exc)
    else:
        raise AssertionError("default council path should require COUNCIL_ENABLED")


def test_openrouter_council_fans_out_to_all_roster_members(monkeypatch):
    registry = _reload_registry(monkeypatch)
    council = importlib.reload(importlib.import_module("src.advisor.council"))
    calls = []

    def fake_call(self, spec, request):
        calls.append((spec.provider, request.prompt))
        return council.CouncilResponse(
            provider=spec.provider,
            model=spec.model_id,
            label=spec.label,
            text=f"{spec.label}: hold",
            input_tokens=10,
            output_tokens=5,
        )

    monkeypatch.setattr(council.CouncilClient, "_call_model", fake_call)

    roster = registry.enabled_roster()
    result = asyncio.get_event_loop().run_until_complete(
        council.CouncilClient(timeout_s=1).deliberate(
            council.CouncilRequest(prompt="Rate NVDA"),
            roster=roster,
        )
    )

    assert len(result) == 3
    assert all(item.ok for item in result)
    assert {call[0] for call in calls} == {registry.CouncilProvider.OPENROUTER}


def test_openrouter_council_surfaces_model_errors(monkeypatch):
    registry = _reload_registry(monkeypatch)
    council = importlib.reload(importlib.import_module("src.advisor.council"))

    def fake_call(self, spec, request):
        if spec.model_id == "deepseek/deepseek-v4-pro":
            raise RuntimeError("quota exhausted")
        return council.CouncilResponse(
            provider=spec.provider,
            model=spec.model_id,
            label=spec.label,
            text="ok",
        )

    monkeypatch.setattr(council.CouncilClient, "_call_model", fake_call)

    result = asyncio.get_event_loop().run_until_complete(
        council.CouncilClient(timeout_s=1).deliberate(
            council.CouncilRequest(prompt="Rate AMZN"),
            roster=registry.enabled_roster(),
        )
    )

    failures = [item for item in result if not item.ok]
    assert len(failures) == 1
    assert failures[0].model == "deepseek/deepseek-v4-pro"
    assert "quota exhausted" in failures[0].error
