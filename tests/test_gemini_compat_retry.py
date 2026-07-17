from __future__ import annotations

import importlib


class _Resp:
    def __init__(self, status_code: int, body: dict | None = None, text: str = ""):
        self.status_code = status_code
        self._body = body or {}
        self.text = text or str(body)

    def json(self):
        return self._body


def _ok_body():
    return {
        "choices": [{"message": {"content": "ok"}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }


def _load_client(monkeypatch, post_fn, api_key="test-key"):
    monkeypatch.setenv("OPENROUTER_API_KEY", api_key)
    monkeypatch.setattr("requests.post", post_fn)
    monkeypatch.setattr("time.sleep", lambda _s: None)
    gemini_compat = importlib.reload(importlib.import_module("src.shared.gemini_compat"))
    return gemini_compat


def _create(gemini_compat):
    client = gemini_compat.Anthropic()
    return client.messages.create(
        model="claude-opus-4-6", max_tokens=64, messages=[{"role": "user", "content": "hi"}]
    )


def test_retries_on_503_then_succeeds(monkeypatch):
    calls = {"n": 0}

    def fake_post(url, *, headers, json, timeout):
        calls["n"] += 1
        if calls["n"] < 3:
            return _Resp(503, text="server error")
        return _Resp(200, _ok_body())

    gemini_compat = _load_client(monkeypatch, fake_post)
    response = _create(gemini_compat)

    assert calls["n"] == 3
    assert response.content[0].text == "ok"


def test_exhausts_retries_and_raises_api_status_error(monkeypatch):
    calls = {"n": 0}

    def fake_post(url, *, headers, json, timeout):
        calls["n"] += 1
        return _Resp(500, text="boom")

    gemini_compat = _load_client(monkeypatch, fake_post)

    import pytest

    with pytest.raises(gemini_compat.APIStatusError) as exc_info:
        _create(gemini_compat)

    assert calls["n"] == gemini_compat._MAX_RETRIES + 1
    assert exc_info.value.status_code == 500


def test_client_error_fails_fast_without_retry(monkeypatch):
    calls = {"n": 0}

    def fake_post(url, *, headers, json, timeout):
        calls["n"] += 1
        return _Resp(400, text="bad request")

    gemini_compat = _load_client(monkeypatch, fake_post)

    import pytest

    with pytest.raises(gemini_compat.APIStatusError) as exc_info:
        _create(gemini_compat)

    assert calls["n"] == 1
    assert exc_info.value.status_code == 400


def test_connection_error_retries_then_succeeds(monkeypatch):
    import requests

    calls = {"n": 0}

    def fake_post(url, *, headers, json, timeout):
        calls["n"] += 1
        if calls["n"] < 2:
            raise requests.exceptions.ConnectionError("network down")
        return _Resp(200, _ok_body())

    gemini_compat = _load_client(monkeypatch, fake_post)
    response = _create(gemini_compat)

    assert calls["n"] == 2
    assert response.content[0].text == "ok"


def test_connection_error_exhausts_retries_raises_connection_error(monkeypatch):
    import requests

    def fake_post(url, *, headers, json, timeout):
        raise requests.exceptions.ConnectionError("network down")

    gemini_compat = _load_client(monkeypatch, fake_post)

    import pytest

    with pytest.raises(gemini_compat.APIConnectionError):
        _create(gemini_compat)


def test_stale_google_key_is_ignored_in_favor_of_openrouter_env(monkeypatch):
    """Regression: callers still pass a legacy GEMINI_API_KEY (a Google
    'AIza...' value) as api_key. Sending that as the OpenRouter bearer token
    yields a 401. The shim must ignore a non-OpenRouter key and use
    OPENROUTER_API_KEY from the environment instead."""
    captured: dict[str, str] = {}

    def fake_post(url, *, headers, json, timeout):
        captured["auth"] = headers["Authorization"]
        return _Resp(200, _ok_body())

    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-realkey")
    monkeypatch.setattr("requests.post", fake_post)
    gemini_compat = importlib.reload(importlib.import_module("src.shared.gemini_compat"))

    client = gemini_compat.Anthropic(api_key="AIzaSyStaleGoogleKey")
    client.messages.create(
        model="claude-opus-4-6", max_tokens=64, messages=[{"role": "user", "content": "hi"}]
    )

    assert captured["auth"] == "Bearer sk-or-v1-realkey"


def test_explicit_openrouter_key_is_honored(monkeypatch):
    captured: dict[str, str] = {}

    def fake_post(url, *, headers, json, timeout):
        captured["auth"] = headers["Authorization"]
        return _Resp(200, _ok_body())

    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-envkey")
    monkeypatch.setattr("requests.post", fake_post)
    gemini_compat = importlib.reload(importlib.import_module("src.shared.gemini_compat"))

    client = gemini_compat.Anthropic(api_key="sk-or-v1-explicitkey")
    client.messages.create(
        model="claude-opus-4-6", max_tokens=64, messages=[{"role": "user", "content": "hi"}]
    )

    assert captured["auth"] == "Bearer sk-or-v1-explicitkey"
