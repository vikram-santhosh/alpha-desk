# AlphaDesk — Project Overview (authoritative reference for humans and LLMs)

> **Read this first.** It is the single most complete description of the
> consolidated AlphaDesk codebase. If anything elsewhere contradicts it, this
> file and [`docs/ALPHADESK.md`](ALPHADESK.md) (the short charter) win.
> Last updated: 2026-06-24.

---

## 0. TL;DR (30 seconds)

AlphaDesk is a **personal, local-first, multi-agent investment-research tool**.
It ingests many independent sources (Reddit, financial news, earnings calls,
13F filings, prediction markets, YouTube, Substack, valuation models), and turns
them into **two products**:

1. **A daily brief** — a narrative research report delivered via Telegram/email
   (the legacy "advisor pipeline").
2. **Top Buys** — a deterministic, breadth-gated **0–10 conviction score** per
   ticker, driven by how many independent platforms corroborate the name (the
   newer "score engine").

A **FastAPI backend** (`src/api/app.py`) serves both to a **React dashboard**.
All LLM inference goes through **OpenRouter** and is currently restricted to
three reliable models: **GLM 5.2, Kimi K2.6, and DeepSeek V4**.

It is **not** a SaaS product, **not** an allocator/position-sizer for live money,
**not** a brokerage integration, and **not** financial advice. It is a research
aggregator / second opinion.

---

## 1. How the codebase got here (essential context)

AlphaDesk existed as **two diverging git forks** that shared a common ancestor
(`f378909`):

- **`~/Documents/New project`** — added a polished "glass cockpit" web frontend,
  a rich FastAPI backend, a multi-model **council** (OpenRouter streaming),
  **position sizing**, **weighted evidence scoring**, **web search**, and
  prediction-market macro. (~29 commits.)
- **`~/workspace/alpha-desk`** (this repo, now canonical) — added the
  deterministic **score engine** + sensor plugins, score **calibration**, the
  **OpenRouter** LLM backend, and the project **charter**. (~7 commits.)

They were **merged** (3-way git merge, commit `0481c06`) into this repo, which
is now **home**. After the merge the backend was unified (`9ee2aac`) and all
inference was restricted to an allowlisted model set (`e9ee401`).

**Consequence you must know:** the merge left **two frontends** in the tree
(`web/` and `dashboard/`). Only **one backend** is canonical (`src/api/app.py`).
Reconciling the two frontends into one is the main **open task** (see §12).

---

## 2. Repository layout

```
alpha-desk/
├── run_daily.py          # entry: daily advisor pipeline (brief) — CLI / Cloud Run job
├── run_api.py            # entry: starts the FastAPI backend with .env loaded (USE THIS)
├── score.py              # entry: score-engine CLI (Top Buys), incl. --dry-run
├── server.py             # DEPRECATED minimal score-only backend, superseded by src/api/app.py
├── config/               # all YAML configuration (see §11)
├── data/                 # SQLite DBs (gitignored) — see §6
├── docs/                 # this file, the charter, plans, audits, handoffs
├── prompts/              # externalized LLM prompt templates + architecture notes
├── src/
│   ├── api/app.py        # THE backend: FastAPI, all /api/* routes (see §8)
│   ├── advisor/          # the daily multi-agent pipeline + memory (see §5, §7)
│   ├── score_engine/     # deterministic Top Buys scorer + sensors (see §10)
│   ├── alpha_scout/      # idea discovery / candidate sourcing / screening
│   ├── news_desk/        # news ingestion (Finnhub + NewsAPI) + LLM analysis
│   ├── street_ear/       # Reddit ingestion + sentiment (OAuth-gated; see §13)
│   ├── substack_ear/     # Substack ingestion (RSS) + thesis extraction
│   ├── youtube_ear/      # YouTube transcript ingestion + analysis
│   ├── sector_scanner/   # broad thematic sector news
│   ├── portfolio_analyst/# price/fundamental fetchers, technicals
│   ├── report/           # report rendering
│   ├── backtest/         # backtest framework
│   ├── shared/           # cross-cutting infra (see §3, §4)
│   └── utils/            # logging etc.
├── web/                  # glass-cockpit React frontend (New project's; the nicer one)
├── dashboard/            # React frontend that has the Top Buys /scout view (mine)
├── tests/                # 393 tests (pytest)
└── scratch/              # throwaway harnesses (gitignored)
```

**Two ignored files that hold secrets and must never be committed:**
`.env` (real API keys, loaded at runtime) and `secrets.txt` (a notes file).
Both are in `.gitignore`.

---

## 3. The data layer (SQLite + an agent bus)

Everything persists to **SQLite** files under `data/` (path overridable via the
`ALPHADESK_DATA_DIR` env var; **bound at import time** in each module, so set it
*before* importing `src.*`). The DBs:

| DB file | Owner module | Holds |
|---|---|---|
| `advisor_memory.db` | `src/advisor/memory.py` | holdings, snapshots, macro theses, conviction list, earnings calls, prediction markets, brief history, outcomes |
| `agent_bus.db` | `src/shared/agent_bus.py` | inter-agent pub/sub signals (the integration backbone) |
| `score_engine.db` | `src/score_engine/snapshot.py` | frozen signal snapshots + computed scores |
| `cost_tracker.db` | `src/shared/cost_tracker.py` | per-run LLM cost + daily cap |
| `cockpit_runs.db` | `src/api/run_store.py` | persisted council + idea-scout runs (for the dashboard) |
| `street_ear_tracker.db`, `substack_tracker.db`, `narrative_tracker.db` | respective ear modules | mention/narrative tracking over time |

### The agent bus (`src/shared/agent_bus.py`)
A SQLite pub/sub. Agents `publish(signal_type, source_agent, payload)`; others
`consume()` / `get_recent_signals()`. This is how ingestion agents feed both the
daily pipeline **and** the score engine. Signal types include `breaking_news`,
`sector_news`, `macro_event`, `expert_thesis`, `expert_analysis`,
`unusual_mentions`, etc. Payloads carry `affected_tickers`/`tickers` and a
`sentiment` in −2..+2.

---

## 4. The LLM layer — OpenRouter allowlist

**All inference is routed through OpenRouter (one API key) and restricted to an
allowlist. Nothing else can be called by default.** This is enforced in two
places:

### `src/shared/gemini_compat.py` (the agent choke point)
Exposes an Anthropic-SDK-shaped client: `Anthropic().messages.create(model=…)`.
`_detect_backend()` prefers **OpenRouter** when `OPENROUTER_API_KEY` is set
(falls back to Anthropic, then Gemini). `_resolve_openrouter_model()` is a hard
**allowlist**:

| Caller passes… | Resolves to |
|---|---|
| `claude-opus-*` (heavy/synthesis role) | `moonshotai/kimi-k2.6` |
| `claude-sonnet-*` / anything unmatched | `z-ai/glm-5.2` |
| `claude-haiku-*` (bulk/extraction role) | `z-ai/glm-5.2` |
| a raw slug already in the allowed set | itself |
| **any other slug or bare name** | `z-ai/glm-5.2` (safe collapse) |

`ALLOWED_OPENROUTER_MODELS = {kimi-k2.6, glm-5.2, deepseek-v4-pro}`.
Role slugs are overridable via env (`OPENROUTER_OPUS/_SONNET/_HAIKU/_DEEPSEEK`).

### `src/api/app.py` (the council/ideas choke point)
`DEFAULT_OPENROUTER_ANALYSIS_MODELS` = the reliable council roster.
`OPENROUTER_MODEL_ALIASES` remaps legacy GCP/Claude/Grok/Gemini ids onto the
allowlist. `_non_opus_openrouter_model` forces the fusion judge to GLM 5.2.

### Model → role mapping (current)
- **GLM 5.2** (`z-ai/glm-5.2`) — standard analysis (most agents) + fusion judge + council seat
- **Kimi K2.6** (`moonshotai/kimi-k2.6`) — heavy synthesis + council seat
- **DeepSeek V4** (`deepseek/deepseek-v4-pro`) — council seat

**Cost** is tracked per run in `cost_tracker.db` with a daily cap.
**Determinism note:** the *score engine* bars LLMs from the scoring/ranking path
entirely (extraction sensors may use an LLM, but scoring is pure arithmetic).

---

## 5. The two subsystems

### (A) Daily advisor pipeline — the narrative brief
Orchestrated by `src/advisor/run_orchestrator.py` → `RunOrchestrator.execute(run_type)`.
Run types: `morning_full` (full pipeline → `src/advisor/main.py::_run_pipeline`),
`evening_wrap` (delta vs morning, Telegram-only), `weekend` (review), plus a
`score` mode that calls the score engine. Profiles/budgets live in
`run_profile.py`. The pipeline gathers from all ingestion agents, runs an
**analyst committee** (`analyst_committee.py`) + **deep research**
(`deep_researcher.py`), maintains **macro theses**, **conviction list**, and
**moonshots**, computes **valuation gates** (`valuation_engine.py`), optional
**position sizing** (`position_sizer.py`), and renders a structured brief
(`formatter.py`, `verbose_formatter.py`) delivered via Telegram/email.

### (B) Score engine — Top Buys (deterministic 0–10)
`src/score_engine/`. Sensors (plugins) each cast **one vote per ticker** as a
`TickerSignal`; votes are frozen to a **snapshot**; a **pure aggregator**
produces a breadth-gated **0–10** `TickerScore`; results render as "Top Buys".
Full detail in §10. **This is the part that is deterministic and most
trustworthy**, and the strategic direction (see the charter): the score engine
is meant to become the unified scoring path; the advisor pipeline's older
scoring (conviction list, alpha_scout composite) is being consolidated into it.

---

## 6. The backend API (`src/api/app.py`)

Start it with **`python run_api.py`** (binds `127.0.0.1:8000`, loads `.env`).
**Do not** add `load_dotenv()` to `app.py` itself — importing the module must not
mutate the environment (tests rely on this). CORS allows any localhost origin.

| Method + Route | Purpose |
|---|---|
| `GET /api/score/top-buys` | latest score snapshot (fast, no LLM) |
| `POST /api/score/run` | run the score engine now (gathers sensors, ~20s) |
| `GET /api/council/models` | the current OpenRouter council roster |
| `POST /api/council/run` | run the multi-model council (non-streaming); accepts optional Scout/score context fields |
| `GET /api/council/stream` | **SSE** stream of council panel→judge→verdict; accepts optional `source`, `idea_run_id`, `score_snapshot_id` |
| `GET /api/council/runs`, `/runs/latest` | persisted council runs |
| `GET /api/ideas/today` | Alpha Scout idea generation (discovery / top-buys) |
| `GET /api/ideas/runs`, `/runs/latest` | persisted idea-scout runs |
| `GET /api/portfolio` | portfolio snapshot + concentration flag |
| `GET /api/macro`, `/macro/regime`, `/macro/themes` | macro dashboard |

The council, when `OPENROUTER_API_KEY` is set, runs via the **OpenRouter
streaming path** (`_stream_openrouter_council_events`) — the allowlisted seats
stream independently with graceful per-seat degradation, then the backend
synthesizes a judge/verdict. When launched from Scout or Top Buys, the frontend
passes `source=scout&idea_run_id=...` or `source=score_engine&score_snapshot_id=...`.
The backend injects that upstream thesis/score/source context into each council
seat and requires any downgrade from a high-conviction prior to name the
disconfirming evidence.

---

## 7. The agents (`src/advisor/` + ingestion packages)

**Ingestion (the "eyes and ears"):**
- `street_ear/` — Reddit posts → ticker mentions + sentiment (needs OAuth; see §13)
- `news_desk/` — Finnhub + NewsAPI articles → relevance/sentiment/urgency, → bus
- `earnings_analyzer.py` — earnings beats/guidance/transcripts (FMP, yfinance fallback)
- `superinvestor_tracker.py` — 13F filings + insider transactions (smart money)
- `prediction_market.py` — Polymarket + Kalshi probabilities
- `youtube_ear/`, `substack_ear/`, `sector_scanner/` — expert/thematic signals
- `alpha_scout/` — candidate discovery, screening, supply-chain & moonshot sourcing

**Reasoning / synthesis:**
- `analyst_committee.py` — multi-perspective (growth/value/risk/deep-research) analysis
- `council.py` — multi-model council (GCP path for cloud; OpenRouter path is live)
- `deep_researcher.py` — multi-step research blocks
- `conviction_manager.py` — evidence test, conviction list, weighted evidence scoring
- `valuation_engine.py` — scenario target price, implied CAGR, margin of safety, investment gates
- `position_sizer.py` — recommendation sizing (role-dependent gates)
- `macro_analyst.py` / `macro_scanner.py` — macro regime + thesis tracking
- `causal_reasoner.py`, `skeptic_agent.py`, `coherence_auditor.py`, `gap_resolver.py`,
  `brief_reviewer.py`, `event_detector.py`, `catalyst_tracker.py` — quality/critique layers
- `outcome_scorer.py`, `reasoning_journal.py`, `feedback_manager.py`, `retrospective.py` —
  the learning loop (tracks whether past calls were right; feeds source trust over time)

**State / orchestration:**
- `memory.py` — the persistence layer (every module reads/writes through here)
- `run_orchestrator.py`, `run_profile.py`, `main.py` — orchestration + entry

---

## 8. The score engine in detail (`src/score_engine/`)

```
signals.py     TickerSignal (frozen), TickerScore, RunRequest, RunResult, Direction enum
weights.py     load_weights() / load_score_engine_config() from config/advisor.yaml score_engine:
sensors/
  base.py      Sensor Protocol + Registry + gather_all_votes() (parallel, health-tracked)
  _bus.py      shared agent-bus reader → TickerSignals (news/youtube/substack)
  earnings.py        EPS surprise → BULL/BEAR; tanh strength; evidence names the driver
  reddit.py          street_ear sentiment (DARK until Reddit OAuth, see §13)
  superinvestor.py   13F + insider smart-money corroboration
  valuation.py       FORWARD-LOOKING: implied CAGR + margin of safety
  news.py / youtube.py / substack.py   bus-backed sentiment
  prediction.py      prediction-market lean (deliberately mild)
aggregator.py  score_tickers(signals, weights, missing) -> list[TickerScore]   PURE
snapshot.py    freeze signals + scores (score_engine.db); re-score reproduces exactly
engine.py      run_scoring(RunRequest) -> RunResult  (gather → snapshot → aggregate → rank)
```

### The contract
```python
TickerSignal(ticker, sensor, direction: Direction, strength 0-1, confidence 0-1, evidence, as_of)
TickerScore(ticker, score 0-10, platforms_reporting[], platforms_failed[], breakdown[])
RunRequest(mode, depth, top_n, sensors|"auto", snapshot_id?, weights_version?)
RunResult(top[], snapshot_id, weights_version, diagnostics{sensors_ok, sensors_empty, sensors_failed, …})
```

### The scoring algorithm (deterministic, in `aggregator.py`)
1. **Dedup** one vote per `(ticker, sensor)` — keep highest confidence.
2. Per ticker: `raw = Σ weight[sensor] × direction.value × strength × confidence`.
3. **Conviction-weighted normalization**: divide by the confidence-weighted weight
   of only the platforms that took a **directional** stance (neutral "no view"
   votes do **not** dilute). Scale to 0–10.
4. **Breadth gate** (the product's core idea): a name needs **K independent
   platforms agreeing** to reach the top tier. `< BREADTH_MIN(2)` bull platforms
   → capped at 6.9; `< TOP_TIER_MIN(3)` → capped at 7.9; ≥3 → full range.
5. **Stable sort** `(-score, ticker)` so ties are deterministic.

### Calibration rubric (mirrored in the dashboard ScoreCard)
| Score | Tier | Meaning |
|---|---|---|
| 8.5–10 | Conviction | many independent sources strongly agree |
| 7–8.4 | Strong | clear multi-source agreement |
| 5–6.9 | Moderate | real support, watch it |
| 3–4.9 | Weak | thin or mixed |
| 0–2.9 | Avoid/none | net negative or no signal |

### Guarantees
- **Determinism:** `(snapshot_id, weights_version)` reproduces byte-identical
  scores & order. No LLM in the scoring/ranking path. (`test_score_repeatability`)
- **Breadth gate:** one loud platform cannot reach the top tier. (`test_breadth_gate`)
- **Honest degradation:** a sensor that runs but emits nothing is reported as
  `sensors_empty` ("no data"), never silently folded into a lower score.

---

## 9. Entry points / how to run

```bash
# Backend API (council, score, ideas, macro) — http://127.0.0.1:8000
python run_api.py

# Score engine CLI
python score.py --dry-run --top 10        # synthetic data, no API calls
python score.py --top 10                   # live sensors (needs API keys)
python score.py --list-snapshots
python score.py --snapshot <id>            # re-score a frozen snapshot (deterministic)

# Daily advisor pipeline (brief)
python run_daily.py --run-type=[morning_full|evening_wrap|weekend|score|auto]

# Frontend (currently the dashboard/ that has the Top Buys view)
cd dashboard && npm run dev                 # http://localhost:5173
#   the web/ glass cockpit is the nicer UI but lacks the Top Buys view (open task)

# Tests
python -m pytest -q                         # 393 tests
```

`server.py` is the **deprecated** minimal score-only backend; `src/api/app.py`
(via `run_api.py`) supersedes it and serves everything.

---

## 10. Configuration (`config/*.yaml`)

- **`advisor.yaml`** — the main config: `holdings`, `macro_theses`,
  `superinvestors` (CIKs), `strategy` (min_cagr 25%, margin_of_safety 15%,
  max_position 15%), `conviction_weights`, `evidence_weighting`, `committee`,
  `prediction_markets`, and the **`score_engine:`** block
  (`breadth_min`, `top_tier_min`, `top_n`, per-sensor `weights`).
- `portfolio.yaml` — holdings *with shares* (note: the advisor pipeline reads
  `advisor.yaml`, not this — a known historical divergence).
- `subreddits.yaml`, `substacks.yaml`, `youtube_channels.yaml`, `watchlist.yaml`,
  `scout.yaml`, `supply_chain.yaml`, `report_style.yaml`.

Secrets/keys live in **`.env`** (gitignored), read via `os.getenv`. Keys present:
FMP, Finnhub, NewsAPI, Kalshi, FRED, YouTube, Telegram, SMTP, and
**`OPENROUTER_API_KEY`** (required for all inference). Reddit OAuth keys are
**absent** (see §13). LunarCrush optional.

---

## 11. Frontends — the open reconciliation

There are **two** React frontends in the tree (both Vite + TypeScript + Tailwind +
Motion, dark glassmorphism theme). They talk to the backend through a swappable
`src/lib/api.ts` seam (defaults to `http://127.0.0.1:8000`).

| | `web/` | `dashboard/` |
|---|---|---|
| Origin | New project (the polished "glass cockpit") | this repo |
| Views | backend, council, macro, portfolio, ideas, etc. | same **+ `scout/` (Top Buys)** |
| Status | nicer UI, **no Top Buys view**, needs `npm install` | functional, **has Top Buys**, currently the one run on :5173 |

**Open task:** pick ONE (recommended: stand up `web/` as canonical and port the
`scout/TopBuysView` + `ScoreCard` into it), retire the other. Until then, run
`dashboard/` for the score view.

---

## 12. Cross-cutting guarantees & invariants

- **One backend:** `src/api/app.py`. One LLM gateway: `gemini_compat`. One
  scoring path target: `score_engine`. (Charter rule: *integrate or delete,
  nothing new in parallel.*)
- **Four models only**, enforced in two layers (§4). Verified by a resolver test
  that maps every model string in the codebase into the allowed set.
- **Determinism** of the score (§8). **Honest degradation** everywhere (failed/
  empty sensors surfaced, never hidden — this fixes audit finding F11).
- **Secrets** never leave `.env`/`secrets.txt`; both gitignored; commits are
  checked for leaks.
- **Tests:** 393, run on every change. The merge + four-model work keeps them green.

---

## 13. Known issues / open items / non-goals

**Open items (do these next, in roughly this order):**
1. **Reconcile the two frontends** (§11). Biggest source of confusion.
2. **Reddit is dark** — `street_ear` uses Reddit's public JSON, which now returns
   "private/quarantined" without OAuth. Needs `REDDIT_CLIENT_ID/SECRET` + an OAuth
   code path. The reddit sensor honestly reports "no data" meanwhile.
3. **Broaden the score universe** beyond the configured holdings, so it can
   surface names you don't already own.
4. **Concentration awareness** — flag when top names are one correlated bet.
5. **Push** `main` to origin (currently ~40 commits ahead, nothing pushed).
6. **Gemini 3.5 Flash is removed from the default roster for now** because it
   has returned incomplete structured output in live council runs.

**Explicit non-goals (do not build without re-deciding the charter):**
- Multi-tenant SaaS (`plans/saas-multi-tenant-roadmap.md` is **shelved**).
- Live allocation / executing trades / brokerage connections.
- Personalized financial advice.

---

## 14. How to extend

- **Add a score sensor:** create `src/score_engine/sensors/<x>.py` implementing
  the `Sensor` protocol (`name`, `weight_key`, `async vote(tickers, ctx)`), add a
  weight under `config/advisor.yaml` `score_engine.weights`, register it in
  `engine.py`. It auto-participates in scoring + honest degradation.
- **Add a no-LLM data source:** publish to the agent bus with `affected_tickers`
  + `sentiment`; the bus-backed sensors pick it up.
- **Add/replace a council model:** edit `DEFAULT_OPENROUTER_ANALYSIS_MODELS` in
  `src/api/app.py` and the allowlist/role slugs in `gemini_compat.py`. Keep the
  allowlist invariant unless the user changes it.
- **Change scoring behavior:** only in `aggregator.py` (keep it pure) + add a
  test. Never put an LLM in the scoring path.

---

## 15. Glossary

- **Sensor** — a plugin that reads one source and emits `TickerSignal`s.
- **Breadth gate** — the rule that high scores require multiple independent
  platforms agreeing.
- **Snapshot** — a frozen set of `TickerSignal`s; re-scoring one is reproducible.
- **Council** — a multi-model panel from the allowlisted roster that debates a ticker and a
  judge synthesizes a verdict; streamed over SSE.
- **Agent bus** — SQLite pub/sub connecting ingestion agents to consumers.
- **Conviction list / moonshots** — the advisor pipeline's persistent
  recommendation sets (being consolidated toward the score engine).
- **The OpenRouter allowlist** — GLM 5.2, Kimi K2.6, and DeepSeek V4 by default.

---

## 16. Companion docs

- [`docs/ALPHADESK.md`](ALPHADESK.md) — the short charter (what it is / isn't).
- [`docs/flow_audit.md`](flow_audit.md) — the original data-flow audit (why the
  rebuild; findings F1–F13).
- [`docs/score_engine_plan.md`](score_engine_plan.md),
  [`docs/end_to_end_plan.md`](end_to_end_plan.md) — score-engine build plans.
- `AGENTS.md`, `docs/AI_CONTEXT.md`, `docs/AI_HANDOFF.md` — earlier
  agent-handoff notes (subordinate to this file).
```
