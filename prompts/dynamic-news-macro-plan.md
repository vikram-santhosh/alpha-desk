# Plan: Remove Hardcoded News/Macro Filtering — Let LLM Infer Relevance
# STATUS: IMPLEMENTED (2026-02-21)

## Context

The pipeline missed tariff rollback news due to three cascading hardcoded filters:
1. NewsAPI query `"stock market OR Federal Reserve OR earnings"` — never fetches trade/policy articles
2. Macro analyst keyword matching (`_extract_relevant_macro`) — only recognizes "fed", "rate", "capex" etc.
3. Analyzer relevance scoring — no portfolio context, so macro events without ticker mentions score low

The user wants the system to fetch broadly and let the LLM decide what matters to an investment advisor — no hardcoded topic filters.

## Changes (4 files + 1 config)

---

### 1. `src/news_desk/news_fetcher.py` — Broaden news acquisition

**What changes:** Replace single hardcoded query with multiple broad category searches.

**Line 388-395** — Replace the single `fetch_newsapi_market` call:

```python
# BEFORE (line 390-393):
market_articles = fetch_newsapi_market(
    newsapi_key,
    query="stock market OR Federal Reserve OR earnings",
)

# AFTER: Multiple broad queries covering all finance-relevant categories
# Each query costs 1 NewsAPI call. Budget: 5 calls/run × 4 runs/day = 20/day (within 100 limit)
broad_queries = [
    "economy OR inflation OR GDP OR unemployment OR recession",
    "tariff OR trade OR sanctions OR import OR export OR trade deal",
    "Federal Reserve OR interest rate OR central bank OR monetary policy",
    "earnings OR IPO OR merger OR acquisition OR stock market",
    "regulation OR SEC OR antitrust OR policy OR legislation",
]
for q in broad_queries:
    articles = fetch_newsapi_market(newsapi_key, q)
    all_articles.extend(articles)
    log.info("NewsAPI market search '%s': %d articles", q[:40], len(articles))
```

**Also change:** `fetch_newsapi_headlines` — increase `pageSize` from 20 to 50 (line 205). Top headlines are the broadest catch-all, and 50 articles is well within API limits.

**API budget impact:** Goes from 2 NewsAPI calls/run to 6 calls/run. At 4 runs/day = 24 calls/day (within 100 free-tier limit).

---

### 2. `src/news_desk/analyzer.py` — Portfolio-aware relevance scoring

**What changes:** Update the system prompt to include portfolio context and explicitly value macro events.

**Lines 25-37** — Replace `ANALYSIS_SYSTEM_PROMPT`:

```python
ANALYSIS_SYSTEM_PROMPT = """You are a financial news analyst for AlphaDesk, a personal stock portfolio intelligence system.

Analyze news articles and score each one on multiple dimensions relevant to an individual investor.

PORTFOLIO CONTEXT (use this to assess indirect impact):
{portfolio_context}

SCORING RULES:
1. **relevance** (0-10): How relevant to this investor's portfolio and market outlook?
   - 9-10: Directly affects a portfolio holding or triggers immediate action
   - 7-8: Affects portfolio sector, thesis, or macro environment significantly
   - 5-6: Relevant market/economic context worth tracking
   - 3-4: Tangentially related
   - 0-2: Not relevant
   IMPORTANT: Macro-economic events (trade policy, tariffs, central bank decisions, fiscal policy,
   geopolitical developments) that affect broad market sectors should score 7+ even if no specific
   tickers are mentioned. An investor with a tech-heavy portfolio NEEDS to know about semiconductor
   tariffs even if "NVDA" isn't in the headline.
2. **sentiment** (-2 to +2): Market sentiment implied. -2 = very bearish, +2 = very bullish.
3. **urgency** ("low", "med", "high"): "high" = breaking/market-moving. Policy changes, trade deals,
   Fed decisions, major earnings surprises are HIGH urgency.
4. **affected_tickers** (list): Tickers directly affected. Also infer indirectly affected tickers
   from the portfolio context (e.g., tariff news → semiconductor holdings).
5. **category**: One of "earnings", "macro", "sector", "company", "regulatory", "geopolitical", "market_sentiment", "other".
6. **summary**: 1-2 sentence market impact summary.

Respond with ONLY a JSON array of objects, one per article, in the same order as provided."""
```

**What changes in `_prepare_batch_prompt`** (line 40): Add portfolio context injection. The function needs to accept and format portfolio tickers + sector info.

```python
def _prepare_batch_prompt(articles: list[dict], portfolio_context: str = "") -> str:
```

**What changes in `analyze_articles`** function: Load portfolio/watchlist tickers and pass them as context to the prompt. Use the existing `get_all_tickers()` from `config_loader.py` plus sector info from holdings config.

---

### 3. `src/news_desk/analyzer.py` — Add macro_event signal publishing

**Lines 296-377** — Add a fourth signal type in `publish_signals()`:

```python
# NEW: Macro/geopolitical/regulatory events (relevance >= 6)
if category in ("macro", "geopolitical", "regulatory") and relevance >= 6:
    payload = {
        "title": article.get("title", ""),
        "url": article.get("url", ""),
        "summary": article.get("summary", ""),
        "sentiment": article.get("sentiment", 0),
        "affected_tickers": article.get("related_tickers", []),
        "source": article.get("source", ""),
        "category": category,
    }
    try:
        signal_id = publish("macro_event", AGENT_NAME, payload)
        signals.append({"id": signal_id, "type": "macro_event", "title": article.get("title", "")})
    except Exception as e:
        log.error("Failed to publish macro_event signal: %s", e)
```

---

### 4. `src/shared/agent_bus.py` — Register new signal type

**Line 21-38** — Add to `SIGNAL_TYPES`:

```python
SIGNAL_TYPES = {
    # ... existing types ...
    # News Desk signals
    "breaking_news",
    "earnings_approaching",
    "sector_news",
    "macro_event",          # NEW: macro/geopolitical/regulatory events
    # ...
}
```

---

### 5. `src/advisor/macro_analyst.py` — Remove hardcoded keyword matching

**`_extract_relevant_macro()` (lines 181-211)** — Replace entire function:

```python
def _extract_relevant_macro(thesis_title: str, macro_data: dict) -> dict:
    """Return all macro data for every thesis.

    Previously filtered by hardcoded keywords, but the macro dataset is only
    ~6 indicators — the token cost of including all is negligible, and filtering
    caused blind spots (e.g., missing tariff impact on growth theses).
    """
    return {k: v for k, v in macro_data.items() if k not in ("fetched_at", "date")}
```

This was the fallback behavior anyway (lines 206-209). Now it's the default. No more keyword gating.

**`_match_news_to_thesis()` (lines 214-251)** — Make matching more inclusive:

The current function splits thesis title into words and does word overlap. This fails for news topics not in the title. Change to: include ALL macro/geopolitical/regulatory news for every thesis, since these are broadly relevant, plus keep the keyword/ticker matching for more specific categories.

```python
def _match_news_to_thesis(thesis_title: str, affected_tickers: list[str],
                          news_signals: list[dict]) -> list[dict]:
    """Find news signals relevant to a macro thesis.

    Macro/geopolitical/regulatory news is included for ALL theses (it's broadly relevant).
    Other news is matched by keyword overlap or ticker intersection.
    """
    title_lower = thesis_title.lower()
    keywords = [w for w in title_lower.split() if len(w) > 3]
    matched = []

    for signal in news_signals:
        headline = (signal.get("headline") or signal.get("title", "")).lower()
        signal_tickers = [t.upper() for t in (signal.get("tickers") or signal.get("affected_tickers") or [])]
        category = (signal.get("category") or "").lower()

        # Macro/geopolitical/regulatory news is relevant to ALL theses
        if category in ("macro", "geopolitical", "regulatory"):
            matched.append({...signal data..., "match_reason": "macro_broad"})
            continue

        # Keyword match (existing logic)
        if any(kw in headline for kw in keywords):
            matched.append({...signal data..., "match_reason": "keyword"})
            continue

        # Ticker match (existing logic)
        if affected_tickers and signal_tickers:
            if set(t.upper() for t in affected_tickers) & set(signal_tickers):
                matched.append({...signal data..., "match_reason": "ticker"})
                continue

    return matched[:15]  # Increase from 10 to 15 to accommodate broader matching
```

---

### 6. `src/advisor/main.py` — Consume macro_event signals

**Line 159** — The advisor already reads all signals via `consume(mark_consumed=False)`. The macro_event signals will automatically flow through because `consume()` returns all unconsumed signals regardless of type. No change needed here.

**Lines 238-243** — `news_signals` are already passed to `update_macro_theses()`. But we should also pass the macro_event signals from the agent bus to ensure they reach the thesis matching:

```python
# After line 159
macro_signals = [s for s in agent_bus_signals if s.get("signal_type") == "macro_event"]

# Line 240 — extend news_signals with macro_event signals from bus
news_signals = news_desk_result.get("signals", [])
# Include macro_event signals that may have been published by this or previous runs
for ms in macro_signals:
    payload = ms.get("payload", {})
    news_signals.append({
        "headline": payload.get("title", ""),
        "source": payload.get("source", ""),
        "tickers": payload.get("affected_tickers", []),
        "category": payload.get("category", "macro"),
    })
```

---

## Files Modified Summary

| File | Change |
|------|--------|
| `src/news_desk/news_fetcher.py` | Replace hardcoded query with 5 broad category queries; increase headline pageSize to 50 |
| `src/news_desk/analyzer.py` | Portfolio-aware relevance prompt; add `macro_event` signal publishing |
| `src/shared/agent_bus.py` | Add `"macro_event"` to `SIGNAL_TYPES` |
| `src/advisor/macro_analyst.py` | Remove keyword filtering in `_extract_relevant_macro`; broaden `_match_news_to_thesis` |
| `src/advisor/main.py` | Pass macro_event signals to thesis matching |

## What Does NOT Change

- News Desk `main.py` orchestration — no structural changes needed
- Formatter code — no changes
- Street Ear pipeline — unaffected
- Portfolio Analyst — unaffected (already consumes all signal types)
- Alpha Scout — unaffected
- Database schemas — no changes
- Config files — no changes needed (theses can be added organically)

## Verification

1. **Run News Desk standalone** — verify broader article set (should be 80-120 articles vs current 34)
2. **Check logs** — confirm all 5 market queries execute and return articles
3. **Verify macro_event signals** — check agent_bus.db for new signal type after a run
4. **Test tariff scenario** — search for a trade/tariff article in the output; verify it scores relevance 7+ and gets published as macro_event
5. **Run full morning brief** — verify advisor synthesis mentions macro events; check daily cost stays under $20
6. **API budget check** — confirm NewsAPI calls/run = 6 (1 headline + 5 market), well within 100/day limit at 4 runs/day

## Cost Impact

- NewsAPI: 6 calls/run instead of 2 (still well within 100/day free tier)
- LLM: ~50 more articles to analyze per run = ~3 more batches of 15 = ~3 extra Opus calls = ~$0.30/run extra
- Acceptable within $20/day budget
