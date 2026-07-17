# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

AlphaDesk is a multi-agent investment-research system with two surfaces: an interactive **web cockpit** (FastAPI backend + React frontend) and a **scheduled brief pipeline**. It ingests social/news/long-form/video/portfolio/macro signals, runs a multi-model "council" and an analyst committee, and produces research output (decision support, not financial advice).

> **⚠️ Trust the code, not the prose docs.** `README.md`, `AGENTS.md`, `docs/AI_CONTEXT.md`, and several docstrings describe an **older architecture** that has been superseded. Where they conflict with the code, the code wins. Known-stale claims:
> - **LLM backend is OpenRouter, not Gemini.** All calls go through `src/shared/gemini_compat.py` (the name is legacy). "Gemini" mentions are obsolete.
> - **Delivery is the web cockpit + API, not Telegram/email.** `telegram_bot.py`, `email_reporter.py`, and the `run_daily.py` CLI have been removed.
> - **Primary store is MySQL, not SQLite.** (Exceptions below.)
> - **Frontend paths in the docs are wrong.** Docs reference `web/src/api/client.ts`, `web/src/api/types.ts`, `web/src/components/IdeaScout.tsx`, `CommandBar.tsx` — none exist. Real layout: `web/src/lib/api.ts`, `web/src/types/index.ts`, `web/src/lib/useCouncilStream.ts`, `web/src/components/<feature>/`.

## Commands

### Backend (Python 3.12)
```bash
python3 -m venv .venv && source .venv/bin/activate
python -m pip install -r requirements.txt

python run_api.py                       # FastAPI cockpit on 127.0.0.1:8000 (inits MySQL schema)
python -m pytest                        # full backend suite
python -m pytest tests/test_api_council.py -q          # one file
python -m pytest tests/test_api_council.py::test_name  # one test
ruff check src                          # lint (no committed config — uses defaults)
```

### Frontend (`web/`)
```bash
cd web
npm install
npm run dev          # Vite dev server (127.0.0.1:5173); talks to API at http://127.0.0.1:8000
npm run build        # tsc -b && vite build
npm run typecheck    # tsc --noEmit
npm test             # vitest run
```

### Full stack with MySQL
```bash
docker compose up    # app on :8000 + MySQL 8 on :3306 (creds alphadesk/alphadesk)
```

### Mock modes (free, deterministic — prefer these; live runs cost money)
- Backend: `OPENROUTER_MOCK=1` (council + idea-scout fallback), `ALPHA_SCOUT_MOCK=1` (skip Alpha Scout pipeline).
- Frontend: `VITE_USE_MOCKS=1` (serve local fixtures from `web/src/data/`); `VITE_API_BASE_URL` overrides the API origin.
- See `AGENTS.md` → "Commands" for a full mock-mode `uvicorn` invocation.

## Architecture

### LLM routing (read this first)
Every agent calls an **Anthropic-shaped** client: `from src.shared import gemini_compat as anthropic`, then `anthropic.Anthropic().messages.create(model=..., max_tokens=..., messages=[...])`. The shim in `src/shared/gemini_compat.py` routes all of it to **OpenRouter** and **clamps the model to an allowlist** (currently GLM 5.2 / Kimi K2.6 / DeepSeek V4 Pro). Legacy model names that still appear in code (e.g. `claude-opus-4-6`, `gemini-*`, `grok-*`) are **aliases** resolved onto that allowlist — they are not literal model calls. The same allowlist + aliasing is enforced again in `src/api/app.py` (`OPENROUTER_MODEL_ALIASES`) and `src/shared/model_registry.py`. Requires `OPENROUTER_API_KEY`.

### The two surfaces
1. **Cockpit API** — `src/api/app.py` (FastAPI). Pydantic models define every contract. Key routes:
   - `POST/GET /api/council/run|stream` — multi-model council (SSE streaming). Stream emits `panel_model_result` → `judge_result` → `verdict` → `done`.
   - `GET /api/ideas/today`, `/api/ideas/runs/latest` — Alpha Scout idea discovery (LLM). `GET /api/ideas/fast` — instant deterministic Top Buys from the latest score snapshot (no LLM). `GET /api/ideas/progress` — live pipeline stage status (`src/shared/scout_progress.py`, written by `src/alpha_scout/main.py::run`) for the cockpit's live stage view. Each `TopIdea` now carries an optional `debug` (`IdeaDebug`: per-dimension score×weight contributions + human-readable fundamental factors from `screener.explain_fundamental_factors` + corroboration/source) powering the Top Buys "Debug" toggle.
   - `POST /api/brief/run`, `/api/brief/runs/latest` — runs the scheduled brief pipeline on demand.
   - `POST /api/deployment/plan`, `GET /api/deployment/stream` (SSE), `/api/deployment/runs/latest` — capital-deployment report (`src/advisor/deployment_planner.py`).
   - `GET /api/score/top-buys`, `POST /api/score/run` — deterministic score engine.
   - `GET /api/portfolio`, `/api/macro*` — snapshots.
   - **Derived read-only views (no LLM, degrade to `[]`):** `GET /api/markets` (prediction-market crowd-odds via `src/advisor/prediction_market.py`), `/api/research` (library from saved council payloads — `run_store.list_council_payloads`), `/api/alerts` (portfolio-concentration breaches + DB `strategy_flags`/`mandate_breaches`), `/api/sentiment` (per-ticker bull/bear from the score-snapshot breakdown, **overlaid with real cross-platform social posts/sentiment from LunarCrush when `LUNARCRUSH_API_KEY`/`LUNAR_CRUSH_API` is set** — see `src/shared/lunarcrush.py` `get_social_posts`/`get_social_summary`/`get_top_creators`/`get_trending_social_stocks`).
   - Run results are persisted (`src/api/run_store.py`, `src/api/brief_store.py`, `src/api/deployment_store.py`) and re-served via `*/runs/latest` without re-spending.
   - **Cockpit nav = 11 views** (`web/src/components/layout/Sidebar.tsx` + routes in `web/src/App.tsx`): Daily Brief, Alpha Scout, Deploy Plan, Council, Research, Moonshots, Macro, Markets, Sentiment, Alerts, Portfolio. All real-backed; Markets/Sentiment are thin until prediction-market/Reddit social data is configured.
2. **Brief pipeline** — `src/advisor/main.py::run(run_type=...)`. Invoked through `POST /api/brief/run` (the old CLI is gone). `src/advisor/run_profile.py` defines run modes `morning_full` / `evening_wrap` / `weekend`, each with a step matrix and USD budget; `run_orchestrator.py` routes between them.

### Council flow (`/api/council/*` → `src/api/app.py` + `src/advisor/council.py`)
Fan out to N OpenRouter models in parallel → optional **cross-examination** round where each seat critiques the others → **synthesis** into panel verdicts + judge analysis + a single verdict (rating, conviction, Bull/Base/Bear scenarios). Before running, `_maybe_score_ticker_async` ensures the ticker has score-engine evidence so the council reasons over grounded signals rather than priors. Cost is tracked and a guardrail (`COUNCIL_COST_CAP_USD`) can downgrade/skip.

### Score engine (`src/score_engine/`)
Deterministic, breadth-gated ranking that feeds council context. `run_scoring()` collects `sensors/` (reddit, news, earnings, valuation, prediction, superinvestor, substack, youtube, cognition) → `signals` → `aggregator` (weighted by `weights.py`) → persisted `snapshot`. No LLM in the scoring path.

### Signal ingestion ("ears") + Alpha Scout
Source agents — `src/street_ear/` (Reddit), `news_desk/`, `substack_ear/`, `youtube_ear/`, `sector_scanner/` — analyze sources and **publish to the agent bus**. `src/alpha_scout/` discovers candidates (agent bus + supply chain + sector peers + 13F + filings + thematic + yfinance + Reddit) → screens → synthesizes → publishes discovery signals.

### Persistence — three backends (gotcha)
- **MySQL** (`src/shared/db.py` pool + `src/shared/schema.py` DDL) is the primary store: holdings, theses, `council_runs`, `idea_scout_runs`, `daily_brief_runs`, score `snapshots`, memory, etc. Schema is bootstrapped by `init_schema()` (called from `run_api.py` and app lifespan). `db.py` translates `?` placeholders to `%s`.
  - **SQLite fallback:** when PyMySQL isn't installed (typical local dev) or `ALPHADESK_DB_BACKEND=sqlite`, `db.py`/`schema.py` transparently persist everything to `data/alphadesk.db` instead (the MySQL DDL is auto-translated). MySQL stays the default whenever PyMySQL is importable, so production is unchanged. This is why local runs persist without a MySQL server.
- **SQLite under `data/`** still backs the live **agent bus** (`src/shared/agent_bus.py`) and **cost tracker** (`src/shared/cost_tracker.py`, `data/cost_tracker.db`). The MySQL schema *declares* `signals`/`api_costs` tables, but the runtime bus/cost paths are SQLite — treat this as a migration in progress, not a contradiction.

## Conventions & gotchas

- **API payloads are Pydantic** in `src/api/app.py`; mirror any change in the frontend types at `web/src/types/index.ts` and the client in `web/src/lib/api.ts`.
- **`.env` is loaded by `run_api.py`, never at import time.** Importing `src/api/app.py` (e.g. in tests) must not mutate the process environment — keep it that way.
- **Source honesty:** distinguish *validated* (used this run) vs *configured* (available, not queried) vs *unavailable* sources in output. Don't show configured sources as validated.
- **Prompts are externalized** markdown in `prompts/agents/` and `prompts/skills/`, loaded via `src/shared/prompt_loader.py`. The directory is lowercase and the Dockerfile copies it verbatim — keep filenames lowercase (case-sensitive in Docker).
- **Config** is YAML in `config/` (`advisor`, `portfolio`, `scout`, `watchlist`, `subreddits`, `substacks`, `youtube_channels`, `supply_chain`, `report_style`); private overrides via `private/portfolio.yaml` (gitignored).
- **Tests** rely on `tests/conftest.py` for an event loop and lean on mock modes; avoid adding tests that need a live MySQL or real network unless gated.
- Don't commit `data/`, `*.db`, `reports/`, `private/`, `secrets.txt`, or `.env*` (all gitignored).

## Session handoff workflow

This repo uses an append-only handoff log. Per `AGENTS.md`: before substantial work read `AGENTS.md` + the latest `docs/AI_HANDOFF.md` entry and check `git status`; afterward append a new entry to the **top** of the session log in `docs/AI_HANDOFF.md`. Never run destructive git (`reset --hard`, `checkout --`) without being asked, and preserve unrelated dirty files.
