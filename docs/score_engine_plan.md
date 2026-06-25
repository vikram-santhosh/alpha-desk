# Build Plan — Multi-Platform Conviction Score Engine

**Branch:** `feat/score-engine` (cut from `main`).
**Goal:** a **repeatable** engine that outputs a **ranked list of top buys**, each with a **0–10 confidence score** driven by **how many independent platforms corroborate the name**. Position sizing is explicitly out of scope (the score is the proxy).
**Principle:** additive, not a rewrite. Reuse `main`'s ingestion flow, signal bus, memory, formatters, and dashboard theme. The score engine is a new layer + a new run mode; the existing daily pipeline keeps working untouched.

---

## 1. Design in one screen

```
sensors (plugins)         each casts ONE vote per ticker
  reddit · x(new) · news · earnings · 13f · valuation · prediction · youtube · substack
        │  emit TickerSignal{direction, strength 0-1, confidence 0-1, evidence}
        ▼
snapshot (memory.db)      freeze the TickerSignal set  →  run = (snapshot_id → scores)
        ▼
aggregator (PURE, deterministic)
  per ticker: Σ source_weight × dir × strength × confidence,  ONE vote per platform
  breadth gate: top tier (8–10) requires K+ independent platforms agreeing
  → TickerScore{score 0-10, platforms_reporting, breakdown[]}
        ▼
rank (stable sort: score desc, ticker asc)   →  top-N buys
        ▼
narrator (LLM, temp 0, top-N only)   writes prose; NEVER changes ranking
        ▼
report (reuse main's theme)   telegram · email · dashboard "Top Buys" · json
```

**Three hard rules** (these are the product):
1. **Score = arithmetic over signals.** No LLM in the scoring/ranking path. LLMs may only *extract* a signal (temp 0, cached) or *narrate* the result.
2. **Breadth-gated.** A single loud platform cannot reach the top tier; corroboration across independent platforms is required.
3. **Reproducible.** Same snapshot ⇒ byte-identical scores and order. Failed platforms are recorded, never silently fold into a lower score.

---

## 2. Reuse map — what comes from `main`

### Flow / scaffolding (reuse, don't rebuild)
| Need | Reuse from `main` |
|---|---|
| Signal transport | `src/shared/agent_bus.py` — sensors publish here |
| Cost/budget | `src/shared/cost_tracker.py` (`set_run_context`, `record_usage`, `check_budget`) |
| Persistence / snapshots | `src/advisor/memory.py` (snapshot tables, conviction list patterns) |
| Reddit votes | `src/street_ear/` (mood/sentiment/mentions) |
| News votes | `src/news_desk/` (`top_articles`, sentiment, related_tickers) |
| Earnings votes | `src/advisor/earnings_analyzer.py` (guidance_sentiment, management_tone, surprise) |
| 13F / insider votes | `src/advisor/superinvestor_tracker.py` (`smart_money_summaries`) |
| Valuation votes | `src/advisor/valuation_engine.py` (implied_cagr, margin_of_safety) |
| Prediction votes | `src/advisor/prediction_market.py` (probability, affected_tickers) |
| YouTube / Substack votes | `src/youtube_ear/`, `src/substack_ear/` |
| Scoring seed logic | `src/advisor/conviction_manager.py` `evidence_test` / `build_evidence_items` / `BASE_WEIGHTS` (generalize, don't duplicate) |
| LLM narrator | `src/shared/agent_decorator.py` (`track_agent`, `select_model`), `prompt_loader.py` |
| Run entry pattern | `run_daily.py`, `src/advisor/run_orchestrator.py` (add a mode, don't fork a new orchestrator) |

### Theme (reuse for output parity)
- Report styling: `config/report_style.yaml`, `src/advisor/formatter.py`, `src/shared/email_template.py`, `src/shared/html_utils.py`.
- Dashboard: the existing component theme (`dashboard/src/components/ui/StatCard.tsx`, card/list components, `dashboard/src/lib/api.ts`, `types/index.ts`). The "Top Buys" view reuses these — new data, same look.

### New code (the only genuinely new surface) — `src/score_engine/`
```
src/score_engine/
  __init__.py
  signals.py        # TickerSignal dataclass + Direction enum (the contract)
  weights.py        # load source weights from config/advisor.yaml (wires the dead config)
  sensors/
    base.py         # Sensor Protocol + registry + parallel gather w/ health
    reddit.py       # thin adapter over src/street_ear
    news.py         # adapter over src/news_desk
    earnings.py     # adapter over earnings_analyzer
    superinvestor.py# adapter over superinvestor_tracker
    valuation.py    # adapter over valuation_engine
    prediction.py   # adapter over prediction_market
    youtube.py  substack.py
    x.py            # NEW platform — proves the plugin path
  aggregator.py     # PURE: signals -> TickerScore (weighted, breadth-gated, 0-10)
  snapshot.py       # persist/load signal set + scores (uses memory.db)
  engine.py         # run_scoring(req) -> ScoreResult  (gather→snapshot→aggregate→rank→narrate)
  narrator.py       # temp-0 LLM prose for top-N only
  report.py         # ScoreResult -> existing formatter/email/telegram/json theme
tests/
  test_score_repeatability.py   # same snapshot -> identical scores/order
  test_breadth_gate.py          # 1-platform spike capped; K+ platforms required for top tier
  test_degradation.py           # failed sensor recorded, not silently scored lower
```

---

## 3. Core contracts (sketch)

```python
# signals.py
class Direction(Enum): BULL = 1; NEUTRAL = 0; BEAR = -1

@dataclass(frozen=True)
class TickerSignal:
    ticker: str
    sensor: str            # "reddit" | "x" | "earnings" | ...
    direction: Direction
    strength: float        # 0..1  magnitude within this platform
    confidence: float      # 0..1  data quality / sample size
    evidence: str          # one line for the report
    as_of: str

# sensors/base.py
class Sensor(Protocol):
    name: str
    weight_key: str        # which config weight applies
    async def vote(self, tickers: list[str], ctx: dict) -> list[TickerSignal]: ...

SENSORS = Registry()       # SENSORS.register(RedditSensor()); enabled set chosen per run

# aggregator.py  (pure, deterministic)
@dataclass
class TickerScore:
    ticker: str
    score: float                 # 0..10
    platforms_reporting: list[str]
    platforms_failed: list[str]
    breakdown: list[dict]        # per-sensor contribution, for the report

def score_tickers(signals: list[TickerSignal], weights: dict,
                  breadth_min: int, missing: list[str]) -> list[TickerScore]:
    # one vote per (ticker, sensor); weighted sum; gate top tier on len(bull platforms) >= breadth_min
    # stable sort: (-score, ticker)
```

`weights` comes from `config/advisor.yaml` (`conviction_weights` / `evidence_weighting`) — building this is what finally makes those config sections live and tunable (audit F3/F5). `breadth_min` and the per-tier caps are new config under a `score_engine:` block.

---

## 4. Determinism plan (the "repeatable" requirement)

| Source of randomness | Fix |
|---|---|
| Data drifts between runs | `snapshot.py` freezes the `TickerSignal` set; a run is `(snapshot_id → scores)`; re-scoring a snapshot reproduces exactly |
| LLM nondeterminism | LLMs barred from scoring; extraction sensors run temperature 0 + cache by content hash; narrator runs after ranking and can't reorder |
| Float/order instability | aggregator uses a fixed sensor order + stable sort `(-score, ticker)`; round to fixed precision |
| Silent platform failure (audit F11) | `ScoreResult` carries `platforms_reporting`/`platforms_failed`; breadth gate counts only reporting platforms; a missing high-weight sensor falls back to last snapshot vote or excludes the name from the top tier (policy flag) |
| Learned source weights drift over time | weights are **versioned**; a run pins a `weights_version`; re-learning runs on a schedule (not mid-run); `(snapshot, weights_version)` reproduces byte-identically |

**Definition of done for "repeatable":** `test_score_repeatability.py` runs the engine twice on one snapshot and asserts identical scores and ordering, in CI from Phase 1 on.

---

## 5. Phased build (each phase ends runnable + tested)

**Phase 0 — Scaffold (0.5 day).** Create `src/score_engine/` package, `TickerSignal`, `Sensor` base + registry, `weights.py` reading `config/advisor.yaml`. Add `score_engine:` config block (`breadth_min`, `top_n`, per-tier caps, source weights). No behavior yet.

**Phase 1 — Deterministic core (1–2 days).** Implement `aggregator.score_tickers` (weighted, breadth-gated, 0–10, stable sort) + `snapshot.py`. Wire **two** sensors as adapters (earnings + reddit) over the existing agents. Ship `test_score_repeatability.py` + `test_breadth_gate.py`. **Demoable:** `python score.py --top 10` prints a ranked list with 0–10 scores and a platform breakdown, reproducible on a fixed snapshot.

**Phase 2 — Full corroboration (2 days).** Add the remaining sensors as adapters: news, 13F/insider, valuation, prediction, youtube, substack. Each is one file. Tune source weights from config (smart money + guidance > Reddit). Now a name needs real cross-platform agreement to score high.

**Phase 3 — Honest degradation + persistence (1 day).** `platforms_reporting`/`failed` surfaced on every score; last-good fallback; `test_degradation.py`. Persist runs so scores are queryable and comparable over time.

**Phase 4 — Output in main's theme (1–2 days).** `report.py` renders `ScoreResult` through the existing `formatter`/`email_template`/Telegram style; add a dashboard **"Top Buys"** view reusing `StatCard`/card components and the existing API client. `narrator.py` (temp 0) writes the one-line rationale for the top-N only.

**Phase 5 — Prove the plugin path (0.5 day).** Implement `x.py` (X/Twitter) as a brand-new platform; registering it should raise the achievable score of names X corroborates — with zero changes to the aggregator or orchestrator. Optional: add day-to-day **score hysteresis** (smoothing) if low churn is wanted.

**Phase 6 — User-extensible sources + learned weights (3–4 days).** The "evolve with me" track (see §8): generic RSS + declarative API sensors so most new sources are no-code, a `/source add` flow, signal provenance recording, and per-source scorecards that turn outcomes into **learned, versioned weights**. Built on the existing outcome-tracking infra.

---

## 6. Entry point & integration

- **CLI:** `python score.py --top 10 [--snapshot <id>]` — primary surface.
- **Run mode:** add `mode="score"` to `RunOrchestrator` so `run_daily.py --run-type=score` works alongside existing types (reuse the run-context/cost wrapper; don't fork an orchestrator).
- **Dashboard:** the "Run" button hits an endpoint that calls `engine.run_scoring`; the "Top Buys" view renders `ScoreResult` in the current theme.
- **Existing daily pipeline:** untouched. The score engine reads the same sensors/bus; it does not modify `_run_pipeline`.

---

## 7. Audit findings folded into this build

| Finding | Handling here |
|---|---|
| F3 `conviction_weights` ignored / F5 `evidence_weighting` dead | **Fixed by construction** — `weights.py` is the score's source weights; the config becomes live + tunable |
| F11 silent degradation | **Fixed** — `platforms_reporting/failed` + fallback; degradation is visible and reproducible |
| F6 earnings/13F reach synthesis | **Partially moot** — they feed the *score* directly via their sensors; narrative is secondary now |
| F7 prediction joins only mega-caps | **Noted** — limits breadth for small caps; flagged in the prediction sensor |
| F1 sizing, F2 macro-thesis status | **Deferred** — out of scope for the score-first product |

---

## 8. Evolve-with-me — user-extensible sources + learned weights

Two separable capabilities. (A) is mostly plumbing you already have; (B) is what makes sources *yours over time*.

### (A) Adding a source — friction ladder (most of it no-code)
| You found… | How you add it | Code? |
|---|---|---|
| Substack / subreddit / YouTube channel | append a line to `config/substacks.yaml` / `subreddits.yaml` / `youtube_channels.yaml` (exist today) | none |
| Any blog/newsletter/site with a feed | append a URL to **`config/feeds.yaml`** → generic RSS sensor | none |
| X account, Telegram channel | append to `config/x_accounts.yaml` (once that sensor exists) | none |
| JSON API with tickers + a field | a **`SourceSpec`** entry (below) → generic declarative sensor | none |
| Novel modality (Discord, podcast audio, bespoke feed) | one new `Sensor` plugin file | one file |

```python
# SourceSpec — declarative, no-code source definition
@dataclass
class SourceSpec:
    name: str                 # "substack:goodinvestor"
    type: str                 # "rss" | "api" | "x" | ...
    url: str
    auth: str | None = None
    items_path: str = ""      # JSON path to the list of items (api)
    ticker_field: str = ""    # where the ticker lives
    signal_field: str = ""    # field → direction/strength, or an extractor name
    default_weight: float = PROBATION   # cold-start trust
```

**Conversational add** (low friction = "share it and it learns"):
```
/source add https://goodinvestor.substack.com
  → fetch once, show "parsed 8 posts → votes NVDA(+) TSM(+), source=substack:goodinvestor, weight=PROBATION"
  → confirm → persisted to the source registry, live next run
```

### (B) Earning trust — sources learn their weight from outcomes
```
share ─► ingest (TickerSignal.source) ─► score (provenance recorded)
   ▲                                              │
 re-weight (versioned) ◄─ source scorecard ◄─ attribute outcome ◄─ name plays out (horizon)
```
- Every signal already carries `source`; when a name is scored we persist **which sources voted and how hard** (provenance).
- As scored names resolve over the outcome horizon, credit/debit is attributed back to each contributing source → a **per-source scorecard** (hit rate, calibration, sample size). Reuses `src/advisor/outcome_scorer.py`, `reasoning_journal.py`, `recommendation_outcomes`.
- `learned_weight = prior + evidence` with shrinkage: a new source starts on **probation** and earns/loses trust as calls resolve. The **breadth gate** already stops an unproven source from pushing a name into the top tier, so a bad new source can't do damage while it's young.
- Learning is implicit (outcomes) **and** explicit (`/source trust <name> down` via `feedback_manager.py`).
- **Visible surface:** source scorecard (`goodinvestor: 14 calls, 71% hit, weight 0.8 ↑`) + per-score provenance (`NVDA 9/10 — vetted by earnings, 13F, goodinvestor, X`).

**Honest constraint:** trust accrues over the outcome horizon (weeks), not instantly — Day 1 a new source is a corroborator at probation weight, not an oracle. That *is* "evolve with me."

---

## 9. Housekeeping

- `docs/flow_audit.md` is kept on this branch as reference (it justifies the priorities above).
- `scratch/` (audit harness) should be added to `.gitignore` or removed before the first PR.
- First PR target: **Phases 0–1** (scaffold + deterministic core + repeatability test) — the smallest slice that produces a real, reproducible 0–10 ranked buy list.
