"""Compact daily investment brief for AlphaDesk Advisor.

Generates a scannable, exception-based report designed to be read on
a phone in 30 seconds.  7 sections (down from 13), card-based HTML,
mobile-first layout.

Sections:
  1. Header Banner (portfolio value, P&L, headline)
  2. What Changed Today (CIO synthesis)
  3. Market Pulse (macro one-liner + active theses)
  4. Portfolio (tiered: movers get cards, steady gets a table)
  5. Actions & Risks (strategy + risk officer top concern)
  6. Watchlist (conviction + moonshots)
  7. Upcoming (catalysts next 7 days)
  Footer (sources, cost, timestamp)
"""
from __future__ import annotations

import re
from datetime import datetime, date
from typing import Any

from src.utils.logger import get_logger

log = get_logger(__name__)

# ── helpers ──────────────────────────────────────────────────────

MOVER_THRESHOLD = 2.0  # |change%| above this → full card


def _safe(val: Any, fmt: str = "", default: str = "N/A") -> str:
    if val is None:
        return default
    try:
        return f"{val:{fmt}}" if fmt else str(val)
    except (ValueError, TypeError):
        return default


def _pct(val: float | None, signed: bool = False) -> str:
    if val is None:
        return "N/A"
    return f"{val:+.1f}%" if signed else f"{val:.1f}%"


def _dollar(val: float | None) -> str:
    if val is None:
        return "N/A"
    if abs(val) >= 1_000_000_000:
        return f"${val / 1_000_000_000:,.1f}B"
    if abs(val) >= 1_000_000:
        return f"${val / 1_000_000:,.1f}M"
    if abs(val) >= 1_000:
        return f"${val / 1_000:,.1f}K"
    return f"${val:,.2f}"


def _color(val: float | None) -> str:
    """Return CSS color for a numeric value."""
    if val is None or val == 0:
        return "#64748b"
    return "#16a34a" if val > 0 else "#dc2626"


def _status_pill(status: str) -> str:
    """HTML pill badge for thesis status."""
    s = status.lower()
    if s == "strengthening":
        return '<span style="background:#dcfce7;color:#166534;padding:3px 9px;border-radius:12px;font-size:0.8em;font-weight:600">STRENGTHENING</span>'
    if s in ("stable", "intact"):
        return '<span style="background:#dbeafe;color:#1e40af;padding:3px 9px;border-radius:12px;font-size:0.8em;font-weight:600">STABLE</span>'
    if s in ("evolving", "monitoring"):
        return '<span style="background:#fef3c7;color:#92400e;padding:3px 9px;border-radius:12px;font-size:0.8em;font-weight:600">EVOLVING</span>'
    if s == "weakening":
        return '<span style="background:#fed7aa;color:#9a3412;padding:3px 9px;border-radius:12px;font-size:0.8em;font-weight:600">WEAKENING</span>'
    if s in ("broken", "invalidated"):
        return '<span style="background:#fecaca;color:#991b1b;padding:3px 9px;border-radius:12px;font-size:0.8em;font-weight:600">BROKEN</span>'
    return '<span style="background:#e2e8f0;color:#475569;padding:3px 9px;border-radius:12px;font-size:0.8em;font-weight:600">UNKNOWN</span>'


def _conviction_pill(conviction: str) -> str:
    c = conviction.lower()
    if c == "high":
        return '<span style="background:#dcfce7;color:#166534;padding:3px 8px;border-radius:8px;font-size:0.78em;font-weight:600">HIGH</span>'
    if c == "medium":
        return '<span style="background:#fef3c7;color:#92400e;padding:3px 8px;border-radius:8px;font-size:0.78em;font-weight:600">MED</span>'
    return '<span style="background:#e2e8f0;color:#475569;padding:3px 8px;border-radius:8px;font-size:0.78em;font-weight:600">LOW</span>'


def _esc(text: str) -> str:
    """Escape HTML entities."""
    return (text.replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


# ── main class ───────────────────────────────────────────────────

class VerboseFormatter:
    """Generates compact daily brief from pipeline data."""

    def __init__(
        self,
        holdings_reports: list[dict] | None = None,
        fundamentals: dict | None = None,
        technicals: dict | None = None,
        macro_data: dict | None = None,
        strategy: dict | None = None,
        conviction_result: dict | None = None,
        moonshot_result: dict | None = None,
        delta_report: Any | None = None,
        catalyst_data: dict | None = None,
        committee_result: dict | None = None,
        updated_theses: list[dict] | None = None,
        prediction_shifts: list[dict] | None = None,
        news_signals: list[dict] | None = None,
        top_articles: list[dict] | None = None,
        earnings_data: dict | None = None,
        superinvestor_data: dict | None = None,
        scorecard: dict | None = None,
        reddit_mood: str = "",
        reddit_themes: list[str] | None = None,
        reddit_signals: list[dict] | None = None,
        substack_signals: list[dict] | None = None,
        youtube_signals: list[dict] | None = None,
        novel_ideas: list[dict] | None = None,
        sector_scanner_signals: list[dict] | None = None,
        sector_scanner_formatted: str = "",
        daily_cost: float = 0.0,
        total_time: float = 0.0,
    ):
        self.novel_ideas = novel_ideas or []
        self.sector_scanner_signals = sector_scanner_signals or []
        self.sector_scanner_formatted = sector_scanner_formatted
        self.holdings_reports = holdings_reports or []
        self.fundamentals = fundamentals or {}
        self.technicals = technicals or {}
        self.macro_data = macro_data or {}
        self.strategy = strategy or {}
        self.conviction_result = conviction_result or {}
        self.moonshot_result = moonshot_result or {}
        self.delta_report = delta_report
        self.catalyst_data = catalyst_data or {}
        self.committee_result = committee_result or {}
        self.updated_theses = updated_theses or []
        self.prediction_shifts = prediction_shifts or []
        self.news_signals = news_signals or []
        self.top_articles = top_articles or []
        self.earnings_data = earnings_data or {}
        self.superinvestor_data = superinvestor_data or {}
        self.scorecard = scorecard or {}
        self.reddit_mood = reddit_mood
        self.reddit_themes = reddit_themes or []
        self.reddit_signals = reddit_signals or []
        self.substack_signals = substack_signals or []
        self.youtube_signals = youtube_signals or []
        self.daily_cost = daily_cost
        self.total_time = total_time
        # Deep research blocks: dict of ticker -> {"content": str, "tier": "full"|"summary"}
        self._deep_research_blocks: dict[str, dict] = {}
        deep_research = (committee_result or {}).get("deep_research", {})
        if isinstance(deep_research, dict):
            raw_blocks = deep_research.get("blocks", {})
            for ticker, block in raw_blocks.items():
                if isinstance(block, str):
                    # Old format — backward compat
                    self._deep_research_blocks[ticker] = {"content": block, "tier": "full"}
                elif isinstance(block, dict):
                    self._deep_research_blocks[ticker] = block
                else:
                    self._deep_research_blocks[ticker] = {"content": str(block), "tier": "full"}

    # ── public API (same interface as before) ────────────────────

    def generate_markdown(self) -> str:
        """Generate a compact plain-text version of the brief."""
        today = datetime.now().strftime("%B %d, %Y")
        totals = self._compute_totals()
        sections = [
            f"AlphaDesk Daily Brief — {today}",
            "=" * 50,
            "",
            self._md_header(totals),
            self._md_what_changed(),
            self._md_mandate_breaches(),
            self._md_market_pulse(),
            self._md_theme_dashboard(),
            self._md_portfolio(totals),
            self._md_actions_risks(),
            self._md_deep_research(),
            self._md_signal_intelligence(),
            self._md_prediction_markets(),
            self._md_smart_money(),
            self._md_watchlist(),
            self._md_novel_ideas(),
            self._md_sector_scanner(),
            self._md_cross_asset_risks(),
            self._md_thesis_breakers(),
            self._md_upcoming(),
            self._md_footer(),
        ]
        return "\n".join(s for s in sections if s)

    def generate_html(self, markdown_text: str | None = None) -> str:
        """Generate the HTML email directly (ignores markdown_text)."""
        totals = self._compute_totals()
        parts = [
            self._html_head(),
            '<body><div class="container">',
            self._html_header(totals),
            self._html_what_changed(),
            self._html_mandate_breaches(),
            self._html_market_pulse(),
            self._html_portfolio(totals),
            self._html_actions_risks(),
            self._html_deep_research(),
            self._html_signal_intelligence(),
            self._html_prediction_markets(),
            self._html_smart_money(),
            self._html_watchlist(),
            self._html_novel_ideas(),
            self._html_sector_scanner(),
            self._html_upcoming(),
            self._html_footer(),
            '</div></body></html>',
        ]
        return "\n".join(p for p in parts if p)

    # ── compute totals ───────────────────────────────────────────

    def _compute_totals(self) -> dict:
        total_value = 0.0
        total_daily_pnl = 0.0
        total_unrealized = 0.0
        for h in self.holdings_reports:
            price = h.get("price")
            shares = h.get("shares") or 0
            entry = h.get("entry_price")
            change_pct = h.get("change_pct") or 0
            if price and shares:
                mv = price * shares
                total_value += mv
                total_daily_pnl += mv * change_pct / 100
                if entry and entry > 0:
                    total_unrealized += (price - entry) * shares
        return {
            "value": total_value,
            "daily_pnl": total_daily_pnl,
            "unrealized": total_unrealized,
            "holdings_count": len(self.holdings_reports),
        }

    def _get_headline(self) -> str:
        """Extract the one-line headline from the CIO brief."""
        brief = self.committee_result.get("formatted_brief", "")
        if not brief:
            return ""
        # Take the first non-empty, non-header line (skip section titles)
        for line in brief.strip().splitlines():
            stripped = line.strip()
            # Skip section headers like **SECTION 1 - ...**
            if stripped.startswith("**") and stripped.endswith("**"):
                continue
            cleaned = stripped.lstrip("#*- ").rstrip("*")
            if len(cleaned) > 20:
                return cleaned[:200]
        return ""

    def _get_cio_sections(self) -> dict[str, str]:
        """Parse CIO brief into named sections.

        Handles both old format (SECTION 1 - WHAT CHANGED TODAY) and
        new format (SECTION 1 - EXECUTIVE TAKE, SECTION 2 - THEME DASHBOARD, etc).
        """
        brief = self.committee_result.get("formatted_brief", "")
        if not brief:
            return {}
        # Strip memo headers (TO:/FROM:/DATE:/SUBJECT:) that the LLM may produce
        brief = re.sub(r'(?m)^\*{0,2}(?:TO|FROM|DATE|SUBJECT)\*{0,2}\s*:.*$', '', brief)
        sections = {}
        current_key = ""
        current_lines: list[str] = []
        for line in brief.strip().splitlines():
            stripped = line.strip()
            # Detect section headers like "**SECTION 1 - EXECUTIVE TAKE**"
            header_match = re.match(r"\*{0,2}(?:SECTION\s+\d+\s*[-—]\s*)?(.+?)\*{0,2}\s*$", stripped)
            if header_match and stripped.startswith("**"):
                if current_key:
                    sections[current_key] = "\n".join(current_lines).strip()
                current_key = header_match.group(1).strip().lower()
                current_lines = []
            else:
                current_lines.append(line)
        if current_key:
            sections[current_key] = "\n".join(current_lines).strip()
        return sections

    # ══════════════════════════════════════════════════════════════
    # MARKDOWN (plain-text fallback)
    # ══════════════════════════════════════════════════════════════

    def _md_header(self, totals: dict) -> str:
        headline = self._get_headline()
        if headline:
            return f"> {headline}\n"
        return ""

    def _md_what_changed(self) -> str:
        cio = self._get_cio_sections()
        text = cio.get("executive take", "") or cio.get("what changed today", "")
        if not text:
            brief = self.committee_result.get("formatted_brief", "")
            if brief:
                paras = brief.strip().split("\n\n")
                text = paras[0] if paras else ""
        if not text:
            return ""
        text = re.sub(r"\*{1,2}(.+?)\*{1,2}", r"\1", text)
        return f"EXECUTIVE TAKE\n{'-' * 40}\n{text}\n"

    def _md_mandate_breaches(self) -> str:
        """Render mandate breach warnings in plain text."""
        actions = self.strategy.get("actions", [])
        breaches = [a for a in actions if "exceeds max" in (a.get("reason", "") or "").lower()]
        if not breaches:
            return ""
        lines = [f"{'!'*50}", "  RISK MANDATE VIOLATIONS", f"{'!'*50}"]
        for b in breaches:
            ticker = b.get("ticker", "")
            reason = b.get("reason", "")
            urgency = b.get("urgency", "low").upper()
            lines.append(f"  ⚠ {b.get('action', 'TRIM').upper()} {ticker}: {reason} [{urgency}]")
        lines.append(f"{'!'*50}")
        return "\n".join(lines) + "\n"

    def _md_market_pulse(self) -> str:
        def _mv(key: str):
            v = self.macro_data.get(key)
            if isinstance(v, dict):
                return _safe(v.get("value"), ".2f"), v.get("change_pct")
            return _safe(v, ".2f"), None

        sp_val, sp_chg = _mv("sp500")
        vix_val, _ = _mv("vix")
        tnx_val, _ = _mv("treasury_10y")
        ff_val, _ = _mv("fed_funds_rate")

        sp_str = f"S&P {sp_val}"
        if sp_chg is not None:
            sp_str += f" ({sp_chg:+.1f}%)"

        line = f"{sp_str}  |  VIX {vix_val}  |  10Y {tnx_val}%  |  Fed {ff_val}%"
        lines = [f"MARKET\n{'-' * 40}", line]

        if self.reddit_mood and self.reddit_mood != "unknown":
            themes = ", ".join(self.reddit_themes[:3]) if self.reddit_themes else ""
            mood_line = f"Reddit: {self.reddit_mood}"
            if themes:
                mood_line += f" — {themes}"
            lines.append(mood_line)

        return "\n".join(lines) + "\n"

    def _md_portfolio(self, totals: dict) -> str:
        lines = [f"PORTFOLIO\n{'-' * 40}"]
        sorted_h = sorted(self.holdings_reports, key=lambda h: abs(h.get("change_pct") or 0), reverse=True)

        movers = [h for h in sorted_h if abs(h.get("change_pct") or 0) >= MOVER_THRESHOLD]
        steady = [h for h in sorted_h if abs(h.get("change_pct") or 0) < MOVER_THRESHOLD]

        if movers:
            lines.append("\nMOVERS:")
            for h in movers:
                t = h.get("ticker", "?")
                chg = h.get("change_pct") or 0
                price = h.get("price")
                pct = h.get("position_pct") or 0
                arrow = "+" if chg > 0 else ""
                lines.append(f"  {t}  ${price}  {arrow}{chg:.1f}%  ({pct:.0f}% of portfolio)")
                events = h.get("key_events", [])[:2]
                for e in events:
                    lines.append(f"    -> {e}")

        if steady:
            lines.append("\nSTEADY:")
            for h in steady:
                t = h.get("ticker", "?")
                chg = h.get("change_pct") or 0
                price = h.get("price")
                pct = h.get("position_pct") or 0
                lines.append(f"  {t}  ${price}  {chg:+.1f}%  ({pct:.0f}%)")

        return "\n".join(lines) + "\n"

    def _md_actions_risks(self) -> str:
        actions = self.strategy.get("actions", [])
        # Filter out mandate breaches (shown in dedicated banner)
        actions = [a for a in actions if "exceeds max" not in (a.get("reason", "") or "").lower()]
        risk = self.committee_result.get("risk_report", {})
        if not actions and not risk:
            return ""
        lines = [f"ACTIONS & RISKS\n{'-' * 40}"]
        if actions:
            for a in actions:
                lines.append(f"  {a.get('action', 'HOLD').upper()} {a.get('ticker', '')} — {a.get('reason', '')}")
        top_risk = risk.get("top_risk", "")
        risk_score = risk.get("risk_score_portfolio")
        if top_risk:
            score_str = f" (safety: {risk_score}/100)" if risk_score is not None else ""
            lines.append(f"\n  Top Risk{score_str}: {top_risk}")
        return "\n".join(lines) + "\n"

    def _md_signal_intelligence(self) -> str:
        has_reddit = bool(self.reddit_signals)
        has_substack = bool(self.substack_signals)
        has_youtube = bool(self.youtube_signals)
        has_articles = bool(self.top_articles)
        if not any([has_reddit, has_substack, has_youtube, has_articles]):
            return ""
        lines = [f"SIGNAL INTELLIGENCE\n{'-' * 40}"]

        if has_articles:
            lines.append("\nTop Headlines:")
            for a in self.top_articles[:5]:
                title = a.get("title", "")
                source = a.get("source", "")
                url = a.get("url", "")
                tickers = a.get("related_tickers") or a.get("affected_tickers", [])
                ticker_str = f" [{', '.join(tickers[:3])}]" if tickers else ""
                title_str = f'<a href="{url}">{title}</a>' if url else title
                lines.append(f"  {title_str}{ticker_str} — {source}")

        if has_reddit:
            lines.append("\nReddit Threads:")
            for s in self.reddit_signals[:5]:
                ticker = s.get("ticker", "")
                sentiment = s.get("sentiment", "")
                mentions = s.get("mentions", "")
                subs = s.get("subreddits", s.get("subreddit", ""))
                first_sub = str(subs).split(",")[0].strip() if subs else ""
                reddit_url = f"https://reddit.com/r/{first_sub}/search?q={ticker}&sort=top&t=day" if first_sub and ticker else ""
                ticker_str = f'<a href="{reddit_url}">{ticker}</a>' if reddit_url else ticker
                lines.append(f"  {ticker_str}: sentiment {sentiment}, {mentions} mentions ({subs})")

        if has_substack:
            lines.append("\nSubstack Newsletters:")
            for s in self.substack_signals[:5]:
                title = s.get("title", "")
                url = s.get("url", "")
                tickers = s.get("tickers", [])
                ticker_str = f" [{', '.join(tickers[:3])}]" if tickers else ""
                title_str = f'<a href="{url}">{title}</a>' if url else title
                lines.append(f"  {title_str}{ticker_str}")

        if has_youtube:
            lines.append("\nYouTube:")
            for y in self.youtube_signals[:3]:
                title = y.get("title", "")
                channel = y.get("channel", "")
                url = y.get("url", "")
                title_str = f'<a href="{url}">{title}</a>' if url else title
                lines.append(f"  {title_str} — {channel}")

        return "\n".join(lines) + "\n"

    def _md_prediction_markets(self) -> str:
        if not self.prediction_shifts:
            return ""
        lines = [f"PREDICTION MARKETS\n{'-' * 40}"]
        for pm in self.prediction_shifts[:5]:
            title = pm.get("title", pm.get("market_title", ""))
            prob = pm.get("probability", 0)
            delta = pm.get("delta", pm.get("delta_pct", 0))
            if isinstance(delta, float) and delta < 1:
                delta = delta * 100  # Convert from 0.15 to 15
            direction = "UP" if delta > 0 else "DOWN"
            lines.append(f"  {title}: {prob * 100 if prob < 1 else prob:.0f}% ({delta:+.0f}pp {direction})")
        return "\n".join(lines) + "\n"

    def _md_smart_money(self) -> str:
        if not self.superinvestor_data:
            return ""
        notable = []
        for ticker, data in self.superinvestor_data.items():
            if not isinstance(data, dict):
                continue
            insider = data.get("insider_net_buying")
            supers = data.get("superinvestors_holding", [])
            activity = data.get("superinvestor_activity", [])
            if insider or supers or activity:
                parts = [f"  {ticker}:"]
                if insider:
                    parts.append("insider net buying")
                if supers:
                    parts.append(f"held by {', '.join(supers[:3])}")
                if activity:
                    recent = activity[0]
                    parts.append(f"{recent.get('investor', '')} {recent.get('action', '')}")
                notable.append(" | ".join(parts))
        if not notable:
            return ""
        lines = [f"SMART MONEY\n{'-' * 40}"] + notable[:6]
        return "\n".join(lines) + "\n"

    def _md_watchlist(self) -> str:
        conviction = self.conviction_result.get("current_list", [])
        moonshots = self.moonshot_result.get("current_list", [])
        if not conviction and not moonshots:
            return ""
        lines = [f"WATCHLIST\n{'-' * 40}"]
        for c in conviction:
            t = c.get("ticker", "?")
            conv = c.get("conviction", "med").upper()
            thesis = c.get("thesis", "")
            source = c.get("source", "")
            lines.append(f"\n  {t} [{conv}] — W{c.get('weeks_on_list', 1)}")
            if thesis:
                lines.append(f"    {thesis}")
            if source:
                lines.append(f"    Source: {source}")
            # Cross-reference signals
            intel = self._gather_ticker_intel(t)
            for line in intel:
                lines.append(f"    {line}")
            # Evidence as compact scorecard
            pros = c.get("pros", [])
            cons = c.get("cons", [])
            checks: list[str] = []
            for p in (pros if isinstance(pros, list) else []):
                label = self._parse_evidence_label(p)
                checks.append(f"✓ {label}")
            for co in (cons if isinstance(cons, list) else []):
                label = self._parse_evidence_label(co)
                checks.append(f"✗ {label}")
            if checks:
                lines.append(f"    Evidence: {' | '.join(checks)}")

        for m in moonshots:
            t = m.get("ticker", "?")
            thesis = m.get("thesis", "")
            upside = m.get("upside_case", "")
            downside = m.get("downside_case", "")
            milestone = m.get("key_milestone", "")
            lines.append(f"\n  {t} [MOONSHOT]")
            if thesis:
                lines.append(f"    {thesis}")
            if upside:
                lines.append(f"    ▲ Bull: {upside}")
            if downside:
                lines.append(f"    ▼ Bear: {downside}")
            if milestone:
                lines.append(f"    Key milestone: {milestone}")
            intel = self._gather_ticker_intel(t)
            for line in intel:
                lines.append(f"    {line}")
        return "\n".join(lines) + "\n"

    def _md_novel_ideas(self) -> str:
        if not self.novel_ideas:
            return ""
        lines = [f"NOVEL IDEAS\n{'-' * 40}"]
        for idea in self.novel_ideas:
            ticker = idea.get("ticker")
            theme = idea.get("theme", "")
            thesis = idea.get("thesis", "")
            source = idea.get("source_signals", "")
            ticker_str = f" {ticker}" if ticker else ""
            lines.append(f"\n  💡{ticker_str} — {theme}")
            if thesis:
                lines.append(f"    {thesis}")
            if source:
                lines.append(f"    Signals: {source}")
        return "\n".join(lines) + "\n"

    def _md_sector_scanner(self) -> str:
        if not self.sector_scanner_signals:
            return ""
        direction_arrow = {"bullish": "↑", "bearish": "↓", "mixed": "↔", "neutral": "—"}
        lines = [f"SECTOR SCANNER\n{'-' * 40}"]
        # Group by sector
        sectors: dict[str, list[dict]] = {}
        for sig in self.sector_scanner_signals:
            sector = sig.get("sector", "unknown")
            sectors.setdefault(sector, []).append(sig)
        for sector, sigs in sorted(sectors.items()):
            label = sector.replace("_", " ").title()
            momentum = [s for s in sigs if s.get("type") == "sector_momentum"]
            catalysts = [s for s in sigs if s.get("type") == "sector_catalyst"]
            if momentum:
                m = momentum[0]
                arrow = direction_arrow.get(m.get("direction", ""), "—")
                lines.append(f"\n  {arrow} {label} ({m.get('article_count', 0)} articles)")
                if m.get("top_summary"):
                    lines.append(f"    {m['top_summary']}")
            for c in catalysts[:2]:
                lines.append(f"    • {c.get('summary', c.get('title', ''))}")
                tickers = c.get("tickers", [])
                if tickers:
                    lines.append(f"      Tickers: {', '.join(tickers[:5])}")
        return "\n".join(lines) + "\n"

    def _gather_ticker_intel(self, ticker: str) -> list[str]:
        """Cross-reference a ticker across all signal sources."""
        intel: list[str] = []
        # Reddit
        for s in self.reddit_signals:
            if s.get("ticker", "").upper() == ticker.upper():
                sent = s.get("sentiment", s.get("sentiment_score", ""))
                mentions = s.get("mentions", s.get("mention_count", ""))
                sub = s.get("subreddit", "")
                intel.append(f"Reddit: sentiment {sent}, {mentions} mentions ({sub})")
                break
        # Substack
        for s in self.substack_signals:
            tickers = [t.upper() for t in s.get("tickers", s.get("affected_tickers", []))]
            if ticker.upper() in tickers:
                title = s.get("title", "")
                intel.append(f"Substack: {title}")
                break
        # Smart money
        si = self.superinvestor_data.get(ticker, {})
        if isinstance(si, dict):
            supers = si.get("superinvestors_holding", [])
            insider = si.get("insider_net_buying")
            parts = []
            if insider:
                parts.append("insider buying")
            if supers:
                parts.append(f"held by {', '.join(str(s) for s in supers[:3])}")
            if parts:
                intel.append(f"Smart money: {', '.join(parts)}")
        # Fundamentals
        fund = self.fundamentals.get(ticker, {})
        if fund:
            parts = []
            pe = fund.get("pe_forward")
            rev = fund.get("revenue_growth")
            margin = fund.get("net_margin")
            if pe is not None:
                parts.append(f"P/E(f) {pe:.1f}")
            if rev is not None:
                parts.append(f"Rev +{rev:.0%}")
            if margin is not None:
                parts.append(f"Margin {margin:.0%}")
            if parts:
                intel.append(f"Fundamentals: {' | '.join(parts)}")
        return intel

    def _md_theme_dashboard(self) -> str:
        """Render theme dashboard from CIO brief's THEME DASHBOARD section."""
        cio = self._get_cio_sections()
        text = cio.get("theme dashboard", "")
        if not text:
            return ""
        text = re.sub(r"\*{1,2}(.+?)\*{1,2}", r"\1", text)
        return f"THEME DASHBOARD\n{'-' * 40}\n{text}\n"

    def _md_deep_research(self) -> str:
        """Render deep research blocks with tiered depth."""
        if not self._deep_research_blocks:
            return ""
        full_lines = []
        summary_lines = []
        for ticker, block_data in self._deep_research_blocks.items():
            content = block_data.get("content", "") if isinstance(block_data, dict) else str(block_data)
            tier = block_data.get("tier", "full") if isinstance(block_data, dict) else "full"
            if not content:
                continue
            if tier == "summary":
                summary_lines.append(f"\n  {ticker}: {content.strip()}")
            else:
                full_lines.append(f"\n## {ticker} — Deep Research")
                full_lines.append(content)
                full_lines.append("")
        lines = []
        if full_lines:
            lines.append(f"DEEP RESEARCH\n{'=' * 50}")
            lines.extend(full_lines)
        if summary_lines:
            lines.append(f"\nQUICK TAKES\n{'-' * 40}")
            lines.extend(summary_lines)
            lines.append("")
        return "\n".join(lines)

    def _md_cross_asset_risks(self) -> str:
        """Render cross-asset / macro risks from CIO brief."""
        cio = self._get_cio_sections()
        text = cio.get("cross-asset / macro risks", "") or cio.get("cross-asset risks", "")
        if not text:
            return ""
        text = re.sub(r"\*{1,2}(.+?)\*{1,2}", r"\1", text)
        return f"CROSS-ASSET / MACRO RISKS\n{'-' * 40}\n{text}\n"

    def _md_thesis_breakers(self) -> str:
        """Render thesis breakers from CIO brief."""
        cio = self._get_cio_sections()
        text = cio.get("thesis breakers", "")
        if not text:
            return ""
        text = re.sub(r"\*{1,2}(.+?)\*{1,2}", r"\1", text)
        return f"THESIS BREAKERS\n{'-' * 40}\n{text}\n"

    def _md_upcoming(self) -> str:
        catalysts = self.catalyst_data.get("catalysts", [])
        if not catalysts:
            return ""
        upcoming = [c for c in catalysts if self._days_away(c) <= 7]
        if not upcoming:
            return ""
        lines = [f"NEXT 7 DAYS\n{'-' * 40}"]
        for c in upcoming[:8]:
            dt = self._cat_date(c)
            desc = self._cat_desc(c)
            days = self._days_away(c)
            day_label = "today" if days == 0 else f"in {days}d"
            lines.append(f"  {dt}  {desc}  ({day_label})")
        return "\n".join(lines) + "\n"

    def _md_footer(self) -> str:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M")
        return f"---\nAlphaDesk v2.0 | ${self.daily_cost:.2f} | {self.total_time:.0f}s | {ts}"

    # ══════════════════════════════════════════════════════════════
    # HTML EMAIL
    # ══════════════════════════════════════════════════════════════

    def _html_head(self) -> str:
        today = datetime.now().strftime("%B %d, %Y")
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AlphaDesk Daily Brief — {today}</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', sans-serif;
    background: #f1f5f9;
    color: #1e293b;
    line-height: 1.65;
    font-size: 16px;
    -webkit-text-size-adjust: 100%;
  }}
  .container {{
    max-width: 680px;
    margin: 0 auto;
    background: #ffffff;
  }}

  /* Header banner */
  .header {{
    background: linear-gradient(135deg, #0f172a 0%, #1e3a5f 100%);
    color: #ffffff;
    padding: 28px 28px 24px;
  }}
  .header-title {{
    font-size: 0.85em;
    text-transform: uppercase;
    letter-spacing: 1.5px;
    color: #94a3b8;
    margin-bottom: 6px;
  }}
  .header-date {{
    font-size: 1.2em;
    font-weight: 600;
    margin-bottom: 18px;
  }}
  .header-stats {{
    display: flex;
    gap: 20px;
    flex-wrap: wrap;
  }}
  .stat {{
    text-align: left;
  }}
  .stat-label {{
    font-size: 0.75em;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    color: #94a3b8;
  }}
  .stat-value {{
    font-size: 1.35em;
    font-weight: 700;
  }}
  .headline {{
    margin-top: 16px;
    padding-top: 12px;
    border-top: 1px solid rgba(255,255,255,0.15);
    font-size: 0.95em;
    color: #cbd5e1;
    line-height: 1.4;
  }}

  /* Section */
  .section {{
    padding: 28px 28px;
    border-bottom: 1px solid #e2e8f0;
  }}
  .section:last-of-type {{
    border-bottom: none;
  }}
  .section-title {{
    font-size: 0.8em;
    text-transform: uppercase;
    letter-spacing: 1.5px;
    color: #94a3b8;
    margin-bottom: 16px;
    font-weight: 600;
  }}
  .section-body {{
    font-size: 1em;
    color: #334155;
    line-height: 1.65;
  }}
  .section-body p {{
    margin-bottom: 12px;
  }}

  /* Market pulse bar */
  .market-bar {{
    display: flex;
    gap: 0;
    flex-wrap: wrap;
    background: #f8fafc;
    border-radius: 8px;
    overflow: hidden;
    margin-bottom: 12px;
  }}
  .market-item {{
    flex: 1;
    min-width: 80px;
    padding: 12px 14px;
    text-align: center;
    border-right: 1px solid #e2e8f0;
  }}
  .market-item:last-child {{
    border-right: none;
  }}
  .market-item-label {{
    font-size: 0.75em;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    color: #94a3b8;
  }}
  .market-item-value {{
    font-size: 1em;
    font-weight: 600;
    color: #1e293b;
  }}

  /* Holding card (movers) */
  .holding-card {{
    background: #f8fafc;
    border-radius: 8px;
    padding: 16px 20px;
    margin-bottom: 10px;
    border-left: 4px solid #e2e8f0;
  }}
  .holding-card.up {{
    border-left-color: #16a34a;
  }}
  .holding-card.down {{
    border-left-color: #dc2626;
  }}
  .holding-top {{
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    margin-bottom: 4px;
  }}
  .holding-ticker {{
    font-weight: 700;
    font-size: 1.05em;
    color: #0f172a;
  }}
  .holding-change {{
    font-weight: 700;
    font-size: 1.05em;
  }}
  .holding-meta {{
    font-size: 0.88em;
    color: #64748b;
    margin-bottom: 8px;
  }}
  .holding-events {{
    font-size: 0.88em;
    color: #475569;
    padding-left: 10px;
    border-left: 2px solid #e2e8f0;
  }}
  .holding-events div {{
    margin-bottom: 4px;
  }}

  /* Steady holdings table */
  .steady-table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 0.92em;
    margin-top: 14px;
  }}
  .steady-table th {{
    text-align: left;
    font-size: 0.75em;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    color: #94a3b8;
    padding: 6px 10px;
    border-bottom: 1px solid #e2e8f0;
    font-weight: 600;
  }}
  .steady-table td {{
    padding: 8px 10px;
    color: #334155;
    border-bottom: 1px solid #f1f5f9;
  }}

  /* Action card */
  .action-card {{
    background: #fffbeb;
    border: 1px solid #fde68a;
    border-radius: 8px;
    padding: 14px 18px;
    margin-bottom: 10px;
  }}
  .action-label {{
    font-weight: 700;
    font-size: 0.92em;
    color: #92400e;
  }}
  .action-reason {{
    font-size: 0.92em;
    color: #78350f;
    margin-top: 4px;
  }}

  /* Risk block */
  .risk-block {{
    background: #fef2f2;
    border: 1px solid #fecaca;
    border-radius: 8px;
    padding: 14px 18px;
    margin-top: 10px;
  }}
  .risk-label {{
    font-weight: 600;
    font-size: 0.8em;
    text-transform: uppercase;
    color: #991b1b;
    margin-bottom: 6px;
  }}
  .risk-text {{
    font-size: 0.92em;
    color: #7f1d1d;
    line-height: 1.55;
  }}

  /* Watchlist */
  .watch-item {{
    display: flex;
    align-items: baseline;
    gap: 10px;
    padding: 10px 0;
    border-bottom: 1px solid #f1f5f9;
    font-size: 0.95em;
  }}
  .watch-item:last-child {{
    border-bottom: none;
  }}
  .watch-ticker {{
    font-weight: 700;
    color: #0f172a;
    min-width: 48px;
  }}
  .watch-thesis {{
    color: #475569;
    flex: 1;
  }}

  /* Upcoming events */
  .event-item {{
    display: flex;
    align-items: baseline;
    gap: 10px;
    padding: 8px 0;
    font-size: 0.95em;
    color: #334155;
  }}
  .event-date {{
    font-weight: 600;
    color: #0f172a;
    min-width: 64px;
    font-size: 0.88em;
  }}
  .event-days {{
    font-size: 0.82em;
    color: #94a3b8;
    white-space: nowrap;
  }}

  /* Thesis row */
  .thesis-row {{
    display: flex;
    align-items: baseline;
    gap: 10px;
    padding: 8px 0;
    font-size: 0.95em;
    border-bottom: 1px solid #f1f5f9;
  }}
  .thesis-row:last-child {{
    border-bottom: none;
  }}
  .thesis-name {{
    font-weight: 600;
    color: #1e293b;
  }}
  .thesis-tickers {{
    color: #64748b;
    font-size: 0.92em;
  }}

  /* Footer */
  .footer {{
    padding: 18px 28px;
    background: #f8fafc;
    border-top: 1px solid #e2e8f0;
    font-size: 0.82em;
    color: #94a3b8;
    text-align: center;
  }}

  /* Responsive */
  @media (max-width: 480px) {{
    .header {{ padding: 20px; }}
    .section {{ padding: 20px; }}
    .header-stats {{ gap: 12px; }}
    .stat-value {{ font-size: 1.15em; }}
    .market-item {{ padding: 10px; }}
  }}
</style>
</head>"""

    def _html_header(self, totals: dict) -> str:
        today = datetime.now().strftime("%B %d, %Y")
        headline = _esc(self._get_headline())

        headline_html = ""
        if headline:
            headline_html = f'<div class="headline">{headline}</div>'

        return f"""
<div class="header">
  <div class="header-title">AlphaDesk Daily Brief</div>
  <div class="header-date">{today}</div>
  {headline_html}
</div>"""

    def _html_what_changed(self) -> str:
        cio = self._get_cio_sections()
        # Try new format first, then old
        text = cio.get("executive take", "") or cio.get("what changed today", "")
        if not text:
            brief = self.committee_result.get("formatted_brief", "")
            if brief:
                paras = [p.strip() for p in brief.strip().split("\n\n") if len(p.strip()) > 30]
                text = paras[0] if paras else ""
        if not text:
            return ""

        text = re.sub(r"\*{1,2}(.+?)\*{1,2}", r"<strong>\1</strong>", text)
        lines = text.strip().splitlines()
        html_lines = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("- ") or stripped.startswith("* "):
                html_lines.append(f"<p style='padding-left:12px'>• {stripped[2:]}</p>")
            elif stripped:
                html_lines.append(f"<p>{stripped}</p>")
        body = "\n".join(html_lines)

        return f"""
<div class="section">
  <div class="section-title">Executive Take</div>
  <div class="section-body">{body}</div>
</div>"""

    def _html_mandate_breaches(self) -> str:
        """Render mandate breach warnings as a prominent banner."""
        actions = self.strategy.get("actions", [])
        breaches = [a for a in actions if "exceeds max" in (a.get("reason", "") or "").lower()]
        if not breaches:
            return ""

        items = []
        for b in breaches:
            ticker = _esc(b.get("ticker", ""))
            reason = _esc(b.get("reason", ""))
            urgency = b.get("urgency", "low")
            bg = "#fef2f2" if urgency == "high" else "#fffbeb"
            border = "#dc2626" if urgency == "high" else "#f59e0b"
            items.append(f"""
<div style="background:{bg};border:2px solid {border};border-radius:8px;padding:14px 18px;margin-bottom:8px">
  <div style="font-weight:700;color:{border};font-size:0.9em">&#9888; MANDATE BREACH &mdash; {ticker}</div>
  <div style="font-size:0.85em;color:#1e293b;margin-top:4px">{reason}. Action: {_esc(b.get('action', 'TRIM').upper())}.</div>
</div>""")

        return f"""
<div class="section" style="padding:16px 24px;background:#fef2f2;border-bottom:2px solid #fecaca">
  <div class="section-title" style="color:#991b1b">&#9888; Risk Mandate Violations</div>
  {"".join(items)}
</div>"""

    def _html_market_pulse(self) -> str:
        def _mv(key: str):
            v = self.macro_data.get(key)
            if isinstance(v, dict):
                return v.get("value"), v.get("change_pct")
            return v, None

        sp_val, sp_chg = _mv("sp500")
        vix_val, vix_chg = _mv("vix")
        tnx_val, _ = _mv("treasury_10y")
        ff_val, _ = _mv("fed_funds_rate")

        sp_str = _safe(sp_val, ",.0f")
        sp_chg_html = f'<span style="color:{_color(sp_chg)};font-size:0.8em"> {sp_chg:+.1f}%</span>' if sp_chg is not None else ""
        vix_str = _safe(vix_val, ".1f")
        vix_chg_html = f'<span style="color:{_color(vix_chg)};font-size:0.8em"> {vix_chg:+.1f}%</span>' if vix_chg is not None else ""

        market_bar = f"""
<div class="market-bar">
  <div class="market-item">
    <div class="market-item-label">S&amp;P 500</div>
    <div class="market-item-value">{sp_str}{sp_chg_html}</div>
  </div>
  <div class="market-item">
    <div class="market-item-label">VIX</div>
    <div class="market-item-value">{vix_str}{vix_chg_html}</div>
  </div>
  <div class="market-item">
    <div class="market-item-label">10Y</div>
    <div class="market-item-value">{_safe(tnx_val, '.2f')}%</div>
  </div>
  <div class="market-item">
    <div class="market-item-label">Fed</div>
    <div class="market-item-value">{_safe(ff_val, '.2f')}%</div>
  </div>
</div>"""

        # Active theses — prefer CIO's theme dashboard, fallback to simple status
        theses_html = ""
        cio = self._get_cio_sections()
        theme_dashboard_text = cio.get("theme dashboard", "")
        if theme_dashboard_text:
            # Use the CIO's evidence-based theme dashboard
            dashboard_html = self._md_to_html(theme_dashboard_text)
            theses_html = f"""
<div style="margin-top:10px;font-size:0.92em;color:#334155">
  <div style="font-size:0.78em;text-transform:uppercase;letter-spacing:1px;color:#94a3b8;font-weight:600;margin-bottom:10px">Theme Dashboard</div>
  {dashboard_html}
</div>"""
        elif self.updated_theses:
            thesis_items = []
            for t in self.updated_theses:
                title = _esc(t.get("title", ""))
                status = t.get("status", "intact")
                affected = ", ".join(t.get("affected_tickers", [])[:5])
                thesis_items.append(f"""
<div class="thesis-row">
  <span class="thesis-name">{title}</span>
  {_status_pill(status)}
  <span class="thesis-tickers">{affected}</span>
</div>""")
            if thesis_items:
                theses_html = "\n".join(thesis_items)

        # Reddit mood
        reddit_html = ""
        if self.reddit_mood and self.reddit_mood != "unknown":
            themes = ", ".join(self.reddit_themes[:3]) if self.reddit_themes else ""
            mood_text = f"Reddit mood: <strong>{_esc(self.reddit_mood)}</strong>"
            if themes:
                mood_text += f" — {_esc(themes)}"
            reddit_html = f'<div style="font-size:0.8em;color:#64748b;margin-top:8px">{mood_text}</div>'

        return f"""
<div class="section">
  <div class="section-title">Market Pulse</div>
  {market_bar}
  {theses_html}
  {reddit_html}
</div>"""

    def _html_portfolio(self, totals: dict) -> str:
        if not self.holdings_reports:
            return ""

        sorted_h = sorted(self.holdings_reports, key=lambda h: abs(h.get("change_pct") or 0), reverse=True)
        movers = [h for h in sorted_h if abs(h.get("change_pct") or 0) >= MOVER_THRESHOLD]
        steady = [h for h in sorted_h if abs(h.get("change_pct") or 0) < MOVER_THRESHOLD]

        cards_html = ""
        if movers:
            cards = []
            for h in movers:
                ticker = _esc(h.get("ticker", "?"))
                price = h.get("price")
                chg = h.get("change_pct") or 0
                pct = h.get("position_pct") or 0
                thesis = _esc(h.get("thesis", ""))
                thesis_status = h.get("thesis_status", "intact")
                direction = "up" if chg > 0 else "down"
                chg_color = _color(chg)

                # Key events (top 2)
                events = h.get("key_events", [])[:2]
                events_html = ""
                if events:
                    ev_items = "".join(f"<div>• {_esc(str(e)[:100])}</div>" for e in events)
                    events_html = f'<div class="holding-events">{ev_items}</div>'

                # Fundamentals one-liner
                fund = self.fundamentals.get(h.get("ticker", ""), {})
                fund_parts = []
                pe_fwd = fund.get("pe_forward")
                if pe_fwd is not None:
                    fund_parts.append(f"P/E(f) {pe_fwd:.1f}")
                rev = fund.get("revenue_growth")
                if rev is not None:
                    fund_parts.append(f"Rev +{rev:.0%}")
                fund_str = " · ".join(fund_parts)
                fund_html = f'<span style="color:#94a3b8;margin-left:8px">{fund_str}</span>' if fund_str else ""

                cards.append(f"""
<div class="holding-card {direction}">
  <div class="holding-top">
    <span>
      <span class="holding-ticker">{ticker}</span>
      <span style="color:#64748b;font-size:0.85em;margin-left:6px">{_dollar(price)}</span>
      {fund_html}
    </span>
    <span class="holding-change" style="color:{chg_color}">{chg:+.1f}%</span>
  </div>
  <div class="holding-meta">
    {pct:.1f}% of portfolio · {thesis} {_status_pill(thesis_status)}
  </div>
  {events_html}
</div>""")
            cards_html = "\n".join(cards)

        # Steady table
        table_html = ""
        if steady:
            rows = []
            for h in steady:
                ticker = _esc(h.get("ticker", "?"))
                price = h.get("price")
                chg = h.get("change_pct") or 0
                pct = h.get("position_pct") or 0
                thesis_status = h.get("thesis_status", "intact")
                chg_color = _color(chg)
                rows.append(f"""<tr>
  <td style="font-weight:600">{ticker}</td>
  <td>{_dollar(price)}</td>
  <td style="color:{chg_color};font-weight:600">{chg:+.1f}%</td>
  <td>{pct:.1f}%</td>
  <td>{_status_pill(thesis_status)}</td>
</tr>""")
            rows_html = "\n".join(rows)
            table_html = f"""
<table class="steady-table" style="margin-top:12px">
  <thead>
    <tr><th>Ticker</th><th>Price</th><th>Change</th><th>Weight</th><th>Thesis</th></tr>
  </thead>
  <tbody>{rows_html}</tbody>
</table>"""

        movers_label = f'<div style="font-size:0.82em;text-transform:uppercase;letter-spacing:1px;color:#94a3b8;margin-bottom:10px;font-weight:600">Movers</div>' if movers else ""
        steady_label = f'<div style="font-size:0.82em;text-transform:uppercase;letter-spacing:1px;color:#94a3b8;margin-top:18px;margin-bottom:6px;font-weight:600">Steady</div>' if steady else ""

        return f"""
<div class="section">
  <div class="section-title">Portfolio</div>
  {movers_label}
  {cards_html}
  {steady_label}
  {table_html}
</div>"""

    def _html_actions_risks(self) -> str:
        actions = self.strategy.get("actions", [])
        # Filter out mandate breaches (shown in dedicated banner)
        actions = [a for a in actions if "exceeds max" not in (a.get("reason", "") or "").lower()]
        risk = self.committee_result.get("risk_report", {})
        top_risk = risk.get("top_risk", "") if isinstance(risk, dict) else ""
        risk_score = risk.get("risk_score_portfolio") if isinstance(risk, dict) else None

        if not actions and not top_risk:
            return ""

        # Action cards
        actions_html = ""
        if actions:
            action_items = []
            for a in actions:
                act = _esc(a.get("action", "hold").upper())
                ticker = _esc(a.get("ticker", ""))
                urgency = a.get("urgency", "low")
                reason = _esc(a.get("reason", ""))
                urgency_color = "#dc2626" if urgency == "high" else "#d97706" if urgency == "medium" else "#64748b"
                action_items.append(f"""
<div class="action-card">
  <div class="action-label">
    <span style="color:{urgency_color}">{act}</span> {ticker}
    <span style="font-weight:400;font-size:0.85em;color:#94a3b8;margin-left:6px">{urgency}</span>
  </div>
  <div class="action-reason">{reason}</div>
</div>""")
            actions_html = "\n".join(action_items)

        # Risk block
        risk_html = ""
        if top_risk:
            score_html = ""
            if risk_score is not None:
                # Color based on safety score (higher = safer)
                if risk_score >= 60:
                    score_color = "#166534"
                elif risk_score >= 40:
                    score_color = "#92400e"
                else:
                    score_color = "#991b1b"
                score_html = f'<span style="float:right;color:{score_color};font-weight:700">Safety: {risk_score}/100</span>'
            risk_html = f"""
<div class="risk-block">
  <div class="risk-label">Top Risk {score_html}</div>
  <div class="risk-text">{_esc(top_risk[:300])}</div>
</div>"""

        return f"""
<div class="section">
  <div class="section-title">Actions &amp; Risks</div>
  {actions_html}
  {risk_html}
</div>"""

    def _html_signal_intelligence(self) -> str:
        has_reddit = bool(self.reddit_signals)
        has_substack = bool(self.substack_signals)
        has_youtube = bool(self.youtube_signals)
        has_articles = bool(self.top_articles)
        if not any([has_reddit, has_substack, has_youtube, has_articles]):
            return ""

        blocks: list[str] = []

        # Top headlines
        if has_articles:
            items = []
            for a in self.top_articles[:5]:
                title = _esc(a.get("title", ""))
                source = _esc(a.get("source", ""))
                tickers = a.get("related_tickers") or a.get("affected_tickers", [])
                sentiment = a.get("sentiment", 0)
                urgency = a.get("urgency", "")
                ticker_html = ""
                if tickers:
                    pills = " ".join(
                        f'<span style="background:#e0e7ff;color:#3730a3;padding:2px 6px;border-radius:4px;font-size:0.78em;font-weight:600">{_esc(t)}</span>'
                        for t in tickers[:3]
                    )
                    ticker_html = f'<span style="margin-left:6px">{pills}</span>'
                urgency_dot = ""
                if urgency == "high":
                    urgency_dot = '<span style="color:#dc2626;margin-right:4px" title="High urgency">&#9679;</span>'
                sent_color = _color(sentiment)
                url = a.get("url", "")
                title_html = f'<a href="{url}" style="color:#1e293b;text-decoration:none;border-bottom:1px solid #cbd5e1">{title}</a>' if url else f'<span style="color:#1e293b">{title}</span>'
                items.append(f"""
<div style="padding:7px 0;border-bottom:1px solid #f1f5f9;font-size:0.92em">
  {urgency_dot}{title_html}{ticker_html}
  <span style="color:#94a3b8;font-size:0.88em;margin-left:6px">{source}</span>
</div>""")
            blocks.append(f"""
<div style="margin-bottom:16px">
  <div style="font-size:0.78em;text-transform:uppercase;letter-spacing:1px;color:#94a3b8;font-weight:600;margin-bottom:8px">Top Headlines</div>
  {"".join(items)}
</div>""")

        # Reddit signals
        if has_reddit:
            items = []
            for s in self.reddit_signals[:5]:
                ticker = _esc(s.get("ticker", ""))
                sentiment = s.get("sentiment", s.get("sentiment_score", 0))
                mentions = s.get("mentions", s.get("mention_count", ""))
                subs = s.get("subreddits", s.get("subreddit", ""))
                if isinstance(subs, list):
                    subs = ", ".join(subs[:2])
                # Sentiment bar
                try:
                    sent_val = float(sentiment)
                except (ValueError, TypeError):
                    sent_val = 0
                sent_color = _color(sent_val)
                sent_str = f"{sent_val:+.1f}" if isinstance(sent_val, float) else str(sentiment)
                # Build Reddit search URL from first subreddit
                first_sub = subs.split(",")[0].strip() if isinstance(subs, str) else (subs[0] if isinstance(subs, list) and subs else "")
                reddit_url = f"https://reddit.com/r/{first_sub}/search?q={ticker}&sort=top&t=day" if first_sub and ticker else ""
                ticker_link = f'<a href="{reddit_url}" style="font-weight:700;color:#0f172a;text-decoration:none;border-bottom:1px solid #cbd5e1;min-width:44px">{ticker}</a>' if reddit_url else f'<span style="font-weight:700;color:#0f172a;min-width:44px">{ticker}</span>'
                items.append(f"""
<div style="display:flex;align-items:baseline;gap:10px;padding:6px 0;border-bottom:1px solid #f1f5f9;font-size:0.92em">
  {ticker_link}
  <span style="color:{sent_color};font-weight:600;min-width:36px">{sent_str}</span>
  <span style="color:#64748b">{mentions} mentions</span>
  <span style="color:#94a3b8;font-size:0.88em">r/{_esc(str(subs))}</span>
</div>""")
            blocks.append(f"""
<div style="margin-bottom:16px">
  <div style="font-size:0.78em;text-transform:uppercase;letter-spacing:1px;color:#f97316;font-weight:600;margin-bottom:8px">&#128172; Reddit</div>
  {"".join(items)}
</div>""")

        # Substack newsletters
        if has_substack:
            items = []
            for s in self.substack_signals[:4]:
                title = _esc(s.get("title", ""))
                summary = _esc(s.get("summary", "")[:120])
                url = s.get("url", "")
                tickers = s.get("tickers", s.get("affected_tickers", []))
                ticker_html = ""
                if tickers:
                    pills = " ".join(
                        f'<span style="background:#fce7f3;color:#9d174d;padding:2px 6px;border-radius:4px;font-size:0.78em;font-weight:600">{_esc(t)}</span>'
                        for t in tickers[:3]
                    )
                    ticker_html = f'<div style="margin-top:2px">{pills}</div>'
                summary_html = f'<div style="color:#64748b;font-size:0.88em;margin-top:3px">{summary}</div>' if summary else ""
                title_html = f'<a href="{url}" style="color:#1e293b;font-weight:500;text-decoration:none;border-bottom:1px solid #cbd5e1">{title}</a>' if url else f'<span style="color:#1e293b;font-weight:500">{title}</span>'
                items.append(f"""
<div style="padding:7px 0;border-bottom:1px solid #f1f5f9;font-size:0.92em">
  <div>{title_html}</div>
  {summary_html}
  {ticker_html}
</div>""")
            blocks.append(f"""
<div style="margin-bottom:16px">
  <div style="font-size:0.78em;text-transform:uppercase;letter-spacing:1px;color:#8b5cf6;font-weight:600;margin-bottom:8px">&#128220; Substack</div>
  {"".join(items)}
</div>""")

        # YouTube
        if has_youtube:
            items = []
            for y in self.youtube_signals[:3]:
                title = _esc(y.get("title", ""))
                channel = _esc(y.get("channel", y.get("author", "")))
                url = y.get("url", "")
                views = y.get("views", y.get("score", 0))
                tickers = y.get("tickers", y.get("affected_tickers", []))
                view_str = ""
                if views:
                    if views >= 1_000_000:
                        view_str = f"{views / 1_000_000:.1f}M views"
                    elif views >= 1_000:
                        view_str = f"{views / 1_000:.0f}K views"
                    else:
                        view_str = f"{views} views"
                ticker_html = ""
                if tickers:
                    ticker_html = f' <span style="color:#94a3b8;font-size:0.85em">[{", ".join(tickers[:3])}]</span>'
                title_html = f'<a href="{url}" style="color:#1e293b;text-decoration:none;border-bottom:1px solid #cbd5e1">{title}</a>' if url else f'<span style="color:#1e293b">{title}</span>'
                items.append(f"""
<div style="padding:6px 0;border-bottom:1px solid #f1f5f9;font-size:0.92em">
  {title_html}{ticker_html}
  <div style="color:#94a3b8;font-size:0.88em">{channel}{(' · ' + view_str) if view_str else ''}</div>
</div>""")
            blocks.append(f"""
<div style="margin-bottom:16px">
  <div style="font-size:0.78em;text-transform:uppercase;letter-spacing:1px;color:#dc2626;font-weight:600;margin-bottom:8px">&#9654; YouTube</div>
  {"".join(items)}
</div>""")

        return f"""
<div class="section">
  <div class="section-title">Signal Intelligence</div>
  {"".join(blocks)}
</div>"""

    def _html_prediction_markets(self) -> str:
        if not self.prediction_shifts:
            return ""

        items = []
        for pm in self.prediction_shifts[:5]:
            title = _esc(pm.get("title", pm.get("market_title", "")))
            prob = pm.get("probability", 0)
            delta = pm.get("delta", pm.get("delta_pct", 0))
            # Normalize: if delta is a fraction (0.15), convert to pp
            if isinstance(delta, float) and -1 < delta < 1 and delta != 0:
                delta = delta * 100
            prob_display = prob * 100 if isinstance(prob, float) and prob < 1 else prob
            direction_color = "#16a34a" if delta > 0 else "#dc2626"
            affected = pm.get("affected_tickers", [])
            ticker_html = ""
            if affected:
                ticker_html = f'<span style="color:#94a3b8;font-size:0.8em;margin-left:6px">[{", ".join(affected[:3])}]</span>'

            # Probability bar
            bar_width = max(5, min(100, int(prob_display)))
            items.append(f"""
<div style="padding:8px 0;border-bottom:1px solid #f1f5f9">
  <div style="display:flex;justify-content:space-between;align-items:baseline;font-size:0.85em;margin-bottom:4px">
    <span style="color:#1e293b;flex:1">{title}{ticker_html}</span>
    <span style="font-weight:700;color:#0f172a;margin-left:8px">{prob_display:.0f}%</span>
    <span style="font-weight:600;color:{direction_color};margin-left:6px;min-width:48px;text-align:right">{delta:+.0f}pp</span>
  </div>
  <div style="background:#e2e8f0;border-radius:4px;height:4px;overflow:hidden">
    <div style="background:{direction_color};height:100%;width:{bar_width}%;border-radius:4px"></div>
  </div>
</div>""")

        return f"""
<div class="section">
  <div class="section-title">Prediction Markets</div>
  {"".join(items)}
</div>"""

    def _html_smart_money(self) -> str:
        if not self.superinvestor_data:
            return ""

        items = []
        for ticker, data in self.superinvestor_data.items():
            if not isinstance(data, dict):
                continue
            insider = data.get("insider_net_buying")
            supers = data.get("superinvestors_holding", [])
            activity = data.get("superinvestor_activity", [])
            count = data.get("superinvestor_count", len(supers))

            if not insider and not supers and not activity:
                continue

            badges = []
            if insider:
                badges.append('<span style="background:#dcfce7;color:#166534;padding:3px 8px;border-radius:8px;font-size:0.78em;font-weight:600">INSIDER BUYING</span>')
            if count and count > 0:
                badges.append(f'<span style="background:#e0e7ff;color:#3730a3;padding:3px 8px;border-radius:8px;font-size:0.78em;font-weight:600">{count} SUPER</span>')

            detail_parts = []
            if supers:
                detail_parts.append(f"Held by: {', '.join(str(s) for s in supers[:4])}")
            if activity:
                recent = activity[0]
                inv = recent.get("investor", "")
                act = recent.get("action", "")
                val = recent.get("value_usd")
                val_str = f" (${val / 1_000_000:.1f}M)" if val and val > 0 else ""
                if inv:
                    detail_parts.append(f"{inv} {act}{val_str}")

            badges_html = " ".join(badges)
            detail_html = f'<div style="color:#64748b;font-size:0.8em;margin-top:2px">{" · ".join(detail_parts)}</div>' if detail_parts else ""

            items.append(f"""
<div style="display:flex;align-items:baseline;gap:8px;padding:7px 0;border-bottom:1px solid #f1f5f9;font-size:0.85em">
  <span style="font-weight:700;color:#0f172a;min-width:44px">{_esc(ticker)}</span>
  <div style="flex:1">
    <div>{badges_html}</div>
    {detail_html}
  </div>
</div>""")

        if not items:
            return ""

        return f"""
<div class="section">
  <div class="section-title">Smart Money</div>
  {"".join(items)}
</div>"""

    @staticmethod
    def _parse_evidence_label(raw: str) -> str:
        """Extract a short human label from PASS/FAIL evidence strings.

        Input:  'PASS Crowd: Reddit sentiment +0.33'
        Output: 'Crowd'
        Input:  'FAIL Valuation: FAIL: CAGR 16.1% < 25.0% minimum'
        Output: 'Valuation'
        """
        text = str(raw)
        # Strip leading PASS/FAIL
        for prefix in ("PASS ", "FAIL "):
            if text.startswith(prefix):
                text = text[len(prefix):]
                break
        # Take text before first colon as the category
        if ":" in text:
            return text.split(":")[0].strip()
        return text[:20].strip()

    def _html_watchlist(self) -> str:
        conviction = self.conviction_result.get("current_list", [])
        moonshots = self.moonshot_result.get("current_list", [])
        if not conviction and not moonshots:
            return ""

        all_cards: list[str] = []

        for c in conviction:
            ticker = c.get("ticker", "?")
            conv = c.get("conviction", "medium")
            thesis = _esc(c.get("thesis", ""))
            weeks = c.get("weeks_on_list", 1)
            source = _esc(c.get("source", ""))
            pros = c.get("pros", [])
            cons = c.get("cons", [])

            # Build compact evidence scorecard (✓ Category / ✗ Category)
            evidence_html = ""
            if pros or cons:
                items = []
                for p in (pros if isinstance(pros, list) else []):
                    label = self._parse_evidence_label(p)
                    items.append(
                        f'<span style="color:#16a34a;font-size:0.82em;margin-right:10px">'
                        f'&#10003; {_esc(label)}</span>'
                    )
                for co in (cons if isinstance(cons, list) else []):
                    label = self._parse_evidence_label(co)
                    items.append(
                        f'<span style="color:#94a3b8;font-size:0.82em;margin-right:10px">'
                        f'&#10007; {_esc(label)}</span>'
                    )
                evidence_html = (
                    f'<div style="margin-top:8px;padding:8px 12px;background:#f1f5f9;'
                    f'border-radius:6px;display:flex;flex-wrap:wrap;gap:2px">'
                    f'{"".join(items)}</div>'
                )

            # Cross-reference intel
            intel_html = self._build_intel_html(ticker)

            # Source line
            source_html = f'<div style="font-size:0.82em;color:#94a3b8;margin-top:6px">Source: {source}</div>' if source else ""

            all_cards.append(f"""
<div style="background:#f8fafc;border-radius:8px;padding:18px 20px;margin-bottom:12px;border-left:4px solid #2563eb">
  <div style="display:flex;align-items:baseline;gap:10px;margin-bottom:6px">
    <span style="font-weight:700;font-size:1.05em;color:#0f172a">{_esc(ticker)}</span>
    {_conviction_pill(conv)}
    <span style="font-size:0.82em;color:#94a3b8">Week {weeks}</span>
  </div>
  <div style="font-size:0.95em;color:#334155;line-height:1.55;margin-bottom:4px">{thesis}</div>
  {source_html}
  {evidence_html}
  {intel_html}
</div>""")

        for m in moonshots:
            ticker = m.get("ticker", "?")
            thesis = _esc(m.get("thesis", ""))
            upside = _esc(m.get("upside_case", ""))
            downside = _esc(m.get("downside_case", ""))
            milestone = _esc(m.get("key_milestone", ""))

            # Upside/downside as two clean rows
            scenarios_html = ""
            rows = []
            if upside:
                rows.append(
                    f'<div style="padding:4px 0">'
                    f'<span style="color:#16a34a;font-weight:600">&#9650; Bull:</span> '
                    f'<span style="color:#334155">{upside}</span></div>'
                )
            if downside:
                rows.append(
                    f'<div style="padding:4px 0">'
                    f'<span style="color:#dc2626;font-weight:600">&#9660; Bear:</span> '
                    f'<span style="color:#334155">{downside}</span></div>'
                )
            if rows:
                scenarios_html = (
                    f'<div style="font-size:0.9em;margin-top:8px;padding:10px 14px;'
                    f'background:rgba(255,255,255,0.6);border-radius:6px;'
                    f'border:1px solid #e9e5f5">{"".join(rows)}</div>'
                )

            milestone_html = (
                f'<div style="font-size:0.85em;color:#64748b;margin-top:8px">'
                f'<span style="font-weight:600;color:#5b21b6">Key milestone:</span> {milestone}</div>'
            ) if milestone else ""

            # Cross-reference intel
            intel_html = self._build_intel_html(ticker)

            all_cards.append(f"""
<div style="background:#faf5ff;border-radius:8px;padding:18px 20px;margin-bottom:12px;border-left:4px solid #7c3aed">
  <div style="display:flex;align-items:baseline;gap:10px;margin-bottom:6px">
    <span style="font-weight:700;font-size:1.05em;color:#0f172a">{_esc(ticker)}</span>
    <span style="background:#ede9fe;color:#5b21b6;padding:3px 8px;border-radius:8px;font-size:0.75em;font-weight:600">MOONSHOT</span>
  </div>
  <div style="font-size:0.95em;color:#334155;line-height:1.55;margin-bottom:4px">{thesis}</div>
  {scenarios_html}
  {milestone_html}
  {intel_html}
</div>""")

        return f"""
<div class="section">
  <div class="section-title">Watchlist</div>
  {"".join(all_cards)}
</div>"""

    def _html_novel_ideas(self) -> str:
        if not self.novel_ideas:
            return ""

        cards = []
        for idea in self.novel_ideas:
            ticker = idea.get("ticker")
            theme = _esc(idea.get("theme", ""))
            thesis = _esc(idea.get("thesis", ""))
            source = _esc(idea.get("source_signals", ""))

            ticker_html = f'<span style="font-weight:700;font-size:1.05em;color:#0f172a">{_esc(ticker)}</span>' if ticker else ""
            source_html = f'<div style="font-size:0.82em;color:#94a3b8;margin-top:6px"><em>Signals: {source}</em></div>' if source else ""

            cards.append(f"""
<div style="background:#fffbeb;border-radius:8px;padding:18px 20px;margin-bottom:12px;border-left:4px solid #f59e0b">
  <div style="display:flex;align-items:baseline;gap:10px;margin-bottom:6px">
    {ticker_html}
    <span style="background:#fef3c7;color:#92400e;padding:3px 8px;border-radius:8px;font-size:0.75em;font-weight:600">NEW IDEA</span>
    <span style="font-size:0.9em;color:#92400e;font-weight:600">{theme}</span>
  </div>
  <div style="font-size:0.95em;color:#334155;line-height:1.55">{thesis}</div>
  {source_html}
</div>""")

        return f"""
<div class="section">
  <div class="section-title">Novel Ideas</div>
  {"".join(cards)}
</div>"""

    def _html_sector_scanner(self) -> str:
        if not self.sector_scanner_signals:
            return ""
        direction_colors = {
            "bullish": ("#dcfce7", "#166534", "🟢"),
            "bearish": ("#fee2e2", "#991b1b", "🔴"),
            "mixed": ("#fef9c3", "#854d0e", "🟡"),
            "neutral": ("#f1f5f9", "#475569", "⚪"),
        }
        sectors: dict[str, list[dict]] = {}
        for sig in self.sector_scanner_signals:
            sector = sig.get("sector", "unknown")
            sectors.setdefault(sector, []).append(sig)

        cards = []
        for sector, sigs in sorted(sectors.items()):
            label = _esc(sector.replace("_", " ").title())
            momentum = [s for s in sigs if s.get("type") == "sector_momentum"]
            catalysts = [s for s in sigs if s.get("type") == "sector_catalyst"]

            direction = momentum[0].get("direction", "neutral") if momentum else "neutral"
            bg, color, emoji = direction_colors.get(direction, direction_colors["neutral"])
            article_count = momentum[0].get("article_count", 0) if momentum else len(catalysts)
            tickers = list(dict.fromkeys(t for s in sigs for t in s.get("tickers", [])[:5]))

            catalyst_html = ""
            for c in catalysts[:2]:
                summary = _esc(c.get("summary", c.get("title", "")))
                cat_type = _esc(c.get("catalyst_type", ""))
                tag = f'<span style="background:#e2e8f0;color:#475569;padding:1px 6px;border-radius:4px;font-size:0.75em">{cat_type}</span>' if cat_type and cat_type != "other" else ""
                catalyst_html += f'<div style="font-size:0.9em;color:#334155;margin-top:4px">• {summary} {tag}</div>'

            ticker_html = f'<div style="font-size:0.82em;color:#94a3b8;margin-top:6px">{", ".join(_esc(t) for t in tickers[:6])}</div>' if tickers else ""

            cards.append(f"""
<div style="background:{bg};border-radius:8px;padding:16px 18px;margin-bottom:10px;border-left:4px solid {color}">
  <div style="display:flex;align-items:baseline;gap:8px;margin-bottom:4px">
    <span>{emoji}</span>
    <span style="font-weight:700;font-size:1em;color:#0f172a">{label}</span>
    <span style="font-size:0.82em;color:{color}">{article_count} articles</span>
  </div>
  {catalyst_html}
  {ticker_html}
</div>""")

        return f"""
<div class="section">
  <div class="section-title">Sector Scanner</div>
  {"".join(cards)}
</div>"""

    def _build_intel_html(self, ticker: str) -> str:
        """Build cross-referenced intelligence HTML for a ticker."""
        intel_items: list[str] = []

        # Reddit signal
        for s in self.reddit_signals:
            if s.get("ticker", "").upper() == ticker.upper():
                sent = s.get("sentiment", s.get("sentiment_score", 0))
                mentions = s.get("mentions", s.get("mention_count", ""))
                sub = s.get("subreddit", "")
                try:
                    sent_val = float(sent)
                    sent_color = _color(sent_val)
                    sent_str = f"{sent_val:+.1f}"
                except (ValueError, TypeError):
                    sent_color = "#64748b"
                    sent_str = str(sent)
                first_sub = str(sub).split(",")[0].strip() if sub else ""
                reddit_url = f"https://reddit.com/r/{first_sub}/search?q={ticker}&sort=top&t=day" if first_sub else ""
                sub_html = f' <a href="{reddit_url}" style="color:#94a3b8;text-decoration:none;border-bottom:1px solid #e2e8f0">r/{_esc(str(sub))}</a>' if reddit_url else (f' <span style="color:#94a3b8">r/{_esc(str(sub))}</span>' if sub else "")
                intel_items.append(
                    f'<span style="color:#f97316">&#128172;</span> '
                    f'<span style="color:{sent_color};font-weight:600">{sent_str}</span> '
                    f'sentiment, {mentions} mentions'
                    + sub_html
                )
                break

        # Substack signal
        for s in self.substack_signals:
            tickers = [t.upper() for t in s.get("tickers", s.get("affected_tickers", []))]
            if ticker.upper() in tickers:
                title = _esc(s.get("title", ""))
                summary = _esc(s.get("summary", "")[:80])
                url = s.get("url", "")
                title_link = f'<a href="{url}" style="color:inherit;text-decoration:none;border-bottom:1px solid #cbd5e1">{title}</a>' if url else title
                line = f'<span style="color:#8b5cf6">&#128220;</span> {title_link}'
                if summary:
                    line += f' <span style="color:#94a3b8">— {summary}</span>'
                intel_items.append(line)
                break

        # YouTube signal
        for y in self.youtube_signals:
            ytickers = [t.upper() for t in y.get("tickers", y.get("affected_tickers", []))]
            if ticker.upper() in ytickers:
                title = _esc(y.get("title", ""))
                channel = _esc(y.get("channel", y.get("author", "")))
                url = y.get("url", "")
                title_link = f'<a href="{url}" style="color:inherit;text-decoration:none;border-bottom:1px solid #cbd5e1">{title}</a>' if url else title
                intel_items.append(f'<span style="color:#dc2626">&#9654;</span> {title_link} <span style="color:#94a3b8">— {channel}</span>')
                break

        # Smart money
        si = self.superinvestor_data.get(ticker, {})
        if isinstance(si, dict):
            supers = si.get("superinvestors_holding", [])
            insider = si.get("insider_net_buying")
            activity = si.get("superinvestor_activity", [])
            parts = []
            if insider:
                parts.append('<span style="color:#16a34a;font-weight:600">insider buying</span>')
            if supers:
                parts.append(f'held by {", ".join(_esc(str(s)) for s in supers[:3])}')
            if activity:
                recent = activity[0]
                inv = _esc(recent.get("investor", ""))
                act = recent.get("action", "")
                val = recent.get("value_usd")
                val_str = f" (${val / 1_000_000:.1f}M)" if val and val > 0 else ""
                if inv:
                    parts.append(f"{inv} {act}{val_str}")
            if parts:
                intel_items.append(f'<span style="color:#2563eb">&#128176;</span> {", ".join(parts)}')

        # Fundamentals
        fund = self.fundamentals.get(ticker, {})
        if fund:
            f_parts = []
            pe = fund.get("pe_forward")
            rev = fund.get("revenue_growth")
            margin = fund.get("net_margin")
            gross = fund.get("gross_margin")
            if pe is not None:
                f_parts.append(f"P/E(f) {pe:.1f}")
            if rev is not None:
                f_parts.append(f"Rev +{rev:.0%}")
            if margin is not None:
                f_parts.append(f"Net {margin:.0%}")
            elif gross is not None:
                f_parts.append(f"Gross {gross:.0%}")
            if f_parts:
                intel_items.append(f'<span style="color:#64748b">&#128202;</span> {" · ".join(f_parts)}')

        if not intel_items:
            return ""

        rows = "\n".join(f'<div style="padding:3px 0">{item}</div>' for item in intel_items)
        return f"""
<div style="margin-top:10px;padding:10px 14px;background:rgba(255,255,255,0.7);border-radius:6px;font-size:0.88em;color:#475569;border:1px solid #e2e8f0">
  {rows}
</div>"""

    def _html_deep_research(self) -> str:
        """Render deep research blocks as two-tier HTML cards."""
        if not self._deep_research_blocks:
            return ""

        full_cards = []
        summary_cards = []

        for ticker, block_data in self._deep_research_blocks.items():
            content = block_data.get("content", "") if isinstance(block_data, dict) else str(block_data)
            tier = block_data.get("tier", "full") if isinstance(block_data, dict) else "full"
            if not content:
                continue

            if tier == "summary":
                summary_cards.append(self._render_summary_card_html(ticker, content))
            else:
                full_cards.append(self._render_research_block_html(ticker, content))

        parts = []
        if full_cards:
            parts.append(f"""
<div class="section" style="padding:20px 24px">
  <div class="section-title">Deep Research</div>
  {"".join(full_cards)}
</div>""")

        if summary_cards:
            parts.append(f"""
<div class="section" style="padding:20px 24px">
  <div class="section-title">Quick Takes</div>
  <div style="display:grid;gap:8px">{"".join(summary_cards)}</div>
</div>""")

        return "\n".join(parts) if parts else ""

    def _render_summary_card_html(self, ticker: str, content: str) -> str:
        """Render a compact summary card for a ticker."""
        report_map = {r.get("ticker"): r for r in self.holdings_reports}
        report = report_map.get(ticker, {})
        chg = report.get("change_pct")
        price = report.get("price")
        pct = report.get("position_pct")

        chg_html = ""
        if chg is not None:
            chg_color = _color(chg)
            chg_html = f'<span style="color:{chg_color};font-weight:700;font-size:0.9em;margin-left:6px">{chg:+.1f}%</span>'

        price_html = f'<span style="color:#64748b;font-size:0.85em;margin-left:6px">${price}</span>' if price else ""
        pct_html = f'<span style="color:#94a3b8;font-size:0.75em;margin-left:6px">{pct:.1f}%</span>' if pct is not None else ""

        # Extract stance from content if present
        stance = ""
        stance_match = re.search(r'Stance:\s*(Add|Hold|Trim|Avoid|Watch)', content, re.IGNORECASE)
        if stance_match:
            stance = stance_match.group(1).upper()
        stance_pill = self._stance_pill(stance) if stance else ""

        # Clean content for display — remove header lines and stance line
        content_clean = re.sub(r'##.*?\n', '', content).strip()
        content_clean = re.sub(r'Stance:\s*(Add|Hold|Trim|Avoid|Watch).*', '', content_clean, flags=re.IGNORECASE).strip()
        # Convert markdown bold/italic
        content_clean = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', content_clean)
        content_clean = re.sub(r'\*(.+?)\*', r'<em>\1</em>', content_clean)
        # Truncate if too long
        if len(content_clean) > 400:
            content_clean = content_clean[:400].rsplit(' ', 1)[0] + '…'

        return f"""
<div style="background:#f8fafc;border-radius:8px;padding:12px 16px;border-left:3px solid #e2e8f0">
  <div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:6px">
    <div>
      <span style="font-weight:700;font-size:0.95em">{_esc(ticker)}</span>{price_html}{chg_html}{pct_html}
    </div>
    {stance_pill}
  </div>
  <div style="font-size:0.85em;color:#334155;line-height:1.5">{content_clean}</div>
</div>"""

    @staticmethod
    def _stance_pill(stance: str) -> str:
        """Render a colored pill for an action stance."""
        colors = {
            "ADD": ("#dcfce7", "#166534"),
            "HOLD": ("#dbeafe", "#1e40af"),
            "TRIM": ("#fed7aa", "#9a3412"),
            "AVOID": ("#fecaca", "#991b1b"),
            "WATCH": ("#fef3c7", "#92400e"),
        }
        bg, fg = colors.get(stance.upper(), ("#e2e8f0", "#475569"))
        return f'<span style="background:{bg};color:{fg};padding:3px 9px;border-radius:12px;font-size:0.8em;font-weight:600">{_esc(stance)}</span>'

    def _render_research_block_html(self, ticker: str, block_text: str) -> str:
        """Render a full deep research block as an HTML card.

        Detects format: if >= 3 subsection headers (### ), renders with sectioned boxes.
        Otherwise renders as flowing prose.
        """
        header_count = len(re.findall(r'^###\s', block_text, re.MULTILINE))

        if header_count >= 3:
            body_html = self._render_sectioned_body(block_text)
        else:
            body_html = self._render_prose_body(block_text)

        # Get position info for card header
        report_map = {r.get("ticker"): r for r in self.holdings_reports}
        report = report_map.get(ticker, {})
        chg = report.get("change_pct")
        price = report.get("price")
        pct = report.get("position_pct")
        meta_parts = []
        if price is not None:
            meta_parts.append(f"${price}")
        if chg is not None:
            meta_parts.append(f"{chg:+.1f}%")
        if pct is not None:
            meta_parts.append(f"{pct:.1f}% of portfolio")
        meta_str = " · ".join(meta_parts)

        return f"""
<div style="margin-bottom:20px;border:1px solid #e2e8f0;border-radius:10px;overflow:hidden">
  <div style="background:linear-gradient(135deg,#0f172a,#1e3a5f);padding:14px 18px;color:#fff">
    <span style="font-weight:700;font-size:1.1em">{_esc(ticker)}</span>
    <span style="color:#94a3b8;font-size:0.85em;margin-left:10px">{_esc(meta_str)}</span>
  </div>
  <div style="padding:14px 18px">
    {body_html}
  </div>
</div>"""

    def _render_sectioned_body(self, block_text: str) -> str:
        """Render research block body as bordered subsection boxes (old 10-section format)."""
        subsections: list[tuple[str, str]] = []
        current_title = ""
        current_lines: list[str] = []

        for line in block_text.strip().splitlines():
            stripped = line.strip()
            if stripped.startswith("### "):
                if current_title or current_lines:
                    subsections.append((current_title, "\n".join(current_lines).strip()))
                current_title = stripped[4:].strip()
                current_title = re.sub(r'^\d+\.\s*', '', current_title)
                current_lines = []
            else:
                current_lines.append(line)
        if current_title or current_lines:
            subsections.append((current_title, "\n".join(current_lines).strip()))

        sections_html_parts = []
        for title, content in subsections:
            if not content.strip():
                continue
            content_html = self._md_to_html(content)
            title_html = _esc(title) if title else ""

            border_color = "#e2e8f0"
            title_lower = title.lower()
            if "thesis scorecard" in title_lower or "what we could be wrong" in title_lower:
                border_color = "#2563eb"
            elif "actionability" in title_lower or "action" in title_lower and "catalyst" in title_lower:
                border_color = "#16a34a"
            elif "bull" in title_lower and "bear" in title_lower:
                border_color = "#7c3aed"
            elif "key question" in title_lower:
                border_color = "#0ea5e9"

            sections_html_parts.append(f"""
<div style="margin-bottom:14px;padding:12px 16px;background:#f8fafc;border-radius:6px;border-left:3px solid {border_color}">
  <div style="font-size:0.82em;text-transform:uppercase;letter-spacing:0.5px;color:#64748b;font-weight:600;margin-bottom:8px">{title_html}</div>
  <div style="font-size:0.95em;color:#334155;line-height:1.6">{content_html}</div>
</div>""")

        return "".join(sections_html_parts)

    def _render_prose_body(self, block_text: str) -> str:
        """Render research block body as flowing prose paragraphs (new format)."""
        # Split on ### headers but render as light section dividers, not boxes
        parts = []
        current_title = ""
        current_lines: list[str] = []

        for line in block_text.strip().splitlines():
            stripped = line.strip()
            if stripped.startswith("### "):
                if current_lines:
                    content = "\n".join(current_lines).strip()
                    if content:
                        content_html = self._md_to_html(content)
                        if current_title:
                            parts.append(f"""
<div style="margin-bottom:16px">
  <div style="font-size:0.85em;font-weight:700;color:#0f172a;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:8px;padding-bottom:5px;border-bottom:1px solid #e2e8f0">{_esc(current_title)}</div>
  <div style="font-size:0.95em;color:#334155;line-height:1.65">{content_html}</div>
</div>""")
                        else:
                            parts.append(f'<div style="font-size:0.95em;color:#334155;line-height:1.65;margin-bottom:16px">{content_html}</div>')
                current_title = stripped[4:].strip()
                current_title = re.sub(r'^\d+\.\s*', '', current_title)
                current_lines = []
            else:
                current_lines.append(line)

        if current_lines:
            content = "\n".join(current_lines).strip()
            if content:
                content_html = self._md_to_html(content)
                if current_title:
                    parts.append(f"""
<div style="margin-bottom:16px">
  <div style="font-size:0.85em;font-weight:700;color:#0f172a;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:8px;padding-bottom:5px;border-bottom:1px solid #e2e8f0">{_esc(current_title)}</div>
  <div style="font-size:0.95em;color:#334155;line-height:1.65">{content_html}</div>
</div>""")
                else:
                    parts.append(f'<div style="font-size:0.95em;color:#334155;line-height:1.65;margin-bottom:16px">{content_html}</div>')

        return "".join(parts) if parts else self._md_to_html(block_text)

    def _md_to_html(self, text: str) -> str:
        """Convert simple markdown to HTML for research blocks."""
        # Bold
        text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
        text = re.sub(r'__(.+?)__', r'<strong>\1</strong>', text)
        # Italic
        text = re.sub(r'\*(.+?)\*', r'<em>\1</em>', text)

        lines = text.strip().splitlines()
        html_lines = []
        in_table = False
        for line in lines:
            stripped = line.strip()
            # Detect markdown table rows (pipes)
            if stripped.startswith("|") and stripped.endswith("|"):
                cells = [c.strip() for c in stripped.strip("|").split("|")]
                # Skip separator rows like |---|---|
                if all(re.match(r'^[-:]+$', c) for c in cells):
                    continue
                if not in_table:
                    in_table = True
                    html_lines.append('<table style="width:100%;border-collapse:collapse;font-size:0.88em;margin:8px 0">')
                    # First row is header
                    html_lines.append("<tr>" + "".join(
                        f'<th style="text-align:left;padding:8px 10px;border-bottom:2px solid #e2e8f0;color:#1e293b;font-weight:600">{c}</th>'
                        for c in cells
                    ) + "</tr>")
                else:
                    html_lines.append("<tr>" + "".join(
                        f'<td style="padding:8px 10px;border-bottom:1px solid #f1f5f9;color:#334155;vertical-align:top">{c}</td>'
                        for c in cells
                    ) + "</tr>")
            else:
                if in_table:
                    html_lines.append("</table>")
                    in_table = False
                if not stripped:
                    html_lines.append("<br>")
                elif stripped.startswith("- "):
                    html_lines.append(f'<div style="padding:3px 0 3px 16px">• {stripped[2:]}</div>')
                else:
                    html_lines.append(f"<div style='margin-bottom:4px'>{stripped}</div>")
        if in_table:
            html_lines.append("</table>")
        return "\n".join(html_lines)

    def _html_upcoming(self) -> str:
        catalysts = self.catalyst_data.get("catalysts", [])
        if not catalysts:
            return ""

        upcoming = [c for c in catalysts if self._days_away(c) <= 7]
        if not upcoming:
            return ""

        items = []
        for c in upcoming[:8]:
            dt = _esc(self._cat_date(c))
            desc = _esc(self._cat_desc(c))
            days = self._days_away(c)
            impact = self._cat_field(c, "impact_estimate", "medium")

            if days == 0:
                day_label = '<span style="color:#dc2626;font-weight:600">TODAY</span>'
            elif days == 1:
                day_label = '<span style="color:#d97706;font-weight:600">TOMORROW</span>'
            else:
                day_label = f'<span class="event-days">in {days}d</span>'

            items.append(f"""
<div class="event-item">
  <span class="event-date">{dt}</span>
  <span style="flex:1">{desc}</span>
  {day_label}
</div>""")

        items_html = "\n".join(items)

        return f"""
<div class="section">
  <div class="section-title">Next 7 Days</div>
  {items_html}
</div>"""

    def _html_footer(self) -> str:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M")

        # Inline sources
        sources = ["yfinance", "FRED"]
        if self.top_articles:
            srcs = {a.get("source", "") for a in self.top_articles[:5] if a.get("source")}
            sources.extend(sorted(srcs)[:3])
        if self.reddit_mood:
            sources.append("Reddit")
        if self.superinvestor_data:
            sources.append("SEC 13F")
        sources.append("Gemini")
        sources_str = " · ".join(sources)
        citations_html = self.committee_result.get("citations_html", "")

        return f"""
<div class="footer">
  AlphaDesk v2.0 · ${self.daily_cost:.2f} · {self.total_time:.0f}s · {ts}<br>
  {sources_str}
  {citations_html}
</div>"""

    # ── catalyst helpers ─────────────────────────────────────────

    def _days_away(self, c) -> int:
        if isinstance(c, dict):
            return c.get("days_away", 999)
        return getattr(c, "days_away", 999)

    def _cat_date(self, c) -> str:
        if isinstance(c, dict):
            return str(c.get("date", "TBD"))
        return str(getattr(c, "date", "TBD"))

    def _cat_desc(self, c) -> str:
        if isinstance(c, dict):
            return c.get("description", "")
        return getattr(c, "description", "")

    def _cat_field(self, c, field: str, default: str = "") -> str:
        if isinstance(c, dict):
            return c.get(field, default)
        return getattr(c, field, default)


# ═══════════════════════════════════════════════════════════════
# SAVE TO DISK (same interface as before)
# ═══════════════════════════════════════════════════════════════

def save_verbose_report(markdown: str, html: str, report_dir: str | None = None) -> dict[str, str]:
    """Save the verbose report to disk.

    Args:
        markdown: Markdown content.
        html: HTML content.
        report_dir: Override directory (default: reports/{date}/).

    Returns:
        Dict with paths: {"markdown": "...", "html": "..."}.
    """
    from pathlib import Path

    if report_dir:
        out_dir = Path(report_dir)
    else:
        out_dir = Path("reports") / date.today().isoformat()

    out_dir.mkdir(parents=True, exist_ok=True)

    md_path = out_dir / "full_report.md"
    html_path = out_dir / "full_report.html"

    md_path.write_text(markdown, encoding="utf-8")
    html_path.write_text(html, encoding="utf-8")

    log.info("Verbose report saved: %s and %s", md_path, html_path)
    return {"markdown": str(md_path), "html": str(html_path)}
