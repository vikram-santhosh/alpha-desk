"""Thematic Scanner + Novelty Scoring for Alpha Scout v2.

Discovers emerging investment themes from news/Reddit and maps them to tickers.
Tracks candidate history for novelty scoring to penalize repeats and reward
new discoveries.
"""
from __future__ import annotations

import json
import math
from collections import Counter
from datetime import date, datetime
from typing import Any

from src.shared import gemini_compat as anthropic

from src.shared.cost_tracker import check_budget, record_usage
from src.utils.logger import get_logger

log = get_logger(__name__)

AGENT_NAME = "thematic_scanner"
MODEL = "claude-haiku-4-5"


# ═══════════════════════════════════════════════════════
# THEMATIC SCANNER
# ═══════════════════════════════════════════════════════

def scan_themes(
    news_articles: list[dict],
    reddit_themes: list[str],
    reddit_signals: list[dict],
) -> list[dict]:
    """Identify emerging investment themes from news and Reddit.

    Uses LLM to cluster signals into actionable themes with investable tickers.

    Returns list of theme dicts with: name, description, catalysts,
    investable_tickers, confidence, timeframe.
    """
    within_budget, spent, cap = check_budget()
    if not within_budget:
        log.warning("Budget exceeded — skipping thematic scan")
        return []

    # Build input context
    news_text = ""
    for article in news_articles[:20]:
        title = article.get("title", article.get("headline", ""))
        source = article.get("source", "")
        if title:
            news_text += f"- {title} ({source})\n"

    reddit_text = ""
    if reddit_themes:
        reddit_text = "Top Reddit themes: " + ", ".join(reddit_themes[:5]) + "\n"
    for signal in reddit_signals[:10]:
        payload = signal.get("payload", {})
        ticker = payload.get("ticker", "")
        msg = payload.get("message", payload.get("title", ""))
        if ticker and msg:
            reddit_text += f"- [{ticker}] {msg[:100]}\n"

    if not news_text and not reddit_text:
        log.info("No news/Reddit data for thematic scan")
        return []

    prompt = f"""You are an investment theme spotter. Given this week's top news headlines and social media themes, identify 3-5 ACTIONABLE investment themes.

NEWS HEADLINES:
{news_text or 'No news available'}

REDDIT/SOCIAL MEDIA:
{reddit_text or 'No Reddit data available'}

For each theme, respond with ONLY valid JSON:
{{
  "themes": [
    {{
      "name": "Theme Name",
      "description": "2-3 sentence description of the theme and why it's investable",
      "catalysts": ["Catalyst 1", "Catalyst 2"],
      "investable_tickers": ["TICKER1", "TICKER2", "TICKER3"],
      "confidence": "high",
      "timeframe": "6-18 months"
    }}
  ]
}}

RULES:
- Only include themes with at least 3 investable US-listed tickers
- Exclude "market going up/down" — must be specific, structural themes
- confidence: "high" if multiple sources confirm, "medium" if emerging, "low" if speculative
- Prefer themes that are EARLY (not consensus yet)
- Each theme must have at least one clear catalyst"""

    try:
        client = anthropic.Anthropic()
        response = client.messages.create(
            model=MODEL,
            max_tokens=1000,
            messages=[{"role": "user", "content": prompt}],
        )
        usage = response.usage
        record_usage(AGENT_NAME, usage.input_tokens, usage.output_tokens, model=MODEL)

        text = response.content[0].text.strip()
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()

        data = json.loads(text)
        themes = data.get("themes", [])
        log.info("Thematic scanner found %d themes", len(themes))
        return themes

    except json.JSONDecodeError:
        log.error("Thematic scanner returned invalid JSON")
        return []
    except Exception:
        log.exception("Thematic scanner failed")
        return []


def themes_to_candidates(
    themes: list[dict], existing_tickers: set[str],
) -> list[dict]:
    """Convert thematic scan results into candidate dicts for screening."""
    candidates = []
    existing_upper = {t.upper() for t in existing_tickers}

    for theme in themes:
        for ticker in theme.get("investable_tickers", []):
            ticker_upper = ticker.upper()
            if ticker_upper in existing_upper:
                continue
            candidates.append({
                "ticker": ticker,
                "source": f"thematic/{theme.get('name', 'unknown').lower().replace(' ', '_')}",
                "signal_type": "thematic_discovery",
                "signal_data": {
                    "theme": theme.get("name", ""),
                    "description": theme.get("description", ""),
                    "confidence": theme.get("confidence", "medium"),
                    "timeframe": theme.get("timeframe", ""),
                },
            })

    log.info("Converted %d themes to %d candidates", len(themes), len(candidates))
    return candidates


# ═══════════════════════════════════════════════════════
# NOVELTY SCORING
# ═══════════════════════════════════════════════════════

def _ensure_candidate_history_table():
    """Create candidate_history table if needed."""
    from src.advisor.memory import _get_db
    conn = _get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS candidate_history (
            id INTEGER PRIMARY KEY,
            ticker TEXT NOT NULL UNIQUE,
            first_seen_date TEXT NOT NULL,
            last_seen_date TEXT NOT NULL,
            times_screened INTEGER DEFAULT 1,
            times_recommended INTEGER DEFAULT 0,
            best_composite_score REAL,
            sources_seen TEXT
        )
    """)
    conn.commit()
    conn.close()


def record_candidate_screening(
    ticker: str, source: str, composite_score: float,
) -> None:
    """Record that a candidate was screened (insert or update)."""
    _ensure_candidate_history_table()
    from src.advisor.memory import _get_db
    conn = _get_db()
    today = date.today().isoformat()

    existing = conn.execute(
        "SELECT id, sources_seen, best_composite_score, times_screened FROM candidate_history WHERE ticker = ?",
        (ticker,),
    ).fetchone()

    if existing:
        sources = json.loads(existing[1] or "[]")
        if source not in sources:
            sources.append(source)
        best = max(existing[2] or 0, composite_score)
        conn.execute("""
            UPDATE candidate_history SET last_seen_date = ?, times_screened = times_screened + 1,
            best_composite_score = ?, sources_seen = ? WHERE ticker = ?
        """, (today, best, json.dumps(sources), ticker))
    else:
        conn.execute("""
            INSERT INTO candidate_history (ticker, first_seen_date, last_seen_date,
            times_screened, best_composite_score, sources_seen)
            VALUES (?, ?, ?, 1, ?, ?)
        """, (ticker, today, today, composite_score, json.dumps([source])))

    conn.commit()
    conn.close()


def get_candidate_history(ticker: str) -> dict | None:
    """Get screening history for a ticker."""
    _ensure_candidate_history_table()
    from src.advisor.memory import _get_db
    conn = _get_db()
    row = conn.execute(
        "SELECT * FROM candidate_history WHERE ticker = ?", (ticker,),
    ).fetchone()
    conn.close()
    if not row:
        return None
    cols = ["id", "ticker", "first_seen_date", "last_seen_date", "times_screened",
            "times_recommended", "best_composite_score", "sources_seen"]
    d = dict(zip(cols, row))
    d["sources_seen"] = json.loads(d["sources_seen"] or "[]")
    return d


def score_novelty(ticker: str, candidate_history: dict | None) -> int:
    """Score novelty of a candidate (0-100).

    100 = never seen before (maximum novelty)
    80 = not seen in past 4 weeks
    60 = not seen in past 2 weeks
    40 = seen recently from same source
    20 = seen frequently
    10 = recommended multiple times already (stale)
    """
    if candidate_history is None:
        return 100

    last_seen = candidate_history.get("last_seen_date", "")
    times = candidate_history.get("times_screened", 1)
    times_rec = candidate_history.get("times_recommended", 0)

    try:
        last_seen_date = datetime.strptime(last_seen, "%Y-%m-%d").date()
        days_since = (date.today() - last_seen_date).days
    except (ValueError, TypeError):
        days_since = 0

    if days_since > 28:
        return 80
    elif days_since > 14:
        return 60
    elif times_rec > 2:
        return 10
    elif times > 5:
        return 20
    else:
        return 40


# ═══════════════════════════════════════════════════════
# SOURCE DIVERSITY METRIC
# ═══════════════════════════════════════════════════════

def compute_source_diversity_index(candidates: list[dict]) -> float:
    """Compute Shannon entropy of candidate sources.

    Higher = more diverse sourcing. Target > 2.0 bits.
    """
    source_types = []
    for c in candidates:
        source = c.get("source", "unknown")
        source_type = source.split("/")[0]
        source_types.append(source_type)

    counts = Counter(source_types)
    total = len(source_types)
    if total == 0:
        return 0.0

    entropy = 0.0
    for count in counts.values():
        p = count / total
        if p > 0:
            entropy -= p * math.log2(p)

    return round(entropy, 2)
