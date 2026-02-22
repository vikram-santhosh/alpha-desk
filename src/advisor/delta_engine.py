"""Delta Engine — "What Changed" detection for AlphaDesk Advisor v2.

Compares today's data to yesterday's across every tracked dimension and
produces a structured delta report. Surfaces only what changed, not current state.

Example: "VIX jumped from 14 to 18, largest move in 6 weeks" instead of "VIX is 18".
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from src.utils.logger import get_logger

log = get_logger(__name__)


# ═══════════════════════════════════════════════════════
# DATACLASSES
# ═══════════════════════════════════════════════════════

@dataclass
class DeltaItem:
    """A single detected change between today and yesterday."""
    ticker_or_key: str = ""  # Ticker symbol or metric name
    dimension: str = ""      # "price", "fundamental", "technical", "sentiment", "macro", etc.
    metric: str = ""         # Specific metric that changed
    old_value: Any = None
    new_value: Any = None
    delta: float | None = None
    delta_pct: float | None = None
    significance: str = "low"  # "high", "medium", "low"
    narrative: str = ""

    def to_dict(self) -> dict:
        return {
            "ticker_or_key": self.ticker_or_key,
            "dimension": self.dimension,
            "metric": self.metric,
            "old_value": self.old_value,
            "new_value": self.new_value,
            "delta": self.delta,
            "delta_pct": self.delta_pct,
            "significance": self.significance,
            "narrative": self.narrative,
        }

    @classmethod
    def from_dict(cls, d: dict) -> DeltaItem:
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class DeltaReport:
    """Grouped delta items by significance level."""
    date: str = ""
    high_significance: list[DeltaItem] = field(default_factory=list)
    medium_significance: list[DeltaItem] = field(default_factory=list)
    low_significance: list[DeltaItem] = field(default_factory=list)
    summary: str = ""

    def to_dict(self) -> dict:
        return {
            "date": self.date,
            "high_significance": [d.to_dict() for d in self.high_significance],
            "medium_significance": [d.to_dict() for d in self.medium_significance],
            "low_significance": [d.to_dict() for d in self.low_significance],
            "summary": self.summary,
        }

    @classmethod
    def from_dict(cls, d: dict) -> DeltaReport:
        return cls(
            date=d.get("date", ""),
            high_significance=[DeltaItem.from_dict(i) for i in d.get("high_significance", [])],
            medium_significance=[DeltaItem.from_dict(i) for i in d.get("medium_significance", [])],
            low_significance=[DeltaItem.from_dict(i) for i in d.get("low_significance", [])],
            summary=d.get("summary", ""),
        )

    @property
    def total_changes(self) -> int:
        return len(self.high_significance) + len(self.medium_significance) + len(self.low_significance)


# ═══════════════════════════════════════════════════════
# SNAPSHOT BUILDING
# ═══════════════════════════════════════════════════════

def build_snapshot(
    holdings_reports: list[dict] | None = None,
    fundamentals: dict | None = None,
    technicals: dict | None = None,
    macro_data: dict | None = None,
    conviction_list: list[dict] | None = None,
    moonshot_list: list[dict] | None = None,
    strategy: dict | None = None,
    earnings_data: dict | None = None,
    superinvestor_data: dict | None = None,
    reddit_mood: str = "",
    reddit_themes: list[str] | None = None,
) -> dict:
    """Build a complete snapshot of today's state for delta comparison.

    Captures per-ticker prices, fundamentals, technicals, macro indicators,
    conviction/moonshot lists, strategy actions, earnings, and sentiment.
    """
    snapshot: dict[str, Any] = {"snapshot_version": 1}

    # Per-ticker data
    tickers_data: dict[str, dict] = {}

    # From holdings reports
    for report in (holdings_reports or []):
        ticker = report.get("ticker", "")
        if not ticker:
            continue
        tickers_data.setdefault(ticker, {})
        tickers_data[ticker]["price"] = report.get("price")
        tickers_data[ticker]["change_pct"] = report.get("change_pct")
        tickers_data[ticker]["thesis_status"] = report.get("thesis_status")

    # From fundamentals
    for ticker, fund in (fundamentals or {}).items():
        if not isinstance(fund, dict):
            continue
        tickers_data.setdefault(ticker, {})
        tickers_data[ticker]["pe_trailing"] = fund.get("pe_trailing")
        tickers_data[ticker]["pe_forward"] = fund.get("pe_forward")
        tickers_data[ticker]["revenue_growth"] = fund.get("revenue_growth")
        tickers_data[ticker]["net_margin"] = fund.get("net_margin")

    # From technicals
    for ticker, tech in (technicals or {}).items():
        if not isinstance(tech, dict):
            continue
        tickers_data.setdefault(ticker, {})
        tickers_data[ticker]["rsi"] = tech.get("rsi")
        tickers_data[ticker]["macd_signal"] = tech.get("macd_signal")
        signals = tech.get("signals", [])
        tickers_data[ticker]["technical_signals"] = signals if isinstance(signals, list) else []

    # From earnings
    per_ticker_earnings = {}
    if isinstance(earnings_data, dict):
        per_ticker_earnings = earnings_data.get("per_ticker", {})
    for ticker, earn in per_ticker_earnings.items():
        if not isinstance(earn, dict):
            continue
        tickers_data.setdefault(ticker, {})
        tickers_data[ticker]["guidance_sentiment"] = earn.get("guidance_sentiment")
        tickers_data[ticker]["management_tone"] = earn.get("management_tone")

    snapshot["tickers"] = tickers_data

    # Macro data
    macro_snapshot = {}
    if macro_data:
        for key in ("sp500", "vix", "treasury_10y", "fed_funds_rate"):
            val = macro_data.get(key)
            if isinstance(val, dict):
                macro_snapshot[key] = val.get("value")
                macro_snapshot[f"{key}_change_pct"] = val.get("change_pct")
            elif isinstance(val, (int, float)):
                macro_snapshot[key] = val
        macro_snapshot["yield_curve_spread"] = macro_data.get("yield_curve_spread_calculated")
    snapshot["macro"] = macro_snapshot

    # Conviction and moonshot lists
    snapshot["conviction_tickers"] = {
        c.get("ticker", ""): c.get("conviction", "medium")
        for c in (conviction_list or [])
    }
    snapshot["moonshot_tickers"] = [m.get("ticker", "") for m in (moonshot_list or [])]

    # Strategy actions
    snapshot["strategy_actions"] = [
        {"ticker": a.get("ticker", ""), "action": a.get("action", ""), "urgency": a.get("urgency", "")}
        for a in (strategy or {}).get("actions", [])
    ]

    # Sentiment
    snapshot["reddit_mood"] = reddit_mood
    snapshot["reddit_themes"] = reddit_themes or []

    # Superinvestor summary
    si_summary = {}
    if superinvestor_data and isinstance(superinvestor_data, dict):
        for ticker, data in superinvestor_data.items():
            if isinstance(data, dict):
                si_summary[ticker] = {
                    "count": data.get("superinvestor_count", 0),
                    "insider_buying": data.get("insider_buying", False),
                }
    snapshot["superinvestor"] = si_summary

    return snapshot


def save_today_snapshot(snapshot: dict) -> None:
    """Save today's snapshot to the database."""
    from src.advisor.memory import save_daily_snapshot
    save_daily_snapshot(date.today().isoformat(), snapshot)


# ═══════════════════════════════════════════════════════
# DELTA COMPUTATION
# ═══════════════════════════════════════════════════════

def compute_deltas(today_data: dict, yesterday_data: dict | None) -> DeltaReport:
    """Compare today's data to yesterday's and produce a DeltaReport.

    If yesterday_data is None (first run), returns an empty report.
    """
    report = DeltaReport(date=date.today().isoformat())

    if not yesterday_data:
        report.summary = "First run — no prior data for comparison."
        return report

    # Run all delta computations, each wrapped in try/except
    delta_fns = [
        _compute_price_deltas,
        _compute_fundamental_deltas,
        _compute_technical_deltas,
        _compute_macro_deltas,
        _compute_thesis_deltas,
        _compute_earnings_deltas,
        _compute_sentiment_deltas,
        _compute_superinvestor_deltas,
    ]

    for fn in delta_fns:
        try:
            items = fn(today_data, yesterday_data)
            for item in items:
                if item.significance == "high":
                    report.high_significance.append(item)
                    log.info("HIGH delta: %s", item.narrative)
                elif item.significance == "medium":
                    report.medium_significance.append(item)
                    log.debug("MEDIUM delta: %s", item.narrative)
                else:
                    report.low_significance.append(item)
        except Exception:
            log.exception("Delta computation failed in %s", fn.__name__)

    return report


def _compute_price_deltas(today: dict, yesterday: dict) -> list[DeltaItem]:
    """Compute price deltas per ticker."""
    items = []
    today_tickers = today.get("tickers", {})
    yesterday_tickers = yesterday.get("tickers", {})

    for ticker, today_data in today_tickers.items():
        yest_data = yesterday_tickers.get(ticker, {})
        new_price = today_data.get("price")
        old_price = yest_data.get("price")

        if new_price is None or old_price is None or old_price == 0:
            continue

        delta = new_price - old_price
        delta_pct = (delta / old_price) * 100

        if abs(delta_pct) > 5:
            sig = "high"
        elif abs(delta_pct) > 3:
            # Check if opposite to prior trend
            sig = "high"  # 3%+ against trend is high
        elif abs(delta_pct) > 2:
            sig = "medium"
        else:
            continue  # Skip small moves

        direction = "up" if delta > 0 else "down"
        items.append(DeltaItem(
            ticker_or_key=ticker,
            dimension="price",
            metric="daily_price",
            old_value=old_price,
            new_value=new_price,
            delta=round(delta, 2),
            delta_pct=round(delta_pct, 2),
            significance=sig,
            narrative=f"{ticker} {direction} {abs(delta_pct):.1f}% (${old_price:.2f} → ${new_price:.2f})",
        ))

    return items


def _compute_fundamental_deltas(today: dict, yesterday: dict) -> list[DeltaItem]:
    """Compute fundamental data deltas — these change infrequently."""
    items = []
    today_tickers = today.get("tickers", {})
    yesterday_tickers = yesterday.get("tickers", {})

    metrics = ["pe_trailing", "pe_forward", "revenue_growth", "net_margin"]

    for ticker, today_data in today_tickers.items():
        yest_data = yesterday_tickers.get(ticker, {})
        for metric in metrics:
            new_val = today_data.get(metric)
            old_val = yest_data.get(metric)
            if new_val is None or old_val is None or old_val == 0:
                continue
            if new_val == old_val:
                continue

            delta_pct = abs((new_val - old_val) / old_val) * 100

            if metric in ("pe_trailing", "pe_forward") and delta_pct > 10:
                sig = "high"
            elif metric == "revenue_growth" and (
                (old_val > 0 and new_val < 0) or (old_val < 0 and new_val > 0)
            ):
                sig = "high"
            else:
                sig = "medium"

            items.append(DeltaItem(
                ticker_or_key=ticker,
                dimension="fundamental",
                metric=metric,
                old_value=old_val,
                new_value=new_val,
                delta=round(new_val - old_val, 4),
                delta_pct=round(delta_pct, 2),
                significance=sig,
                narrative=f"{ticker} {metric} changed: {old_val} → {new_val}",
            ))

    return items


def _compute_technical_deltas(today: dict, yesterday: dict) -> list[DeltaItem]:
    """Compute technical signal deltas (RSI zones, MACD crossovers)."""
    items = []
    today_tickers = today.get("tickers", {})
    yesterday_tickers = yesterday.get("tickers", {})

    def _rsi_zone(rsi: float | None) -> str:
        if rsi is None:
            return "unknown"
        if rsi > 70:
            return "overbought"
        if rsi < 30:
            return "oversold"
        return "neutral"

    for ticker, today_data in today_tickers.items():
        yest_data = yesterday_tickers.get(ticker, {})

        # RSI zone changes
        new_rsi = today_data.get("rsi")
        old_rsi = yest_data.get("rsi")
        new_zone = _rsi_zone(new_rsi)
        old_zone = _rsi_zone(old_rsi)

        if new_zone != old_zone and new_zone != "unknown" and old_zone != "unknown":
            sig = "high" if new_zone in ("oversold", "overbought") else "medium"
            items.append(DeltaItem(
                ticker_or_key=ticker,
                dimension="technical",
                metric="rsi_zone",
                old_value=old_zone,
                new_value=new_zone,
                significance=sig,
                narrative=f"{ticker} RSI zone: {old_zone} → {new_zone} (RSI {old_rsi:.0f} → {new_rsi:.0f})",
            ))

        # MACD signal changes
        new_macd = today_data.get("macd_signal")
        old_macd = yest_data.get("macd_signal")
        if new_macd is not None and old_macd is not None:
            # Detect crossover: sign change
            if (old_macd < 0 and new_macd >= 0) or (old_macd >= 0 and new_macd < 0):
                cross_type = "bullish" if new_macd >= 0 else "bearish"
                items.append(DeltaItem(
                    ticker_or_key=ticker,
                    dimension="technical",
                    metric="macd_crossover",
                    old_value=old_macd,
                    new_value=new_macd,
                    significance="high",
                    narrative=f"{ticker} MACD {cross_type} crossover",
                ))

    return items


def _compute_macro_deltas(today: dict, yesterday: dict) -> list[DeltaItem]:
    """Compute macro indicator deltas."""
    items = []
    today_macro = today.get("macro", {})
    yesterday_macro = yesterday.get("macro", {})

    # VIX
    new_vix = today_macro.get("vix")
    old_vix = yesterday_macro.get("vix")
    if new_vix is not None and old_vix is not None and old_vix != 0:
        vix_delta = new_vix - old_vix
        vix_pct = abs(vix_delta / old_vix) * 100
        if abs(vix_delta) > 3 or vix_pct > 15:
            items.append(DeltaItem(
                ticker_or_key="VIX", dimension="macro", metric="vix",
                old_value=old_vix, new_value=new_vix,
                delta=round(vix_delta, 2), delta_pct=round(vix_pct, 1),
                significance="high",
                narrative=f"VIX moved {vix_delta:+.1f} ({old_vix:.1f} → {new_vix:.1f})",
            ))
        elif abs(vix_delta) > 1:
            items.append(DeltaItem(
                ticker_or_key="VIX", dimension="macro", metric="vix",
                old_value=old_vix, new_value=new_vix,
                delta=round(vix_delta, 2), delta_pct=round(vix_pct, 1),
                significance="medium",
                narrative=f"VIX {vix_delta:+.1f} ({old_vix:.1f} → {new_vix:.1f})",
            ))

    # Treasury 10Y
    new_10y = today_macro.get("treasury_10y")
    old_10y = yesterday_macro.get("treasury_10y")
    if new_10y is not None and old_10y is not None:
        delta_10y = new_10y - old_10y
        if abs(delta_10y) > 0.10:
            items.append(DeltaItem(
                ticker_or_key="10Y_YIELD", dimension="macro", metric="treasury_10y",
                old_value=old_10y, new_value=new_10y,
                delta=round(delta_10y, 3),
                significance="high",
                narrative=f"10Y yield {delta_10y:+.2f}% ({old_10y:.2f}% → {new_10y:.2f}%)",
            ))
        elif abs(delta_10y) > 0.05:
            items.append(DeltaItem(
                ticker_or_key="10Y_YIELD", dimension="macro", metric="treasury_10y",
                old_value=old_10y, new_value=new_10y,
                delta=round(delta_10y, 3),
                significance="medium",
                narrative=f"10Y yield {delta_10y:+.2f}% ({old_10y:.2f}% → {new_10y:.2f}%)",
            ))

    # S&P 500
    new_sp = today_macro.get("sp500")
    old_sp = yesterday_macro.get("sp500")
    if new_sp is not None and old_sp is not None and old_sp != 0:
        sp_pct = ((new_sp - old_sp) / old_sp) * 100
        if abs(sp_pct) > 2:
            items.append(DeltaItem(
                ticker_or_key="S&P500", dimension="macro", metric="sp500",
                old_value=old_sp, new_value=new_sp,
                delta=round(new_sp - old_sp, 2), delta_pct=round(sp_pct, 2),
                significance="high",
                narrative=f"S&P 500 {sp_pct:+.1f}% ({old_sp:.0f} → {new_sp:.0f})",
            ))
        elif abs(sp_pct) > 1:
            items.append(DeltaItem(
                ticker_or_key="S&P500", dimension="macro", metric="sp500",
                old_value=old_sp, new_value=new_sp,
                delta=round(new_sp - old_sp, 2), delta_pct=round(sp_pct, 2),
                significance="medium",
                narrative=f"S&P 500 {sp_pct:+.1f}% ({old_sp:.0f} → {new_sp:.0f})",
            ))

    # Fed funds rate — any change is HIGH
    new_ff = today_macro.get("fed_funds_rate")
    old_ff = yesterday_macro.get("fed_funds_rate")
    if new_ff is not None and old_ff is not None and new_ff != old_ff:
        items.append(DeltaItem(
            ticker_or_key="FED_RATE", dimension="macro", metric="fed_funds_rate",
            old_value=old_ff, new_value=new_ff,
            delta=round(new_ff - old_ff, 3),
            significance="high",
            narrative=f"Fed funds rate changed: {old_ff:.2f}% → {new_ff:.2f}%",
        ))

    return items


def _compute_thesis_deltas(today: dict, yesterday: dict) -> list[DeltaItem]:
    """Compute thesis status deltas per ticker."""
    items = []
    today_tickers = today.get("tickers", {})
    yesterday_tickers = yesterday.get("tickers", {})

    for ticker, today_data in today_tickers.items():
        yest_data = yesterday_tickers.get(ticker, {})
        new_status = today_data.get("thesis_status")
        old_status = yest_data.get("thesis_status")

        if not new_status or not old_status or new_status == old_status:
            continue

        # Deterioration is high significance
        deterioration = (
            (old_status == "intact" and new_status in ("weakening", "invalidated"))
            or (old_status == "weakening" and new_status == "invalidated")
        )
        sig = "high" if deterioration else "medium"

        items.append(DeltaItem(
            ticker_or_key=ticker,
            dimension="thesis_status",
            metric="thesis_status",
            old_value=old_status,
            new_value=new_status,
            significance=sig,
            narrative=f"{ticker} thesis: {old_status} → {new_status}",
        ))

    return items


def _compute_earnings_deltas(today: dict, yesterday: dict) -> list[DeltaItem]:
    """Compute earnings data deltas."""
    items = []
    today_tickers = today.get("tickers", {})
    yesterday_tickers = yesterday.get("tickers", {})

    for ticker, today_data in today_tickers.items():
        yest_data = yesterday_tickers.get(ticker, {})

        # Guidance sentiment change
        new_guidance = today_data.get("guidance_sentiment")
        old_guidance = yest_data.get("guidance_sentiment")
        if new_guidance and old_guidance and new_guidance != old_guidance:
            sig = "high" if new_guidance in ("lowered", "withdrawn") else "medium"
            items.append(DeltaItem(
                ticker_or_key=ticker,
                dimension="earnings",
                metric="guidance_sentiment",
                old_value=old_guidance,
                new_value=new_guidance,
                significance=sig,
                narrative=f"{ticker} guidance: {old_guidance} → {new_guidance}",
            ))

        # Management tone change
        new_tone = today_data.get("management_tone")
        old_tone = yest_data.get("management_tone")
        if new_tone and old_tone and new_tone != old_tone:
            items.append(DeltaItem(
                ticker_or_key=ticker,
                dimension="earnings",
                metric="management_tone",
                old_value=old_tone,
                new_value=new_tone,
                significance="medium",
                narrative=f"{ticker} management tone: {old_tone} → {new_tone}",
            ))

        # New earnings data that wasn't there yesterday
        if new_guidance and not old_guidance:
            items.append(DeltaItem(
                ticker_or_key=ticker,
                dimension="earnings",
                metric="new_earnings_data",
                new_value=new_guidance,
                significance="high",
                narrative=f"{ticker} new earnings data available: guidance={new_guidance}",
            ))

    return items


def _compute_sentiment_deltas(today: dict, yesterday: dict) -> list[DeltaItem]:
    """Compute Reddit/sentiment deltas."""
    items = []

    new_mood = today.get("reddit_mood", "")
    old_mood = yesterday.get("reddit_mood", "")
    if new_mood and old_mood and new_mood != old_mood:
        items.append(DeltaItem(
            ticker_or_key="REDDIT",
            dimension="sentiment",
            metric="reddit_mood",
            old_value=old_mood,
            new_value=new_mood,
            significance="medium",
            narrative=f"Reddit mood shifted: {old_mood} → {new_mood}",
        ))

    return items


def _compute_superinvestor_deltas(today: dict, yesterday: dict) -> list[DeltaItem]:
    """Compute superinvestor activity deltas."""
    items = []
    today_si = today.get("superinvestor", {})
    yesterday_si = yesterday.get("superinvestor", {})

    for ticker, today_data in today_si.items():
        yest_data = yesterday_si.get(ticker, {})
        new_count = today_data.get("count", 0)
        old_count = yest_data.get("count", 0)
        new_insider = today_data.get("insider_buying", False)
        old_insider = yest_data.get("insider_buying", False)

        if new_count > old_count:
            items.append(DeltaItem(
                ticker_or_key=ticker,
                dimension="superinvestor",
                metric="superinvestor_count",
                old_value=old_count,
                new_value=new_count,
                significance="high",
                narrative=f"{ticker} new superinvestor position detected ({old_count} → {new_count})",
            ))

        if new_insider and not old_insider:
            items.append(DeltaItem(
                ticker_or_key=ticker,
                dimension="superinvestor",
                metric="insider_buying",
                old_value=False,
                new_value=True,
                significance="high",
                narrative=f"{ticker} insider buying detected",
            ))

    # Check for tickers that were in yesterday but not today (exited)
    for ticker in yesterday_si:
        if ticker not in today_si:
            old_count = yesterday_si[ticker].get("count", 0)
            if old_count > 0:
                items.append(DeltaItem(
                    ticker_or_key=ticker,
                    dimension="superinvestor",
                    metric="superinvestor_exit",
                    old_value=old_count,
                    new_value=0,
                    significance="high",
                    narrative=f"{ticker} superinvestor position exited",
                ))

    return items


# ═══════════════════════════════════════════════════════
# SUMMARY GENERATION
# ═══════════════════════════════════════════════════════

def generate_delta_summary(delta_report: DeltaReport, anthropic_client=None) -> str:
    """Generate a 2-3 sentence summary of the most important changes.

    Uses LLM if available, falls back to template-based summary.
    """
    if delta_report.total_changes == 0:
        return "Quiet day — no material changes to holdings or theses."

    # Try LLM-based summary if client available
    if anthropic_client is not None:
        try:
            return _llm_summary(delta_report, anthropic_client)
        except Exception:
            log.exception("LLM delta summary failed, using template")

    # Template-based fallback
    return _template_summary(delta_report)


def _llm_summary(delta_report: DeltaReport, client) -> str:
    """Use Claude Haiku for a concise summary."""
    from src.shared.cost_tracker import record_usage

    high_items = "\n".join(f"- {d.narrative}" for d in delta_report.high_significance[:10])
    medium_items = "\n".join(f"- {d.narrative}" for d in delta_report.medium_significance[:5])

    prompt = f"""You are a portfolio manager's chief of staff. Given these changes from yesterday, write 2-3 sentences highlighting only what demands attention. If nothing material changed, say 'Quiet day — no material changes to holdings or theses.' Be specific with numbers. Do not summarize — prioritize.

HIGH SIGNIFICANCE:
{high_items or "None"}

MEDIUM SIGNIFICANCE:
{medium_items or "None"}"""

    response = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=200,
        messages=[{"role": "user", "content": prompt}],
    )
    usage = response.usage
    record_usage("delta_engine", usage.input_tokens, usage.output_tokens, model="claude-haiku-4-5")
    return response.content[0].text.strip()


def _template_summary(delta_report: DeltaReport) -> str:
    """Build a template-based summary from high-significance items."""
    high = delta_report.high_significance
    if not high:
        medium = delta_report.medium_significance
        if not medium:
            return "Quiet day — no material changes to holdings or theses."
        return f"{len(medium)} minor changes detected. " + medium[0].narrative + "."

    parts = []
    for item in high[:3]:
        parts.append(item.narrative)
    return ". ".join(parts) + "."


# ═══════════════════════════════════════════════════════
# FORMATTING
# ═══════════════════════════════════════════════════════

def format_delta_for_prompt(delta_report: DeltaReport) -> str:
    """Format delta report for inclusion in the Opus synthesis prompt."""
    if delta_report.total_changes == 0:
        return ""

    lines = ["## WHAT CHANGED SINCE YESTERDAY", ""]

    if delta_report.high_significance:
        lines.append("### HIGH SIGNIFICANCE")
        for item in delta_report.high_significance:
            lines.append(f"- {item.narrative}")
        lines.append("")

    if delta_report.medium_significance:
        lines.append("### MEDIUM SIGNIFICANCE")
        for item in delta_report.medium_significance[:10]:
            lines.append(f"- {item.narrative}")
        lines.append("")

    if delta_report.summary:
        lines.append(f"SUMMARY: {delta_report.summary}")
        lines.append("")

    lines.append("INSTRUCTION: Focus your analysis on WHAT CHANGED. Do not summarize static data. Lead with the most important change and explain its implications for the portfolio.")
    lines.append("")

    return "\n".join(lines)


def format_delta_for_telegram(delta_report: DeltaReport) -> str:
    """Format delta report as Telegram HTML message."""
    lines = ["<b>What Changed Today</b>", ""]

    if delta_report.total_changes == 0:
        lines.append("<i>Quiet day — no material changes.</i>")
        return "\n".join(lines)

    if delta_report.summary:
        lines.append(f"<i>{delta_report.summary}</i>")
        lines.append("")

    if delta_report.high_significance:
        for item in delta_report.high_significance:
            lines.append(f"  {item.narrative}")
        lines.append("")

    if delta_report.medium_significance:
        lines.append("<b>Also noted:</b>")
        for item in delta_report.medium_significance[:5]:
            lines.append(f"  {item.narrative}")

    return "\n".join(lines)
