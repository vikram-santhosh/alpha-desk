"""Pytest compatibility fixtures for the local test suite."""

import asyncio

import pytest


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
