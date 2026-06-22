# AlphaDesk AI Context

## Product Overview

AlphaDesk is a multi-agent investment research system with two user-facing surfaces:

- A scheduled research stack that produces daily investment briefings.
- A web research cockpit for interactive ticker analysis and idea discovery.

The system is designed to reduce daily research time by combining market data, social/news signals, portfolio context, discovery pipelines, and LLM synthesis.

The current cockpit can:

- Run a model council on a ticker or idea.
- Stream council events into the UI.
- Display panel results, judge synthesis, scenario bars, conviction, risks, catalysts, and portfolio context.
- Run Alpha Scout full pipeline from the "Find today's top ideas" button.
- Display data-source checks for each discovery run.
- Run the council on any idea returned by Alpha Scout.

## Architecture Summary

Backend:

- FastAPI app lives in `src/api/app.py`.
- Pydantic models define the cockpit API contracts.
- OpenRouter direct council is used when `OPENROUTER_API_KEY` is present.
- `OPENROUTER_MOCK=1` makes council and fallback idea scouting deterministic and free.
- `GET /api/ideas/today` now attempts Alpha Scout full pipeline first, then falls back to OpenRouter/mock idea scout if Alpha Scout fails or returns no recommendations.

Frontend:

- React/Vite app lives in `web/src`.
- API client lives in `web/src/api/client.ts`.
- Shared TS payload types live in `web/src/api/types.ts`.
- Main cockpit composition is in `web/src/App.tsx`.
- Idea Scout UI is in `web/src/components/IdeaScout.tsx`.

Alpha Scout:

- Entry point: `src/alpha_scout/main.py`.
- Candidate sourcing: `src/alpha_scout/candidate_sourcer.py`.
- Screening: `src/alpha_scout/screener.py`.
- LLM/fallback synthesis: `src/alpha_scout/synthesizer.py`.
- Formatting: `src/alpha_scout/formatter.py`.
- Publishes discovery signals to the shared agent bus.
- The cockpit idea button now calls Alpha Scout full pipeline first. A verified live run returned 46 sourced candidates, 46 screened candidates, 10 watchlist ideas, and 10 published discovery signals.
- Alpha Scout source checks shown in the UI include pipeline, agent bus, supply chain, sector peers, S&P 500, superinvestor 13F, filing scanner, thematic scanner, yfinance, Reddit moonshot, Kalshi, Polymarket, portfolio config, and council roster.

## Important Files And Directories

- `src/api/app.py` - Main cockpit backend API and OpenRouter/Alpha Scout integration.
- `tests/test_api_council.py` - Backend tests for council, portfolio, OpenRouter normalization, and idea scout.
- `web/src/App.tsx` - Main cockpit shell.
- `web/src/components/CommandBar.tsx` - Ticker input, council button, idea scout button, model chips.
- `web/src/components/IdeaScout.tsx` - Idea cards and source checks.
- `web/src/api/useCouncilStream.ts` - SSE council stream state.
- `config/scout.yaml` - Alpha Scout source configuration and scoring weights.
- `config/advisor.yaml` - Advisor settings, prediction-market config, strategy thresholds.
- `config/portfolio.yaml` - Portfolio holdings.
- `requirements.txt` - Python dependencies.
- `web/package.json` - Frontend scripts and dependencies.
- `docs/AI_HANDOFF.md` - Append-only session log.
- `scripts/ai-handoff.sh` - Generates a context pack for agent handoff.

## Current Known Constraints

- This is an investment research tool, not a trade execution system.
- Source checks are best-effort. They report module/config availability and high-level pipeline stats, not full per-source row counts unless the upstream pipeline exposes them.
- Alpha Scout currently uses prediction-market config but does not query Kalshi/Polymarket inside the full pipeline.
- The current API server is often run with `OPENROUTER_MOCK=1` to avoid live model spend.
- Alpha Scout synthesis falls back to score-based ranking when `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, or `GOOGLE_API_KEY` is unavailable.
- S&P 500 source may require optional `lxml` for `pandas.read_html`.
- In the current `/tmp/alphadesk-venv`, project requirements were installed, but `lxml` is still absent, so the S&P 500 source reports unavailable.
- The installed `yfinance` version imports and supports market-data fetches, but its `Screener` API may be unavailable, causing yfinance screener sourcing to skip while price/fundamental fetches still work.
- Browser automation may need DOM-based clicks when role-based Playwright clicks time out in the in-app browser runtime.

## Key Technical Decisions

- Keep the cockpit API in one FastAPI module for now because the current surface is small and tests are focused there.
- Use Pydantic models for every backend response shape.
- Mirror backend response models in TypeScript interfaces.
- Direct OpenRouter council replaced expensive Fusion as the default OpenRouter path.
- Alpha Scout is the primary source for broad "top ideas"; OpenRouter/mock idea scouting is fallback.
- Source checks are shown in the UI to make missing, configured, and validated data sources visible.
- Tests prefer deterministic mock paths for speed, cost control, and repeatability.
- The handoff script includes untracked text files as pseudo-diffs, excludes noisy lock/cache paths, and redacts obvious API key/token patterns.

## Testing Strategy

Backend:

- Use `pytest` with `fastapi.testclient`.
- Mock expensive or network-heavy paths where possible.
- Keep focused tests around API contracts and normalization logic.

Frontend:

- Use Vitest and React Testing Library.
- Test component behavior, button state, rendering of cards/panels, and error states.
- Use production build as a TypeScript/Vite verification step.

End-to-end/manual:

- Run Vite at `127.0.0.1:5173`.
- Run FastAPI at `127.0.0.1:8000`.
- Browser-test the command bar, idea scout button, source checks, council run, retry path, and console logs.

## Common Gotchas

- The API base URL defaults to `http://127.0.0.1:8000`.
- The frontend may show fallback roster briefly before `/api/council/models` returns.
- `OPENROUTER_MOCK=1` means no live OpenRouter model calls are made.
- Alpha Scout can take 30-60 seconds or more because it sources candidates and fetches market data.
- Missing optional packages can make sources show as unavailable.
- Without a Gemini/Anthropic key, Alpha Scout still completes via score-based fallback synthesis.
- Repeated Alpha Scout runs publish discovery signals to the local agent bus; agents should be aware this can mutate local data state.
- `docs/AI_HANDOFF.md` is append-only; do not rewrite old entries except to correct formatting at user request.
- Handoff packs include diffs, so the script redacts obvious secret patterns and excludes lockfile diffs where possible.

## Open Questions

- Should Kalshi and Polymarket be integrated into Alpha Scout proper, or remain advisor-layer context?
- Should source checks report exact per-source candidate counts from Alpha Scout?
- Should Alpha Scout install optional `lxml` by default for S&P 500 parsing?
- Should the cockpit cache the latest Alpha Scout result to avoid repeated long fetches?
- Should live OpenRouter keys be managed via local `.env` only, never process command lines?
