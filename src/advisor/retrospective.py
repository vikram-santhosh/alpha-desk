"""Weekly Retrospective for AlphaDesk Advisor v2.

Scores past recommendations, runs pattern analysis via LLM, and feeds
results back into the system's prompts so it can learn from its own
performance. Closes the feedback loop.
"""

import json
from datetime import date, datetime
from typing import Any

import anthropic

from src.advisor.memory import get_recommendation_scorecard
from src.advisor.outcome_scorer import score_all_outcomes, format_scorecard
from src.shared.cost_tracker import check_budget, record_usage
from src.utils.logger import get_logger

log = get_logger(__name__)

AGENT_NAME = "advisor_retrospective"
MODEL = "claude-opus-4-6"


def _ensure_retrospectives_table():
    """Create retrospectives table if needed."""
    from src.advisor.memory import _get_db
    conn = _get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS retrospectives (
            id INTEGER PRIMARY KEY,
            week_ending TEXT NOT NULL UNIQUE,
            scorecard TEXT NOT NULL,
            pattern_analysis TEXT NOT NULL,
            recommendations_evaluated INTEGER,
            created_at TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()


def run_weekly_retrospective() -> dict:
    """Run the weekly retrospective analysis.

    Steps:
        1. Score all open recommendations (update prices/returns)
        2. Compute scorecard (hit rate, alpha, false positives)
        3. Run LLM pattern analysis on the track record
        4. Save to retrospectives table
        5. Return full retrospective dict

    Returns:
        Dict with: scorecard, pattern_analysis, recommendations_evaluated, week_ending.
    """
    _ensure_retrospectives_table()

    log.info("Running weekly retrospective")

    # Step 1: Score all open recommendations
    scorecard = score_all_outcomes()
    total = scorecard.get("total_recommendations", 0)

    # Step 2: Run pattern analysis via LLM
    pattern_analysis = _run_pattern_analysis(scorecard)

    # Step 3: Save to DB
    week_ending = date.today().isoformat()
    from src.advisor.memory import _get_db
    conn = _get_db()
    try:
        conn.execute("""
            INSERT OR REPLACE INTO retrospectives
            (week_ending, scorecard, pattern_analysis, recommendations_evaluated, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (
            week_ending,
            json.dumps(scorecard),
            json.dumps(pattern_analysis),
            total,
            datetime.now().isoformat(),
        ))
        conn.commit()
    except Exception:
        log.exception("Failed to save retrospective")
    conn.close()

    result = {
        "scorecard": scorecard,
        "pattern_analysis": pattern_analysis,
        "recommendations_evaluated": total,
        "week_ending": week_ending,
    }

    log.info("Retrospective complete: %d recommendations evaluated", total)
    return result


def _run_pattern_analysis(scorecard: dict) -> dict:
    """Use LLM to analyze the track record and identify patterns."""
    total = scorecard.get("total_recommendations", 0)

    if total == 0:
        return {
            "performance_summary": "No recommendations tracked yet — insufficient data for pattern analysis.",
            "systematic_biases": [],
            "best_performing_pattern": "N/A",
            "worst_performing_pattern": "N/A",
            "calibration_advice": "Continue building track record before drawing conclusions.",
            "evidence_weight_adjustments": {"increase_weight": [], "decrease_weight": []},
        }

    within_budget, spent, cap = check_budget()
    if not within_budget:
        log.warning("Budget exceeded — using template pattern analysis")
        return _template_pattern_analysis(scorecard)

    # Build context for LLM
    hit_rate = scorecard.get("hit_rate_1m", 0)
    avg_alpha = scorecard.get("avg_alpha_1m_pct", 0)
    fp_rate = scorecard.get("false_positive_rate", 0)
    best = scorecard.get("best_recommendation")
    worst = scorecard.get("worst_recommendation")
    by_source = scorecard.get("hit_rate_by_source", {})
    by_conviction = scorecard.get("hit_rate_by_conviction", {})

    prompt = f"""You are analyzing the track record of an AI investment recommendation system. Here are the recent results:

## AGGREGATE METRICS (PAST 30 DAYS)
Total recommendations: {total}
Hit rate (1m): {hit_rate:.1f}%
Avg alpha vs SPY (1m): {avg_alpha:+.1f}%
False positive rate (high conviction losing >10%): {fp_rate:.1f}%
Best: {best['ticker'] + ' ' + str(best['return_pct']) + '%' if best else 'N/A'}
Worst: {worst['ticker'] + ' ' + str(worst['return_pct']) + '%' if worst else 'N/A'}

## HIT RATE BY SOURCE
{json.dumps(by_source, indent=2) if by_source else 'No breakdown available'}

## HIT RATE BY CONVICTION
{json.dumps(by_conviction, indent=2) if by_conviction else 'No breakdown available'}

Analyze this track record and respond with ONLY valid JSON:
{{
  "performance_summary": "2-3 sentence honest assessment of performance",
  "systematic_biases": ["List of patterns — e.g., 'overweights momentum', 'too bullish on small caps'"],
  "best_performing_pattern": "What type of recommendation worked best?",
  "worst_performing_pattern": "What type of recommendation worked worst?",
  "calibration_advice": "Specific advice for improving recommendations",
  "evidence_weight_adjustments": {{
    "increase_weight": ["sources that correlated with good outcomes"],
    "decrease_weight": ["sources that correlated with bad outcomes"]
  }}
}}"""

    try:
        client = anthropic.Anthropic()
        response = client.messages.create(
            model=MODEL,
            max_tokens=800,
            messages=[{"role": "user", "content": prompt}],
        )
        usage = response.usage
        record_usage(AGENT_NAME, usage.input_tokens, usage.output_tokens, model=MODEL)

        text = response.content[0].text.strip()
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()

        return json.loads(text)

    except json.JSONDecodeError:
        log.error("Pattern analysis returned invalid JSON")
        return _template_pattern_analysis(scorecard)
    except Exception:
        log.exception("Pattern analysis failed")
        return _template_pattern_analysis(scorecard)


def _template_pattern_analysis(scorecard: dict) -> dict:
    """Fallback template-based pattern analysis."""
    hit_rate = scorecard.get("hit_rate_1m", 0)
    return {
        "performance_summary": f"Track record shows {hit_rate:.0f}% hit rate at 1 month. Limited data — continue monitoring.",
        "systematic_biases": ["Insufficient data to detect biases"],
        "best_performing_pattern": "Insufficient data",
        "worst_performing_pattern": "Insufficient data",
        "calibration_advice": "Continue building track record. Review again after 10+ recommendations.",
        "evidence_weight_adjustments": {"increase_weight": [], "decrease_weight": []},
    }


def get_latest_retrospective_context() -> str:
    """Get the most recent retrospective formatted for the Opus synthesis prompt.

    Called at the start of every advisor pipeline run to provide
    self-awareness about past performance.
    """
    _ensure_retrospectives_table()

    from src.advisor.memory import _get_db
    conn = _get_db()
    row = conn.execute("""
        SELECT scorecard, pattern_analysis, week_ending
        FROM retrospectives ORDER BY week_ending DESC LIMIT 1
    """).fetchone()
    conn.close()

    if not row:
        return ""

    try:
        scorecard = json.loads(row[0])
        analysis = json.loads(row[1])
        week = row[2]
    except (json.JSONDecodeError, TypeError):
        return ""

    total = scorecard.get("total_recommendations", 0)
    if total == 0:
        return ""

    hit_rate = scorecard.get("hit_rate_1m", 0)
    avg_alpha = scorecard.get("avg_alpha_1m_pct", 0)
    fp_rate = scorecard.get("false_positive_rate", 0)
    biases = analysis.get("systematic_biases", [])
    advice = analysis.get("calibration_advice", "")

    lines = [
        f"## YOUR TRACK RECORD (as of {week})",
        f"Hit rate: {hit_rate:.0f}% ({total} recommendations in past 30 days)",
        f"Avg alpha: {avg_alpha:+.1f}% vs SPY",
        f"False positives: {fp_rate:.0f}%",
    ]

    if biases and biases[0] != "Insufficient data to detect biases":
        lines.append(f"Systematic biases detected: {'; '.join(biases[:3])}")

    if advice and advice != "Continue building track record. Review again after 10+ recommendations.":
        lines.append(f"Calibration advice: {advice}")

    lines.append("")
    lines.append("INSTRUCTION: Review your track record above. Adjust your confidence accordingly. If you've been systematically wrong about a pattern, explicitly correct for that bias today.")
    lines.append("")

    return "\n".join(lines)


def format_retrospective(retro: dict) -> str:
    """Format the retrospective for Telegram display."""
    scorecard = retro.get("scorecard", {})
    analysis = retro.get("pattern_analysis", {})
    week = retro.get("week_ending", "")

    lines = [
        f"<b>Weekly Retrospective — {week}</b>",
        "",
    ]

    # Scorecard
    total = scorecard.get("total_recommendations", 0)
    if total == 0:
        lines.append("<i>No recommendations tracked yet.</i>")
        return "\n".join(lines)

    lines.append(format_scorecard(scorecard))
    lines.append("")

    # Pattern analysis
    summary = analysis.get("performance_summary", "")
    if summary:
        lines.append(f"<b>Assessment:</b> {summary}")

    biases = analysis.get("systematic_biases", [])
    if biases and biases[0] != "Insufficient data to detect biases":
        lines.append(f"\n<b>Biases Detected:</b>")
        for bias in biases[:3]:
            lines.append(f"  - {bias}")

    advice = analysis.get("calibration_advice", "")
    if advice:
        lines.append(f"\n<b>Calibration:</b> {advice}")

    adjustments = analysis.get("evidence_weight_adjustments", {})
    increase = adjustments.get("increase_weight", [])
    decrease = adjustments.get("decrease_weight", [])
    if increase or decrease:
        lines.append(f"\n<b>Weight Adjustments:</b>")
        if increase:
            lines.append(f"  Increase: {', '.join(increase)}")
        if decrease:
            lines.append(f"  Decrease: {', '.join(decrease)}")

    return "\n".join(lines)
