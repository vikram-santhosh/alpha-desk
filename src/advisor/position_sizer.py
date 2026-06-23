"""Position sizing helpers for AlphaDesk recommendations."""
from __future__ import annotations

from typing import Any

from src.shared.schemas import Sizing
from src.utils.logger import get_logger

log = get_logger(__name__)


def size_recommendations(
    *,
    conviction_list: list[dict[str, Any]],
    moonshot_list: list[dict[str, Any]],
    holdings: list[dict[str, Any]],
    valuation_data: dict[str, dict[str, Any]],
    config: dict[str, Any],
) -> dict[str, Any]:
    """Create target sizing recommendations plus cash and concentration flags."""
    strategy = config.get("strategy", {})
    max_position_pct = float(strategy.get("max_position_pct", 15))
    moonshot_max_pct = float(strategy.get("moonshot_max_pct", 3))
    min_hold_days = int(strategy.get("min_hold_period_days", 365))
    concentration_cap = float(strategy.get("theme_concentration_threshold_pct", 50))

    current_exposure = _compute_theme_exposure(holdings)
    allocations: list[dict[str, Any]] = []

    for entry in conviction_list:
        ticker = entry.get("ticker")
        if not ticker:
            continue
        valuation = valuation_data.get(ticker, {})
        sector = _lookup_theme(ticker, holdings) or entry.get("sector") or "Unclassified"
        weight = _target_weight(
            conviction_score=_conviction_score(entry),
            margin_of_safety=valuation.get("margin_of_safety", 0),
            cap=max_position_pct,
        )
        if weight <= 0:
            continue
        sizing = Sizing(
            recommended_weight_pct=weight,
            max_weight_pct=max_position_pct,
            entry_strategy=_entry_strategy(min_hold_days),
            portfolio_impact=_portfolio_impact(sector, current_exposure.get(sector, 0.0), weight),
        )
        allocations.append({
            "ticker": ticker,
            "type": "conviction",
            "recommended_weight_pct": sizing.recommended_weight_pct,
            "max_weight_pct": sizing.max_weight_pct,
            "entry_strategy": sizing.entry_strategy,
            "portfolio_impact": sizing.portfolio_impact,
            "sizing": sizing.to_dict(),
        })

    for entry in moonshot_list:
        ticker = entry.get("ticker")
        if not ticker:
            continue
        sector = _lookup_theme(ticker, holdings) or entry.get("sector") or entry.get("archetype") or "Moonshot"
        conviction = _conviction_score(entry)
        cap = min(float(entry.get("max_position_pct") or moonshot_max_pct), moonshot_max_pct)
        weight = max(0.5, min(cap, cap * conviction))
        sizing = Sizing(
            recommended_weight_pct=round(weight, 2),
            max_weight_pct=cap,
            entry_strategy=_entry_strategy(min_hold_days, moonshot=True),
            portfolio_impact=_portfolio_impact(sector, current_exposure.get(sector, 0.0), weight),
        )
        allocations.append({
            "ticker": ticker,
            "type": "moonshot",
            "recommended_weight_pct": sizing.recommended_weight_pct,
            "max_weight_pct": sizing.max_weight_pct,
            "entry_strategy": sizing.entry_strategy,
            "portfolio_impact": sizing.portfolio_impact,
            "sizing": sizing.to_dict(),
        })

    _scale_to_caps_if_needed(allocations)
    invested_weight = round(sum(a["recommended_weight_pct"] for a in allocations), 2)
    cash_weight = round(max(0.0, 100.0 - invested_weight), 2)
    allocations.append({
        "ticker": "CASH",
        "type": "cash",
        "recommended_weight_pct": cash_weight,
        "max_weight_pct": 100.0,
        "entry_strategy": "Hold as dry powder until more names clear the gate.",
        "portfolio_impact": "Preserves optionality and dampens concentration risk.",
        "sizing": Sizing(
            recommended_weight_pct=cash_weight,
            max_weight_pct=100.0,
            entry_strategy="Hold as dry powder until more names clear the gate.",
            portfolio_impact="Preserves optionality and dampens concentration risk.",
        ).to_dict(),
    })

    concentration_flags = _concentration_flags(
        holdings,
        exposure=current_exposure,
        threshold_pct=concentration_cap,
    )

    return {
        "allocations": allocations,
        "cash_weight_pct": cash_weight,
        "concentration_flags": concentration_flags,
        "trim_suggestions": [
            trim
            for flag in concentration_flags
            for trim in flag.get("trim_suggestions", [])
        ],
    }


def _target_weight(*, conviction_score: float, margin_of_safety: float, cap: float) -> float:
    mos_score = max(0.0, min(1.0, float(margin_of_safety or 0) / 50.0))
    quality = max(0.0, min(1.0, conviction_score * 0.65 + mos_score * 0.35))
    if quality <= 0:
        return 0.0
    return round(max(1.0, min(cap, cap * quality)), 2)


def _conviction_score(entry: dict[str, Any]) -> float:
    if isinstance(entry.get("weighted_score"), (int, float)):
        return max(0.0, min(1.0, float(entry["weighted_score"])))
    level = str(entry.get("conviction", "medium")).lower()
    return {"high": 0.90, "medium": 0.65, "low": 0.35}.get(level, 0.50)


def _entry_strategy(min_hold_days: int, *, moonshot: bool = False) -> str:
    cadence = "25% starter, 25% on proof point, 50% after milestone" if moonshot else "50% now, 25% on pullback, 25% after next catalyst"
    return f"Scale in: {cadence}; minimum hold {min_hold_days} days unless thesis breaks."


def _portfolio_impact(theme: str, current_pct: float, added_pct: float) -> str:
    new_pct = min(100.0, current_pct + added_pct)
    return f"Raises {theme} exposure from {current_pct:.0f}% to {new_pct:.0f}%."


def _lookup_theme(ticker: str, holdings: list[dict[str, Any]]) -> str:
    for holding in holdings:
        if holding.get("ticker") == ticker:
            return _holding_theme(holding)
    return ""


def _holding_theme(holding: dict[str, Any]) -> str:
    return (
        holding.get("theme")
        or holding.get("sector")
        or holding.get("category")
        or "Unclassified"
    )


def _holding_weight(holding: dict[str, Any]) -> float:
    for key in ("position_pct", "weight_pct", "portfolio_pct"):
        value = holding.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    return 0.0


def _compute_theme_exposure(holdings: list[dict[str, Any]]) -> dict[str, float]:
    exposure: dict[str, float] = {}
    for holding in holdings:
        theme = _holding_theme(holding)
        exposure[theme] = exposure.get(theme, 0.0) + _holding_weight(holding)
    return {theme: round(weight, 2) for theme, weight in exposure.items()}


def _scale_to_caps_if_needed(allocations: list[dict[str, Any]]) -> None:
    total = sum(a["recommended_weight_pct"] for a in allocations)
    if total <= 100:
        return
    scale = 100 / total
    for allocation in allocations:
        allocation["recommended_weight_pct"] = round(allocation["recommended_weight_pct"] * scale, 2)
        allocation["sizing"]["recommended_weight_pct"] = allocation["recommended_weight_pct"]


def _concentration_flags(
    holdings: list[dict[str, Any]],
    *,
    exposure: dict[str, float],
    threshold_pct: float,
) -> list[dict[str, Any]]:
    flags = []
    holdings_by_theme: dict[str, list[dict[str, Any]]] = {}
    for holding in holdings:
        holdings_by_theme.setdefault(_holding_theme(holding), []).append(holding)

    for theme, weight in sorted(exposure.items(), key=lambda item: item[1], reverse=True):
        if weight <= threshold_pct:
            continue
        excess = round(weight - threshold_pct, 2)
        remaining = excess
        trims = []
        for holding in sorted(holdings_by_theme.get(theme, []), key=_holding_weight, reverse=True):
            if remaining <= 0:
                break
            current_weight = _holding_weight(holding)
            trim_pct = round(min(current_weight * 0.25, remaining), 2)
            if trim_pct <= 0:
                continue
            trims.append({
                "ticker": holding.get("ticker", ""),
                "trim_pct": trim_pct,
                "reason": f"Reduce {theme} exposure toward {threshold_pct:.0f}% cap.",
            })
            remaining = round(remaining - trim_pct, 2)
        flags.append({
            "theme": theme,
            "exposure_pct": round(weight, 2),
            "threshold_pct": threshold_pct,
            "excess_pct": excess,
            "trim_suggestions": trims,
        })
    return flags
