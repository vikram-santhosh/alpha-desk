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
    if s in ("strengthening", "intact"):
        return '<span style="background:#dcfce7;color:#166534;padding:2px 8px;border-radius:12px;font-size:0.75em;font-weight:600">INTACT</span>'
    if s in ("evolving", "monitoring"):
        return '<span style="background:#fef3c7;color:#92400e;padding:2px 8px;border-radius:12px;font-size:0.75em;font-weight:600">EVOLVING</span>'
    if s in ("weakening", "invalidated"):
        return '<span style="background:#fecaca;color:#991b1b;padding:2px 8px;border-radius:12px;font-size:0.75em;font-weight:600">WEAKENING</span>'
    return '<span style="background:#e2e8f0;color:#475569;padding:2px 8px;border-radius:12px;font-size:0.75em;font-weight:600">UNKNOWN</span>'


def _conviction_pill(conviction: str) -> str:
    c = conviction.lower()
    if c == "high":
        return '<span style="background:#dcfce7;color:#166534;padding:2px 6px;border-radius:8px;font-size:0.7em;font-weight:600">HIGH</span>'
    if c == "medium":
        return '<span style="background:#fef3c7;color:#92400e;padding:2px 6px;border-radius:8px;font-size:0.7em;font-weight:600">MED</span>'
    return '<span style="background:#e2e8f0;color:#475569;padding:2px 6px;border-radius:8px;font-size:0.7em;font-weight:600">LOW</span>'


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
        daily_cost: float = 0.0,
        total_time: float = 0.0,
    ):
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
            self._md_market_pulse(),
            self._md_portfolio(totals),
            self._md_actions_risks(),
            self._md_signal_intelligence(),
            self._md_prediction_markets(),
            self._md_smart_money(),
            self._md_watchlist(),
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
            self._html_market_pulse(),
            self._html_portfolio(totals),
            self._html_actions_risks(),
            self._html_signal_intelligence(),
            self._html_prediction_markets(),
            self._html_smart_money(),
            self._html_watchlist(),
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
        """Parse CIO brief into named sections."""
        brief = self.committee_result.get("formatted_brief", "")
        if not brief:
            return {}
        sections = {}
        current_key = ""
        current_lines: list[str] = []
        for line in brief.strip().splitlines():
            stripped = line.strip()
            # Detect section headers like "**SECTION 1 - WHAT CHANGED TODAY**"
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
        pnl = totals["daily_pnl"]
        sign = "+" if pnl >= 0 else ""
        lines = [
            f"Portfolio: {_dollar(totals['value'])}  |  Today: {sign}{_dollar(pnl)}  |  {totals['holdings_count']} holdings",
        ]
        headline = self._get_headline()
        if headline:
            lines.append(f"\n> {headline}")
        return "\n".join(lines) + "\n"

    def _md_what_changed(self) -> str:
        cio = self._get_cio_sections()
        text = cio.get("what changed today", "")
        if not text:
            brief = self.committee_result.get("formatted_brief", "")
            if brief:
                # Take first paragraph
                paras = brief.strip().split("\n\n")
                text = paras[0] if paras else ""
        if not text:
            return ""
        # Strip markdown formatting
        text = re.sub(r"\*{1,2}(.+?)\*{1,2}", r"\1", text)
        return f"WHAT CHANGED\n{'-' * 40}\n{text}\n"

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
                tickers = a.get("related_tickers") or a.get("affected_tickers", [])
                ticker_str = f" [{', '.join(tickers[:3])}]" if tickers else ""
                lines.append(f"  {title}{ticker_str} — {source}")

        if has_reddit:
            lines.append("\nReddit Threads:")
            for s in self.reddit_signals[:5]:
                ticker = s.get("ticker", "")
                sentiment = s.get("sentiment", "")
                mentions = s.get("mentions", "")
                subs = s.get("subreddits", s.get("subreddit", ""))
                lines.append(f"  {ticker}: sentiment {sentiment}, {mentions} mentions ({subs})")

        if has_substack:
            lines.append("\nSubstack Newsletters:")
            for s in self.substack_signals[:5]:
                title = s.get("title", "")
                tickers = s.get("tickers", [])
                ticker_str = f" [{', '.join(tickers[:3])}]" if tickers else ""
                lines.append(f"  {title}{ticker_str}")

        if has_youtube:
            lines.append("\nYouTube:")
            for y in self.youtube_signals[:3]:
                title = y.get("title", "")
                channel = y.get("channel", "")
                lines.append(f"  {title} — {channel}")

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
                lines.append(f"    Thesis: {thesis}")
            if source:
                lines.append(f"    Source: {source}")
            # Cross-reference signals
            intel = self._gather_ticker_intel(t)
            for line in intel:
                lines.append(f"    {line}")
            # Pros/cons
            pros = c.get("pros", [])
            cons = c.get("cons", [])
            if pros:
                lines.append(f"    Bull: {'; '.join(str(p) for p in pros[:3])}")
            if cons:
                lines.append(f"    Bear: {'; '.join(str(p) for p in cons[:3])}")

        for m in moonshots:
            t = m.get("ticker", "?")
            thesis = m.get("thesis", "")
            upside = m.get("upside_case", "")
            downside = m.get("downside_case", "")
            milestone = m.get("key_milestone", "")
            lines.append(f"\n  {t} [MOONSHOT]")
            if thesis:
                lines.append(f"    Thesis: {thesis}")
            if upside:
                lines.append(f"    Upside: {upside}")
            if downside:
                lines.append(f"    Downside: {downside}")
            if milestone:
                lines.append(f"    Milestone: {milestone}")
            intel = self._gather_ticker_intel(t)
            for line in intel:
                lines.append(f"    {line}")
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
    line-height: 1.5;
    -webkit-text-size-adjust: 100%;
  }}
  .container {{
    max-width: 640px;
    margin: 0 auto;
    background: #ffffff;
  }}

  /* Header banner */
  .header {{
    background: linear-gradient(135deg, #0f172a 0%, #1e3a5f 100%);
    color: #ffffff;
    padding: 24px 24px 20px;
  }}
  .header-title {{
    font-size: 0.8em;
    text-transform: uppercase;
    letter-spacing: 1.5px;
    color: #94a3b8;
    margin-bottom: 4px;
  }}
  .header-date {{
    font-size: 1.1em;
    font-weight: 600;
    margin-bottom: 16px;
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
    font-size: 0.7em;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    color: #94a3b8;
  }}
  .stat-value {{
    font-size: 1.3em;
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
    padding: 20px 24px;
    border-bottom: 1px solid #e2e8f0;
  }}
  .section:last-of-type {{
    border-bottom: none;
  }}
  .section-title {{
    font-size: 0.7em;
    text-transform: uppercase;
    letter-spacing: 1.5px;
    color: #94a3b8;
    margin-bottom: 12px;
    font-weight: 600;
  }}
  .section-body {{
    font-size: 0.9em;
    color: #334155;
  }}
  .section-body p {{
    margin-bottom: 8px;
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
    padding: 10px 12px;
    text-align: center;
    border-right: 1px solid #e2e8f0;
  }}
  .market-item:last-child {{
    border-right: none;
  }}
  .market-item-label {{
    font-size: 0.65em;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    color: #94a3b8;
  }}
  .market-item-value {{
    font-size: 0.95em;
    font-weight: 600;
    color: #1e293b;
  }}

  /* Holding card (movers) */
  .holding-card {{
    background: #f8fafc;
    border-radius: 8px;
    padding: 14px 16px;
    margin-bottom: 8px;
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
    font-size: 1em;
    color: #0f172a;
  }}
  .holding-change {{
    font-weight: 700;
    font-size: 1em;
  }}
  .holding-meta {{
    font-size: 0.8em;
    color: #64748b;
    margin-bottom: 6px;
  }}
  .holding-events {{
    font-size: 0.8em;
    color: #475569;
    padding-left: 8px;
    border-left: 2px solid #e2e8f0;
  }}
  .holding-events div {{
    margin-bottom: 2px;
  }}

  /* Steady holdings table */
  .steady-table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 0.85em;
    margin-top: 12px;
  }}
  .steady-table th {{
    text-align: left;
    font-size: 0.7em;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    color: #94a3b8;
    padding: 4px 8px;
    border-bottom: 1px solid #e2e8f0;
    font-weight: 600;
  }}
  .steady-table td {{
    padding: 6px 8px;
    color: #334155;
    border-bottom: 1px solid #f1f5f9;
  }}

  /* Action card */
  .action-card {{
    background: #fffbeb;
    border: 1px solid #fde68a;
    border-radius: 8px;
    padding: 12px 16px;
    margin-bottom: 8px;
  }}
  .action-label {{
    font-weight: 700;
    font-size: 0.85em;
    color: #92400e;
  }}
  .action-reason {{
    font-size: 0.85em;
    color: #78350f;
    margin-top: 2px;
  }}

  /* Risk block */
  .risk-block {{
    background: #fef2f2;
    border: 1px solid #fecaca;
    border-radius: 8px;
    padding: 12px 16px;
    margin-top: 8px;
  }}
  .risk-label {{
    font-weight: 600;
    font-size: 0.75em;
    text-transform: uppercase;
    color: #991b1b;
    margin-bottom: 4px;
  }}
  .risk-text {{
    font-size: 0.85em;
    color: #7f1d1d;
    line-height: 1.4;
  }}

  /* Watchlist */
  .watch-item {{
    display: flex;
    align-items: baseline;
    gap: 8px;
    padding: 8px 0;
    border-bottom: 1px solid #f1f5f9;
    font-size: 0.85em;
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
    gap: 8px;
    padding: 6px 0;
    font-size: 0.85em;
    color: #334155;
  }}
  .event-date {{
    font-weight: 600;
    color: #0f172a;
    min-width: 60px;
    font-size: 0.8em;
  }}
  .event-days {{
    font-size: 0.75em;
    color: #94a3b8;
    white-space: nowrap;
  }}

  /* Thesis row */
  .thesis-row {{
    display: flex;
    align-items: baseline;
    gap: 8px;
    padding: 6px 0;
    font-size: 0.85em;
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
    font-size: 0.85em;
  }}

  /* Footer */
  .footer {{
    padding: 16px 24px;
    background: #f8fafc;
    border-top: 1px solid #e2e8f0;
    font-size: 0.75em;
    color: #94a3b8;
    text-align: center;
  }}

  /* Responsive */
  @media (max-width: 480px) {{
    .header {{ padding: 16px; }}
    .section {{ padding: 16px; }}
    .header-stats {{ gap: 12px; }}
    .stat-value {{ font-size: 1.1em; }}
    .market-item {{ padding: 8px; }}
  }}
</style>
</head>"""

    def _html_header(self, totals: dict) -> str:
        today = datetime.now().strftime("%B %d, %Y")
        pnl = totals["daily_pnl"]
        pnl_color = "#4ade80" if pnl >= 0 else "#f87171"
        pnl_sign = "+" if pnl >= 0 else ""
        headline = _esc(self._get_headline())

        headline_html = ""
        if headline:
            headline_html = f'<div class="headline">{headline}</div>'

        return f"""
<div class="header">
  <div class="header-title">AlphaDesk Daily Brief</div>
  <div class="header-date">{today}</div>
  <div class="header-stats">
    <div class="stat">
      <div class="stat-label">Portfolio</div>
      <div class="stat-value">{_dollar(totals['value'])}</div>
    </div>
    <div class="stat">
      <div class="stat-label">Today</div>
      <div class="stat-value" style="color:{pnl_color}">{pnl_sign}{_dollar(pnl)}</div>
    </div>
    <div class="stat">
      <div class="stat-label">Unrealized</div>
      <div class="stat-value">{_dollar(totals['unrealized'])}</div>
    </div>
    <div class="stat">
      <div class="stat-label">Holdings</div>
      <div class="stat-value">{totals['holdings_count']}</div>
    </div>
  </div>
  {headline_html}
</div>"""

    def _html_what_changed(self) -> str:
        cio = self._get_cio_sections()
        text = cio.get("what changed today", "")
        if not text:
            brief = self.committee_result.get("formatted_brief", "")
            if brief:
                # Take first meaningful paragraph
                paras = [p.strip() for p in brief.strip().split("\n\n") if len(p.strip()) > 30]
                text = paras[0] if paras else ""
        if not text:
            return ""

        # Clean up markdown formatting for HTML
        text = re.sub(r"\*{1,2}(.+?)\*{1,2}", r"<strong>\1</strong>", text)
        # Convert bullet points
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
  <div class="section-title">What Changed Today</div>
  <div class="section-body">{body}</div>
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

        # Active theses — only show ones with recent evidence
        theses_html = ""
        if self.updated_theses:
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

        movers_label = f'<div style="font-size:0.75em;text-transform:uppercase;letter-spacing:1px;color:#94a3b8;margin-bottom:8px;font-weight:600">Movers</div>' if movers else ""
        steady_label = f'<div style="font-size:0.75em;text-transform:uppercase;letter-spacing:1px;color:#94a3b8;margin-top:16px;margin-bottom:4px;font-weight:600">Steady</div>' if steady else ""

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
                        f'<span style="background:#e0e7ff;color:#3730a3;padding:1px 5px;border-radius:4px;font-size:0.7em;font-weight:600">{_esc(t)}</span>'
                        for t in tickers[:3]
                    )
                    ticker_html = f'<span style="margin-left:6px">{pills}</span>'
                urgency_dot = ""
                if urgency == "high":
                    urgency_dot = '<span style="color:#dc2626;margin-right:4px" title="High urgency">&#9679;</span>'
                sent_color = _color(sentiment)
                items.append(f"""
<div style="padding:6px 0;border-bottom:1px solid #f1f5f9;font-size:0.85em">
  {urgency_dot}<span style="color:#1e293b">{title}</span>{ticker_html}
  <span style="color:#94a3b8;font-size:0.85em;margin-left:6px">{source}</span>
</div>""")
            blocks.append(f"""
<div style="margin-bottom:14px">
  <div style="font-size:0.7em;text-transform:uppercase;letter-spacing:1px;color:#94a3b8;font-weight:600;margin-bottom:6px">Top Headlines</div>
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
                items.append(f"""
<div style="display:flex;align-items:baseline;gap:8px;padding:5px 0;border-bottom:1px solid #f1f5f9;font-size:0.85em">
  <span style="font-weight:700;color:#0f172a;min-width:44px">{ticker}</span>
  <span style="color:{sent_color};font-weight:600;min-width:36px">{sent_str}</span>
  <span style="color:#64748b">{mentions} mentions</span>
  <span style="color:#94a3b8;font-size:0.85em">r/{_esc(str(subs))}</span>
</div>""")
            blocks.append(f"""
<div style="margin-bottom:14px">
  <div style="font-size:0.7em;text-transform:uppercase;letter-spacing:1px;color:#f97316;font-weight:600;margin-bottom:6px">&#128172; Reddit</div>
  {"".join(items)}
</div>""")

        # Substack newsletters
        if has_substack:
            items = []
            for s in self.substack_signals[:4]:
                title = _esc(s.get("title", ""))
                summary = _esc(s.get("summary", "")[:120])
                tickers = s.get("tickers", s.get("affected_tickers", []))
                ticker_html = ""
                if tickers:
                    pills = " ".join(
                        f'<span style="background:#fce7f3;color:#9d174d;padding:1px 5px;border-radius:4px;font-size:0.7em;font-weight:600">{_esc(t)}</span>'
                        for t in tickers[:3]
                    )
                    ticker_html = f'<div style="margin-top:2px">{pills}</div>'
                summary_html = f'<div style="color:#64748b;font-size:0.85em;margin-top:2px">{summary}</div>' if summary else ""
                items.append(f"""
<div style="padding:6px 0;border-bottom:1px solid #f1f5f9;font-size:0.85em">
  <div style="color:#1e293b;font-weight:500">{title}</div>
  {summary_html}
  {ticker_html}
</div>""")
            blocks.append(f"""
<div style="margin-bottom:14px">
  <div style="font-size:0.7em;text-transform:uppercase;letter-spacing:1px;color:#8b5cf6;font-weight:600;margin-bottom:6px">&#128220; Substack</div>
  {"".join(items)}
</div>""")

        # YouTube
        if has_youtube:
            items = []
            for y in self.youtube_signals[:3]:
                title = _esc(y.get("title", ""))
                channel = _esc(y.get("channel", y.get("author", "")))
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
                items.append(f"""
<div style="padding:5px 0;border-bottom:1px solid #f1f5f9;font-size:0.85em">
  <span style="color:#1e293b">{title}</span>{ticker_html}
  <div style="color:#94a3b8;font-size:0.85em">{channel}{(' · ' + view_str) if view_str else ''}</div>
</div>""")
            blocks.append(f"""
<div style="margin-bottom:14px">
  <div style="font-size:0.7em;text-transform:uppercase;letter-spacing:1px;color:#dc2626;font-weight:600;margin-bottom:6px">&#9654; YouTube</div>
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
                badges.append('<span style="background:#dcfce7;color:#166534;padding:2px 6px;border-radius:8px;font-size:0.7em;font-weight:600">INSIDER BUYING</span>')
            if count and count > 0:
                badges.append(f'<span style="background:#e0e7ff;color:#3730a3;padding:2px 6px;border-radius:8px;font-size:0.7em;font-weight:600">{count} SUPER</span>')

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

            # Evidence tags
            evidence_html = ""
            if pros or cons:
                tags = []
                for p in (pros if isinstance(pros, list) else [])[:4]:
                    p_str = str(p)
                    tags.append(f'<span style="background:#dcfce7;color:#166534;padding:1px 6px;border-radius:4px;font-size:0.7em;margin:1px">{_esc(p_str)}</span>')
                for co in (cons if isinstance(cons, list) else [])[:3]:
                    c_str = str(co)
                    tags.append(f'<span style="background:#fecaca;color:#991b1b;padding:1px 6px;border-radius:4px;font-size:0.7em;margin:1px">{_esc(c_str)}</span>')
                evidence_html = f'<div style="margin-top:6px;display:flex;flex-wrap:wrap;gap:2px">{"".join(tags)}</div>'

            # Cross-reference intel
            intel_html = self._build_intel_html(ticker)

            # Source line
            source_html = f'<div style="font-size:0.75em;color:#94a3b8;margin-top:4px">Source: {source}</div>' if source else ""

            all_cards.append(f"""
<div style="background:#f8fafc;border-radius:8px;padding:14px 16px;margin-bottom:10px;border-left:4px solid #2563eb">
  <div style="display:flex;align-items:baseline;gap:8px;margin-bottom:4px">
    <span style="font-weight:700;font-size:1em;color:#0f172a">{_esc(ticker)}</span>
    {_conviction_pill(conv)}
    <span style="font-size:0.75em;color:#94a3b8">Week {weeks}</span>
  </div>
  <div style="font-size:0.85em;color:#334155;margin-bottom:4px">{thesis}</div>
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

            # Upside/downside row
            scenarios_html = ""
            scenario_parts = []
            if upside:
                scenario_parts.append(f'<span style="color:#16a34a">&#9650; {upside}</span>')
            if downside:
                scenario_parts.append(f'<span style="color:#dc2626">&#9660; {downside}</span>')
            if scenario_parts:
                scenarios_html = f'<div style="font-size:0.8em;margin-top:4px">{" &nbsp;|&nbsp; ".join(scenario_parts)}</div>'

            milestone_html = f'<div style="font-size:0.75em;color:#94a3b8;margin-top:4px">Milestone: {milestone}</div>' if milestone else ""

            # Cross-reference intel
            intel_html = self._build_intel_html(ticker)

            all_cards.append(f"""
<div style="background:#faf5ff;border-radius:8px;padding:14px 16px;margin-bottom:10px;border-left:4px solid #7c3aed">
  <div style="display:flex;align-items:baseline;gap:8px;margin-bottom:4px">
    <span style="font-weight:700;font-size:1em;color:#0f172a">{_esc(ticker)}</span>
    <span style="background:#ede9fe;color:#5b21b6;padding:2px 6px;border-radius:8px;font-size:0.7em;font-weight:600">MOONSHOT</span>
  </div>
  <div style="font-size:0.85em;color:#334155;margin-bottom:2px">{thesis}</div>
  {scenarios_html}
  {milestone_html}
  {intel_html}
</div>""")

        return f"""
<div class="section">
  <div class="section-title">Watchlist</div>
  {"".join(all_cards)}
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
                intel_items.append(
                    f'<span style="color:#f97316">&#128172;</span> '
                    f'<span style="color:{sent_color};font-weight:600">{sent_str}</span> '
                    f'sentiment, {mentions} mentions'
                    + (f' <span style="color:#94a3b8">r/{_esc(str(sub))}</span>' if sub else "")
                )
                break

        # Substack signal
        for s in self.substack_signals:
            tickers = [t.upper() for t in s.get("tickers", s.get("affected_tickers", []))]
            if ticker.upper() in tickers:
                title = _esc(s.get("title", ""))
                summary = _esc(s.get("summary", "")[:80])
                line = f'<span style="color:#8b5cf6">&#128220;</span> {title}'
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
                intel_items.append(f'<span style="color:#dc2626">&#9654;</span> {title} <span style="color:#94a3b8">— {channel}</span>')
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

        rows = "\n".join(f'<div style="padding:2px 0">{item}</div>' for item in intel_items)
        return f"""
<div style="margin-top:8px;padding:8px 10px;background:rgba(255,255,255,0.7);border-radius:6px;font-size:0.8em;color:#475569;border:1px solid #e2e8f0">
  {rows}
</div>"""

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

        return f"""
<div class="footer">
  AlphaDesk v2.0 · ${self.daily_cost:.2f} · {self.total_time:.0f}s · {ts}<br>
  {sources_str}
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
