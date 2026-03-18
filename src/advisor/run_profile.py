"""Run-profile classification for AlphaDesk execution modes."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from src.shared.config_loader import load_config
from src.utils.logger import get_logger

log = get_logger(__name__)

RUN_TYPES = frozenset({"morning_full", "evening_wrap", "weekend"})

DEFAULT_SCHEDULE = {
    "market_days": [
        {"time": "07:00", "run_type": "morning_full", "budget_usd": 10.0},
        {"time": "19:00", "run_type": "evening_wrap", "budget_usd": 3.0},
    ],
    "weekends": [
        {"time": "10:00", "run_type": "weekend", "budget_usd": 2.0},
    ],
    "daily_cost_cap": 25.0,
}

RUN_STEP_MATRIX = {
    "morning_full": {
        "load_memory",
        "street_ear",
        "news_desk",
        "substack_ear",
        "youtube_ear",
        "sector_scanner",
        "market_data_full",
        "advisor_data",
        "holdings_monitor",
        "delta_engine",
        "decision_engine",
        "full_analyst_committee",
        "report_generation_all",
    },
    "evening_wrap": {
        "load_memory",
        "news_desk_headlines",
        "market_data_prices",
        "holdings_monitor",
        "delta_engine",
        "delta_analyst",
        "report_generation_telegram",
    },
    "weekend": {
        "load_memory",
        "thesis_review",
        "report_generation_telegram",
    },
}

REPORT_FORMATS = {
    "morning_full": "full_brief",
    "evening_wrap": "evening_summary",
    "weekend": "weekend_review",
}


@dataclass(frozen=True)
class RunProfile:
    run_type: str
    run_id: str
    market_open: bool
    hours_since_last_run: float
    run_steps: set[str]
    report_format: str
    budget_usd: float


def _load_schedule() -> dict[str, Any]:
    """Load schedule config with sane defaults."""
    try:
        config = load_config("advisor")
    except Exception:
        log.debug("Advisor config unavailable while resolving run profile", exc_info=True)
        return DEFAULT_SCHEDULE

    schedule = config.get("schedule") or {}
    merged = dict(DEFAULT_SCHEDULE)
    merged.update({k: v for k, v in schedule.items() if v is not None})
    return merged


def _parse_schedule_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize schedule entries and sort them by time."""
    normalized: list[dict[str, Any]] = []
    for entry in entries:
        run_type = entry.get("run_type")
        time_str = entry.get("time")
        if run_type not in RUN_TYPES or not time_str:
            continue
        try:
            slot_dt = datetime.strptime(time_str, "%H:%M")
        except ValueError:
            log.warning("Invalid schedule time %r for %s", time_str, run_type)
            continue
        normalized.append(
            {
                "run_type": run_type,
                "time": time_str,
                "slot": slot_dt.time(),
                "budget_usd": float(entry.get("budget_usd", 0.0) or 0.0),
            }
        )
    return sorted(normalized, key=lambda item: item["slot"])


def _select_schedule_entry(
    run_type: str,
    now: datetime,
    schedule: dict[str, Any],
) -> dict[str, Any]:
    """Resolve the relevant schedule entry for the current day/run type."""
    entry_group = "weekends" if run_type == "weekend" else "market_days"
    entries = _parse_schedule_entries(schedule.get(entry_group, []))
    matching = [entry for entry in entries if entry["run_type"] == run_type]

    if run_type != "weekend" and not matching:
        # Allow a weekend fallback if the config only declares one schedule block.
        matching = [entry for entry in _parse_schedule_entries(schedule.get("weekends", [])) if entry["run_type"] == run_type]

    if matching:
        return matching[0]

    default_entries = _parse_schedule_entries(DEFAULT_SCHEDULE["weekends" if run_type == "weekend" else "market_days"])
    for entry in default_entries:
        if entry["run_type"] == run_type:
            return entry

    raise ValueError(f"Unsupported run type: {run_type}")


def _auto_run_type(now: datetime, schedule: dict[str, Any]) -> str:
    """Infer the run type from the current day and schedule."""
    if now.weekday() >= 5:
        return "weekend"

    entries = _parse_schedule_entries(schedule.get("market_days", []))
    if not entries:
        entries = _parse_schedule_entries(DEFAULT_SCHEDULE["market_days"])

    eligible = [entry for entry in entries if entry["slot"] <= now.time()]
    if eligible:
        return eligible[-1]["run_type"]
    return entries[0]["run_type"]


def _hours_since_last_run(now: datetime) -> float:
    """Measure wall-clock time since the last recorded run."""
    try:
        from src.advisor.memory import get_latest_run_snapshot

        latest = get_latest_run_snapshot()
    except Exception:
        log.debug("Unable to load latest run snapshot for profile resolution", exc_info=True)
        return 24.0

    if not latest or not latest.get("run_id"):
        return 24.0

    try:
        last_run = datetime.strptime(latest["run_id"], "%Y-%m-%dT%H:%M")
    except ValueError:
        log.warning("Invalid run_id in run_snapshots: %s", latest.get("run_id"))
        return 24.0

    delta = now - last_run
    return round(max(delta.total_seconds(), 0.0) / 3600.0, 2)


def determine_run_profile(run_type: str = "auto", now: datetime | None = None) -> RunProfile:
    """Classify this execution and return its run metadata."""
    now = now or datetime.now()
    schedule = _load_schedule()

    resolved_run_type = run_type
    if run_type == "auto":
        resolved_run_type = _auto_run_type(now, schedule)
    if resolved_run_type not in RUN_TYPES:
        raise ValueError(f"Unsupported run_type: {run_type}")

    entry = _select_schedule_entry(resolved_run_type, now, schedule)
    slot = entry["slot"]

    run_id = f"{now.date().isoformat()}T{slot.strftime('%H:%M')}"
    budget_usd = float(entry.get("budget_usd") or 0.0)
    if budget_usd <= 0:
        budget_usd = float(
            DEFAULT_SCHEDULE["weekends"][0]["budget_usd"]
            if resolved_run_type == "weekend"
            else next(
                item["budget_usd"]
                for item in DEFAULT_SCHEDULE["market_days"]
                if item["run_type"] == resolved_run_type
            )
        )

    return RunProfile(
        run_type=resolved_run_type,
        run_id=run_id,
        market_open=now.weekday() < 5,
        hours_since_last_run=_hours_since_last_run(now),
        run_steps=set(RUN_STEP_MATRIX[resolved_run_type]),
        report_format=REPORT_FORMATS[resolved_run_type],
        budget_usd=budget_usd,
    )


def get_run_profile(
    run_type: str,
    run_id: str | None = None,
    market_open: bool | None = None,
    hours_since_last_run: float | None = None,
    budget_usd: float | None = None,
) -> RunProfile:
    """Backwards-compatible wrapper for older callers."""
    profile = determine_run_profile(run_type=run_type)
    return RunProfile(
        run_type=profile.run_type,
        run_id=run_id or profile.run_id,
        market_open=profile.market_open if market_open is None else market_open,
        hours_since_last_run=profile.hours_since_last_run if hours_since_last_run is None else hours_since_last_run,
        run_steps=profile.run_steps,
        report_format=profile.report_format,
        budget_usd=profile.budget_usd if budget_usd is None else budget_usd,
    )
