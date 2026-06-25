# AlphaDesk — End-to-End Data & Control Flow Audit

**Scope:** the `morning_full` daily-brief pipeline (`run_daily.py` → `src/advisor/run_orchestrator.py` → `src/advisor/main._run_pipeline`).
**Method:** static reading of every stage module + a standalone dynamic trace harness (`scratch/flow_trace.py`, all tagged `# FLOW-AUDIT`) that drives the **real** production functions for each suspected handoff with no network/LLM/paid calls. Eight handoffs were proven by execution; the captured trace is saved at `scratch/flow_trace_output.txt`.
**Status:** investigation only — no production code, config, or behavior was modified.

To reproduce the dynamic evidence:

```bash
python scratch/flow_trace.py          # prints # FLOW-AUDIT lines + per-probe verdict
```

All eight probes return **CONFIRMED** (the suspected bug reproduces).

---

## 1. Intended vs. actual dataflow map

### Intended pipeline (per README / methodology / config)

```
ingestion (Street Ear/Reddit, News Desk/Finnhub+NewsAPI, Substack, YouTube, Sector Scanner)
        │  + market data (yfinance prices/hist/technicals, FMP fundamentals)
        │  + advisor data (FRED+yfinance macro, FMP earnings, 13F superinvestors, Kalshi/Polymarket)
        ▼
macro thesis evaluation ── prediction markets feed thesis status ──┐
        ▼                                                          │
holdings monitor (real position sizing) ── concentration/exposure ─┤
        ▼                                                          │
decision engine: screen (conviction hierarchy weights) →           │
   conviction list (25% CAGR gate from config) → moonshots → strategy/sizing
        ▼                                                          │
analyst committee (Growth/Value/Risk) + deep research + editor  ◄──┘
   ← receives ALL signals incl. earnings, superinvestor, youtube
        ▼
formatter / verbose report / Telegram + email
        ▼
memory write-back (conviction, theses, snapshots, outcomes) → read next run
```

### Where actual diverges (▲ = a finding below)

```
ingestion ────────────────────────────────────────────────────────────────────┐
  YouTube Ear ▲F8 ─────────────────────────────────► verbose HTML report ONLY  │ (never reaches editor)
  Substack / Reddit / News / Sector ───────────────► editor + verbose  ✔        │
        ▼                                                                       │
macro thesis eval (update_macro_theses)                                         │
  • prediction markets NOT an input ▲F7 (bolted on AFTER as decoration)         │
  • status NEVER changes — frozen at 'intact' ▲F2 (downstream branches dead)    │
        ▼                                                                       │
holdings monitor                                                                │
  • shares absent in advisor.yaml ⇒ shares=1 ⇒ position_pct = PRICE-weighted ▲F1│
  • portfolio.yaml (real share counts) NEVER loaded ▲F1                         │
        ▼                                                                       │
decision engine                                                                 │
  • conviction_weights config keys ≠ screener keys ⇒ ignored ▲F3               │
  • conviction CAGR gate hardcoded 25/15, ignores config ▲F4                    │
  • evidence_weighting + scoring_weights config sections DEAD ▲F5               │
  • schemas.Sizing never populated/rendered ▲F9                                 │
        ▼                                                                       │
analyst committee ◄─────────────────────────────────────────────────────────────┘
  • earnings_context + superinvestor_context passed in then DROPPED ▲F6
  • data_context has no superinvestor_data ⇒ deep researcher SI gather empty ▲F6
  • deep researcher earnings gather reads non-existent keys ▲F6
        ▼
memory write-back
  • seed_holdings / seed_macro_theses use INSERT OR IGNORE ⇒ edited config never
    propagates to an existing DB row ▲F10
any external/LLM/fetch failure ⇒ _run_blocking_step / broad except ⇒ empty default,
brief silently degraded, never flagged ▲F11
```

---

## 2. Findings

Severity rubric: **Critical** = corrupts/inverts recommendations · **High** = silently drops a signal that should drive decisions · **Medium** = config/logic not applied as intended · **Low** = inefficiency/cosmetic.
Confidence: **Confirmed-by-execution** (harness) · **Confirmed-static** (code path unambiguous) · **Suspected**.

| # | Severity | Finding | Intended | Observed | Evidence (file:func + trace) | Confidence |
|---|----------|---------|----------|----------|------------------------------|------------|
| **F1** | **Critical** | **Position sizing is price-weighted, not value-weighted; `portfolio.yaml` share counts never reach the pipeline.** | Holdings carry real share counts; `position_pct`, concentration alerts, thesis-exposure %, and trim mandate reflect actual portfolio weights. | `advisor.yaml` holdings have **no `shares`**; `holdings_monitor` does `shares = r.get("shares") or 1`, so every name is "1 share" → `position_pct ∝ price`. The real share counts live in `config/portfolio.yaml` (50/30/15/200/25) which the advisor **never loads** (it only merges a nonexistent `private/portfolio.yaml`). These weights drive `strategy_engine.should_trim` (`max_position_pct`), `_compute_thesis_exposure`, and the brief's "% of portfolio on thesis". | `holdings_monitor.py:87` (`shares … or 1`), `:96` (`position_pct`); `main.py:51` (`private/portfolio.yaml`); trace **Probe E**: `position_pct == price-proportional expectation` exactly; advisor vs portfolio holdings disjoint (`NVDA,META,AVGO,VRT,MRVL,NFLX` vs `RKLB,VTI`). | Confirmed-by-execution |
| **F2** | **High** | **Macro thesis status is frozen at `intact`; nothing ever sets `weakening`/`invalidated`.** | "Active macro theses … managed by the system"; status downgrades drive holdings downgrades, `macro_headwind` flags, weekend thesis-change report. | `update_macro_theses` only appends evidence and re-writes the *existing* status (`update_macro_thesis(title, thesis.get("status","intact"), …)`). No code anywhere assigns a weakening/invalidated macro status. Every consumer that branches on those states (`holdings_monitor._apply_dynamic_thesis_status` macro path, `strategy_engine` macro_headwind, `run_orchestrator._compute_thesis_changes`) is effectively dead. | `macro_analyst.py:169`; `memory.py:431` `update_macro_thesis`; grep: zero writers of `weakening/invalidated` for macro theses; trace **Probe F**: status stays `intact` after VIX 35 + hawkish/recession news. | Confirmed-by-execution |
| **F3** | **Medium** | **`conviction_weights` config is silently ignored (key-schema mismatch).** | The documented conviction hierarchy (guidance 0.30 > crowd 0.25 > smart money 0.20 > fundamentals 0.15 > analyst 0.10) weights screening. | `main.py` passes `config["conviction_weights"]` (keys `company_guidance/crowd_sentiment/smart_money/fundamentals/analyst_consensus`) into `screen_candidates`, which reads `technical/fundamental/sentiment/diversification`. **Zero key overlap** → every `weights.get(...)` falls to its in-code default 0.30/0.30/0.20/0.20. The conviction list itself (`conviction_manager.evidence_test`) is a flat 5-source pass/fail count — it never reads `conviction_weights` at all. | `main.py:790`; `screener.py:276-279`; trace **Probe A**: composite with config weights == composite with `{}` (defaults), but changes when keys align (`technical=1.0`). | Confirmed-by-execution |
| **F4** | **Medium** | **Conviction pipeline's CAGR/MoS gate is hardcoded, not config-driven.** | `strategy.min_cagr_pct` / `min_margin_of_safety_pct` drive the investment gate everywhere. | `conviction_manager.evidence_test` calls `passes_investment_gate(valuation)` with **no overrides** → hardcoded `min_cagr=25, min_mos=15`. `valuation_engine.compute_target_price` also hardcodes `passes_cagr_gate: implied_cagr >= 25.0`. Only `strategy_engine.should_add` threads the config values. Editing `min_cagr_pct` changes the *strategy* gate but **not** the conviction gate. | `conviction_manager.py:162`; `valuation_engine.py:148,164-167`; `strategy_engine.py:163-180`; trace **Probe B**: `passes_investment_gate(val)`=True while `(…,min_cagr=40)`=False; conviction call site has no `min_cagr`. | Confirmed-by-execution |
| **F5** | **Medium** | **`evidence_weighting` (21 keys) and `scoring_weights` (6 keys) config sections are dead.** | These tune evidence weights and the composite score. | Neither key is read anywhere in `src/`. The values are hardcoded in `schemas.BASE_WEIGHTS` and `schemas.compute_composite_score`, and they **diverge** from config (e.g. `reddit_strong_positive` config 2.5 vs code 1.5; `fundamentals_moderate` 2.0 vs 3.0; `insider_selling_large` −4.0 vs −5.0). Editing the config changes nothing. | grep: 0 refs to `evidence_weighting`/`scoring_weights`; `schemas.py:517` `BASE_WEIGHTS`, `:65` `compute_composite_score`; trace **Probe C**. | Confirmed-by-execution |
| **F6** | **High** | **Earnings & superinvestor intelligence never reaches the committee editor.** | The editor synthesizes over earnings guidance/tone and 13F/insider activity. | `run_analyst_committee` accepts `earnings_context` and `superinvestor_context` but references each **exactly once** (the signature) and never forwards them to `AdvisorEditor.synthesize`. `main._data_context` omits `superinvestor_data`, so `deep_researcher._gather_superinvestor` always reads `{}`. `deep_researcher._gather_earnings` reads `ticker_earnings["summary"]`/`["surprise_pct"]`, but the earnings per-ticker dict exposes `guidance_sentiment`/`management_tone`/… (no `summary`). `GrowthAnalyst._build_holdings_context` is handed `earnings_data` but never reads it. Net: guidance/tone + smart-money reach conviction scoring, valuation, and the *verbose HTML report*, but **not** the narrative brief. | `analyst_committee.py:235-258` (params), `:442-464` (synthesize call), `:64-85` (growth ignores earnings), `:315-331` (`superinvestor_data` empty); `deep_researcher.py:288-289`; `main.py:1092-1102` (`_data_context`); trace **Probe G**. | Confirmed-by-execution |
| **F7** | **Medium** | **Prediction markets do not feed macro-thesis evaluation.** | "Prediction market shifts feed thesis evaluation." | `update_macro_theses(macro_data, news_signals)` has **no prediction parameter**. `prediction_shifts` are attached to the returned thesis dicts as `prediction_context` *after* evaluation (decoration only) and passed to `format_macro_section`. They **do** correctly reach `conviction_manager` and `moonshot_manager` evidence. So not "dead data," but they never influence thesis status. | `main.py:544-556`; `macro_analyst.py:129`; trace **Probe F** (signature has only `macro_data, news_signals`); `conviction_manager.py:444`, `moonshot_manager.py:88`. | Confirmed-by-execution |
| **F8** | **Medium** | **YouTube Ear output only reaches the verbose HTML report, not the daily brief.** | YouTube signals inform the brief like Reddit/Substack. | The committee call passes `news_context`, `reddit_context`, `substack_context` (and the dropped earnings/SI) — there is **no** `youtube_context`, and `run_analyst_committee` has no such param. YouTube bus signals are consumed only into `_youtube_sigs` for `VerboseFormatter`. | `main.py:1207-1228` (no youtube arg), `:1539-1547` (verbose only); `analyst_committee.py:235-258`. | Confirmed-static |
| **F9** | **Medium** | **`schemas.Sizing` is never populated or rendered in the advisor pipeline.** | Every BUY carries structured position sizing (recommended/max weight, entry strategy, portfolio impact) surfaced in the brief. | `Sizing`, `Recommendation`, `validate_recommendation`, `compute_composite_score` are used **only** in `alpha_scout/synthesizer.py` (the standalone Alpha Scout agent run via `morning_brief.py`), and even there `sizing=None`. The advisor pipeline builds raw `rec_dict`s (no sizing) and calls `record_recommendation`; no formatter renders sizing (`grep sizing` in formatters → only CSS `box-sizing`). | `schemas.py:260-283`; `main.py:898-921` (raw dict, no sizing); `alpha_scout/synthesizer.py:459` (`sizing=None`); grep. | Confirmed-static |
| **F10** | **Medium** | **Edited holdings/theses config never propagates after first seed (`INSERT OR IGNORE`).** | Config is the source of truth; editing a thesis description/affected_tickers or a holding's thesis/category takes effect next run. | `seed_macro_theses` and `seed_holdings` use `INSERT OR IGNORE` keyed on title/ticker. For an existing row, edits to description/affected_tickers/thesis/category are dropped. (Only `entry_price` is separately synced via `update_holding`, and `advisor.yaml` holdings carry none.) | `memory.py:325-328` (holdings), `:404-409` (theses); trace **Probe D**: after editing & re-seeding, desc stays `ORIGINAL`, tickers stay `[AAA]`. | Confirmed-by-execution |
| **F11** | **High** | **External/LLM/fetch failures are swallowed into empty defaults; the brief is silently degraded, never flagged.** | A failed source should be surfaced (flagged/retried), not silently treated as "no data." | `_run_blocking_step` catches all exceptions and returns the caller's `default` (`{}`/`[]`); `_run_agent` returns an inline error string with empty `signals`. The Step 3/4 `asyncio.gather`s do **not** use `return_exceptions`, but every leaf is wrapped in `_run_blocking_step`, so a dead FRED/yfinance/FMP/news call yields empty `macro_data`/`prices`/`news` and the pipeline proceeds; the final brief contains no "data unavailable" marker. | `main.py:82-93` (`_run_blocking_step`), `:70-79` (`_run_agent`); trace **Probe H**: injected `RuntimeError` → `macro_data == {}`, `news == []`, no raise. | Confirmed-by-execution |
| **F12** | **Low** | **Risk Officer prompt always shows "Total portfolio value: 0".** | Risk officer sees portfolio value. | It sums `report.get("market_value", 0)`, but `holdings_monitor` stores the value under `_market_value` and `pop()`s it; the final report has no `market_value`. | `analyst_committee.py:131`; `holdings_monitor.py:89-96`. | Confirmed-static |
| **F13** | **Low / informational** | **No multi-model `council` exists.** | The task asks whether `council.deliberate` is invoked from the daily run. | `council.py` / `council.deliberate` do not exist anywhere in the repo (grep across all `.py`). The "analyst committee" (Growth/Value/Risk + Editor) is the actual synthesis council and **is** invoked from the daily pipeline (`main.py:1207`). Treat the spec reference as stale. | grep `council` → none; `main.py:1167-1228`. | Confirmed-static |

### Notes on specific handoffs the brief explicitly asked about

- **Prediction bundle → `update_macro_theses`:** *Refuted as "used in thesis evaluation"* — it is never an input (F7); it is decoration + reaches conviction/moonshot.
- **`conviction_weights` schema into `screen_candidates`:** *Confirmed mismatch* (F3) — producer keys ≠ consumer keys; defaults always win.
- **Conviction gate vs configured `min_cagr_pct`:** *Confirmed hardcoded* (F4).
- **Which holdings drive the run:** *advisor.yaml* (F1). It and `portfolio.yaml` **disagree** and divergence is silent; `portfolio.yaml` only feeds the separate `portfolio_analyst` agent/Telegram `/portfolio`.
- **`deep_researcher._gather` swallowing:** uses `return_exceptions=True` (`deep_researcher.py:215, 76`); a failed sub-gather is logged at WARNING and its observations dropped, but successful articles/observations/citations **do** reach `_synthesize` → `blocks` → committee editor and the citation registry (F6 is about *which inputs are present*, not the plumbing).
- **`schemas.Sizing` populated/rendered:** *No* (F9).
- **`council.deliberate` from daily run:** *Does not exist* (F13); the committee does.

---

## 3. What is actually working correctly

- **News Desk** `top_articles` is the backbone and flows correctly: → `news_signals` → macro thesis matching, holdings `key_events`, deep-research article selection + body fetch, event detection, citation registry, and the formatter. (`main.py:481-491`, `holdings_monitor.py:416-428`, `deep_researcher.py:416-426`.)
- **Street Ear (Reddit)** mood/themes + per-ticker bus signals reach the editor (`reddit_context`), the macro scanner, the single-pass fallback synthesis, and the verbose report. (`main.py:322-323, 1124-1149`.)
- **Substack** signals reach the editor (`substack_context`) and verbose report. **Sector Scanner** signals are folded into `news_signals` (so they reach macro matching + idea generator) and the verbose report. (`main.py:507-521`.)
- **Prediction markets** correctly map macro categories → equity tickers (`KEYWORD_TICKER_MAP`) and feed conviction/moonshot evidence (`prediction_market_favorable/unfavorable`) and the macro formatter. (`prediction_market.py:95-103`, `conviction_manager.py:262-277`.)
- **Strategy engine is genuinely config-driven:** `max_position_pct`, `min_cagr_pct`/`min_margin_of_safety_pct`, `conviction_promotion_weeks`, `min_evidence_sources` all read and change behavior (`strategy_engine.py:92,162-165,229`). (Its *inputs* are distorted by F1, but the config wiring is correct.)
- **Conviction list memory round-trip** works: upsert/remove/get with active filtering, weeks increment, recommendation recording for outcome tracking. (`memory.py:460-476`, `conviction_manager.py`.)
- **Delta engine** builds today's snapshot, loads the prior snapshot, computes deltas, and persists run snapshots with `mirror_to_daily` dedup — a clean write→read round-trip across runs. (`main.py:606-685, 1615-1630`.)
- **Analyst committee** orchestration is sound: Growth/Value/Risk run in parallel with `return_exceptions` and missing analysts are flagged to the editor; deep-research blocks + citations are threaded into the editor prompt; budget context is set/reset per run. (`analyst_committee.py:298-480`, `run_orchestrator.py:36-47`.)
- **Moonshot enrichment** (macro-driven + LunarCrush trending) is wired into the discovery candidate set. (`main.py:925-932`, `moonshot_manager.py:650-673`.)

---

## 4. Prioritized handoffs most worth fixing

1. **F1 — load real share counts (or store weights) so `position_pct` is value-weighted.** Concentration alerts, thesis-exposure %, and every trim recommendation are currently computed on price magnitude. This is the one finding that can produce *wrong recommendations*, not just missing detail.
2. **F11 — surface fetch/LLM failures in the brief.** Today a dead FRED/FMP/news key produces a confident-looking brief built on `{}`; readers can't tell a "quiet day" from a data outage.
3. **F6 — forward `earnings_context`/`superinvestor_context` to the editor and add `superinvestor_data` to `data_context`; fix the earnings key names in `_gather_earnings`.** Two of the highest-signal sources currently bypass the narrative.
4. **F2 — actually mutate macro thesis status.** Until something writes `weakening`/`invalidated`, a large, well-built block of downstream logic (macro headwind flags, holdings downgrades, weekend thesis-change report) never fires.
5. **F3/F4/F5 — reconcile config schemas with consumers.** `conviction_weights`, the conviction CAGR gate, `evidence_weighting`, and `scoring_weights` all advertise tunability the code ignores; align keys or delete the config to avoid false confidence.
6. **F10 — make seeding upsert editable fields** (or document that thesis/holding text edits require a DB reset), so config truly remains the source of truth.
7. **F8 — pass `youtube_context` to the committee** (or accept that YouTube is verbose-report-only and document it).
8. **F9 / F12 / F13 — schema/cosmetic cleanup:** populate or remove `schemas.Sizing`, fix the Risk Officer `market_value` key, and drop the `council` reference from the spec.

---

## 5. Harness & instrumentation (removal)

All audit artifacts are confined to the throwaway branch `flow-audit` and are trivially greppable:

```bash
grep -rn "FLOW-AUDIT" .          # tag on every line of instrumentation
rm -rf scratch/                  # removes flow_trace.py + flow_trace_output.txt
```

No production file was modified; the harness imports and calls real functions only. External, network, and LLM calls were never exercised (the probed functions are pure or DB-only; the one fault-injection probe raises locally).
