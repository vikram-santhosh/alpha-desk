"""Reasoning Journal for AlphaDesk Advisor.

Records daily thesis snapshots and predictions for each ticker, then evaluates
accuracy weekly to build per-analyst calibration profiles. This enables the CIO
synthesis prompt to receive bias corrections like:

    "Growth analyst overestimates 70% of the time -- discount accordingly."

Tables live in the shared advisor_memory.db alongside other advisor state.
"""

import json
from datetime import date, datetime, timedelta
from typing import Any

import yfinance as yf

from src.shared import gemini_compat as anthropic
from src.shared.cost_tracker import check_budget, record_usage
from src.utils.logger import get_logger

log = get_logger(__name__)

AGENT_NAME = "reasoning_journal"
MODEL = "claude-haiku-4-5"


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def _ensure_tables():
    """Create reasoning_journal and calibration_profiles tables if they don't exist."""
    from src.advisor.memory import _get_db

    conn = _get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS reasoning_journal (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            ticker TEXT NOT NULL,
            analyst TEXT NOT NULL DEFAULT 'composite',
            thesis_snapshot TEXT NOT NULL,
            assumption_chain TEXT DEFAULT '[]',
            predicted_direction TEXT NOT NULL DEFAULT 'up',
            predicted_magnitude TEXT DEFAULT 'moderate',
            actual_direction TEXT,
            actual_return_pct REAL,
            was_correct INTEGER,
            error_analysis TEXT,
            evaluated_at TEXT,
            UNIQUE(date, ticker, analyst)
        );

        CREATE TABLE IF NOT EXISTS calibration_profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            profile_type TEXT NOT NULL,
            profile_key TEXT NOT NULL,
            total_predictions INTEGER NOT NULL DEFAULT 0,
            correct_predictions INTEGER NOT NULL DEFAULT 0,
            hit_rate REAL NOT NULL DEFAULT 0.0,
            systematic_bias TEXT DEFAULT '',
            bias_direction TEXT DEFAULT '',
            last_updated TEXT NOT NULL,
            UNIQUE(profile_type, profile_key)
        );
    """)
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Record daily reasoning (no LLM call)
# ---------------------------------------------------------------------------

def record_daily_reasoning(
    ticker: str,
    analyst: str,
    thesis_snapshot: str,
    predicted_direction: str,
    predicted_magnitude: str = "moderate",
    assumption_chain: list[str] | None = None,
) -> None:
    """Save a thesis snapshot and prediction to the journal.

    Called after Step 6 in main.py for each holding + conviction ticker.
    No LLM call -- just a DB write.

    Args:
        ticker: Stock ticker symbol.
        analyst: One of "growth", "value", "risk", or "composite".
        thesis_snapshot: Current thesis text for this ticker.
        predicted_direction: "up", "down", or "flat".
        predicted_magnitude: "small" (<2%), "moderate" (2-5%), "large" (>5%).
        assumption_chain: Optional list of assumption strings underpinning the thesis.
    """
    _ensure_tables()

    today = date.today().isoformat()
    chain_json = json.dumps(assumption_chain or [])

    from src.advisor.memory import _get_db

    conn = _get_db()
    try:
        conn.execute(
            """INSERT OR REPLACE INTO reasoning_journal
               (date, ticker, analyst, thesis_snapshot, assumption_chain,
                predicted_direction, predicted_magnitude)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                today,
                ticker.upper(),
                analyst,
                thesis_snapshot,
                chain_json,
                predicted_direction,
                predicted_magnitude,
            ),
        )
        conn.commit()
        log.info("Recorded reasoning: %s %s (%s, %s %s)",
                 ticker, analyst, predicted_direction, predicted_magnitude, today)
    except Exception:
        log.exception("Failed to record reasoning for %s/%s", ticker, analyst)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Weekly evaluation
# ---------------------------------------------------------------------------

def _fetch_price_on_date(ticker: str, target_date: str) -> float | None:
    """Fetch closing price for *ticker* on or near *target_date*.

    Uses a small window around the target date to handle weekends/holidays.
    """
    try:
        start = (datetime.strptime(target_date, "%Y-%m-%d") - timedelta(days=3)).strftime("%Y-%m-%d")
        end = (datetime.strptime(target_date, "%Y-%m-%d") + timedelta(days=3)).strftime("%Y-%m-%d")
        hist = yf.download(ticker, start=start, end=end, progress=False)
        if hist.empty:
            return None
        # Find the closest date at or before target
        target_dt = datetime.strptime(target_date, "%Y-%m-%d")
        valid = hist.loc[hist.index <= target_dt.strftime("%Y-%m-%d")]
        if valid.empty:
            valid = hist
        close_col = "Close"
        if isinstance(hist.columns, __import__("pandas").MultiIndex):
            close_col = ("Close", ticker)
        return float(valid[close_col].iloc[-1])
    except Exception:
        log.debug("Failed to fetch price for %s on %s", ticker, target_date)
        return None


def _fetch_current_price(ticker: str) -> float | None:
    """Fetch the most recent closing price for *ticker*."""
    try:
        hist = yf.download(ticker, period="5d", progress=False)
        if hist.empty:
            return None
        close_col = "Close"
        if isinstance(hist.columns, __import__("pandas").MultiIndex):
            close_col = ("Close", ticker)
        return float(hist[close_col].iloc[-1])
    except Exception:
        log.debug("Failed to fetch current price for %s", ticker)
        return None


def evaluate_past_reasoning(lookback_days: int = 30) -> dict:
    """Evaluate unevaluated journal entries from the past *lookback_days*.

    For each unevaluated entry:
      1. Fetches entry-date and current prices to compute actual return.
      2. Batches all entries into a single Flash LLM call for error analysis.
      3. Updates each row with results and refreshes calibration profiles.

    Returns:
        Summary dict: {evaluated, correct, hit_rate, errors}.
    """
    _ensure_tables()
    from src.advisor.memory import _get_db

    cutoff = (date.today() - timedelta(days=lookback_days)).isoformat()

    conn = _get_db()
    rows = conn.execute(
        """SELECT id, date, ticker, analyst, thesis_snapshot,
                  predicted_direction, predicted_magnitude
           FROM reasoning_journal
           WHERE evaluated_at IS NULL AND date >= ?
           ORDER BY date""",
        (cutoff,),
    ).fetchall()
    conn.close()

    if not rows:
        log.info("No unevaluated journal entries in the past %d days", lookback_days)
        return {"evaluated": 0, "correct": 0, "hit_rate": 0.0, "errors": []}

    # --- Fetch prices and compute actual returns ---
    entries: list[dict[str, Any]] = []
    for row in rows:
        entry_id, entry_date, ticker, analyst, thesis, pred_dir, pred_mag = row

        entry_price = _fetch_price_on_date(ticker, entry_date)
        current_price = _fetch_current_price(ticker)

        if entry_price is None or current_price is None or entry_price == 0:
            log.warning("Skipping %s (%s): missing price data", ticker, entry_date)
            continue

        actual_return = ((current_price - entry_price) / entry_price) * 100
        if actual_return > 0.5:
            actual_direction = "up"
        elif actual_return < -0.5:
            actual_direction = "down"
        else:
            actual_direction = "flat"

        entries.append({
            "id": entry_id,
            "date": entry_date,
            "ticker": ticker,
            "analyst": analyst,
            "thesis": thesis,
            "predicted_direction": pred_dir,
            "predicted_magnitude": pred_mag,
            "actual_direction": actual_direction,
            "actual_return_pct": round(actual_return, 2),
        })

    if not entries:
        log.info("No entries with valid price data to evaluate")
        return {"evaluated": 0, "correct": 0, "hit_rate": 0.0, "errors": []}

    # --- LLM batch evaluation ---
    error_analyses = _batch_evaluate_with_llm(entries)

    # --- Update DB rows ---
    conn = _get_db()
    now = datetime.now().isoformat()
    correct_count = 0
    all_errors: list[str] = []

    for i, entry in enumerate(entries):
        llm_result = error_analyses[i] if i < len(error_analyses) else {}
        was_correct = llm_result.get("was_correct", entry["predicted_direction"] == entry["actual_direction"])
        error_text = llm_result.get("error_analysis", "")

        if was_correct:
            correct_count += 1
        if error_text and not was_correct:
            all_errors.append(f"[{entry['date']}] {entry['ticker']}: {error_text}")

        try:
            conn.execute(
                """UPDATE reasoning_journal
                   SET actual_direction = ?, actual_return_pct = ?,
                       was_correct = ?, error_analysis = ?, evaluated_at = ?
                   WHERE id = ?""",
                (
                    entry["actual_direction"],
                    entry["actual_return_pct"],
                    1 if was_correct else 0,
                    error_text,
                    now,
                    entry["id"],
                ),
            )
        except Exception:
            log.exception("Failed to update journal entry %d", entry["id"])

    conn.commit()
    conn.close()

    evaluated = len(entries)
    hit_rate = (correct_count / evaluated * 100) if evaluated > 0 else 0.0

    log.info("Evaluation complete: %d/%d correct (%.1f%%)", correct_count, evaluated, hit_rate)

    # --- Refresh calibration profiles ---
    _update_calibration_profiles()

    return {
        "evaluated": evaluated,
        "correct": correct_count,
        "hit_rate": round(hit_rate, 1),
        "errors": all_errors[:10],
    }


def _batch_evaluate_with_llm(entries: list[dict[str, Any]]) -> list[dict]:
    """Use a single Flash LLM call to batch-classify prediction accuracy.

    Returns a list of dicts with {was_correct: bool, error_analysis: str} aligned
    to the *entries* list. Falls back to simple direction matching on error.
    """
    within_budget, spent, cap = check_budget()
    if not within_budget:
        log.warning("Budget exceeded -- falling back to simple direction matching")
        return _simple_direction_match(entries)

    numbered_items = []
    for i, e in enumerate(entries):
        numbered_items.append(
            f"{i+1}. Ticker: {e['ticker']} | Date: {e['date']} | "
            f"Thesis: {e['thesis'][:300]} | "
            f"Predicted: {e['predicted_direction']} ({e['predicted_magnitude']}) | "
            f"Actual: {e['actual_direction']} ({e['actual_return_pct']:+.1f}%)"
        )

    prompt = f"""You are evaluating stock prediction accuracy. For each numbered prediction below,
determine whether the prediction was correct and provide a brief error analysis if wrong.

A prediction is correct if:
- Predicted direction matches actual direction (up/down/flat)
- OR if predicted "flat" and actual move was < 2%

Predictions:
{chr(10).join(numbered_items)}

Respond with ONLY a valid JSON array. Each element must have:
- "index": the prediction number (1-based)
- "was_correct": true or false
- "error_analysis": brief explanation of what went wrong (empty string if correct)

Example: [{{"index": 1, "was_correct": false, "error_analysis": "Ignored sector rotation headwind"}}]"""

    try:
        client = anthropic.Anthropic()
        response = client.messages.create(
            model=MODEL,
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )
        usage = response.usage
        record_usage(AGENT_NAME, usage.input_tokens, usage.output_tokens, model=MODEL)

        text = response.content[0].text.strip()
        # Strip markdown fences if present
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()

        results_list = json.loads(text)

        # Build index-aligned output
        results_by_index: dict[int, dict] = {}
        for item in results_list:
            idx = item.get("index", 0)
            results_by_index[idx] = {
                "was_correct": bool(item.get("was_correct", False)),
                "error_analysis": item.get("error_analysis", ""),
            }

        return [
            results_by_index.get(i + 1, {"was_correct": False, "error_analysis": ""})
            for i in range(len(entries))
        ]

    except json.JSONDecodeError:
        log.error("LLM returned invalid JSON for batch evaluation -- falling back")
        return _simple_direction_match(entries)
    except Exception:
        log.exception("Batch evaluation LLM call failed -- falling back")
        return _simple_direction_match(entries)


def _simple_direction_match(entries: list[dict[str, Any]]) -> list[dict]:
    """Fallback: mark correct if predicted direction matches actual direction."""
    results = []
    for e in entries:
        correct = e["predicted_direction"] == e["actual_direction"]
        results.append({
            "was_correct": correct,
            "error_analysis": "" if correct else f"Predicted {e['predicted_direction']}, actual {e['actual_direction']} ({e['actual_return_pct']:+.1f}%)",
        })
    return results


# ---------------------------------------------------------------------------
# Calibration profiles
# ---------------------------------------------------------------------------

def _update_calibration_profiles() -> None:
    """Recompute calibration profiles from all evaluated journal entries.

    Groups by analyst and computes hit rates. Detects systematic bias by
    comparing hit rates for "up" vs "down" predictions per analyst.
    """
    from src.advisor.memory import _get_db

    conn = _get_db()

    # Aggregate by analyst
    analyst_rows = conn.execute(
        """SELECT analyst,
                  COUNT(*) as total,
                  SUM(CASE WHEN was_correct = 1 THEN 1 ELSE 0 END) as correct
           FROM reasoning_journal
           WHERE evaluated_at IS NOT NULL
           GROUP BY analyst"""
    ).fetchall()

    now = datetime.now().isoformat()

    for analyst, total, correct in analyst_rows:
        hit_rate = (correct / total * 100) if total > 0 else 0.0

        # Detect systematic bias: compare up vs down hit rates
        bias_text, bias_dir = _detect_bias(conn, analyst)

        try:
            conn.execute(
                """INSERT OR REPLACE INTO calibration_profiles
                   (profile_type, profile_key, total_predictions, correct_predictions,
                    hit_rate, systematic_bias, bias_direction, last_updated)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    "analyst",
                    analyst,
                    total,
                    correct,
                    round(hit_rate, 1),
                    bias_text,
                    bias_dir,
                    now,
                ),
            )
        except Exception:
            log.exception("Failed to update calibration profile for %s", analyst)

    conn.commit()
    conn.close()
    log.info("Updated calibration profiles for %d analysts", len(analyst_rows))


def _detect_bias(conn, analyst: str) -> tuple[str, str]:
    """Check if an analyst is systematically biased toward up or down predictions.

    Returns (bias_description, bias_direction) tuple.
    """
    rows = conn.execute(
        """SELECT predicted_direction,
                  COUNT(*) as total,
                  SUM(CASE WHEN was_correct = 1 THEN 1 ELSE 0 END) as correct
           FROM reasoning_journal
           WHERE evaluated_at IS NOT NULL AND analyst = ?
           GROUP BY predicted_direction""",
        (analyst,),
    ).fetchall()

    dir_stats: dict[str, dict[str, int]] = {}
    for direction, total, correct in rows:
        dir_stats[direction] = {"total": total, "correct": correct}

    up_stats = dir_stats.get("up", {"total": 0, "correct": 0})
    down_stats = dir_stats.get("down", {"total": 0, "correct": 0})

    up_total = up_stats["total"]
    down_total = down_stats["total"]

    # Need enough data to detect bias
    if up_total < 3 and down_total < 3:
        return ("", "")

    up_hit = (up_stats["correct"] / up_total * 100) if up_total > 0 else 0
    down_hit = (down_stats["correct"] / down_total * 100) if down_total > 0 else 0

    # Check for prediction frequency bias (>75% of predictions in one direction)
    total_directional = up_total + down_total
    if total_directional > 0:
        up_pct = up_total / total_directional * 100

        if up_pct > 75 and up_hit < down_hit:
            overestimate_rate = 100 - up_hit
            return (
                f"systematically bullish -- overestimates upside {overestimate_rate:.0f}% of the time",
                "bullish",
            )
        elif up_pct < 25 and down_hit < up_hit:
            overestimate_rate = 100 - down_hit
            return (
                f"systematically bearish -- overestimates downside {overestimate_rate:.0f}% of the time",
                "bearish",
            )

    # Check for significant hit rate divergence (>15pp)
    if abs(up_hit - down_hit) > 15:
        if up_hit < down_hit and up_total >= 3:
            return ("overweights momentum -- worse at calling upside", "bullish")
        elif down_hit < up_hit and down_total >= 3:
            return ("overweights risk -- worse at calling downside", "bearish")

    return ("", "")


# ---------------------------------------------------------------------------
# Build calibration context for CIO prompt
# ---------------------------------------------------------------------------

def build_calibration_context() -> str:
    """Build a formatted calibration string for injection into the CIO prompt.

    Reads calibration_profiles + 3 most recent errors from reasoning_journal.
    Returns empty string if no calibration data exists yet.
    """
    _ensure_tables()
    from src.advisor.memory import _get_db

    conn = _get_db()

    profiles = conn.execute(
        """SELECT profile_key, total_predictions, correct_predictions,
                  hit_rate, systematic_bias
           FROM calibration_profiles
           WHERE profile_type = 'analyst'
           ORDER BY total_predictions DESC"""
    ).fetchall()

    if not profiles:
        conn.close()
        return ""

    # Check if there's any meaningful data
    total_all = sum(p[1] for p in profiles)
    if total_all == 0:
        conn.close()
        return ""

    # Build analyst lines
    lines = ["## CALIBRATION DATA (from past 30 days)"]

    for profile_key, total, correct, hit_rate, bias in profiles:
        analyst_label = profile_key.capitalize() if profile_key != "composite" else "Composite"
        line = f"{analyst_label} analyst: {hit_rate:.0f}% hit rate ({correct}/{total} predictions)"
        lines.append(line)
        if bias:
            lines.append(f"  Bias: {bias}")

    # Recent errors (3 most recent)
    error_rows = conn.execute(
        """SELECT date, ticker, predicted_direction, predicted_magnitude,
                  actual_return_pct, error_analysis
           FROM reasoning_journal
           WHERE was_correct = 0 AND error_analysis != '' AND error_analysis IS NOT NULL
           ORDER BY date DESC
           LIMIT 3"""
    ).fetchall()
    conn.close()

    if error_rows:
        lines.append("")
        lines.append("Recent errors:")
        for i, (err_date, ticker, pred_dir, pred_mag, actual_ret, analysis) in enumerate(error_rows, 1):
            ret_str = f"{actual_ret:+.1f}%" if actual_ret is not None else "N/A"
            lines.append(
                f"{i}. [{err_date}] {ticker}: predicted {pred_mag} {pred_dir}, "
                f"actual {ret_str}. Error: {analysis}"
            )

    lines.append("")
    lines.append(
        "INSTRUCTION: Use this calibration data to adjust your confidence. "
        "If an analyst is systematically biased, explicitly correct for that bias."
    )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Query helper
# ---------------------------------------------------------------------------

def get_journal_entries(ticker: str | None = None, days: int = 7) -> list[dict]:
    """Return recent journal entries, optionally filtered by ticker.

    Args:
        ticker: Filter by ticker symbol (None for all).
        days: How many days back to look (default 7).

    Returns:
        List of dicts with all journal columns.
    """
    _ensure_tables()
    from src.advisor.memory import _get_db

    cutoff = (date.today() - timedelta(days=days)).isoformat()

    conn = _get_db()
    if ticker:
        rows = conn.execute(
            """SELECT id, date, ticker, analyst, thesis_snapshot, assumption_chain,
                      predicted_direction, predicted_magnitude, actual_direction,
                      actual_return_pct, was_correct, error_analysis, evaluated_at
               FROM reasoning_journal
               WHERE ticker = ? AND date >= ?
               ORDER BY date DESC""",
            (ticker.upper(), cutoff),
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT id, date, ticker, analyst, thesis_snapshot, assumption_chain,
                      predicted_direction, predicted_magnitude, actual_direction,
                      actual_return_pct, was_correct, error_analysis, evaluated_at
               FROM reasoning_journal
               WHERE date >= ?
               ORDER BY date DESC""",
            (cutoff,),
        ).fetchall()
    conn.close()

    columns = [
        "id", "date", "ticker", "analyst", "thesis_snapshot", "assumption_chain",
        "predicted_direction", "predicted_magnitude", "actual_direction",
        "actual_return_pct", "was_correct", "error_analysis", "evaluated_at",
    ]

    results = []
    for row in rows:
        entry = dict(zip(columns, row))
        # Parse assumption_chain from JSON
        try:
            entry["assumption_chain"] = json.loads(entry.get("assumption_chain") or "[]")
        except (json.JSONDecodeError, TypeError):
            entry["assumption_chain"] = []
        results.append(entry)

    return results
