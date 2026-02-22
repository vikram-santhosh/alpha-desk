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
# §3b THESIS EXPOSURE
# ═══════════════════════════════════════════════════════

def format_thesis_exposure_section(thesis_exposure: list[dict[str, Any]]) -> str:
    """Format thesis-level portfolio concentration risk."""
    if not thesis_exposure:
        return ""

    lines = ["\U0001f4ca <b>THESIS EXPOSURE</b>", ""]

    for entry in thesis_exposure:
        thesis = sanitize_html(entry.get("thesis", ""))
        pct = entry.get("exposure_pct", 0)
        tickers = entry.get("tickers", [])
        status = entry.get("status", "intact")
        warning = entry.get("warning")
        overlaps = entry.get("overlaps_with", [])

        # Visual bar (1 block per 5%)
        bar_len = int(pct / 5)
        bar = "\u2588" * bar_len

        status_e = _status_emoji(status)
        ticker_str = ", ".join(tickers[:5])
        lines.append(f"  <b>{pct:.0f}%</b> {thesis} {status_e}")
        lines.append(f"     <code>{bar}</code> ({ticker_str})")
        if overlaps:
            overlap_names = ", ".join(sanitize_html(o) for o in overlaps[:2])
            lines.append(f"     \u2194\ufe0f Overlaps with: {overlap_names}")
        if warning:
            lines.append(f"     \u26a0\ufe0f {warning}")
        lines.append("")

    # Footnote if any thesis has overlaps — prevents user from double-counting
    has_overlaps = any(entry.get("overlaps_with") for entry in thesis_exposure)
    if has_overlaps:
        lines.append("  <i>Note: Tickers can appear in multiple theses. Percentages are not additive.</i>")

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

def format_key_headlines(top_articles: list[dict[str, Any]], max_headlines: int = 3) -> str:
    """Format top macro/geopolitical news headlines for the advisor brief.

    Shows the most relevant news articles so the reader can see what
    drove the analysis, instead of only seeing signals downstream.

    Args:
        top_articles: Analyzed articles from news_desk (sorted by relevance).
        max_headlines: Maximum headlines to show.

    Returns:
        Formatted HTML string, or empty string if no relevant articles.
    """
    # Filter to macro-relevant categories with relevance >= 6
    macro_categories = {"macro", "geopolitical", "regulatory", "market_sentiment"}
    relevant = [
        a for a in top_articles
        if a.get("category", "").lower() in macro_categories
        and a.get("relevance", 0) >= 6
    ]

    if not relevant:
        return ""

    lines = ["\U0001f4f0 <b>KEY HEADLINES</b>", ""]
    for article in relevant[:max_headlines]:
        title = sanitize_html(article.get("title", ""))
        source = sanitize_html(article.get("source", ""))
        sentiment = article.get("sentiment", 0)
        emoji = "\U0001f7e2" if sentiment > 0 else "\U0001f534" if sentiment < 0 else "\u26aa"
        lines.append(f"  {emoji} {title} <i>({source})</i>")

    return "\n".join(lines)


def format_daily_brief(
    macro_section: str,
    holdings_section: str,
    strategy_section: str,
    conviction_section: str,
    moonshot_section: str,
    daily_cost: float = 0.0,
    macro_summary: str | None = None,
    thesis_exposure_section: str = "",
    key_headlines_section: str = "",
    reddit_mood: str = "",
    reddit_themes: list[str] | None = None,
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

    # Key headlines — show what news drove the analysis
    if key_headlines_section:
        sections.extend(["", SEPARATOR, "", key_headlines_section])

    sections.extend([
        "",
        SEPARATOR,
        "",
        macro_section,
    ])

    # Reddit mood (if available) — include top themes for context
    if reddit_mood and reddit_mood != "unknown":
        theme_suffix = ""
        if reddit_themes:
            safe_themes = ", ".join(sanitize_html(t) for t in reddit_themes[:2])
            theme_suffix = f" \u2014 {safe_themes}"
        sections.append(f"  \U0001f4e3 Reddit mood: <b>{sanitize_html(reddit_mood)}</b>{theme_suffix}")

    sections.extend([
        "",
        SEPARATOR,
        "",
        holdings_section,
        "",
        SEPARATOR,
        "",
        strategy_section,
    ])

    # Thesis exposure (between strategy and conviction)
    if thesis_exposure_section:
        sections.extend(["", SEPARATOR, "", thesis_exposure_section])

    sections.extend([
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


# ═══════════════════════════════════════════════════════
# v2 FORMATTERS
# ═══════════════════════════════════════════════════════

def format_committee_brief(editor_output: dict[str, Any]) -> str:
    """Format the analyst committee's Editor output for Telegram.

    Shows the 5-section brief produced by the CIO editor, with
    analyst disagreements highlighted.
    """
    brief = editor_output.get("formatted_brief", "")
    if not brief:
        return "<i>Committee synthesis unavailable.</i>"

    # The editor outputs plain text with **SECTION** headers — convert to HTML
    formatted = sanitize_html(brief)
    # Bold section headers (patterns like "SECTION 1 - ..." or "**SECTION...**")
    import re
    formatted = re.sub(
        r"\*\*(.+?)\*\*",
        r"<b>\1</b>",
        formatted,
    )
    return formatted


def format_delta_section(delta_report) -> str:
    """Format delta report for the daily brief.

    Shows HIGH significance items prominently, MEDIUM items compactly.
    """
    if not delta_report or delta_report.total_changes == 0:
        return ""

    lines = ["\u26a1 <b>WHAT CHANGED TODAY</b>", ""]

    if delta_report.summary:
        lines.append(f"<i>{sanitize_html(delta_report.summary)}</i>")
        lines.append("")

    for item in delta_report.high_significance:
        lines.append(f"  \u26a1 {sanitize_html(item.narrative)}")

    if delta_report.medium_significance:
        lines.append("")
        for item in delta_report.medium_significance[:5]:
            lines.append(f"  \U0001f4cc {sanitize_html(item.narrative)}")

    return "\n".join(lines)


def format_scorecard_section(scorecard: dict[str, Any]) -> str:
    """Format recommendation scorecard for the daily brief footer."""
    total = scorecard.get("total_recommendations", 0)
    if total == 0:
        return ""

    hit_rate = scorecard.get("hit_rate_1m", 0)
    avg_alpha = scorecard.get("avg_alpha_1m_pct", 0)
    fp_rate = scorecard.get("false_positive_rate", 0)

    # Visual bar for hit rate (1 block per 10%)
    bar_len = int(hit_rate / 10)
    bar = "\u2588" * bar_len + "\u2591" * (10 - bar_len)

    lines = [
        "\U0001f4ca <b>TRACK RECORD (30d)</b>",
        "",
        f"  Hit rate: <code>{bar}</code> {hit_rate:.0f}% ({total} recs)",
        f"  Alpha: {avg_alpha:+.1f}% vs SPY | False positives: {fp_rate:.0f}%",
    ]

    best = scorecard.get("best_recommendation")
    worst = scorecard.get("worst_recommendation")
    if best:
        lines.append(f"  Best: {best['ticker']} ({best['return_pct']:+.1f}%)")
    if worst:
        lines.append(f"  Worst: {worst['ticker']} ({worst['return_pct']:+.1f}%)")

    return "\n".join(lines)


def format_recommendation_card(rec: dict[str, Any]) -> str:
    """Format a single recommendation as a compact Telegram card."""
    ticker = sanitize_html(rec.get("ticker", "???"))
    action = rec.get("action", "WATCH")
    conviction = rec.get("conviction_level", rec.get("conviction", "medium"))
    badge = _conviction_badge(conviction)

    # Action emoji
    action_emoji = {
        "BUY": "\U0001f3af",
        "WATCH": "\U0001f440",
        "TRIM": "\u2702\ufe0f",
        "SELL": "\U0001f6d1",
        "HOLD": "\U0001f7e2",
    }.get(action, "\U0001f4cb")

    lines = [f"{action_emoji} <b>{action} {ticker}</b> [{badge}]"]

    # Thesis
    thesis = rec.get("thesis", {})
    core = thesis.get("core_argument", "") if isinstance(thesis, dict) else str(thesis)
    if core:
        lines.append(f"  {_truncate(sanitize_html(core), 160)}")

    # Bear case
    bear = rec.get("bear_case", {})
    primary_risk = bear.get("primary_risk", "") if isinstance(bear, dict) else ""
    if primary_risk:
        lines.append(f"  \u2696\ufe0f Bear: {_truncate(sanitize_html(primary_risk), 120)}")

    # Invalidation
    conditions = rec.get("invalidation_conditions", [])
    if conditions:
        first = conditions[0] if isinstance(conditions[0], dict) else {"condition": str(conditions[0])}
        lines.append(f"  \u274c Invalidate if: {_truncate(sanitize_html(first.get('condition', '')), 120)}")

    # Valuation
    val = rec.get("valuation", {})
    target = val.get("target_price")
    cagr = val.get("implied_cagr")
    if target and cagr:
        lines.append(f"  \U0001f4ca Target: ${target:.0f} (CAGR {cagr:.1f}%)")

    return "\n".join(lines)


def split_message(text: str, max_chars: int = 4000) -> list[str]:
    """Split a message into chunks that fit Telegram's 4096 char limit.

    Splits on section boundaries (separator lines) rather than mid-content.
    """
    if len(text) <= max_chars:
        return [text]

    chunks = []
    while text:
        if len(text) <= max_chars:
            chunks.append(text)
            break

        # Try to split at a separator line
        split_at = text.rfind(SEPARATOR, 0, max_chars)
        if split_at == -1:
            # Fall back to splitting at a newline
            split_at = text.rfind("\n", 0, max_chars)
        if split_at == -1:
            split_at = max_chars

        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")

    return chunks
