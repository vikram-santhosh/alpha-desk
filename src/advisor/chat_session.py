"""Interactive chat session for AlphaDesk Advisor.

Manages conversational Q&A about the daily brief via Telegram. Users can
ask follow-up questions about their portfolio, holdings, catalysts, and
anything covered in the morning brief.

Sessions expire after 4 hours of inactivity. Message history is capped at
10 messages (5 Q&A pairs) to keep context windows manageable.
"""

import json
from datetime import datetime, timedelta
from typing import Any

from src.shared import gemini_compat as anthropic
from src.shared.cost_tracker import check_budget, record_usage
from src.utils.logger import get_logger

log = get_logger(__name__)

AGENT_NAME = "advisor_chat"
MODEL = "claude-haiku-4-5"

# Session expires after 4 hours of inactivity
SESSION_EXPIRY_HOURS = 4
# Keep last 10 messages (5 Q&A pairs)
MAX_HISTORY = 10
# Max conversation messages to include in prompt (last 5 turns)
PROMPT_HISTORY_LIMIT = 5

SYSTEM_PROMPT = """You are AlphaDesk's investment chat assistant. The user has just read their daily brief and has follow-up questions.

You have access to:
1. Today's daily brief (below)
2. Portfolio holdings with current thesis status
3. Recent price snapshots (past 7 days)
4. Upcoming catalysts

Answer concisely. Use specific data from the brief and memory when available. If you don't have enough information, say so rather than speculating.

Format for Telegram: use <b>bold</b> and <i>italic</i> HTML tags. Keep answers under 500 words."""


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def _ensure_table():
    """Create chat_sessions table if it doesn't exist."""
    from src.advisor.memory import _get_db

    conn = _get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS chat_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id TEXT NOT NULL,
            last_brief_json TEXT,
            last_active TEXT NOT NULL,
            message_history TEXT DEFAULT '[]'
        );

        CREATE INDEX IF NOT EXISTS idx_chat_sessions_chat_id
            ON chat_sessions (chat_id);
    """)
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# ChatSession class
# ---------------------------------------------------------------------------

class ChatSession:
    """Manages a conversational Q&A session for a single Telegram chat."""

    def __init__(self, chat_id: str):
        self.chat_id = chat_id
        _ensure_table()

    def has_brief_context(self) -> bool:
        """Check if this session has a stored brief context."""
        from src.advisor.memory import _get_db

        conn = _get_db()
        row = conn.execute(
            "SELECT last_brief_json FROM chat_sessions WHERE chat_id = ?",
            (self.chat_id,),
        ).fetchone()
        conn.close()

        if not row or not row[0]:
            return False

        try:
            data = json.loads(row[0])
            return bool(data.get("brief_text"))
        except (json.JSONDecodeError, TypeError):
            return False

    def update_brief_context(self, brief_text: str, holdings_summary: str = ""):
        """Store the latest daily brief for this session's Q&A context.

        Resets message history when a new brief arrives so the conversation
        starts fresh with updated data.

        Args:
            brief_text: Full text of today's daily brief.
            holdings_summary: Optional summary of current holdings.
        """
        from src.advisor.memory import _get_db

        brief_json = json.dumps({
            "brief_text": brief_text,
            "holdings_summary": holdings_summary,
            "updated_at": datetime.now().isoformat(),
        })

        conn = _get_db()
        now = datetime.now().isoformat()

        existing = conn.execute(
            "SELECT id FROM chat_sessions WHERE chat_id = ?",
            (self.chat_id,),
        ).fetchone()

        if existing:
            conn.execute(
                """UPDATE chat_sessions
                   SET last_brief_json = ?, last_active = ?, message_history = '[]'
                   WHERE chat_id = ?""",
                (brief_json, now, self.chat_id),
            )
        else:
            conn.execute(
                """INSERT INTO chat_sessions
                   (chat_id, last_brief_json, last_active, message_history)
                   VALUES (?, ?, ?, '[]')""",
                (self.chat_id, brief_json, now),
            )

        conn.commit()
        conn.close()
        log.info("Updated brief context for chat %s", self.chat_id)

    async def answer_question(self, question: str) -> str:
        """Answer a follow-up question about the daily brief using Flash.

        Steps:
            1. Check session expiry (4 hours)
            2. Load brief context from DB
            3. Load last 5 messages from history
            4. Query advisor_memory.db for holdings, snapshots, catalysts
            5. Build prompt with brief + memory + conversation history
            6. Single Flash call
            7. Append Q+A to message_history, save
            8. Return answer text

        Args:
            question: The user's follow-up question.

        Returns:
            Answer text formatted for Telegram HTML.
        """
        # Check budget
        within_budget, spent, cap = check_budget()
        if not within_budget:
            log.warning("Budget exceeded ($%.2f/$%.2f) — declining chat", spent, cap)
            return (
                "<i>Daily API budget exceeded. Chat will resume tomorrow.</i>"
            )

        # Load session
        session = self._load_session()
        if not session:
            return (
                "<i>No active session. Send /brief first to load today's brief, "
                "then ask your question.</i>"
            )

        # Check expiry
        last_active = datetime.fromisoformat(session["last_active"])
        if datetime.now() - last_active > timedelta(hours=SESSION_EXPIRY_HOURS):
            log.info("Session expired for chat %s", self.chat_id)
            return (
                "<i>Your session has expired (4h inactive). "
                "Send /brief to start a new session.</i>"
            )

        # Parse brief context
        brief_data = {}
        if session.get("last_brief_json"):
            try:
                brief_data = json.loads(session["last_brief_json"])
            except (json.JSONDecodeError, TypeError):
                log.warning("Failed to parse brief JSON for chat %s", self.chat_id)

        brief_text = brief_data.get("brief_text", "No brief available.")
        holdings_summary = brief_data.get("holdings_summary", "")

        # Load conversation history
        history = []
        if session.get("message_history"):
            try:
                history = json.loads(session["message_history"])
            except (json.JSONDecodeError, TypeError):
                history = []

        # Build memory context from advisor DB
        memory_context = self._build_memory_context()

        # Build the full prompt
        context_parts = [
            "## TODAY'S DAILY BRIEF",
            brief_text,
        ]

        if holdings_summary:
            context_parts.extend([
                "",
                "## HOLDINGS SUMMARY",
                holdings_summary,
            ])

        if memory_context:
            context_parts.extend([
                "",
                memory_context,
            ])

        full_context = "\n".join(context_parts)

        # Build messages for the API call
        messages: list[dict[str, str]] = []

        # Add recent conversation history (last N turns)
        recent_history = history[-PROMPT_HISTORY_LIMIT * 2:]
        for msg in recent_history:
            messages.append({
                "role": msg["role"],
                "content": msg["content"],
            })

        # Add current question with context
        user_content = f"""Context for answering:
{full_context}

---

User question: {question}"""

        messages.append({"role": "user", "content": user_content})

        # Make the API call
        try:
            client = anthropic.Anthropic()
            response = client.messages.create(
                model=MODEL,
                max_tokens=1000,
                system=SYSTEM_PROMPT,
                messages=messages,
            )

            if not response.content:
                log.warning("Empty response for chat %s", self.chat_id)
                return "<i>I couldn't generate a response. Please try again.</i>"

            usage = response.usage
            record_usage(
                AGENT_NAME,
                usage.input_tokens,
                usage.output_tokens,
                model=MODEL,
            )

            answer = response.content[0].text.strip()
            log.info(
                "Chat response for %s (%d in, %d out)",
                self.chat_id,
                usage.input_tokens,
                usage.output_tokens,
            )

        except Exception:
            log.exception("Chat API call failed for %s", self.chat_id)
            return "<i>Something went wrong. Please try again in a moment.</i>"

        # Save Q+A to history
        self._save_message("user", question)
        self._save_message("assistant", answer)

        return answer

    def _load_session(self) -> dict | None:
        """Load session from DB.

        Returns:
            Session dict with keys: chat_id, last_brief_json, last_active,
            message_history. Returns None if no session exists.
        """
        from src.advisor.memory import _get_db

        conn = _get_db()
        row = conn.execute(
            """SELECT chat_id, last_brief_json, last_active, message_history
               FROM chat_sessions WHERE chat_id = ?""",
            (self.chat_id,),
        ).fetchone()
        conn.close()

        if not row:
            return None

        return {
            "chat_id": row[0],
            "last_brief_json": row[1],
            "last_active": row[2],
            "message_history": row[3],
        }

    def _save_message(self, role: str, content: str):
        """Append message to history (keep last MAX_HISTORY messages).

        Args:
            role: "user" or "assistant".
            content: Message text.
        """
        from src.advisor.memory import _get_db

        conn = _get_db()
        row = conn.execute(
            "SELECT message_history FROM chat_sessions WHERE chat_id = ?",
            (self.chat_id,),
        ).fetchone()

        history = []
        if row and row[0]:
            try:
                history = json.loads(row[0])
            except (json.JSONDecodeError, TypeError):
                history = []

        history.append({
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat(),
        })

        # Trim to last MAX_HISTORY messages
        if len(history) > MAX_HISTORY:
            history = history[-MAX_HISTORY:]

        now = datetime.now().isoformat()
        conn.execute(
            """UPDATE chat_sessions
               SET message_history = ?, last_active = ?
               WHERE chat_id = ?""",
            (json.dumps(history), now, self.chat_id),
        )
        conn.commit()
        conn.close()

    def _build_memory_context(self) -> str:
        """Query advisor_memory.db for holdings, snapshots, and catalysts.

        Returns a formatted string with portfolio data for the LLM prompt.
        """
        from src.advisor.memory import _get_db

        parts: list[str] = []
        conn = _get_db()

        # --- Holdings ---
        try:
            holdings = conn.execute(
                "SELECT ticker, thesis, thesis_status, entry_price FROM holdings"
            ).fetchall()

            if holdings:
                lines = ["## PORTFOLIO HOLDINGS"]
                for ticker, thesis, status, entry_price in holdings:
                    price_str = f"${entry_price:.2f}" if entry_price else "N/A"
                    lines.append(
                        f"- {ticker}: {thesis} "
                        f"(status: {status}, entry: {price_str})"
                    )
                parts.append("\n".join(lines))
        except Exception:
            log.debug("Failed to query holdings for chat context")

        # --- Recent price snapshots (past 7 days) ---
        try:
            snapshots = conn.execute(
                """SELECT ticker, date, price, change_pct
                   FROM holding_snapshots
                   WHERE date >= date('now', '-7 days')
                   ORDER BY date DESC"""
            ).fetchall()

            if snapshots:
                lines = ["## RECENT PRICE SNAPSHOTS (7d)"]
                # Group by ticker
                by_ticker: dict[str, list[tuple]] = {}
                for ticker, dt, price, change in snapshots:
                    by_ticker.setdefault(ticker, []).append(
                        (dt, price, change)
                    )
                for ticker, entries in by_ticker.items():
                    latest = entries[0]
                    change_str = (
                        f"{latest[2]:+.1f}%" if latest[2] is not None else ""
                    )
                    lines.append(
                        f"- {ticker}: ${latest[1]:.2f} {change_str} "
                        f"({len(entries)} snapshots)"
                    )
                parts.append("\n".join(lines))
        except Exception:
            log.debug("Failed to query snapshots for chat context")

        # --- Upcoming catalysts (next 30 days) ---
        try:
            catalysts = conn.execute(
                """SELECT ticker, event_type, event_date, description,
                          impact_estimate
                   FROM catalysts
                   WHERE event_date >= date('now')
                   ORDER BY event_date ASC
                   LIMIT 10"""
            ).fetchall()

            if catalysts:
                lines = ["## UPCOMING CATALYSTS"]
                for ticker, event_type, event_date, desc, impact in catalysts:
                    impact_tag = (
                        "[HIGH]" if impact == "high" else "[med]"
                    )
                    lines.append(
                        f"- {event_date} {impact_tag} {desc} ({ticker})"
                    )
                parts.append("\n".join(lines))
        except Exception:
            log.debug("Failed to query catalysts for chat context")

        # --- Conviction list ---
        try:
            convictions = conn.execute(
                """SELECT ticker, conviction, thesis
                   FROM conviction_list
                   WHERE status = 'active'"""
            ).fetchall()

            if convictions:
                lines = ["## CONVICTION LIST"]
                for ticker, conviction, thesis in convictions:
                    lines.append(
                        f"- {ticker} ({conviction} conviction): {thesis}"
                    )
                parts.append("\n".join(lines))
        except Exception:
            log.debug("Failed to query conviction list for chat context")

        conn.close()
        return "\n\n".join(parts)
