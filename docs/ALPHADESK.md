# AlphaDesk — Charter (single source of truth)

**Status:** authoritative. Supersedes conflicting vision/architecture/roadmap docs (see "Superseded" below).
**Decided:** 2026-06-24.

## What AlphaDesk is

A **personal, local-first research tool** that helps **one user (you)** think about **your own** investing. It ingests many independent sources, scores names by **multi-platform corroboration** on a deterministic **0–10 scale**, and shows the result in one dashboard. It is a **second opinion / signal aggregator**, not an allocator and not financial advice.

## What AlphaDesk is NOT (explicit non-goals)

- **Not** a multi-tenant SaaS product. No signups, tenants, billing, auth. (`plans/saas-multi-tenant-roadmap.md` is shelved.)
- **Not** an allocator or position-sizer. It ranks conviction; the how-much-to-buy decision is yours.
- **Not** personalized financial advice.
- **Not** a brokerage integration. Read-only, no trades.

## The one path (everything routes through this)

```
existing ingestion agents  ──►  score engine sensors  ──►  0–10 breadth-gated score  ──►  one dashboard + Telegram
(reddit, news, 13F, earnings,    (one adapter each)        (deterministic, provenance)
 prediction, youtube, substack)
```

- **One scorer:** `src/score_engine/`. The legacy `advisor` conviction scoring and `alpha_scout` composite screener are being retired into this.
- **One backend:** `server.py` (FastAPI) in this repo.
- **One frontend data seam:** `dashboard/src/lib/api.ts` → `server.py` (real data, mock only as labeled fallback).
- **One entry point (target):** the daily run routes through the score engine.

## The consolidation rule

**Every change either integrates into the one path or deletes a competing one. Nothing new runs in parallel.** A PR that adds a third way to do something is rejected in favor of extending the one way.

## Consolidation roadmap

- [x] **Step 0 — Charter** (this doc): retire competing visions.
- [ ] **Step 1 — M2:** wire existing agents (news, 13F, prediction, youtube, substack, valuation) into the score engine as sensor adapters. Collapses 3 scorers → 1.
- [ ] **Step 2 — Real-data dashboard:** point each view at `server.py`; delete mock fallbacks view-by-view.
- [ ] **Step 3 — One entry point:** daily run goes through the score engine; delete legacy conviction/composite scoring once unused.

## Superseded documents

These are kept for history but are **no longer authoritative**:

- `plans/saas-multi-tenant-roadmap.md` — SaaS pivot. **Shelved** (non-goal).
- `prompts/alphadesk-architecture.md` — v0.1 "local-first, no cloud" + later cloud/Gemini commits. **Partially stale**; this charter governs.
- `docs/end_to_end_plan.md`, `docs/score_engine_plan.md` — still valid as *implementation detail* for the score engine, subordinate to this charter.
