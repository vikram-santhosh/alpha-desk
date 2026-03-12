"""Shared agent wrappers for cost tracking, timing, and JSON extraction."""
from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from functools import wraps
from typing import Any, TypeVar

from src.shared.cost_tracker import check_budget, record_usage
from src.utils.logger import get_logger

log = get_logger(__name__)

F = TypeVar("F", bound=Callable[..., Awaitable[Any]])


class UsageLike:
    input_tokens: int
    output_tokens: int


def strip_markdown_fences(text: str) -> str:
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        first_newline = cleaned.find("\n")
        if first_newline != -1:
            cleaned = cleaned[first_newline + 1 :]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3].strip()
    return cleaned


def repair_json_text(text: str) -> str:
    candidate = strip_markdown_fences(text)
    if not candidate:
        return "{}"

    open_braces = candidate.count("{") - candidate.count("}")
    open_brackets = candidate.count("[") - candidate.count("]")
    repaired = candidate.rstrip().rstrip(",")
    if open_brackets > 0:
        repaired += "]" * open_brackets
    if open_braces > 0:
        repaired += "}" * open_braces
    return repaired


def extract_json_payload(text: str, default: Any = None) -> Any:
    cleaned = strip_markdown_fences(text)
    if not cleaned:
        return {} if default is None else default

    for candidate in (cleaned, repair_json_text(cleaned)):
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue

    last_object = cleaned.rfind("}")
    if last_object > 0:
        try:
            return json.loads(cleaned[: last_object + 1])
        except json.JSONDecodeError:
            pass

    return {} if default is None else default


def track_agent(name: str, budget: float | None = None) -> Callable[[F], F]:
    """Wrap an async agent function with budget, timing, and usage accounting.

    The wrapped function may return:
    - a dict containing ``text``/``raw_text`` and ``usage``/``model`` metadata
    - a dict containing ``data`` and optional ``usage``/``model`` metadata
    - any other JSON-serialisable payload
    """

    def decorator(func: F) -> F:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> dict[str, Any]:
            within_budget, spent, cap = check_budget(run_budget=budget)
            if not within_budget:
                log.warning("%s skipped: budget exceeded (%.2f / %.2f)", name, spent, cap)
                return {
                    "data": {},
                    "agent": name,
                    "cost_usd": 0.0,
                    "elapsed_s": 0.0,
                    "error": "budget_exceeded",
                }

            started = time.monotonic()
            try:
                result = await func(*args, **kwargs)
                elapsed = round(time.monotonic() - started, 3)

                if isinstance(result, dict):
                    usage = result.get("usage")
                    model = result.get("model")
                    raw_text = result.get("text") or result.get("raw_text")
                    data = result.get("data")
                    metadata = {
                        key: value
                        for key, value in result.items()
                        if key not in {"usage", "model", "text", "raw_text", "data"}
                    }
                else:
                    usage = None
                    model = None
                    raw_text = None
                    data = result
                    metadata = {}

                if data is None and raw_text is not None:
                    data = extract_json_payload(raw_text, default={})

                cost = 0.0
                if usage is not None:
                    input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
                    output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
                    cost = record_usage(name, input_tokens, output_tokens, model=model)

                envelope = {
                    "data": data if data is not None else {},
                    "agent": name,
                    "cost_usd": round(cost, 4),
                    "elapsed_s": elapsed,
                }
                if raw_text is not None:
                    envelope["raw_text"] = raw_text
                if model is not None:
                    envelope["model"] = model
                if metadata:
                    envelope.update(metadata)
                return envelope
            except Exception as exc:
                elapsed = round(time.monotonic() - started, 3)
                log.exception("%s failed", name)
                return {
                    "data": {},
                    "agent": name,
                    "cost_usd": 0.0,
                    "elapsed_s": elapsed,
                    "error": str(exc),
                }

        return wrapper  # type: ignore[return-value]

    return decorator


async def to_thread_call(func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Run a blocking callable in a worker thread."""
    return await asyncio.to_thread(func, *args, **kwargs)
