# AlphaDesk Redesign — Personal Investment Advisor

## Philosophy Shift

**Current system**: Scans everything, dumps data, presents options daily.
**New system**: Thinks like YOUR portfolio manager. Has a worldview. Remembers yesterday. Only speaks up when something matters. Values consistency over novelty.

Core principles:
- You're an investor, not a trader. Hold period: 1+ year.
- Low churn. "No action needed" is the best answer most days.
- Macro thesis drives stock-level decisions (top-down → bottom-up).
- Recommendations persist across days — don't churn names.
- Prefer undervalued stocks. Open to momentum when evidence is strong.
- Track what smart money is doing.

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

## Technical Architecture

### New Files

```
src/advisor/
├── __init__.py
├── main.py                      # Master orchestrator (replaces morning_brief as primary)
├── macro_analyst.py             # Macro thesis tracking, FRED data, regime
├── holdings_monitor.py          # Daily holdings check-in with memory
├── strategy_engine.py           # Add/trim/hold logic with low-churn bias
├── conviction_manager.py        # Persistent conviction list management
├── moonshot_manager.py          # Moonshot idea tracking
├── superinvestor_tracker.py     # 13F parsing, whale tracking
├── memory.py                    # All advisor_memory.db operations
└── formatter.py                 # 5-section brief formatter

config/advisor.yaml              # Holdings, theses, tracked superinvestors
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
```

### Pipeline Flow

```
1. Load memory (advisor_memory.db)
   ├── Yesterday's brief summary
   ├── Holdings + theses + snapshots
   ├── Macro theses + status
   ├── Conviction list (current)
   ├── Moonshot list (current)
   ├── Active strategy flags
   └── Superinvestor data

2. Fetch fresh data (parallel)
   ├── Street Ear → Reddit signals
   ├── News Desk → News signals
   ├── Price data → All tracked tickers (holdings + conviction + moonshot)
   ├── FRED → Rates, yields, VIX
   └── yfinance → Insider transactions for conviction list names

3. Opus 4.6 synthesis (single comprehensive call)
   Input: memory + fresh data + explicit instructions
   Output: 5-section daily brief as structured JSON

4. Save memory
   ├── Today's holding snapshots
   ├── Updated thesis statuses
   ├── Updated conviction list
   ├── Updated moonshot list
   ├── New/resolved strategy flags
   └── Today's brief summary (for tomorrow)

5. Format → Telegram HTML → Send
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

## What Changes vs Current System

| Component | Current | After Redesign |
|-----------|---------|---------------|
| Morning brief orchestrator | `morning_brief.py` (4 agents) | `advisor/main.py` (memory-aware, 5-section output) |
| Holdings | `config/portfolio.yaml` (ticker, shares, cost_basis) | `config/advisor.yaml` (ticker, thesis, category) + daily snapshots in DB |
| Recommendations | Alpha Scout: 15 new names every run | Conviction list: 3-5 persistent names, updated not replaced |
| Memory | None (each run starts fresh) | `advisor_memory.db`: theses, snapshots, flags, conviction history, brief history |
| Macro awareness | None | Tracked theses with status, FRED data, regime |
| Action bias | "Here are 15 interesting tickers" | "No action needed today" (default) |
| Smart money | None | 13F quarterly + insider daily |
| Moonshots | None | 1-2 persistent asymmetric ideas |
| Output tone | Data dump | Opinionated advisor with worldview |

### What We Keep

- **Street Ear** — still scans Reddit, still publishes signals to agent bus
- **News Desk** — still fetches news, still publishes signals
- **Agent Bus** — still the communication backbone
- **Portfolio Analyst modules** — price_fetcher, technical_analyzer, fundamental_analyzer reused
- **Telegram Bot** — extended with new commands
- **Cost Tracker** — unchanged
- **Config/security/logging** — unchanged

### What We Retire

- **Alpha Scout** as a standalone agent — its candidate sourcing logic gets absorbed into conviction_manager.py, but the "15 random names daily" behavior is replaced by persistent conviction list management
- **Morning Brief** as the primary entry point — replaced by `advisor/main.py` which produces the 5-section brief. Morning Brief can still exist as a legacy/alternative mode.

---

## Build Order

```
Step 1: Memory layer (advisor/memory.py + DB schema)
        Config file (config/advisor.yaml)
        No external dependencies. Foundation for everything else.

Step 2: Holdings monitor (advisor/holdings_monitor.py)
        Daily snapshots, thesis tracking, narrative generation.
        Depends on: memory.py + existing price_fetcher.

Step 3: Macro analyst (advisor/macro_analyst.py)
        FRED data, thesis status tracking, regime.
        Depends on: memory.py. New dep: fredapi.

Step 4: Superinvestor tracker (advisor/superinvestor_tracker.py)
        SEC 13F parsing, insider transactions.
        Depends on: memory.py + yfinance.

Step 5: Conviction + moonshot managers
        Persistent list logic with promotion/removal.
        Depends on: memory.py + superinvestor data.

Step 6: Strategy engine (advisor/strategy_engine.py)
        Add/trim/hold logic with low-churn bias.
        Depends on: all of the above.

Step 7: Formatter + main orchestrator
        Wire everything into the 5-section brief.
        Depends on: all of the above.

Step 8: Telegram integration
        New commands, update bot.
```

Steps 1-4 can be partially parallelized. Steps 5-8 are sequential.

---

## New Dependencies

```
fredapi    # FRED economic data (rates, yields, CPI)
```

```env
# Add to .env
FRED_API_KEY=your_key   # Free at https://fred.stlouisfed.org/docs/api/api_key.html
```

---

## Day 1 vs Day 30 vs Day 180

**Day 1**: System has your holdings and theses from config. Conviction list is empty. No memory. Brief is data-driven but lacks narrative depth.

**Day 7**: System has a week of snapshots. Can say "NVDA up 5 of 7 sessions" and "META valuation flag raised 3 days ago, still valid." Conviction list has 2-3 names in early research phase.

**Day 30**: Rich narrative memory. Knows how each holding performed through an earnings cycle. Conviction list has promoted 1-2 names to "consider adding." Strategy flags have history — some resolved, some persistent. Macro theses have evolved. The brief reads like a PM wrote it.

**Day 180**: Full market cycle context. Knows which macro theses played out and which didn't. Conviction list has a track record. The system's own judgment is calibrated — it knows "my high-conviction promotions have a 75% hit rate" and adjusts accordingly.
