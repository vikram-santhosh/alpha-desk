"""Backtest report generator.

Writes results.json, summary.md, and signals.csv to backtests/{run_date}/.
"""

import csv
import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

from src.utils.logger import get_logger

log = get_logger(__name__)


def _sanitize_for_json(obj: Any) -> Any:
    """Recursively convert numpy types to Python natives for JSON serialization."""
    try:
        import numpy as np
        if isinstance(obj, dict):
            return {k: _sanitize_for_json(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_sanitize_for_json(v) for v in obj]
        if isinstance(obj, (np.bool_,)):
            return bool(obj)
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
    except ImportError:
        pass
    return obj


class BacktestReportGenerator:
    """Generates backtest reports in multiple formats."""

    def __init__(self, output_dir: str | None = None):
        if output_dir:
            self.output_dir = Path(output_dir)
        else:
            self.output_dir = Path("backtests") / date.today().isoformat()
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def write_results_json(
        self,
        day_results: list[dict],
        scored_signals: list[dict],
        agent_metrics: dict[str, dict],
        overall_metrics: dict,
        config: dict | None = None,
    ) -> str:
        """Write the full results JSON file."""
        data = _sanitize_for_json({
            "backtest_date": date.today().isoformat(),
            "generated_at": datetime.now().isoformat(),
            "config": {
                "days": len(day_results),
                "tickers": list({t for d in day_results for t in d.get("prices", {}).keys()}),
            },
            "day_results": day_results,
            "scored_signals": scored_signals,
            "agent_metrics": agent_metrics,
            "overall_metrics": overall_metrics,
        })

        path = self.output_dir / "results.json"
        with open(path, "w") as f:
            json.dump(data, f, indent=2, default=str)

        log.info("Wrote results.json: %s", path)
        return str(path)

    def write_signals_csv(self, scored_signals: list[dict]) -> str:
        """Write signals to CSV for easy analysis."""
        path = self.output_dir / "signals.csv"

        if not scored_signals:
            path.write_text("date,agent,ticker,signal_type,conviction,return_1d,return_3d,return_7d,classification_7d,reasoning\n")
            log.info("Wrote empty signals.csv: %s", path)
            return str(path)

        fieldnames = [
            "date", "agent", "ticker", "signal_type", "conviction",
            "return_1d", "return_3d", "return_7d", "classification_7d", "reasoning",
        ]

        with open(path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for s in scored_signals:
                writer.writerow(s)

        log.info("Wrote signals.csv: %d signals to %s", len(scored_signals), path)
        return str(path)

    def write_summary_md(
        self,
        day_results: list[dict],
        agent_metrics: dict[str, dict],
        overall_metrics: dict,
        tickers: list[str],
        total_time: float,
    ) -> str:
        """Write a human-readable Markdown summary."""
        lines = [
            f"# AlphaDesk Backtest Summary — {date.today().isoformat()}\n",
            f"**Days:** {len(day_results)}  ",
            f"**Tickers:** {len(tickers)}  ",
            f"**Total Time:** {total_time:.1f}s  ",
            f"**Total Cost:** ${sum(r.get('cost', 0) for r in day_results):.2f}\n",
        ]

        # Price performance table
        lines.append("## Price Performance\n")
        if day_results:
            header = "| Ticker |"
            separator = "|--------|"
            for r in day_results:
                day_label = r.get("day", "?")
                header += f" {day_label} |"
                separator += "---------|"
            header += " Week |"
            separator += "------|"
            lines.append(header)
            lines.append(separator)

            for ticker in tickers[:15]:
                row = f"| {ticker} |"
                first_price = None
                last_price = None
                for r in day_results:
                    p = r.get("prices", {}).get(ticker)
                    if p is not None:
                        if first_price is None:
                            first_price = p
                        last_price = p
                        row += f" ${p:.2f} |"
                    else:
                        row += " N/A |"
                if first_price and last_price:
                    week_chg = (last_price - first_price) / first_price * 100
                    row += f" {week_chg:+.1f}% |"
                else:
                    row += " N/A |"
                lines.append(row)

        # Delta summary
        lines.append("\n## Delta Engine Summary\n")
        lines.append("| Day | High | Medium | Low | Total |")
        lines.append("|-----|------|--------|-----|-------|")
        for r in day_results:
            h, m, l = r.get("delta_high", 0), r.get("delta_med", 0), r.get("delta_low", 0)
            lines.append(f"| {r.get('day', '?')} | {h} | {m} | {l} | {h+m+l} |")

        # Decision engine summary
        lines.append("\n## Decision Engine Summary\n")
        lines.append("| Day | Conviction | +Added | Moonshot | +Added | Actions | Theses |")
        lines.append("|-----|------------|--------|----------|--------|---------|--------|")
        for r in day_results:
            lines.append(
                f"| {r.get('day', '?')} | {r.get('conviction_count', 0)} | "
                f"{r.get('conviction_added', 0)} | {r.get('moonshot_count', 0)} | "
                f"{r.get('moonshot_added', 0)} | {r.get('strategy_actions', 0)} | "
                f"{r.get('thesis_exposures', 0)} |"
            )

        # Signal metrics
        lines.append("\n## Signal Metrics\n")
        if overall_metrics.get("total_signals", 0) > 0:
            om = overall_metrics
            lines.append(f"**Total Signals:** {om['total_signals']}  ")
            lines.append(f"**Bullish Signals:** {om.get('bullish_signals', 0)}  ")
            lines.append(f"**Overall Hit Rate (7d):** {om.get('overall_hit_rate', 0):.1f}%  ")
            lines.append(f"**Avg Return 1d:** {om.get('avg_return_1d', 'N/A')}%  ")
            lines.append(f"**Avg Return 7d:** {om.get('avg_return_7d', 'N/A')}%\n")
        else:
            lines.append("*No signals captured.*\n")

        # Per-agent metrics
        if agent_metrics:
            lines.append("### Per-Agent Performance\n")
            lines.append("| Agent | Signals | Hit Rate | Avg 7d | FP Rate | TP | FP | TN | FN |")
            lines.append("|-------|---------|----------|--------|---------|----|----|----|----|")
            for agent, m in sorted(agent_metrics.items()):
                cm = m.get("confusion_matrix", {})
                avg_7d = m.get("avg_return_7d")
                avg_str = f"{avg_7d}%" if avg_7d is not None else "N/A"
                lines.append(
                    f"| {agent} | {m['total_signals']} | {m['hit_rate']:.1f}% | "
                    f"{avg_str} | {m['false_positive_rate']:.1f}% | "
                    f"{cm.get('TP', 0)} | {cm.get('FP', 0)} | {cm.get('TN', 0)} | {cm.get('FN', 0)} |"
                )

        # Pipeline stats
        lines.append("\n## Pipeline Stats\n")
        total_cost = sum(r.get("cost", 0) for r in day_results)
        briefs_ok = sum(1 for r in day_results if r.get("committee_ok"))
        lines.append(f"- Days processed: {len(day_results)}")
        lines.append(f"- Briefs generated: {briefs_ok}/{len(day_results)}")
        lines.append(f"- Total cost: ${total_cost:.2f}")
        lines.append(f"- Avg cost/day: ${total_cost / max(len(day_results), 1):.2f}")
        lines.append(f"- Total time: {total_time:.1f}s")

        lines.append(f"\n*Generated by AlphaDesk Backtest on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*")

        md_text = "\n".join(lines)
        path = self.output_dir / "summary.md"
        path.write_text(md_text, encoding="utf-8")

        log.info("Wrote summary.md: %s", path)
        return str(path)
