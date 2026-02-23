"""HTML report generator with sparkline charts and styled tables.

Generates email-safe HTML with:
- Sparkline charts (matplotlib → base64 PNG inline images)
- Color-coded performance tables
- Header banner with portfolio summary
- Table of contents
"""

import base64
import io
from datetime import datetime
from typing import Any

from src.utils.logger import get_logger

log = get_logger(__name__)


def _generate_sparkline_base64(
    prices: list[float],
    width: int = 200,
    height: int = 40,
    color: str = "#2563eb",
) -> str | None:
    """Generate a sparkline chart as a base64-encoded PNG.

    Returns base64 string or None if matplotlib unavailable.
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        log.debug("matplotlib not available — skipping sparkline generation")
        return None

    if not prices or len(prices) < 2:
        return None

    fig, ax = plt.subplots(figsize=(width / 100, height / 100), dpi=100)
    ax.plot(prices, color=color, linewidth=1.5)
    ax.fill_between(range(len(prices)), prices, alpha=0.1, color=color)
    ax.set_xlim(0, len(prices) - 1)
    ax.axis("off")
    fig.patch.set_alpha(0)
    ax.patch.set_alpha(0)
    plt.tight_layout(pad=0)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", transparent=True, bbox_inches="tight", pad_inches=0)
    plt.close(fig)
    buf.seek(0)

    return base64.b64encode(buf.read()).decode("ascii")


def _sparkline_img_tag(prices: list[float], color: str = "#2563eb") -> str:
    """Generate an inline <img> tag with a sparkline, or empty string."""
    b64 = _generate_sparkline_base64(prices, color=color)
    if not b64:
        return ""
    return f'<img src="data:image/png;base64,{b64}" style="vertical-align:middle;height:30px;" alt="sparkline">'


def _pnl_color(value: float) -> str:
    """Return CSS color for a P&L value."""
    if value > 0:
        return "#16a34a"
    if value < 0:
        return "#dc2626"
    return "#6b7280"


def _pct_badge(value: float | None) -> str:
    """Return a colored percentage badge."""
    if value is None:
        return '<span style="color:#6b7280">N/A</span>'
    color = _pnl_color(value)
    return f'<span style="color:{color};font-weight:600">{value:+.1f}%</span>'


class ReportHTMLGenerator:
    """Generates a rich HTML email report with charts and styled tables."""

    def __init__(
        self,
        holdings_reports: list[dict] | None = None,
        ticker_dfs: dict | None = None,
        macro_data: dict | None = None,
        strategy: dict | None = None,
        daily_cost: float = 0.0,
    ):
        self.holdings_reports = holdings_reports or []
        self.ticker_dfs = ticker_dfs or {}
        self.macro_data = macro_data or {}
        self.strategy = strategy or {}
        self.daily_cost = daily_cost

    def generate_header_banner(self) -> str:
        """Generate the report header banner with portfolio summary."""
        today = datetime.now().strftime("%B %d, %Y")

        total_value = 0.0
        total_daily_pnl = 0.0
        top_mover_ticker = ""
        top_mover_pct = 0.0

        for h in self.holdings_reports:
            price = h.get("price")
            shares = h.get("shares") or 0
            change_pct = h.get("change_pct") or 0
            if price and shares:
                mv = price * shares
                total_value += mv
                total_daily_pnl += mv * change_pct / 100
            if abs(change_pct) > abs(top_mover_pct):
                top_mover_pct = change_pct
                top_mover_ticker = h.get("ticker", "")

        pnl_color = _pnl_color(total_daily_pnl)
        mover_color = _pnl_color(top_mover_pct)

        return f"""
        <div style="background:linear-gradient(135deg,#0f172a,#1e3a5f);color:white;padding:24px 32px;border-radius:12px;margin-bottom:24px;">
            <h1 style="margin:0;font-size:1.6em;color:white;">AlphaDesk Daily Report</h1>
            <p style="margin:8px 0 0;opacity:0.8;font-size:0.95em;">{today}</p>
            <div style="display:flex;gap:32px;margin-top:16px;flex-wrap:wrap;">
                <div>
                    <div style="opacity:0.7;font-size:0.8em;">Portfolio Value</div>
                    <div style="font-size:1.3em;font-weight:700;">${total_value:,.0f}</div>
                </div>
                <div>
                    <div style="opacity:0.7;font-size:0.8em;">Today's P&L</div>
                    <div style="font-size:1.3em;font-weight:700;color:{pnl_color};">${total_daily_pnl:+,.0f}</div>
                </div>
                <div>
                    <div style="opacity:0.7;font-size:0.8em;">Top Mover</div>
                    <div style="font-size:1.3em;font-weight:700;color:{mover_color};">{top_mover_ticker} {top_mover_pct:+.1f}%</div>
                </div>
                <div>
                    <div style="opacity:0.7;font-size:0.8em;">API Cost</div>
                    <div style="font-size:1.3em;font-weight:700;">${self.daily_cost:.2f}</div>
                </div>
            </div>
        </div>
        """

    def generate_toc(self, sections: list[str]) -> str:
        """Generate a table of contents."""
        links = []
        for i, section in enumerate(sections, 1):
            anchor = section.lower().replace(" ", "-").replace("/", "")
            links.append(f'<a href="#{anchor}" style="color:#2563eb;text-decoration:none;">{i}. {section}</a>')

        return f"""
        <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:16px 24px;margin-bottom:24px;">
            <strong style="color:#334155;">Contents</strong><br>
            {'<br>'.join(links)}
        </div>
        """

    def generate_holdings_table(self) -> str:
        """Generate a color-coded holdings performance table with sparklines."""
        if not self.holdings_reports:
            return "<p><em>No holdings data.</em></p>"

        sorted_h = sorted(self.holdings_reports, key=lambda h: (h.get("position_pct") or 0), reverse=True)

        rows = []
        for h in sorted_h:
            ticker = h.get("ticker", "???")
            price = h.get("price")
            change_pct = h.get("change_pct")
            cumul = h.get("cumulative_return_pct")
            position_pct = h.get("position_pct") or 0
            thesis_status = h.get("thesis_status", "intact")

            # Sparkline from historical data
            sparkline = ""
            df = self.ticker_dfs.get(ticker)
            if df is not None and not df.empty:
                try:
                    recent = df["Close"].tail(20).tolist()
                    color = "#16a34a" if (change_pct or 0) >= 0 else "#dc2626"
                    sparkline = _sparkline_img_tag(recent, color=color)
                except Exception:
                    pass

            # Status badge
            status_colors = {
                "intact": "#16a34a", "strengthening": "#16a34a",
                "evolving": "#d97706", "monitoring": "#d97706",
                "weakening": "#dc2626", "invalidated": "#dc2626",
            }
            status_color = status_colors.get(thesis_status, "#6b7280")
            status_badge = f'<span style="color:{status_color};font-weight:600">{thesis_status}</span>'

            price_str = f"${price:,.2f}" if price else "N/A"

            rows.append(f"""
            <tr>
                <td style="font-weight:600;">{ticker}</td>
                <td>{price_str}</td>
                <td>{_pct_badge(change_pct)}</td>
                <td>{_pct_badge(cumul)}</td>
                <td>{position_pct:.1f}%</td>
                <td>{status_badge}</td>
                <td>{sparkline}</td>
            </tr>
            """)

        return f"""
        <table style="width:100%;border-collapse:collapse;font-size:0.9em;">
            <tr style="background:#f1f5f9;">
                <th style="padding:8px 12px;text-align:left;border-bottom:2px solid #e2e8f0;">Ticker</th>
                <th style="padding:8px 12px;text-align:right;border-bottom:2px solid #e2e8f0;">Price</th>
                <th style="padding:8px 12px;text-align:right;border-bottom:2px solid #e2e8f0;">Today</th>
                <th style="padding:8px 12px;text-align:right;border-bottom:2px solid #e2e8f0;">Total</th>
                <th style="padding:8px 12px;text-align:right;border-bottom:2px solid #e2e8f0;">Weight</th>
                <th style="padding:8px 12px;text-align:left;border-bottom:2px solid #e2e8f0;">Thesis</th>
                <th style="padding:8px 12px;text-align:center;border-bottom:2px solid #e2e8f0;">20d</th>
            </tr>
            {''.join(rows)}
        </table>
        """

    def wrap_verbose_html(self, verbose_html: str) -> str:
        """Wrap verbose report HTML with header banner and styling enhancements.

        Takes the verbose HTML from VerboseFormatter and wraps it with
        the header banner, sparkline table, and email-friendly structure.
        """
        banner = self.generate_header_banner()

        toc_sections = [
            "Executive Summary", "Market Context", "Holdings Deep Dive",
            "Strategy Memo", "Thesis Exposure", "Conviction List",
            "Moonshot Analysis", "Committee Transcript", "Delta Report",
            "Catalyst Calendar", "Track Record", "Sources", "Cost",
        ]
        toc = self.generate_toc(toc_sections)

        holdings_table = self.generate_holdings_table()

        # Extract body content from verbose HTML (strip outer html/body tags)
        import re
        body_match = re.search(r"<body>(.*)</body>", verbose_html, re.DOTALL)
        body_content = body_match.group(1) if body_match else verbose_html

        return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 900px; margin: 0 auto; padding: 20px; color: #1a1a1a; background: #fff; line-height: 1.6; }}
        h1 {{ color: #0f172a; font-size: 1.8em; }}
        h2 {{ color: #1e3a5f; border-bottom: 1px solid #e2e8f0; padding-bottom: 6px; margin-top: 2em; }}
        h3 {{ color: #334155; margin-top: 1.5em; }}
        table {{ border-collapse: collapse; width: 100%; margin: 1em 0; }}
        th {{ background: #f1f5f9; padding: 8px 12px; text-align: left; border: 1px solid #e2e8f0; }}
        td {{ padding: 6px 12px; border: 1px solid #e2e8f0; }}
        tr:nth-child(even) {{ background: #f8fafc; }}
        code {{ background: #f1f5f9; padding: 2px 6px; border-radius: 3px; font-size: 0.9em; }}
        em {{ color: #64748b; }}
    </style>
</head>
<body>
    {banner}
    {toc}
    <h2>Portfolio Performance</h2>
    {holdings_table}
    {body_content}
</body>
</html>"""
