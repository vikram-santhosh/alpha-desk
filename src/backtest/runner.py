"""Backtest runner — orchestrates multi-day pipeline replay.

Loops over trading days, runs the pipeline per day (with historical data),
captures signals, computes forward-looking outcomes, and generates reports.
"""
from __future__ import annotations

import asyncio
import time
from datetime import date
from typing import Any

from src.backtest.data_replay import (
    build_historical_up_to_day,
    build_macro_for_day,
    build_prices_for_day,
    fetch_all_historical_data,
    get_macro_symbols,
    get_trading_days,
)
from src.backtest.db_isolation import TempDBContext
from src.backtest.outcome_tracker import (
    build_agent_metrics,
    build_overall_metrics,
    compute_forward_returns,
    score_signal,
)
from src.backtest.report_generator import BacktestReportGenerator, _sanitize_for_json
from src.backtest.signal_capture import SignalCapture
from src.utils.logger import get_logger

log = get_logger(__name__)

THICK_SEP = "\u2501" * 50
THIN_SEP = "\u2500" * 50


class BacktestRunner:
    """Orchestrates a multi-day backtest of the AlphaDesk pipeline."""

    def __init__(
        self,
        num_days: int = 5,
        skip_committee: bool = False,
        skip_agents: list[str] | None = None,
        dry_run: bool = False,
        output_dir: str | None = None,
        portfolio_config: str | None = None,
    ):
        self.num_days = num_days
        self.skip_committee = skip_committee
        self.skip_agents = skip_agents or ["street_ear", "news_desk"]
        self.dry_run = dry_run
        self.output_dir = output_dir
        self.portfolio_config = portfolio_config

    def _load_config(self) -> dict:
        """Load advisor config (with private portfolio merge)."""
        from pathlib import Path
        from src.shared.config_loader import load_config

        if self.portfolio_config:
            import yaml
            with open(self.portfolio_config) as f:
                config = yaml.safe_load(f) or {}
            # Merge with advisor.yaml defaults
            try:
                advisor_config = load_config("advisor")
                for key in advisor_config:
                    if key not in config:
                        config[key] = advisor_config[key]
            except Exception:
                pass
            return config

        config = load_config("advisor")
        private_path = Path("private/portfolio.yaml")
        if private_path.exists():
            try:
                import yaml
                with open(private_path) as f:
                    private = yaml.safe_load(f) or {}
                if "holdings" in private:
                    config["holdings"] = private["holdings"]
                for key in ("macro_theses", "superinvestors"):
                    if key in private:
                        config[key] = private[key]
            except Exception:
                pass
        return config

    async def run(self) -> dict[str, Any]:
        """Run the full backtest and return results dict."""
        overall_start = time.time()

        print(f"\n{THICK_SEP}")
        print("  ALPHADESK BACKTEST")
        print(f"{THICK_SEP}\n")

        # Load config
        config = self._load_config()
        tickers = [h["ticker"] for h in config.get("holdings", [])]
        tickers = list(dict.fromkeys(tickers))
        macro_symbols = get_macro_symbols()
        print(f"  Tickers: {', '.join(tickers[:12])}{'...' if len(tickers) > 12 else ''}")
        print(f"  Skip committee: {self.skip_committee}")
        print(f"  Skip agents: {', '.join(self.skip_agents)}")

        # Get trading days
        print(f"\n  Finding last {self.num_days} trading days...")
        trading_days = get_trading_days(self.num_days)
        print(f"  Trading days: {' | '.join(d.strftime('%a %b %d') for d in trading_days)}")

        # Pre-fetch data
        print(f"\n  Pre-fetching historical data...")
        fetch_start = time.time()
        ticker_dfs = fetch_all_historical_data(tickers, macro_symbols, trading_days)
        print(f"  Fetched in {time.time() - fetch_start:.1f}s")

        # Fetch fundamentals once
        print("\n  Fetching fundamentals (one-time)...")
        from src.portfolio_analyst.fundamental_analyzer import fetch_all_fundamentals
        try:
            fundamentals = fetch_all_fundamentals(tickers)
            print(f"  Got fundamentals for {len(fundamentals)} tickers")
        except Exception as e:
            print(f"  Warning: Fundamentals fetch failed: {e}")
            fundamentals = {}

        # Fetch earnings once
        earnings_data: dict = {}
        try:
            from src.advisor.earnings_analyzer import run_earnings_analysis
            earnings_data = run_earnings_analysis(tickers)
        except Exception:
            pass

        # Fetch superinvestor data once
        superinvestor_data: dict = {}
        try:
            from src.advisor.superinvestor_tracker import run_superinvestor_tracking
            raw_si = run_superinvestor_tracking(tickers, config)
            superinvestor_data = raw_si.get("smart_money_summaries", {}) if isinstance(raw_si, dict) else {}
        except Exception:
            pass

        # Patch budget check
        import src.shared.cost_tracker as cost_mod
        _original_check_budget = cost_mod.check_budget
        cost_mod.check_budget = lambda: (True, 0.0, 50.0)

        try:
            import src.advisor.analyst_committee as committee_mod
            committee_mod.check_budget = lambda: (True, 0.0, 50.0)
        except Exception:
            pass
        try:
            import src.advisor.conviction_manager as conviction_mod
            conviction_mod.check_budget = lambda: (True, 0.0, 50.0)
        except Exception:
            pass
        try:
            import src.advisor.moonshot_manager as moonshot_mod
            moonshot_mod.check_budget = lambda: (True, 0.0, 50.0)
        except Exception:
            pass

        # Run backtest
        results: list[dict] = []
        all_signals: list[dict] = []
        day_costs: list[float] = []

        with TempDBContext():
            for i, day in enumerate(trading_days):
                prev_day = trading_days[i - 1] if i > 0 else None
                try:
                    result, day_signals = await self._run_day(
                        day_num=i + 1,
                        day=day,
                        prev_day=prev_day,
                        config=config,
                        tickers=tickers,
                        ticker_dfs=ticker_dfs,
                        fundamentals=fundamentals,
                        earnings_data=earnings_data,
                        superinvestor_data=superinvestor_data,
                        day_costs=day_costs,
                    )
                    results.append(result)
                    all_signals.extend(day_signals)
                except Exception as e:
                    print(f"\n  DAY {i+1} FAILED: {e}")
                    import traceback
                    traceback.print_exc()
                    day_costs.append(day_costs[-1] if day_costs else 0)

        # Restore budget
        cost_mod.check_budget = _original_check_budget

        # Score all signals with forward-looking returns
        print(f"\n{THIN_SEP}")
        print("  SCORING SIGNALS")
        print(f"{THIN_SEP}")

        scored_signals: list[dict] = []
        for sig_dict in all_signals:
            from src.backtest.signal_capture import CapturedSignal
            sig = CapturedSignal(**sig_dict)
            try:
                sig_date = date.fromisoformat(sig.date)
            except ValueError:
                continue
            returns = compute_forward_returns(sig.ticker, sig_date, ticker_dfs)
            scored = score_signal(sig, returns)
            scored_signals.append(scored)

        agent_metrics = build_agent_metrics(scored_signals)
        overall_metrics = build_overall_metrics(scored_signals)

        print(f"  Total signals: {overall_metrics.get('total_signals', 0)}")
        print(f"  Hit rate (7d): {overall_metrics.get('overall_hit_rate', 0):.1f}%")
        for agent, m in sorted(agent_metrics.items()):
            print(f"  {agent}: {m['total_signals']} signals, {m['hit_rate']:.1f}% hit rate")

        # Generate reports
        total_time = time.time() - overall_start
        report_gen = BacktestReportGenerator(output_dir=self.output_dir)
        json_path = report_gen.write_results_json(results, scored_signals, agent_metrics, overall_metrics)
        csv_path = report_gen.write_signals_csv(scored_signals)
        md_path = report_gen.write_summary_md(results, agent_metrics, overall_metrics, tickers, total_time)

        print(f"\n{THICK_SEP}")
        print("  BACKTEST COMPLETE")
        print(f"{THICK_SEP}")
        print(f"  Days: {len(results)}/{self.num_days}")
        print(f"  Signals: {len(scored_signals)}")
        print(f"  Cost: ${sum(r.get('cost', 0) for r in results):.2f}")
        print(f"  Time: {total_time:.1f}s")
        print(f"\n  Results: {json_path}")
        print(f"  Summary: {md_path}")
        print(f"  Signals: {csv_path}")

        return {
            "day_results": results,
            "scored_signals": scored_signals,
            "agent_metrics": agent_metrics,
            "overall_metrics": overall_metrics,
            "output_dir": str(report_gen.output_dir),
        }

    async def _run_day(
        self,
        day_num: int,
        day: date,
        prev_day: date | None,
        config: dict,
        tickers: list[str],
        ticker_dfs: dict,
        fundamentals: dict,
        earnings_data: dict,
        superinvestor_data: dict,
        day_costs: list[float],
    ) -> tuple[dict, list[dict]]:
        """Run a single day of the backtest. Returns (day_result, signals_list)."""
        day_start = time.time()
        day_str = day.strftime("%A %b %d, %Y")
        print(f"\n{THICK_SEP}")
        print(f"  DAY {day_num}: {day_str}")
        print(f"{THICK_SEP}\n")

        signal_capture = SignalCapture(day)

        # 1. Build price data
        prices = build_prices_for_day(ticker_dfs, tickers, day, prev_day)

        # 2. Build macro data
        macro_data = build_macro_for_day(ticker_dfs, day, prev_day)

        # 3. Build truncated historical
        historical = build_historical_up_to_day(ticker_dfs, tickers, day)

        # 4. Technical analysis
        from src.portfolio_analyst.technical_analyzer import analyze_all as run_technical_analysis
        try:
            technicals = run_technical_analysis(tickers, historical)
        except Exception:
            technicals = {}

        # 5. Holdings monitor
        from src.advisor.memory import seed_holdings, seed_macro_theses, build_memory_context, update_holding
        from src.advisor.holdings_monitor import monitor_holdings

        seed_holdings(config.get("holdings", []))
        seed_macro_theses(config.get("macro_theses", []))
        for h in config.get("holdings", []):
            if h.get("entry_price"):
                try:
                    update_holding(h["ticker"], entry_price=h["entry_price"])
                except Exception:
                    pass

        memory = build_memory_context()
        config_holdings_map = {h["ticker"]: h for h in config.get("holdings", [])}
        for h in memory["holdings"]:
            cfg = config_holdings_map.get(h["ticker"], {})
            if cfg.get("shares"):
                h["shares"] = cfg["shares"]
            if cfg.get("entry_price") and not h.get("entry_price"):
                h["entry_price"] = cfg["entry_price"]

        try:
            holdings_reports = monitor_holdings(
                holdings=memory["holdings"], prices=prices,
                fundamentals=fundamentals, signals=[], news_signals=[],
            )
        except Exception as e:
            print(f"  Warning: Holdings monitor failed: {e}")
            holdings_reports = []

        # 6. Delta engine
        from src.advisor.delta_engine import build_snapshot, compute_deltas, generate_delta_summary, format_delta_for_prompt
        from src.advisor.memory import get_latest_snapshot_before, save_daily_snapshot

        delta_report = None
        delta_prompt_section = ""
        try:
            today_snapshot = build_snapshot(
                holdings_reports=holdings_reports, fundamentals=fundamentals,
                technicals=technicals, macro_data=macro_data,
                conviction_list=memory.get("conviction_list", []),
                moonshot_list=memory.get("moonshot_list", []),
                strategy={}, earnings_data=earnings_data if isinstance(earnings_data, dict) else {},
                superinvestor_data=superinvestor_data,
            )
            today_snapshot = _sanitize_for_json(today_snapshot)
            save_daily_snapshot(day.isoformat(), today_snapshot)
        except Exception:
            today_snapshot = {}

        try:
            yesterday_snapshot = get_latest_snapshot_before(day.isoformat())
            delta_report = compute_deltas(today_snapshot, yesterday_snapshot)
            delta_report.date = day.isoformat()
            delta_report.summary = generate_delta_summary(delta_report)
            delta_prompt_section = format_delta_for_prompt(delta_report)
            signal_capture.capture_delta_signals(delta_report)
            print(f"  Delta: {len(delta_report.high_significance)} high, {len(delta_report.medium_significance)} med")
        except Exception:
            pass

        # 7. Decision engine
        from src.advisor.valuation_engine import compute_target_price
        from src.advisor.conviction_manager import update_conviction_list
        from src.advisor.moonshot_manager import update_moonshot_list
        from src.advisor.strategy_engine import generate_strategy

        valuation_data = {}
        for ticker in tickers:
            try:
                fund = fundamentals.get(ticker, {})
                earn = earnings_data.get("per_ticker", {}).get(ticker) if isinstance(earnings_data, dict) else None
                val_result = compute_target_price(ticker, fund, earn)
                if not val_result.get("insufficient_data"):
                    val_result["pe_trailing"] = fund.get("pe_trailing")
                    val_result["pe_forward"] = fund.get("pe_forward")
                valuation_data[ticker] = val_result
            except Exception:
                pass

        conviction_result = {"current_list": [], "added": [], "removed": []}
        try:
            conviction_result = update_conviction_list(
                candidates=[], superinvestor_data=superinvestor_data,
                earnings_data=earnings_data if isinstance(earnings_data, dict) else {},
                prediction_data=[], valuation_data=valuation_data, config=config,
            )
            signal_capture.capture_conviction_changes(conviction_result)
        except Exception as e:
            print(f"  Warning: Conviction update failed: {e}")

        moonshot_result = {"current_list": [], "added": [], "removed": []}
        try:
            moonshot_result = update_moonshot_list(
                candidates=[], config=config, prediction_data=[],
                earnings_data=earnings_data if isinstance(earnings_data, dict) else {},
                valuation_data=valuation_data,
            )
            signal_capture.capture_moonshot_changes(moonshot_result)
        except Exception as e:
            print(f"  Warning: Moonshot update failed: {e}")

        updated_theses = memory.get("macro_theses", [])
        strategy = {"actions": [], "flags": [], "summary": "", "thesis_exposure": []}
        try:
            strategy = generate_strategy(
                holdings_reports=holdings_reports, macro_theses=updated_theses,
                valuation_data=valuation_data, config=config,
            )
            signal_capture.capture_strategy_actions(strategy)
            print(f"  Strategy: {len(strategy.get('actions', []))} actions")
        except Exception as e:
            print(f"  Warning: Strategy failed: {e}")

        # 8. Analyst committee (optional)
        brief_text = ""
        if not self.skip_committee:
            try:
                from src.advisor.analyst_committee import run_analyst_committee

                _data_context = {
                    "fundamentals": fundamentals,
                    "holdings_reports": holdings_reports,
                    "valuation_data": valuation_data,
                    "macro_data": macro_data,
                    "strategy": strategy,
                }
                _macro_ctx = "\n".join(
                    f"- {t.get('title')}: {t.get('status', 'intact')}"
                    for t in updated_theses
                ) or "No macro theses."
                _holdings_ctx = "\n".join(
                    f"- {h.get('ticker')}: ${h.get('price', 'N/A')} ({(h.get('change_pct') or 0):+.1f}%)"
                    for h in holdings_reports
                ) or "No holdings data."

                committee_result = await run_analyst_committee(
                    tickers=tickers[:12], data_context=_data_context,
                    delta_summary=delta_prompt_section,
                    macro_context=_macro_ctx, holdings_context=_holdings_ctx,
                )
                brief_text = committee_result.get("formatted_brief", "")
                print(f"  Committee: {'OK' if brief_text else 'FAIL'}")
            except Exception as e:
                print(f"  Committee failed: {e}")
        else:
            print("  Committee: SKIPPED")

        # 9. Save brief to memory for next day
        try:
            from src.advisor.memory import save_daily_brief
            save_daily_brief(
                macro_summary=brief_text[:500] if brief_text else "No brief.",
                portfolio_actions=strategy.get("actions", []),
                conviction_changes=conviction_result.get("added", []) + conviction_result.get("removed", []),
                moonshot_changes=moonshot_result.get("added", []) + moonshot_result.get("removed", []),
            )
        except Exception:
            pass

        # Cost tracking
        from src.shared.cost_tracker import get_daily_cost
        daily_cost = get_daily_cost()
        prev_cost = day_costs[-1] if day_costs else 0
        day_cost = daily_cost - prev_cost
        day_costs.append(daily_cost)

        elapsed = time.time() - day_start
        print(f"  Cost: ${day_cost:.2f} | Time: {elapsed:.1f}s")

        day_result = {
            "day": day.isoformat(),
            "day_str": day_str,
            "prices": {t: prices.get(t, {}).get("price") for t in tickers if prices.get(t, {}).get("price")},
            "delta_high": len(delta_report.high_significance) if delta_report else 0,
            "delta_med": len(delta_report.medium_significance) if delta_report else 0,
            "delta_low": len(delta_report.low_significance) if delta_report else 0,
            "brief_length": len(brief_text),
            "cost": day_cost,
            "time_s": round(elapsed, 1),
            "committee_ok": bool(brief_text),
            "conviction_count": len(conviction_result.get("current_list", [])),
            "conviction_added": len(conviction_result.get("added", [])),
            "moonshot_count": len(moonshot_result.get("current_list", [])),
            "moonshot_added": len(moonshot_result.get("added", [])),
            "strategy_actions": len(strategy.get("actions", [])),
            "thesis_exposures": len(strategy.get("thesis_exposure", [])),
        }

        return day_result, signal_capture.to_dicts()
