# AlphaDesk AI Handoff Log

This file is append-only. Add a new session entry at the top of the session log for every substantial agent handoff. Do not delete or rewrite previous sessions unless the user explicitly asks.

## Entry Template

```markdown
## Session YYYY-MM-DD HH:MM TZ - Agent Name

### Goal
- What the user asked for.

### Files Changed
- `path/to/file`

### Commands Run
- `command`

### Test/Lint/Build Results
- Result summary.

### Current State
- What works now.

### Blockers
- Anything unresolved or blocked.

### Recommended Next Step
- The most useful next action.
```

## Session 2026-06-29 21:00 UTC - Claude

### Goal
- Restart backend to load fixes (user authorized "restart it"); AFRM reappeared at 90 after restart — find why and fix.

### Root cause
- The live backend had been running since Jun 24 (pre-all-fixes). After restart with new code, the main pipeline correctly drops AFRM (screener 74) — but `/api/ideas/today`'s **fallback path** (`_run_openrouter_idea_scout_sync`, used when the full pipeline times out at 180s or returns an empty buy bucket) is a legacy free-form LLM idea scout that bypasses the quantitative screen and re-invented AFRM at composite 90 with boilerplate catalysts. That fallback produced run 63.

### Files Changed
- `src/api/app.py` `scout_today_ideas` — fallback no longer calls the free-form LLM scout. Live runs now fall back to the **deterministic score engine** (`_fast_score_result` + `_idea_scout_from_score_result`); mock mode still returns `_mock_today_ideas`. Verified by forcing `ALPHA_SCOUT_TIMEOUT_S=1`: fallback returns `[ARM]`, AFRM absent, cost $0.

### Test/Lint Results
- 451 passed, 2 skipped. ruff clean. (Fixed 2 api_council tests that asserted the old mock-fallback behavior.)

### Current State
- Backend restarted on :8000 with all fixes live (`/api/ideas/progress` → 200). Both the main pipeline and the fallback are now AFRM-free.

### Note / next
- The deterministic fallback is thin when the score snapshot is stale (returned only ARM). Main pipeline is the normal path; consider refreshing the score snapshot or broadening the fallback universe. The score engine (`src/score_engine/`) is a separate scorer from the alpha_scout screener and does NOT yet have the fundamental-quality fix.

## Session 2026-06-29 20:20 UTC - Claude

### Goal
- User: "Affirm consistently comes up in Alpha Scout" — fix it in a continuous self-improvement loop.

### Findings (ground truth from live DB + screener)
- AFRM is already fixed in code: real screener scores it 73.9 (gone from top buys). The card the user showed was **ARM (Arm Holdings, a watchlist name)**, not AFRM — and the live :8000 returns **404 on `/api/ideas/progress`**, proving the running backend is still on PRE-FIX code. That is why old 88-scores (and `NOISY*` test tickers) keep appearing. The fixes are correct but unloaded; restart was previously denied to the agent (user's process).
- Genuine remaining gap found + fixed: SMCI scored fundamental 100 / composite 88 despite an 8% gross margin and negative FCF.

### Files Changed
- `src/alpha_scout/screener.py` — `score_fundamental` now penalises very low gross margin (<20% → −10) and negative free cash flow (−10); `explain_fundamental_factors` updated to match. SMCI 88.1 → 81.6; NVDA/GOOG/MU/META unaffected; ARM 74.4 / AFRM 73.9 unchanged.
- Tests: `tests/test_alpha_scout_core.py` (low-quality-cheap case), `tests/test_idea_debug.py` (thin-margin/cash-burn factors).

### Test/Lint Results
- 451 passed, 2 skipped. ruff clean.

### Blockers
- Live backend MUST be restarted to load any of this (404 proves it's stale). Agent is sandbox-blocked from killing the user's :8000 process.

### Recommended Next Step
- Restart backend (`lsof -ti tcp:8000 | xargs kill` then `/tmp/alphadesk-api-test-venv/bin/python run_api.py`), then re-run Alpha Scout.

## Session 2026-06-28 20:30 UTC - Claude

### Goal
- (1) Live visualization of Alpha Scout pipeline stages while running. (2) A UI "debug mode" showing *why* each idea scored/ranked as it did. (Same session also: LunarCrush social-feed integration; fundamental-quality scoring fix for the AFRM false-positive.)

### Files Changed
- `src/shared/scout_progress.py` (new) — thread-safe progress singleton (start/stage/finish/snapshot) with 6 ordered stages.
- `src/alpha_scout/main.py` — `run()` now reports each stage via `scout_progress`; `_run_alpha_scout_pipeline` (app.py) finishes-with-error on crash.
- `src/alpha_scout/screener.py` — `explain_fundamental_factors()` mirrors `score_fundamental`'s rubric as signed human-readable factors (the debug "why").
- `src/alpha_scout/synthesizer.py` — fallback recs carry `corroboration_count`/`corroborating_sources`/`synthesis_source`.
- `src/api/app.py` — `IdeaDebug`/`DimensionScore` models + `debug` on `TopIdea` (built by `_idea_debug_from_rec`); `ScoutProgress`/`ScoutStage` models + `GET /api/ideas/progress`.
- Frontend: `web/src/types/index.ts` (IdeaDebug/DimensionScore/ScoutProgress/ScoutStage + `debug` on BackendTopIdea); `web/src/lib/api.ts` (`fetchScoutProgress`); new `ScoutPipeline.tsx` (live stepper) + `IdeaDebugPanel.tsx` (dimension bars + factors + provenance); `TopBuysView.tsx` (polls progress during a run, "Debug" toggle renders per-idea panels).
- Tests: `tests/test_scout_progress.py`, `tests/test_idea_debug.py` (9 new).

### Test/Lint/Build Results
- Backend: 449 passed, 2 skipped. `ruff check src` clean. Frontend: typecheck + build clean.

### Current State
- Live stage view + debug mode are built and verified at the data layer (progress transitions, debug payload with AFRM's `-15 EV/EBITDA`, `-10 P/E 72`, `+25 revenue growth`). Debug populates richest in the score_fallback path (recs carry `scores`); LLM-synthesis recs may lack per-dimension scores → panel shows a graceful "no breakdown" note.

### Blockers
- Visual browser verification not done: the user's live :8000 is old code (restart was denied as their process) and pointing a preview Vite at a fresh backend would restart their :5173 (Vite watches .env). Needs a backend restart to see live.

### Recommended Next Step
- Restart backend, open Top Buys, hit Run (watch stages) and toggle Debug.

## Session 2026-06-28 07:35 UTC - Claude

### Goal
- User questions: (1) "is Reddit working now?" (2) noted they fixed/bought a 1-day LunarCrush API key and want it working today, (3) "why is AFRM a Top Buy? it isn't one."

### Files Changed
- `src/shared/lunarcrush.py` — `_get_headers()` now accepts `LUNAR_CRUSH_API` as well as canonical `LUNARCRUSH_API_KEY`; `get_stock_social_metrics()` now reads metrics from the v4 nested `data` object instead of the response root (was returning all-`None`).
- `src/alpha_scout/screener.py` — **`score_fundamental()` made quality-aware** (the primary AFRM fix): adds EV/EBITDA + analyst-implied-upside factors and a steeper high-P/E penalty, penalises losses (was: no penalty for negative margins), and stops treating "down from 52w high / near 52w low" as a standalone positive (value-trap reward). AFRM 100→70; NVDA/MSFT/GOOG/MU stay 98-100.
- `src/alpha_scout/screener.py` — `score_evidence_quality()` also made corroboration-aware (secondary): top of range reserved for tracked names (+40) or multi-source discoveries; a lone single-source discovery caps ~60.
- `src/alpha_scout/candidate_sourcer.py` — dedup now records corroboration breadth (`corroboration_count` / `corroborating_sources`) instead of silently discarding duplicate-source hits.
- `tests/test_lunarcrush.py` (new), `tests/test_alpha_scout_core.py` (added score_fundamental quality test + AFRM-vs-tracked regression), `tests/test_screener_declustering.py` (robust spread assertion).

### Commands Run
- Live probes: LunarCrush `/coins/{sym}/v1` (HTTP 200, real data) and Reddit public `/r/stocks/hot.json` (HTTP 403).
- `python -m pytest` (full), targeted alpha_scout/screener/lunarcrush suites, `ruff check src`.

### Test/Lint/Build Results
- Full suite: 433 passed, 2 skipped. `ruff check src`: all checks passed.

### Current State
- LunarCrush: key works live; the two-bug fix means it's actually consumed now (was silently ignored + mis-parsed).
- Reddit: NOT working — all `REDDIT_*` keys absent from `.env`; public endpoint is 403-blocked, so it returns zero posts.
- AFRM root cause (user clarified the real issue is *quality*, not watchlist membership): the fundamental scorer gave AFRM 100/100 because it rewarded 33% revenue growth + being down 20% off highs, while a 72× P/E cost only −5 and it ignored EV/EBITDA (53.7), thin margins (10%), and near-zero analyst upside (5.5%). Now AFRM scores 70 fundamentally vs 98-100 for the quality names. (The earlier evidence_quality/corroboration change is a secondary guard against thin single-source discoveries.)

### Blockers
- Reddit needs the user's OAuth creds (`REDDIT_CLIENT_ID/SECRET/USERNAME/PASSWORD/USER_AGENT`).
- AFRM still shows in the *cached* scout run (id 43) until a fresh Alpha Scout run is triggered on the new code (requires backend restart).

### Recommended Next Step
- Restart the backend and re-run Alpha Scout to refresh Top Buys; add Reddit keys to `.env` if live social data is wanted.

## Session 2026-06-19 04:19 UTC - Codex

### Goal
- Make the running dashboard call the actual FastAPI backend for at least the recommendation engine, and make backend/mock status visible.

### Files Changed
- `src/api/app.py`
- `src/advisor/macro_analyst.py`
- `tests/test_api_council.py`
- `/Users/vikram/workspace/alpha-desk/dashboard/src/lib/api.ts`
- `/Users/vikram/workspace/alpha-desk/dashboard/src/types/index.ts`
- `/Users/vikram/workspace/alpha-desk/dashboard/src/components/moonshots/MoonshotCard.tsx`
- `/Users/vikram/workspace/alpha-desk/dashboard/src/components/commandcenter/CommandCenter.tsx`
- `/Users/vikram/workspace/alpha-desk/dashboard/src/components/macro/MacroRegimeSection.tsx`
- `docs/AI_HANDOFF.md`

### Commands Run
- `/tmp/alphadesk-venv/bin/python -m pytest tests/test_api_council.py -q`
- `/tmp/alphadesk-venv/bin/python -m pytest tests/test_api_council.py tests/test_macro_dedup.py -q`
- `/tmp/alphadesk-venv/bin/ruff check src/api src/advisor/macro_analyst.py tests/test_api_council.py`
- `npm run typecheck`
- `npm run lint`
- `npm run build`
- `uvicorn src.api.app:app --host 127.0.0.1 --port 8000`
- Browser smoke at `http://localhost:5173/`

### Test/Lint/Build Results
- Backend focused tests: 24 passed, 1 urllib3/LibreSSL warning.
- Backend lint: passed.
- Dashboard typecheck: passed.
- Dashboard lint: passed.
- Dashboard build: passed.
- Browser smoke showed `Backend Recommendation`, `Backend`, and `Backend macro`.
- FastAPI logs confirmed browser requests to `/api/ideas/today?limit=10&mode=new_discoveries` and `/api/macro`.

### Current State
- Dashboard `fetchMoonshots()` now calls FastAPI `/api/ideas/today?limit=10&mode=new_discoveries` and maps Alpha Scout ideas into the existing recommendation/moonshot cards.
- Dashboard homepage `fetchDailyBrief()` now uses live backend macro data and live backend recommendations where available.
- Dashboard macro data now calls FastAPI `/api/macro`.
- Recommendation and macro UI surfaces show visible `Backend`/`Mock` or `Backend macro`/`Mock macro` status badges.
- Mock fallback remains available if the backend is offline or if `VITE_USE_MOCKS=1`.
- A live-spend backend server is currently running on `127.0.0.1:8000` with mock flags removed, `DAILY_COST_CAP=100000`, `COUNCIL_COST_CAP_USD=100000`, and `ALPHA_SCOUT_SYNTHESIS_MODEL=gemini-2.5-flash`.
- Live Alpha Scout completed with `scout_mode=new_discoveries`, sourced 639 raw candidates, capped/scored 50 candidates, and returned 10 ideas.
- The available Gemini key has no quota for `gemini-2.5-pro`; it returned `429 RESOURCE_EXHAUSTED`. `gemini-2.5-flash` works and one Alpha Scout synthesis call recorded approximately `$0.0002` of LLM cost.
- The Flash synthesis response did not parse as valid JSON in the latest run, so Alpha Scout still ranked scored candidates directly after spending on the model call.

### Blockers
- For higher-quality/expensive synthesis, provide a paid `ANTHROPIC_API_KEY` or `OPENROUTER_API_KEY`, or enable billing/quota for Gemini Pro on the existing Google key.
- The dashboard repo has many pre-existing dirty parent-backend files outside `dashboard/`; these were not touched.

### Recommended Next Step
- Improve Alpha Scout JSON-mode synthesis for Gemini Flash, then wire the next dashboard routes (`portfolio`, `research`, `alerts`, or command palette`) to FastAPI endpoints one at a time with visible source status.

## Session 2026-06-19 04:07 UTC - Codex

### Goal
- Diagnose whether `http://localhost:5173/macro` is working and whether it is actually calling backend models.

### Files Changed
- `docs/AI_HANDOFF.md`

### Commands Run
- `git status --short`
- `sed -n '1,260p' docs/AI_CONTEXT.md`
- `tail -n 220 docs/AI_HANDOFF.md`
- `rg --files`
- `lsof -nP -iTCP:5173 -sTCP:LISTEN`
- `lsof -nP -iTCP:8000 -sTCP:LISTEN`
- `curl -sS -I http://localhost:5173/macro`
- `curl -sS http://127.0.0.1:8000/api/council/models`
- `lsof -a -p 65231 -d cwd -Fn`
- `sed -n '1,260p' /Users/vikram/workspace/alpha-desk/dashboard/HANDOFF.md`
- `sed -n '1,320p' /Users/vikram/workspace/alpha-desk/dashboard/src/lib/api.ts`
- `sed -n '1,260p' /Users/vikram/workspace/alpha-desk/dashboard/src/components/macro/MacroView.tsx`
- `npm run typecheck`
- `npm run lint`
- `npm run build`

### Test/Lint/Build Results
- Dashboard `npm run typecheck` -> passed.
- Dashboard `npm run lint` -> passed.
- Dashboard `npm run build` -> passed.
- Browser check of `http://localhost:5173/macro` rendered the Macro Regime page with no console warnings/errors.
- A temporary mock FastAPI server was started on `127.0.0.1:8000` only to verify this repo's SSE council endpoint, then stopped.

### Current State
- The Vite process serving `http://localhost:5173/macro` is not from `/Users/vikram/Documents/New project`; its cwd is `/Users/vikram/workspace/alpha-desk/dashboard`.
- That dashboard's own `AGENTS.md` and `HANDOFF.md` state that `src/lib/api.ts` is a mock-only API seam.
- The running `/macro` page calls `fetchMacroRegime()` and `fetchMacroThemes()`, which return local mock data via `delay(...)`; there is no `fetch`, `EventSource`, or backend model call in that page.
- Before the temporary mock server was started, nothing was listening on `127.0.0.1:8000`, so the original local state had no backend reachable by the browser anyway.
- In `/Users/vikram/Documents/New project`, the backend council SSE path does work in mock mode and reports `council_mode: openrouter_mock`, with `cost_usd: 0.0`.

### Blockers
- None for the diagnosis.

### Recommended Next Step
- Wire `/Users/vikram/workspace/alpha-desk/dashboard/src/lib/api.ts` to real FastAPI endpoints, and add visible UI status/copy that distinguishes mock data, live backend data, and live model calls.

## Session 2026-06-18 04:29 UTC - Codex

### Goal
- Prepare the repository for handoff to another AI coding agent without new feature changes.
- Update durable AI context and append a concise handoff entry so Kimi can continue without reading the chat.

### What Changed
- Updated `docs/AI_CONTEXT.md` with durable knowledge discovered during this session:
  - Cockpit idea discovery now runs Alpha Scout full pipeline first.
  - Verified Alpha Scout live run stats: 46 sourced, 46 screened, 10 watchlist ideas, 10 discovery signals published.
  - Source checks now cover 14 rows, including Alpha Scout source families and council/portfolio context.
  - Current constraints: `lxml` missing for S&P 500 parsing, yfinance screener API may be unavailable, Alpha Scout falls back without Gemini/Anthropic keys, repeated runs publish local agent-bus signals.
- Appended this entry to `docs/AI_HANDOFF.md`.

### Files Touched
- `docs/AI_CONTEXT.md`
- `docs/AI_HANDOFF.md`

### Commands Run
- `sed -n '1,260p' docs/AI_CONTEXT.md`
- `sed -n '1,260p' docs/AI_HANDOFF.md`
- `git branch --show-current && git status --short`
- `date -u '+%Y-%m-%d %H:%M UTC'`

### Test/Lint/Build Results
- No app tests were rerun for this docs-only handoff update.
- Most recent validation before this handoff entry:
  - Backend: `/tmp/alphadesk-venv/bin/python -m pytest tests/test_api_council.py -q` -> 19 passed, 1 urllib3/LibreSSL warning.
  - Backend lint: `/tmp/alphadesk-venv/bin/ruff check src/api tests/test_api_council.py` -> passed.
  - Frontend: `npm test -- --run` in `web` -> 7 files / 18 tests passed.
  - Frontend build: `npm run build` in `web` -> passed.
  - API smoke: `/api/ideas/today?limit=12` completed Alpha Scout full pipeline with 10 ideas and 14 source checks.

### Current State
- Current branch: `codex/phase-f-final-a11y-polish`.
- Working tree is dirty with app changes from the council/OpenRouter/Idea Scout/Alpha Scout work plus the new handoff docs/scripts.
- API server was restarted after the Alpha Scout changes and has been run with:
  - `OPENROUTER_API_KEY='test-key'`
  - `OPENROUTER_MOCK=1`
  - `OPENROUTER_ANALYSIS_MODELS='google/gemini-3.5-flash,moonshotai/kimi-k2.6,deepseek/deepseek-v4-pro,z-ai/glm-5.2'`
  - `COUNCIL_STREAM_TIMEOUT_S=60`
  - `ALPHA_SCOUT_TIMEOUT_S=180`
- Frontend dev server has been running at `http://127.0.0.1:5173`.
- `scripts/ai-handoff.sh` is executable and was verified to generate a markdown handoff pack including untracked text files.

### Known Failures Or Blockers
- `lxml` is missing from the API venv, so Alpha Scout's S&P 500 index source reports unavailable.
- Alpha Scout yfinance screeners may skip because the installed yfinance package does not expose the expected `Screener` API, though price/fundamental fetches work.
- No `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, or `GOOGLE_API_KEY` was available in the tested API run, so Alpha Scout synthesis fell back to score-based recommendations.
- Kalshi and Polymarket are configured, but Alpha Scout does not query prediction markets yet.
- Repeated Alpha Scout runs publish discovery signals to the local SQLite agent bus.

### Important Design Decisions
- `GET /api/ideas/today` should try Alpha Scout full pipeline first and only use OpenRouter/mock idea scout as fallback.
- Data source checks should be honest: validated only when actually validated, configured when enabled/importable, unavailable when missing dependencies or disabled.
- OpenRouter direct council remains the cheaper default over OpenRouter Fusion.
- `OPENROUTER_MOCK=1` is the safe/default local test mode for council and fallback idea scouting.
- Handoff docs are append-only; future agents should add new entries rather than rewriting old ones.

### Recommended Next Step
- Generate a fresh context pack with `./scripts/ai-handoff.sh > /tmp/alphadesk-ai-handoff.md`, give it to Kimi, and ask Kimi to first inspect the dirty working tree before making any edits.

## Session 2026-06-18 04:20 UTC - Codex

### Goal
- Create a durable multi-agent handoff system so Codex, Kimi, and other coding agents can switch contexts without losing project state.

### Files Changed
- `AGENTS.md`
- `docs/AI_CONTEXT.md`
- `docs/AI_HANDOFF.md`
- `scripts/ai-handoff.sh`

### Commands Run
- `find . -maxdepth 3 -type f ...`
- `find . -maxdepth 2 -type d`
- `git branch --show-current`
- `git status --short`
- `git log --oneline -5`
- `sed -n '1,260p' README.md`
- `cat web/package.json`
- `mkdir -p docs scripts`

### Test/Lint/Build Results
- Documentation/script-only change in this session.
- No app tests were rerun for this documentation-only handoff setup.
- Prior current branch validation before this handoff work included backend tests, backend lint, frontend tests, frontend build, API smoke, and browser checks for the Alpha Scout cockpit flow.

### Current State
- `AGENTS.md` is the main instruction file for Codex-style agents.
- `docs/AI_CONTEXT.md` summarizes product, architecture, constraints, decisions, testing, gotchas, and open questions for Kimi/other agents.
- `docs/AI_HANDOFF.md` now contains this append-only session entry and a template.
- `scripts/ai-handoff.sh` generates a markdown context pack with git state, recent commits, changed files, diffs, main agent docs, and the latest handoff section.

### Blockers
- None for the handoff system.

### Recommended Next Step
- Run `./scripts/ai-handoff.sh > /tmp/alphadesk-ai-handoff.md` before switching models, then paste that file into Kimi with the prompt provided by Codex.

## Session 2026-06-19 04:50 UTC - Codex

### Goal
- Make the live cockpit recommendation engine call the real backend and use OpenRouter/GLM 5.2 for Alpha Scout synthesis, with no Opus default.

### Files Changed
- `src/api/app.py`
- `src/alpha_scout/main.py`
- `src/alpha_scout/synthesizer.py`
- `src/shared/gemini_compat.py`
- `src/advisor/macro_analyst.py`
- `tests/test_api_council.py`
- `tests/test_alpha_scout_core.py`
- `tests/test_cost_attribution.py`
- `docs/AI_HANDOFF.md`

### Commands Run
- `git status --short`
- `/tmp/alphadesk-venv/bin/python -m pytest tests/test_alpha_scout_core.py tests/test_cost_attribution.py tests/test_api_council.py tests/test_macro_dedup.py -q`
- `/tmp/alphadesk-venv/bin/ruff check src/api src/advisor/macro_analyst.py src/alpha_scout/main.py src/alpha_scout/synthesizer.py src/shared/gemini_compat.py tests/test_api_council.py tests/test_alpha_scout_core.py tests/test_cost_attribution.py`
- `curl -sS http://127.0.0.1:8000/api/council/models`
- `curl -sS -m 620 http://127.0.0.1:8000/api/ideas/today?limit=10\&mode=new_discoveries`

### Test/Lint/Build Results
- Backend focused tests: 33 passed, 1 urllib3/LibreSSL warning.
- Backend lint: passed.
- Live OpenRouter smoke:
  - `/api/council/models` returned `z-ai/glm-5.2` first and no Opus model.
  - `/api/ideas/today?limit=10&mode=new_discoveries` completed Alpha Scout full pipeline.
  - Live synthesis detail: `llm_repaired_json via openrouter on z-ai/glm-5.2-20260616`.
  - Live endpoint returned 8 LLM-synthesized ideas, 0 degraded reasons, and recorded OpenRouter synthesis cost.

### Current State
- Backend API is running at `http://127.0.0.1:8000`.
- Dashboard dev server is running at `http://127.0.0.1:5173`.
- The OpenRouter API key was provided interactively at runtime only; it was not written to repo files or this handoff.
- Runtime backend env was started with:
  - `ALPHA_SCOUT_SYNTHESIS_PROVIDER=openrouter`
  - `ALPHA_SCOUT_OPENROUTER_MODEL=z-ai/glm-5.2`
  - `OPENROUTER_IDEA_MODEL=z-ai/glm-5.2`
  - `OPENROUTER_FUSION_JUDGE=z-ai/glm-5.2`
  - `OPENROUTER_ANALYSIS_MODELS=z-ai/glm-5.2,moonshotai/kimi-k2.6,deepseek/deepseek-v4-pro,google/gemini-3.5-flash`
  - high cost/time caps for live local testing.
- Alpha Scout now refuses OpenRouter model ids containing `opus` and falls back to `z-ai/glm-5.2` for synthesis.
- OpenRouter JSON schema for Alpha Scout synthesis no longer uses `maxItems`; count limits are enforced by prompt/parser.

### Known Failures Or Blockers
- The first GLM response in the live smoke hit `max_tokens` and was not parseable, but the paid JSON repair retry succeeded.
- Repeated Alpha Scout runs publish discovery and technical signals to the local SQLite agent bus.
- Some yfinance/FRED source warnings are still normal in local runs, including missing fundamentals for ETF-like tickers such as `VTI`.

### Recommended Next Step
- Keep the backend running with the GLM/OpenRouter runtime env above while testing `http://localhost:5173/`.
- If GLM frequently truncates first-pass synthesis, raise `max_tokens` or make the initial prompt ask for fewer recommendations before relying on repair.
## Session 2026-06-21 00:26 UTC - Codex

### Goal
- Redesign the FastAPI cockpit UI so the key backend features are explicit and easy to explore.

### Files Changed
- `web/src/App.tsx`
- `web/src/api/client.ts`
- `web/src/api/types.ts`
- `web/src/components/BackendFeatureGrid.tsx`
- `web/src/components/MacroPanel.tsx`
- `web/src/components/CommandBar.tsx`
- `web/src/components/IdeaScout.tsx`
- `web/src/App.test.tsx`
- `web/src/components/CommandBar.test.tsx`
- `web/src/components/IdeaScout.test.tsx`
- `docs/AI_HANDOFF.md`

### What Changed
- Reworked the cockpit first screen around actual backend feature cards:
  - Alpha Scout discovery: `/api/ideas/today?mode=new_discoveries`
  - Alpha Scout top buys: `/api/ideas/today?mode=top_buys`
  - Macro regime: `/api/macro`
  - Portfolio context: `/api/portfolio`
- Added typed frontend support for `/api/macro`.
- Added a `MacroPanel` showing backend regime score, confidence, rationale, degraded reasons, and macro themes.
- Changed the Alpha Scout UI heading to reflect the active backend mode instead of generic "today's top ideas."
- Kept council controls in the main cockpit but made them read as a model-council feature, not the whole product.
- Added clearer offline backend copy for unavailable endpoints instead of raw `Failed to fetch`.
- Fixed mobile feature-card overflow caused by long endpoint labels.

### Commands Run
- `git status --short`
- `sed -n '1,240p' AGENTS.md`
- `sed -n '1,260p' docs/AI_CONTEXT.md`
- `tail -n 220 docs/AI_HANDOFF.md`
- `npm test -- --run`
- `npm run build`
- `npm run dev -- --port 5174`
- Browser layout smoke at `http://127.0.0.1:5174/`

### Test/Lint/Build Results
- Frontend tests: 7 files / 18 tests passed.
- Frontend build: passed.
- Browser desktop/mobile scan: no horizontal overflow and no console warnings/errors.

### Current State
- The redesigned cockpit dev server is running at `http://127.0.0.1:5174/`.
- Port `5173` is still occupied by the separate dashboard process, so it was left untouched.
- No FastAPI process was listening on `127.0.0.1:8000` during browser verification, so macro and portfolio panels correctly showed backend-unavailable messages.

### Recommended Next Step
- Start FastAPI on `127.0.0.1:8000`, then click "Run discovery" and "Run top buys" to verify both Alpha Scout modes with the live backend.
## Session 2026-06-21 00:58 UTC - Codex

### Goal
- Merge the themed `5173` dashboard with the real FastAPI backend and keep only pages backed by actual backend routes.

### Files Changed
- `/Users/vikram/workspace/alpha-desk/dashboard/src/App.tsx`
- `/Users/vikram/workspace/alpha-desk/dashboard/src/lib/api.ts`
- `/Users/vikram/workspace/alpha-desk/dashboard/src/lib/useCouncilStream.ts`
- `/Users/vikram/workspace/alpha-desk/dashboard/src/types/index.ts`
- `/Users/vikram/workspace/alpha-desk/dashboard/src/components/backend/BackendCockpitView.tsx`
- `/Users/vikram/workspace/alpha-desk/dashboard/src/components/council/CouncilView.tsx`
- `/Users/vikram/workspace/alpha-desk/dashboard/src/components/layout/AppShell.tsx`
- `/Users/vikram/workspace/alpha-desk/dashboard/src/components/layout/Sidebar.tsx`
- `/Users/vikram/workspace/alpha-desk/dashboard/src/components/moonshots/MoonshotsView.tsx`
- `/Users/vikram/workspace/alpha-desk/dashboard/src/components/portfolio/BackendPortfolioView.tsx`
- `docs/AI_HANDOFF.md`

### What Changed
- Kept the dashboard visual theme from `http://127.0.0.1:5173`.
- Removed mock-only pages from the active router/sidebar:
  - Alerts, Sentiment, Research, Markets, Digest, and the mock command palette are no longer exposed.
- Kept only backend-backed pages:
  - Backend cockpit: `/`
  - Alpha Scout: `/scout`
  - Model Council: `/council`
  - Macro: `/macro`
  - Portfolio: `/portfolio`
- Updated `src/lib/api.ts` so these pages call the FastAPI backend at `http://127.0.0.1:8000`.
- Added `useCouncilStream` and a themed Council page that streams `/api/council/stream`.
- Added a backend-only portfolio page using `/api/portfolio`.
- Reworked Alpha Scout page to explicitly run `new_discoveries` or `top_buys` through `/api/ideas/today`; it no longer auto-runs on navigation, so spending happens only on click.
- Kept Macro page backend-backed through `/api/macro`.

### Backend Verification
- FastAPI was started on `127.0.0.1:8000`.
- `/api/council/models` returned the OpenRouter-compatible roster with `z-ai/glm-5.2` first.
- `/api/portfolio` returned 5 configured positions and concentration data.
- `/api/macro` returned backend macro regime data and 6 themes.
- `/api/ideas/today?limit=10&mode=new_discoveries` completed Alpha Scout:
  - `scout_mode`: `new_discoveries`
  - 647 raw candidates
  - 534 unique candidates
  - 50 capped candidates
  - 22 source checks
  - 1 returned idea: `AFRM`
  - synthesis: Gemini-backed Alpha Scout LLM synthesis
  - recorded cost: approximately `$0.000263`
- UI council run from `http://127.0.0.1:5173/council` streamed a complete backend result.

### Important Caveat
- No live `OPENROUTER_API_KEY` was present in the shell. The backend was therefore started with `OPENROUTER_API_KEY=test-key` and `OPENROUTER_MOCK=1` to verify the council SSE path.
- This means the council UI talks to the actual FastAPI backend, but current council model output is deterministic backend mock mode until a real OpenRouter key is exported in the backend process.
- A Gemini key from the local `.env` was available and Alpha Scout used Gemini synthesis.

### Commands Run
- `npm run typecheck`
- `npm run lint`
- `npm run build`
- FastAPI `uvicorn src.api.app:app --host 127.0.0.1 --port 8000`
- `curl` smokes for `/api/council/models`, `/api/portfolio`, `/api/macro`, `/api/council/stream`, and `/api/ideas/today`
- Browser QA on `http://127.0.0.1:5173/`, `/portfolio`, `/macro`, `/council`, `/scout`

### Test/Lint/Build Results
- Dashboard typecheck: passed.
- Dashboard lint: passed.
- Dashboard build: passed.
- Browser QA: exposed routes rendered with no console warnings/errors and no horizontal overflow.
- UI council run successfully streamed backend SSE events into the page.

### Current State
- FastAPI backend is running at `http://127.0.0.1:8000`.
- Merged themed dashboard is running at `http://127.0.0.1:5173`.
- Active dashboard nav now contains only: Backend, Alpha Scout, Council, Macro, Portfolio.

### Recommended Next Step
- Restart FastAPI with a real `OPENROUTER_API_KEY` and `OPENROUTER_MOCK=0` to make the council use live paid OpenRouter/GLM instead of backend mock mode.
## Session 2026-06-21 18:31 UTC - Codex

### Goal
- Persist Alpha Scout cockpit runs to local SQLite so results survive tab navigation and can be reloaded without rerunning the backend pipeline.

### Files Changed
- `src/api/run_store.py`
- `src/api/app.py`
- `tests/test_api_council.py`
- `/Users/vikram/workspace/alpha-desk/dashboard/src/lib/api.ts`
- `/Users/vikram/workspace/alpha-desk/dashboard/src/types/index.ts`
- `/Users/vikram/workspace/alpha-desk/dashboard/src/components/moonshots/MoonshotsView.tsx`
- `docs/AI_HANDOFF.md`

### What Changed
- Added `data/cockpit_runs.db` SQLite persistence for Alpha Scout run payloads.
- `GET /api/ideas/today` now saves every successful returned Scout payload, including Alpha Scout pipeline results and fallback results.
- Added `GET /api/ideas/runs/latest` to restore the latest saved run without spending or rerunning Scout.
- Added `GET /api/ideas/runs` to list saved run summaries.
- Added optional `run_id` and `saved_at` fields to the Scout API payload.
- Updated the active themed dashboard Scout page to hydrate from `/api/ideas/runs/latest` on mount, so switching away from and back to Alpha Scout keeps the last saved result visible.
- Added a saved-run id/timestamp cue in the Scout run audit card.
- Isolated API tests from the real local data directory so tests do not write fake runs into `data/cockpit_runs.db`.

### Commands Run
- `npm run typecheck`
- `npm run build`
- `/tmp/alphadesk-api-test-venv/bin/python -m pytest tests/test_api_council.py -q`
- `/tmp/alphadesk-api-test-venv/bin/python -m ruff check src/api tests/test_api_council.py`
- `python3 -m py_compile src/api/app.py src/api/run_store.py tests/test_api_council.py`
- SQLite module smoke test for save/latest/list.
- Restarted FastAPI on `127.0.0.1:8000`.
- Verified `GET /api/ideas/runs?limit=5` returns `[]` on a clean store.
- Verified `GET /api/ideas/runs/latest` returns `404` on a clean store.
- Verified Vite frontend remains live on `127.0.0.1:5173`.

### Test/Lint/Build Results
- Dashboard typecheck: passed.
- Dashboard build: passed.
- Backend focused tests: 23 passed, 1 third-party Starlette/httpx deprecation warning.
- Ruff: passed.
- Python compile check: passed.

### Current State
- FastAPI backend is running at `http://127.0.0.1:8000` with the updated persistence routes.
- The themed dashboard is running at `http://127.0.0.1:5173`.
- `data/cockpit_runs.db` exists locally as the SQLite store and is currently clean/empty after removing test-created mock rows.
- The running backend is still using mock OpenRouter posture (`OPENROUTER_MOCK=1` with a test key), matching the pre-existing local server state. Alpha Scout itself will run through the backend pipeline unless `ALPHA_SCOUT_MOCK=1` is set.

### Recommended Next Step
- Run Alpha Scout from the UI once; the result should save into `data/cockpit_runs.db`, then remain visible after navigating away from and back to the Scout page.
## Session 2026-06-21 19:20 UTC - Codex

### Goal
- Switch the local cockpit from mock model mode to live OpenRouter-backed API calls.

### Runtime Changes
- Restarted FastAPI in detached `screen` session `alphadesk-api`.
- Set runtime model mode to live:
  - `OPENROUTER_MOCK=0`
  - `ALPHA_SCOUT_MOCK=0`
  - `ALPHA_SCOUT_SYNTHESIS_PROVIDER=openrouter`
  - `ALPHA_SCOUT_OPENROUTER_MODEL=z-ai/glm-5.2`
  - `OPENROUTER_IDEA_MODEL=z-ai/glm-5.2`
  - `OPENROUTER_FUSION_JUDGE=z-ai/glm-5.2`
  - `OPENROUTER_ANALYSIS_MODELS=z-ai/glm-5.2,moonshotai/kimi-k2.6,deepseek/deepseek-v4-pro,google/gemini-3.5-flash`
- The OpenRouter API key was injected only into the live process environment. It was not written to repo files or this handoff.

### Verification
- `GET /api/council/models` returned GLM 5.2 first and no Opus model.
- `GET /api/council/stream?ticker=NVDA&models=z-ai/glm-5.2` completed with:
  - `council_mode=openrouter_live`
  - nonzero OpenRouter cost
  - no degraded reasons
- `GET /api/ideas/today?limit=10&mode=new_discoveries` completed a live Alpha Scout run:
  - saved as SQLite run `#2`
  - 10 ideas returned: AFRM, ABT, DLR, DIS, UBER, NFLX, ADBE, BABA, CRM, LYFT
  - nonzero OpenRouter synthesis cost
  - no degraded reasons
- `GET /api/ideas/runs/latest` returns the saved live Scout run.
- Frontend remains live on `127.0.0.1:5173`; backend remains live on `127.0.0.1:8000`.

### Notes
- Alpha Scout first-pass GLM synthesis logged a JSON parse failure, but the endpoint completed successfully with LLM-synthesized ideas and no degraded reasons.
- The live Scout run mutated local SQLite state by publishing technical/discovery signals and saving the cockpit run.
## Session 2026-06-21 19:53 UTC - Codex

### Goal
- Fix Kimi/Gemini council reliability and make the model council adversarial, with each LLM explicitly accepting, rejecting, and challenging claims from the other seats.

### Files Changed
- `src/api/app.py`
- `tests/test_api_council.py`
- `web/src/App.tsx`
- `web/src/api/types.ts`
- `web/src/components/PanelCard.tsx`
- `web/src/components/CommandBar.test.tsx`
- `web/src/components/Council.test.tsx`
- `/Users/vikram/workspace/alpha-desk/dashboard/src/components/council/CouncilView.tsx`
- `/Users/vikram/workspace/alpha-desk/dashboard/src/types/index.ts`
- `docs/AI_HANDOFF.md`

### What Changed
- Replaced broken/default council roster entries:
  - Kimi: `moonshotai/kimi-k2.6` -> `moonshotai/kimi-k2.7-code`
  - Gemini: `google/gemini-3.5-flash` -> `google/gemini-2.5-flash`
- Kept compatibility aliases so old Kimi/Gemini IDs remap to the working variants.
- Added `accepted_claims`, `rejected_claims`, and `challenges` fields to each `PanelVerdict`.
- Added a second council round where each model reviews the other models' claims and can revise rating/confidence.
- Made live council calls sequential to avoid OpenRouter provider empty-response issues seen when providers are called concurrently.
- Added tolerant fallback parsing for model responses that do not follow strict JSON schema.
- Prevented degraded cross-exam responses from overwriting a stronger first-pass verdict.
- Updated the active dashboard council cards to show Accepts / Rejects / Challenges for each model.
- Updated canonical web fallback roster/types/card rendering to match.

### Verification
- OpenRouter model registry check showed current Kimi/Gemini IDs.
- Live single-model tests:
  - `moonshotai/kimi-k2.7-code` worked.
  - `google/gemini-2.5-flash` worked.
  - `google/gemini-3.1-flash-lite` also worked, but the runtime default was set to Gemini 2.5 Flash.
  - `moonshotai/kimi-k2.6`, `moonshotai/kimi-k2.5`, and `google/gemini-3.5-flash` were unreliable in this council path.
- Live full council smoke on MSFT with GLM, Kimi, DeepSeek, and Gemini:
  - `council_mode=openrouter_live`
  - nonzero OpenRouter cost
  - no degraded reasons
  - all four panel seats returned accepted/rejected/challenge fields
- Tests/checks:
  - `/tmp/alphadesk-api-test-venv/bin/python -m pytest tests/test_api_council.py -q` -> 23 passed
  - `/tmp/alphadesk-api-test-venv/bin/python -m ruff check src/api tests/test_api_council.py` -> passed
  - `cd web && npm test -- --run && npm run build` -> passed
  - `cd /Users/vikram/workspace/alpha-desk/dashboard && npm run typecheck && npm run build` -> passed

### Current State
- FastAPI is running in detached `screen` session `alphadesk-api` on `127.0.0.1:8000`.
- The active council roster is:
  - `z-ai/glm-5.2`
  - `moonshotai/kimi-k2.7-code`
  - `deepseek/deepseek-v4-pro`
  - `google/gemini-2.5-flash`
- OpenRouter mock mode remains disabled in the running backend.
- The OpenRouter key remains runtime-only and was not written into repo files or this handoff.
## Session 2026-06-21 20:06 UTC - Codex

### Goal
- Make the Model Council visibly indicate that a live sequential council run is still in progress.

### Files Changed
- `/Users/vikram/workspace/alpha-desk/dashboard/src/components/council/CouncilView.tsx`
- `docs/AI_HANDOFF.md`

### What Changed
- Added a prominent live-running banner to the active dashboard council page.
- Banner shows:
  - spinner
  - active ticker
  - elapsed timer
  - returned-seat count
  - per-model pending/returned status chips
- This addresses the UX gap where the backend was working sequentially but the page only showed a small status badge and quiet skeleton cards.

### Verification
- `cd /Users/vikram/workspace/alpha-desk/dashboard && npm run typecheck` -> passed
- `cd /Users/vikram/workspace/alpha-desk/dashboard && npm run build` -> passed
- `http://127.0.0.1:5173/council` responds.
- `http://127.0.0.1:8000/api/council/models` responds.
## Session 2026-06-21 20:14 UTC - Codex

### Goal
- Diagnose and fix Kimi/DeepSeek council cards showing broken raw JSON or empty-response placeholders.

### Files Changed
- `src/api/app.py`
- `docs/AI_HANDOFF.md`

### What Changed
- Added partial JSON salvage for panel responses so malformed/truncated JSON fields are extracted instead of rendered as the thesis.
- Expanded degraded cross-exam detection so retry/truncated/raw JSON responses cannot overwrite a cleaner first-pass model result.
- Restarted the live FastAPI backend with the fix.

### Verification
- `/tmp/alphadesk-api-test-venv/bin/python -m py_compile src/api/app.py tests/test_api_council.py` -> passed
- `/tmp/alphadesk-api-test-venv/bin/python -m pytest tests/test_api_council.py -q` -> 23 passed
- `/tmp/alphadesk-api-test-venv/bin/python -m ruff check src/api tests/test_api_council.py` -> passed
- Fresh full live NVDA council with GLM, Kimi K2.7 Code, DeepSeek V4 Pro, and Gemini 2.5 Flash:
  - all four models returned real panel theses
  - no empty-response placeholders in parsed panel output
  - no degraded reasons
  - nonzero live OpenRouter cost

### Notes
- The broken screenshot came from a malformed Kimi cross-exam response being treated as plain text and rendered as the thesis. DeepSeek was previously affected by provider empty-response behavior in multi-model runs; the latest full run returned a normal DeepSeek thesis.
## Session 2026-06-22 00:21 UTC - Codex

### Goal
- Restore Gemini council roster entry to `google/gemini-3.5-flash` instead of `google/gemini-2.5-flash`.

### Files Changed
- `src/api/app.py`
- `tests/test_api_council.py`
- `web/src/App.tsx`
- `web/src/components/CommandBar.test.tsx`
- `web/src/components/Council.test.tsx`
- `/Users/vikram/workspace/alpha-desk/dashboard/src/components/council/CouncilView.tsx`
- `docs/AI_HANDOFF.md`

### What Changed
- Changed default council roster back to `google/gemini-3.5-flash`.
- Removed the alias that remapped `google/gemini-3.5-flash` to Gemini 2.5 Flash.
- Updated dashboard and canonical web fallback/test references to Gemini 3.5 Flash.
- Restarted the live FastAPI backend with runtime `OPENROUTER_ANALYSIS_MODELS` containing `google/gemini-3.5-flash`.

### Verification
- `/tmp/alphadesk-api-test-venv/bin/python -m pytest tests/test_api_council.py -q` -> 23 passed
- `/tmp/alphadesk-api-test-venv/bin/python -m ruff check src/api tests/test_api_council.py` -> passed
- `cd /Users/vikram/Documents/New project/web && npm test -- --run && npm run build` -> passed
- `cd /Users/vikram/workspace/alpha-desk/dashboard && npm run typecheck && npm run build` -> passed
- Live backend `GET /api/council/models` returns `google/gemini-3.5-flash`.
- Live Gemini 3.5 council smoke on NVDA returned:
  - `model_id=google/gemini-3.5-flash`
  - clean thesis
  - accepted/rejected/challenge fields
  - `council_mode=openrouter_live`
  - no degraded reasons
## Session 2026-06-22 00:33 UTC - Codex

### Goal
- Remove leaked empty-response placeholders from Kimi and DeepSeek council cards.

### Files Changed
- `src/api/app.py`
- `tests/test_api_council.py`
- `docs/AI_HANDOFF.md`

### What Changed
- Fixed `_merge_cross_exam_verdict` so degraded cross-exam output is discarded entirely instead of copying placeholder `rejected_claims` / `challenges` onto a valid first-pass panel result.
- Skipped cross-exam when only one model is selected, since there are no other seats to critique.
- Removed internal partial-JSON parser warning text from user-facing challenge lists.
- Added a regression test that ensures empty-response placeholder text cannot overwrite a valid Kimi first-pass panel.

### Verification
- `/tmp/alphadesk-api-test-venv/bin/python -m pytest tests/test_api_council.py -q` -> 24 passed
- `/tmp/alphadesk-api-test-venv/bin/python -m ruff check src/api tests/test_api_council.py` -> passed
- Fresh live full NVDA council before final cleanup confirmed:
  - no `Empty model response cannot validate other seats` in SSE output
  - no `Retry this model or inspect provider availability` in SSE output
  - Kimi K2.7 Code and DeepSeek V4 Pro returned real rejected/challenge claims
- Restarted FastAPI backend in detached `screen` session `alphadesk-api`.
## Session 2026-06-22 00:00 UTC - Codex

### Goal
- Stop malformed Gemini 3.5/Kimi/DeepSeek council output from rendering as raw JSON, and preserve completed council runs in local SQLite so tab/page changes do not lose the result.

### Files Changed
- `src/api/app.py`
- `src/api/run_store.py`
- `tests/test_api_council.py`
- `web/src/api/client.ts`
- `web/src/api/types.ts`
- `/Users/vikram/workspace/alpha-desk/dashboard/src/lib/api.ts`
- `/Users/vikram/workspace/alpha-desk/dashboard/src/lib/useCouncilStream.ts`
- `/Users/vikram/workspace/alpha-desk/dashboard/src/types/index.ts`
- `/Users/vikram/workspace/alpha-desk/dashboard/src/components/council/CouncilView.tsx`
- `docs/AI_HANDOFF.md`

### What Changed
- Added `council_runs` to `data/cockpit_runs.db` via `src/api/run_store.py`.
- Persisted successful `POST /api/council/run` and streamed `/api/council/stream` completions.
- Added `GET /api/council/runs/latest` and `GET /api/council/runs`.
- Added optional `run_id` and `saved_at` to council result and done-event payloads.
- Updated the active dashboard to hydrate the latest saved council run on page load/remount.
- Added saved-run metadata to the council done card.
- Added a degraded-output retry path for OpenRouter panel calls.
- Prevented JSON-shaped malformed text from being displayed as a model thesis.
- Skipped cross-examination for degraded first-pass seats.
- Bumped the running backend `OPENROUTER_MODEL_MAX_TOKENS` to `1200` to reduce truncated JSON from Gemini 3.5 Flash.

### Verification
- `/tmp/alphadesk-api-test-venv/bin/python -m pytest tests/test_api_council.py -q` -> 26 passed.
- `/tmp/alphadesk-api-test-venv/bin/python -m ruff check src/api tests/test_api_council.py` -> passed.
- `/tmp/alphadesk-api-test-venv/bin/python -m py_compile src/api/app.py src/api/run_store.py tests/test_api_council.py` -> passed.
- `cd /Users/vikram/workspace/alpha-desk/dashboard && npm run typecheck && npm run build` -> passed.
- `cd /Users/vikram/Documents/New project/web && npm test -- --run && npm run build` -> passed.
- Restarted FastAPI in live OpenRouter mode on `127.0.0.1:8000`.
- Live Gemini 3.5 Flash NVDA smoke returned a clean thesis, no degraded reasons, nonzero OpenRouter cost, and saved as council run `#1`.
- `GET /api/council/runs/latest?ticker=NVDA` returned saved run `#1`.
- Browser check at `http://127.0.0.1:5173/council` restored saved run `#1`, showed the clean Gemini thesis, and did not contain raw `{"model_id":...` text or the unstructured-output warning.

### Current State
- Backend remains running at `http://127.0.0.1:8000`.
- Dashboard remains running at `http://127.0.0.1:5173`.
- The OpenRouter key remains runtime-only and was not written to repo files or this handoff.
- `data/cockpit_runs.db` now contains the live Gemini smoke run and should remain a local, uncommitted runtime artifact.
## Session 2026-06-22 00:00 UTC - Codex

### Goal
- Link Alpha Scout ideas to a model-council deep dive and diagnose why META/NVDA/AMZN/MSFT were not highlighted by the current Scout output.

### Files Changed
- `/Users/vikram/workspace/alpha-desk/dashboard/src/components/moonshots/MoonshotCard.tsx`
- `/Users/vikram/workspace/alpha-desk/dashboard/src/components/council/CouncilView.tsx`
- `docs/AI_HANDOFF.md`

### What Changed
- Added a `Deep dive` action to each active-dashboard Alpha Scout card.
- The action navigates to `/council?ticker=<ticker>&run=1&from=scout`.
- The council page now reads `ticker` from the query string and auto-starts a council run once when `run=1` or `autorun=1`.
- The council page also supports `/council?ticker=<ticker>` without autorun, prefilling the ticker only.

### Diagnosis
- Saved Alpha Scout runs were all `new_discoveries`, not `top_buys`.
- `new_discoveries` intentionally excludes holdings/watchlist names, and the latest run audit explicitly excluded AMZN, META, MSFT, and NVDA as tracked tickers.
- A live direct `top_buys` pipeline run included the tracked universe and scored the target names, but ranked them low:
  - AMZN rank 35, composite 61.5
  - NVDA rank 39, composite 60.5
  - META rank 40, composite 60.5
  - MSFT rank 45, composite 59.5
- All four had fundamental scores of 100 but were dragged down by low technical scores, diversification penalties, and novelty penalties for existing holdings/watchlist names.
- Synthesis only saw the top 20 scored candidates, so those names never reached the LLM synthesis step in this run.
- The live `top_buys` synthesis also needed JSON repair (`llm_repaired_json`), so synthesis reliability remains a separate issue.

### Verification
- `cd /Users/vikram/workspace/alpha-desk/dashboard && npm run typecheck` -> passed.
- `cd /Users/vikram/workspace/alpha-desk/dashboard && npm run build` -> passed.
- Browser check confirmed `/scout` showed 10 `Deep dive` buttons.
- Browser check confirmed `/council?ticker=META` prefills the council ticker input with `META`.

### Recommended Next Step
- Make Alpha Scout mode-aware:
  - keep `new_discoveries` novelty-heavy,
  - make `top_buys` conviction/core-quality heavy,
  - report tracked ticker rank/score/reason in the UI,
  - force top tracked/core candidates into synthesis or final coverage when their fundamentals/council score justify it.
## Session 2026-06-22 03:47 UTC - Codex

### Goal
- Fix Alpha Scout `top_buys` so high-quality tracked/core names such as META, AMZN, NVDA, AVGO, and TSM are not buried by discovery-style novelty/diversification scoring.

### Files Changed
- `src/alpha_scout/screener.py`
- `src/alpha_scout/main.py`
- `tests/test_alpha_scout_core.py`
- `/Users/vikram/workspace/alpha-desk/dashboard/src/components/moonshots/MoonshotsView.tsx`
- `/Users/vikram/workspace/alpha-desk/dashboard/src/lib/api.ts`
- `docs/AI_HANDOFF.md`

### What Changed
- Added mode-aware Scout scoring:
  - `new_discoveries` keeps the existing novelty-heavy behavior.
  - `top_buys` now uses quality/core-company weights with more emphasis on fundamentals, evidence quality, catalysts, and durable technical setup.
- Added a top-buy quality floor for tracked portfolio/watchlist names that have strong fundamentals and evidence.
- Added a synthesis shortlist coverage step so high-quality tracked names cannot be excluded merely because they fell outside the raw top-N discovery ranking.
- Added a final top-buy core coverage step so strong tracked names survive LLM synthesis if the model omits them.
- Expanded `tracked_ticker_checks` with rank, composite, score details, synthesis inclusion, recommendation status, and omission reason.
- Updated the active dashboard Scout page to:
  - default to `top_buys`,
  - hydrate the latest saved top-buy run first,
  - show tracked coverage diagnostics,
  - make digest/moonshot fetches call top buys by default.

### Verification
- `/tmp/alphadesk-api-test-venv/bin/python -m py_compile src/alpha_scout/screener.py src/alpha_scout/main.py tests/test_alpha_scout_core.py` -> passed.
- `/tmp/alphadesk-api-test-venv/bin/python -m pytest tests/test_alpha_scout_core.py -q` -> 11 passed.
- `/tmp/alphadesk-api-test-venv/bin/python -m pytest tests/test_api_council.py -q` -> 26 passed.
- `/tmp/alphadesk-api-test-venv/bin/python -m ruff check src/alpha_scout/screener.py src/alpha_scout/main.py tests/test_alpha_scout_core.py src/api/app.py tests/test_api_council.py` -> passed.
- `cd /Users/vikram/workspace/alpha-desk/dashboard && npm run typecheck` -> passed.
- `cd /Users/vikram/workspace/alpha-desk/dashboard && npm run build` -> passed.
- Restarted FastAPI live on `127.0.0.1:8000`.
- Live `GET /api/ideas/today?mode=top_buys&limit=10` saved run `#7` with nonzero OpenRouter cost and returned:
  - TSM rank 1, score 89.3
  - NVDA rank 3, score 88.1
  - AVGO rank 4, score 88.1
  - META rank 6, score 88.0
  - AMZN rank 7, score 87.5
- `GET /api/ideas/runs/latest?mode=top_buys` returns saved run `#7`.

### Notes
- The Taiwan Semiconductor ticker is `TSM`, not `TSMC`, so `TSMC` will not appear as a tracked ticker key.
- Backend remains live on `127.0.0.1:8000`; active dashboard remains live on `127.0.0.1:5173`.
- The OpenRouter key was restored only into the running backend environment and was not written into repo files or this handoff.
## Session 2026-06-22 21:00 UTC - Codex

### Goal
- Run a live Alpha Scout plus Model Council batch for the user's requested allocation universe and compare AlphaDesk output to an independent ChatGPT research allocation.

### Assets Analyzed
- META, NVDA, AVGO, TSM, SOFI, MSFT, UBER, ETH, VRT, APLD, RDDT, MXL, LITE, DIS.
- Normalized names:
  - Vertiv -> VRT
  - Lumentum -> LITE
  - Taiwan Semiconductor -> TSM
  - Ethereum -> ETH

### Runtime Work
- Inspected council code path for buy-bias risk:
  - Ratings support Buy, Overweight, Hold, Underweight, and Sell.
  - Direct OpenRouter council aggregates by modal rating.
  - The crowded-bullish flag is surfaced but does not automatically lower the rating.
- Ran live `GET /api/ideas/today?mode=top_buys&limit=12`.
- Ran live `POST /api/council/run` for each requested asset using:
  - `z-ai/glm-5.2`
  - `moonshotai/kimi-k2.7-code`
  - `deepseek/deepseek-v4-pro`
  - `google/gemini-3.5-flash`
- Pulled current quote/fundamental snapshots with local yfinance and used web searches for current company earnings/news context.

### Live Alpha Scout Result
- Saved Scout run `#9`, cost `$0.0109266`.
- Top 12:
  - AFRM 91.0
  - TSM 88.5
  - GOOG 88.2
  - NVDA 88.1
  - SMCI 88.1
  - AVGO 88.1
  - META 88.0
  - AMZN 87.5
  - QCOM 86.9
  - CRWD 86.3
  - MU 86.0
  - MSFT 86.0

### Live Model Council Results
- META run `#6`: Buy, conviction 0.78, no degradation.
- NVDA run `#7`: Buy, conviction 0.81, no degradation.
- AVGO run `#8`: Buy, conviction 0.57, one zero-confidence GLM seat.
- TSM run `#9`: Buy, conviction 0.82, no degradation.
- SOFI run `#10`: Overweight, conviction 0.59, no degradation.
- MSFT run `#11`: Buy, conviction 0.82, no degradation.
- UBER run `#12`: Overweight, conviction 0.56, GLM degraded before returning a real thesis.
- ETH run `#13`: Overweight, conviction 0.64, no degradation; equity council schema is a weaker fit for crypto.
- VRT run `#14`: Overweight, conviction 0.54, one zero-confidence Gemini seat.
- APLD run `#15`: Overweight, conviction 0.41, one zero-confidence GLM seat.
- RDDT run `#16`: Overweight, conviction 0.70, no degradation.
- MXL run `#17`: Hold, conviction 0.54, Kimi degraded.
- LITE run `#18`: Overweight, conviction 0.65, no degradation.
- DIS run `#19`: Hold, conviction 0.59, DeepSeek cross-exam validation failed.

### Notes
- The council is not mechanically always bullish: MXL and DIS came back Hold, and ETH had a Gemini Hold seat.
- The batch still showed a constructive bias: no requested asset received Underweight or Sell.
- Final response framed the $100k allocation as research support, not personalized financial advice.
- No secrets were written to repo files or this handoff.
## Session 2026-06-22 15:01 UTC - Codex

### Goal
- Merge the accumulated AlphaDesk cockpit/backend changes into the local `main` branch.

### Planned Scope
- Commit current working-tree changes on `codex/phase-f-final-a11y-polish`.
- Merge that branch into local `main`.
- Preserve unrelated files and avoid destructive git commands.

### Verification Plan
- Run focused backend tests for Alpha Scout and council API.
- Run backend lint for changed Python surfaces.
- Run frontend tests/build for `web/`.
- Generate the AI handoff context pack after merge work.

### Result
- Committed current feature-branch work as `88c72c4` (`feat: wire live cockpit persistence and top-buy scoring`).
- Switched to local `main` and merged `codex/phase-f-final-a11y-polish` with a non-fast-forward merge commit.
- Fetched and merged the newer `origin/main` dashboard commit before pushing.
- Updated one cost-attribution test expectation to match the merged Gemini 3.1 alias target.
- Pushed local `main` to `origin/main`.

### Verification
- `/tmp/alphadesk-api-test-venv/bin/python -m pytest tests/test_alpha_scout_core.py tests/test_api_council.py tests/test_cost_attribution.py -q` -> 38 passed, 1 third-party Starlette/httpx deprecation warning.
- `/tmp/alphadesk-api-test-venv/bin/python -m ruff check src/api src/alpha_scout/main.py src/alpha_scout/screener.py src/alpha_scout/synthesizer.py src/advisor/macro_analyst.py src/shared/gemini_compat.py tests/test_alpha_scout_core.py tests/test_api_council.py tests/test_cost_attribution.py` -> passed.
- `cd web && npm test -- --run && npm run build` -> passed.
- A broader ruff check over all `src/alpha_scout` surfaced two pre-existing unused imports in untouched files (`reddit_moonshot_sourcer.py`, `thematic_scanner.py`); these were not modified for the merge.
## Session 2026-06-22 18:20 PDT - Codex

### Goal
- Complete the attached recommendation-quality task brief as seven independently shippable commits on `codex/recommendation-quality-fixes`.

### Commits
- `07a6079 fix(config): reconcile holdings and upsert macro seeds`
- `0a429dc feat(deep-research): add web-search grounding`
- `c4523ee feat(macro): use prediction markets for rate regime`
- `2e67d0c feat(conviction): implement weighted evidence scoring`
- `255fff1 feat(strategy): add role-dependent investment gates`
- `d7ccfaa feat(strategy): add recommendation position sizing`
- `bae2d10 feat(committee): gate model council in morning brief`

### Result
- Portfolio holdings now reconcile `portfolio.yaml` positions with `advisor.yaml` thesis metadata, warning on drift.
- Macro seed text upserts descriptions/affected tickers without resetting learned status/evidence.
- Deep research can gather web-search observations with citations and degrades cleanly when unavailable.
- Macro thesis evaluation now consumes prediction markets and deterministically weakens stale rate-easing assumptions when cut odds are low.
- Conviction ranking uses weighted evidence dimensions separate from Alpha Scout screening weights.
- Investment gates are role-dependent, with ballast/defensive total-return handling and moonshot exemption.
- Strategy output now includes sizing, cash sleeve, entry strategy, portfolio impact, concentration flags, and trim suggestions.
- Morning full runs can optionally call the model council when `COUNCIL_ENABLED=true`, with cost-cap/run-budget fallbacks; disabled default leaves the editor path unchanged.

### Verification
- `/tmp/alphadesk-api-test-venv/bin/python -m pytest tests/test_council_brief_integration.py -q` -> 3 passed.
- `/tmp/alphadesk-api-test-venv/bin/python -m pytest tests/test_council_brief_integration.py tests/test_position_sizer.py tests/test_gate_roles.py tests/test_conviction_fix.py tests/test_macro_regime.py tests/test_macro_dedup.py tests/test_deep_research_websearch.py tests/test_config_reconciliation.py -q` -> 27 passed.
- `/tmp/alphadesk-api-test-venv/bin/python -m pytest tests/test_api_council.py tests/test_council_brief_integration.py -q` -> 29 passed, 1 third-party Starlette/httpx deprecation warning.
- `/tmp/alphadesk-api-test-venv/bin/python -m ruff check src/advisor/analyst_committee.py src/advisor/main.py tests/test_council_brief_integration.py` -> passed.
- `git ls-files 'tests/*.py' | tr '\n' ' ' | xargs /tmp/alphadesk-api-test-venv/bin/python -m pytest -q` -> 360 passed, 1 skipped, 1 third-party Starlette/httpx deprecation warning.

### Caveats
- Raw `/tmp/alphadesk-api-test-venv/bin/python -m pytest -q` collected unrelated untracked duplicate `* 2.py` test files and failed in `tests/test_cost_attribution 2.py` because that duplicate still expects the older `gemini-2.5-pro` alias. The tracked suite is green.
- `/tmp/alphadesk-api-test-venv/bin/python tests/simulate_week.py` failed before reaching the current committee path because the stale simulator patches `src.advisor.analyst_committee.check_budget`, which is not an exported attribute. The generated preview artifact from this failed validation attempt was restored.
## Session 2026-06-22 20:24 PDT - Codex

### Goal
- Verify whether the latest pushed `main` was actually running locally after the user still saw old results.

### Result
- Confirmed GitHub/local `main` was at `e38e405`, but the running local backend was an older process started on 2026-06-21 and the frontend on port 5173 was serving `/Users/vikram/workspace/alpha-desk/dashboard`, not this repo's `web/`.
- Restarted FastAPI from `/Users/vikram/Documents/New project` on `127.0.0.1:8000` with live OpenRouter mode preserved from the old process environment.
- Restarted Vite from `/Users/vikram/Documents/New project/web` on `127.0.0.1:5173`.
- Fresh top-buys run completed as run `#11`, cost `$0.0147632`, no degraded reasons.

### Fresh Top-Buys Run #11
- AFRM rank 1, score 0.91.
- TSM rank 2, score 0.893.
- GOOG rank 3, score 0.882.
- NVDA rank 4, score 0.881.
- SMCI rank 5, score 0.881.
- AVGO rank 6, score 0.881.
- META rank 7, score 0.88.
- AMZN rank 8, score 0.875.
- CRWD rank 9, score 0.863.
- MSFT rank 10, score 0.86.

### Notes
- If the browser still shows old content, hard-refresh `http://127.0.0.1:5173/` or close the prior tab. The local services are now running from the current repo.
## Session 2026-06-22 20:53 PDT - Codex

### Goal
- Fix the frontend/backend split after the user noticed the theme changed while the backend was updated.

### Result
- Ported the previously-running dark glass dashboard theme into this repo's `web/` app.
- Kept the dashboard trimmed to live backend pages: Backend Cockpit, Alpha Scout, Council, Macro, and Portfolio.
- Updated frontend tooling to Tailwind 4 + Vite 8, restored the `@` alias, and added a Vitest smoke test for the cockpit shell.
- Removed stale generated Vite/PostCSS config artifacts that caused the wrong theme pipeline to load locally.
- Restarted Vite from `/Users/vikram/Documents/New project/web` on `127.0.0.1:5173`; backend remains live from this repo on `127.0.0.1:8000`.

### Verification
- `cd web && npm run typecheck` -> passed.
- `cd web && npm test -- --run` -> 1 passed.
- `cd web && npm run build` -> passed, clean Tailwind 4 build.
- `/tmp/alphadesk-api-test-venv/bin/python -m pytest tests/test_api_council.py tests/test_alpha_scout_core.py tests/test_council_brief_integration.py -q` -> 40 passed, 1 third-party Starlette/httpx deprecation warning.
- `git ls-files 'tests/*.py' | tr '\n' ' ' | xargs /tmp/alphadesk-api-test-venv/bin/python -m pytest -q` -> 360 passed, 1 skipped, 1 third-party Starlette/httpx deprecation warning.
- Browser smoke via system Chrome:
  - `/` rendered `Backend Cockpit`, Alpha Scout, Model Council, Macro Regime, Portfolio, and `Backend ready` with zero console/page errors.
  - `/scout` rendered saved top-buys data with run id, backend cost, and NVDA/META/AMZN present.
## Session 2026-06-22 21:21 PDT - Codex

### Goal
- Fix the Model Council timeout/blank-skeleton behavior reported from the web cockpit.

### Root Cause
- `GET /api/council/stream` emitted `panel_started`, then ran the entire OpenRouter council under one wrapper timeout before yielding any panel results.
- Four live model seats plus the adversarial cross-exam round could exceed that wrapper timeout, so the UI showed empty cards and then a misleading `complete` status with `Mode: timeout`.

### Result
- Added an OpenRouter-specific streaming path that emits `progress` and `panel_model_result` events as each model returns.
- Initial seats and cross-exam seats now run with per-model timeouts and stream partial results instead of making the whole UI wait for the slowest provider.
- Timed-out or failed seats become explicit zero-confidence degraded panel cards while usable seats still synthesize and persist.
- The frontend now consumes `progress` SSE events, updates the running banner copy, and treats a backend `timeout` done event as an error state rather than a green complete state.
- Restarted local FastAPI and Vite from this repo using detached processes:
  - Backend: `127.0.0.1:8000`
  - Frontend: `127.0.0.1:5173`

### Live Verification
- Ran live `AFRM` council stream against the fixed backend with:
  - `z-ai/glm-5.2`
  - `moonshotai/kimi-k2.7-code`
  - `deepseek/deepseek-v4-pro`
  - `google/gemini-3.5-flash`
- Initial panel cards streamed by 26s.
- Cross-exam and final synthesis completed at 66s.
- Saved council run `#20`, execution mode `openrouter_live`, cost `$0.052389`, no degraded reasons.
- Browser smoke on `/council?ticker=AFRM` showed saved run `#20`, all four panels, `Mode: openrouter_live`, and no console/page errors.

### Verification
- `/tmp/alphadesk-api-test-venv/bin/python -m pytest tests/test_api_council.py -q` -> 28 passed, 1 third-party Starlette/httpx deprecation warning.
- `/tmp/alphadesk-api-test-venv/bin/python -m ruff check src/api tests/test_api_council.py` -> passed.
- `cd web && npm run typecheck` -> passed.
- `cd web && npm test -- --run` -> 1 passed.
- `cd web && npm run build` -> passed.
- `git ls-files 'tests/*.py' | tr '\n' ' ' | xargs /tmp/alphadesk-api-test-venv/bin/python -m pytest -q` -> 362 passed, 1 skipped, 1 third-party Starlette/httpx deprecation warning.

### Notes
- No API keys were written to repo files, logs, diffs, or this handoff.
- The unrelated untracked duplicate `* 2` files remain untouched.
## Session 2026-06-24 22:41 PDT - Codex

### Goal
- Read through the project to gain working context only; no implementation change was requested.

### Result
- Read `AGENTS.md`, `docs/PROJECT_OVERVIEW.md`, `docs/AI_CONTEXT.md`, the latest `docs/AI_HANDOFF.md` entry, and key backend/frontend/config/test files.
- Confirmed the canonical cockpit backend is `src/api/app.py` launched by `run_api.py`; `server.py` appears to be a legacy compatibility/stub surface despite older docs referencing it.
- Mapped the two frontend surfaces: `web/` is the current cockpit, while `dashboard/` still contains the deterministic score-engine Top Buys view not yet ported into `web/`.
- Confirmed score-engine APIs exist in `src/api/app.py`, while the score engine itself lives under `src/score_engine/` and currently defaults its ticker universe from `config/advisor.yaml` metadata holdings.
- Noted documentation/code drift around OpenRouter model invariants, score run-type support, and `portfolio.yaml` versus `advisor.yaml` holdings.

### Verification
- Context pass only; no tests were run.
- `git status --short` was clean before this handoff note.

### Notes
- No secrets or local database contents were read.
- No context pack was generated because this was not a handoff to another model.
## Session 2026-06-24 22:51 PDT - Codex

### Goal
- Fix the Top Buys/Alpha Scout mismatch where AMZN scored as Weak/Hold while the council thesis was bullish, and remove Gemini 3.5 Flash from the council roster for now.

### Result
- Changed score normalization in `src/score_engine/aggregator.py` so weak directional evidence no longer counts as a full-strength denominator vote.
- Updated the valuation sensor so moderate forward CAGR plus a high margin of safety is bullish instead of neutral.
- Added regression coverage for the AMZN-shaped signal mix; the representative score is now 7.20, in the Buy/Strong band.
- Removed Gemini 3.5 Flash from default council rosters in backend, `web/`, and `dashboard/`.
- Routed legacy Gemini council ids to GLM 5.2 and normalized stale Kimi K2.7 ids to Kimi K2.6 so old UI chips/env values do not call broken models.
- Changed the OpenRouter haiku/bulk default in `src/shared/gemini_compat.py` from Gemini 3.5 Flash to GLM 5.2.
- Updated `docs/PROJECT_OVERVIEW.md` to describe the current three-model OpenRouter allowlist.

### Verification
- AMZN-shaped scoring snippet returned `TickerScore(... score=7.2 ...)`.
- `/tmp/alphadesk-api-test-venv/bin/python -m pytest tests/test_breadth_gate.py tests/test_valuation_sensor.py tests/test_score_repeatability.py tests/test_api_council.py -q` -> 43 passed, 1 third-party Starlette/httpx deprecation warning.
- `/tmp/alphadesk-api-test-venv/bin/python -m ruff check src/api/app.py src/score_engine/aggregator.py src/score_engine/sensors/valuation.py src/shared/gemini_compat.py tests/test_breadth_gate.py tests/test_valuation_sensor.py tests/test_api_council.py` -> passed.
- `cd web && npm ci` -> installed lockfile deps, 0 vulnerabilities.
- `cd web && npm run typecheck` -> passed.
- `cd web && npm test -- --run` -> 1 passed.
- `cd web && npm run build` -> passed.
- `cd dashboard && npm run typecheck` -> passed.
- `cd dashboard && npm run build` -> passed.

### Notes
- No secrets or local database contents were read.
- Existing saved score snapshots may still show old scores until the score engine is rerun.
## Session 2026-06-24 23:13 PDT - Codex

### Goal
- Rewire Scout/Top Buys and Model Council so the council audits upstream buy theses instead of starting from a ticker-only prompt.

### Result
- Confirmed the previous flow only passed `/council?ticker=...&run=1`, so model seats did not see the Scout or score-engine thesis.
- Added optional council context fields: `source`, `idea_run_id`, and `score_snapshot_id`.
- Added `run_store.get_idea_scout_run()` and backend context resolution for saved Alpha Scout runs and score-engine snapshots.
- Injected compact upstream context into first-pass council prompts and cross-exam prompts.
- Added a context-aware synthesis tie-breaker: a high-conviction Scout/score prior can prevent final synthesis from mechanically collapsing to Hold when there is at least one bullish/overweight seat and no bearish seat.
- Wired `web/` Alpha Scout cards to pass `source=scout&idea_run_id=<run>`.
- Wired `dashboard/` score-engine Top Buys cards to pass `source=score_engine&score_snapshot_id=<snapshot>`.
- Added a visible Council page context line, e.g. `Using Alpha Scout context from run #4.`
- Updated `docs/PROJECT_OVERVIEW.md` with the new context-aware council contract.

### Verification
- `/tmp/alphadesk-api-test-venv/bin/python -m pytest tests/test_api_council.py tests/test_breadth_gate.py tests/test_valuation_sensor.py -q` -> 39 passed, 1 third-party Starlette/httpx deprecation warning.
- `/tmp/alphadesk-api-test-venv/bin/python -m ruff check src/api/app.py src/api/run_store.py tests/test_api_council.py` -> passed.
- `/tmp/alphadesk-api-test-venv/bin/python -m py_compile src/api/app.py src/api/run_store.py` -> passed.
- `cd web && npm run typecheck` -> passed.
- `cd web && npm test -- --run` -> 1 passed.
- `cd web && npm run build` -> passed.
- `cd dashboard && npm run typecheck` -> passed.
- `cd dashboard && npm run build` -> passed.
- Browser MCP loaded `http://localhost:5173/council?ticker=AFRM&source=scout&idea_run_id=4`, rendered the context label, and reported no console errors.

### Notes
- The first Scout run still does not automatically run a paid council for every candidate. The implemented contract makes follow-up council runs source-aware; automatic council validation for top-N candidates should be a separate explicit policy/toggle because it has latency and cost implications.
- Backend was restarted live with `OPENROUTER_MOCK=0` and `ALPHA_SCOUT_MOCK=0`; frontend remained live on `127.0.0.1:5173`.
## Session 2026-06-27 16:31 PDT - Codex

### Goal
- Execute the attached sequencing brief through the web/API consolidation milestones without introducing live-cost side effects.

### Result
- Completed the foundation/OpenRouter/delivery/web-entry portions of the plan:
  - `security.py` now requires only `OPENROUTER_API_KEY` and no longer exposes Telegram chat authorization.
  - `gemini_compat.py`, `model_registry.py`, and `advisor/council.py` are OpenRouter-only, with the three-model GLM/Kimi/DeepSeek roster and no direct Anthropic/Gemini/GCP SDK usage.
  - Advisor committee council calls now use `CouncilClient`; GCP-specific tests were replaced with OpenRouter council tests.
  - Gemini grounded web search was removed; web search is HTTP-provider only.
  - Telegram/email delivery files and stale secondary entry points were deleted (`telegram_bot.py`, email reporter/template, `server.py`, `run_daily.py`, `score.py`, `run_deployment_plan.py`, `src/report/__main__.py`).
  - Docker now starts the FastAPI cockpit and compose includes a MySQL 8 service with `ALPHADESK_DB_*` env wiring.
  - Added shared MySQL helpers (`src/shared/db.py`) and broad schema bootstrap (`src/shared/schema.py`) including `daily_brief_runs`.
  - Added `src/api/brief_store.py`, `POST /api/brief/run`, and `GET /api/brief/runs/latest`; persistence failures degrade the run response instead of failing a completed brief.
  - Replaced the `/` frontend backend-status hub with a Daily Brief view that can run the blocking brief endpoint and display the latest saved/unsaved result.
- Started local dev servers:
  - Backend: `http://127.0.0.1:8001` because port 8000 was already occupied.
  - Frontend: `http://127.0.0.1:5173` with `VITE_API_BASE_URL=http://127.0.0.1:8001`.

### Verification
- `python -m py_compile src/shared/db.py src/shared/schema.py src/api/brief_store.py src/api/app.py src/advisor/council.py src/shared/gemini_compat.py src/shared/model_registry.py src/advisor/analyst_committee.py src/advisor/main.py src/advisor/run_profile.py` -> passed.
- `python -m ruff check src/api/app.py src/api/brief_store.py src/shared/db.py src/shared/schema.py src/shared/gemini_compat.py src/shared/model_registry.py src/advisor/council.py src/advisor/analyst_committee.py src/advisor/main.py src/advisor/run_profile.py src/shared/security.py src/shared/web_search.py tests/test_api_brief.py tests/test_openrouter_council.py tests/test_api_council.py tests/test_council_brief_integration.py tests/test_cost_attribution.py tests/test_cost_tracker_resolved_model.py tests/test_v21_integration.py` -> passed.
- `git ls-files 'tests/*.py' | while IFS= read -r f; do [ -e "$f" ] && printf '%s\n' "$f"; done | xargs python -m pytest -q` -> 386 passed, 2 skipped, 1 third-party Starlette/httpx deprecation warning.
- `cd web && npm test -- --run && npm run build` -> passed.
- `curl http://127.0.0.1:8001/api/council/models` -> returned GLM 5.2, Kimi K2.6, DeepSeek V4 Pro.
- `curl -i http://127.0.0.1:8001/api/brief/runs/latest` -> 404 `No saved brief run found.` when local MySQL/PyMySQL are unavailable.
- `curl -I http://127.0.0.1:5173/` -> 200.

### Caveats
- The deeper M4 per-module SQLite-to-MySQL dialect migration was not performed; existing modules such as `memory.py`, `agent_bus.py`, `cost_tracker.py`, `run_store.py`, and the ear trackers still use their current SQLite stores.
- The M7 advisor pipeline reorder (`StructuredDecision`, `MarketDataStore`, S0-S10 reorder, single MySQL transaction, coherence gate) was not performed. Attempting that halfway would be riskier than leaving it for a dedicated follow-up.
- Local backend startup currently warns that PyMySQL is not installed in the active shell. `requirements.txt` has `PyMySQL` and `DBUtils`; install requirements or use Docker Compose for MySQL-backed persistence.
- No context pack was generated because this was not a handoff to another model.
