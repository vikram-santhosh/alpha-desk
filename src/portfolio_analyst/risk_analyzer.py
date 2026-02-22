"""Risk analysis engine for AlphaDesk Portfolio Analyst.

Evaluates portfolio concentration, sector exposure, total P&L, and
cross-references signals from other agents with current holdings.
"""

from typing import Any

from src.shared.agent_bus import publish
from src.utils.logger import get_logger

log = get_logger(__name__)

SOURCE_AGENT = "portfolio_analyst"

# Thresholds
CONCENTRATION_THRESHOLD_PCT = 30.0
SECTOR_THRESHOLD_PCT = 50.0


def analyze_concentration(
    holdings: list[dict[str, Any]], prices: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """Compute position weights and flag concentrated positions.

    A position is flagged if it represents more than 30% of total
    portfolio value. Flagged positions are published as
    "concentration_warning" to the agent bus.

    Args:
        holdings: List of holding dicts with keys: ticker, shares, cost_basis.
        prices: Dict of ticker -> {price, ...} from price_fetcher.

    Returns:
        Dict with positions list (ticker, value, weight_pct) and
        warnings list.
    """
    positions: list[dict[str, Any]] = []
    total_value = 0.0

    for h in holdings:
        ticker = h["ticker"]
        shares = h["shares"]
        price_data = prices.get(ticker)

        if price_data is None:
            log.warning("No price data for %s — excluding from concentration analysis", ticker)
            continue

        current_price = price_data["price"]
        position_value = shares * current_price
        total_value += position_value

        positions.append({
            "ticker": ticker,
            "shares": shares,
            "price": current_price,
            "value": round(position_value, 2),
        })

    # Compute weights
    warnings: list[str] = []
    for pos in positions:
        weight = (pos["value"] / total_value * 100) if total_value > 0 else 0.0
        pos["weight_pct"] = round(weight, 2)

        if weight > CONCENTRATION_THRESHOLD_PCT:
            msg = f"{pos['ticker']} is {weight:.1f}% of portfolio (>${CONCENTRATION_THRESHOLD_PCT:.0f}% threshold)"
            warnings.append(msg)

    # Publish warnings
    if warnings:
        try:
            publish(
                signal_type="concentration_warning",
                source_agent=SOURCE_AGENT,
                payload={"warnings": warnings, "total_value": round(total_value, 2)},
            )
        except Exception:
            log.exception("Failed to publish concentration_warning")

    # Sort positions by weight descending
    positions.sort(key=lambda p: p["weight_pct"], reverse=True)

    log.info(
        "Concentration analysis: %d positions, total $%.2f, %d warnings",
        len(positions),
        total_value,
        len(warnings),
    )

    return {
        "positions": positions,
        "total_value": round(total_value, 2),
        "warnings": warnings,
    }


def analyze_sector_exposure(
    fundamentals: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Group holdings by sector and flag overexposure (> 50%).

    Args:
        fundamentals: Dict of ticker -> fundamentals from fundamental_analyzer.

    Returns:
        Dict with sectors mapping (sector -> {tickers, count, pct}) and
        warnings list.
    """
    sector_tickers: dict[str, list[str]] = {}

    for ticker, data in fundamentals.items():
        sector = data.get("sector") or "Unknown"
        sector_tickers.setdefault(sector, []).append(ticker)

    total_tickers = sum(len(t) for t in sector_tickers.values())
    sectors: dict[str, dict[str, Any]] = {}
    warnings: list[str] = []

    for sector, tickers in sorted(sector_tickers.items(), key=lambda x: -len(x[1])):
        pct = (len(tickers) / total_tickers * 100) if total_tickers > 0 else 0.0
        sectors[sector] = {
            "tickers": tickers,
            "count": len(tickers),
            "pct": round(pct, 1),
        }

        if pct > SECTOR_THRESHOLD_PCT:
            warnings.append(f"{sector} sector is {pct:.1f}% of tracked tickers (>{SECTOR_THRESHOLD_PCT:.0f}% threshold)")

    log.info(
        "Sector exposure: %d sectors, %d warnings",
        len(sectors),
        len(warnings),
    )

    return {
        "sectors": sectors,
        "total_tickers": total_tickers,
        "warnings": warnings,
    }


def compute_portfolio_summary(
    holdings: list[dict[str, Any]], prices: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """Compute total portfolio value, cost basis, and P&L.

    Args:
        holdings: List of holding dicts with keys: ticker, shares, cost_basis.
        prices: Dict of ticker -> {price, ...} from price_fetcher.

    Returns:
        Dict with total_value, total_cost, total_pnl, total_pnl_pct,
        and per-holding breakdowns.
    """
    total_value = 0.0
    total_cost = 0.0
    holding_details: list[dict[str, Any]] = []

    for h in holdings:
        ticker = h["ticker"]
        shares = h["shares"]
        cost_basis = h["cost_basis"]
        total_cost_for_pos = shares * cost_basis
        total_cost += total_cost_for_pos

        price_data = prices.get(ticker)
        if price_data is None:
            log.warning("No price for %s — using cost basis for summary", ticker)
            current_price = cost_basis
            day_change = 0.0
            day_change_pct = 0.0
        else:
            current_price = price_data["price"]
            day_change = price_data["change"]
            day_change_pct = price_data["change_pct"]

        current_value = shares * current_price
        total_value += current_value

        pnl = current_value - total_cost_for_pos
        pnl_pct = (pnl / total_cost_for_pos * 100) if total_cost_for_pos > 0 else 0.0

        holding_details.append({
            "ticker": ticker,
            "shares": shares,
            "cost_basis": cost_basis,
            "current_price": round(current_price, 2),
            "current_value": round(current_value, 2),
            "pnl": round(pnl, 2),
            "pnl_pct": round(pnl_pct, 2),
            "day_change": round(day_change, 2),
            "day_change_pct": round(day_change_pct, 2),
        })

    total_pnl = total_value - total_cost
    total_pnl_pct = (total_pnl / total_cost * 100) if total_cost > 0 else 0.0

    log.info(
        "Portfolio summary: value=$%.2f, cost=$%.2f, P&L=$%.2f (%.2f%%)",
        total_value,
        total_cost,
        total_pnl,
        total_pnl_pct,
    )

    return {
        "total_value": round(total_value, 2),
        "total_cost": round(total_cost, 2),
        "total_pnl": round(total_pnl, 2),
        "total_pnl_pct": round(total_pnl_pct, 2),
        "holdings": holding_details,
    }


def integrate_signals(
    agent_bus_signals: list[dict[str, Any]],
    technicals: dict[str, dict[str, Any]],
    fundamentals: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Cross-reference signals from other agents with portfolio data.

    Merges external signals (e.g. from street_ear, news_desk) with
    technical and fundamental analysis to produce an integrated list
    of actionable insights.

    Args:
        agent_bus_signals: Signals consumed from the agent bus
            (from street_ear, news_desk, etc.).
        technicals: Dict of ticker -> technical analysis results.
        fundamentals: Dict of ticker -> fundamental data.

    Returns:
        List of integrated signal dicts with context from technicals
        and fundamentals appended where available.
    """
    integrated: list[dict[str, Any]] = []

    for signal in agent_bus_signals:
        payload = signal.get("payload", {})
        ticker = payload.get("ticker")

        enriched: dict[str, Any] = {
            "signal_id": signal.get("id"),
            "signal_type": signal.get("signal_type"),
            "source_agent": signal.get("source_agent"),
            "timestamp": signal.get("timestamp"),
            "payload": payload,
            "technical_context": None,
            "fundamental_context": None,
        }

        # Attach technical context if we have analysis for this ticker
        if ticker and ticker in technicals:
            tech = technicals[ticker]
            enriched["technical_context"] = {
                "signals": tech.get("signals_summary", []),
                "rsi": tech.get("rsi", {}).get("rsi"),
            }

        # Attach fundamental context if we have data for this ticker
        if ticker and ticker in fundamentals:
            fund = fundamentals[ticker]
            enriched["fundamental_context"] = {
                "pe_trailing": fund.get("pe_trailing"),
                "market_cap": fund.get("market_cap"),
                "sector": fund.get("sector"),
            }

        integrated.append(enriched)

    log.info(
        "Integrated %d external signals with portfolio context",
        len(integrated),
    )
    return integrated
