"""Telegram HTML formatter for the AlphaDesk Advisor 5-section daily brief.

Sections:
  §0 What Changed Today (Opus synthesis lead)
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

# Holdings with position_pct below this are collapsed into a summary line
_DETAIL_THRESHOLD_PCT = 2.0


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


def _fmt_dollar(amount: float | None) -> str:
    """Format a dollar amount with sign."""
    if amount is None:
        return "N/A"
    sign = "+" if amount >= 0 else ""
    if abs(amount) >= 1_000_000:
        return f"{sign}${amount / 1_000_000:,.1f}M"
    if abs(amount) >= 1_000:
        return f"{sign}${amount / 1_000:,.1f}K"
    return f"{sign}${amount:,.0f}"


def _truncate(text: str, max_len: int = 200) -> str:
    """Truncate text to max_len, adding ellipsis."""
    if len(text) <= max_len:
        return text
    return text[:max_len - 3].rsplit(" ", 1)[0] + "..."


# ═══════════════════════════════════════════════════════
# §1 MACRO
# ═══════════════════════════════════════════════════════

def format_macro_section(macro_data: dict[str, Any], theses: list[dict[str, Any]],
                         prediction_shifts: list[dict[str, Any]]) -> str:
    """Format §1 Macro & Market Context."""
    lines = ["\U0001f30d <b>MACRO &amp; MARKET CONTEXT</b>", ""]

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

    # Active theses — only show those with evidence or non-intact status
    if theses:
        lines.append("<b>Active Theses:</b>")
        for i, t in enumerate(theses, 1):
            status = t.get("status", "intact")
            emoji = _status_emoji(status)
            title = sanitize_html(t.get("title", ""))
            affected = t.get("affected_tickers", [])
            ticker_str = f" ({', '.join(affected[:4])})" if affected else ""
            lines.append(f"  {i}. {title}{ticker_str} {emoji}")
            # Only show evidence if something changed
            evidence_log = t.get("evidence_log", [])
            if evidence_log:
                latest = evidence_log[-1]
                lines.append(f"     {sanitize_html(latest.get('evidence', ''))}")
        lines.append("")

    # Prediction market shifts
    if prediction_shifts:
        lines.append("<b>Prediction Markets:</b>")
        for pm in prediction_shifts[:3]:
            title = sanitize_html(pm.get("market_title", ""))
            prob = pm.get("probability", 0)
            delta = pm.get("delta", 0)
            direction = "\u2b06\ufe0f" if delta > 0 else "\u2b07\ufe0f"
            lines.append(f"  {direction} {title}: {prob*100:.0f}% ({delta*100:+.0f}pp)")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════
# §2 PORTFOLIO
# ═══════════════════════════════════════════════════════

def format_holdings_section(holdings_reports: list[dict[str, Any]]) -> str:
    """Format §2 Your Portfolio.

    Top holdings (>2% weight) get full detail.
    Smaller positions + ETFs are collapsed into a summary line.
    Includes dollar P&L per holding and portfolio total.
    """
    lines = ["\U0001f4ca <b>YOUR PORTFOLIO</b>", ""]

    if not holdings_reports:
        lines.append("  <i>No holdings data available.</i>")
        return "\n".join(lines)

    # Compute total portfolio value and daily P&L
    total_value = 0.0
    total_daily_pnl = 0.0
    total_unrealized_pnl = 0.0
    for h in holdings_reports:
        price = h.get("price")
        shares = h.get("shares") or 0
        entry = h.get("entry_price")
        change_pct = h.get("change_pct") or 0

        if price and shares:
            mv = price * shares
            total_value += mv
            total_daily_pnl += mv * change_pct / 100
            if entry and entry > 0:
                total_unrealized_pnl += (price - entry) * shares

    # Portfolio header with dollar values
    if total_value > 0:
        lines.append(
            f"  Total: <b>${total_value:,.0f}</b> | "
            f"Today: <b>{_fmt_dollar(total_daily_pnl)}</b> | "
            f"Unrealized: <b>{_fmt_dollar(total_unrealized_pnl)}</b>"
        )
        lines.append("")

    # Sort by position size descending
    sorted_holdings = sorted(
        holdings_reports,
        key=lambda h: (h.get("position_pct") or 0),
        reverse=True,
    )

    # Split into detailed (>threshold) and summary (<threshold or ETFs)
    detailed = []
    summarized = []
    for h in sorted_holdings:
        cat = h.get("category", "core")
        pct = h.get("position_pct") or 0
        if cat == "etf" or pct < _DETAIL_THRESHOLD_PCT:
            summarized.append(h)
        else:
            detailed.append(h)

    # Detailed holdings
    for h in detailed:
        _format_holding_detail(h, lines)

    # Collapsed summary for small positions + ETFs
    if summarized:
        lines.append("  <b>Smaller positions &amp; ETFs:</b>")
        parts = []
        for h in summarized:
            ticker = h.get("ticker", "???")
            price = h.get("price")
            change_pct = h.get("change_pct")
            pct = h.get("position_pct") or 0
            chg_str = f"{change_pct:+.1f}%" if change_pct is not None else "N/A"
            pct_str = f"{pct:.1f}%" if pct > 0 else ""
            parts.append(f"{ticker} {chg_str}")
        lines.append(f"  {' | '.join(parts)}")
        lines.append("")

    return "\n".join(lines)


def _format_holding_detail(h: dict, lines: list[str]) -> None:
    """Format a single holding with full detail including dollar P&L."""
    ticker = sanitize_html(h.get("ticker", "???"))
    price = h.get("price")
    shares = h.get("shares") or 0
    entry_price = h.get("entry_price")
    change_pct = h.get("change_pct")
    cumul = h.get("cumulative_return_pct")
    thesis = h.get("thesis", "")
    thesis_status = h.get("thesis_status", "intact")
    recent_trend = h.get("recent_trend", "")
    key_events = h.get("key_events", [])
    position_pct = h.get("position_pct") or 0

    emoji = _pnl_emoji(change_pct if change_pct is not None else 0)
    status_e = _status_emoji(thesis_status)

    # Line 1: Ticker, price, daily change, position weight
    price_str = f"${price:,.2f}" if price is not None else "N/A"
    chg_str = f"{change_pct:+.1f}%" if change_pct is not None else ""
    pct_str = f"({position_pct:.0f}%)" if position_pct else ""
    lines.append(f"  {emoji} <b>{ticker}</b>  {price_str}  {chg_str}  {pct_str}")

    # Line 2: Dollar P&L
    if price and shares and entry_price and entry_price > 0:
        daily_pnl = price * shares * (change_pct or 0) / 100
        unrealized = (price - entry_price) * shares
        lines.append(
            f"     {shares} shares | Entry ${entry_price:,.2f} | "
            f"Today {_fmt_dollar(daily_pnl)} | P&amp;L {_fmt_dollar(unrealized)}"
        )
    elif shares:
        lines.append(f"     {shares} shares")

    # Line 3: Thesis + status (only if not intact — intact is default/boring)
    if thesis_status not in ("intact",):
        lines.append(f"     Thesis: {sanitize_html(thesis)} {status_e}")

    # Line 4: Trend (only if meaningful — 3+ days of data)
    if recent_trend and "first day" not in recent_trend.lower() and "0 of last 1" not in recent_trend:
        lines.append(f"     {sanitize_html(recent_trend)}")

    # Key events (signals, news)
    for event in key_events[:2]:
        lines.append(f"     \u2022 {sanitize_html(event)}")

    lines.append("")


# ═══════════════════════════════════════════════════════
# §3 STRATEGY
# ═══════════════════════════════════════════════════════

def format_strategy_section(strategy: dict[str, Any]) -> str:
    """Format §3 Portfolio Strategy — Add / Trim / Hold."""
    lines = ["\u2696\ufe0f <b>PORTFOLIO STRATEGY</b>", ""]

    actions = strategy.get("actions", [])
    flags = strategy.get("flags", []) or strategy.get("active_flags", [])
    summary = strategy.get("summary", "")

    if not actions and not flags:
        lines.append("  \U0001f7e2 <b>NO CHANGES — all theses intact</b>")
        return "\n".join(lines)

    for action in actions:
        ticker = sanitize_html(action.get("ticker", ""))
        act = action.get("action", "hold")
        reason = sanitize_html(action.get("reason", ""))
        urgency = action.get("urgency", "low")

        if act == "add":
            lines.append(f"  \U0001f7e2 ADD: <b>{ticker}</b>")
        elif act == "trim":
            urgency_str = " \u26a0\ufe0f" if urgency == "high" else ""
            lines.append(f"  \U0001f534 TRIM: <b>{ticker}</b>{urgency_str}")
        else:
            lines.append(f"  \U0001f7e1 {act.upper()}: <b>{ticker}</b>")

        if reason:
            lines.append(f"     {reason}")
        lines.append("")

    if flags:
        lines.append("<b>Watching:</b>")
        for flag in flags[:5]:
            ticker = sanitize_html(flag.get("ticker", ""))
            flag_type = flag.get("flag_type", "")
            lines.append(f"  \u2022 <b>{ticker}</b> — {flag_type.replace('_', ' ')}")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════
# §4 CONVICTION
# ═══════════════════════════════════════════════════════

def format_conviction_section(conviction_list: list[dict[str, Any]]) -> str:
    """Format §4 Conviction List."""
    lines = ["\U0001f50d <b>CONVICTION LIST</b>", ""]

    if not conviction_list:
        lines.append("  <i>No conviction names currently. Building watchlist.</i>")
        return "\n".join(lines)

    for i, entry in enumerate(conviction_list, 1):
        ticker = sanitize_html(entry.get("ticker", "???"))
        conviction = entry.get("conviction", "medium")
        weeks = entry.get("weeks_on_list", 1)
        thesis = sanitize_html(entry.get("thesis", ""))
        badge = _conviction_badge(conviction)

        lines.append(f"  {i}. <b>{ticker}</b> \u2014 W{weeks} [{badge}]")
        if thesis:
            lines.append(f"     {_truncate(thesis, 180)}")
        lines.append("")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════
# §5 MOONSHOTS
# ═══════════════════════════════════════════════════════

def format_moonshot_section(moonshot_list: list[dict[str, Any]]) -> str:
    """Format §5 Moonshot Ideas — compact with key info."""
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

        lines.append(f"  {i}. <b>{ticker}</b> \u2014 M{months} [{badge}]")
        if thesis:
            lines.append(f"     {_truncate(thesis, 200)}")
        if upside:
            lines.append(f"     \u2b06 {_truncate(sanitize_html(upside), 120)}")
        if downside:
            lines.append(f"     \u2b07 {_truncate(sanitize_html(downside), 120)}")
        if milestone:
            lines.append(f"     \U0001f3af {_truncate(sanitize_html(milestone), 100)}")
        lines.append("")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════
# ASSEMBLY
# ═══════════════════════════════════════════════════════

def format_daily_brief(
    macro_section: str,
    holdings_section: str,
    strategy_section: str,
    conviction_section: str,
    moonshot_section: str,
    daily_cost: float = 0.0,
    macro_summary: str | None = None,
) -> str:
    """Assemble the complete daily brief with Opus synthesis lead."""
    today = datetime.now().strftime("%b %d, %Y")

    sections = [
        f"\u2600\ufe0f <b>ALPHADESK DAILY BRIEF \u2014 {today}</b>",
        SEPARATOR,
    ]

    # Lead with Opus synthesis ("What changed today")
    if macro_summary and macro_summary != "Synthesis unavailable — review sections below.":
        sections.append("")
        sections.append(f"\U0001f4ac <b>TODAY&apos;S TAKE</b>")
        sections.append(f"  {sanitize_html(macro_summary)}")

    sections.extend([
        "",
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
        f"AlphaDesk v0.2 | ${daily_cost:.2f} today",
        "/advisor /holdings /macro /conviction /moonshot /action /cost",
    ])

    return "\n".join(sections)
