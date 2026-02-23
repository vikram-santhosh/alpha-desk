"""Verbose investment memo formatter for AlphaDesk Advisor.

Generates a comprehensive multi-section investment report as both Markdown
and HTML. Designed for email delivery and archival — separate from the
condensed Telegram formatter.

Sections:
  1. Executive Summary
  2. Market Context
  3. Holdings Deep Dive
  4. Strategy Memo
  5. Thesis Exposure Analysis
  6. Conviction List Deep Dive
  7. Moonshot Analysis
  8. Analyst Committee Transcript
  9. Delta Report
  10. Catalyst Calendar
  11. Track Record / Scorecard
  12. Sources Used
  13. Cost Breakdown
"""

from datetime import datetime
from typing import Any

from src.utils.logger import get_logger

log = get_logger(__name__)

SEPARATOR_MD = "---"


def _safe(val: Any, fmt: str = "", default: str = "N/A") -> str:
    """Safely format a value, returning default if None."""
    if val is None:
        return default
    try:
        if fmt:
            return f"{val:{fmt}}"
        return str(val)
    except (ValueError, TypeError):
        return default


def _pct(val: float | None, signed: bool = False) -> str:
    if val is None:
        return "N/A"
    if signed:
        return f"{val:+.1f}%"
    return f"{val:.1f}%"


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


def _status_indicator(status: str) -> str:
    if status in ("strengthening", "intact"):
        return "[INTACT]"
    if status in ("evolving", "monitoring"):
        return "[EVOLVING]"
    if status in ("weakening", "invalidated"):
        return "[WEAKENING]"
    return "[UNKNOWN]"


class VerboseFormatter:
    """Generates full investment memo from pipeline data."""

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
        self.daily_cost = daily_cost
        self.total_time = total_time

    def generate_markdown(self) -> str:
        """Generate the full verbose report as Markdown."""
        today = datetime.now().strftime("%B %d, %Y")
        sections = [
            f"# AlphaDesk Daily Investment Memo — {today}\n",
            self._section_executive_summary(),
            self._section_market_context(),
            self._section_holdings_deep_dive(),
            self._section_strategy_memo(),
            self._section_thesis_exposure(),
            self._section_conviction_deep_dive(),
            self._section_moonshot_analysis(),
            self._section_committee_transcript(),
            self._section_delta_report(),
            self._section_catalyst_calendar(),
            self._section_track_record(),
            self._section_sources(),
            self._section_cost_breakdown(),
        ]
        return "\n\n".join(s for s in sections if s)

    def generate_html(self, markdown_text: str | None = None) -> str:
        """Convert the Markdown report to email-safe HTML with inline CSS."""
        md = markdown_text or self.generate_markdown()
        return _markdown_to_html(md)

    # ────────────────────────────────────────────────────────
    # Section 1: Executive Summary
    # ────────────────────────────────────────────────────────

    def _section_executive_summary(self) -> str:
        lines = ["## 1. Executive Summary\n"]

        # Portfolio totals
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

        lines.append(f"**Portfolio Value:** {_dollar(total_value)}  ")
        lines.append(f"**Today's P&L:** {_dollar(total_daily_pnl)}  ")
        lines.append(f"**Unrealized P&L:** {_dollar(total_unrealized)}  ")
        lines.append(f"**Holdings:** {len(self.holdings_reports)}  ")
        lines.append(f"**Conviction Names:** {len(self.conviction_result.get('current_list', []))}  ")
        lines.append(f"**Moonshots:** {len(self.moonshot_result.get('current_list', []))}  ")
        lines.append(f"**Strategy Actions:** {len(self.strategy.get('actions', []))}\n")

        # Committee brief as executive summary
        brief = self.committee_result.get("formatted_brief", "")
        if brief:
            lines.append(brief[:2000])

        return "\n".join(lines)

    # ────────────────────────────────────────────────────────
    # Section 2: Market Context
    # ────────────────────────────────────────────────────────

    def _section_market_context(self) -> str:
        lines = ["## 2. Market Context\n"]

        def _mv(key: str) -> tuple[str, str]:
            v = self.macro_data.get(key)
            if isinstance(v, dict):
                val = _safe(v.get("value"), ".2f")
                chg = _pct(v.get("change_pct"), signed=True)
                return val, chg
            return _safe(v, ".2f"), "N/A"

        sp_val, sp_chg = _mv("sp500")
        vix_val, vix_chg = _mv("vix")
        tnx_val, tnx_chg = _mv("treasury_10y")
        ff_val, _ = _mv("fed_funds_rate")

        lines.append("### Market Snapshot\n")
        lines.append("| Indicator | Value | Change |")
        lines.append("|-----------|-------|--------|")
        lines.append(f"| S&P 500 | {sp_val} | {sp_chg} |")
        lines.append(f"| VIX | {vix_val} | {vix_chg} |")
        lines.append(f"| 10Y Treasury | {tnx_val}% | {tnx_chg} |")
        lines.append(f"| Fed Funds Rate | {ff_val}% | — |")
        yc = self.macro_data.get("yield_curve_spread_calculated", "N/A")
        lines.append(f"| Yield Curve | {yc} | — |")

        # Macro theses
        if self.updated_theses:
            lines.append("\n### Active Macro Theses\n")
            for t in self.updated_theses:
                status = t.get("status", "intact")
                title = t.get("title", "")
                affected = ", ".join(t.get("affected_tickers", [])[:6])
                evidence_log = t.get("evidence_log", [])
                lines.append(f"**{title}** {_status_indicator(status)}")
                lines.append(f"  - Affected: {affected}")
                if evidence_log:
                    latest = evidence_log[-1]
                    lines.append(f"  - Latest evidence: {latest.get('evidence', '')}")
                lines.append("")

        # Prediction market shifts
        if self.prediction_shifts:
            lines.append("### Prediction Market Shifts\n")
            for pm in self.prediction_shifts[:5]:
                title = pm.get("market_title", "")
                prob = pm.get("probability", 0)
                delta = pm.get("delta", 0)
                direction = "UP" if delta > 0 else "DOWN"
                lines.append(f"- **{title}**: {prob*100:.0f}% ({delta*100:+.0f}pp {direction})")

        # Reddit mood
        if self.reddit_mood and self.reddit_mood != "unknown":
            themes = ", ".join(self.reddit_themes[:3]) if self.reddit_themes else "none"
            lines.append(f"\n**Reddit Mood:** {self.reddit_mood} — Top themes: {themes}")

        return "\n".join(lines)

    # ────────────────────────────────────────────────────────
    # Section 3: Holdings Deep Dive
    # ────────────────────────────────────────────────────────

    def _section_holdings_deep_dive(self) -> str:
        lines = ["## 3. Holdings Deep Dive\n"]

        if not self.holdings_reports:
            lines.append("*No holdings data available.*")
            return "\n".join(lines)

        sorted_holdings = sorted(
            self.holdings_reports,
            key=lambda h: (h.get("position_pct") or 0),
            reverse=True,
        )

        for h in sorted_holdings:
            ticker = h.get("ticker", "???")
            price = h.get("price")
            shares = h.get("shares") or 0
            entry = h.get("entry_price")
            change_pct = h.get("change_pct")
            cumul = h.get("cumulative_return_pct")
            position_pct = h.get("position_pct") or 0
            thesis = h.get("thesis", "")
            thesis_status = h.get("thesis_status", "intact")
            category = h.get("category", "core")
            recent_trend = h.get("recent_trend", "")
            key_events = h.get("key_events", [])
            sector = h.get("sector", "")

            lines.append(f"### {ticker} — {_pct(position_pct)} of portfolio\n")

            # Price info
            lines.append("| Metric | Value |")
            lines.append("|--------|-------|")
            lines.append(f"| Current Price | {_dollar(price)} |")
            lines.append(f"| Today | {_pct(change_pct, signed=True)} |")
            lines.append(f"| Entry Price | {_dollar(entry)} |")
            lines.append(f"| Total Return | {_pct(cumul, signed=True)} |")
            lines.append(f"| Shares | {shares} |")
            if price and shares:
                mv = price * shares
                lines.append(f"| Market Value | {_dollar(mv)} |")
                if entry and entry > 0:
                    pnl = (price - entry) * shares
                    lines.append(f"| Unrealized P&L | {_dollar(pnl)} |")
            lines.append(f"| Category | {category} |")
            lines.append(f"| Sector | {sector or 'N/A'} |")

            # Technicals
            tech = self.technicals.get(ticker, {})
            if tech:
                lines.append(f"\n**Technical Setup:**")
                rsi_data = tech.get("rsi")
                rsi_val = rsi_data.get("rsi") if isinstance(rsi_data, dict) else rsi_data
                rsi_signal = rsi_data.get("signal", "") if isinstance(rsi_data, dict) else ""
                macd = tech.get("macd_signal", "N/A")
                trend = tech.get("trend", "N/A")
                support = tech.get("support")
                resistance = tech.get("resistance")
                tech_signals = tech.get("signals", [])

                lines.append(f"- RSI: {_safe(rsi_val, '.1f')} ({rsi_signal})")
                lines.append(f"- MACD: {macd}")
                lines.append(f"- Trend: {trend}")
                if support:
                    lines.append(f"- Support: {_dollar(support)}")
                if resistance:
                    lines.append(f"- Resistance: {_dollar(resistance)}")
                if tech_signals:
                    lines.append(f"- Signals: {', '.join(str(s) for s in tech_signals[:3])}")

            # Fundamentals
            fund = self.fundamentals.get(ticker, {})
            if fund:
                lines.append(f"\n**Fundamentals:**")
                lines.append(f"- P/E (trailing): {_safe(fund.get('pe_trailing'), '.1f')}")
                lines.append(f"- P/E (forward): {_safe(fund.get('pe_forward'), '.1f')}")
                rev_growth = fund.get("revenue_growth")
                if rev_growth is not None:
                    lines.append(f"- Revenue Growth: {rev_growth:.0%}")
                margin = fund.get("net_margin")
                if margin is not None:
                    lines.append(f"- Net Margin: {margin:.0%}")
                roe = fund.get("roe")
                if roe is not None:
                    lines.append(f"- ROE: {roe:.0%}")

            # Thesis
            lines.append(f"\n**Thesis:** {thesis} {_status_indicator(thesis_status)}")

            # Trend & Events
            if recent_trend:
                lines.append(f"\n**Recent Trend:** {recent_trend}")
            if key_events:
                lines.append("\n**Key Events:**")
                for event in key_events[:4]:
                    lines.append(f"- {event}")

            lines.append("")

        return "\n".join(lines)

    # ────────────────────────────────────────────────────────
    # Section 4: Strategy Memo
    # ────────────────────────────────────────────────────────

    def _section_strategy_memo(self) -> str:
        lines = ["## 4. Strategy Memo\n"]

        actions = self.strategy.get("actions", [])
        flags = self.strategy.get("flags", []) or self.strategy.get("active_flags", [])
        summary = self.strategy.get("summary", "")

        if not actions and not flags:
            lines.append("**No changes recommended.** All theses intact.\n")
            if summary:
                lines.append(summary)
            return "\n".join(lines)

        if actions:
            lines.append("### Recommended Actions\n")
            lines.append("| # | Action | Ticker | Urgency | Reason |")
            lines.append("|---|--------|--------|---------|--------|")
            for i, a in enumerate(actions, 1):
                action = a.get("action", "hold").upper()
                ticker = a.get("ticker", "")
                urgency = a.get("urgency", "low")
                reason = a.get("reason", "")
                lines.append(f"| {i} | {action} | {ticker} | {urgency} | {reason} |")
            lines.append("")

        if flags:
            lines.append("### Active Flags\n")
            for f in flags[:8]:
                ticker = f.get("ticker", "")
                flag_type = f.get("flag_type", "").replace("_", " ")
                desc = f.get("description", f.get("message", ""))
                lines.append(f"- **{ticker}** — {flag_type}: {desc}")
            lines.append("")

        if summary:
            lines.append(f"**Summary:** {summary}")

        return "\n".join(lines)

    # ────────────────────────────────────────────────────────
    # Section 5: Thesis Exposure
    # ────────────────────────────────────────────────────────

    def _section_thesis_exposure(self) -> str:
        thesis_exposure = self.strategy.get("thesis_exposure", [])
        if not thesis_exposure:
            return ""

        lines = ["## 5. Thesis Exposure Analysis\n"]

        lines.append("| Thesis | Exposure | Tickers | Status |")
        lines.append("|--------|----------|---------|--------|")
        for entry in thesis_exposure:
            thesis = entry.get("thesis", "")
            pct = entry.get("exposure_pct", 0)
            tickers = ", ".join(entry.get("tickers", [])[:5])
            status = entry.get("status", "intact")
            bar = "#" * int(pct / 5)
            lines.append(f"| {thesis} | {pct:.0f}% `{bar}` | {tickers} | {_status_indicator(status)} |")

        # Overlap warnings
        has_overlap = any(entry.get("overlaps_with") for entry in thesis_exposure)
        if has_overlap:
            lines.append("\n### Overlap Warnings\n")
            for entry in thesis_exposure:
                overlaps = entry.get("overlaps_with", [])
                warning = entry.get("warning", "")
                if overlaps:
                    lines.append(f"- **{entry.get('thesis', '')}** overlaps with: {', '.join(overlaps[:3])}")
                if warning:
                    lines.append(f"  - {warning}")

        return "\n".join(lines)

    # ────────────────────────────────────────────────────────
    # Section 6: Conviction Deep Dive
    # ────────────────────────────────────────────────────────

    def _section_conviction_deep_dive(self) -> str:
        lines = ["## 6. Conviction List Deep Dive\n"]

        current = self.conviction_result.get("current_list", [])
        added = self.conviction_result.get("added", [])
        removed = self.conviction_result.get("removed", [])

        if not current:
            lines.append("*No conviction names currently. Building watchlist.*")
            return "\n".join(lines)

        for entry in current:
            ticker = entry.get("ticker", "???")
            conviction = entry.get("conviction", "medium")
            weeks = entry.get("weeks_on_list", 1)
            thesis = entry.get("thesis", "")
            pros = entry.get("pros", [])
            cons = entry.get("cons", [])

            lines.append(f"### {ticker} — Week {weeks} [{conviction.upper()}]\n")
            lines.append(f"**Thesis:** {thesis}\n")

            if pros:
                lines.append("**Bull Case:**")
                for p in (pros if isinstance(pros, list) else []):
                    lines.append(f"- {p}")
                lines.append("")

            if cons:
                lines.append("**Bear Case:**")
                for c in (cons if isinstance(cons, list) else []):
                    lines.append(f"- {c}")
                lines.append("")

            # Fundamental data if available
            fund = self.fundamentals.get(ticker, {})
            if fund:
                pe = _safe(fund.get("pe_trailing"), ".1f")
                rev = fund.get("revenue_growth")
                rev_str = f"{rev:.0%}" if rev is not None else "N/A"
                lines.append(f"**Valuation:** P/E {pe} | Rev Growth {rev_str}\n")

        if added:
            lines.append("### New Additions\n")
            for a in added:
                lines.append(f"- **{a.get('ticker', '')}**: {a.get('thesis', '')}")

        if removed:
            lines.append("\n### Removed\n")
            for r in removed:
                lines.append(f"- **{r.get('ticker', '')}**: {r.get('removal_reason', r.get('reason', ''))}")

        return "\n".join(lines)

    # ────────────────────────────────────────────────────────
    # Section 7: Moonshot Analysis
    # ────────────────────────────────────────────────────────

    def _section_moonshot_analysis(self) -> str:
        lines = ["## 7. Moonshot Analysis\n"]

        current = self.moonshot_result.get("current_list", [])
        if not current:
            lines.append("*No moonshot ideas currently.*")
            return "\n".join(lines)

        for entry in current:
            ticker = entry.get("ticker", "???")
            conviction = entry.get("conviction", "medium")
            thesis = entry.get("thesis", "")
            upside = entry.get("upside_case", "")
            downside = entry.get("downside_case", "")
            milestone = entry.get("key_milestone", "")
            max_pct = entry.get("max_position_pct", 3.0)

            lines.append(f"### {ticker} [{conviction.upper()}] — Max {max_pct:.0f}% allocation\n")
            lines.append(f"**Thesis:** {thesis}\n")
            if upside:
                lines.append(f"**Upside Scenario:** {upside}\n")
            if downside:
                lines.append(f"**Downside Scenario:** {downside}\n")
            if milestone:
                lines.append(f"**Key Milestone:** {milestone}\n")

        return "\n".join(lines)

    # ────────────────────────────────────────────────────────
    # Section 8: Committee Transcript
    # ────────────────────────────────────────────────────────

    def _section_committee_transcript(self) -> str:
        lines = ["## 8. Analyst Committee Transcript\n"]

        if not self.committee_result:
            lines.append("*Committee did not run.*")
            return "\n".join(lines)

        # Growth report
        growth = self.committee_result.get("growth_report", {})
        if growth and "error" not in growth:
            lines.append("### Growth Analyst\n")
            top_pick = growth.get("top_growth_pick", "N/A")
            concern = growth.get("growth_concern", "N/A")
            lines.append(f"**Top Growth Pick:** {top_pick}  ")
            lines.append(f"**Growth Concern:** {concern}\n")
            analyses = growth.get("analyses", {})
            for ticker, data in list(analyses.items())[:8]:
                if not isinstance(data, dict):
                    continue
                score = data.get("growth_score", "N/A")
                thesis = data.get("growth_thesis", "")
                moat = data.get("competitive_moat", "N/A")
                risk = data.get("key_growth_risk", "")
                lines.append(f"- **{ticker}** (score: {score}, moat: {moat}): {thesis}")
                if risk:
                    lines.append(f"  - Risk: {risk}")
            lines.append("")

        # Value report
        value = self.committee_result.get("value_report", {})
        if value and "error" not in value:
            lines.append("### Value Analyst\n")
            best = value.get("best_value", "N/A")
            expensive = value.get("most_expensive", "N/A")
            lines.append(f"**Best Value:** {best}  ")
            lines.append(f"**Most Expensive:** {expensive}\n")
            analyses = value.get("analyses", {})
            for ticker, data in list(analyses.items())[:8]:
                if not isinstance(data, dict):
                    continue
                score = data.get("value_score", "N/A")
                thesis = data.get("value_thesis", "")
                regime = data.get("current_regime", "N/A")
                mos = data.get("margin_of_safety_pct", "N/A")
                lines.append(f"- **{ticker}** (score: {score}, regime: {regime}, MoS: {mos}%): {thesis}")
            lines.append("")

        # Risk report
        risk = self.committee_result.get("risk_report", {})
        if risk and "error" not in risk:
            lines.append("### Risk Officer\n")
            risk_score = risk.get("risk_score_portfolio", "N/A")
            top_risk = risk.get("top_risk", "N/A")
            corr = risk.get("correlation_warning", "N/A")
            lines.append(f"**Portfolio Risk Score:** {risk_score}/100 (higher = safer)  ")
            lines.append(f"**Top Risk:** {top_risk}  ")
            lines.append(f"**Correlation Warning:** {corr}\n")

            flags = risk.get("portfolio_risk_flags", [])
            if flags:
                lines.append("**Risk Flags:**")
                for f in flags[:5]:
                    if isinstance(f, dict):
                        lines.append(f"- {f.get('flag', '')}")
                        scenario = f.get("scenario", "")
                        if scenario:
                            lines.append(f"  - Scenario: {scenario}")
                        mitigation = f.get("mitigation", "")
                        if mitigation:
                            lines.append(f"  - Mitigation: {mitigation}")
                lines.append("")

            drawdown = risk.get("max_drawdown_scenario", {})
            if drawdown and isinstance(drawdown, dict):
                lines.append("**Worst-Case Drawdown Scenario:**")
                lines.append(f"- Scenario: {drawdown.get('scenario', 'N/A')}")
                lines.append(f"- Estimated drawdown: {drawdown.get('estimated_portfolio_drawdown_pct', 'N/A')}%")
                survive = drawdown.get("which_holdings_survive", [])
                dont = drawdown.get("which_dont", [])
                if survive:
                    lines.append(f"- Survivors: {', '.join(str(s) for s in survive)}")
                if dont:
                    lines.append(f"- At risk: {', '.join(str(d) for d in dont)}")

        return "\n".join(lines)

    # ────────────────────────────────────────────────────────
    # Section 9: Delta Report
    # ────────────────────────────────────────────────────────

    def _section_delta_report(self) -> str:
        lines = ["## 9. Delta Report — What Changed\n"]

        if not self.delta_report:
            lines.append("*No delta data available (first run or delta engine disabled).*")
            return "\n".join(lines)

        # Handle both DeltaReport objects and dicts
        if hasattr(self.delta_report, "high_significance"):
            high = self.delta_report.high_significance
            medium = self.delta_report.medium_significance
            low = self.delta_report.low_significance
            summary = self.delta_report.summary
            total = self.delta_report.total_changes
        else:
            high = [type("D", (), d)() for d in self.delta_report.get("high_significance", [])]
            medium = [type("D", (), d)() for d in self.delta_report.get("medium_significance", [])]
            low = [type("D", (), d)() for d in self.delta_report.get("low_significance", [])]
            summary = self.delta_report.get("summary", "")
            total = len(high) + len(medium) + len(low)

        if summary:
            lines.append(f"*{summary}*\n")

        lines.append(f"**Total changes:** {total} ({len(high)} high, {len(medium)} medium, {len(low)} low)\n")

        if high:
            lines.append("### High Significance\n")
            for item in high:
                narrative = getattr(item, "narrative", str(item))
                lines.append(f"- **{narrative}**")
            lines.append("")

        if medium:
            lines.append("### Medium Significance\n")
            for item in medium[:10]:
                narrative = getattr(item, "narrative", str(item))
                lines.append(f"- {narrative}")
            lines.append("")

        if low:
            lines.append(f"*{len(low)} low-significance changes omitted.*")

        return "\n".join(lines)

    # ────────────────────────────────────────────────────────
    # Section 10: Catalyst Calendar
    # ────────────────────────────────────────────────────────

    def _section_catalyst_calendar(self) -> str:
        lines = ["## 10. Catalyst Calendar (Next 30 Days)\n"]

        catalysts = self.catalyst_data.get("catalysts", [])
        if not catalysts:
            lines.append("*No upcoming catalysts tracked.*")
            return "\n".join(lines)

        lines.append("| Date | Event | Type | Impact | Days Away |")
        lines.append("|------|-------|------|--------|-----------|")

        for c in catalysts[:20]:
            if isinstance(c, dict):
                dt = c.get("date", "TBD")
                desc = c.get("description", "")
                event_type = c.get("event_type", "")
                impact = c.get("impact_estimate", "medium")
                days = c.get("days_away", "?")
                lines.append(f"| {dt} | {desc} | {event_type} | {impact} | {days} |")
            else:
                # Handle CatalystEvent dataclasses
                dt = getattr(c, "date", "TBD")
                desc = getattr(c, "description", "")
                event_type = getattr(c, "event_type", "")
                impact = getattr(c, "impact_estimate", "medium")
                days = getattr(c, "days_away", "?")
                lines.append(f"| {dt} | {desc} | {event_type} | {impact} | {days} |")

        return "\n".join(lines)

    # ────────────────────────────────────────────────────────
    # Section 11: Track Record
    # ────────────────────────────────────────────────────────

    def _section_track_record(self) -> str:
        lines = ["## 11. Track Record / Scorecard\n"]

        if not self.scorecard or self.scorecard.get("total_recommendations", 0) == 0:
            lines.append("*No recommendation history yet.*")
            return "\n".join(lines)

        sc = self.scorecard
        lines.append(f"**Total Recommendations (30d):** {sc.get('total_recommendations', 0)}  ")
        lines.append(f"**Hit Rate (1m):** {sc.get('hit_rate_1m', 0):.0f}%  ")
        lines.append(f"**Avg Return (1m):** {sc.get('avg_return_1m_pct', 0):+.1f}%  ")
        lines.append(f"**Avg Alpha vs SPY (1m):** {sc.get('avg_alpha_1m_pct', 0):+.1f}%  ")
        lines.append(f"**False Positive Rate:** {sc.get('false_positive_rate', 0):.0f}%\n")

        best = sc.get("best_recommendation")
        worst = sc.get("worst_recommendation")
        if best:
            lines.append(f"**Best:** {best['ticker']} ({best['return_pct']:+.1f}%)  ")
        if worst:
            lines.append(f"**Worst:** {worst['ticker']} ({worst['return_pct']:+.1f}%)")

        by_conv = sc.get("hit_rate_by_conviction", {})
        if by_conv:
            lines.append("\n### By Conviction Level\n")
            lines.append("| Level | Hit Rate |")
            lines.append("|-------|----------|")
            for level, rate in sorted(by_conv.items()):
                lines.append(f"| {level} | {rate:.0f}% |")

        return "\n".join(lines)

    # ────────────────────────────────────────────────────────
    # Section 12: Sources
    # ────────────────────────────────────────────────────────

    def _section_sources(self) -> str:
        lines = ["## 12. Sources Used\n"]

        sources = set()
        sources.add("yfinance (prices, historical, fundamentals)")

        if self.macro_data:
            sources.add("FRED API (macro indicators)")
        if self.top_articles:
            for a in self.top_articles[:5]:
                src = a.get("source", "")
                if src:
                    sources.add(f"News: {src}")
        if self.reddit_mood:
            sources.add("Reddit (Street Ear agent)")
        if self.earnings_data:
            sources.add("Financial Modeling Prep (earnings transcripts)")
        if self.superinvestor_data:
            sources.add("SEC EDGAR (13F filings)")
        if self.prediction_shifts:
            sources.add("Polymarket / Kalshi (prediction markets)")
        sources.add("Anthropic Claude Opus 4.6 (analysis)")

        for s in sorted(sources):
            lines.append(f"- {s}")

        return "\n".join(lines)

    # ────────────────────────────────────────────────────────
    # Section 13: Cost Breakdown
    # ────────────────────────────────────────────────────────

    def _section_cost_breakdown(self) -> str:
        lines = ["## 13. Cost Breakdown\n"]
        lines.append(f"**Today's API Cost:** ${self.daily_cost:.2f}  ")
        lines.append(f"**Pipeline Runtime:** {self.total_time:.1f}s\n")
        lines.append(f"*Generated by AlphaDesk v2.0 on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*")
        return "\n".join(lines)


# ═══════════════════════════════════════════════════════
# MARKDOWN → HTML CONVERTER
# ═══════════════════════════════════════════════════════

def _markdown_to_html(md: str) -> str:
    """Convert Markdown to email-safe HTML with inline CSS.

    Simple converter that handles the subset of Markdown we generate:
    headings, bold, italic, tables, lists, code spans, horizontal rules.
    """
    import re

    lines = md.split("\n")
    html_lines = []
    in_table = False
    in_list = False
    table_header_done = False

    # CSS
    css = """
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 900px; margin: 0 auto; padding: 20px; color: #1a1a1a; background: #fff; line-height: 1.6; }
        h1 { color: #0f172a; border-bottom: 3px solid #2563eb; padding-bottom: 10px; font-size: 1.8em; }
        h2 { color: #1e3a5f; border-bottom: 1px solid #e2e8f0; padding-bottom: 6px; margin-top: 2em; font-size: 1.4em; }
        h3 { color: #334155; margin-top: 1.5em; font-size: 1.1em; }
        table { border-collapse: collapse; width: 100%; margin: 1em 0; font-size: 0.9em; }
        th { background: #f1f5f9; color: #334155; padding: 8px 12px; text-align: left; border: 1px solid #e2e8f0; font-weight: 600; }
        td { padding: 6px 12px; border: 1px solid #e2e8f0; }
        tr:nth-child(even) { background: #f8fafc; }
        code { background: #f1f5f9; padding: 2px 6px; border-radius: 3px; font-size: 0.9em; color: #475569; }
        blockquote { border-left: 4px solid #2563eb; padding: 0.5em 1em; margin: 1em 0; background: #f8fafc; color: #475569; }
        .status-intact { color: #16a34a; font-weight: 600; }
        .status-evolving { color: #d97706; font-weight: 600; }
        .status-weakening { color: #dc2626; font-weight: 600; }
        hr { border: none; border-top: 1px solid #e2e8f0; margin: 2em 0; }
        ul { padding-left: 1.5em; }
        li { margin-bottom: 0.3em; }
        em { color: #64748b; }
        strong { color: #0f172a; }
    </style>
    """

    html_lines.append(f"<!DOCTYPE html>\n<html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'>{css}</head><body>")

    for line in lines:
        stripped = line.strip()

        # Horizontal rule
        if stripped == "---":
            if in_table:
                html_lines.append("</table>")
                in_table = False
                table_header_done = False
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            html_lines.append("<hr>")
            continue

        # Table separator row (|---|---|)
        if stripped.startswith("|") and set(stripped.replace("|", "").replace("-", "").strip()) <= {" ", ""}:
            table_header_done = True
            continue

        # Table row
        if stripped.startswith("|") and stripped.endswith("|"):
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            cells = [c.strip() for c in stripped[1:-1].split("|")]
            if not in_table:
                html_lines.append("<table>")
                in_table = True
                # First row is header
                html_lines.append("<tr>" + "".join(f"<th>{_inline_md(c)}</th>" for c in cells) + "</tr>")
                continue
            tag = "td"
            html_lines.append("<tr>" + "".join(f"<td>{_inline_md(c)}</td>" for c in cells) + "</tr>")
            continue

        # Close table if we were in one
        if in_table and not stripped.startswith("|"):
            html_lines.append("</table>")
            in_table = False
            table_header_done = False

        # Headings
        if stripped.startswith("# ") and not stripped.startswith("## "):
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            html_lines.append(f"<h1>{_inline_md(stripped[2:])}</h1>")
            continue
        if stripped.startswith("## "):
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            html_lines.append(f"<h2>{_inline_md(stripped[3:])}</h2>")
            continue
        if stripped.startswith("### "):
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            html_lines.append(f"<h3>{_inline_md(stripped[4:])}</h3>")
            continue

        # List items
        if stripped.startswith("- "):
            if not in_list:
                html_lines.append("<ul>")
                in_list = True
            content = stripped[2:]
            # Handle nested items (indented with spaces)
            html_lines.append(f"<li>{_inline_md(content)}</li>")
            continue

        if stripped.startswith("  - "):
            if not in_list:
                html_lines.append("<ul>")
                in_list = True
            html_lines.append(f"<li style='margin-left:1em'>{_inline_md(stripped[4:])}</li>")
            continue

        # Close list if not a list item
        if in_list and not stripped.startswith("- ") and not stripped.startswith("  - "):
            html_lines.append("</ul>")
            in_list = False

        # Empty line
        if not stripped:
            continue

        # Italic block (*text*)
        if stripped.startswith("*") and stripped.endswith("*") and not stripped.startswith("**"):
            html_lines.append(f"<p><em>{_inline_md(stripped[1:-1])}</em></p>")
            continue

        # Regular paragraph
        html_lines.append(f"<p>{_inline_md(stripped)}</p>")

    # Close any open elements
    if in_table:
        html_lines.append("</table>")
    if in_list:
        html_lines.append("</ul>")

    html_lines.append("</body></html>")
    return "\n".join(html_lines)


def _inline_md(text: str) -> str:
    """Convert inline Markdown: **bold**, *italic*, `code`, [INTACT] badges."""
    import re
    # Bold
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    # Italic
    text = re.sub(r"\*(.+?)\*", r"<em>\1</em>", text)
    # Code
    text = re.sub(r"`(.+?)`", r"<code>\1</code>", text)
    # Status badges
    text = text.replace("[INTACT]", '<span class="status-intact">[INTACT]</span>')
    text = text.replace("[EVOLVING]", '<span class="status-evolving">[EVOLVING]</span>')
    text = text.replace("[WEAKENING]", '<span class="status-weakening">[WEAKENING]</span>')
    text = text.replace("[UNKNOWN]", '<span style="color:#94a3b8">[UNKNOWN]</span>')
    return text


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
    from datetime import date

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
