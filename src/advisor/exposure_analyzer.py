"""Portfolio exposure gap analyzer for AlphaDesk Advisor.

Compares portfolio sector/asset-class exposure against a reference basket
to surface what the portfolio is NOT exposed to. This is often the most
important analytical insight — zero-exposure gaps in rising sectors are
invisible to agents that only analyze held positions.

Also computes a portfolio-level safety score (0-100) used to gate
moonshot/speculative recommendations.
"""
from __future__ import annotations

from typing import Any

from src.utils.logger import get_logger

log = get_logger(__name__)

# Reference exposure ranges — what a diversified portfolio "should" have.
# These are not mandates; they're benchmarks for gap detection.
DEFAULT_REFERENCE_EXPOSURES = [
    {"name": "Technology/AI", "benchmark_range": [30, 50]},
    {"name": "Energy/Commodities", "benchmark_range": [5, 15]},
    {"name": "Defense/Aerospace", "benchmark_range": [3, 8]},
    {"name": "Precious Metals", "benchmark_range": [3, 10]},
    {"name": "Healthcare", "benchmark_range": [5, 15]},
    {"name": "Financials", "benchmark_range": [5, 15]},
    {"name": "Consumer", "benchmark_range": [5, 15]},
    {"name": "Industrials", "benchmark_range": [3, 10]},
    {"name": "Real Estate", "benchmark_range": [2, 8]},
    {"name": "Utilities", "benchmark_range": [2, 5]},
]

# Map yfinance sector names to our reference categories
SECTOR_MAPPING = {
    "Technology": "Technology/AI",
    "Communication Services": "Technology/AI",
    "Consumer Cyclical": "Consumer",
    "Consumer Defensive": "Consumer",
    "Energy": "Energy/Commodities",
    "Basic Materials": "Energy/Commodities",
    "Healthcare": "Healthcare",
    "Financial Services": "Financials",
    "Industrials": "Industrials",
    "Real Estate": "Real Estate",
    "Utilities": "Utilities",
}


def analyze_exposure_gaps(
    holdings_reports: list[dict],
    reference_exposures: list[dict] | None = None,
    macro_data: dict | None = None,
) -> dict[str, Any]:
    """Analyze portfolio exposure gaps against reference basket.

    Args:
        holdings_reports: Enriched holding reports with position_pct and sector.
        reference_exposures: Override reference ranges (or use defaults).
        macro_data: Current macro data (VIX, oil, etc.) for context-weighting.

    Returns:
        Dict with:
            sector_breakdown: Actual sector weights.
            gaps: List of exposure gaps (sectors at 0% or below min benchmark).
            overweights: Sectors above max benchmark.
            gap_summary: One-line summary string for the report.
            safety_score: Portfolio-level safety score (0-100).
    """
    refs = reference_exposures or DEFAULT_REFERENCE_EXPOSURES

    # Build actual sector weights from holdings
    sector_weight: dict[str, float] = {}
    total_allocated = 0.0

    for h in holdings_reports:
        pct = h.get("position_pct") or 0
        raw_sector = h.get("sector") or "Unknown"
        mapped = SECTOR_MAPPING.get(raw_sector, raw_sector)
        sector_weight[mapped] = sector_weight.get(mapped, 0) + pct
        total_allocated += pct

    # Compare against reference
    gaps: list[dict] = []
    overweights: list[dict] = []

    for ref in refs:
        name = ref["name"]
        lo, hi = ref["benchmark_range"]
        actual = sector_weight.get(name, 0)

        if actual < lo:
            severity = "critical" if actual == 0 else "warning"
            gaps.append({
                "sector": name,
                "actual_pct": round(actual, 1),
                "benchmark_min": lo,
                "benchmark_max": hi,
                "severity": severity,
            })
        elif actual > hi:
            overweights.append({
                "sector": name,
                "actual_pct": round(actual, 1),
                "benchmark_min": lo,
                "benchmark_max": hi,
            })

    # Build gap summary
    zero_sectors = [g["sector"] for g in gaps if g["actual_pct"] == 0]
    under_sectors = [g["sector"] for g in gaps if g["actual_pct"] > 0]

    parts: list[str] = []
    if zero_sectors:
        parts.append(f"Zero exposure: {', '.join(zero_sectors)}")
    if under_sectors:
        parts.append(f"Underweight: {', '.join(under_sectors)}")
    gap_summary = ". ".join(parts) if parts else "Exposure in line with benchmarks."

    # Compute safety score
    safety_score = compute_safety_score(
        holdings_reports=holdings_reports,
        gaps=gaps,
        overweights=overweights,
        macro_data=macro_data,
    )

    result = {
        "sector_breakdown": {k: round(v, 1) for k, v in sorted(
            sector_weight.items(), key=lambda x: -x[1]
        )},
        "gaps": gaps,
        "overweights": overweights,
        "gap_summary": gap_summary,
        "zero_exposure_sectors": zero_sectors,
        "safety_score": safety_score,
    }

    log.info(
        "Exposure analysis: %d gaps (%d critical), %d overweight, safety=%d",
        len(gaps), len(zero_sectors), len(overweights), safety_score,
    )
    return result


def compute_safety_score(
    holdings_reports: list[dict],
    gaps: list[dict] | None = None,
    overweights: list[dict] | None = None,
    macro_data: dict | None = None,
) -> int:
    """Compute a portfolio-level safety score (0-100, higher = safer).

    Components:
        - Concentration (HHI-based): max 30 points
        - Thesis health: max 20 points
        - Diversification (gap count): max 20 points
        - Macro environment (VIX): max 15 points
        - Drawdown levels: max 15 points
    """
    score = 0.0

    if not holdings_reports:
        return 50  # Neutral if no data

    # 1. Concentration — based on HHI (Herfindahl index)
    # HHI of 10000 = single stock, 1000 = 10 equal stocks
    weights = [h.get("position_pct", 0) for h in holdings_reports if h.get("position_pct")]
    if weights:
        hhi = sum(w**2 for w in weights)
        # Perfect diversification (10 equal = HHI 1000) → 30 pts
        # Single stock (HHI 10000) → 0 pts
        concentration_score = max(0, 30 * (1 - (hhi - 1000) / 9000))
        score += min(30, concentration_score)
    else:
        score += 15  # Neutral

    # 2. Thesis health — penalize weakening/invalidated theses
    thesis_statuses = [h.get("thesis_status", "intact") for h in holdings_reports]
    total = len(thesis_statuses) or 1
    intact_count = sum(1 for s in thesis_statuses if s in ("intact", "strengthening"))
    thesis_score = 20 * (intact_count / total)
    score += thesis_score

    # 3. Diversification — based on number of critical gaps
    gaps = gaps or []
    critical_gaps = sum(1 for g in gaps if g.get("severity") == "critical")
    # 0 critical gaps = 20 pts, each critical gap costs 5 pts
    div_score = max(0, 20 - critical_gaps * 5)
    score += div_score

    # 4. Macro environment — VIX as proxy
    macro_data = macro_data or {}
    vix = macro_data.get("vix")
    if isinstance(vix, dict):
        vix = vix.get("value")
    if vix is not None and isinstance(vix, (int, float)):
        # VIX < 15 → 15 pts, VIX 15-22 → 10 pts, VIX 22-30 → 5 pts, VIX > 30 → 0
        if vix < 15:
            score += 15
        elif vix < 22:
            score += 10
        elif vix < 30:
            score += 5
    else:
        score += 8  # Neutral if no VIX data

    # 5. Drawdown levels — penalize deep drawdowns
    drawdowns = [
        abs(h.get("drawdown_from_peak_pct") or 0)
        for h in holdings_reports
        if h.get("drawdown_from_peak_pct") is not None
    ]
    if drawdowns:
        avg_drawdown = sum(drawdowns) / len(drawdowns)
        # 0% avg drawdown → 15 pts, 20%+ → 0 pts
        dd_score = max(0, 15 * (1 - avg_drawdown / 20))
        score += dd_score
    else:
        score += 8  # Neutral

    return max(0, min(100, int(round(score))))


def format_exposure_summary(exposure_result: dict) -> str:
    """Format a one-line exposure summary for the report.

    Example: "Tech: 92% | Energy: 0% | Defense: 0% | Healthcare: 0%"
    """
    breakdown = exposure_result.get("sector_breakdown", {})
    if not breakdown:
        return ""

    # Always show top sectors + any at 0%
    zero_sectors = exposure_result.get("zero_exposure_sectors", [])
    parts: list[str] = []

    for sector, pct in breakdown.items():
        parts.append(f"{sector}: {pct:.0f}%")

    # Add zeros that aren't in breakdown
    for sector in zero_sectors:
        if sector not in breakdown:
            parts.append(f"{sector}: 0%")

    return " | ".join(parts)


def format_exposure_for_prompt(exposure_result: dict) -> str:
    """Format exposure analysis for inclusion in synthesis prompts."""
    lines: list[str] = []

    lines.append("PORTFOLIO EXPOSURE ANALYSIS")
    lines.append(f"Safety Score: {exposure_result.get('safety_score', 'N/A')}/100")
    lines.append("")

    breakdown = exposure_result.get("sector_breakdown", {})
    if breakdown:
        lines.append("Sector Weights:")
        for sector, pct in breakdown.items():
            lines.append(f"  {sector}: {pct:.1f}%")
        lines.append("")

    gaps = exposure_result.get("gaps", [])
    if gaps:
        lines.append("EXPOSURE GAPS:")
        for g in gaps:
            severity_tag = "CRITICAL" if g["severity"] == "critical" else "WARNING"
            lines.append(
                f"  [{severity_tag}] {g['sector']}: {g['actual_pct']:.1f}% "
                f"(benchmark: {g['benchmark_min']}-{g['benchmark_max']}%)"
            )
        lines.append("")

    overweights = exposure_result.get("overweights", [])
    if overweights:
        lines.append("OVERWEIGHT:")
        for o in overweights:
            lines.append(
                f"  {o['sector']}: {o['actual_pct']:.1f}% "
                f"(benchmark max: {o['benchmark_max']}%)"
            )

    return "\n".join(lines)
