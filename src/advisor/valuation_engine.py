"""Valuation engine for AlphaDesk Advisor.

Computes 3-year target prices using scenario analysis, CAGR calculations,
and margin-of-safety checks. Implements the 25% CAGR gate that filters
all portfolio addition recommendations.
"""
from __future__ import annotations

from src.utils.logger import get_logger

log = get_logger(__name__)

DEFAULT_GATE_BY_ROLE = {
    "growth": {"min_cagr_pct": 25.0, "min_mos_pct": 15.0},
    "ballast": {"min_cagr_pct": 10.0, "min_mos_pct": 10.0, "use_total_return": True},
    "defensive": {"min_cagr_pct": 10.0, "min_mos_pct": 10.0, "use_total_return": True},
    "moonshot": {"exempt": True},
}


def compute_cagr(current_price: float, target_price: float, years: int = 3) -> float:
    """Compute compound annual growth rate.

    Args:
        current_price: Current stock price.
        target_price: Projected future price.
        years: Time horizon in years.

    Returns:
        CAGR as a percentage (e.g. 25.0 for 25%).
    """
    if current_price <= 0 or target_price <= 0 or years <= 0:
        return 0.0
    return ((target_price / current_price) ** (1.0 / years) - 1) * 100


def compute_target_price(
    ticker: str,
    fundamentals: dict,
    earnings_data: dict | None = None,
) -> dict:
    """Compute 3-year target price using scenario analysis.

    Uses current revenue, growth rate, margins, and P/E to project bull/base/bear
    scenarios and a weighted-average target price.

    Args:
        ticker: Stock ticker symbol.
        fundamentals: Fundamentals dict from fundamental_analyzer.fetch_fundamentals.
        earnings_data: Optional earnings call data with guidance fields.

    Returns:
        Dict with target_price, implied_cagr, margin_of_safety, scenario targets,
        and passes_cagr_gate flag.  If data is insufficient, returns
        {insufficient_data: True, reason: "..."}.
    """
    current_price = fundamentals.get("current_price")
    revenue = fundamentals.get("revenue")
    revenue_growth = fundamentals.get("revenue_growth")
    pe = fundamentals.get("pe_trailing") or fundamentals.get("pe_forward")
    net_margin = fundamentals.get("net_margin")

    # Try to pull guidance growth from earnings data
    guidance_growth = None
    if earnings_data:
        rev_low = earnings_data.get("guidance_revenue_low")
        rev_high = earnings_data.get("guidance_revenue_high")
        rev_actual = earnings_data.get("revenue_actual")
        if rev_low and rev_high and rev_actual and rev_actual > 0:
            mid_guidance = (rev_low + rev_high) / 2
            guidance_growth = (mid_guidance - rev_actual) / rev_actual

    # Validate minimum required data
    if current_price is None or current_price <= 0:
        return {"insufficient_data": True, "reason": f"{ticker}: missing current price"}

    if revenue is None or revenue <= 0:
        return {"insufficient_data": True, "reason": f"{ticker}: missing revenue data"}

    if revenue_growth is None and guidance_growth is None:
        return {"insufficient_data": True, "reason": f"{ticker}: missing growth rate"}

    if pe is None or pe <= 0:
        return {"insufficient_data": True, "reason": f"{ticker}: missing P/E ratio"}

    if net_margin is None:
        return {"insufficient_data": True, "reason": f"{ticker}: missing net margin"}

    # Use best available growth rate
    base_growth = guidance_growth if guidance_growth is not None else revenue_growth

    # Shares implied from market data
    eps = fundamentals.get("eps_trailing") or fundamentals.get("eps_forward")
    if eps and eps > 0:
        shares_implied = revenue * net_margin / eps
    else:
        # Estimate shares from market cap
        market_cap = fundamentals.get("market_cap")
        if market_cap and market_cap > 0:
            shares_implied = market_cap / current_price
        else:
            return {"insufficient_data": True, "reason": f"{ticker}: cannot determine share count"}

    if shares_implied <= 0:
        return {"insufficient_data": True, "reason": f"{ticker}: invalid share count"}

    # --- Scenario analysis (3-year projection) ---

    # Bull case: growth continues at recent pace + margin expansion (+2pp)
    bull_growth = base_growth
    bull_margin = min(net_margin + 0.02, 0.50)  # cap at 50%
    bull_pe = pe * 1.1  # slight multiple expansion

    bull_revenue_3y = revenue * (1 + bull_growth) ** 3
    bull_earnings_3y = bull_revenue_3y * bull_margin
    bull_eps_3y = bull_earnings_3y / shares_implied
    bull_target = bull_eps_3y * bull_pe

    # Base case: growth moderates (80% of recent pace)
    base_growth_rate = base_growth * 0.8
    base_margin = net_margin  # margins hold
    base_pe = pe  # multiple holds

    base_revenue_3y = revenue * (1 + base_growth_rate) ** 3
    base_earnings_3y = base_revenue_3y * base_margin
    base_eps_3y = base_earnings_3y / shares_implied
    base_target = base_eps_3y * base_pe

    # Bear case: growth disappoints (50% of recent pace), margins compress (-2pp)
    bear_growth_rate = base_growth * 0.5
    bear_margin = max(net_margin - 0.02, 0.01)  # floor at 1%
    bear_pe = pe * 0.85  # multiple compression

    bear_revenue_3y = revenue * (1 + bear_growth_rate) ** 3
    bear_earnings_3y = bear_revenue_3y * bear_margin
    bear_eps_3y = bear_earnings_3y / shares_implied
    bear_target = bear_eps_3y * bear_pe

    # Weighted average: 25% bull, 50% base, 25% bear
    target_price = 0.25 * bull_target + 0.50 * base_target + 0.25 * bear_target

    # Guard against nonsensical targets
    if target_price <= 0:
        return {"insufficient_data": True, "reason": f"{ticker}: computed target is non-positive"}

    implied_cagr = compute_cagr(current_price, target_price, years=3)
    margin_of_safety = (target_price - current_price) / current_price * 100 if current_price > 0 else 0.0

    result = {
        "ticker": ticker,
        "current_price": round(current_price, 2),
        "target_price": round(target_price, 2),
        "implied_cagr": round(implied_cagr, 1),
        "margin_of_safety": round(margin_of_safety, 1),
        "passes_cagr_gate": implied_cagr >= 25.0,
        "bull_target": round(bull_target, 2),
        "base_target": round(base_target, 2),
        "bear_target": round(bear_target, 2),
        "growth_rate_used": round(base_growth * 100, 1),
        "insufficient_data": False,
    }

    log.info(
        "%s valuation: target=$%.2f, CAGR=%.1f%%, MoS=%.1f%%, gate=%s",
        ticker, target_price, implied_cagr, margin_of_safety,
        "PASS" if result["passes_cagr_gate"] else "FAIL",
    )
    return result


def passes_investment_gate(
    valuation: dict,
    min_cagr: float | None = 25.0,
    min_mos: float | None = 15.0,
    *,
    role: str = "growth",
    gate_by_role: dict | None = None,
    dividend_yield: float | None = None,
) -> tuple[bool, str]:
    """Check if a valuation passes the investment gate.

    Args:
        valuation: Output from compute_target_price.
        min_cagr: Minimum required CAGR percentage.
        min_mos: Minimum required margin of safety percentage.
        role: Portfolio role/category for role-dependent thresholds.
        gate_by_role: Optional config table keyed by role.
        dividend_yield: Optional dividend yield, decimal or percentage.

    Returns:
        Tuple of (passes, reason).
    """
    if valuation.get("insufficient_data"):
        reason = valuation.get("reason", "insufficient data")
        return False, f"Cannot evaluate: {reason}"

    role_key = _normalize_role(role)
    thresholds = _thresholds_for_role(
        role_key,
        gate_by_role=gate_by_role,
        fallback_min_cagr=min_cagr,
        fallback_min_mos=min_mos,
    )
    if thresholds.get("exempt"):
        return True, f"PASS: {role_key} role is exempt from the standard valuation gate"

    min_cagr = float(thresholds.get("min_cagr_pct", 25.0))
    min_mos = float(thresholds.get("min_mos_pct", 15.0))

    cagr = valuation.get("implied_cagr", 0)
    mos = valuation.get("margin_of_safety", 0)
    dividend = _normalize_dividend_yield(
        dividend_yield if dividend_yield is not None else valuation.get("dividend_yield")
    )
    return_measure = cagr
    return_label = "CAGR"
    if thresholds.get("use_total_return") or role_key in {"ballast", "defensive", "income"}:
        return_measure = cagr + dividend
        return_label = "total return"

    cagr_ok = return_measure >= min_cagr
    mos_ok = mos >= min_mos

    if cagr_ok and mos_ok:
        return True, (
            f"PASS ({role_key}): {return_measure:.1f}% {return_label} "
            f"(>={min_cagr}%) and {mos:.1f}% margin of safety (>={min_mos}%)"
        )

    reasons = []
    if not cagr_ok:
        if return_label == "total return" and dividend:
            reasons.append(
                f"Total return {return_measure:.1f}% "
                f"(CAGR {cagr:.1f}% + dividend {dividend:.1f}%) < {min_cagr}% minimum"
            )
        else:
            reasons.append(f"{return_label.title()} {return_measure:.1f}% < {min_cagr}% minimum")
    if not mos_ok:
        reasons.append(f"Margin of safety {mos:.1f}% < {min_mos}% minimum")

    return False, f"FAIL ({role_key}): {'; '.join(reasons)}"


def _normalize_role(role: str | None) -> str:
    role_key = (role or "growth").strip().lower()
    aliases = {
        "core": "growth",
        "new_position": "growth",
        "income": "ballast",
        "etf": "ballast",
    }
    return aliases.get(role_key, role_key)


def _thresholds_for_role(
    role: str,
    *,
    gate_by_role: dict | None,
    fallback_min_cagr: float | None,
    fallback_min_mos: float | None,
) -> dict:
    table = {**DEFAULT_GATE_BY_ROLE, **(gate_by_role or {})}
    thresholds = dict(table.get(role) or table.get("growth") or DEFAULT_GATE_BY_ROLE["growth"])
    if fallback_min_cagr is not None and not gate_by_role:
        thresholds["min_cagr_pct"] = fallback_min_cagr
    if fallback_min_mos is not None and not gate_by_role:
        thresholds["min_mos_pct"] = fallback_min_mos
    return thresholds


def _normalize_dividend_yield(value: float | None) -> float:
    if value is None:
        return 0.0
    try:
        dividend = float(value)
    except (TypeError, ValueError):
        return 0.0
    if dividend <= 0:
        return 0.0
    return dividend * 100 if dividend <= 1 else dividend
