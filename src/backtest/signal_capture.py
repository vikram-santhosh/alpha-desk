"""Signal capture for backtesting.

Hooks into the pipeline to capture every signal and recommendation
with date, agent, ticker, type, conviction, and reasoning.
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from src.utils.logger import get_logger

log = get_logger(__name__)


@dataclass
class CapturedSignal:
    """A single captured signal from the pipeline."""
    date: str = ""
    agent: str = ""
    ticker: str = ""
    signal_type: str = ""  # "bullish", "bearish", "neutral", "buy", "trim", "hold"
    conviction: str = ""   # "high", "medium", "low"
    reasoning: str = ""
    source: str = ""       # "strategy_engine", "conviction_manager", "delta_engine", etc.
    raw_data: dict = field(default_factory=dict)


class SignalCapture:
    """Captures signals from a single day's pipeline run."""

    def __init__(self, run_date: date):
        self.run_date = run_date
        self.signals: list[CapturedSignal] = []

    def capture_strategy_actions(self, strategy: dict) -> None:
        """Capture signals from the strategy engine output."""
        for action in strategy.get("actions", []):
            action_type = action.get("action", "hold").lower()
            signal_type = "bullish" if action_type in ("add", "buy") else "bearish" if action_type in ("trim", "sell") else "neutral"
            self.signals.append(CapturedSignal(
                date=self.run_date.isoformat(),
                agent="strategy_engine",
                ticker=action.get("ticker", ""),
                signal_type=signal_type,
                conviction=action.get("urgency", "medium"),
                reasoning=action.get("reason", ""),
                source="strategy_engine",
                raw_data=action,
            ))

    def capture_conviction_changes(self, conviction_result: dict) -> None:
        """Capture conviction list additions/removals."""
        for added in conviction_result.get("added", []):
            self.signals.append(CapturedSignal(
                date=self.run_date.isoformat(),
                agent="conviction_manager",
                ticker=added.get("ticker", ""),
                signal_type="bullish",
                conviction=added.get("conviction", "medium"),
                reasoning=added.get("thesis", ""),
                source="conviction_pipeline",
                raw_data=added,
            ))
        for removed in conviction_result.get("removed", []):
            self.signals.append(CapturedSignal(
                date=self.run_date.isoformat(),
                agent="conviction_manager",
                ticker=removed.get("ticker", ""),
                signal_type="bearish",
                conviction="medium",
                reasoning=removed.get("removal_reason", removed.get("reason", "")),
                source="conviction_pipeline",
                raw_data=removed,
            ))

    def capture_moonshot_changes(self, moonshot_result: dict) -> None:
        """Capture moonshot list additions."""
        for added in moonshot_result.get("added", []):
            self.signals.append(CapturedSignal(
                date=self.run_date.isoformat(),
                agent="moonshot_manager",
                ticker=added.get("ticker", ""),
                signal_type="bullish",
                conviction=added.get("conviction", "low"),
                reasoning=added.get("thesis", ""),
                source="moonshot_pipeline",
                raw_data=added,
            ))

    def capture_delta_signals(self, delta_report: Any) -> None:
        """Capture high-significance delta items as signals."""
        if not delta_report:
            return

        high_items = []
        if hasattr(delta_report, "high_significance"):
            high_items = delta_report.high_significance
        elif isinstance(delta_report, dict):
            high_items = delta_report.get("high_significance", [])

        for item in high_items:
            ticker = getattr(item, "ticker_or_key", "") if hasattr(item, "ticker_or_key") else item.get("ticker_or_key", "")
            narrative = getattr(item, "narrative", "") if hasattr(item, "narrative") else item.get("narrative", "")
            delta_pct = getattr(item, "delta_pct", None) if hasattr(item, "delta_pct") else item.get("delta_pct")

            signal_type = "neutral"
            if delta_pct is not None:
                signal_type = "bullish" if delta_pct > 0 else "bearish"

            self.signals.append(CapturedSignal(
                date=self.run_date.isoformat(),
                agent="delta_engine",
                ticker=ticker,
                signal_type=signal_type,
                conviction="high",
                reasoning=narrative,
                source="delta_engine",
            ))

    def to_dicts(self) -> list[dict]:
        """Convert all captured signals to dicts for serialization."""
        return [
            {
                "date": s.date,
                "agent": s.agent,
                "ticker": s.ticker,
                "signal_type": s.signal_type,
                "conviction": s.conviction,
                "reasoning": s.reasoning,
                "source": s.source,
            }
            for s in self.signals
        ]
