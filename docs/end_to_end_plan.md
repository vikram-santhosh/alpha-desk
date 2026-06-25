# AlphaDesk — End-to-End Build Plan (master roadmap)

**Branch:** `feat/score-engine` (cut from `main`).
**This document** is the master plan: where we are, the target system, the full lifecycle, and the milestone-by-milestone roadmap to ship it.
**Companion docs:** [`docs/flow_audit.md`](flow_audit.md) — why we're rebuilding (the evidence); [`docs/score_engine_plan.md`](score_engine_plan.md) — component-level detail for the scoring core.

---

## 0. Goal & non-goals

**Build:** a **repeatable** engine that produces a **ranked list of top buys**, each with a **0–10 confidence score** driven by **how many independent platforms corroborate the name** — and that the user can **extend with new sources on the fly**, with each source **earning its weight from tracked outcomes**.

**Why now:** the audit ([flow_audit.md](flow_audit.md)) showed the current pipeline silently drops/corrupts signal (F1, F6, F11), ignores its own config (F3, F5), and is reached through ~6 tangled entry points. We rebuild the part that matters — the score — on clean, deterministic, extensible foundations, reusing everything in `main` that works.

**v1 success criteria (measurable):**
1. `score --top 10` returns a ranked 0–10 list with a per-name **platform breakdown**.
2. **Determinism:** same snapshot ⇒ byte-identical scores & order (CI test).
3. **Breadth:** no name reaches the top tier (8–10) without K+ independent platforms.
4. **Extensible:** common new sources (feed/Substack/subreddit/API) are **no-code**.
5. **Learns:** source weights move with tracked outcomes; a source scorecard is visible.
6. **Parity:** output renders in `main`'s existing theme (Telegram/email/dashboard).

**Out of scope for v1 (deferred, additive later):** position sizing / dollar allocation (F1), macro-thesis status (F2), the single-pass narrative brief. Sizing is a proxy for the score and comes as an add-on.

---

## 1. Target architecture (end to end)

```
callers:  CLI · dashboard "Run" · telegram · scheduler
                         │  (one contract)
                         ▼
                 run(RunRequest) ──────────────► RunResult
                         │
   ┌─────────────────────┼───────────────────────────────────────────┐
   ▼                     ▼                                             ▼
SENSORS (plugins)   each casts ONE vote/ticker          SOURCE REGISTRY (user-extensible)
 reddit·x·news·earnings·13f·valuation·prediction·yt·substack·feeds   config + /source add
   │  emit TickerSignal{dir, strength, confidence, evidence, source}
   ▼
SNAPSHOT (memory.db)   freeze signal set → run = (snapshot_id → scores)
   ▼
AGGREGATOR (pure, deterministic)   Σ weight×dir×strength×conf · breadth gate → 0–10
   ▼
RANK (stable sort)  → top-N
   ▼
NARRATOR (LLM, temp 0, top-N only)   prose; never reorders
   ▼
OUTPUT ADAPTERS (reuse main theme)   telegram · email · dashboard "Top Buys" · json
   ▼
OUTCOMES (existing infra)  names resolve over horizon
   ▼
LEARN (scheduled)  per-source scorecard → learned, VERSIONED weights ──┐
   └───────────────────────────── feeds back into AGGREGATOR weights ◄─┘
```

The legacy daily pipeline (`_run_pipeline`) stays intact; the score engine is a **new mode**, not a replacement. Entry-point unification happens incrementally (M6) — `run(RunRequest)` becomes the single front door for the score path first, then others migrate.

---

## 2. End-to-end lifecycle (three journeys)

**A run:** caller invokes `run(mode="score", depth, top_n)` → enabled sensors vote in parallel (each health-tracked) → votes frozen to a snapshot → aggregator scores every ticker (one vote/platform, breadth-gated) → stable-ranked → narrator writes one-liners for the top-N → rendered in the chosen adapter. `RunResult` carries `platforms_reporting/failed` so a degraded run is visible, never silent.

**Sharing a source:** `/source add <url>` → engine fetches once, shows what it parsed (`"8 posts → NVDA(+), TSM(+)"`), you confirm → persisted to the source registry at **probation** weight → live next run. No code for feeds/Substack/subreddit/declarative-API sources.

**Learning:** every signal is provenance-tagged (`source`); when a scored name resolves over the outcome horizon, credit/debit is attributed to each contributing source → per-source scorecard (hit rate, calibration) → a scheduled job recomputes **learned, versioned** weights → the aggregator uses them next run. A bad new source can't do damage while unproven (probation weight + breadth gate).

---

## 3. Build surface — reuse vs. new

**Reuse from `main` (flow):** `agent_bus` (transport), `memory.py` (snapshots/persistence), `cost_tracker` (budget), the ingestion agents (`street_ear`, `news_desk`, `earnings_analyzer`, `superinvestor_tracker`, `prediction_market`, `youtube_ear`, `substack_ear`), `valuation_engine`, `conviction_manager.evidence_test`/`BASE_WEIGHTS` (scoring seed), `outcome_scorer`/`reasoning_journal`/`feedback_manager` (learning loop), `agent_decorator`/`prompt_loader` (narrator).
**Reuse from `main` (theme):** `config/report_style.yaml`, `formatter.py`, `email_template.py`, `html_utils.py`; dashboard `StatCard`/card components + `lib/api.ts` + `types`.
**New:** `src/score_engine/` (contracts, sensors-as-adapters, aggregator, snapshot, engine, narrator, report), `config/feeds.yaml` + `config/score_engine:` block + source registry, dashboard "Top Buys" view. Full detail in [score_engine_plan.md](score_engine_plan.md) §2–3.

---

## 4. Stable contracts (the interfaces everything builds on)

```python
RunRequest(mode, depth, top_n, sensors|"auto", snapshot_id=None, weights_version=None)
RunResult(top: list[TickerScore], snapshot_id, weights_version, diagnostics)
TickerSignal(ticker, sensor, direction, strength 0-1, confidence 0-1, evidence, as_of)
Sensor(name, weight_key, vote(tickers, ctx) -> list[TickerSignal])      # plugin
SourceSpec(name, type, url, auth?, items_path, ticker_field, signal_field, default_weight)
TickerScore(ticker, score 0-10, platforms_reporting[], platforms_failed[], breakdown[])
```
These freeze in M0–M1 and don't churn afterward; sensors, sources, and learning all bolt onto them.

---

## 5. Cross-cutting guarantees

- **Determinism:** score = pure arithmetic over `TickerSignal`s; no LLM in scoring/ranking (extraction at temp 0 + content-hash cache; narrator after ranking). Snapshots + **versioned** weights ⇒ `(snapshot, weights_version)` reproduces exactly.
- **Breadth gate:** top tier requires K+ independent platforms; one loud source can't dominate.
- **Honest degradation (fixes F11):** failed sensors recorded; missing high-weight sensor → last-good fallback or excluded from top tier; never a silent lower score.
- **Provenance & trust:** every score keeps its per-source breakdown; weights are config at first, then **learned** from outcomes; new sources start on probation.

---

## 6. Roadmap — milestones (each ends runnable + tested)

| M | Milestone | Deliverable | Test / proof | You can now… | Est. |
|---|---|---|---|---|---|
| **M0** | Scaffold & contracts | `src/score_engine/` pkg, `TickerSignal`/`Sensor`/`SourceSpec`, `config/score_engine:` block, `weights.py` reading config | imports + config load | — | 0.5d |
| **M1** | Deterministic core | aggregator (weighted, breadth-gated, 0–10, stable sort) + `snapshot.py`; 2 sensors (earnings, reddit) | `test_score_repeatability`, `test_breadth_gate` | `score --top 10` → reproducible ranked list w/ breakdown | 1–2d |
| **M2** | Full corroboration | remaining sensors (news, 13f, valuation, prediction, yt, substack) as adapters; wire config source-weights (fixes F3/F5) | per-sensor unit tests | get scores backed by real multi-platform agreement | 2d |
| **M3** | Honest degradation + persistence | `platforms_reporting/failed`, last-good fallback, run persistence | `test_degradation` | trust that a score isn't secretly degraded; query past runs | 1d |
| **M4** | Output in main's theme | `report.py` → telegram/email/json in existing style; `narrator.py` (temp 0) top-N prose | snapshot render test | get the list delivered the way `main` already looks | 1–2d |
| **M5** | Dashboard "Top Buys" | new view reusing `StatCard`/cards + API endpoint calling `run_scoring` | UI smoke test | see top buys + provenance in the dashboard | 1–2d |
| **M6** | Single-run entry | `run(RunRequest)`; `run_daily.py --run-type=score`; dashboard "Run" → same fn | parity test vs CLI | one front door for the score path | 1d |
| **M7** | User-extensible sources | `config/feeds.yaml` + generic RSS & declarative-API sensors; `/source add` flow + registry | add-a-source test (no code) | share a new source and have it ingested same run | 2d |
| **M8** | Learned weights | provenance recording; per-source scorecards via outcome infra; scheduled versioned re-weighting; explicit `/source trust` | calibration test on synthetic outcomes | watch sources earn/lose trust over time | 2d |
| **M9** | Plugin proof + polish | `x.py` as a brand-new platform (zero core changes); optional score hysteresis | adding-a-plugin test | prove extensibility end to end | 0.5d |
| **later** | Add-ons | position sizing / $ allocation (F1), macro-thesis status (F2), narrative brief | — | — | TBD |

**Critical path:** M0 → M1 (everything depends on the deterministic core). M2–M5 parallelizable after M1. M7/M8 (extensibility + learning) depend on M1 contracts + M3 provenance. Sizing stays an explicit add-on after v1.

**First PR:** M0 + M1 — the smallest slice that prints a reproducible 0–10 ranked buy list with platform breakdowns.

---

## 7. Risks & mitigations

| Risk | Mitigation |
|---|---|
| LLM nondeterminism leaks into scores | LLMs barred from scoring; extraction temp 0 + cached; narrator post-rank |
| A newly-added source is noise | probation weight + breadth gate; learning demotes it as outcomes resolve |
| External APIs flaky | per-sensor health + last-good fallback; degradation surfaced, not hidden |
| Scope creep (sizing/macro) | explicitly deferred to "later"; v1 is score-only |
| Breaking the working daily pipeline | additive — new mode + new package; `_run_pipeline` untouched until M6 chooses to migrate |
| "Learning" feels like magic / over-promises | honest: trust accrues over the outcome horizon (weeks); Day 1 = probation corroborator |

---

## 8. Definition of done (v1)

All six §0 success criteria pass, with: green `test_score_repeatability`/`test_breadth_gate`/`test_degradation` in CI; ≥6 sensors live; at least one **no-code** source added end-to-end; one full **learn cycle** demonstrated on recorded outcomes; output shipped through Telegram/email/dashboard in the existing theme. `scratch/` gitignored/removed; `docs/flow_audit.md` retained as rationale.

---

## 9. Open decisions (settle in M0, don't block start)

- `breadth_min` K (how many platforms for the top tier) and the per-tier score caps.
- Probation weight value + shrinkage prior for learning.
- Credit-assignment for per-source learning: start with directional hit-rate, refine to Brier/calibration.
- Source-weight blend during transition: static config vs. learned (start static, blend in at M8).
