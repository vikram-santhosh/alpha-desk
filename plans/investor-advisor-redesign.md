# AlphaDesk Redesign — Personal Investment Advisor

## Philosophy Shift

**Current system**: Scans everything, dumps data, presents options daily.
**New system**: Same data engine underneath — Street Ear still scans Reddit, News Desk still fetches news, Portfolio Analyst still runs technicals/fundamentals. But a new **Advisor layer** sits on top that consumes all their output with persistent memory, macro thesis tracking, and a structured 5-section brief. The existing agents are the eyes and ears. The Advisor is the brain.

**What stays exactly as-is**: Street Ear, News Desk, Portfolio Analyst, Alpha Scout (candidate sourcing logic), Agent Bus, Cost Tracker, all config files, all SQLite databases.
**What's new**: An `src/advisor/` package that orchestrates the existing agents, adds memory + macro + superinvestor tracking, and formats the output as a structured daily brief instead of a data dump.

Core principles:
- You're an investor, not a trader. Hold period: 1+ year.
- Low churn. "No action needed" is the best answer most days.
- Macro thesis drives stock-level decisions (top-down → bottom-up).
- Recommendations persist across days — don't churn names.
- Prefer undervalued stocks. Open to momentum when evidence is strong.
- **25% CAGR minimum** — don't recommend portfolio changes unless the thesis supports it.
- **Margin of safety matters** — valuation must justify entry, not just narrative.
- **Crowd > analysts** — weight actual investor behavior (Reddit, prediction markets, insider buys) over Wall Street price targets.
- **Earnings calls are primary source** — actual company guidance and cross-company mentions, not analyst summaries.
- Track what smart money is doing (hedge funds, superinvestors, prediction markets).

---

## Daily Brief Structure

The daily output is ONE message with 5 sections, designed to be read in 5 minutes:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
☀️ ALPHADESK DAILY BRIEF — Feb 21, 2026
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

§1  MACRO & MARKET CONTEXT
§2  YOUR PORTFOLIO — Holdings Check-in
§3  PORTFOLIO STRATEGY — Add / Trim / Hold
§4  CONVICTION LIST — 3-5 Interesting Names
§5  MOONSHOT IDEAS — 1-2 High-Conviction Asymmetric Bets

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

### Section 1: MACRO & MARKET CONTEXT

Not generic market news. Specifically the 4-5 macro forces that affect YOUR holdings, tracked day-over-day.

```
🌍 MACRO & MARKET CONTEXT

Active Theses (tracked since [date]):

  1. Hyperscaler CapEx Boom → Chip Revenue [STRENGTHENING]
     MSFT, GOOG, META, AMZN all guided CapEx higher in Q4.
     Combined 2026 CapEx guidance: $240B (+35% YoY).
     → Beneficiaries in your portfolio: NVDA, AVGO, VRT, MRVL
     → Today: NVDA +2.1% on report that MSFT accelerating H200 orders.

  2. SaaS Rotation / Multiple Compression [INTACT]
     Enterprise software names de-rated avg 15% from Dec highs.
     CrowdStrike, Snowflake, Datadog all below 200 SMA.
     → Your exposure: MSFT (minor risk — diversified beyond SaaS).
     → No new developments today.

  3. Fed Rate Path → Easing Cycle [EVOLVING]
     Fed held rates at 4.25%. Dot plot suggests 2 cuts in 2026.
     10Y yield: 4.31% (-3bp). Dollar weakening.
     → Tailwind for growth/tech holdings. Positive for your portfolio.

  4. "Big Beautiful Bill" / Fiscal Stimulus [MONITORING]
     House passed framework. Senate markup begins next week.
     Key items: tax cuts, infrastructure, defense spending.
     → Potential beneficiaries: industrials, defense. Not in your portfolio currently.

  Market: S&P +0.4% | Nasdaq +0.7% | VIX 14.2 (low/complacent)
```

**How this works technically:**
- Macro theses are stored in `data/advisor_memory.db` with a status field
- Each run, News Desk + a new FRED data fetch provides fresh data
- Opus 4.6 updates thesis status: `strengthening`, `intact`, `evolving`, `weakening`, `invalidated`
- Theses persist until explicitly removed — not recreated daily
- User can add theses via Telegram: `/thesis add "Hyperscaler CapEx Boom"`

---

### Section 2: YOUR PORTFOLIO — Holdings Check-in

Not just prices. Context, memory, and what changed since yesterday.

```
📊 YOUR PORTFOLIO

  NVDA    $142.30  +2.1% today  |  +34.2% since tracking (Oct 15)
          Thesis: AI CapEx beneficiary. INTACT ✅
          Today: MSFT accelerating H200 orders (Bloomberg).
          Earnings May 28 — 96 days out. Consensus: $0.89 EPS.
          Memory: Up 5 of last 7 sessions. Momentum strong.

  AMZN    $218.50  +0.8% today  |  +22.1% since tracking
          Thesis: AWS re-acceleration + retail margin expansion. INTACT ✅
          No material news today.
          Note: Approaching 52-week high ($224). Watch for breakout.

  AVGO    $198.40  -1.2% today  |  +8.5% since tracking (Jan 10)
          Thesis: AI ASIC + VMware integration. INTACT ✅
          Today: Minor pullback, no news catalyst. Normal vol.
          Memory: 3rd red day in 5. Still above 50 SMA ($191).

  VRT     $118.20  +3.4% today  |  NEW POSITION (tracking since Feb 18)
          Thesis: Data center power/cooling picks-and-shovels play. EARLY ✅
          Today: Upgraded by Goldman, PT $140. Volume 2.3x avg.
          Memory: Day 3 of tracking. Need more data before sizing up.

  MRVL    $91.50   +1.8% today  |  NEW POSITION (tracking since Feb 18)
          Thesis: Custom silicon / AI networking. EARLY ✅
          Today: No news. Trading in range.
          Earnings Mar 6 — 13 days. Key catalyst.

  GOOG    $188.30  +0.3% today  |  +15.7% since tracking
          Thesis: Cloud margin inflection + Search moat. INTACT ✅
          Gemini 2.0 launch reception positive. Cloud growing 28%.

  META    $612.40  +1.1% today  |  +28.3% since tracking
          Thesis: Reels monetization + AI ad targeting. INTACT ✅
          Approaching ATH. Valuation getting stretched (P/E 28).
          Memory: Flagged "watch valuation" last week. Still valid.

  NFLX    $945.20  +0.5% today  |  +18.9% since tracking
          Thesis: Ad tier growth + pricing power. INTACT ✅
          Steady. No news. Holding well above all moving averages.

  MSFT    $445.10  -0.2% today  |  +6.1% since tracking
          Thesis: Azure growth + Copilot monetization. INTACT ⚠️
          Caution: SaaS rotation thesis may create near-term headwind.
          Azure growth strong but stock lagging peers. Monitor.

  Portfolio total: +18.4% weighted avg since tracking
  vs S&P 500: +7.2% over same period → Alpha: +11.2%
```

**How this works technically:**
- `advisor_memory.db` stores each holding with: start tracking date, entry price, thesis text, thesis status
- Each run: fetch current prices, compute changes, check for news/earnings/signals
- Opus 4.6 writes the per-holding narrative using: price data + news + signals + memory of past days
- "Memory" lines reference stored observations from previous runs
- Thesis status updated by Opus based on fundamental/news evidence, not daily price moves

---

### Section 3: PORTFOLIO STRATEGY — Add / Trim / Hold

This section is often empty. That's by design. Only speaks up when evidence warrants action.

```
⚖️ PORTFOLIO STRATEGY

  Overall: NO CHANGES RECOMMENDED TODAY

  Monitoring:
  • META — valuation stretching (P/E 28 vs 5yr avg 22). Not a sell signal
    yet but if P/E > 32 or growth decelerates, consider trimming.
    Status: WATCH (flagged 3 days ago, no change)

  • MSFT — weakest performer in portfolio. SaaS rotation headwind.
    Azure fundamentals still strong. No action unless breaks below $420.
    Status: WATCH (flagged 5 days ago)

  Upcoming catalysts that could trigger action:
  • MRVL earnings Mar 6 — if beat + guide up, consider sizing up to full position
  • Fed meeting Mar 18 — if dovish surprise, add to rate-sensitive names
```

On days where action IS warranted:

```
⚖️ PORTFOLIO STRATEGY

  🟢 CONSIDER ADDING: AVGO
     Reason: Pulled back 8% from highs on no fundamental news.
     Now at $191, near 50 SMA support. AI ASIC thesis strengthening
     (3 new design wins reported this quarter).
     Suggestion: Add 2-3% of portfolio at current levels.
     Risk: Earnings in 45 days. Could gap either way.
     Conviction: MEDIUM — would upgrade to HIGH on earnings beat.

  🔴 CONSIDER TRIMMING: META (only if up >30% and P/E > 32)
     This is NOT urgent. Just a plan for IF we get there.
     Reason: Rebalancing, not thesis change. Lock in gains on richest name.
     Suggestion: Trim 20% of position if hits $650+ and redeploy to AVGO/VRT.
```

**How this works technically:**
- Opus 4.6 receives: all holdings data, macro theses, memory of past flags, price levels
- Explicit instruction in system prompt: "Default to NO CHANGES. Only recommend action when evidence is strong. This investor holds for 1+ year. Low churn."
- Previous flags stored in memory — if "watch META valuation" was flagged 3 days ago with no change, it says so rather than flagging it as new
- Price trigger levels stored in memory: "if MSFT breaks $420, revisit"

---

### Section 4: CONVICTION LIST — 3-5 Interesting Names

These are NOT the portfolio. These are names being researched. They persist across days and only rotate when evidence changes.

```
🔍 CONVICTION LIST (Week 3 — updated when evidence warrants)

  1. LLY  $705  — WEEK 4 ON LIST [CONVICTION: HIGH → UPGRADING]
     Thesis: GLP-1 dominance, 10yr patent runway, 42% ROIC.
     This week: Mounjaro international expansion approved in 3 new markets.
     Revenue CAGR 5yr: 18%. P/E 58 (rich, but growth justifies).
     Superinvestors: Berkshire added Q4. ARK bought. Viking Global top 5 holding.
     Pros: Strongest moat in pharma. Secular obesity tailwind. Pricing power.
     Cons: Valuation premium. GLP-1 competition from NVO. Political drug pricing risk.
     Status: 4 weeks of consistent evidence. Worth a starter position.
     → PROMOTED TO "CONSIDER ADDING" in §3 next week if holds above $680.

  2. CHTR  $385  — WEEK 2 ON LIST [CONVICTION: MEDIUM]
     Thesis: Deep value cable play. FCF yield 8.2%, P/E 11.3.
     Superinvestors: Buffett holds since 2014. Li Lu added Q4.
     Pros: Regional monopoly. Massive FCF. Trading at 5yr P/E low.
     Cons: Cord-cutting secular decline. Fiber overbuild risk. Debt heavy.
     Status: Need Q1 subscriber data (April) to validate. HOLDING ON LIST.

  3. UBER  $82  — WEEK 1 ON LIST [CONVICTION: MEDIUM]
     Thesis: Platform network effects, profitability inflection, autonomous optionality.
     Superinvestors: Altimeter top position. Dragoneer Capital added.
     Pros: Free cash flow positive. 18% revenue growth. Duopoly with Lyft.
     Cons: Autonomous disruption risk (Waymo). Regulatory overhang. Low margin business.
     Status: NEW — need 1-2 more weeks of analysis before conviction upgrade.

  Removed this week:
  • CRWD — removed after 2 weeks. SaaS rotation headwind + valuation
    (P/S 22x) too rich in current environment. May revisit if drops to $280.

  Holding in reserve (not enough conviction yet):
  • PANW — interesting but want to see if SaaS rotation creates a better entry.
```

**How this works technically:**
- Conviction List stored in `advisor_memory.db` table `conviction_list`:
  - ticker, date_added, weeks_on_list, conviction_level, thesis, pros, cons, status
- Each run: Opus reviews the EXISTING list first, updates status, then considers new additions
- System prompt explicitly says: "Do NOT replace the list daily. Only add a name if it's been on your watchlist for 2+ runs with strengthening evidence. Only remove with a stated reason."
- Superinvestor/hedge fund data: fetched from SEC 13F filings (quarterly) + whale tracking APIs
- History of removed names stored too — prevents re-adding a recently dropped name without reason

---

### Section 5: MOONSHOT IDEAS — 1-2 Asymmetric Bets

```
🚀 MOONSHOT IDEAS (high risk / high reward — small position size only)

  1. RKLB  $28.50  — MONTH 2 ON LIST [CONVICTION: MEDIUM]
     Thesis: Only pure-play orbital launch competitor to SpaceX.
     $1B backlog. Neutron rocket on track for 2026 maiden flight.
     If Neutron succeeds: 5-10x upside over 5 years.
     If Neutron fails/delays: 30-50% downside.
     This week: Won $45M NASA contract. Electron launch cadence accelerating.
     Superinvestors: Cathie Wood (ARK) top 10 holding.
     Size: Max 2-3% of portfolio. Asymmetric risk/reward.
     Status: Neutron timeline is the key variable. Next milestone: June test.

  No changes to moonshot list this week.
```

---

## Memory Architecture

### Database: `data/advisor_memory.db`

```sql
-- Core holdings with thesis tracking
CREATE TABLE holdings (
    id INTEGER PRIMARY KEY,
    ticker TEXT NOT NULL UNIQUE,
    tracking_since TEXT NOT NULL,          -- date we started tracking
    entry_price REAL,                      -- price when tracking started
    thesis TEXT NOT NULL,                  -- current investment thesis
    thesis_status TEXT DEFAULT 'intact',   -- intact, strengthening, weakening, invalidated
    category TEXT DEFAULT 'core',          -- core, new_position, trimming
    notes TEXT,                            -- running notes
    updated_at TEXT NOT NULL
);

-- Daily snapshot of each holding (builds the "memory" narrative)
CREATE TABLE holding_snapshots (
    id INTEGER PRIMARY KEY,
    ticker TEXT NOT NULL,
    date TEXT NOT NULL,
    price REAL NOT NULL,
    change_pct REAL,
    cumulative_return_pct REAL,            -- since tracking_since
    thesis_status TEXT,
    daily_narrative TEXT,                   -- Opus-generated 1-liner about this day
    key_event TEXT,                         -- major news/earnings/upgrade (null if quiet day)
    UNIQUE(ticker, date)
);

-- Macro theses with evolution tracking
CREATE TABLE macro_theses (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,                    -- "Hyperscaler CapEx Boom"
    description TEXT NOT NULL,
    status TEXT DEFAULT 'intact',           -- intact, strengthening, evolving, weakening, invalidated
    created_date TEXT NOT NULL,
    last_updated TEXT NOT NULL,
    affected_tickers TEXT,                  -- JSON: ["NVDA","AVGO","VRT","MRVL"]
    evidence_log TEXT                       -- JSON array of dated evidence points
);

-- Conviction list (persistent across runs)
CREATE TABLE conviction_list (
    id INTEGER PRIMARY KEY,
    ticker TEXT NOT NULL UNIQUE,
    date_added TEXT NOT NULL,
    weeks_on_list INTEGER DEFAULT 1,
    conviction TEXT DEFAULT 'medium',       -- low, medium, high
    thesis TEXT NOT NULL,
    pros TEXT,                              -- JSON array
    cons TEXT,                              -- JSON array
    superinvestor_activity TEXT,            -- JSON: who's buying/selling
    status TEXT DEFAULT 'active',           -- active, promoted, removed
    removal_reason TEXT,
    removal_date TEXT,
    updated_at TEXT NOT NULL
);

-- Moonshot ideas (persistent, low churn)
CREATE TABLE moonshot_list (
    id INTEGER PRIMARY KEY,
    ticker TEXT NOT NULL UNIQUE,
    date_added TEXT NOT NULL,
    months_on_list INTEGER DEFAULT 1,
    conviction TEXT DEFAULT 'medium',
    thesis TEXT NOT NULL,
    upside_case TEXT,
    downside_case TEXT,
    key_milestone TEXT,                     -- "Neutron maiden flight June 2026"
    max_position_pct REAL DEFAULT 3.0,
    status TEXT DEFAULT 'active',
    updated_at TEXT NOT NULL
);

-- Portfolio strategy flags (prevents re-flagging the same thing daily)
CREATE TABLE strategy_flags (
    id INTEGER PRIMARY KEY,
    ticker TEXT NOT NULL,
    flag_type TEXT NOT NULL,                -- 'watch_valuation', 'consider_trim', 'consider_add', 'price_trigger'
    flag_date TEXT NOT NULL,
    description TEXT NOT NULL,
    trigger_condition TEXT,                 -- "if P/E > 32" or "if breaks below $420"
    resolved INTEGER DEFAULT 0,
    resolved_date TEXT,
    resolved_action TEXT,                   -- what happened: 'trimmed', 'added', 'dismissed'
    UNIQUE(ticker, flag_type, resolved)
);

-- Superinvestor/hedge fund tracking (refreshed quarterly from 13F)
CREATE TABLE superinvestor_positions (
    id INTEGER PRIMARY KEY,
    investor_name TEXT NOT NULL,            -- "Berkshire Hathaway", "ARK Invest"
    ticker TEXT NOT NULL,
    quarter TEXT NOT NULL,                  -- "2025Q4"
    action TEXT,                            -- 'new_position', 'added', 'reduced', 'sold'
    shares INTEGER,
    value_usd REAL,
    pct_of_portfolio REAL,
    UNIQUE(investor_name, ticker, quarter)
);

-- Earnings call intelligence
CREATE TABLE earnings_calls (
    id INTEGER PRIMARY KEY,
    ticker TEXT NOT NULL,
    quarter TEXT NOT NULL,                  -- "2025Q4"
    call_date TEXT NOT NULL,
    revenue_actual REAL,
    revenue_estimate REAL,
    eps_actual REAL,
    eps_estimate REAL,
    guidance_revenue_low REAL,              -- forward guidance range
    guidance_revenue_high REAL,
    guidance_eps_low REAL,
    guidance_eps_high REAL,
    guidance_sentiment TEXT,                -- 'raised', 'maintained', 'lowered', 'withdrawn'
    key_quotes TEXT,                        -- JSON: most important management quotes
    capex_guidance REAL,                    -- important for infra/AI thesis
    mentioned_companies TEXT,               -- JSON: companies mentioned in the call
    management_tone TEXT,                   -- 'confident', 'cautious', 'defensive'
    transcript_summary TEXT,               -- Opus-generated summary of the call
    UNIQUE(ticker, quarter)
);

-- Cross-company mentions (when MSFT mentions NVDA in their call, that's a signal)
CREATE TABLE cross_mentions (
    id INTEGER PRIMARY KEY,
    source_ticker TEXT NOT NULL,            -- who said it (e.g. MSFT)
    mentioned_ticker TEXT NOT NULL,         -- who was mentioned (e.g. NVDA)
    quarter TEXT NOT NULL,
    context TEXT NOT NULL,                  -- the relevant quote/context
    sentiment TEXT,                         -- 'positive', 'neutral', 'negative'
    category TEXT,                          -- 'supplier', 'competitor', 'partner', 'customer'
    UNIQUE(source_ticker, mentioned_ticker, quarter)
);

-- Prediction market data (Polymarket, Kalshi)
CREATE TABLE prediction_markets (
    id INTEGER PRIMARY KEY,
    date TEXT NOT NULL,
    platform TEXT NOT NULL,                 -- 'polymarket', 'kalshi'
    market_title TEXT NOT NULL,             -- "Fed rate cut by June 2026"
    category TEXT,                          -- 'fed_policy', 'recession', 'election', 'regulation', 'earnings'
    probability REAL NOT NULL,              -- 0.0 to 1.0 (crowd's implied probability)
    prev_probability REAL,                 -- yesterday's value (for delta tracking)
    volume_usd REAL,                       -- market volume (conviction proxy)
    affected_tickers TEXT,                  -- JSON: tickers this market affects
    url TEXT,                               -- link to the market
    UNIQUE(date, platform, market_title)
);

-- Run history (so Opus knows what it said yesterday)
CREATE TABLE daily_briefs (
    id INTEGER PRIMARY KEY,
    date TEXT NOT NULL UNIQUE,
    macro_summary TEXT,                     -- condensed macro section
    portfolio_actions TEXT,                 -- JSON of any actions recommended
    conviction_changes TEXT,               -- JSON of adds/removes/upgrades
    moonshot_changes TEXT,
    full_brief_hash TEXT                    -- for dedup / change detection
);
```

### How Memory Flows Into Each Run

```
Run N:
  1. Load from advisor_memory.db:
     - All holdings with theses and last snapshot
     - Active macro theses with status
     - Current conviction list (with weeks_on_list)
     - Current moonshot list
     - Active strategy flags
     - Yesterday's brief summary
     - Superinvestor positions

  2. Fetch fresh data:
     - Current prices for all tickers (holdings + conviction + moonshots)
     - News via News Desk
     - Reddit via Street Ear
     - Macro data (FRED: rates, yields)
     - Earnings calendar

  3. Opus 4.6 synthesis with FULL context:
     - "Here is what you said yesterday: [...]"
     - "Here are the active theses and their status: [...]"
     - "Here is the conviction list (week N): [...]"
     - "Here are active strategy flags: [...]"
     - "Here is today's new data: [...]"
     - "Produce the 5-section daily brief. Remember: low churn,
        investor mindset, only recommend changes with strong evidence."

  4. Save to advisor_memory.db:
     - Today's snapshots for all holdings
     - Updated thesis statuses
     - Updated conviction list (weeks_on_list incremented)
     - Any new/removed strategy flags
     - Today's brief summary (for tomorrow's context)
```

---

## Superinvestor / Hedge Fund Tracking

### Data Sources

**SEC 13F Filings** (quarterly, free):
- API: `https://efts.sec.gov/LATEST/search-index?q=13F&dateRange=custom&startdt=2025-10-01`
- Track: Berkshire Hathaway, Bridgewater, Renaissance, Pershing Square, Appaloosa, Viking Global, Dragoneer, Altimeter, Tiger Global, Coatue, ARK Invest
- Parse: new positions, increases, decreases, exits

**Whale Wisdom / Dataroma** (free tier scraping):
- Superinvestor portfolio summaries
- Most bought/sold by top funds

**yfinance** (already available):
- `Ticker.institutional_holders` — top holders + shares
- `Ticker.insider_transactions` — insider buy/sell

### How It's Used

Not as a standalone section. Woven into the conviction list:
- "Superinvestors: Berkshire added Q4. ARK bought. Viking Global top 5 holding."
- Used as a conviction multiplier: if 3+ superinvestors hold, +1 conviction level
- Insider buying on a conviction list name → flag for promotion

### Refresh Cadence
- 13F data: quarterly (filings are 45 days after quarter end)
- Insider transactions: daily (via yfinance)
- Store in `superinvestor_positions` table, only update when new quarter data available

---

## Earnings Call Intelligence

The most underrated data source. When a CEO says "we're accelerating AI infrastructure spend," that's not an analyst opinion — that's the company telling you where the money is going.

### What We Extract

**From each earnings call transcript:**

```
1. GUIDANCE (the most important thing)
   - Revenue guidance: raised / maintained / lowered / withdrawn
   - EPS guidance: raised / maintained / lowered
   - CapEx guidance (critical for AI infra thesis)
   - Specific numbers: "We expect Q2 revenue of $38-40B"
   - Tone: confident / cautious / defensive

2. KEY MANAGEMENT QUOTES
   - Opus 4.6 extracts the 3-5 most forward-looking statements
   - Focus on: demand signals, pricing, new products, market share
   - "We're seeing unprecedented demand for H200" (NVDA CEO)
   - "We plan to invest $80B in AI infrastructure in 2026" (META CEO)

3. CROSS-COMPANY MENTIONS (gold mine for thesis validation)
   - When MSFT mentions "our NVIDIA partnership" → signal for NVDA
   - When AMZN says "Graviton is replacing x86" → headwind for INTC
   - When 3+ hyperscalers mention increased AI CapEx → thesis: STRENGTHENING
   - Tracked in cross_mentions table with sentiment + relationship type

4. BEAT/MISS + REACTION
   - Revenue: beat by X% / missed by X%
   - EPS: beat by X% / missed by X%
   - Stock reaction: how did it trade post-earnings?
   - "Beat and raise" = strongest signal. "Beat but guide down" = caution.
```

### Data Sources

**Earnings Transcripts** (multiple options):

```
Option A: Financial Modeling Prep API (free tier: 250 calls/day)
  - Full earnings transcripts
  - Endpoint: /api/v3/earning_call_transcript/{symbol}?quarter=Q4&year=2025
  - Also has: earnings surprises, guidance history

Option B: SEC EDGAR (free, no key)
  - 8-K filings contain earnings press releases
  - Not full transcripts but has guidance numbers

Option C: Seeking Alpha / Motley Fool RSS (free, scraping)
  - Earnings call summaries
  - Less structured but widely available

Recommended: Option A (FMP) for transcripts, yfinance for beat/miss data
```

**yfinance** (already available):
- `Ticker.earnings_dates` — upcoming and past earnings dates
- `Ticker.earnings_history` — actual vs estimate (EPS)
- `Ticker.revenue_forecasts` — analyst revenue estimates

### How It's Used in the Brief

**In §1 Macro (when earnings season is active):**
```
  Earnings signal: 4/5 hyperscalers have now guided CapEx higher.
  Combined 2026 CapEx: $240B (+35% YoY). MSFT: $80B, META: $65B,
  GOOG: $50B, AMZN: $45B.
  Cross-mentions: NVDA mentioned in all 4 calls. AVGO in 3. VRT in 2.
  → Thesis "Hyperscaler CapEx Boom": STRENGTHENING (was: INTACT)
```

**In §2 Holdings (per ticker):**
```
  NVDA    $142.30  +2.1%
          Last earnings (Q4): Beat revenue by 8%, EPS by 12%.
          Guidance: RAISED — Q1 revenue $44B vs $40B consensus.
          CEO quote: "Blackwell demand is incredible, supply-constrained into H2."
          Cross-mentions: Named in MSFT, META, GOOG, AMZN earnings calls.
```

**In §4 Conviction List:**
```
  VRT — Mentioned by MSFT ("our data center cooling partner Vertiv")
        and EQIX ("Vertiv infrastructure is critical to our expansion").
        Cross-mention count: 4 companies this quarter. Rising.
```

---

## Prediction Markets (Crowd Intelligence)

Wall Street analysts have conflicts of interest. Prediction market bettors have money on the line. When Polymarket says there's an 85% chance the Fed cuts in June and that was 60% last week, that's real crowd conviction shifting.

### Markets to Track

**Macro / Policy (affects entire portfolio):**
- Fed rate cuts: timing, number, magnitude
- Recession probability
- Inflation trajectory
- Government shutdown / debt ceiling
- Trade war / tariff escalation
- "Big Beautiful Bill" passage odds

**Sector / Company-specific (when available):**
- Tech regulation outcomes
- Antitrust (GOOG, META, AAPL)
- AI regulation sentiment
- Earnings beat/miss (some platforms offer these)

### Data Sources

**Polymarket** (free API):
```
GET https://clob.polymarket.com/markets
GET https://gamma-api.polymarket.com/events?closed=false&tag=politics,economics
```
- Returns: market title, current price (= probability), volume, outcomes
- Filter for markets with >$100K volume (high-signal markets)

**Kalshi** (free API with key):
```
GET https://trading-api.kalshi.com/trade-api/v2/markets
```
- Returns: market title, yes_price, volume, category
- Strong on: economic indicators, Fed policy, government action

### How It's Used

Not as a standalone section. Woven into §1 Macro:

```
🌍 MACRO & MARKET CONTEXT

  3. Fed Rate Path → Easing Cycle [EVOLVING]
     Fed held at 4.25%. Dot plot: 2 cuts in 2026.
     Polymarket: 85% chance of cut by June (was 60% last week, +25pp)
     Kalshi: 72% chance of 2+ cuts this year (was 65%, +7pp)
     Crowd is pricing in faster easing than the Fed projects.
     → Tailwind for growth/tech. Your portfolio benefits.
```

And into strategy flags:

```
  Prediction market shift: "US recession in 2026" went from 15% → 28%
  in 2 weeks on Polymarket ($4M volume). Not actionable yet but
  MONITORING. If >40%, consider defensive tilt.
```

### Delta Tracking (What Changed)

The absolute probability is less useful than the **change**. System tracks:
- Today's probability vs yesterday (daily delta)
- Today vs 7 days ago (weekly delta)
- Today vs 30 days ago (monthly delta)
- Volume (higher volume = more conviction behind the number)

Only surface prediction market data when there's a **meaningful shift** (>10pp weekly move or >$500K new volume). Don't noise up the brief with "Fed cut probability is 73% (was 72%)."

---

## The 25% CAGR Gate

This is the most important filter. It prevents the system from recommending portfolio changes for mediocre opportunities.

### How It Works

Before any "CONSIDER ADDING" recommendation in §3, the system must answer:

```
CAGR TEST:
  Current price: $X
  Intrinsic value (3yr target): $Y
  Implied 3yr CAGR: ((Y/X)^(1/3) - 1) × 100

  If CAGR < 25%: DO NOT RECOMMEND for portfolio addition.
  May still sit on conviction list as a "monitor."

  If CAGR ≥ 25% AND margin of safety ≥ 15%: eligible for portfolio.
```

### What Feeds the Target Price

Not analyst price targets. The system computes its own target using:

```
1. Revenue trajectory:
   - Current revenue × (1 + revenue_CAGR)^3
   - revenue_CAGR from: company guidance, historical trend, industry growth

2. Margin assumption:
   - Will margins expand, hold, or compress?
   - Use: guidance, margin trend, industry comps

3. Multiple assumption:
   - What P/E or EV/Revenue will the market pay in 3 years?
   - Use: historical average, sector average, growth-adjusted

4. Scenario weighting:
   - Bull case (25% weight): everything goes right
   - Base case (50% weight): guidance is roughly met
   - Bear case (25% weight): growth disappoints, margins compress

5. Target = weighted average of 3 scenarios
   Margin of Safety = (Target - Current) / Target
```

### In the Brief

Every conviction list entry shows the CAGR math:

```
  1. LLY  $705 — 3yr target: $1,180 (base case)
     Implied CAGR: 18.8% ❌ BELOW 25% THRESHOLD
     → Stays on conviction list but NOT eligible for portfolio add.
     Would need to drop to $580 for 25% CAGR. WAITING.

  2. AVGO  $191 — 3yr target: $380 (base case)
     Implied CAGR: 25.7% ✅ ABOVE THRESHOLD
     Margin of safety: 21% at current price.
     → ELIGIBLE for portfolio add if fundamentals confirm.
```

### The Conviction Hierarchy (Updated)

```
Signal source                              Weight in conviction
─────────────────────────────────────────────────────────────────
Company guidance (earnings calls)           30%  ← primary
Crowd sentiment (Reddit + prediction mkts)  25%  ← real money/attention
Superinvestor/hedge fund activity           20%  ← smart money
Fundamentals (ROIC, FCF, margins)           15%  ← quality check
Analyst consensus                           10%  ← least weight
```

Analysts are informational but not trusted for conviction. Real investors putting real money — whether on Reddit, prediction markets, or via insider buys — carry more weight.

---

## Evidence Backing a Thesis

Every conviction list name must have evidence from at least 3 of these 5 sources:

```
✅ Required: at least 3 of 5 must be present

1. COMPANY SAYS SO — guidance raised, management confident on call
2. CROWD AGREES — Reddit buzz positive, prediction markets favorable
3. SMART MONEY AGREES — superinvestors holding/adding, insiders buying
4. NUMBERS CONFIRM — revenue growing, margins expanding, ROIC >15%
5. VALUATION ALLOWS — 25% CAGR achievable, margin of safety exists

If only 1-2 sources agree: WATCHLIST (monitor, don't act)
If 3-4 sources agree: CONVICTION LIST (high confidence)
If all 5 agree: STRONG BUY candidate (rare — maybe 1-2 per quarter)
```

Shown in the brief:

```
  AVGO  $191 — CONVICTION: HIGH (4/5 evidence sources)
    ✅ Company: Raised guidance Q4, CEO "AI ASIC pipeline strongest ever"
    ✅ Crowd: Reddit sentiment +1.4, 5 subreddits discussing. Polymarket
       "AVGO beats Q1" at 78%.
    ✅ Smart money: Berkshire added. 3 superinvestors hold.
    ✅ Numbers: Rev growth 24%, ROIC 31%, gross margin 74% (expanding).
    ⚠️ Valuation: 25.7% CAGR — passes, but barely. Want more margin of safety.
       Would prefer entry at $180 for 29% CAGR.
```

---

## Technical Architecture (Updated)

### New Files

```
src/advisor/
├── __init__.py
├── main.py                      # Master orchestrator
├── macro_analyst.py             # Macro thesis tracking, FRED data, regime
├── holdings_monitor.py          # Daily holdings check-in with memory
├── strategy_engine.py           # Add/trim/hold logic with 25% CAGR gate
├── conviction_manager.py        # Persistent conviction list, evidence scoring
├── moonshot_manager.py          # Moonshot idea tracking
├── superinvestor_tracker.py     # 13F parsing, whale tracking
├── earnings_analyzer.py         # NEW: Earnings call transcripts, guidance, cross-mentions
├── prediction_market.py         # NEW: Polymarket + Kalshi crowd sentiment
├── valuation_engine.py          # NEW: 3yr target, CAGR calc, margin of safety
├── memory.py                    # All advisor_memory.db operations
└── formatter.py                 # 5-section brief formatter

config/advisor.yaml              # Holdings, theses, tracked superinvestors, prediction markets
data/advisor_memory.db           # Persistent memory (created at runtime)
```

### Config: `config/advisor.yaml`

```yaml
# Your actual holdings (replaces portfolio.yaml as source of truth)
holdings:
  - ticker: NVDA
    category: core
    thesis: "AI CapEx beneficiary — dominant GPU franchise"
  - ticker: AMZN
    category: core
    thesis: "AWS re-acceleration + retail margin expansion"
  - ticker: GOOG
    category: core
    thesis: "Cloud margin inflection + Search moat"
  - ticker: META
    category: core
    thesis: "Reels monetization + AI ad targeting"
  - ticker: AVGO
    category: new_position
    thesis: "AI ASIC design wins + VMware integration"
  - ticker: VRT
    category: new_position
    thesis: "Data center power/cooling picks-and-shovels"
  - ticker: MRVL
    category: new_position
    thesis: "Custom silicon / AI networking"
  - ticker: NFLX
    category: core
    thesis: "Ad tier growth + pricing power"
  - ticker: MSFT
    category: core
    thesis: "Azure growth + Copilot monetization"

# Active macro theses (seeded, then managed by the system)
macro_theses:
  - title: "Hyperscaler CapEx Boom"
    description: "MSFT, GOOG, META, AMZN guiding CapEx higher → chip revenue"
    affected_tickers: [NVDA, AVGO, VRT, MRVL]
  - title: "SaaS Rotation / Multiple Compression"
    description: "Enterprise software de-rating, rotation out of high-multiple names"
    affected_tickers: [MSFT]
  - title: "Fed Easing Cycle"
    description: "Rate cuts expected in 2026, dollar weakening, growth tailwind"
    affected_tickers: [NVDA, AMZN, GOOG, META, NFLX]
  - title: "Big Beautiful Bill / Fiscal Stimulus"
    description: "Tax cuts + infrastructure + defense spending"
    affected_tickers: []

# Superinvestors to track
superinvestors:
  - name: "Berkshire Hathaway"
    cik: "0001067983"
  - name: "Bridgewater Associates"
    cik: "0001350694"
  - name: "Pershing Square"
    cik: "0001336528"
  - name: "ARK Invest"
    cik: "0001697748"
  - name: "Appaloosa Management"
    cik: "0001656456"
  - name: "Viking Global"
    cik: "0001103804"
  - name: "Dragoneer Investment"
    cik: "0001571983"
  - name: "Coatue Management"
    cik: "0001535392"
  - name: "Tiger Global"
    cik: "0001167483"
  - name: "Altimeter Capital"
    cik: "0001806813"

# Strategy parameters
strategy:
  min_hold_period_days: 365          # Investor, not trader
  churn_bias: low                    # Default to "no action"
  max_position_pct: 15               # Never let one name exceed 15%
  trim_trigger_pct: 30               # Consider trim if up >30% AND valuation stretched
  conviction_promotion_weeks: 3      # Min weeks before conviction list → portfolio
  moonshot_max_pct: 3                # Max portfolio % per moonshot
  min_cagr_pct: 25                   # Don't recommend add unless 25% 3yr CAGR
  min_margin_of_safety_pct: 15       # Intrinsic value must be 15%+ above current price
  min_evidence_sources: 3            # Need 3/5 evidence sources for conviction

# Earnings intelligence
earnings:
  transcript_source: fmp             # 'fmp' (Financial Modeling Prep) or 'sec_edgar'
  lookback_quarters: 4               # How many past quarters to keep
  cross_mention_tracking: true       # Track when companies mention each other

# Prediction markets
prediction_markets:
  polymarket: true
  kalshi: true
  min_volume_usd: 100000             # Only track markets with >$100K volume
  alert_delta_pct: 10                # Alert on >10pp weekly probability shift
  tracked_categories:
    - fed_policy
    - recession
    - regulation
    - trade_war
    - fiscal_policy

# Conviction hierarchy weights (must sum to 1.0)
conviction_weights:
  company_guidance: 0.30             # Earnings calls, management quotes
  crowd_sentiment: 0.25              # Reddit + prediction markets
  smart_money: 0.20                  # Superinvestors, insiders
  fundamentals: 0.15                 # ROIC, FCF, margins
  analyst_consensus: 0.10            # Least weight — informational only
```

### Pipeline Flow

```
1. Load memory (advisor_memory.db)
   ├── Yesterday's brief summary
   ├── Holdings + theses + snapshots (last 7 days)
   ├── Macro theses + status
   ├── Conviction list (current)
   ├── Moonshot list (current)
   ├── Active strategy flags
   └── Superinvestor positions

2. Run existing agents (parallel — REUSED AS-IS)
   ├── Street Ear (reddit_fetcher → analyzer → tracker → agent bus signals)
   ├── News Desk (news_fetcher → analyzer → agent bus signals)
   └── These run their full pipelines and publish to agent bus

3. Fetch market data (REUSING existing portfolio_analyst modules)
   ├── price_fetcher.fetch_current_prices(all_tracked_tickers)
   ├── price_fetcher.fetch_all_historical(all_tracked_tickers)
   ├── fundamental_analyzer.fetch_all_fundamentals(all_tracked_tickers)
   ├── technical_analyzer.analyze_all(all_tracked_tickers, historical)
   └── risk_analyzer.analyze_concentration() + analyze_sector_exposure()
   Note: "all_tracked_tickers" = holdings + conviction list + moonshots

4. Fetch NEW data (advisor-specific)
   ├── FRED API → rates, yields, VIX (macro_analyst.py)
   ├── SEC 13F → superinvestor positions (superinvestor_tracker.py)
   ├── yfinance → insider transactions for conviction list names
   ├── Earnings transcripts → guidance, key quotes, cross-mentions (earnings_analyzer.py)
   ├── Polymarket + Kalshi → crowd probabilities for tracked macro events (prediction_market.py)
   └── Agent bus → consume signals from Street Ear + News Desk (mark_consumed=False)

5. Source conviction candidates (REUSING Alpha Scout modules)
   ├── candidate_sourcer.source_all_candidates() → raw candidates
   ├── screener.screen_candidates() → scored candidates
   ├── valuation_engine: compute 3yr target, CAGR, margin of safety per candidate
   ├── Apply 25% CAGR gate — filter out sub-threshold names
   ├── Apply evidence test — need 3/5 sources (guidance, crowd, smart money, numbers, valuation)
   └── conviction_manager merges with existing list (persistent, not replaced)

6. Opus 4.6 synthesis (single comprehensive call)
   Input: memory context + all agent data + market data + macro + superinvestor
          + earnings intelligence + prediction market shifts + CAGR math
   Output: 5-section daily brief as structured JSON

7. Save memory
   ├── Today's holding snapshots (price, thesis_status, daily_narrative)
   ├── Updated macro thesis statuses
   ├── Updated conviction list (weeks_on_list incremented, any adds/removes)
   ├── Updated moonshot list
   ├── New/resolved strategy flags
   └── Today's brief summary (for tomorrow's context)

8. Format → Telegram HTML → Send
```

### Opus 4.6 System Prompt (Core)

```
You are a senior portfolio manager advising an individual investor.

INVESTOR PROFILE:
- Holds positions for 1+ years. Low churn.
- Prefers undervalued stocks but open to momentum with strong evidence.
- Current portfolio is tech/AI-heavy by conviction, not accident.
- Wants to understand macro forces driving their holdings.

YOUR RULES:
1. DEFAULT TO "NO CHANGES." Only recommend add/trim with strong,
   multi-factor evidence. Price moves alone are not evidence.
2. MAINTAIN CONSISTENCY in your conviction list. Don't swap names daily.
   A stock stays on the list until evidence changes, not because a new
   shiny thing appeared. Minimum 2 weeks before promoting to portfolio.
3. REMEMBER YESTERDAY. You have the previous brief and holding snapshots.
   If you flagged something yesterday, reference it ("as flagged 3 days ago").
   Don't repeat the same alert as if it's new.
4. THESIS-FIRST. Every holding and conviction name has a thesis. Evaluate
   new information AGAINST the thesis. Price drops don't invalidate theses;
   fundamental deterioration does.
5. BE HONEST ABOUT UNCERTAINTY. "I don't have enough data yet" and
   "too early to tell" are valid answers.
6. MOONSHOTS are special. They can be speculative but need an asymmetric
   risk/reward argument. Max 2 at a time. Don't churn.
```

### Telegram Commands (Updated)

| Command | Description |
|---------|-------------|
| `/brief` | Full daily 5-section brief |
| `/holdings` | Just §2 — portfolio check-in |
| `/macro` | Just §1 — macro context |
| `/conviction` | Just §4 — conviction list with history |
| `/moonshot` | Just §5 — moonshot ideas |
| `/thesis NVDA` | Show full thesis + history for one ticker |
| `/action` | Just §3 — any pending add/trim/hold recommendations |
| `/flag META "watch valuation"` | Manually add a strategy flag |
| `/add VRT core "data center power play"` | Add a holding |
| `/remove INTC "thesis invalidated"` | Remove a holding |
| `/cost` | API cost report |
| `/help` | List commands |

---

## Architecture: Existing Agents Feed the New Advisor Layer

```
┌─────────────────────────────────────────────────────────────────────┐
│                        ADVISOR LAYER (NEW)                          │
│                        src/advisor/main.py                          │
│                                                                     │
│   ┌──────────┐  ┌──────────┐  ┌───────────┐  ┌──────────────────┐  │
│   │  Memory   │  │  Macro   │  │ Strategy  │  │  Conviction +    │  │
│   │  Layer    │  │  Analyst │  │  Engine   │  │  Moonshot Mgr    │  │
│   │ (DB)      │  │ (FRED)   │  │ (low churn│  │  (persistent)    │  │
│   └─────┬────┘  └────┬─────┘  │  bias)    │  └────────┬─────────┘  │
│         │            │        └─────┬─────┘           │             │
│         └────────────┴──────────────┴─────────────────┘             │
│                              │                                      │
│                     Opus 4.6 Synthesis                               │
│               (memory-aware 5-section brief)                        │
│                              │                                      │
│                     5-Section Telegram Output                        │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                    ╔══════════╧══════════╗
                    ║    AGENT BUS        ║  (existing, unchanged)
                    ╚══════════╤══════════╝
                               │
          ┌────────────────────┼────────────────────┐
          │                    │                     │
  ┌───────▼───────┐   ┌───────▼───────┐   ┌────────▼────────┐
  │  STREET EAR   │   │   NEWS DESK   │   │ PORTFOLIO       │
  │  (existing)   │   │   (existing)  │   │ ANALYST         │
  │               │   │               │   │ (existing)      │
  │ Reddit scan   │   │ Finnhub +     │   │ Prices +        │
  │ Sentiment     │   │ NewsAPI       │   │ Technicals +    │
  │ Mentions      │   │ Analysis      │   │ Fundamentals +  │
  │ Anomalies     │   │ Urgency       │   │ Risk            │
  └───────────────┘   └───────────────┘   └─────────────────┘
                               │
                      ┌────────▼────────┐
                      │  ALPHA SCOUT    │
                      │  (existing)     │  ← candidate sourcing
                      │  Reused by      │    logic reused by
                      │  conviction_mgr │    conviction_manager
                      └─────────────────┘

  + NEW: superinvestor_tracker.py (13F + insider data)
```

### Every existing module and its role in the new system

| Existing Module | Still Runs? | How the Advisor Uses It |
|----------------|-------------|------------------------|
| **Street Ear** (reddit_fetcher, analyzer, tracker) | Yes, unchanged | Advisor reads its agent bus signals for Reddit buzz on holdings + conviction list names |
| **News Desk** (news_fetcher, analyzer) | Yes, unchanged | Advisor reads its signals for breaking news, earnings, sector news affecting holdings |
| **Portfolio Analyst** (price_fetcher) | Yes, reused directly | Advisor calls `fetch_current_prices()` and `fetch_all_historical()` for all tracked tickers |
| **Portfolio Analyst** (technical_analyzer) | Yes, reused directly | Advisor calls `analyze_ticker()` for technicals on holdings + conviction list |
| **Portfolio Analyst** (fundamental_analyzer) | Yes, reused directly | Advisor calls `fetch_fundamentals()` for P/E, margins, growth, 52wk data |
| **Portfolio Analyst** (risk_analyzer) | Yes, reused directly | Advisor calls `analyze_concentration()` and `analyze_sector_exposure()` |
| **Alpha Scout** (candidate_sourcer) | Yes, reused by conviction_manager | Sources new candidates from agent bus, sector peers, screeners — fed into conviction pipeline |
| **Alpha Scout** (screener) | Yes, reused by conviction_manager | Scores candidates on tech/fund/sentiment/diversification before Opus evaluation |
| **Agent Bus** | Yes, unchanged | All inter-agent communication. Advisor reads signals with `mark_consumed=False` |
| **Cost Tracker** | Yes, unchanged | Tracks all Opus API spend |
| **Config Loader** | Yes, extended | Adds `load_advisor_config()` |
| **Telegram Bot** | Yes, extended | New commands added (`/holdings`, `/macro`, `/conviction`, `/thesis`, etc.) |
| **Security** | Yes, unchanged | Env validation, HTML sanitization |
| **Logger** | Yes, unchanged | Structured logging |

### What's genuinely new (not a reuse)

| New Component | Purpose | Why it can't reuse existing code |
|--------------|---------|--------------------------------|
| `advisor/memory.py` | Persistent memory DB (theses, snapshots, conviction history) | Nothing like this exists — current system is stateless between runs |
| `advisor/macro_analyst.py` | FRED data + macro thesis tracking with status evolution | No macro awareness exists at all |
| `advisor/superinvestor_tracker.py` | SEC 13F parsing + insider transaction tracking | No smart money tracking exists |
| `advisor/holdings_monitor.py` | Daily narrative per holding with memory of past days | Current portfolio_analyst has no memory |
| `advisor/strategy_engine.py` | Low-churn add/trim/hold logic with flag persistence | Current system has no strategy layer |
| `advisor/conviction_manager.py` | Persistent conviction list that evolves over weeks | Alpha Scout generates fresh lists each run — no persistence |
| `advisor/moonshot_manager.py` | Long-lived moonshot idea tracking | Doesn't exist |
| `advisor/formatter.py` | 5-section brief format | Different output structure from current |
| `advisor/main.py` | Orchestrates existing agents + new advisor modules | New orchestration flow |
| `data/advisor_memory.db` | SQLite database for all memory | New database |
| `config/advisor.yaml` | Holdings with theses, macro theses, superinvestor list | New config format |

### What we DON'T change

- Zero modifications to Street Ear, News Desk, or their sub-modules
- Zero modifications to Portfolio Analyst sub-modules (price_fetcher, technical_analyzer, fundamental_analyzer, risk_analyzer)
- Alpha Scout's candidate_sourcer.py and screener.py stay as-is — imported by conviction_manager
- Agent bus schema unchanged (just add a couple signal types)
- All existing SQLite databases unchanged
- Morning Brief (`morning_brief.py`) stays as a legacy option — can still run via `/brief_legacy`

---

## Build Order

```
Step 1: Memory layer (advisor/memory.py + DB schema — all 11 tables)
        Config file (config/advisor.yaml)
        No external dependencies. Foundation for everything else.

Step 2: Holdings monitor (advisor/holdings_monitor.py)
        Daily snapshots, thesis tracking, narrative generation.
        Depends on: memory.py + existing price_fetcher + fundamental_analyzer.

Step 3: Macro analyst (advisor/macro_analyst.py)    ┐
        FRED data, thesis status tracking, regime.   │
        Depends on: memory.py. New dep: fredapi.     │
                                                     │ Can build
Step 4: Earnings analyzer (advisor/earnings_analyzer.py)  │ in parallel
        Transcript fetching, guidance extraction,    │
        cross-mention detection.                     │
        Depends on: memory.py. New dep: FMP API.     │
                                                     │
Step 5: Prediction markets (advisor/prediction_market.py) │
        Polymarket + Kalshi API integration.         │
        Depends on: memory.py.                       │
                                                     │
Step 6: Superinvestor tracker (advisor/superinvestor_tracker.py)
        SEC 13F parsing, insider transactions.       ┘
        Depends on: memory.py + yfinance.

Step 7: Valuation engine (advisor/valuation_engine.py)
        3yr target calc, CAGR, margin of safety.
        Depends on: earnings_analyzer (for guidance) + fundamental_analyzer.

Step 8: Conviction + moonshot managers
        Persistent list logic with evidence scoring (3/5 test).
        25% CAGR gate via valuation_engine.
        Depends on: memory.py + valuation_engine + superinvestor + earnings + prediction_market.

Step 9: Strategy engine (advisor/strategy_engine.py)
        Add/trim/hold logic with low-churn bias.
        Depends on: all of the above.

Step 10: Formatter + main orchestrator
         Wire everything into the 5-section brief.
         Depends on: all of the above.

Step 11: Telegram integration
         New commands, update bot.
```

Steps 1-2 are sequential (memory first, then holdings). Steps 3-6 can all be built in parallel. Steps 7-11 are sequential.

---

## New Dependencies

```
fredapi            # FRED economic data (rates, yields, CPI)
```

All other data fetched via `requests` (Polymarket, Kalshi, SEC EDGAR) or `yfinance` (already installed).

### New Environment Variables

```env
# Add to .env
FRED_API_KEY=your_key          # Free at https://fred.stlouisfed.org/docs/api/api_key.html
FMP_API_KEY=your_key           # Free at https://financialmodelingprep.com/ (250 calls/day)
                               # For earnings transcripts. Optional — falls back to yfinance earnings data.
KALSHI_API_KEY=your_key        # Optional — for Kalshi prediction markets
                               # Polymarket API is public (no key needed)
```

---

## Day 1 vs Day 30 vs Day 180

**Day 1**: System has your holdings and theses from config. Conviction list is empty. No memory. Brief is data-driven but lacks narrative depth.

**Day 7**: System has a week of snapshots. Can say "NVDA up 5 of 7 sessions" and "META valuation flag raised 3 days ago, still valid." Conviction list has 2-3 names in early research phase.

**Day 30**: Rich narrative memory. Knows how each holding performed through an earnings cycle. Conviction list has promoted 1-2 names to "consider adding." Strategy flags have history — some resolved, some persistent. Macro theses have evolved. The brief reads like a PM wrote it.

**Day 180**: Full market cycle context. Knows which macro theses played out and which didn't. Conviction list has a track record. The system's own judgment is calibrated — it knows "my high-conviction promotions have a 75% hit rate" and adjusts accordingly.
