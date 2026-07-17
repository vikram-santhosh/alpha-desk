from __future__ import annotations

import asyncio
import importlib


def test_concurrent_same_key_coalesces_to_one_call():
    app = importlib.import_module("src.api.app")
    calls = {"n": 0}

    async def factory():
        calls["n"] += 1
        await asyncio.sleep(0.05)
        return calls["n"]

    async def scenario():
        results = await asyncio.gather(
            app._run_singleflight("k", factory),
            app._run_singleflight("k", factory),
            app._run_singleflight("k", factory),
        )
        return results

    results = asyncio.new_event_loop().run_until_complete(scenario())
    assert calls["n"] == 1
    assert results == [1, 1, 1]


def test_different_keys_run_independently():
    app = importlib.import_module("src.api.app")
    calls = {"a": 0, "b": 0}

    async def factory_a():
        calls["a"] += 1
        await asyncio.sleep(0.02)
        return "a"

    async def factory_b():
        calls["b"] += 1
        await asyncio.sleep(0.02)
        return "b"

    async def scenario():
        return await asyncio.gather(
            app._run_singleflight("key-a", factory_a),
            app._run_singleflight("key-b", factory_b),
        )

    results = asyncio.new_event_loop().run_until_complete(scenario())
    assert calls == {"a": 1, "b": 1}
    assert results == ["a", "b"]


def test_sequential_calls_after_completion_each_invoke_factory():
    app = importlib.import_module("src.api.app")
    calls = {"n": 0}

    async def factory():
        calls["n"] += 1
        return calls["n"]

    async def scenario():
        first = await app._run_singleflight("seq", factory)
        second = await app._run_singleflight("seq", factory)
        return first, second

    results = asyncio.new_event_loop().run_until_complete(scenario())
    assert calls["n"] == 2
    assert results == (1, 2)


def test_exception_propagates_to_all_waiters_without_caching_error():
    app = importlib.import_module("src.api.app")
    calls = {"n": 0}

    async def failing_factory():
        calls["n"] += 1
        await asyncio.sleep(0.02)
        raise ValueError("boom")

    async def scenario():
        results = await asyncio.gather(
            app._run_singleflight("err", failing_factory),
            app._run_singleflight("err", failing_factory),
            return_exceptions=True,
        )
        return results

    results = asyncio.new_event_loop().run_until_complete(scenario())
    assert calls["n"] == 1
    assert all(isinstance(r, ValueError) for r in results)
