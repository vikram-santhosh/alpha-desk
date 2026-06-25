# AlphaDesk Agent Instructions

## Project Mission

AlphaDesk is a multi-agent investment intelligence system. It ingests signals from social, news, long-form research, video, portfolio, market, macro, and discovery sources, then produces actionable research briefs and an interactive research cockpit.

The current web cockpit supports:

- Running a model council against a ticker or idea.
- Discovering top investment ideas through the Alpha Scout pipeline.
- Reviewing source validation checks for each idea-discovery run.
- Running the council on a selected discovered idea.

Research output is for decision support only. Do not present recommendations as personalized financial advice.

## Repository Structure

- `src/api/` - FastAPI surface for the web cockpit.
- `src/alpha_scout/` - Full ticker discovery pipeline: source, screen, synthesize, publish signals.
- `src/advisor/` - Advisor layer, analyst committee, macro, moonshot, catalyst, prediction-market, and brief logic.
- `src/shared/` - Shared infrastructure: config loading, agent bus, LLM compatibility shim, cost tracking, schemas, Telegram bot.
- `src/portfolio_analyst/` - Prices, fundamentals, technicals, risk analysis.
- `src/street_ear/` - Reddit intelligence pipeline.
- `src/news_desk/` - Market news pipeline.
- `src/substack_ear/` - Substack RSS ingestion and analysis.
- `src/youtube_ear/` - YouTube transcript ingestion and analysis.
- `config/` - YAML configs for portfolio, advisor, scout, source lists, and reporting.
- `tests/` - Python tests.
- `web/` - React/Vite cockpit frontend.
- `docs/` - Durable AI context and handoff documentation.
- `scripts/` - Local utility scripts.

## Architecture Overview

AlphaDesk has two major operating modes:

1. Daily/background research system:
   - Source agents collect and analyze signals.
   - Agents publish signals into the SQLite agent bus.
   - Alpha Scout discovers new candidates from agent bus, supply chain, sector peers, filings, Reddit, yfinance, and other sources.
   - Advisor and committee agents synthesize briefings.
   - Telegram/email delivery formats the result.

2. Interactive cockpit:
   - `src/api/app.py` exposes FastAPI routes for model council, portfolio snapshot, and idea discovery.
   - `web/src/` renders the cockpit.
   - Idea discovery now attempts Alpha Scout full pipeline first.
   - OpenRouter/mock paths are used for the direct council and as fallback/test surfaces.

Important runtime routes:

- `GET /api/council/models`
- `POST /api/council/run`
- `GET /api/council/stream`
- `GET /api/ideas/today`
- `GET /api/portfolio`

## Coding Conventions

- Prefer small, scoped changes that follow existing module boundaries.
- Keep API payloads typed with Pydantic models in `src/api/app.py`.
- Keep frontend payloads mirrored in `web/src/api/types.ts`.
- Use structured parsers and typed repair/normalization helpers for LLM output.
- Do not introduce broad refactors while fixing a narrow issue.
- Keep UI copy direct and honest about degraded or unavailable data sources.
- For investment features, distinguish:
  - validated data used in the current run,
  - configured sources not queried by the current run,
  - unavailable sources.
- Do not commit generated caches, local databases, local secrets, or build artifacts unless explicitly requested.

## Commands

Python setup:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

The local Codex/API work in this repo has also used `/tmp/alphadesk-venv`.

Backend tests:

```bash
python -m pytest tests/test_api_council.py -q
python -m pytest
```

Backend lint used in this workspace:

```bash
ruff check src/api tests/test_api_council.py
```

Frontend:

```bash
cd web
npm test -- --run
npm run build
npm run dev -- --port 5173
```

Local cockpit API:

```bash
OPENROUTER_API_KEY='test-key' \
OPENROUTER_MOCK=1 \
OPENROUTER_ANALYSIS_MODELS='google/gemini-3.5-flash,moonshotai/kimi-k2.6,deepseek/deepseek-v4-pro,z-ai/glm-5.2' \
COUNCIL_STREAM_TIMEOUT_S=60 \
ALPHA_SCOUT_TIMEOUT_S=180 \
uvicorn src.api.app:app --host 127.0.0.1 --port 8000
```

Generate an AI handoff context pack:

```bash
./scripts/ai-handoff.sh > /tmp/alphadesk-ai-handoff.md
```

## Safety Rules

- Never expose API keys or tokens in docs, diffs, logs, or handoff packs.
- Never paste user-provided secrets into durable files.
- Do not run destructive git commands such as `git reset --hard` or `git checkout --` unless explicitly asked.
- The repo may have unrelated dirty files. Do not revert changes you did not make.
- Treat investment output as research support, not financial advice.
- If a live API call would spend money, prefer mock mode unless the user explicitly asks for a live run.
- When adding source checks, report what actually happened; do not show configured sources as validated unless they were used or proved healthy.

## Handoff Protocol

For every substantial agent session:

1. Read `AGENTS.md`.
2. Read `docs/AI_CONTEXT.md`.
3. Read the latest entry in `docs/AI_HANDOFF.md`.
4. Inspect `git status --short` before editing.
5. Preserve unrelated user or agent changes.
6. Make focused edits.
7. Run the smallest meaningful tests first, then broader tests when risk warrants.
8. Append a new entry to `docs/AI_HANDOFF.md` before ending.
9. Generate a context pack with `./scripts/ai-handoff.sh` when handing off to another model.

For Kimi or another coding model, provide the generated context pack plus the prompt printed by the current agent.

