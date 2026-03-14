# AlphaDesk SaaS — Multi-Tenant Product Roadmap

## Vision

Transform AlphaDesk from a single-user CLI/Telegram investment intelligence tool into a multi-tenant SaaS platform where users can sign up, upload portfolios, receive personalized daily reports, track recommendation outcomes, and visualize portfolio performance — all through a web interface.

---

## Current State (as of March 2026)

- 7-agent pipeline: Street Ear, News Desk, Substack Ear, YouTube Ear, Alpha Scout, Portfolio Analyst, Advisor
- SQLite databases (6 DBs, WAL mode): agent_bus, advisor_memory, street_ear_tracker, substack_tracker, youtube_tracker, narrative_tracker, cost_tracker
- Single-tenant: one TELEGRAM_CHAT_ID, one portfolio.yaml, global DB paths, no user isolation
- Delivery: Telegram only
- Execution: Cloud Run Job (run_daily.py) or manual
- 195 tests across 5 files (unit + integration + E2E + signal quality)
- LLM: Gemini 2.5-Pro + Claude Opus 4.6, daily budget ~$20

---

## Architecture Target

```
┌──────────────────────────────────────────────────────────┐
│                  FRONTEND (Next.js)                       │
│  Auth │ Dashboard │ Portfolio │ Reports │ Visualizations  │
└────────────────────┬─────────────────────────────────────┘
                     │  REST + WebSocket (job progress)
┌────────────────────▼─────────────────────────────────────┐
│                   API LAYER (FastAPI)                      │
│  JWT Auth │ Tenant Context │ Rate Limiting │ Billing      │
└─────┬──────────┬──────────────┬──────────────────────────┘
      │          │              │
┌─────▼────┐ ┌──▼───────┐ ┌───▼──────────────┐
│ Postgres │ │ Redis +   │ │ Object Storage   │
│ (data)   │ │ Celery    │ │ (S3/GCS: PDFs,   │
│          │ │ (jobs)    │ │  uploads, assets) │
└──────────┘ └─────┬─────┘ └──────────────────┘
                   │
      ┌────────────▼──────────────────┐
      │       AGENT WORKERS           │
      │                               │
      │  GLOBAL (run once/cycle):     │
      │    Street Ear, News Desk,     │
      │    Substack Ear, YouTube Ear  │
      │                               │
      │  PER-USER (fan-out):          │
      │    Alpha Scout, Portfolio     │
      │    Analyst, Advisor Synthesis  │
      └───────────────────────────────┘
```

---

## The Critical Cost Insight: Global vs. Per-User Split

This is the single most important architectural decision. Market data is the same for all users — Reddit posts, news, Substack articles, YouTube videos don't change based on who's reading them. Only portfolio-specific analysis needs to run per-user.

| Layer | Runs | Cost | What It Produces |
|-------|------|------|-----------------|
| **Global Ear Agents** | Once per cycle | ~$2-3 | Shared signal pool (mentions, theses, news, narratives) |
| **Per-User Synthesis** | Once per user per cycle | ~$0.50-1.00 | Personalized brief from shared signals + user's portfolio |

**Additional cost levers:**
- Ticker-level caching: if 50 users hold AAPL, analyze AAPL once, share the result
- Model tiering: Haiku for formatting, Gemini Flash for filtering, Opus only for final synthesis
- Frequency tiers: free users get weekly, paid get daily
- Pre-compute popular ticker bundles (top 100 held tickers)

**Projected cost at scale:**

| Users | Global Run | Per-User Runs | Daily LLM Cost | Monthly LLM Cost |
|-------|-----------|---------------|-----------------|------------------|
| 10 | $2-3 | 10 x $0.75 | ~$10 | ~$300 |
| 100 | $2-3 | 100 x $0.75 | ~$78 | ~$2,400 |
| 1,000 | $2-3 | 1,000 x $0.75 | ~$753 | ~$23,000 |
| 10,000 | $2-3 | 10,000 x $0.50* | ~$5,003 | ~$150,000 |

*At scale, ticker caching + model tiering should reduce per-user cost to ~$0.50.

---

## Phase 1: API Layer + Database Migration

**Goal**: Stand up the backend that the web app will talk to. No UI yet — validate with API calls and existing Telegram delivery alongside.

### 1.1 Postgres Migration

**Move from 6 SQLite databases → 1 Postgres instance with proper schemas.**

New core tables (all existing tables + `user_id`):

```sql
-- Auth & tenancy
users (id, email, password_hash, name, plan_tier, created_at, last_login)
user_portfolios (id, user_id, name, uploaded_at, is_active, source_file_url)

-- Existing tables, now with user_id where needed
holdings (id, user_id, portfolio_id, ticker, shares, entry_price, thesis, category, tracking_since)

-- Shared signal tables (NO user_id — these are global)
market_signals (id, timestamp, signal_type, source_agent, payload_json, cycle_id)
narrative_propagation (id, narrative, first_seen_source, current_stage, affected_tickers, confidence)
signal_outcomes (id, signal_id, price_at_signal, price_after_1d/5d/20d, outcome)
source_reliability (id, source_name, platform, hit_rate, avg_lead_time_hours)

-- Per-user tables (WITH user_id)
user_signals (id, user_id, signal_id, relevance_score, acted_on)
conviction_list (id, user_id, ticker, conviction, thesis, pros_json, cons_json, status)
moonshot_list (id, user_id, ticker, conviction, thesis, upside_case, downside_case)
macro_theses (id, user_id, title, description, status, affected_tickers, evidence_log_json)
recommendation_outcomes (id, user_id, ticker, action, conviction, entry_price, returns tracking)
daily_briefs / reports (id, user_id, report_type, generated_at, status, content_json, content_html, pdf_url, cycle_id)

-- Cost tracking (per-user)
api_costs (id, user_id, timestamp, agent, input_tokens, output_tokens, cost_usd, run_id)
```

**Row-Level Security (RLS)** as a second line of defense:
```sql
ALTER TABLE holdings ENABLE ROW LEVEL SECURITY;
CREATE POLICY user_holdings ON holdings USING (user_id = current_setting('app.current_user_id')::uuid);
```

**Migration approach:**
- Write a migration script that reads each SQLite DB and inserts into Postgres
- Run existing 195 tests against Postgres (swap connection string in test config)
- Keep SQLite as fallback for local dev / single-user mode

### 1.2 FastAPI Backend

```
src/api/
  main.py              -- FastAPI app, CORS, middleware
  auth/
    router.py          -- /signup, /login, /me, /refresh-token
    dependencies.py    -- get_current_user() dependency
    models.py          -- User pydantic models
  portfolio/
    router.py          -- CRUD: upload CSV, add/remove holdings, list portfolios
    parser.py          -- CSV/Excel parser for portfolio uploads
  reports/
    router.py          -- GET /reports, GET /reports/:id, POST /reports/generate
    renderer.py        -- JSON → HTML, JSON → PDF
  signals/
    router.py          -- GET /signals (shared market signals, filterable)
  advisor/
    router.py          -- GET /conviction-list, GET /moonshots, GET /macro-theses
  jobs/
    router.py          -- GET /jobs/:id/status (poll job progress)
    websocket.py       -- WS endpoint for real-time progress
  db/
    session.py         -- async SQLAlchemy / asyncpg session
    models.py          -- ORM models
    migrations/        -- Alembic migrations
```

**Key endpoints:**

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | /auth/signup | Create account |
| POST | /auth/login | JWT token pair |
| GET | /me | Current user profile + plan tier |
| POST | /portfolio/upload | Upload CSV → parse → create holdings |
| GET | /portfolio | Current holdings |
| PUT | /portfolio/holdings/:id | Update a holding |
| POST | /reports/generate | Trigger an on-demand report (returns job_id) |
| GET | /reports | List past reports (paginated) |
| GET | /reports/:id | Full report with structured JSON |
| GET | /reports/:id/pdf | Download PDF version |
| WS | /jobs/:id/ws | Real-time progress (agent-by-agent status) |
| GET | /signals | Shared market signals (filterable by type, ticker, date) |
| GET | /advisor/conviction-list | User's conviction list |
| GET | /advisor/recommendations | Recommendations + outcomes tracking |
| GET | /dashboard/summary | Aggregated dashboard data |

### 1.3 Authentication

**Use Clerk or Auth0** — don't build auth from scratch.

- Social login (Google, GitHub) + email/password
- JWT access tokens (15 min) + refresh tokens (7 days)
- Plan tier stored in user metadata → used for rate limiting & feature gating
- FastAPI dependency `get_current_user()` extracts `user_id` from JWT, sets Postgres `app.current_user_id` for RLS

### 1.4 Deliverables

- [ ] Postgres schema + Alembic migrations for all tables
- [ ] SQLite → Postgres migration script
- [ ] FastAPI app with auth, portfolio CRUD, report listing
- [ ] Existing test suite passing against Postgres
- [ ] Docker Compose: Postgres + Redis + API server
- [ ] API documentation (auto-generated via FastAPI /docs)

---

## Phase 2: Job System + Global/Per-User Agent Split

**Goal**: Refactor agent execution into a scalable job system that separates shared market intelligence from per-user analysis.

### 2.1 Celery + Redis Job Queue

```
src/workers/
  celery_app.py           -- Celery config, broker=Redis
  tasks/
    global_cycle.py       -- Runs all 4 ear agents, stores shared signals
    user_brief.py         -- Per-user: reads shared signals + portfolio → report
    adhoc_report.py       -- User-triggered on-demand report
    pdf_generation.py     -- Async PDF rendering from report JSON
```

**Job lifecycle:**

```
SCHEDULED (Celery Beat):
  06:00 → global_cycle_task()
            ├── street_ear_task()      ─┐
            ├── news_desk_task()        │  parallel
            ├── substack_ear_task()     │
            └── youtube_ear_task()     ─┘
            │
            ▼ on completion (chord callback)
  06:15 → fan_out_user_briefs()
            ├── user_brief_task(user_id=1)  ─┐
            ├── user_brief_task(user_id=2)   │  parallel (concurrency-limited)
            ├── user_brief_task(user_id=3)   │
            └── ...                         ─┘

ON-DEMAND (user clicks "Generate Report"):
  → adhoc_report_task(user_id, report_type)
    reads latest shared signals + user portfolio
    → generates personalized brief
    → stores report
    → notifies via WebSocket
```

### 2.2 Refactor Existing Agents

Minimal changes to existing agent code — wrap, don't rewrite:

```python
# Current: agent returns (formatted_html, signals_list)
# New: agent writes signals to Postgres, returns structured data

def run_street_ear(cycle_id: str, db_session) -> dict:
    """Same logic, but writes to shared market_signals table."""
    # existing fetch + analyze + track logic
    # CHANGE: write to Postgres market_signals instead of SQLite agent_bus
    # CHANGE: return structured dict instead of Telegram HTML
    return {"signals": [...], "summary": "...", "tickers_mentioned": [...]}

def run_user_brief(user_id: str, cycle_id: str, db_session) -> dict:
    """Reads shared signals + user portfolio → personalized report."""
    shared_signals = get_cycle_signals(cycle_id, db_session)
    user_holdings = get_user_holdings(user_id, db_session)

    # Run Alpha Scout (personalized to user's watchlist)
    # Run Portfolio Analyst (user's holdings vs. signals)
    # Run Advisor synthesis (Opus: shared signals + user context → report)

    report = generate_report(shared_signals, user_holdings, ...)
    store_report(user_id, report, db_session)
    return report
```

### 2.3 Ticker-Level Caching

```sql
ticker_analysis_cache (
  id, cycle_id, ticker, analysis_json, model_used, created_at
)
```

Before analyzing a ticker for a user, check if it was already analyzed this cycle. Shared across users — if user A and user B both hold NVDA, the NVDA analysis runs once.

### 2.4 Progress Tracking via WebSocket

```python
# Worker emits progress to Redis pub/sub
redis.publish(f"job:{job_id}:progress", json.dumps({
    "stage": "portfolio_analyst",
    "pct": 60,
    "message": "Analyzing your holdings against market signals..."
}))

# API WebSocket endpoint relays to client
@app.websocket("/jobs/{job_id}/ws")
async def job_progress(websocket, job_id):
    async for msg in redis.subscribe(f"job:{job_id}:progress"):
        await websocket.send_json(msg)
```

### 2.5 Deliverables

- [ ] Celery app with Redis broker
- [ ] Global cycle task (4 ear agents → shared signals table)
- [ ] Per-user brief task (3 agents → personalized report)
- [ ] Celery Beat schedule for daily runs
- [ ] Ticker-level analysis cache
- [ ] WebSocket progress endpoint
- [ ] Concurrency controls (max N parallel LLM calls)
- [ ] Docker Compose updated: + Redis + Celery workers + Beat scheduler

---

## Phase 3: Web Frontend

**Goal**: Build the user-facing web application.

**Tech stack**: Next.js 14 (App Router) + Tailwind + Tremor (dashboard components) + Recharts

### 3.1 Pages & Components

```
app/
  (auth)/
    login/page.tsx          -- Clerk/Auth0 login
    signup/page.tsx         -- Registration with plan selection
  (dashboard)/
    page.tsx                -- Main dashboard (summary cards, latest signals, report preview)
    portfolio/
      page.tsx              -- Portfolio manager (holdings table, allocation chart)
      upload/page.tsx       -- CSV upload wizard
    reports/
      page.tsx              -- Report history (timeline, search, filter by type)
      [id]/page.tsx         -- Full report viewer (interactive, expandable sections)
    recommendations/
      page.tsx              -- Recommendation tracker (what we said → what happened)
    signals/
      page.tsx              -- Market signal explorer (shared intelligence feed)
    settings/
      page.tsx              -- Preferences, notification settings, plan management
```

### 3.2 Dashboard Page

The main landing page after login. Shows at-a-glance:

```
┌──────────────────────────────────────────────────────────┐
│  ALPHADESK DASHBOARD                        [Generate ▶] │
├──────────┬──────────┬───────────┬────────────────────────┤
│ Portfolio│ Today's  │ Active    │ Recommendation         │
│ Value    │ Signals  │ Theses    │ Hit Rate               │
│ $XXX,XXX │ 12 new   │ 3 macro   │ 68% (30d)             │
├──────────┴──────────┴───────────┴────────────────────────┤
│                                                          │
│  LATEST REPORT (March 13, 2026)          [View Full →]   │
│  ┌─ Key Takeaways ─────────────────────────────────┐     │
│  │ • NVDA: Unusual Reddit volume + Substack thesis  │     │
│  │ • Macro: Rate cut expectations shifted...        │     │
│  │ • Portfolio: Consider trimming XYZ concentration │     │
│  └──────────────────────────────────────────────────┘     │
│                                                          │
│  SIGNAL HEATMAP                    PORTFOLIO ALLOCATION   │
│  ┌─────────────────────┐          ┌──────────────────┐   │
│  │ NVDA ████████ 8     │          │   ╭──────╮       │   │
│  │ AAPL ████── 4       │          │  ╱ Tech   ╲      │   │
│  │ TSLA ███─── 3       │          │ │  45%     │     │   │
│  │ PLTR ██──── 2       │          │  ╲ Health ╱      │   │
│  └─────────────────────┘          │   ╰──────╯       │   │
│                                    └──────────────────┘   │
├──────────────────────────────────────────────────────────┤
│  NARRATIVE TRACKER                                        │
│  Substack ──●──── YouTube ──●──── Reddit                 │
│  "AI capex thesis"  amplified 3/11  mainstream 3/13      │
└──────────────────────────────────────────────────────────┘
```

### 3.3 Report Viewer

Reports are stored as structured JSON. The viewer renders them interactively:

- **Expandable sections**: Market Overview → Portfolio Impact → Conviction Changes → Action Items
- **Clickable tickers**: Click any $TICKER → side panel with signal history, price chart, recommendation trail
- **Diff view**: Compare today's report with yesterday's (what changed in convictions, new signals)
- **Export**: Download as PDF, share via link (read-only)

### 3.4 Recommendation Tracker (Key Differentiator)

This page uses the existing `recommendation_outcomes` and `signal_outcomes` data:

```
┌──────────────────────────────────────────────────────────┐
│  RECOMMENDATION TRACKER                                   │
├──────────┬─────────┬────────┬────────┬────────┬──────────┤
│ Date     │ Ticker  │ Action │ Entry  │ Now    │ Return   │
├──────────┼─────────┼────────┼────────┼────────┼──────────┤
│ 2/15     │ NVDA    │ BUY    │ $820   │ $905   │ +10.4%  ✅│
│ 2/20     │ PLTR    │ WATCH  │ $78    │ $82    │ +5.1%   ✅│
│ 3/01     │ XYZ     │ TRIM   │ $45    │ $42    │ avoided ✅│
│ 3/05     │ ABC     │ BUY    │ $120   │ $115   │ -4.2%   ⏳│
├──────────┴─────────┴────────┴────────┴────────┴──────────┤
│                                                          │
│  SIGNAL SOURCE RELIABILITY         CUMULATIVE ALPHA      │
│  ┌────────────────────────┐       ┌───────────────────┐  │
│  │ Substack theses: 72%   │       │     ╱─── AlphaDesk│  │
│  │ Reddit signals:  61%   │       │   ╱               │  │
│  │ YouTube amplif:  58%   │       │ ╱    ── S&P 500   │  │
│  │ News catalysts:  55%   │       │╱                   │  │
│  └────────────────────────┘       └───────────────────┘  │
└──────────────────────────────────────────────────────────┘
```

### 3.5 Visualization Library

Built from data already in the system:

| Visualization | Data Source | Component |
|---------------|------------|-----------|
| Portfolio allocation donut | `holdings` | Recharts PieChart |
| Signal heatmap by ticker | `market_signals` | Tremor HeatMap |
| Narrative propagation timeline | `narrative_propagation` | Custom timeline (Substack→YouTube→Reddit flow) |
| Recommendation hit rate over time | `recommendation_outcomes` | Recharts LineChart |
| Conviction list changes | `conviction_list` + snapshots | Tremor DeltaBar |
| Sector exposure vs. signals | `holdings` + `market_signals` | Stacked bar chart |
| Source reliability radar | `source_reliability` | Recharts RadarChart |
| Daily P&L with signal overlay | `holding_snapshots` + `market_signals` | Recharts ComposedChart |

### 3.6 Deliverables

- [ ] Next.js app with Clerk/Auth0 authentication
- [ ] Dashboard page with summary cards + charts
- [ ] Portfolio upload (CSV parser) + holdings management
- [ ] Report list + interactive report viewer
- [ ] Recommendation tracker page
- [ ] Market signals explorer
- [ ] WebSocket integration for job progress
- [ ] Responsive design (desktop-first, tablet-friendly)
- [ ] Settings page (notification preferences, plan management)

---

## Phase 4: Delivery, Polish & Scale

**Goal**: Multi-channel delivery, billing, and production hardening.

### 4.1 Multi-Channel Report Delivery

| Channel | Implementation | Trigger |
|---------|---------------|---------|
| **Web** (default) | Report stored in DB, rendered on /reports/:id | Always (report viewer) |
| **Email** | SendGrid/Resend: render `content_html` → email template | User preference: daily/weekly digest |
| **Telegram** (legacy) | Keep existing bot, now reads from Postgres reports table | User links Telegram in settings |
| **Push notification** | Web push via service worker | "Your report is ready" when job completes |
| **PDF download** | Puppeteer/WeasyPrint renders `content_html` → PDF, stores in S3 | On-demand from report viewer |

### 4.2 Billing Integration (Stripe)

```
Plan tiers:
  FREE:    Weekly report, 1 portfolio, 30-day history, no PDF export
  PRO:     Daily reports, 3 portfolios, full history, PDF, email delivery     — $29/mo
  PREMIUM: Daily + on-demand, unlimited portfolios, API access, priority queue — $79/mo
```

Implementation:
- Stripe Checkout for subscription
- Webhook handler for subscription status changes
- FastAPI middleware checks `plan_tier` for feature gating
- Celery task priority: PREMIUM > PRO > FREE in queue ordering

### 4.3 Production Infrastructure

```
┌─────────────────────────────────────────────┐
│              PRODUCTION STACK                 │
├─────────────────────────────────────────────┤
│ Frontend:  Vercel (Next.js)                  │
│ API:       Cloud Run (FastAPI, auto-scaling) │
│ Workers:   Cloud Run Jobs (Celery workers)   │
│ Database:  Cloud SQL (Postgres 15)           │
│ Cache:     Memorystore (Redis)               │
│ Storage:   Cloud Storage (PDFs, uploads)     │
│ Scheduler: Cloud Scheduler → Pub/Sub → Beat  │
│ Monitoring: Cloud Logging + custom dashboard │
│ Secrets:   Secret Manager                    │
└─────────────────────────────────────────────┘
```

### 4.4 Observability & Monitoring

- **Per-user job tracking**: run_id, timing per agent, error rates
- **LLM cost dashboard**: daily spend by agent, by user tier, by model
- **Signal quality feedback loop**: `signal_outcomes` → source reliability auto-update
- **Alerting**: daily cost > threshold, job failure rate > 5%, synthesis latency > 5 min

### 4.5 Security Hardening

- [ ] Postgres RLS policies on all user-scoped tables
- [ ] API rate limiting (per user, per tier)
- [ ] Input sanitization on portfolio uploads (prevent CSV injection)
- [ ] Secrets in GCP Secret Manager (no .env in production)
- [ ] Audit log for sensitive operations (portfolio changes, report access)
- [ ] GDPR: user data export + deletion endpoints

### 4.6 Deliverables

- [ ] Email delivery pipeline (SendGrid/Resend)
- [ ] PDF generation service
- [ ] Push notifications (service worker)
- [ ] Stripe billing integration
- [ ] Plan-based feature gating middleware
- [ ] Production deployment (Vercel + Cloud Run + Cloud SQL)
- [ ] Monitoring dashboard
- [ ] Rate limiting + security hardening
- [ ] GDPR compliance endpoints

---

## Phase 5: Advanced Features (Post-Launch)

### 5.1 Interactive Advisor Chat

Extend the existing `chat_session.py` to the web:
- Chat interface in the report viewer: "Why did you recommend trimming XYZ?"
- Advisor has full context: user's portfolio + latest report + memory
- Conversation stored in `chat_sessions` table (already exists)
- Streaming responses via SSE

### 5.2 Custom Alert Rules

Users define their own signal triggers:
- "Alert me if any Substack author mentions $TICKER"
- "Notify me when a narrative reaches 'mainstream' stage"
- "Flag any conviction change in my holdings"

Stored as rules in DB, evaluated against each signal cycle.

### 5.3 Social / Community Features

- Anonymous portfolio performance leaderboard
- "What signals are other users watching?" (aggregated, anonymized)
- Shared conviction lists (opt-in)

### 5.4 API Access (Premium Tier)

- REST API for programmatic access to signals, reports, recommendations
- Webhook delivery for real-time signal notifications
- Enables integration with user's own trading tools / spreadsheets

### 5.5 Mobile App

- React Native wrapper around the web views
- Push notifications for daily brief + urgent signals
- Portfolio widget for home screen

---

## Risk Register

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| LLM costs exceed revenue per user | High | Critical | Global/per-user split, ticker caching, model tiering, plan pricing covers cost |
| SQLite → Postgres migration breaks data | Medium | High | Migration script + validation, 195 existing tests, run both in parallel during transition |
| Report quality degrades at scale (rushed synthesis) | Medium | High | Keep signal_outcomes feedback loop, A/B test synthesis prompts, quality monitoring |
| Long report generation time frustrates users | High | Medium | WebSocket progress, async jobs, pre-compute popular tickers, priority queues |
| Multi-tenant data leak (user sees another's data) | Low | Critical | Postgres RLS, user_id in every query, security audit, integration tests for isolation |
| API rate limits from Reddit/YouTube/News sources | Medium | Medium | Caching, respect rate limits, fallback sources, shared global fetching reduces call volume |
| Stripe billing edge cases (failed payments, downgrades) | Medium | Low | Stripe webhooks for status sync, grace period on failed payments, feature degradation not hard cutoff |

---

## Timeline Estimate

| Phase | Scope | Suggested Duration |
|-------|-------|----------|
| Phase 1 | API + Postgres + Auth | 4-6 weeks |
| Phase 2 | Job system + agent refactor | 3-4 weeks |
| Phase 3 | Web frontend | 4-6 weeks |
| Phase 4 | Delivery + billing + production | 3-4 weeks |
| Phase 5 | Advanced features | Ongoing post-launch |

**MVP (Phases 1-3)**: ~11-16 weeks to a working multi-tenant web app with reports and visualizations.

---

## Open Questions

1. **Pricing validation**: Is $29/$79/mo viable? Need to validate willingness to pay before building billing.
2. **Data sources**: Do Reddit/YouTube/News API ToS allow reselling derived insights to end users?
3. **Real-time vs. batch**: Should reports only be daily, or should signals stream to dashboard in real-time?
4. **Mobile-first?**: Is the primary audience mobile (checking morning brief on phone) or desktop?
5. **White-label potential**: Should the architecture support white-labeling for financial advisors who want to offer this to their clients?
6. **Regulatory**: Does providing investment recommendations to paying users trigger SEC/FINRA registration requirements?
