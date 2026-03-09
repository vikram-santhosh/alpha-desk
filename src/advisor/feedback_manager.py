"""User feedback manager for AlphaDesk Advisor.

Records user feedback (ratings, preferences, corrections, missed signals) and
extracts structured preferences via LLM. These preferences are injected into
the CIO synthesis prompt so future analysis adapts to the user's priorities.

Feedback types:
    - rating:        "Today's brief was great / mediocre / bad"
    - preference:    "Weight geopolitical risk higher"
    - correction:    "NVDA thesis is wrong because..."
    - missed_signal: "You missed the AMD competitor impact on NVDA"
"""

import json
from datetime import date, datetime, timedelta
from typing import Any

from src.shared import gemini_compat as anthropic
from src.shared.cost_tracker import check_budget, record_usage
from src.utils.logger import get_logger

log = get_logger(__name__)

AGENT_NAME = "advisor_feedback"
MODEL = "claude-haiku-4-5"

VALID_FEEDBACK_TYPES = ("rating", "preference", "correction", "missed_signal")


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def _ensure_tables():
    """Create feedback and preferences tables if they don't exist."""
    from src.advisor.memory import _get_db

    conn = _get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS user_feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            feedback_type TEXT NOT NULL,
            context TEXT DEFAULT '',
            raw_text TEXT NOT NULL,
            structured_preference TEXT DEFAULT '{}'
        );

        CREATE TABLE IF NOT EXISTS user_preferences (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            preference_key TEXT NOT NULL UNIQUE,
            preference_value TEXT NOT NULL,
            confidence REAL DEFAULT 0.5,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
    """)
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------

def record_feedback(
    feedback_type: str,
    raw_text: str,
    context: str = "",
) -> int:
    """Save raw feedback to the user_feedback table.

    Args:
        feedback_type: One of "rating", "preference", "correction",
                       "missed_signal".
        raw_text: The user's raw feedback text.
        context: Optional context (e.g., ticker, brief section).

    Returns:
        Row ID of the inserted feedback record.

    Raises:
        ValueError: If feedback_type is not a valid type.
    """
    if feedback_type not in VALID_FEEDBACK_TYPES:
        raise ValueError(
            f"Invalid feedback_type '{feedback_type}'. "
            f"Must be one of: {VALID_FEEDBACK_TYPES}"
        )

    _ensure_tables()
    from src.advisor.memory import _get_db

    conn = _get_db()
    cursor = conn.execute(
        """INSERT INTO user_feedback
           (date, feedback_type, context, raw_text, structured_preference)
           VALUES (?, ?, ?, ?, '{}')""",
        (date.today().isoformat(), feedback_type, context, raw_text),
    )
    row_id = cursor.lastrowid
    conn.commit()
    conn.close()

    log.info(
        "Recorded %s feedback (id=%d): %.80s",
        feedback_type, row_id, raw_text,
    )
    return row_id


def extract_preferences(text: str) -> list[dict]:
    """Extract structured preferences from natural language via Flash.

    Sends the feedback text to Flash and asks it to extract actionable
    preference key-value pairs with confidence scores.

    Examples:
        "Weight geopolitical risk higher"
        -> [{key: "geopolitical_risk_weight", value: "increase", confidence: 0.8}]

        "Focus more on tech and healthcare"
        -> [{key: "sector_focus", value: "technology, healthcare", confidence: 0.9}]

    Args:
        text: Raw feedback text from the user.

    Returns:
        List of dicts, each with keys: key, value, confidence.
        Returns empty list if budget is exceeded or extraction fails.
    """
    within_budget, spent, cap = check_budget()
    if not within_budget:
        log.warning(
            "Budget exceeded ($%.2f/$%.2f) — skipping preference extraction",
            spent, cap,
        )
        return []

    prompt = f"""Extract structured investment preferences from this user feedback. Return ONLY valid JSON.

User feedback: "{text}"

Extract preferences as a JSON array. Each preference should have:
- "key": a snake_case preference identifier (e.g., "geopolitical_risk_weight", "sector_focus", "risk_tolerance", "position_sizing", "reporting_detail")
- "value": the preference value as a short string (e.g., "increase", "technology, healthcare", "conservative")
- "confidence": how confident you are this is a real preference (0.0-1.0)

Rules:
- Only extract clear, actionable preferences
- Ignore vague statements or questions
- If no clear preference is expressed, return an empty array: []
- Return ONLY the JSON array, no other text

Response:"""

    try:
        client = anthropic.Anthropic()
        response = client.messages.create(
            model=MODEL,
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )

        if not response.content:
            log.warning("Empty response from preference extraction")
            return []

        usage = response.usage
        record_usage(
            AGENT_NAME,
            usage.input_tokens,
            usage.output_tokens,
            model=MODEL,
        )

        raw = response.content[0].text.strip()

        # Strip markdown code fences if present
        if "```json" in raw:
            raw = raw.split("```json")[1].split("```")[0].strip()
        elif "```" in raw:
            raw = raw.split("```")[1].split("```")[0].strip()

        preferences = json.loads(raw)

        # Validate structure
        if not isinstance(preferences, list):
            log.warning("Preference extraction returned non-list: %s", type(preferences))
            return []

        validated = []
        for pref in preferences:
            if (
                isinstance(pref, dict)
                and "key" in pref
                and "value" in pref
            ):
                validated.append({
                    "key": str(pref["key"]),
                    "value": str(pref["value"]),
                    "confidence": float(pref.get("confidence", 0.5)),
                })

        log.info(
            "Extracted %d preferences from feedback (%d in, %d out)",
            len(validated), usage.input_tokens, usage.output_tokens,
        )
        return validated

    except json.JSONDecodeError:
        log.error("Preference extraction returned invalid JSON")
        return []
    except Exception:
        log.exception("Preference extraction failed")
        return []


def save_preferences(preferences: list[dict]):
    """Upsert extracted preferences into the user_preferences table.

    For each preference, either inserts a new row or updates an existing
    one (matched by preference_key). Confidence is updated using a weighted
    average: new_confidence = 0.7 * new + 0.3 * old, so repeated signals
    build confidence over time.

    Args:
        preferences: List of dicts with keys: key, value, confidence.
    """
    if not preferences:
        return

    _ensure_tables()
    from src.advisor.memory import _get_db

    conn = _get_db()
    now = datetime.now().isoformat()

    for pref in preferences:
        key = pref.get("key", "")
        value = pref.get("value", "")
        confidence = pref.get("confidence", 0.5)

        if not key or not value:
            continue

        # Check if preference already exists
        existing = conn.execute(
            "SELECT id, confidence FROM user_preferences WHERE preference_key = ?",
            (key,),
        ).fetchone()

        if existing:
            # Weighted average: new signal gets 70% weight
            old_confidence = existing[1]
            blended_confidence = 0.7 * confidence + 0.3 * old_confidence
            conn.execute(
                """UPDATE user_preferences
                   SET preference_value = ?, confidence = ?, updated_at = ?
                   WHERE preference_key = ?""",
                (value, blended_confidence, now, key),
            )
            log.debug(
                "Updated preference %s = %s (confidence: %.2f -> %.2f)",
                key, value, old_confidence, blended_confidence,
            )
        else:
            conn.execute(
                """INSERT INTO user_preferences
                   (preference_key, preference_value, confidence,
                    created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (key, value, confidence, now, now),
            )
            log.debug("Saved new preference %s = %s (confidence: %.2f)", key, value, confidence)

    conn.commit()
    conn.close()
    log.info("Saved %d preferences", len(preferences))


def build_preference_context() -> str:
    """Read all preferences and recent feedback, formatted for CIO prompt injection.

    Returns a string block that can be appended to the CIO synthesis prompt.
    Includes:
        - All stored preferences with confidence scores
        - Last 5 pieces of recent feedback (past 30 days)
        - Instruction for the CIO to incorporate these signals

    Returns:
        Formatted preference context string, or empty string if no data.
    """
    _ensure_tables()
    from src.advisor.memory import _get_db

    conn = _get_db()

    # Load all preferences
    prefs = conn.execute(
        """SELECT preference_key, preference_value, confidence
           FROM user_preferences
           ORDER BY confidence DESC"""
    ).fetchall()

    # Load recent feedback (last 30 days, max 5)
    cutoff = (date.today() - timedelta(days=30)).isoformat()
    feedback_rows = conn.execute(
        """SELECT date, raw_text
           FROM user_feedback
           WHERE date >= ?
           ORDER BY date DESC
           LIMIT 5""",
        (cutoff,),
    ).fetchall()

    conn.close()

    if not prefs and not feedback_rows:
        return ""

    lines = ["## USER PREFERENCES"]

    if prefs:
        for key, value, confidence in prefs:
            lines.append(f"- {key}: {value} (confidence: {confidence:.1f})")
    else:
        lines.append("- No structured preferences recorded yet.")

    if feedback_rows:
        lines.append("")
        lines.append("Recent feedback:")
        for fb_date, raw_text in feedback_rows:
            # Truncate long feedback for the prompt
            display_text = raw_text[:120]
            if len(raw_text) > 120:
                display_text += "..."
            lines.append(f'- [{fb_date}] "{display_text}"')

    lines.append("")
    lines.append(
        "INSTRUCTION: Incorporate these user preferences into your analysis. "
        "Give extra weight to areas the user has flagged."
    )

    return "\n".join(lines)


def get_recent_feedback(days: int = 30) -> list[dict]:
    """Get recent feedback entries from the database.

    Args:
        days: Number of days to look back (default 30).

    Returns:
        List of feedback dicts with keys: id, date, feedback_type,
        context, raw_text, structured_preference.
    """
    _ensure_tables()
    from src.advisor.memory import _get_db

    cutoff = (date.today() - timedelta(days=days)).isoformat()

    conn = _get_db()
    rows = conn.execute(
        """SELECT id, date, feedback_type, context, raw_text,
                  structured_preference
           FROM user_feedback
           WHERE date >= ?
           ORDER BY date DESC""",
        (cutoff,),
    ).fetchall()
    conn.close()

    results = []
    for row in rows:
        structured = {}
        if row[5]:
            try:
                structured = json.loads(row[5])
            except (json.JSONDecodeError, TypeError):
                structured = {}

        results.append({
            "id": row[0],
            "date": row[1],
            "feedback_type": row[2],
            "context": row[3],
            "raw_text": row[4],
            "structured_preference": structured,
        })

    log.info("Retrieved %d feedback entries (last %d days)", len(results), days)
    return results
