# AlphaDesk DeerFlow v2 Improvements — Codex Task

## Repository
https://github.com/vikram-santhosh/alpha-desk (branch: `main`)

## Context
AlphaDesk is a Python multi-agent investment advisor that runs 3x daily on GCP Cloud Run. It uses a committee of LLM agents (growth analyst, value analyst, risk officer, deep researcher, causal reasoner, CIO editor) to produce a daily investment brief. The architecture already adopts some patterns from ByteDance's DeerFlow multi-agent framework. This task implements 10 improvements inspired by DeerFlow v2.

## Task Overview
Implement these 10 changes in priority order. Each has a specific code location and a clear spec. Do NOT refactor unrelated code. Preserve all existing tests. Run `python -m pytest tests/` after all changes.

---

## P0 — Critical Bugs (fix first)

### 1. Wire deep research blocks into CIO editor

**Problem:** `MultiStepDeepResearcher` produces per-ticker research blocks at ~$1.50/ticker, but the result is NEVER passed to the `AdvisorEditor.synthesize()` call. The CIO editor writes the brief without seeing the deep research. The blocks only appear in the verbose HTML report.

**Files to change:**

**`src/advisor/analyst_committee.py`:**
- Line 155-178: `AdvisorEditor.synthesize()` — add parameter `deep_research_context: str = ""`
- Lines 387-408: The `editor.synthesize(...)` call — add `deep_research_context=deep_research_prompt_section` where `deep_research_prompt_section` is built from `deep_research_result["blocks"]`
- Build the prompt section by iterating `deep_research_result["blocks"]` — for each ticker/block, extract `block.get("content", "")`, cap each block at 1500 chars, join with `\n\n---\n\n`, wrap in a header like `"## Deep Research\n{blocks_text}"`
- Use `ContextBudget` from `src/shared/context_manager.py` to cap the total deep research context at 4000 tokens (priority 85, between holdings and analyst_reports)

**`prompts/agents/cio_editor.md`:**
- Add a `${deep_research_blocks}` template variable in the context section, between the analyst reports and the supplementary research
- Add a brief instruction: `"Deep Research contains multi-step investigative analysis per ticker. Incorporate specific findings and cited evidence into your synthesis. Prefer deep research conclusions over single-pass analyst opinions when they conflict."`

**`src/advisor/analyst_committee.py` — `AdvisorEditor.synthesize()` implementation (around line 180-220):**
- The method builds a prompt via `load_prompt("cio_editor", ...)` — add `deep_research_blocks=deep_research_context` to the `load_prompt()` kwargs

### 2. Enforce `run_steps` matrix in the orchestrator

**Problem:** `RunProfile.run_steps` (defined in `src/advisor/run_profile.py` lines 26-55) declares which pipeline steps each run type should execute, but `_run_pipeline()` in `src/advisor/main.py` never checks it. The step matrix is dead code.

**Files to change:**

**`src/advisor/main.py` — `_run_pipeline()` (starts line 129):**
- At each major step boundary, add a guard: `if "step_name" not in run_profile.run_steps: skip`
- The step names are defined in `RUN_STEP_MATRIX` in `run_profile.py`:
  - `"load_memory"`, `"street_ear"`, `"news_desk"`, `"substack_ear"`, `"youtube_ear"`
  - `"market_data_full"`, `"market_data_prices"` (evening uses prices-only)
  - `"advisor_data"`, `"holdings_monitor"`, `"delta_engine"`, `"decision_engine"`
  - `"full_analyst_committee"`, `"delta_analyst"`, `"thesis_review"`
  - `"report_generation_all"`, `"report_generation_telegram"`
- Map each existing pipeline step to its step name. When a step is skipped, set its output to a sensible default (empty dict, empty list, etc.)
- Log when a step is skipped: `log.info("Skipping step %s (not in run_steps for %s)", step_name, run_profile.run_type)`
- This makes the evening_wrap and weekend run types work through `_run_pipeline()` too, not just via the orchestrator's separate methods

---

## P1 — High Value

### 3. Add Flash reviewer before email delivery

**Problem:** The CIO brief ships with zero quality review. The `SkepticAgent` exists but is only used for conviction additions (main.py line 754).

**Files to change:**

**`src/advisor/analyst_committee.py` (or create `src/advisor/brief_reviewer.py`):**
- Create `review_brief(brief_text: str, holdings_context: str, news_context: str) -> dict`
- Uses Flash model (claude-haiku-4-5 / gemini-2.5-flash), max 800 tokens
- Prompt: "Review this investment brief for: (1) claims not supported by the provided evidence, (2) internal contradictions, (3) stale or missing data for tickers mentioned, (4) risk of misleading the reader. Return JSON: {issues: [{type, severity, description, suggestion}], overall_quality: 1-10, should_flag: bool}"
- Wrap with `@track_agent("brief_reviewer")`

**`src/advisor/main.py` — after committee synthesis (around line 1010-1020):**
- Call `review_brief()` with the synthesized brief text
- If `should_flag` is true OR `overall_quality < 6`, prepend a yellow banner to the brief: `"[REVIEWER NOTE: {issue_summary}]"`
- Log the review result regardless
- This is NOT a gate — the brief always ships, but flagged issues are visible

### 4. Scope analyst contexts

**Problem:** All three analysts (growth, value, risk) receive the same full context dump. The growth analyst doesn't need Reddit sentiment. The risk officer doesn't need Substack theses.

**Files to change:**

**`src/advisor/analyst_committee.py`:**
- In `run_analyst_committee()` around lines 250-280, where analyst prompts are built:
  - `GrowthAnalyst.build_prompt()` — pass: holdings, fundamentals, earnings, news (filtered to growth-relevant: revenue, product launches, TAM), catalyst data. REMOVE: reddit_context, substack_context
  - `ValueAnalyst.build_prompt()` — pass: holdings, fundamentals, valuation metrics, superinvestor data, prediction market data. REMOVE: reddit_context, substack_context, news beyond valuation-relevant
  - `RiskOfficer.build_prompt()` — pass: holdings (positions, concentration), mandate breaches, macro data, VIX/treasury, geopolitical news. REMOVE: substack_context, earnings detail
- Each analyst class (`GrowthAnalyst`, `ValueAnalyst`, `RiskOfficer`) has a `build_prompt(tickers, data_context)` method. Modify the `data_context` dict passed to each one to contain only relevant slices
- Measure token reduction in logs: `log.info("Growth analyst context: %d tokens (full would be %d)", scoped_tokens, full_tokens)`

---

## P2 — Important

### 5. LLM-powered research planner

**Problem:** `ResearchPlanner.plan()` in `src/advisor/research_planner.py` is entirely rule-based. Research questions are templates. The `data_needs` field is computed but never consumed by `deep_researcher.py`'s `_gather()` method.

**Files to change:**

**`src/advisor/research_planner.py`:**
- Add new method `async plan_with_llm()` that:
  1. Runs the existing rule-based `plan()` first to get candidate tickers + priority scores
  2. Makes a single Flash model call with the candidate list + today's signals summary
  3. Prompt: "Given these tickers and today's signals, generate research questions and data needs. For each ticker, specify: research_question (specific, not generic), task_type, data_needs (from: full_article_text, earnings_context, sec_filing, competitor_comparison, cross_validation, superinvestor_check). Prioritize uncertainty and information gaps over price magnitude."
  4. Parses the LLM output and overrides the template-based research_question and data_needs in the existing `ResearchTask` objects
  5. Falls back to the rule-based plan if the LLM call fails
- Wrap with `@track_agent("research_planner")`

**`src/advisor/deep_researcher.py` — `_gather()` method (lines 101-134):**
- Read `task.data_needs` and conditionally gather:
  - `"full_article_text"`: current behavior (fetch article bodies) — keep as-is
  - `"earnings_context"`: pull from `data_context.get("earnings_data", {})` for the ticker
  - `"competitor_comparison"`: use GapResolver's `_resolve_missing_competitor_data()` or yfinance to fetch peer data
  - `"superinvestor_check"`: pull from `data_context.get("superinvestor_data", {})` for the ticker
  - `"sec_filing"`: log as unresolved (no SEC API yet), add to observations as a noted gap
- Each data_need maps to a gather sub-step; run them in parallel with `asyncio.gather`

### 6. Feed recommendation outcomes into planner weights

**Problem:** `recommendation_outcomes` table in `src/advisor/memory.py` tracks 1d/1w/1m/3m returns and alpha, but this data never feeds back into planning.

**Files to change:**

**`src/advisor/memory.py`:**
- Add function `get_planner_calibration(lookback_days=90) -> dict` that queries `recommendation_outcomes`:
  - For each `trigger_type` (price_move, news_event, thesis_change, earnings), calculate: hit_rate (thesis_played_out percentage), average alpha, average confidence_modifier
  - Return dict like `{"price_move": {"hit_rate": 0.45, "avg_alpha": -1.2}, "news_event": {"hit_rate": 0.72, "avg_alpha": 3.1}, ...}`

**`src/advisor/research_planner.py`:**
- Accept optional `calibration: dict` parameter in `plan()` and `plan_with_llm()`
- Adjust priority scores: if `price_move` trigger historically has low hit rate, reduce the `move >= 4` uncertainty bonus from +2 to +1. If `news_event` has high hit rate, boost info_density weight for article-rich tickers
- This is a soft adjustment (multiply priority by a calibration factor 0.7-1.3), not a hard override

---

## P3 — Medium Priority

### 7. Per-ticker memory retrieval from all 13 tables

**Problem:** `build_memory_context()` in `src/advisor/memory.py` only reads 6 of 13 tables. Earnings calls, superinvestor positions, cross-mentions, prediction markets, and recommendation outcomes are invisible to synthesis.

**Files to change:**

**`src/advisor/memory.py`:**
- Add function `get_ticker_deep_context(ticker: str, lookback_days: int = 90) -> dict` that queries:
  - `earnings_calls`: last 2 earnings for the ticker (actual vs estimate, guidance, key quotes, management tone)
  - `superinvestor_positions`: latest quarter entries for the ticker
  - `cross_mentions`: any cross-mentions involving this ticker
  - `prediction_markets`: latest entries for this ticker
  - `recommendation_outcomes`: last 5 recommendations for this ticker with actual returns
  - `thesis_actions`: recent actions for this ticker
- Return a structured dict with these sections
- Cap total output at 2000 chars per ticker to avoid context explosion

**`src/advisor/deep_researcher.py` — `_gather()` method:**
- Call `get_ticker_deep_context(task.ticker)` and add relevant sections to `observations`
- Only include non-empty sections

### 8. Artifact-based deep research

**Problem:** The `observations` list in `deep_researcher.py` is in-memory only. If the pipeline crashes on ticker #4 of 6, tickers 1-3's research is lost. No crash resilience, no cross-referencing.

**Files to change:**

**`src/advisor/deep_researcher.py`:**
- At the start of `run()`, create a run workspace: `reports/{date}/research/{run_id}/`
- After each step in `_research_one()`, write the accumulated state to `{workspace}/{ticker}.json`:
  ```json
  {
    "ticker": "NVDA",
    "step": "analyze",
    "observations": [...],
    "analysis": {...},
    "gaps": [...],
    "synthesis": "..."
  }
  ```
- At the start of `_research_one()`, check if a partial artifact exists — if so, resume from the last completed step
- Final synthesis writes the complete artifact
- The `run()` method returns the artifacts path in addition to the blocks dict

### 9. Skills as markdown prompts

**Problem:** Research workflows are hardcoded. The deep researcher always runs the same 4 steps regardless of `task_type`.

**Files to change:**

**Create `prompts/skills/` directory with:**
- `thesis_refresh.md`: Instructions for refreshing an investment thesis — emphasize comparing current evidence vs original thesis, check for invalidation conditions
- `earnings_deep_dive.md`: Instructions for analyzing earnings — compare actual vs estimate, parse guidance, identify management tone shifts, check whisper numbers
- `variant_perception.md`: Instructions for finding variant perceptions — look for where market consensus differs from the evidence, identify non-obvious angles
- `catalyst_stress_test.md`: Instructions for stress-testing upcoming catalysts — model bull/bear/base outcomes, assign probabilities

**`src/shared/prompt_loader.py`:**
- Add `load_skill(skill_name: str, **variables) -> str` that loads from `prompts/skills/{skill_name}.md`
- Same template substitution as `load_prompt()`

**`src/advisor/deep_researcher.py` — `_synthesize()` method:**
- Map `task.task_type` to a skill: `"thesis_validation" -> "thesis_refresh"`, `"event_analysis" -> "earnings_deep_dive"`, `"news_deep_dive" -> "variant_perception"`
- Load the skill and append it to the synthesis prompt as additional instructions
- Fall back to the existing `deep_researcher.md` prompt if no skill matches

### 10. Dynamic model routing based on budget pressure

**Problem:** Model selection is hardcoded per-agent (`PRO_MODEL = "claude-opus-4-6"`, `FLASH_MODEL = "claude-haiku-4-5"`). No budget-aware degradation.

**Files to change:**

**`src/shared/cost_tracker.py`:**
- Add function `get_budget_pressure() -> float` that returns 0.0-1.0:
  - 0.0 = no pressure (spent < 50% of run budget)
  - 0.5 = moderate (50-80%)
  - 1.0 = critical (> 80%)
  - Uses the per-run budget from contextvar, falls back to daily cap

**`src/shared/agent_decorator.py`:**
- Add function `select_model(preferred: str, allow_downgrade: bool = True) -> str` that:
  - If `allow_downgrade=False` or budget_pressure < 0.5: return `preferred`
  - If budget_pressure >= 0.5 and preferred is Pro: return Flash
  - If budget_pressure >= 0.8: return Flash regardless
  - Log downgrades: `log.info("Model downgraded %s -> %s (budget pressure %.1f)", preferred, actual, pressure)`

**`src/advisor/analyst_committee.py`:**
- Replace hardcoded `PRO_MODEL` in analyst factory calls with `select_model(PRO_MODEL)`
- The CIO editor and deep research synthesis should use `select_model(PRO_MODEL, allow_downgrade=False)` — these are too important to downgrade

**`src/advisor/deep_researcher.py`:**
- Replace `PRO_MODEL` in `_analyze()` with `select_model(PRO_MODEL)` (analysis can be downgraded)
- Keep `PRO_MODEL` in `_synthesize()` (synthesis quality matters)

---

## Testing

After all changes:
1. `python -m pytest tests/` — all existing tests pass
2. `python -m pytest tests/test_run_foundation.py` — run profile tests pass
3. `python -m pytest tests/test_multirun_orchestrator.py` — orchestrator tests pass
4. Add new tests in `tests/test_deerflow_improvements.py`:
   - Test that `review_brief()` returns valid JSON with expected keys
   - Test that `get_budget_pressure()` returns 0.0-1.0 range
   - Test that `select_model()` downgrades when pressure is high
   - Test that `get_ticker_deep_context()` returns structured dict
   - Test that `get_planner_calibration()` returns per-trigger-type stats
   - Test that the CIO editor template now includes `${deep_research_blocks}`

## Important Constraints
- Do NOT change the `RunProfile` dataclass or `RUN_STEP_MATRIX` — they are correct as-is
- Do NOT modify the Dockerfile or deployment config
- Do NOT change model names or the `gemini_compat` shim
- Preserve the `@track_agent` decorator on all new async agent functions
- Use `load_prompt()` for any new prompt templates, following existing patterns
- Keep Flash model for all new lightweight calls (reviewer, planner LLM call)
- All new functions that make LLM calls must check budget via `check_budget()` before calling
