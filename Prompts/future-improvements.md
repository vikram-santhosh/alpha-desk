# AlphaDesk Future Improvements

**Created:** 2026-02-21
**Last updated:** 2026-02-21

Items discovered during the full-system review (architect, code reviewer, QA, investment advisor, quant).

---

## Latest Pipeline Run — 2026-02-21 23:27

### 3 Trim Actions Recommended (all concentration-driven)

| Ticker | Position % | Max Allowed | Reason |
|--------|-----------|-------------|--------|
| **AMZN** | 33.9% | 15% | More than 2x the cap. Thesis (AWS re-acceleration) is intact — this is pure concentration risk, not thesis-driven. Consider reducing to 18-20% over 2-3 weeks. |
| **RBRK** | 25.5% | 15% | Single-name cybersecurity bet at 25% of portfolio. Thesis (Zero Trust adoption) is intact but position size is aggressive for a $7B company. |
| **GOOG** | 16.3% | 15% | Marginally above cap. Cloud margin inflection thesis intact. Low urgency — a small trim to 14-15% is sufficient. |

**Note:** All three trims are concentration-based, not thesis-based. No thesis is weakening or invalidated. The strategy engine correctly identifies these as position management issues, not sell signals.

### Other Observations
- **Conviction list:** Empty (correct — min_evidence_sources raised to 3, no candidates passed)
- **Moonshots:** 2 active (BKNG/CRM removed after $50B market cap filter)
- **Reddit mood:** bearish
- **Cost:** $11.62/day (news_desk $7.43 on Sonnet, street_ear $2.59)

---

## P0 — High Impact, Should Do Next

### 1. Correlation Risk Analysis
The portfolio has 6 holdings riding the same "Hyperscaler CapEx" thesis: NVDA, AVGO, VRT, MRVL, AMD, TSM. If CapEx disappoints, all six drop together. The system flags individual concentration (max_position_pct) but doesn't quantify portfolio-level concentration by thesis.

**What to build:** A thesis-exposure module that calculates what % of portfolio value is tied to each macro thesis. Surface it in the risk dashboard with warnings like "62% of portfolio exposed to Hyperscaler CapEx thesis."

**Files:** `src/advisor/strategy_engine.py`, `src/advisor/formatter.py`

### 2. Reddit Mood in Advisor Brief
Street Ear extracts `market_mood` (e.g., "bearish") but this never reaches the advisor output. The advisor pipeline uses Street Ear only for signals via agent_bus — the mood string is discarded.

**Fix:** In `src/advisor/main.py`, extract `street_ear_result.get("analysis", {}).get("market_mood")` and pass it to the Opus synthesis prompt and/or the macro section formatter.

### 3. Macro News Headlines in Advisor Output
Tariff/trade/Fed articles from NewsAPI flow through `news_signals` to thesis matching and holdings monitor, but the actual headlines/links are never shown in the advisor daily brief. The reader can't see what news drove the analysis unless they use the legacy `/news` command.

**Fix:** Add a "Key Headlines" subsection to the advisor formatter showing top 3-5 macro articles (from `news_desk_result.get("top_articles")`). File: `src/advisor/formatter.py`, `src/advisor/main.py`.

---

## P1 — Medium Impact

### 4. Position Sizing Guidance
Strategy engine says "trim" or "add" but never says how much. "Trim NVDA" could mean sell 5% or 50%. A real advisor gives target allocation ranges.

**What to build:** Strategy engine should output `target_weight_pct` alongside the action. E.g., "Trim NVDA from 18% to 12%" based on max_position_pct and thesis strength.

**Files:** `src/advisor/strategy_engine.py`, `src/advisor/formatter.py`

### 5. Tax-Lot Awareness
Trim recommendations don't consider tax implications. A position held 11 months vs 13 months has very different after-tax outcomes. Short-term vs long-term capital gains is a material decision factor.

**What to build:** Add `purchase_date` to portfolio config. Strategy engine checks hold period before recommending trims. If < 12 months, add a tax warning to the action.

**Files:** `config/advisor.yaml` (or `private/portfolio.yaml`), `src/advisor/strategy_engine.py`

### 6. Evidence Recency in Conviction Scoring
The 5-source evidence model doesn't distinguish stale from fresh data. A superinvestor holding from a 3-month-old 13F gets the same weight as last week's insider purchase.

**What to build:** Add a recency multiplier to evidence scoring. Sources < 2 weeks old get full weight, 2-8 weeks get 0.5x, > 8 weeks get 0.25x.

**Files:** `src/advisor/conviction_manager.py`

### 7. Substack + YouTube Integration
Full plan in `Prompts/substack-youtube-integration-plan.md`. Adds expert thesis detection (Substack RSS) and narrative amplification tracking (YouTube transcripts). Cross-source narrative propagation tracking is the highest-value component.

---

## P2 — Tech Debt / Robustness

### 8. Relative DB Paths
`DB_PATH = Path("data/advisor_memory.db")` is relative to working directory. Running from a different directory creates a fresh empty DB silently. Should use `Path(__file__).parent.parent.parent / "data" / ...` or an env var.

**Files:** `src/advisor/memory.py`, `src/shared/agent_bus.py`, `src/shared/cost_tracker.py`, `src/street_ear/tracker.py`

### 9. Signal Consumption Race Condition
The agent_bus uses `consumed = 0/1` flags. The advisor reads with `mark_consumed=False` then Portfolio Analyst consumes with `mark_consumed=True`. If Portfolio Analyst runs independently (not via advisor), it consumes signals before the advisor sees them.

**Fix:** Consider a per-consumer tracking model instead of global consumed flag, or always run via the orchestrator.

### 10. Evidence Deduplication
If the pipeline runs twice in a day, evidence gets appended again (duplicate entries). `update_macro_thesis()` appends blindly to evidence_log. Should deduplicate by date or check if today's evidence already exists.

**Files:** `src/advisor/macro_analyst.py`, `src/advisor/memory.py`

### 11. SQLite Connection Lifecycle
All memory.py functions use `conn = _get_db()` ... `conn.close()` without try/finally. Exceptions between these leak connections. Should use context manager pattern.

**Files:** `src/advisor/memory.py`, `src/shared/agent_bus.py`, `src/shared/cost_tracker.py`

### 12. BRK.B Ticker Incompatibility
Yahoo Finance uses `BRK-B` not `BRK.B`. Current config causes "possibly delisted" errors and missing price data. Need ticker normalization for Yahoo Finance API.

**Files:** `src/portfolio_analyst/price_fetcher.py` or `config/portfolio.yaml`
