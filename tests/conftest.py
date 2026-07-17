"""Pytest compatibility fixtures for the local test suite."""

import asyncio
import importlib
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolate_cockpit_databases(tmp_path, monkeypatch):
    """Point every persistence store at a per-test temp dir.

    Without this, tests that save runs (idea-scout, brief, deployment) write to
    the real ``data/*.db`` files the dev cockpit reads from — a pytest run then
    clobbers the developer's "latest run" with mock fixtures (NOISY0/SHOP/CELH),
    which is exactly how stale data kept surfacing in the running UI. The store
    modules compute their ``DB_PATH`` at import time from ALPHADESK_DATA_DIR, so
    setting the env var alone isn't enough for already-imported modules; we also
    repoint each module's DB_PATH explicitly.
    """
    monkeypatch.setenv("ALPHADESK_DATA_DIR", str(tmp_path))
    for mod_name in ("src.api.run_store", "src.api.brief_store", "src.api.deployment_store"):
        try:
            mod = importlib.import_module(mod_name)
        except Exception:
            continue
        db_path = getattr(mod, "DB_PATH", None)
        if db_path is not None:
            monkeypatch.setattr(mod, "DB_PATH", tmp_path / Path(db_path).name)
    yield


@pytest.fixture(autouse=True)
def ensure_default_event_loop():
    """Provide a default event loop for sync tests on Python 3.13+.

    Several tests still call ``asyncio.get_event_loop().run_until_complete(...)``.
    Python 3.13 no longer creates an implicit loop in that case, so install one
    for each test to preserve the existing test style.
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        yield
    finally:
        if not loop.is_closed():
            loop.close()
        asyncio.set_event_loop(None)
