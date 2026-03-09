"""Flash agent that extracts future-dated events from news articles.

Catches events the hardcoded catalyst tracker misses -- things like
"Trump announces 15% tariff implementation April 15" or "EU AI Act
enforcement June 1" or "Iran sanctions could disrupt oil supply chains."

Detected events are persisted as catalysts in advisor_memory.db so the
catalyst-proximity scorer and morning-brief formatter can pick them up.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Any

from src.shared import gemini_compat as anthropic
from src.shared.cost_tracker import check_budget, record_usage
from src.utils.logger import get_logger

log = get_logger(__name__)

AGENT_NAME = "event_detector"
MODEL = "claude-haiku-4-5"  # maps to gemini-2.5-flash
MAX_TOKENS = 4096

# Categories that should pass the article filter regardless of relevance score
_POLICY_CATEGORIES = {
    "geopolitical",
    "trade",
    "regulatory",
    "policy",
    "sanctions",
    "tariff",
    "war",
    "conflict",
}

# ═══════════════════════════════════════════════════════
# LLM PROMPTS
# ═══════════════════════════════════════════════════════

_SYSTEM_PROMPT = """\
You are a financial event extraction specialist. Given news articles, identify \
FUTURE-DATED events that could impact markets or specific stocks.

Rules:
1. Only extract events with specific dates or timeframes (not vague "could happen someday").
2. Convert relative dates ("next month", "in two weeks") to absolute ISO dates based on today's date: {today}.
3. Assign impact_estimate based on market-moving potential:
   - "high": likely >2% broad market or >5% single-stock move
   - "medium": 1-2% market or 2-5% single-stock move
   - "low": <1% market move
4. Use "BROAD_MARKET" as ticker if the event affects the whole market. \
Otherwise use specific tickers (standard US symbols).
5. confidence: 0.0-1.0 based on source reliability and specificity of the date. \
Official government announcements = 0.9+. Analyst speculation = 0.4-0.6.
6. Deduplicate: if an event matches one in the EXISTING CATALYSTS list \
(same type + similar date + same ticker), skip it.
7. event_type must be one of: geopolitical, regulatory, supply_chain, policy, industry, legal.
8. affected_tickers: list of US ticker symbols most directly impacted (may be empty for broad macro).

Respond with ONLY a JSON array. Each object must have these keys:
event_type, ticker, event_date (ISO), description, impact_estimate, source, \
source_article, confidence, affected_tickers, category."""

_USER_PROMPT_TEMPLATE = """\
Today's date: {today}

=== EXISTING CATALYSTS (skip duplicates) ===
{existing_catalysts}

=== NEWS ARTICLES ===
{articles}

Extract all future-dated events from the articles above. \
Return a JSON array (empty array [] if no events found)."""


# ═══════════════════════════════════════════════════════
# EVENT DETECTOR CLASS
# ═══════════════════════════════════════════════════════

class EventDetector:
    """Extract future-dated events from news articles and persist as catalysts."""

    SUPPORTED_TYPES = [
        "geopolitical",    # Wars, conflicts, sanctions, territorial disputes
        "regulatory",      # New laws, enforcement actions, regulatory rulings
        "supply_chain",    # Supply disruptions, logistics changes, commodity shocks
        "policy",          # Trade policy, tariffs, fiscal policy, central bank decisions
        "industry",        # Industry conferences, product launches, technology milestones
        "legal",           # Lawsuits, antitrust, patent disputes, settlements
    ]

    def __init__(self) -> None:
        self.client = anthropic.Anthropic()

    # ── public API ──────────────────────────────────────

    def extract_events(
        self,
        articles: list[dict],
        existing_catalysts: list[dict],
    ) -> list[dict]:
        """Extract future-dated events from news articles.

        Args:
            articles: News articles from news_desk. Each has:
                title, summary, source, url, related_tickers, category,
                sentiment, relevance
            existing_catalysts: Already-known catalysts (for deduplication).
                Each has: ticker, event_type, event_date, description

        Returns:
            List of new event dicts ready to be saved as catalysts:
            [
                {
                    "event_type": "policy",
                    "ticker": "BROAD_MARKET",
                    "event_date": "2026-04-15",
                    "description": "Trump tariff hike to 25% takes effect",
                    "impact_estimate": "high",
                    "source": "WSJ",
                    "source_article": "Trump announces April 15 tariff deadline",
                    "confidence": 0.85,
                    "affected_tickers": ["AAPL", "NVDA", "AVGO"],
                    "category": "policy",
                },
                ...
            ]
        """
        filtered = self._filter_articles(articles)
        if not filtered:
            log.info("No high-relevance or policy articles to scan for events")
            return []

        # Budget gate
        within_budget, spent, cap = check_budget()
        if not within_budget:
            log.warning(
                "Budget exceeded ($%.2f / $%.2f); skipping event detection",
                spent,
                cap,
            )
            return []

        today = date.today().isoformat()

        # Build existing-catalyst summary for dedup prompt
        if existing_catalysts:
            cat_lines = []
            for c in existing_catalysts:
                # Handle both CatalystEvent dataclasses and plain dicts
                if hasattr(c, 'event_type'):
                    cat_lines.append(
                        f"- [{c.event_type}] {getattr(c, 'ticker', '?')} "
                        f"{c.date}: {c.description}"
                    )
                else:
                    cat_lines.append(
                        f"- [{c.get('event_type', '?')}] {c.get('ticker', '?')} "
                        f"{c.get('event_date', c.get('date', '?'))}: {c.get('description', '?')}"
                    )
            existing_text = "\n".join(cat_lines)
        else:
            existing_text = "(none)"

        # Build articles text
        article_lines: list[str] = []
        for i, art in enumerate(filtered, 1):
            article_lines.append(f"--- Article {i} ---")
            article_lines.append(f"Title: {art.get('title', 'Untitled')}")
            article_lines.append(f"Source: {art.get('source', 'Unknown')}")
            article_lines.append(f"Summary: {art.get('summary', '')}")
            tickers = art.get("related_tickers", [])
            if tickers:
                article_lines.append(f"Tickers: {', '.join(tickers)}")
            article_lines.append("")

        user_prompt = _USER_PROMPT_TEMPLATE.format(
            today=today,
            existing_catalysts=existing_text,
            articles="\n".join(article_lines),
        )

        system_prompt = _SYSTEM_PROMPT.format(today=today)

        # LLM call
        try:
            response = self.client.messages.create(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )

            # Track costs
            usage = response.usage
            record_usage(
                agent=AGENT_NAME,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                model=MODEL,
            )

            # Extract text
            response_text = ""
            for block in response.content:
                if block.type == "text":
                    response_text += block.text

        except anthropic.APIStatusError as e:
            log.error(
                "API error during event detection: %s (status %d)",
                e.message,
                e.status_code,
            )
            return []
        except anthropic.APIConnectionError as e:
            log.error("Connection error during event detection: %s", e)
            return []
        except Exception as e:
            log.error("Unexpected error during event detection: %s", e, exc_info=True)
            return []

        # Parse JSON response
        new_events = self._parse_response(response_text)

        # Server-side dedup (LLM may still produce duplicates)
        new_events = self._deduplicate(new_events, existing_catalysts)

        log.info(
            "Detected %d new events from %d articles",
            len(new_events),
            len(filtered),
        )
        return new_events

    # ── private helpers ─────────────────────────────────

    def _filter_articles(self, articles: list[dict]) -> list[dict]:
        """Keep only articles with relevance >= 7 OR policy/geopolitical category.

        Args:
            articles: Raw articles from news_desk.

        Returns:
            Filtered list of articles worth scanning for future events.
        """
        filtered: list[dict] = []
        for art in articles:
            relevance = art.get("relevance", 0)
            category = str(art.get("category", "")).lower()
            if relevance >= 7 or category in _POLICY_CATEGORIES:
                filtered.append(art)
        return filtered

    def _parse_response(self, response_text: str) -> list[dict]:
        """Parse the LLM JSON response into a list of event dicts.

        Handles markdown code fences and partial JSON gracefully.

        Args:
            response_text: Raw text from the LLM.

        Returns:
            List of parsed event dicts.
        """
        text = response_text.strip()
        if not text:
            return []

        # Strip markdown code fences if present
        if text.startswith("```"):
            first_newline = text.index("\n")
            text = text[first_newline + 1:]
        if text.endswith("```"):
            text = text[:-3].strip()

        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as e:
            log.error("Failed to parse event detection JSON: %s", e)
            log.debug("Response text: %s", text[:500])
            return []

        if not isinstance(parsed, list):
            log.error("Expected JSON array, got %s", type(parsed).__name__)
            return []

        # Validate and normalise each event
        validated: list[dict] = []
        for item in parsed:
            if not isinstance(item, dict):
                continue
            event = self._validate_event(item)
            if event is not None:
                validated.append(event)

        return validated

    def _validate_event(self, raw: dict) -> dict | None:
        """Validate and normalise a single event dict from the LLM.

        Returns None if the event is invalid (missing required fields or
        event_date is in the past).
        """
        event_type = str(raw.get("event_type", "")).lower()
        if event_type not in self.SUPPORTED_TYPES:
            log.debug("Skipping unsupported event_type: %s", event_type)
            return None

        event_date = str(raw.get("event_date", "")).strip()
        if not event_date:
            return None

        # Validate date format and ensure it's in the future
        try:
            parsed_date = datetime.strptime(event_date, "%Y-%m-%d").date()
        except ValueError:
            log.debug("Skipping event with invalid date: %s", event_date)
            return None

        if parsed_date < date.today():
            log.debug("Skipping past event: %s on %s", raw.get("description"), event_date)
            return None

        ticker = str(raw.get("ticker", "BROAD_MARKET")).upper()
        description = str(raw.get("description", "")).strip()
        if not description:
            return None

        impact = str(raw.get("impact_estimate", "medium")).lower()
        if impact not in ("high", "medium", "low"):
            impact = "medium"

        confidence = raw.get("confidence", 0.5)
        try:
            confidence = max(0.0, min(1.0, float(confidence)))
        except (TypeError, ValueError):
            confidence = 0.5

        affected_tickers = raw.get("affected_tickers", [])
        if not isinstance(affected_tickers, list):
            affected_tickers = []
        affected_tickers = [str(t).upper() for t in affected_tickers]

        return {
            "event_type": event_type,
            "ticker": ticker,
            "event_date": event_date,
            "description": description,
            "impact_estimate": impact,
            "source": str(raw.get("source", "")),
            "source_article": str(raw.get("source_article", "")),
            "confidence": confidence,
            "affected_tickers": affected_tickers,
            "category": event_type,  # mirror event_type as category
        }

    def _deduplicate(
        self,
        new_events: list[dict],
        existing_catalysts: list[dict],
    ) -> list[dict]:
        """Remove events that match an existing catalyst.

        A match is defined as same event_type, same ticker, and event_date
        within 3 days of an existing catalyst.

        Args:
            new_events: Freshly extracted events.
            existing_catalysts: Already-known catalysts from the DB.

        Returns:
            De-duplicated list of genuinely new events.
        """
        if not existing_catalysts:
            return new_events

        # Pre-parse existing catalyst dates for fast comparison
        existing_keys: list[tuple[str, str, date]] = []
        for cat in existing_catalysts:
            try:
                cat_date = datetime.strptime(
                    str(cat.get("event_date", "")), "%Y-%m-%d"
                ).date()
            except ValueError:
                continue
            existing_keys.append((
                str(cat.get("event_type", "")).lower(),
                str(cat.get("ticker", "")).upper(),
                cat_date,
            ))

        kept: list[dict] = []
        for event in new_events:
            try:
                ev_date = datetime.strptime(event["event_date"], "%Y-%m-%d").date()
            except ValueError:
                kept.append(event)
                continue

            ev_type = event["event_type"].lower()
            ev_ticker = event["ticker"].upper()

            is_dup = False
            for ex_type, ex_ticker, ex_date in existing_keys:
                if (
                    ev_type == ex_type
                    and ev_ticker == ex_ticker
                    and abs((ev_date - ex_date).days) <= 3
                ):
                    is_dup = True
                    log.debug(
                        "Dedup: skipping '%s' (%s %s) — matches existing catalyst on %s",
                        event["description"],
                        ev_type,
                        ev_ticker,
                        ex_date.isoformat(),
                    )
                    break

            if not is_dup:
                kept.append(event)

        if len(kept) < len(new_events):
            log.info(
                "Deduplication removed %d events (%d kept)",
                len(new_events) - len(kept),
                len(kept),
            )
        return kept


# ═══════════════════════════════════════════════════════
# PERSISTENCE
# ═══════════════════════════════════════════════════════

def save_detected_events(events: list[dict]) -> int:
    """Save detected events to the catalysts table in advisor_memory.db.

    Uses INSERT OR IGNORE so duplicate (ticker, event_type, event_date)
    rows are silently skipped.

    Args:
        events: List of event dicts from EventDetector.extract_events().

    Returns:
        Number of events actually inserted.
    """
    if not events:
        return 0

    from src.advisor.memory import _get_db

    conn = _get_db()
    now = datetime.now().isoformat()
    inserted = 0

    # Ensure catalysts table exists (catalyst_tracker creates it, but be safe)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS catalysts (
            id INTEGER PRIMARY KEY,
            ticker TEXT NOT NULL,
            event_type TEXT NOT NULL,
            event_date TEXT,
            description TEXT NOT NULL,
            impact_estimate TEXT DEFAULT 'medium',
            source TEXT,
            status TEXT DEFAULT 'upcoming',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(ticker, event_type, event_date)
        )
    """)

    for event in events:
        try:
            conn.execute(
                """
                INSERT OR IGNORE INTO catalysts
                (ticker, event_type, event_date, description, impact_estimate,
                 source, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 'upcoming', ?, ?)
                """,
                (
                    event["ticker"],
                    event["event_type"],
                    event["event_date"],
                    event["description"],
                    event["impact_estimate"],
                    event.get("source", "event_detector"),
                    now,
                    now,
                ),
            )
            if conn.execute("SELECT changes()").fetchone()[0] > 0:
                inserted += 1
        except Exception:
            log.debug(
                "Failed to save event: %s %s %s",
                event.get("ticker"),
                event.get("event_type"),
                event.get("event_date"),
            )

    conn.commit()
    conn.close()

    log.info("Saved %d/%d detected events to catalysts table", inserted, len(events))
    return inserted


# ═══════════════════════════════════════════════════════
# CONVENIENCE WRAPPER
# ═══════════════════════════════════════════════════════

def run_event_detection(
    articles: list[dict],
    existing_catalysts: list[dict],
) -> list[dict]:
    """End-to-end event detection: extract, save, return new events.

    Creates an EventDetector, extracts future-dated events from the
    provided articles, saves them to the catalysts DB, and returns
    the list of newly detected events.

    Args:
        articles: News articles from news_desk.
        existing_catalysts: Already-known catalysts for deduplication.

    Returns:
        List of newly detected and saved event dicts.
    """
    detector = EventDetector()
    new_events = detector.extract_events(articles, existing_catalysts)
    if new_events:
        save_detected_events(new_events)
    return new_events
