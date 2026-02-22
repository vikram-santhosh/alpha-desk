"""Telegram HTML formatter for the AlphaDesk Advisor 5-section daily brief.

Sections:
  §1 Macro & Market Context
  §2 Your Portfolio — Holdings Check-in
  §3 Portfolio Strategy — Add / Trim / Hold
  §4 Conviction List — 3-5 Interesting Names
  §5 Moonshot Ideas — 1-2 Asymmetric Bets
"""

from datetime import datetime
from typing import Any

from src.shared.security import sanitize_html
from src.utils.logger import get_logger

log = get_logger(__name__)

SEPARATOR = "\u2501" * 35


def _status_emoji(status: str) -> str:
    if status in ("strengthening", "intact"):
        return "\u2705"
    elif status in ("evolving", "monitoring"):
        return "\u26a0\ufe0f"
    elif status in ("weakening", "invalidated"):
        return "\u274c"
    return "\u2753"


def _conviction_badge(conviction: str) -> str:
    if conviction == "high":
        return "\U0001f7e2 HIGH"
    elif conviction == "medium":
        return "\U0001f7e1 MED"
    return "\u26aa LOW"


def _pnl_emoji(value: float) -> str:
    return "\U0001f7e2" if value > 0 else "\U0001f534" if value < 0 else "\U0001f7e1"


def format_macro_section(macro_data: dict[str, Any], theses: list[dict[str, Any]],
                         prediction_shifts: list[dict[str, Any]]) -> str:
    """Format §1 Macro & Market Context."""
    lines = ["\U0001f30d <b>MACRO &amp; MARKET CONTEXT</b>", ""]

    # Market snapshot — macro_data values may be dicts with "value" key or raw floats
    def _val(key: str) -> float | None:
        v = macro_data.get(key)
        if isinstance(v, dict):
            return v.get("value")
        return v

    def _chg(key: str) -> float | None:
        v = macro_data.get(key)
        if isinstance(v, dict):
            return v.get("change_pct")
        return None

    sp500 = _val("sp500")
    sp500_chg = _chg("sp500")
    vix = _val("vix")
    ten_yr = _val("treasury_10y")
    fed_rate = _val("fed_funds_rate")

    market_parts = []
    if sp500 is not None:
        chg_str = f"{sp500_chg:+.1f}%" if sp500_chg is not None else ""
        market_parts.append(f"S&amp;P: {sp500:,.0f} {chg_str}")
    if vix is not None:
        market_parts.append(f"VIX: {vix:.1f}")
    if ten_yr is not None:
        market_parts.append(f"10Y: {ten_yr:.2f}%")
    if fed_rate is not None:
        market_parts.append(f"Fed: {fed_rate:.2f}%")
    if market_parts:
        lines.append(f"  {' | '.join(market_parts)}")
        lines.append("")

    # Active theses
    if theses:
        lines.append("<b>Active Theses:</b>")
        for i, t in enumerate(theses, 1):
            status = t.get("status", "intact")
            emoji = _status_emoji(status)
            title = sanitize_html(t.get("title", ""))
            desc = sanitize_html(t.get("description", ""))
            lines.append(f"  {i}. {title} [{status.upper()}] {emoji}")
            if desc:
                lines.append(f"     {desc}")
            affected = t.get("affected_tickers", [])
            if affected:
                lines.append(f"     Tickers: {', '.join(affected)}")
            # Latest evidence
            evidence_log = t.get("evidence_log", [])
            if evidence_log:
                latest = evidence_log[-1]
                lines.append(f"     Latest: {sanitize_html(latest.get('evidence', ''))}")
            lines.append("")

    # Prediction market shifts
    if prediction_shifts:
        lines.append("<b>Prediction Markets (significant shifts):</b>")
        for pm in prediction_shifts[:3]:
            title = sanitize_html(pm.get("market_title", ""))
            prob = pm.get("probability", 0)
            delta = pm.get("delta", 0)
            direction = "\u2b06\ufe0f" if delta > 0 else "\u2b07\ufe0f"
            lines.append(f"  {direction} {title}: {prob*100:.0f}% ({delta*100:+.0f}pp)")

    return "\n".join(lines)


def format_holdings_section(holdings_reports: list[dict[str, Any]]) -> str:
    """Format §2 Your Portfolio — Holdings Check-in."""
    lines = ["\U0001f4ca <b>YOUR PORTFOLIO</b>", ""]

    if not holdings_reports:
        lines.append("  <i>No holdings data available.</i>")
        return "\n".join(lines)

    # Portfolio total
    total_return = 0.0
    count = 0
    for h in holdings_reports:
        cr = h.get("cumulative_return_pct")
        if cr is not None:
            total_return += cr
            count += 1
    if count > 0:
        avg_return = total_return / count
        lines.append(f"  Portfolio avg return: <b>{avg_return:+.1f}%</b>")
        lines.append("")

    for h in holdings_reports:
        ticker = sanitize_html(h.get("ticker", "???"))
        price = h.get("price", 0)
        change_pct = h.get("change_pct", 0)
        cumul = h.get("cumulative_return_pct")
        thesis = h.get("thesis", "")
        thesis_status = h.get("thesis_status", "intact")
        category = h.get("category", "core")
        recent_trend = h.get("recent_trend", "")
        key_events = h.get("key_events", [])

        emoji = _pnl_emoji(change_pct)
        status_e = _status_emoji(thesis_status)

        lines.append(f"  {emoji} <b>{ticker}</b>  ${price:,.2f}  {change_pct:+.1f}% today")
        if cumul is not None:
            tracking = h.get("tracking_since", "")
            lines.append(f"     {cumul:+.1f}% since tracking ({tracking})")
        lines.append(f"     Thesis: {sanitize_html(thesis)} {status_e}")
        if recent_trend:
            lines.append(f"     {sanitize_html(recent_trend)}")
        for event in key_events[:2]:
            lines.append(f"     \u2022 {sanitize_html(event)}")
        lines.append("")

    return "\n".join(lines)


def format_strategy_section(strategy: dict[str, Any]) -> str:
    """Format §3 Portfolio Strategy — Add / Trim / Hold."""
    lines = ["\u2696\ufe0f <b>PORTFOLIO STRATEGY</b>", ""]

    actions = strategy.get("actions", [])
    flags = strategy.get("active_flags", [])
    summary = strategy.get("summary", "")

    if not actions and not flags:
        lines.append("  <b>NO CHANGES RECOMMENDED TODAY</b>")
        if summary:
            lines.append(f"  <i>{sanitize_html(summary)}</i>")
        return "\n".join(lines)

    for action in actions:
        ticker = sanitize_html(action.get("ticker", ""))
        act = action.get("action", "hold")
        reason = sanitize_html(action.get("reason", ""))

        if act == "add":
            lines.append(f"  \U0001f7e2 CONSIDER ADDING: <b>{ticker}</b>")
        elif act == "trim":
            lines.append(f"  \U0001f534 CONSIDER TRIMMING: <b>{ticker}</b>")
        elif act == "reduce":
            lines.append(f"  \U0001f7e1 CONSIDER REDUCING: <b>{ticker}</b>")
        else:
            lines.append(f"  \u26aa {act.upper()}: <b>{ticker}</b>")
        if reason:
            lines.append(f"     {reason}")
        lines.append("")

    if flags:
        lines.append("<b>Monitoring:</b>")
        for flag in flags[:5]:
            ticker = sanitize_html(flag.get("ticker", ""))
            desc = sanitize_html(flag.get("description", ""))
            flag_date = flag.get("flag_date", "")
            lines.append(f"  \u2022 <b>{ticker}</b> — {desc} (since {flag_date})")

    return "\n".join(lines)


def format_conviction_section(conviction_list: list[dict[str, Any]]) -> str:
    """Format §4 Conviction List — 3-5 Interesting Names."""
    lines = ["\U0001f50d <b>CONVICTION LIST</b>", ""]

    if not conviction_list:
        lines.append("  <i>No conviction names currently. Building watchlist.</i>")
        return "\n".join(lines)

    for i, entry in enumerate(conviction_list, 1):
        ticker = sanitize_html(entry.get("ticker", "???"))
        conviction = entry.get("conviction", "medium")
        weeks = entry.get("weeks_on_list", 1)
        thesis = sanitize_html(entry.get("thesis", ""))
        pros = entry.get("pros", [])
        cons = entry.get("cons", [])
        badge = _conviction_badge(conviction)

        lines.append(f"  {i}. <b>{ticker}</b> \u2014 WEEK {weeks} [{badge}]")
        if thesis:
            lines.append(f"     Thesis: {thesis}")
        if pros:
            lines.append(f"     Pros: {', '.join(sanitize_html(p) for p in pros[:3])}")
        if cons:
            lines.append(f"     Cons: {', '.join(sanitize_html(c) for c in cons[:3])}")
        si = entry.get("superinvestor_activity")
        if si:
            lines.append(f"     Smart money: {sanitize_html(si)}")
        lines.append("")

    return "\n".join(lines)


def format_moonshot_section(moonshot_list: list[dict[str, Any]]) -> str:
    """Format §5 Moonshot Ideas — 1-2 Asymmetric Bets."""
    lines = ["\U0001f680 <b>MOONSHOT IDEAS</b>", ""]

    if not moonshot_list:
        lines.append("  <i>No moonshot ideas currently.</i>")
        return "\n".join(lines)

    for i, entry in enumerate(moonshot_list, 1):
        ticker = sanitize_html(entry.get("ticker", "???"))
        conviction = entry.get("conviction", "medium")
        months = entry.get("months_on_list", 1)
        thesis = sanitize_html(entry.get("thesis", ""))
        upside = entry.get("upside_case", "")
        downside = entry.get("downside_case", "")
        milestone = entry.get("key_milestone", "")
        badge = _conviction_badge(conviction)

        lines.append(f"  {i}. <b>{ticker}</b> \u2014 MONTH {months} [{badge}]")
        if thesis:
            lines.append(f"     {thesis}")
        if upside:
            lines.append(f"     \u2b06 Upside: {sanitize_html(upside)}")
        if downside:
            lines.append(f"     \u2b07 Downside: {sanitize_html(downside)}")
        if milestone:
            lines.append(f"     Key milestone: {sanitize_html(milestone)}")
        lines.append("")

    return "\n".join(lines)


def format_daily_brief(
    macro_section: str,
    holdings_section: str,
    strategy_section: str,
    conviction_section: str,
    moonshot_section: str,
    daily_cost: float = 0.0,
) -> str:
    """Assemble the complete 5-section daily brief."""
    today = datetime.now().strftime("%b %d, %Y")

    sections = [
        f"\u2600\ufe0f <b>ALPHADESK DAILY BRIEF \u2014 {today}</b>",
        SEPARATOR,
        "",
        macro_section,
        "",
        SEPARATOR,
        "",
        holdings_section,
        "",
        SEPARATOR,
        "",
        strategy_section,
        "",
        SEPARATOR,
        "",
        conviction_section,
        "",
        SEPARATOR,
        "",
        moonshot_section,
        "",
        SEPARATOR,
        f"AlphaDesk v0.2 | API cost today: ${daily_cost:.2f}",
        "/advisor /holdings /macro /conviction /moonshot /action /cost",
    ]

    return "\n".join(sections)
