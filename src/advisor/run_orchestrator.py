"""Multi-run orchestration for AlphaDesk morning, evening, and weekend executions."""
from __future__ import annotations

import asyncio
import time
from datetime import date
from typing import Any

from src.shared import gemini_compat as anthropic
from src.shared.agent_bus import consume, consume_since, get_latest_signal_id
from src.shared.cost_tracker import get_daily_cost, get_run_cost, reset_run_context, set_run_context
from src.shared.prompt_loader import load_prompt
from src.utils.logger import get_logger

from src.advisor.run_profile import RunProfile, determine_run_profile
from src.shared.agent_decorator import track_agent
from src.shared.citations import CitationRegistry

log = get_logger(__name__)

DELTA_MODEL = "claude-haiku-4-5"


def _call_model(prompt: str, *, model: str, max_tokens: int) -> dict[str, Any]:
    client = anthropic.Anthropic()
    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    return {"text": response.content[0].text.strip(), "usage": response.usage, "model": model}


class RunOrchestrator:
    async def execute(self, run_type: str = "auto") -> dict[str, Any]:
        profile = determine_run_profile(run_type)
        context_tokens = set_run_context(run_id=profile.run_id, run_budget=profile.budget_usd)
        try:
            if profile.run_type == "morning_full":
                from src.advisor.main import _run_pipeline

                return await _run_pipeline(profile)
            if profile.run_type == "evening_wrap":
                return await self._execute_evening_wrap(profile)
            return await self._execute_weekend_review(profile)
        finally:
            reset_run_context(context_tokens)

    async def _execute_evening_wrap(self, profile: RunProfile) -> dict[str, Any]:
        started = time.time()
        config = self._load_config()
        memory = self._load_memory(config)
        holdings = memory.get("holdings", [])
        tickers = [holding["ticker"] for holding in holdings]

        from src.news_desk.main import run as run_news_desk
        from src.portfolio_analyst.price_fetcher import fetch_current_prices
        from src.advisor.holdings_monitor import monitor_holdings
        from src.advisor.delta_engine import build_snapshot, compute_deltas, generate_delta_summary
        from src.advisor.formatter import format_evening_wrap
        from src.advisor.memory import get_latest_run_snapshot, save_run_snapshot

        morning_snapshot = get_latest_run_snapshot(run_type="morning_full", date_str=date.today().isoformat())
        since_id = int((morning_snapshot or {}).get("last_consumed_signal_id") or 0)

        news_result, prices = await asyncio.gather(
            run_news_desk(headlines_only=True),
            asyncio.to_thread(fetch_current_prices, tickers),
        )
        bus_signals = consume_since(since_id, mark_consumed=False) if since_id else consume(mark_consumed=False)
        news_signals = self._news_signals(news_result, bus_signals)
        holdings_reports = monitor_holdings(
            holdings=holdings,
            prices=prices,
            fundamentals={},
            signals=bus_signals,
            news_signals=news_signals,
        )

        snapshot = build_snapshot(
            holdings_reports=holdings_reports,
            fundamentals={},
            technicals={},
            macro_data={},
            conviction_list=memory.get("conviction_list", []),
            moonshot_list=memory.get("moonshot_list", []),
            strategy={},
        )
        reference_snapshot = (morning_snapshot or {}).get("snapshot_data")
        delta_report = compute_deltas(snapshot, reference_snapshot)
        delta_report.summary = await asyncio.to_thread(generate_delta_summary, delta_report)

        citations = CitationRegistry()
        for article in news_result.get("top_articles", [])[:10]:
            citations.register(
                article.get("url", ""),
                article.get("title", "Untitled"),
                article.get("origin", article.get("source", "news_desk")),
                article.get("published_at", ""),
            )

        morning_brief = ""
        if morning_snapshot:
            morning_brief = str((morning_snapshot.get("snapshot_data") or {}).get("brief_text", ""))
        delta_analysis = await self._run_delta_analyst(
            morning_brief=morning_brief,
            delta_summary=delta_report.summary,
            holdings_context=self._format_holdings_context(holdings_reports),
            news_context="\n".join(self._news_lines(news_result.get("top_articles", []))),
            citations=citations.format_for_prompt(),
        )
        raw_text = delta_analysis.get("raw_text", "")
        parsed = self._parse_numbered_sections(raw_text)

        catalyst_items = await self._load_catalysts(tickers)
        movers = self._build_movers(holdings_reports, news_result.get("top_articles", []))
        after_hours = [article.get("title", "") for article in news_result.get("top_articles", [])[:3] if article.get("title")]

        formatted = format_evening_wrap(
            run_id=profile.run_id,
            scorecard=parsed.get("scorecard", raw_text[:240]),
            delta_summary=parsed.get("what changed", delta_report.summary),
            movers=movers,
            tomorrow_catalysts=catalyst_items,
            after_hours=after_hours,
        )

        total_time = time.time() - started
        run_cost = get_run_cost(profile.run_id)
        snapshot["brief_text"] = formatted
        save_run_snapshot(
            run_id=profile.run_id,
            run_type=profile.run_type,
            date_str=date.today().isoformat(),
            snapshot_data=snapshot,
            delta=delta_report.to_dict(),
            run_cost=run_cost,
            run_duration=round(total_time, 1),
            last_signal_id=get_latest_signal_id(),
            mirror_to_daily=False,
        )

        return {
            "formatted": formatted,
            "signals": bus_signals,
            "run_profile": {
                "run_id": profile.run_id,
                "run_type": profile.run_type,
                "report_format": profile.report_format,
                "budget_usd": profile.budget_usd,
                "hours_since_last_run": profile.hours_since_last_run,
            },
            "stats": {
                "total_time_s": round(total_time, 1),
                "daily_cost": get_daily_cost(),
                "run_cost": run_cost,
                "holdings_count": len(holdings_reports),
                "actions_count": 0,
            },
            "sections": {
                "holdings": holdings_reports,
                "delta_report": delta_report.to_dict(),
                "committee": {"formatted_brief": raw_text, "citations": citations.as_list()},
            },
        }

    async def _execute_weekend_review(self, profile: RunProfile) -> dict[str, Any]:
        started = time.time()
        config = self._load_config()
        memory = self._load_memory(config)

        from src.advisor.formatter import format_weekend_review
        from src.advisor.memory import list_run_snapshots, save_run_snapshot

        recent_runs = list_run_snapshots(limit=8)
        thesis_changes = self._compute_thesis_changes(recent_runs)
        week_in_review = self._summarize_recent_runs(recent_runs)
        next_week_preview = [
            catalyst.get("description", "")
            for catalyst in await self._load_catalysts([holding["ticker"] for holding in memory.get("holdings", [])])
        ]

        formatted = format_weekend_review(
            run_id=profile.run_id,
            thesis_changes=thesis_changes,
            week_in_review=week_in_review,
            next_week_preview=next_week_preview,
        )
        total_time = time.time() - started
        run_cost = get_run_cost(profile.run_id)

        save_run_snapshot(
            run_id=profile.run_id,
            run_type=profile.run_type,
            date_str=date.today().isoformat(),
            snapshot_data={"brief_text": formatted, "recent_runs": recent_runs[:5]},
            delta=None,
            run_cost=run_cost,
            run_duration=round(total_time, 1),
            last_signal_id=get_latest_signal_id(),
            mirror_to_daily=False,
        )

        return {
            "formatted": formatted,
            "signals": [],
            "run_profile": {
                "run_id": profile.run_id,
                "run_type": profile.run_type,
                "report_format": profile.report_format,
                "budget_usd": profile.budget_usd,
                "hours_since_last_run": profile.hours_since_last_run,
            },
            "stats": {
                "total_time_s": round(total_time, 1),
                "daily_cost": get_daily_cost(),
                "run_cost": run_cost,
                "holdings_count": len(memory.get("holdings", [])),
                "actions_count": 0,
            },
            "sections": {
                "committee": {"formatted_brief": formatted},
            },
        }

    def _load_config(self) -> dict[str, Any]:
        from src.advisor.main import _load_advisor_config

        return _load_advisor_config()

    def _load_memory(self, config: dict[str, Any]) -> dict[str, Any]:
        from src.advisor.memory import build_memory_context, seed_holdings, seed_macro_theses, update_holding

        seed_holdings(config.get("holdings", []))
        seed_macro_theses(config.get("macro_theses", []))
        for holding in config.get("holdings", []):
            if holding.get("entry_price"):
                try:
                    update_holding(holding["ticker"], entry_price=holding["entry_price"])
                except Exception:
                    log.debug("Could not sync entry price for %s", holding.get("ticker"))

        memory = build_memory_context()
        config_holdings = {holding["ticker"]: holding for holding in config.get("holdings", [])}
        for holding in memory.get("holdings", []):
            cfg = config_holdings.get(holding["ticker"], {})
            if cfg.get("shares"):
                holding["shares"] = cfg["shares"]
            if cfg.get("entry_price") and not holding.get("entry_price"):
                holding["entry_price"] = cfg["entry_price"]
        return memory

    @track_agent("delta_analyst")
    async def _run_delta_analyst(
        self,
        *,
        morning_brief: str,
        delta_summary: str,
        holdings_context: str,
        news_context: str,
        citations: str,
    ) -> dict[str, Any]:
        prompt = load_prompt(
            "delta_analyst",
            morning_brief=morning_brief or "No morning brief available.",
            delta_summary=delta_summary,
            holdings_context=holdings_context,
            news_context=news_context,
            citations=citations,
        )
        return await asyncio.to_thread(_call_model, prompt, model=DELTA_MODEL, max_tokens=1600)

    def _news_signals(self, news_result: dict[str, Any], bus_signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
        news_signals = []
        for article in news_result.get("top_articles", []):
            related = article.get("related_tickers", [])
            news_signals.append(
                {
                    "headline": article.get("title", ""),
                    "source": article.get("source", ""),
                    "tickers": related,
                    "ticker": related[0] if related else "",
                    "summary": article.get("summary", ""),
                    "category": article.get("category", ""),
                    "sentiment": article.get("sentiment", 0),
                }
            )
        for signal in bus_signals:
            if signal.get("signal_type") == "macro_event":
                payload = signal.get("payload", {})
                affected = payload.get("affected_tickers", [])
                news_signals.append(
                    {
                        "headline": payload.get("title", ""),
                        "source": payload.get("source", ""),
                        "tickers": affected,
                        "ticker": affected[0] if affected else "",
                        "summary": payload.get("summary", ""),
                        "category": payload.get("category", "macro"),
                        "sentiment": payload.get("sentiment", 0),
                    }
                )
        return news_signals

    def _format_holdings_context(self, holdings_reports: list[dict[str, Any]]) -> str:
        lines = []
        for report in sorted(holdings_reports, key=lambda item: abs(item.get("change_pct") or 0), reverse=True):
            lines.append(
                f"- {report.get('ticker', '')}: price={report.get('price', 'N/A')} change={report.get('change_pct', 0):+.1f}% "
                f"position={report.get('position_pct', 'N/A')} thesis_status={report.get('thesis_status', 'intact')}"
            )
        return "\n".join(lines)

    def _news_lines(self, articles: list[dict[str, Any]]) -> list[str]:
        lines = []
        for article in articles[:10]:
            tickers = ", ".join(article.get("related_tickers", [])[:3])
            prefix = f"[{tickers}] " if tickers else ""
            lines.append(f"- {prefix}{article.get('title', '')}: {article.get('summary', '')[:180]}")
        return lines

    def _build_movers(self, holdings_reports: list[dict[str, Any]], articles: list[dict[str, Any]]) -> list[dict[str, Any]]:
        article_map: dict[str, str] = {}
        for article in articles:
            for ticker in article.get("related_tickers", [])[:3]:
                article_map.setdefault(ticker, article.get("summary", article.get("title", "")))
        movers = []
        for report in sorted(holdings_reports, key=lambda item: abs(item.get("change_pct") or 0), reverse=True)[:6]:
            ticker = report.get("ticker", "")
            movers.append(
                {
                    "ticker": ticker,
                    "change_pct": report.get("change_pct"),
                    "summary": article_map.get(ticker, report.get("recent_trend", "No linked headline.")),
                }
            )
        return movers

    async def _load_catalysts(self, tickers: list[str]) -> list[dict[str, Any]]:
        try:
            from src.advisor.catalyst_tracker import run_catalyst_tracking

            catalyst_data = await asyncio.to_thread(run_catalyst_tracking, tickers)
            return catalyst_data.get("catalysts", []) if isinstance(catalyst_data, dict) else []
        except Exception:
            log.debug("Catalyst tracking unavailable for lightweight run", exc_info=True)
            return []

    def _parse_numbered_sections(self, text: str) -> dict[str, str]:
        sections: dict[str, list[str]] = {}
        current = ""
        for raw_line in text.splitlines():
            line = raw_line.strip()
            lowered = line.lower().strip(" :")
            if lowered.startswith("1."):
                current = "scorecard"
                sections.setdefault(current, [])
                continue
            if lowered.startswith("2."):
                current = "what changed"
                sections.setdefault(current, [])
                continue
            if lowered.startswith("3."):
                current = "after-hours / tomorrow"
                sections.setdefault(current, [])
                continue
            if current:
                sections[current].append(raw_line)
        return {key: "\n".join(value).strip() for key, value in sections.items() if value}

    def _compute_thesis_changes(self, recent_runs: list[dict[str, Any]]) -> list[str]:
        if len(recent_runs) < 2:
            return []
        latest = (recent_runs[0].get("snapshot_data") or {}).get("tickers", {})
        previous = (recent_runs[1].get("snapshot_data") or {}).get("tickers", {})
        changes = []
        for ticker, latest_data in latest.items():
            prev_status = (previous.get(ticker) or {}).get("thesis_status")
            new_status = latest_data.get("thesis_status")
            if prev_status and new_status and prev_status != new_status:
                changes.append(f"{ticker}: {prev_status} → {new_status}")
        return changes

    def _summarize_recent_runs(self, recent_runs: list[dict[str, Any]]) -> list[str]:
        items: list[str] = []
        for run in recent_runs[:6]:
            delta = run.get("delta_from_previous") or {}
            for bucket in ("high_significance", "medium_significance"):
                for entry in delta.get(bucket, [])[:2]:
                    narrative = entry.get("narrative") if isinstance(entry, dict) else ""
                    if narrative:
                        items.append(f"{run.get('run_type', 'run')}: {narrative}")
            if len(items) >= 8:
                break
        return items
