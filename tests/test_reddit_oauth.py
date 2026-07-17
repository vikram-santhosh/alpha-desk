"""Reddit fetcher OAuth: authenticate when creds exist, degrade cleanly otherwise."""
from __future__ import annotations

import requests

from src.street_ear import reddit_fetcher as rf


class _Resp:
    def __init__(self, json_data: dict, status: int = 200) -> None:
        self._json = json_data
        self.status_code = status

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(f"HTTP {self.status_code}")

    def json(self) -> dict:
        return self._json


def _clear_creds(monkeypatch):
    for key in ("REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET", "REDDIT_USERNAME", "REDDIT_PASSWORD"):
        monkeypatch.delenv(key, raising=False)


def test_no_creds_stays_unauthenticated(monkeypatch):
    _clear_creds(monkeypatch)
    session = requests.Session()
    assert rf._authenticate(session) is False
    assert "Authorization" not in session.headers


def test_client_credentials_grant_sets_bearer(monkeypatch):
    _clear_creds(monkeypatch)
    monkeypatch.setenv("REDDIT_CLIENT_ID", "cid")
    monkeypatch.setenv("REDDIT_CLIENT_SECRET", "secret")
    captured: dict = {}

    def fake_post(url, auth=None, data=None, headers=None, timeout=None):
        captured.update(url=url, auth=auth, data=data)
        return _Resp({"access_token": "TESTTOKEN"})

    monkeypatch.setattr(rf.requests, "post", fake_post)
    session = requests.Session()
    assert rf._authenticate(session) is True
    assert session.headers["Authorization"] == "bearer TESTTOKEN"
    assert captured["url"] == rf.TOKEN_URL
    assert captured["auth"] == ("cid", "secret")
    assert captured["data"]["grant_type"] == "client_credentials"


def test_password_grant_when_user_and_pass_present(monkeypatch):
    _clear_creds(monkeypatch)
    monkeypatch.setenv("REDDIT_CLIENT_ID", "cid")
    monkeypatch.setenv("REDDIT_CLIENT_SECRET", "secret")
    monkeypatch.setenv("REDDIT_USERNAME", "u")
    monkeypatch.setenv("REDDIT_PASSWORD", "p")
    captured: dict = {}

    def fake_post(url, auth=None, data=None, headers=None, timeout=None):
        captured.update(data=data)
        return _Resp({"access_token": "T"})

    monkeypatch.setattr(rf.requests, "post", fake_post)
    session = requests.Session()
    assert rf._authenticate(session) is True
    assert captured["data"]["grant_type"] == "password"
    assert captured["data"]["username"] == "u"


def test_oauth_failure_degrades_to_unauthenticated(monkeypatch):
    _clear_creds(monkeypatch)
    monkeypatch.setenv("REDDIT_CLIENT_ID", "cid")
    monkeypatch.setenv("REDDIT_CLIENT_SECRET", "secret")

    def boom(*_args, **_kwargs):
        raise requests.exceptions.ConnectionError("reddit down")

    monkeypatch.setattr(rf.requests, "post", boom)
    session = requests.Session()
    assert rf._authenticate(session) is False
    assert "Authorization" not in session.headers
