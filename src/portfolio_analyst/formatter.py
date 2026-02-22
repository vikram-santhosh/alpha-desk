"""Telegram HTML formatter for AlphaDesk Portfolio Analyst.

Produces Telegram-compatible HTML output with sections for portfolio
summary, holdings table, technical alerts, fundamental highlights,
and risk dashboard. Uses emoji coding for quick visual scanning.
"""

from typing import Any

from src.shared.security import sanitize_html
from src.utils.logger import get_logger

log = get_logger(__name__)

# Emoji constants for Telegram display
GREEN_CIRCLE = "\U0001f7e2"   # Profit / bullish
RED_CIRCLE = "\U0001f534"     # Loss / bearish
YELLOW_CIRCLE = "\U0001f7e1"  # Caution / neutral
WARNING = "\u26a0\ufe0f"       # Warning
CHART_UP = "\U0001f4c8"       # Chart increasing
CHART_DOWN = "\U0001f4c9"     # Chart decreasing
SHIELD = "\U0001f6e1\ufe0f"   # Risk/protection


def _pnl_emoji(value: float) -> str:
    """Return green, red, or yellow emoji based on P&L value."""
    if value > 0:
        return GREEN_CIRCLE
    elif value < 0:
        return RED_CIRCLE
    return YELLOW_CIRCLE


def _sign_str(value: float) -> str:
    """Format a number with a leading + for positives."""
    return f"+{value:,.2f}" if value >= 0 else f"{value:,.2f}"


def format_portfolio_summary(summary: dict[str, Any]) -> str:
    """Format the portfolio summary section.

    Args:
        summary: Dict from risk_analyzer.compute_portfolio_summary().

    Returns:
        Telegram HTML string.
    """
    pnl = summary.get("total_pnl", 0)
    pnl_pct = summary.get("total_pnl_pct", 0)
    emoji = _pnl_emoji(pnl)

    lines = [
        f"{CHART_UP} <b>Portfolio Summary</b>",
        "",
        f"Total Value:  <b>${summary.get('total_value', 0):,.2f}</b>",
        f"Total Cost:   ${summary.get('total_cost', 0):,.2f}",
        f"P&amp;L:         {emoji} <b>{_sign_str(pnl)}</b> ({_sign_str(pnl_pct)}%)",
    ]

    return "\n".join(lines)


def format_holdings_table(summary: dict[str, Any]) -> str:
    """Format the holdings table using monospace code blocks.

    Args:
        summary: Dict from risk_analyzer.compute_portfolio_summary().

    Returns:
        Telegram HTML string with aligned columns.
    """
    holdings = summary.get("holdings", [])
    if not holdings:
        return "<b>Holdings</b>\nNo holdings data available."

    lines = ["<b>Holdings</b>", "<code>"]

    # Header
    lines.append(
        f"{'Ticker':<6} {'Price':>8} {'Chg%':>7} {'P&L':>10} {'P&L%':>7}"
    )
    lines.append("-" * 42)

    for h in holdings:
        ticker = sanitize_html(h.get("ticker", "???"))
        price = h.get("current_price", 0)
        day_chg_pct = h.get("day_change_pct", 0)
        pnl = h.get("pnl", 0)
        pnl_pct = h.get("pnl_pct", 0)

        lines.append(
            f"{ticker:<6} {price:>8.2f} {day_chg_pct:>+6.2f}% {pnl:>+10.2f} {pnl_pct:>+6.2f}%"
        )

    lines.append("</code>")
    return "\n".join(lines)


def format_technical_alerts(technicals: dict[str, dict[str, Any]]) -> str:
    """Format technical analysis alerts section.

    Args:
        technicals: Dict of ticker -> analysis result from
            technical_analyzer.analyze_all().

    Returns:
        Telegram HTML string. Empty string if no signals found.
    """
    alert_lines: list[str] = []

    for ticker, data in technicals.items():
        signals = data.get("signals_summary", [])
        if not signals:
            continue

        safe_ticker = sanitize_html(ticker)
        for signal in signals:
            safe_signal = sanitize_html(signal)

            # Choose emoji based on signal content
            if any(kw in signal.lower() for kw in ["bullish", "golden", "oversold"]):
                emoji = GREEN_CIRCLE
            elif any(kw in signal.lower() for kw in ["bearish", "death", "overbought"]):
                emoji = RED_CIRCLE
            else:
                emoji = YELLOW_CIRCLE

            alert_lines.append(f"  {emoji} <b>{safe_ticker}</b>: {safe_signal}")

    if not alert_lines:
        return ""

    header = f"{CHART_UP} <b>Technical Alerts</b>"
    return "\n".join([header, ""] + alert_lines)


def format_fundamental_highlights(
    fundamentals: dict[str, dict[str, Any]],
    alerts: list[dict[str, Any]],
) -> str:
    """Format fundamental highlights section.

    Args:
        fundamentals: Dict of ticker -> fundamentals from
            fundamental_analyzer.fetch_all_fundamentals().
        alerts: List of alert dicts from
            fundamental_analyzer.detect_fundamental_alerts().

    Returns:
        Telegram HTML string. Empty string if no alerts.
    """
    if not alerts:
        return ""

    lines = [f"{CHART_DOWN} <b>Fundamental Highlights</b>", ""]

    # Group alerts by ticker
    by_ticker: dict[str, list[str]] = {}
    for alert in alerts:
        t = alert.get("ticker", "???")
        by_ticker.setdefault(t, []).append(alert.get("message", ""))

    for ticker, messages in by_ticker.items():
        safe_ticker = sanitize_html(ticker)
        fund = fundamentals.get(ticker, {})
        pe = fund.get("pe_trailing")
        pe_str = f"P/E {pe:.1f}" if pe is not None else "P/E n/a"

        lines.append(f"  {WARNING} <b>{safe_ticker}</b> ({pe_str})")
        for msg in messages:
            lines.append(f"      - {sanitize_html(msg)}")

    return "\n".join(lines)


def format_risk_dashboard(
    concentration: dict[str, Any],
    sector_exposure: dict[str, Any],
) -> str:
    """Format the risk dashboard section.

    Args:
        concentration: Dict from risk_analyzer.analyze_concentration().
        sector_exposure: Dict from risk_analyzer.analyze_sector_exposure().

    Returns:
        Telegram HTML string.
    """
    lines = [f"{SHIELD} <b>Risk Dashboard</b>", ""]

    # Concentration warnings
    conc_warnings = concentration.get("warnings", [])
    if conc_warnings:
        lines.append("<b>Concentration</b>")
        for w in conc_warnings:
            lines.append(f"  {WARNING} {sanitize_html(w)}")
        lines.append("")

    # Top positions by weight
    positions = concentration.get("positions", [])
    if positions:
        lines.append("<b>Position Weights</b>")
        lines.append("<code>")
        for pos in positions[:5]:  # Top 5
            ticker = sanitize_html(pos.get("ticker", "???"))
            weight = pos.get("weight_pct", 0)
            bar_len = int(weight / 5)  # Scale for display
            bar = "\u2588" * bar_len
            lines.append(f"  {ticker:<6} {weight:>5.1f}% {bar}")
        lines.append("</code>")
        lines.append("")

    # Sector exposure
    sector_warnings = sector_exposure.get("warnings", [])
    if sector_warnings:
        lines.append("<b>Sector Exposure</b>")
        for w in sector_warnings:
            lines.append(f"  {WARNING} {sanitize_html(w)}")
        lines.append("")

    sectors = sector_exposure.get("sectors", {})
    if sectors:
        if not sector_warnings:
            lines.append("<b>Sector Exposure</b>")
        lines.append("<code>")
        for sector, data in sectors.items():
            safe_sector = sanitize_html(sector)
            pct = data.get("pct", 0)
            count = data.get("count", 0)
            lines.append(f"  {safe_sector:<20} {count:>2} ({pct:.0f}%)")
        lines.append("</code>")

    return "\n".join(lines)


def format_integrated_signals(
    integrated: list[dict[str, Any]],
) -> str:
    """Format integrated signals from other agents.

    Args:
        integrated: List from risk_analyzer.integrate_signals().

    Returns:
        Telegram HTML string. Empty string if no signals.
    """
    if not integrated:
        return ""

    lines = [f"{WARNING} <b>Cross-Agent Signals</b>", ""]

    for sig in integrated:
        source = sanitize_html(sig.get("source_agent", "unknown"))
        sig_type = sanitize_html(sig.get("signal_type", "unknown"))
        payload = sig.get("payload", {})
        ticker = payload.get("ticker", "")
        safe_ticker = sanitize_html(ticker) if ticker else ""

        summary_parts = []
        if safe_ticker:
            summary_parts.append(f"<b>{safe_ticker}</b>")
        summary_parts.append(f"[{source}/{sig_type}]")

        # Include a brief description from payload
        description = payload.get("summary") or payload.get("title") or payload.get("text", "")
        if description:
            summary_parts.append(sanitize_html(str(description)[:120]))

        lines.append(f"  {YELLOW_CIRCLE} " + " ".join(summary_parts))

        # Append technical context
        tech_ctx = sig.get("technical_context")
        if tech_ctx and tech_ctx.get("signals"):
            for ts in tech_ctx["signals"][:2]:
                lines.append(f"      {CHART_UP} {sanitize_html(ts)}")

    return "\n".join(lines)


def format_full_report(
    portfolio_summary: dict[str, Any],
    technicals: dict[str, dict[str, Any]],
    fundamentals: dict[str, dict[str, Any]],
    fundamental_alerts: list[dict[str, Any]],
    concentration: dict[str, Any],
    sector_exposure: dict[str, Any],
    integrated_signals: list[dict[str, Any]],
) -> str:
    """Assemble the full Portfolio Analyst report for Telegram.

    Args:
        portfolio_summary: From risk_analyzer.compute_portfolio_summary().
        technicals: From technical_analyzer.analyze_all().
        fundamentals: From fundamental_analyzer.fetch_all_fundamentals().
        fundamental_alerts: From fundamental_analyzer.detect_fundamental_alerts().
        concentration: From risk_analyzer.analyze_concentration().
        sector_exposure: From risk_analyzer.analyze_sector_exposure().
        integrated_signals: From risk_analyzer.integrate_signals().

    Returns:
        Complete Telegram HTML report string.
    """
    sections: list[str] = []

    # Always include summary and holdings
    sections.append(format_portfolio_summary(portfolio_summary))
    sections.append(format_holdings_table(portfolio_summary))

    # Optional sections — only include if there is content
    tech_section = format_technical_alerts(technicals)
    if tech_section:
        sections.append(tech_section)

    fund_section = format_fundamental_highlights(fundamentals, fundamental_alerts)
    if fund_section:
        sections.append(fund_section)

    sections.append(format_risk_dashboard(concentration, sector_exposure))

    signals_section = format_integrated_signals(integrated_signals)
    if signals_section:
        sections.append(signals_section)

    report = "\n\n".join(sections)
    log.info("Formatted full report: %d characters, %d sections", len(report), len(sections))
    return report
