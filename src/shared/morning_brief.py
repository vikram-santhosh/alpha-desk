"""Morning Brief Orchestrator — runs all agents and synthesizes with Opus 4.6.

This is the master orchestrator that:
1. Runs Street Ear, Portfolio Analyst, and News Desk agents
2. Collects their outputs and signals
3. Uses Claude Opus 4.6 to synthesize key takeaways and action items
4. Assembles the complete morning briefing for Telegram delivery
"""

import asyncio
import time
from datetime import date, datetime
from typing import Any

import anthropic

from src.shared.agent_bus import get_recent_signals
from src.shared.cost_tracker import (
    check_budget,
    format_cost_report,
    get_daily_cost,
    record_usage,
)
from src.utils.logger import get_logger

log = get_logger(__name__)

AGENT_NAME = "morning_brief"
MODEL = "claude-opus-4-6"


async def _run_agent(name: str, run_fn) -> dict[str, Any]:
    """Run a single agent with error handling and timing."""
    start = time.time()
    try:
        result = await run_fn()
        elapsed = time.time() - start
        log.info("Agent %s completed in %.1fs", name, elapsed)
        return result
    except Exception as e:
        elapsed = time.time() - start
        log.error("Agent %s failed after %.1fs: %s", name, elapsed, e, exc_info=True)
        return {
            "formatted": f"<b>{name}</b>\n<i>Agent error: {e}</i>",
            "signals": [],
            "stats": {"error": str(e)},
        }


def _synthesize_brief(
    street_ear: dict[str, Any],
    portfolio: dict[str, Any],
    news_desk: dict[str, Any],
    alpha_scout: dict[str, Any] | None = None,
) -> str:
    """Use Opus 4.6 to synthesize key takeaways and action items.

    Takes the raw outputs from all agents and produces
    the KEY TAKEAWAYS and ACTION ITEMS sections of the morning brief.
    """
    within_budget, spent, cap = check_budget()
    if not within_budget:
        log.warning("Budget exceeded ($%.2f/$%.2f) — skipping synthesis", spent, cap)
        return (
            "<b>KEY TAKEAWAYS</b>\n"
            "<i>Budget exceeded — synthesis skipped. Review agent sections below.</i>"
        )

    # Build context from agent outputs
    portfolio_summary = portfolio.get("portfolio_summary", {})
    all_signals = (
        street_ear.get("signals", [])
        + portfolio.get("signals", [])
        + news_desk.get("signals", [])
    )
    if alpha_scout:
        all_signals.extend(alpha_scout.get("signals", []))

    stats = {
        "street_ear": street_ear.get("stats", {}),
        "portfolio": {
            "total_value": portfolio_summary.get("total_value", 0),
            "total_pnl": portfolio_summary.get("total_pnl", 0),
            "total_pnl_pct": portfolio_summary.get("total_pnl_pct", 0),
        },
        "news_desk": news_desk.get("stats", {}),
    }

    # Build Alpha Scout section for the synthesis prompt
    alpha_scout_section = ""
    if alpha_scout:
        alpha_scout_section = f"""

## ALPHA SCOUT (Ticker Discovery)
{alpha_scout.get('formatted', 'No data available')}
"""

    prompt = f"""You are an expert investment analyst synthesizing a morning briefing.

Today is {date.today().strftime('%B %d, %Y')}.

Here are the outputs from the research agents:

## STREET EAR (Reddit Intelligence)
{street_ear.get('formatted', 'No data available')}

## PORTFOLIO ANALYST
{portfolio.get('formatted', 'No data available')}

## NEWS DESK (Market News)
{news_desk.get('formatted', 'No data available')}
{alpha_scout_section}
## ACTIVE SIGNALS
{_format_signals_for_synthesis(all_signals)}

## PORTFOLIO STATS
Total Value: ${stats['portfolio'].get('total_value', 0):,.0f}
Total P&L: ${stats['portfolio'].get('total_pnl', 0):,.0f} ({stats['portfolio'].get('total_pnl_pct', 0):.1f}%)

Based on all this data, produce EXACTLY two sections:

1. KEY TAKEAWAYS — 3-5 bullet points highlighting the MOST important findings across all agents. Cross-reference signals (e.g., if a stock has both unusual Reddit buzz AND technical signals, mention both). Prioritize actionable insights.

2. ACTION ITEMS — 2-4 numbered, specific action items the investor should consider today. Be concrete (mention specific tickers, price levels, percentages).

Format using Telegram HTML tags (<b>, <i>, <code>). Be concise and direct. No headers beyond the section names. Do not repeat raw data — synthesize and connect the dots."""

    try:
        client = anthropic.Anthropic()
        response = client.messages.create(
            model=MODEL,
            max_tokens=1500,
            messages=[{"role": "user", "content": prompt}],
        )

        # Track costs
        usage = response.usage
        record_usage(AGENT_NAME, usage.input_tokens, usage.output_tokens, model=MODEL)

        synthesis = response.content[0].text
        log.info(
            "Synthesis complete: %d tokens in, %d tokens out",
            usage.input_tokens,
            usage.output_tokens,
        )
        return synthesis

    except Exception as e:
        log.error("Synthesis failed: %s", e, exc_info=True)
        return (
            "<b>KEY TAKEAWAYS</b>\n"
            "<i>Synthesis unavailable — review agent sections below.</i>"
        )


def _format_signals_for_synthesis(signals: list[dict[str, Any]]) -> str:
    """Format signals into a readable list for the synthesis prompt."""
    if not signals:
        return "No active signals."

    lines = []
    for s in signals[:20]:  # Cap to prevent prompt bloat
        signal_type = s.get("type", s.get("signal_type", "unknown"))
        ticker = s.get("ticker", s.get("payload", {}).get("ticker", "N/A"))
        lines.append(f"- [{signal_type}] {ticker}: {_signal_summary(s)}")
    return "\n".join(lines)


def _signal_summary(signal: dict[str, Any]) -> str:
    """Generate a brief summary of a signal."""
    payload = signal.get("payload", signal)
    parts = []
    if "current_mentions" in payload:
        parts.append(f"mentions={payload['current_mentions']}")
    if "ratio" in payload:
        parts.append(f"ratio={payload['ratio']:.1f}x")
    if "sentiment" in payload or "avg_sentiment" in payload:
        sent = payload.get("sentiment", payload.get("avg_sentiment", 0))
        parts.append(f"sentiment={sent}")
    if "subreddits" in payload:
        subs = payload["subreddits"]
        if isinstance(subs, list):
            parts.append(f"subs={len(subs)}")
    if "headline" in payload:
        parts.append(payload["headline"][:80])
    if "urgency" in payload:
        parts.append(f"urgency={payload['urgency']}")
    if "signals_summary" in payload:
        parts.extend(payload["signals_summary"][:3])
    return ", ".join(parts) if parts else str(payload)[:100]


def _assemble_briefing(
    synthesis: str,
    street_ear_formatted: str,
    portfolio_formatted: str,
    news_desk_formatted: str,
    daily_cost: float,
    alpha_scout_formatted: str = "",
) -> str:
    """Assemble the complete morning briefing."""
    today = datetime.now().strftime("%b %d, %Y")
    separator = "\u2501" * 35  # ━━━━━

    sections = [
        f"\u2600\ufe0f <b>ALPHADESK MORNING BRIEF \u2014 {today}</b>",
        separator,
        "",
        f"\U0001f3af {synthesis}",
        "",
        separator,
        "",
        f"\U0001f4ca {portfolio_formatted}",
        "",
        separator,
        "",
        f"\U0001f525 <b>STREET EAR \u2014 Reddit Intelligence</b>",
        street_ear_formatted,
        "",
        separator,
        "",
        f"\U0001f4f0 <b>NEWS DESK \u2014 Market Intelligence</b>",
        news_desk_formatted,
    ]

    # Alpha Scout section (if available)
    if alpha_scout_formatted:
        sections.extend([
            "",
            separator,
            "",
            alpha_scout_formatted,
        ])

    sections.extend([
        "",
        separator,
        f"AlphaDesk v0.1 | API cost today: ${daily_cost:.2f}",
        "/refresh /portfolio /news /trending /discover /brief /cost",
    ])

    return "\n".join(sections)


async def run() -> dict[str, Any]:
    """Run the complete morning brief pipeline.

    Executes all three agents, synthesizes with Opus 4.6,
    and assembles the full briefing.

    Returns:
        Dict with keys:
        - formatted: Complete briefing as Telegram HTML
        - sections: Individual agent outputs
        - signals: All signals from all agents
        - stats: Pipeline statistics
    """
    pipeline_start = time.time()
    log.info("Morning Brief pipeline starting")

    # Run all agents: Street Ear + News Desk in parallel first,
    # then Alpha Scout (reads signals without consuming),
    # then Portfolio Analyst (consumes signals).
    from src.street_ear.main import run as run_street_ear
    from src.news_desk.main import run as run_news_desk
    from src.alpha_scout.main import run as run_alpha_scout
    from src.portfolio_analyst.main import run as run_portfolio

    # Phase 1: Run Street Ear and News Desk in parallel
    log.info("Phase 1: Running Street Ear and News Desk in parallel")
    street_ear_result, news_desk_result = await asyncio.gather(
        _run_agent("Street Ear", run_street_ear),
        _run_agent("News Desk", run_news_desk),
    )

    # Phase 2: Run Alpha Scout (reads signals without consuming them)
    log.info("Phase 2: Running Alpha Scout")
    alpha_scout_result = await _run_agent("Alpha Scout", run_alpha_scout)

    # Phase 3: Run Portfolio Analyst (consumes signals from Phase 1)
    log.info("Phase 3: Running Portfolio Analyst")
    portfolio_result = await _run_agent("Portfolio Analyst", run_portfolio)

    # Phase 4: Synthesize with Opus 4.6
    log.info("Phase 4: Synthesizing with Opus 4.6")
    synthesis_start = time.time()
    synthesis = _synthesize_brief(
        street_ear_result, portfolio_result, news_desk_result, alpha_scout_result,
    )
    log.info("Synthesis took %.1fs", time.time() - synthesis_start)

    # Assemble the complete briefing
    daily_cost = get_daily_cost()
    briefing = _assemble_briefing(
        synthesis=synthesis,
        street_ear_formatted=street_ear_result.get("formatted", ""),
        portfolio_formatted=portfolio_result.get("formatted", ""),
        news_desk_formatted=news_desk_result.get("formatted", ""),
        daily_cost=daily_cost,
        alpha_scout_formatted=alpha_scout_result.get("formatted", ""),
    )

    # Collect all signals
    all_signals = (
        street_ear_result.get("signals", [])
        + portfolio_result.get("signals", [])
        + news_desk_result.get("signals", [])
        + alpha_scout_result.get("signals", [])
    )

    total_time = time.time() - pipeline_start
    log.info("Morning Brief complete in %.1fs", total_time)

    return {
        "formatted": briefing,
        "sections": {
            "street_ear": street_ear_result,
            "portfolio": portfolio_result,
            "news_desk": news_desk_result,
            "alpha_scout": alpha_scout_result,
        },
        "signals": all_signals,
        "stats": {
            "total_time_s": round(total_time, 1),
            "daily_cost": daily_cost,
            "signal_count": len(all_signals),
        },
    }


async def run_single_agent(agent_name: str) -> dict[str, Any]:
    """Run a single agent by name. Used for individual commands."""
    if agent_name == "street_ear":
        from src.street_ear.main import run as agent_run
    elif agent_name == "portfolio":
        from src.portfolio_analyst.main import run as agent_run
    elif agent_name == "news_desk":
        from src.news_desk.main import run as agent_run
    elif agent_name == "alpha_scout":
        from src.alpha_scout.main import run as agent_run
    else:
        return {"formatted": f"Unknown agent: {agent_name}", "signals": []}

    return await _run_agent(agent_name, agent_run)


if __name__ == "__main__":
    result = asyncio.run(run())
    print(result["formatted"])
