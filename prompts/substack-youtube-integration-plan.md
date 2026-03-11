# Substack & YouTube Integration Plan for AlphaDesk

**Created:** 2026-02-21
**Status:** Approved for future build
**Priority:** P0 (Substack), P1 (YouTube)
**Discord:** Skipped — high legal risk, low ROI

---

## Critical Assessment

### Why Not Just Clone the Reddit Fetcher

The original proposal treats Substack/YouTube as drop-in fetcher replacements. That misses several real problems:

1. **Tracker is useless for Substack.** Anomaly detection (`detect_anomalies`, `detect_sentiment_reversals`, `detect_multi_sub_convergence`) is built around volume metrics — `score`, `num_comments`, mention spikes vs 7-day avg. Substack has score=0, comments=0, ~3 posts/day. Nothing to spike. Zero alerts would fire.

2. **Analyzer prompt is Reddit-specific.** `analyzer.py:86` formats as `r/{sub} | score:{score} comments:{comments}`. System prompt says "retail investor sentiment analysis" and "Reddit posts." A 5,000-word macro thesis is not a Reddit post. The same prompt extracts tickers but misses the actual value — deep reasoning, macro frameworks, thesis formation.

3. **2,000-char selftext cap kills Substack.** `reddit_fetcher.py:132` caps selftext at 2,000 chars. Analyzer further truncates to 500 chars at line 82. For a 10,000-word Substack piece, you'd feed Claude the title and opening sentence and discard the analysis.

4. **"Gets smarter every day" needs design, not just more sources.** Current memory: mention counts in `mention_history`, narratives as text blobs, advisor conviction scores. No feedback loop. More inputs ≠ more intelligence. Need source quality scoring, thesis propagation tracking, signal hit-rate tracking.

### Verdict

Substack and YouTube are worth adding, but as **purpose-built agents** — not Reddit fetcher clones. They need different analyzers, different tracker logic, cross-source correlation, and a feedback mechanism.

---

## Architecture: How Sources Complement Each Other

```
SUBSTACK (48-72h lead)     Expert thesis formation, deep research
    ↓ ideas trickle down
YOUTUBE  (24-48h lead)     Analysis & commentary, broader audience
    ↓ narratives spread
REDDIT   (0-24h, real-time) Mass retail sentiment, momentum signals
```

The real value isn't three separate fetchers — it's tracking narrative propagation across these layers. A thesis published on Substack that shows up on YouTube 2 days later and then spikes on Reddit is a high-conviction signal.

---

## P0: Substack Integration

### New Files

```
src/substack_ear/
├── main.py              # Pipeline orchestrator (same pattern as street_ear)
├── substack_fetcher.py  # RSS fetcher via feedparser
├── analyzer.py          # Thesis-extraction prompt (NOT ticker-mention prompt)
├── tracker.py           # Thesis tracker (NOT volume-based anomaly detector)
└── formatter.py         # Telegram HTML output

config/substacks.yaml    # Curated newsletter list + settings
```

### Fetcher: `substack_fetcher.py`

```python
def fetch_articles() -> list[dict[str, Any]]:
    """Fetch recent articles from curated Substack newsletters via RSS."""
    # Uses feedparser library
    # RSS URL pattern: {name}.substack.com/feed
    # Returns full article HTML (not truncated)
    return [
        {
            "title": str,           # Article title
            "selftext": str,        # Full article text (HTML stripped, up to 8000 chars)
            "score": 0,             # No public metric
            "num_comments": 0,      # No public metric
            "subreddit": str,       # Publication name (e.g., "The Diff")
            "url": str,             # Article URL
            "created_utc": float,   # Published timestamp
            "author": str,          # Newsletter author
            "source_platform": "substack",
        }
    ]
```

**Key differences from Reddit fetcher:**
- RSS via `feedparser` instead of JSON API
- `selftext` capped at **8,000 chars** (not 2,000) — Substack articles are dense
- No score/comment filtering (curated list = quality control)
- Max age: 72 hours (Substack publishes less frequently)
- No rate limiting needed (RSS is lightweight)

### Config: `config/substacks.yaml`

```yaml
newsletters:
  macro:
    - name: "Kyla Scanlon"
      slug: kyla
      focus: "macro economics, labor market, fed policy"
    - name: "Apricitas Economics"
      slug: apricitas
      focus: "macro data analysis, employment, inflation"
    - name: "The Diff"
      slug: thediff
      focus: "technology, finance, business strategy"

  sector:
    - name: "Doomberg"
      slug: doomberg
      focus: "energy, commodities, industrial policy"
    - name: "Net Interest"
      slug: netinterest
      focus: "financial sector, banking, fintech"
    - name: "Fabricated Knowledge"
      slug: fabricatedknowledge
      focus: "semiconductors, technology supply chain"

  investing:
    - name: "Yet Another Value Blog"
      slug: yetanothervalueblog
      focus: "deep value, special situations"
    - name: "Mostly Borrowed Ideas"
      slug: mbi
      focus: "quality compounders, long-term investing"

settings:
  max_article_age_hours: 72
  max_article_chars: 8000
  max_articles_per_newsletter: 3
```

### Analyzer: Different Prompt Strategy

The Substack analyzer should extract **investment theses**, not just ticker mentions.

```python
SYSTEM_PROMPT = """You are a senior investment analyst reading expert financial newsletters.
Extract structured intelligence from long-form financial analysis.

Focus on:
- Investment theses (specific claims about why a stock/sector will move)
- Macro frameworks (interest rates, inflation, employment trends)
- Sector rotation calls (money moving from X to Y)
- Specific ticker mentions with the author's conviction level
- Contrarian views that differ from consensus

Do NOT treat this like social media sentiment analysis. These are expert-written pieces.
Extract the reasoning, not just the ticker."""

ANALYSIS_PROMPT = """Analyze this financial newsletter article for investment intelligence.

Publication: {publication}
Author: {author}
Title: {title}
Article:
{article_text}

Return a JSON object:
{{
  "tickers": [
    {{
      "symbol": "NVDA",
      "mentions": 1,
      "sentiment": 1.5,
      "confidence": 0.9,
      "themes": ["AI capex beneficiary"],
      "notable_quote": "The market underestimates...",
      "source_subreddits": ["{publication}"]
    }}
  ],
  "theses": [
    {{
      "title": "Hyperscaler CapEx cycle has 2 more years to run",
      "summary": "Author argues that...",
      "affected_tickers": ["NVDA", "AVGO", "VRT"],
      "conviction": "high",
      "time_horizon": "6-12 months",
      "contrarian": false
    }}
  ],
  "macro_signals": [
    {{
      "indicator": "labor market softening",
      "implication": "Fed likely to cut in Q2",
      "affected_sectors": ["financials", "real_estate"]
    }}
  ],
  "overall_themes": ["AI infrastructure spending"],
  "market_mood": "cautiously bullish"
}}"""
```

**Key difference:** Articles analyzed one-at-a-time (not batched 20-at-a-time like Reddit). Each article is dense enough to warrant individual analysis. Batch size = 1-3.

### Tracker: Thesis-Based (Not Volume-Based)

```python
# New database: data/substack_tracker.db

# Table: theses
# Stores extracted theses with timestamps for propagation tracking
CREATE TABLE theses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    source TEXT NOT NULL,          -- newsletter name
    author TEXT NOT NULL,
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    affected_tickers TEXT NOT NULL, -- JSON array
    conviction TEXT NOT NULL,       -- low/medium/high
    time_horizon TEXT,
    contrarian INTEGER DEFAULT 0,
    propagation_stage TEXT DEFAULT 'expert'  -- expert -> amplified -> mainstream
);

# Table: macro_signals
CREATE TABLE macro_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    source TEXT NOT NULL,
    indicator TEXT NOT NULL,
    implication TEXT NOT NULL,
    affected_sectors TEXT NOT NULL  -- JSON array
);
```

**No anomaly detection.** Instead:
- Track thesis publication dates
- When YouTube/Reddit later echo the same thesis → update `propagation_stage`
- Signal types: `expert_thesis`, `macro_framework`, `sector_rotation_call`

### Signal Types (add to `agent_bus.py`)

```python
SIGNAL_TYPES = {
    # ... existing types ...

    # Substack Ear signals
    "expert_thesis",           # Deep investment thesis from newsletter
    "macro_framework",         # Macro economic analysis
    "sector_rotation_call",    # Sector shift signal
}
```

### Morning Brief Integration

Add to Phase 1 (parallel with Street Ear + News Desk):

```python
# morning_brief.py
street_ear_result, news_desk_result, substack_result = await asyncio.gather(
    _run_agent("Street Ear", run_street_ear),
    _run_agent("News Desk", run_news_desk),
    _run_agent("Substack Ear", run_substack_ear),  # NEW
)
```

Add to briefing assembly:
```python
# New section in _assemble_briefing
f"📚 <b>SUBSTACK EAR — Expert Intelligence</b>",
substack_formatted,
```

### Cost Impact

- ~15 articles/day × ~3,000 tokens each = ~45,000 input tokens/run
- At Opus 4.6 pricing (~$15/MTok input) = ~$0.68/run
- Well within $20/day budget cap

### Dependencies

```
pip install feedparser
```

---

## P1: YouTube Integration

### New Files

```
src/youtube_ear/
├── main.py               # Pipeline orchestrator
├── youtube_fetcher.py    # Transcript + metadata fetcher
├── analyzer.py           # Transcript-aware analysis prompt
├── tracker.py            # Hybrid tracker (has view counts unlike Substack)
└── formatter.py          # Telegram HTML output

config/youtube_channels.yaml  # Curated channel list
```

### Fetcher: `youtube_fetcher.py`

```python
def fetch_videos() -> list[dict[str, Any]]:
    """Fetch recent video transcripts from curated finance channels."""
    # Step 1: YouTube Data API v3 → get recent video IDs per channel
    # Step 2: youtube-transcript-api → get transcript text
    # Step 3: Normalize to standard schema
    return [
        {
            "title": str,               # Video title
            "selftext": str,            # Transcript text (up to 6000 chars)
            "score": int,               # View count
            "num_comments": int,        # Comment count
            "subreddit": str,           # Channel name
            "url": str,                 # YouTube video URL
            "created_utc": float,       # Published timestamp
            "author": str,              # Channel name
            "source_platform": "youtube",
            "duration_seconds": int,    # Video length
        }
    ]
```

**Key differences from Reddit:**
- Two-step fetch: metadata via API, transcript via `youtube-transcript-api`
- `selftext` = joined transcript segments (up to 6,000 chars)
- Has real engagement metrics (views, comments) — tracker partially works
- Max age: 48 hours
- YouTube Data API v3 quota: 10,000 units/day (search=100 units, videos.list=1 unit)

### Config: `config/youtube_channels.yaml`

```yaml
channels:
  macro:
    - name: "Patrick Boyle"
      channel_id: "UCfSVfJYyDZODsKtqqh3INPA"
      focus: "macro analysis, hedge fund perspective"
    - name: "The Plain Bagel"
      channel_id: "UCFCEuCsyWP0YkP3CZ3Mr01Q"
      focus: "investing fundamentals, market analysis"

  analysis:
    - name: "Joseph Carlson"
      channel_id: "UCbta0n8i6Rljh0obO7HzG9A"
      focus: "portfolio management, stock analysis"
    - name: "Everything Money"
      channel_id: "UCKMjY8y8j5D7U2jOiJiNz9g"
      focus: "stock valuations, fundamental analysis"

settings:
  max_video_age_hours: 48
  max_transcript_chars: 6000
  max_videos_per_channel: 3
  min_view_count: 1000
  youtube_api_key_env: "YOUTUBE_API_KEY"
```

### Analyzer: Transcript-Aware Prompt

```python
SYSTEM_PROMPT = """You are a financial analyst extracting investment intelligence from video transcripts.

Transcripts may contain:
- Filler words ("um", "you know", "like") — ignore these
- Auto-generated errors — infer correct meaning from context
- Verbal hedging ("I think maybe") — assess true conviction level
- Sponsor segments — skip these entirely

Focus on substantive analysis, not presentation style."""
```

### Tracker: Hybrid Approach

YouTube has real engagement metrics (view count, comment count), so volume-based anomaly detection partially works:
- Mention spike detection: YES (view counts serve as signal strength)
- Multi-source convergence: YES (channel names serve as "subreddits")
- Sentiment reversal: YES (sentiment across multiple videos)
- Thesis extraction: Also YES (like Substack, transcripts contain deep analysis)

### Signal Types (add to `agent_bus.py`)

```python
SIGNAL_TYPES = {
    # ... existing + substack types ...

    # YouTube Ear signals
    "expert_analysis",            # Deep analysis from finance YouTuber
    "narrative_amplification",    # Thesis gaining traction (views spiking)
}
```

### Cost Impact

- ~10-15 videos/day × ~4,000 tokens each = ~50,000 input tokens/run
- ~$0.75/run with Opus
- YouTube Data API: free tier (10K quota/day) is sufficient for curated list

### Dependencies

```
pip install youtube-transcript-api google-api-python-client
```

### Environment Variables

```
YOUTUBE_API_KEY=...  # YouTube Data API v3 key (free)
```

---

## Cross-Source Intelligence: Narrative Propagation Tracker

**This is the highest-value component** — it's what turns three separate fetchers into an actual intelligence system.

### New Module: `src/shared/narrative_tracker.py`

```python
# Database: data/narrative_tracker.db

CREATE TABLE narrative_propagation (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    narrative TEXT NOT NULL,           -- Normalized narrative title
    first_seen_source TEXT NOT NULL,   -- "substack", "youtube", "reddit"
    first_seen_date TEXT NOT NULL,
    first_seen_detail TEXT NOT NULL,   -- Publication/channel name
    current_stage TEXT NOT NULL,       -- "expert" -> "amplified" -> "mainstream"
    affected_tickers TEXT NOT NULL,    -- JSON array
    stage_history TEXT NOT NULL,       -- JSON array of {stage, date, source}
    confidence REAL DEFAULT 0.5
);

CREATE TABLE signal_outcomes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id INTEGER NOT NULL,       -- References agent_bus.signals.id
    signal_type TEXT NOT NULL,
    ticker TEXT NOT NULL,
    signal_date TEXT NOT NULL,
    price_at_signal REAL,
    price_after_1d REAL,
    price_after_5d REAL,
    price_after_20d REAL,
    outcome TEXT,                      -- "correct", "incorrect", "neutral"
    FOREIGN KEY (signal_id) REFERENCES signals(id)
);

CREATE TABLE source_reliability (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_name TEXT NOT NULL,         -- Newsletter/channel/subreddit name
    source_platform TEXT NOT NULL,     -- "substack", "youtube", "reddit"
    total_signals INTEGER DEFAULT 0,
    correct_signals INTEGER DEFAULT 0,
    hit_rate REAL DEFAULT 0.0,
    avg_lead_time_hours REAL,         -- How early vs price move
    last_updated TEXT NOT NULL,
    UNIQUE(source_name, source_platform)
);
```

### How It Works

1. **Substack publishes `expert_thesis`** → narrative_tracker stores it with `stage = "expert"`
2. **YouTube publishes `narrative_amplification`** on same theme → tracker updates `stage = "amplified"`, publishes `thesis_propagation` signal
3. **Reddit's `unusual_mentions`** fires on related tickers → tracker updates `stage = "mainstream"`, publishes high-priority `thesis_confirmed` signal
4. **Price tracking** (via portfolio_analyst) records outcomes → updates `source_reliability` scores
5. **Advisor** can use `source_reliability` to weight signals dynamically

### New Signal Types

```python
SIGNAL_TYPES = {
    # ... all existing types ...

    # Narrative Tracker signals
    "thesis_propagation",     # Thesis moving from expert → amplified
    "thesis_confirmed",       # Thesis reached mainstream (all 3 sources)
    "source_quality_update",  # Source reliability score changed
}
```

---

## Memory Enhancement for "Smarter Every Day"

### What Changes in Advisor

The advisor's `conviction_weights` in `config/advisor.yaml` are currently static:

```yaml
conviction_weights:
  company_guidance: 0.30
  crowd_sentiment: 0.25
  smart_money: 0.20
  fundamentals: 0.15
  analyst_consensus: 0.10
```

With the narrative tracker's `source_reliability` data, these could become dynamic:
- Sources with higher hit rates get more weight
- Sources with longer lead times get early-signal priority
- The advisor prompt receives source reliability context

### New Memory Tables (in `advisor_memory.db`)

```sql
-- Track which theses the advisor acted on and outcomes
CREATE TABLE thesis_actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    thesis_id INTEGER,
    action_date TEXT NOT NULL,
    action_type TEXT NOT NULL,     -- "added_to_watchlist", "bought", "increased", "ignored"
    ticker TEXT NOT NULL,
    outcome_30d TEXT,              -- "profitable", "loss", "flat"
    notes TEXT
);
```

---

## Validation Plan

### Phase 1: Unit Tests

| Test | What It Validates |
|------|-------------------|
| `test_substack_fetcher.py` | RSS parsing, schema compliance, char limits |
| `test_youtube_fetcher.py` | Transcript extraction, metadata normalization |
| `test_substack_analyzer.py` | Thesis extraction, JSON schema, ticker validation |
| `test_youtube_analyzer.py` | Transcript cleaning, filler word handling |
| `test_narrative_tracker.py` | Propagation stage updates, deduplication |

### Phase 2: Integration Tests

| Test | What It Validates |
|------|-------------------|
| Run Substack Ear standalone | Full pipeline: fetch → analyze → track → publish signals |
| Run YouTube Ear standalone | Full pipeline with transcript extraction |
| Signal bus consumption | Downstream agents (Portfolio Analyst, Alpha Scout) receive new signal types |
| Morning Brief with all sources | Synthesis prompt handles 5 agents, new sections appear in output |

### Phase 3: End-to-End Validation

| Test | What It Validates |
|------|-------------------|
| Full morning brief run | All 5 agents complete, signals cross-reference, cost under $20/day |
| Narrative propagation | Manually inject a thesis → verify it tracks through stages |
| Telegram output | Verify formatting, character limits, section ordering |
| Cost tracking | Verify per-agent cost attribution for new agents |

### Phase 4: Signal Quality (Quant Review)

| Test | What It Validates |
|------|-------------------|
| Backtest Substack theses | Would last month's newsletter theses have improved decisions? |
| YouTube signal vs price | Did high-view finance videos correlate with next-day moves? |
| Cross-source correlation | Does the Substack→YouTube→Reddit chain actually predict? |

---

## Team Structure for Build Phase

| Role | Responsibility |
|------|---------------|
| **Architect** | Design narrative_tracker schema, cross-source correlation logic, memory enhancement |
| **Code Reviewer** | Verify data contract compliance between new fetchers and existing pipeline, catch integration bugs |
| **QA** | Write and run all validation phases (unit → integration → E2E), verify Telegram output |
| **Quant/Investment Analyst** | Validate signal quality, backtest thesis propagation, assess information ratio improvement |

---

## Implementation Order

```
Week 1: P0 — Substack Ear
  Day 1: substack_fetcher.py + config/substacks.yaml + unit tests
  Day 2: substack analyzer (thesis-extraction prompt) + unit tests
  Day 3: substack tracker + signal types + integration with agent_bus
  Day 4: formatter + morning_brief integration + E2E test

Week 2: P1 — YouTube Ear
  Day 1: youtube_fetcher.py + config/youtube_channels.yaml + unit tests
  Day 2: youtube analyzer (transcript-aware prompt) + unit tests
  Day 3: youtube tracker + signal types + integration
  Day 4: formatter + morning_brief integration + E2E test

Week 3: Cross-Source Intelligence
  Day 1-2: narrative_tracker.py (propagation tracking)
  Day 3: signal_outcomes + source_reliability tables
  Day 4: Advisor memory enhancement + dynamic conviction weights
  Day 5: Full system E2E validation + quant review
```

---

## Risk Mitigation

| Risk | Mitigation |
|------|-----------|
| Substack RSS changes format | feedparser handles edge cases; add schema validation |
| youtube-transcript-api breaks (undocumented endpoint) | Fallback: YouTube Data API captions endpoint (less reliable but official) |
| LLM costs spike from long articles | Cap article text at 8K chars; batch budget check before each analysis |
| Poor signal quality from new sources | Run 2 weeks in "shadow mode" (analyze but don't include in action items) |
| Narrative tracker false positives | Require semantic similarity threshold for cross-source matching, not just keyword overlap |

---

## Files That Need Modification (Existing)

| File | Change |
|------|--------|
| `src/shared/agent_bus.py` | Add new signal types to `SIGNAL_TYPES` set |
| `src/shared/morning_brief.py` | Add Substack/YouTube to Phase 1 parallel execution, add sections to assembly |
| `src/shared/morning_brief.py` | Update `_synthesize_brief` to include new agent outputs |
| `config/advisor.yaml` | Add dynamic conviction weight configuration |
| `.env.example` | Add `YOUTUBE_API_KEY` |
| `requirements.txt` | Add `feedparser`, `youtube-transcript-api`, `google-api-python-client` |
