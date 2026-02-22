# AlphaDesk Buffett Upgrade — Full Build Plan

## Vision

Transform AlphaDesk from a tactical scanner into an autonomous investment analyst that thinks like Warren Buffett, trades like a quant, and learns from its own track record. The system should answer one question every day:

> "What should I buy, hold, or sell today — and exactly why?"

---

## Final Outcome (What the Daily Briefing Looks Like After All Phases)

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🎯 ALPHADESK DAILY CONVICTION REPORT — Feb 21, 2026

📊 PORTFOLIO HEALTH
Total Value: $147,230  |  P&L: +$18,430 (+14.3%)
Sharpe (90d): 1.82  |  Max Drawdown: -8.2%  |  Cash: 15%
Track Record: 72% win rate on past 50 recommendations

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🚨 ACTION ITEMS (Requires Your Decision)

  🟢 BUY: AAPL @ $178.50 — Conviction: HIGH
     Target: $240 (+34%) | Stop: $158 (-11%) | Position: 8% of portfolio
     Thesis: FCF yield 5.2% vs 3.8% 5yr avg. ROIC 58% and expanding.
     Trading at 15% below intrinsic value ($210 DCF).
     Insiders bought $12M in last 30 days. Moat: WIDE (ecosystem lock-in).
     ⏱ This is the 3rd time AAPL entered our buy zone in 12 months.
     Past performance: 2/2 previous buy signals returned avg +22%.

  🔴 SELL: INTC @ $24.30 — Conviction: HIGH
     Thesis INVALIDATED: ROIC declined from 18% → 7% over 3 years.
     Gross margin compressed 54% → 41%. Lost foundry moat.
     Original buy thesis (turnaround under Gelsinger) has not materialized.
     Capital is better deployed elsewhere. Estimated tax loss: -$2,100.

  🟡 REDUCE: RKLB — Trim from 12% → 6% of portfolio
     Concentration risk: position grew to 12% after +48% run.
     Fundamentals still strong (Rev growth 45%) but valuation stretched
     (P/S 28x vs sector 8x). Lock in gains, redeploy to AAPL.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🔍 DISCOVERY — New Ticker Recommendations

  1. LLY — Portfolio Add [HIGH conviction]
     Moat: WIDE (GLP-1 drug pipeline, 10yr patent runway)
     ROIC: 42% | FCF Yield: 3.1% | Rev CAGR 5yr: 18%
     22% below intrinsic value. Insiders net buyers.
     Entry: $680-720 | Target: $950 | Stop: $620

  2. CHTR — Watchlist [MEDIUM conviction]
     Moat: NARROW (regional cable monopoly, but cord-cutting risk)
     ROIC: 15% | FCF Yield: 8.2% | P/E: 11.3
     Deep value but thesis needs confirmation: Q1 subscriber data.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📈 PORTFOLIO SCORECARD (Past Recommendations)

  Last 30 days: +8.2% vs S&P +3.1% (alpha: +5.1%)
  Active theses: 12 intact | 2 invalidated | 1 upgraded

  ✅ NFLX (rec'd Jan 15 @ $850): Now $920 (+8.2%) — THESIS INTACT
     FCF accelerating, ad tier growing faster than expected.
  ❌ NKE (rec'd Jan 20 @ $78): Now $72 (-7.7%) — UNDER REVIEW
     Missed earnings, China weakness. Watching Q2 guidance.
  ⬆️ GOOG (rec'd Dec 10 @ $165): Now $188 (+13.9%) — UPGRADED
     Moved from Watchlist → Portfolio. Cloud margins inflecting.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🌍 MARKET REGIME: LATE-CYCLE EXPANSION
  VIX: 14.2 (low) | 10Y: 4.3% | Yield curve: Normal
  Implication: Stay invested but tighten stops. Favor quality over growth.
  Cash recommendation: 15% (up from 10% last week)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

That's the target. Here's how to build it.

---

## Architecture After All Phases

```
┌─────────────────────────────────────────────────────────┐
│                    MORNING BRIEF ORCHESTRATOR            │
│                                                         │
│  Phase 1 (parallel): Street Ear + News Desk             │
│  Phase 2: Alpha Scout (discovery + deep fundamentals)   │
│  Phase 3: Value Lens (DCF, moat, quality scoring)       │
│  Phase 4: Trade Architect (entry/exit/sizing)           │
│  Phase 5: Portfolio Analyst (risk + performance)        │
│  Phase 6: Market Pulse (macro regime)                   │
│  Phase 7: Opus 4.6 Synthesis → Conviction Report        │
│                                                         │
│  Memory Layer: recommendation_tracker.db                │
│  (persists theses, tracks performance, feeds learning)  │
└─────────────────────────────────────────────────────────┘
```

### New Agents & Modules

| Component | Type | Purpose |
|-----------|------|---------|
| `src/value_lens/` | New Agent | Deep fundamentals: FCF, ROIC, DCF, moat scoring |
| `src/trade_architect/` | New Agent | Entry/exit signals, position sizing, stop losses |
| `src/market_pulse/` | New Agent | Macro regime detection, market breadth, cash allocation |
| `src/shared/recommendation_tracker.py` | New Shared Module | Persistent memory: recommendation history + performance tracking |
| `src/shared/insider_tracker.py` | New Shared Module | SEC Form 4 insider buying/selling data |
| `config/valuation.yaml` | New Config | DCF parameters, moat criteria, quality thresholds |
| `config/regime.yaml` | New Config | VIX thresholds, yield curve rules, cash allocation tiers |

---

## Phase 1: Deep Fundamentals — "Value Lens" Agent

**Goal**: Fetch every metric Warren Buffett looks at before buying a stock.

### New Files

```
src/value_lens/
├── __init__.py
├── main.py                    # Pipeline orchestrator
├── cash_flow_analyzer.py      # FCF, owner earnings, cash conversion
├── quality_scorer.py          # ROIC, ROE, debt ratios, margin trends
├── valuation_engine.py        # DCF intrinsic value, PEG, EV/EBITDA, P/FCF
├── moat_analyzer.py           # Opus 4.6 competitive advantage analysis
├── growth_analyzer.py         # Multi-year CAGR, growth sustainability
└── formatter.py               # Telegram output
config/valuation.yaml          # DCF assumptions, quality thresholds
```

### Data to Fetch (all available via yfinance)

**Cash Flow Statement** (yfinance `Ticker.cashflow`):
- Operating Cash Flow
- Capital Expenditures
- Free Cash Flow = Operating CF - CapEx
- FCF Yield = FCF / Market Cap
- FCF / Net Income ratio (earnings quality — should be >1.0)
- Owner Earnings = Net Income + D&A - CapEx (Buffett's formula)

**Balance Sheet** (yfinance `Ticker.balance_sheet`):
- Total Debt, Long-term Debt
- Total Equity, Stockholders' Equity
- Cash & Short-term Investments
- Net Debt = Total Debt - Cash
- Debt-to-Equity ratio
- Current Ratio = Current Assets / Current Liabilities
- Interest Coverage = EBIT / Interest Expense

**Return Metrics** (computed):
- ROIC = NOPAT / Invested Capital
- ROE = Net Income / Shareholders' Equity
- ROA = Net Income / Total Assets
- ROIC trending (3yr, 5yr — is the business getting better or worse?)

**Multi-Year Growth** (yfinance `Ticker.financials` — 4 years of annual data):
- Revenue CAGR (3yr, 5yr)
- EPS CAGR (3yr, 5yr)
- FCF CAGR (3yr, 5yr)
- Margin trends (expanding, stable, compressing?)

**Valuation Models**:
- **DCF Intrinsic Value**:
  - Project FCF 10 years using growth rate
  - Terminal value using perpetuity growth (2.5%)
  - Discount at WACC (default 10%, adjusted by beta)
  - Intrinsic Value = Sum of discounted CFs / shares outstanding
  - Margin of Safety = (Intrinsic - Current) / Intrinsic
- **Relative Valuation**:
  - P/E vs 5yr historical average
  - P/FCF vs sector median
  - EV/EBITDA vs sector median
  - PEG ratio (P/E / EPS growth rate)

**Dividend Analysis**:
- Dividend yield, payout ratio
- Years of consecutive dividend growth
- Buyback yield (share count reduction)
- Total shareholder yield = dividend yield + buyback yield

### Moat Analysis (Opus 4.6)

Feed Opus the full fundamental profile and ask it to score:

```
Moat Width: WIDE / NARROW / NONE
Moat Sources (check all that apply):
  - Brand power (pricing above commodity)
  - Network effects (value increases with users)
  - Switching costs (expensive to leave)
  - Cost advantages (scale, proprietary tech)
  - Intangible assets (patents, licenses, data)
  - Efficient scale (natural monopoly/oligopoly)
Moat Durability: 10+ years / 5-10 years / <5 years
Key Risk to Moat: [specific threat]
```

### Quality Score (0-100)

```
ROIC > 15%:          +20  |  > 25%: +10 bonus  |  < 10%: -10
ROIC trending up:    +10  |  trending down: -15
Debt/Equity < 0.5:   +15  |  < 1.0: +10  |  > 2.0: -15
FCF/NI > 1.0:        +15  |  < 0.5: -10  (earnings quality)
Gross margin > 40%:  +10  |  expanding: +5  |  compressing: -10
Interest coverage >5: +10  |  < 2: -15
Dividend growth 5yr+: +5  |  10yr+: +10
Moat = WIDE:         +10  |  NARROW: +5  |  NONE: -10
```

### Signal Types Published

- `quality_score` — per-ticker quality score + components
- `valuation_alert` — "AAPL trading 20% below intrinsic value"
- `moat_assessment` — moat width + sources for each ticker
- `thesis_invalidation` — "INTC ROIC declined below 10%, moat eroding"

### Modified Files

- `src/shared/agent_bus.py` — Add signal types: `quality_score`, `valuation_alert`, `moat_assessment`, `thesis_invalidation`
- `src/shared/config_loader.py` — Add `load_valuation_config()`
- `src/alpha_scout/screener.py` — Replace basic `score_fundamental()` with quality_score from Value Lens
- `src/shared/morning_brief.py` — Add Value Lens as Phase 3

---

## Phase 2: Smart Money Tracker — "Insider Edge" Module

**Goal**: Know what insiders and institutions are doing before the crowd.

### New Files

```
src/shared/insider_tracker.py  # SEC EDGAR API for Form 4 filings
```

### Data Sources

**SEC EDGAR API** (free, no key required):
- Company filings endpoint: `https://efts.sec.gov/LATEST/search-index?q=...`
- Form 4 (insider transactions): buying, selling, option exercises
- Parse: insider name, title, transaction type, shares, price, date

**yfinance** (already available):
- `Ticker.institutional_holders` — top institutional owners + % held
- `Ticker.major_holders` — insider %, institutional %, float
- `Ticker.insider_transactions` — recent insider buys/sells

**Short Interest** (via yfinance `Ticker.info`):
- `shortRatio`, `shortPercentOfFloat`

### Scoring Impact

Add to Value Lens quality score:
```
Net insider buying (30d):     +15
Net insider selling (30d):    -10
Institutional ownership >60%:  +5
Short interest > 20%:         -10  (crowded short — could also be contrarian bullish)
Short interest declining:      +5  (shorts covering)
```

### Signal Types Published

- `insider_activity` — "CEO of AAPL bought $5M in shares"
- `institutional_shift` — significant ownership changes

---

## Phase 3: Entry/Exit Engine — "Trade Architect" Agent

**Goal**: Answer "at what price do I buy, and when do I sell?"

### New Files

```
src/trade_architect/
├── __init__.py
├── main.py                  # Pipeline orchestrator
├── entry_calculator.py      # Buy zones based on DCF, support levels, ATR
├── exit_calculator.py       # Stop losses, trailing stops, profit targets
├── position_sizer.py        # Kelly criterion, risk-parity sizing
├── thesis_monitor.py        # Track thesis validity, invalidation triggers
└── formatter.py             # Telegram output with price levels
```

### Entry Zone Calculation

For each candidate, compute a **buy zone** using multiple methods:

```
1. DCF-based entry:
   Buy Below = Intrinsic Value × (1 - margin_of_safety)
   Default margin_of_safety = 0.25 (25% discount)

2. Technical entry:
   Support Level = max(SMA-200, lower Bollinger Band, recent swing low)
   Entry if price within 5% of support

3. Mean-reversion entry:
   P/E is >1 std dev below 5yr average P/E
   or
   Price is >20% below 52-week high with improving fundamentals

4. Combined Buy Zone:
   Lower bound = min(DCF entry, technical support)
   Upper bound = max(DCF entry, technical support)
   "Buy between $X and $Y"
```

### Exit / Stop-Loss Calculation

```
1. Initial stop-loss:
   Stop = Entry Price - (2 × ATR_14)
   Typical risk: 8-12% below entry

2. Trailing stop (once profitable):
   Trail = Highest Close Since Entry - (2 × ATR_14)
   Tighten as profit grows

3. Profit target:
   Target = Intrinsic Value (from DCF)
   or
   Target = Entry + (3 × risk)  ← 3:1 reward/risk

4. Thesis invalidation (automatic sell trigger):
   - ROIC drops below 10%
   - FCF turns negative for 2 consecutive quarters
   - Moat downgraded from WIDE to NONE
   - Revenue declines 2 consecutive quarters
   - Management change (CEO departure)
   → Signal: "SELL — thesis invalidated"
```

### Position Sizing (Kelly Criterion)

```
Kelly % = (win_rate × avg_win / avg_loss - (1 - win_rate)) / (avg_win / avg_loss)

Inputs (from recommendation_tracker.py history):
  - Historical win rate of our recommendations
  - Average win magnitude
  - Average loss magnitude

Constraints:
  - Max single position: 10% of portfolio (Buffett goes higher, but we're learning)
  - Min position: 2% (worth having)
  - Half-Kelly default (conservative — full Kelly is volatile)
  - Reduce sizing if correlation with existing holdings > 0.7
```

### Conviction → Position Size Mapping

```
HIGH conviction + Wide Moat:    8-10% of portfolio
HIGH conviction + Narrow Moat:  5-8%
MEDIUM conviction:              3-5%
LOW conviction (watchlist):     0% (monitor only)
```

### Signal Types Published

- `entry_signal` — "AAPL entered buy zone at $178 (25% below intrinsic)"
- `exit_signal` — "INTC trailing stop hit at $23.50"
- `position_size` — recommended allocation per ticker
- `thesis_invalidation` — specific trigger that failed

### Modified Files

- `src/shared/agent_bus.py` — Add signal types: `entry_signal`, `exit_signal`, `position_size`
- `src/shared/morning_brief.py` — Add Trade Architect as Phase 4
- `src/shared/telegram_bot.py` — Add `/action` command (buy/sell actions only)

---

## Phase 4: Recommendation Memory — "Recommendation Tracker" Module

**Goal**: Remember every recommendation, track its outcome, and learn.

This is the critical piece that makes the system **self-improving**.

### New Files

```
src/shared/recommendation_tracker.py   # SQLite persistent memory
data/recommendation_tracker.db          # Created at runtime
```

### Database Schema

```sql
-- Every recommendation ever made
CREATE TABLE recommendations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,                    -- when recommended
    ticker TEXT NOT NULL,
    category TEXT NOT NULL,                -- 'buy', 'watchlist', 'sell', 'reduce'
    conviction TEXT NOT NULL,              -- 'high', 'medium', 'low'
    entry_price REAL,                      -- price at recommendation time
    target_price REAL,                     -- DCF-based target
    stop_price REAL,                       -- stop-loss level
    position_pct REAL,                     -- recommended % of portfolio
    thesis TEXT NOT NULL,                  -- investment thesis
    moat_width TEXT,                       -- 'wide', 'narrow', 'none'
    quality_score INTEGER,                 -- 0-100
    composite_score REAL,                  -- from screener
    status TEXT DEFAULT 'active',          -- 'active', 'closed_win', 'closed_loss',
                                           -- 'invalidated', 'expired', 'upgraded', 'downgraded'
    closed_date TEXT,                      -- when position was closed
    closed_price REAL,                     -- price when closed
    return_pct REAL,                       -- realized return
    invalidation_reason TEXT,              -- why thesis was invalidated (if applicable)
    UNIQUE(ticker, date, category)
);

-- Daily price snapshots for active recommendations (for tracking unrealized P&L)
CREATE TABLE recommendation_tracking (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recommendation_id INTEGER NOT NULL,
    date TEXT NOT NULL,
    price REAL NOT NULL,
    unrealized_return_pct REAL,
    thesis_status TEXT DEFAULT 'intact',   -- 'intact', 'weakening', 'invalidated'
    notes TEXT,                            -- auto-generated status notes
    FOREIGN KEY (recommendation_id) REFERENCES recommendations(id)
);

-- Aggregate performance metrics (computed daily)
CREATE TABLE performance_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    win_rate REAL,                          -- % of closed recs that were profitable
    avg_return REAL,                        -- average return on closed recs
    avg_win REAL,                           -- average winning return
    avg_loss REAL,                          -- average losing return
    alpha_vs_sp500 REAL,                    -- our returns - S&P 500 returns
    sharpe_ratio REAL,                      -- risk-adjusted returns
    total_recommendations INTEGER,
    active_count INTEGER,
    high_conviction_win_rate REAL,          -- win rate on high-conviction picks only
    UNIQUE(date)
);

-- Thesis evolution log (tracks how a thesis changes over time)
CREATE TABLE thesis_journal (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recommendation_id INTEGER NOT NULL,
    date TEXT NOT NULL,
    event_type TEXT NOT NULL,               -- 'created', 'updated', 'strengthened',
                                            -- 'weakened', 'invalidated', 'upgraded'
    content TEXT NOT NULL,                  -- what changed and why
    data_snapshot TEXT,                     -- JSON of key metrics at this point
    FOREIGN KEY (recommendation_id) REFERENCES recommendations(id)
);
```

### Key Functions

```python
# Record a new recommendation
record_recommendation(ticker, category, conviction, thesis, entry_price,
                      target_price, stop_price, position_pct, moat, quality_score)

# Daily tracking update (called by morning brief)
update_tracking(recommendation_id, current_price, thesis_status, notes)

# Close a recommendation (win, loss, or invalidation)
close_recommendation(recommendation_id, reason, closed_price)

# Get active recommendations for a ticker (used by Trade Architect)
get_active_recommendations(ticker) -> list

# Get all active recommendations (used by Portfolio Analyst)
get_all_active() -> list

# Compute and store performance metrics
compute_performance_metrics() -> dict

# Get historical performance (used by synthesis prompt)
get_track_record(days=90) -> dict
# Returns: win_rate, avg_return, alpha, sharpe, high_conviction_win_rate

# Get past recommendations for a ticker (used by Alpha Scout + Trade Architect)
get_ticker_history(ticker) -> list
# Returns: all past recommendations, outcomes, and thesis evolution

# Check thesis validity against current data
check_thesis_validity(recommendation_id, current_fundamentals) -> str
# Returns: 'intact', 'weakening', 'invalidated' + reason

# Feed learning data into the synthesis prompt
get_learning_context() -> str
# Returns: formatted text about what worked, what didn't, and pattern insights
```

### How Memory Feeds Into Each Run

```
                  ┌──────────────────────────┐
                  │  recommendation_tracker   │
                  │         .db               │
                  └────┬──────────┬───────────┘
                       │          │
          ┌────────────▼──┐  ┌───▼────────────────┐
          │  Alpha Scout  │  │  Trade Architect    │
          │               │  │                     │
          │ "We recommended│  │ "Past buy signals   │
          │  AAPL 3 times │  │  at this P/E level  │
          │  before, all  │  │  had 72% win rate.  │
          │  profitable.  │  │  Size accordingly." │
          │  Upgrade to   │  │                     │
          │  HIGH conv."  │  │ "This ticker hit    │
          │               │  │  our stop last time │
          └───────────────┘  │  — thesis was wrong │
                             │  about margins."    │
                             └────────────────────┘
                                      │
                            ┌─────────▼──────────┐
                            │  Opus 4.6 Synthesis │
                            │                     │
                            │ "Our track record:  │
                            │  72% win rate,      │
                            │  +5.1% alpha.       │
                            │  High-conviction    │
                            │  picks: 85% win.    │
                            │  Adjust strategy:   │
                            │  our value picks    │
                            │  outperform growth  │
                            │  picks by 8%."      │
                            └─────────────────────┘
```

### Memory-Informed Synthesis Prompt Addition

```
## TRACK RECORD (last 90 days)
- Total recommendations: 47
- Win rate: 72% (34/47)
- Average return: +11.2%
- High-conviction win rate: 85% (17/20)
- Alpha vs S&P 500: +5.1%

## PATTERNS LEARNED
- Our value picks (low P/E + high ROIC) outperform growth picks by 8%
- Insider buying signals have 82% accuracy
- Reddit sentiment is contrarian — very bullish Reddit = sell signal
- Our stop losses saved avg 12% on losing positions

## ACTIVE RECOMMENDATIONS STATUS
- AAPL: rec'd at $178, now $192 (+7.9%) — thesis intact (FCF growing)
- NKE: rec'd at $78, now $72 (-7.7%) — thesis weakening (China miss)
- NFLX: rec'd at $850, now $920 (+8.2%) — thesis intact (ad tier)

## PAST OUTCOMES FOR TODAY'S CANDIDATES
- AAPL: recommended 3 times before, 3/3 profitable (avg +18%)
- LLY: never recommended — no history
- INTC: recommended once, lost -14% — thesis invalidated (margin compression)

Use this track record to calibrate your conviction levels. If our past
recommendations in a sector or style have been consistently wrong, lower
conviction. If a pattern has been consistently right, increase conviction.
```

---

## Phase 5: Macro Regime — "Market Pulse" Agent

**Goal**: Know what part of the market cycle we're in and adjust strategy.

### New Files

```
src/market_pulse/
├── __init__.py
├── main.py                    # Pipeline orchestrator
├── macro_fetcher.py           # FRED API for rates, yield curve, CPI
├── regime_detector.py         # Bull/bear/sideways classification
├── breadth_analyzer.py        # Market breadth, sector rotation
├── cash_allocator.py          # Cash vs invested recommendation
└── formatter.py               # Telegram output
config/regime.yaml             # VIX thresholds, regime rules
```

### Data Sources

**FRED API** (free, key required — https://fred.stlouisfed.org/):
- Federal Funds Rate (`FEDFUNDS`)
- 10-Year Treasury (`DGS10`)
- 2-Year Treasury (`DGS2`)
- Yield Curve Spread = 10Y - 2Y (`T10Y2Y`)
- CPI Year-over-Year (`CPIAUCSL`)
- Unemployment Rate (`UNRATE`)

**yfinance** (already available):
- VIX (`^VIX`)
- S&P 500 (`^GSPC`) — for breadth, performance comparison
- Sector ETFs (XLK, XLF, XLV, XLE, etc.) — for rotation signals

### Regime Classification

```
                    VIX < 15        VIX 15-25        VIX > 25
                 ┌──────────────┬────────────────┬──────────────┐
Yield Curve      │   GOLDILOCKS │    NORMAL      │   STRESS     │
  Normal (>0)    │   Full invest│    Std alloc   │   Buy dips   │
                 │   Cash: 5%   │    Cash: 10%   │   Cash: 15%  │
                 ├──────────────┼────────────────┼──────────────┤
Yield Curve      │   LATE CYCLE │    CAUTIOUS    │   CRISIS     │
  Inverted (<0)  │   Tighten    │    Defensive   │   Cash heavy │
                 │   Cash: 15%  │    Cash: 25%   │   Cash: 40%  │
                 └──────────────┴────────────────┴──────────────┘
```

### Strategy Adjustment by Regime

| Regime | Portfolio Strategy | Position Sizing | Sector Tilt |
|--------|-------------------|-----------------|-------------|
| Goldilocks | Aggressive growth, full Kelly | Max 10% per position | Technology, Consumer Discretionary |
| Normal | Balanced quality + growth | Standard half-Kelly | Broad diversification |
| Late Cycle | Favor quality + dividends | Reduce to 1/3 Kelly | Healthcare, Consumer Staples, Utilities |
| Cautious | Defensive, high FCF yield | Small positions only | Utilities, Healthcare, bonds |
| Stress | Contrarian buying (Buffett: "be greedy") | Start buying aggressively | Whatever is cheapest vs intrinsic value |
| Crisis | Maximum contrarian buying | Full Kelly on wide-moat | Blue chips at 40%+ discount |

### Signal Types Published

- `regime_change` — "Market shifted from Normal to Cautious"
- `cash_allocation` — "Increase cash to 25%"
- `sector_rotation` — "Rotate from Tech to Healthcare"

---

## Integration: How It All Fits Together

### Updated Morning Brief Pipeline

```python
async def run():
    # Phase 1 (parallel): Intelligence gathering
    street_ear, news_desk = await gather(
        run_street_ear(),     # Reddit signals
        run_news_desk(),      # News signals
    )

    # Phase 2: Discovery (reads signals, doesn't consume)
    alpha_scout = await run_alpha_scout()

    # Phase 3: Deep fundamental analysis on portfolio + top candidates
    value_lens = await run_value_lens()

    # Phase 4: Entry/exit signals, position sizing
    trade_architect = await run_trade_architect()

    # Phase 5: Portfolio risk + performance (consumes all signals)
    portfolio_analyst = await run_portfolio_analyst()

    # Phase 6: Macro context
    market_pulse = await run_market_pulse()

    # Phase 7: Update recommendation tracker
    update_recommendation_tracking()

    # Phase 8: Opus 4.6 Conviction Synthesis
    # Includes: track record, memory, learning context
    synthesis = synthesize_conviction_report(
        street_ear, news_desk, alpha_scout, value_lens,
        trade_architect, portfolio_analyst, market_pulse,
        track_record=get_track_record(),
        learning_context=get_learning_context(),
    )

    return assemble_conviction_report(...)
```

### Updated Alpha Scout Scoring (After Value Lens Exists)

Replace the current 4-dimension scoring with a 6-dimension system:

```
Dimension              Weight    Source
─────────────────────────────────────────
Quality (ROIC, moat)    0.25    Value Lens quality_scorer
Valuation (DCF margin)  0.25    Value Lens valuation_engine
Technical (momentum)    0.15    Portfolio Analyst technical_analyzer
Sentiment (crowd)       0.10    Street Ear + News Desk
Diversification         0.10    Portfolio Analyst risk_analyzer
Smart Money (insiders)  0.15    Insider Edge tracker
```

### New Telegram Commands

| Command | Description |
|---------|-------------|
| `/action` | Buy/sell actions only (no noise) |
| `/thesis AAPL` | Show current thesis + history for a ticker |
| `/scorecard` | Track record and performance metrics |
| `/regime` | Current market regime and cash allocation |
| `/intrinsic AAPL` | DCF intrinsic value calculation for a ticker |

---

## Build Order and Dependencies

```
Phase 1: Value Lens              (no dependencies — can build first)
   ├── cash_flow_analyzer.py     (yfinance .cashflow)
   ├── quality_scorer.py         (yfinance .financials + .balance_sheet)
   ├── valuation_engine.py       (DCF using above + .info)
   ├── moat_analyzer.py          (Opus 4.6 analysis)
   ├── growth_analyzer.py        (yfinance .financials multi-year)
   └── formatter.py

Phase 2: Insider Edge            (no dependencies — can build parallel with Phase 1)
   └── insider_tracker.py        (yfinance .insider_transactions + .major_holders)

Phase 3: Trade Architect         (depends on Phase 1 for DCF values)
   ├── entry_calculator.py       (needs DCF from valuation_engine)
   ├── exit_calculator.py        (needs ATR from technical_analyzer)
   ├── position_sizer.py         (needs Kelly data from rec tracker)
   └── thesis_monitor.py         (needs quality_score from quality_scorer)

Phase 4: Recommendation Tracker  (no dependencies — can build parallel with Phase 1)
   └── recommendation_tracker.py (pure SQLite, no external deps)

Phase 5: Market Pulse            (no dependencies — can build parallel)
   ├── macro_fetcher.py          (FRED API)
   ├── regime_detector.py        (VIX + yield curve)
   ├── breadth_analyzer.py       (sector ETFs via yfinance)
   └── cash_allocator.py         (regime → cash %)

Integration: Wire everything into morning_brief.py + telegram_bot.py
```

**Parallelizable**: Phases 1, 2, 4, and 5 have no cross-dependencies and can be built simultaneously. Phase 3 (Trade Architect) depends on Phase 1 (Value Lens) output.

---

## New Dependencies

```
# Add to requirements.txt
fredapi          # FRED economic data API
```

### New Environment Variables

```env
# Add to .env
FRED_API_KEY=your_fred_key   # Free at https://fred.stlouisfed.org/docs/api/api_key.html
```

---

## Success Metrics

After all phases are built, measure these monthly:

| Metric | Target | How Measured |
|--------|--------|-------------|
| Win Rate (all picks) | >65% | recommendation_tracker.db |
| Win Rate (high conviction) | >80% | recommendation_tracker.db |
| Average Return per pick | >12% annualized | recommendation_tracker.db |
| Alpha vs S&P 500 | >5% annualized | recommendation_tracker.db vs ^GSPC |
| Thesis Accuracy | >70% theses play out | thesis_journal table |
| Stop-Loss Savings | Avg 10%+ saved on losers | exit calculations vs actual |
| Time to Invalidation | <30 days to flag bad picks | thesis_monitor.py |

---

## Cost Estimate

| Phase | Opus Calls per Run | Estimated Cost per Run |
|-------|-------------------|----------------------|
| Current system | ~4-5 calls | ~$0.50 |
| + Value Lens (moat analysis) | +2 calls | +$0.30 |
| + Trade Architect (synthesis) | +1 call | +$0.15 |
| + Market Pulse | +0 (data only) | +$0.00 |
| + Enhanced synthesis | +1 call (larger prompt) | +$0.20 |
| **Total per daily run** | **~8-9 calls** | **~$1.15** |
| **Monthly (30 days)** | | **~$35** |

Well within a $50/month budget for institutional-quality daily analysis.

---

## What Memory Gives You (The Compounding Edge)

Run 1 (Day 1): System has no history. Makes recommendations based purely on current data.

Run 30 (Month 1): System has 30 days of data. Knows which recommendations are winning/losing. Starts adjusting conviction based on early results.

Run 90 (Month 3): System has meaningful track record. Knows:
- "Our value picks outperform growth picks by 8%"
- "Insider buying signals have 82% accuracy"
- "AAPL has been recommended 3 times, all profitable"
- "Our stop losses saved avg 12% on losers"
- Opus uses this context to make better-calibrated recommendations.

Run 365 (Year 1): System has full market cycle data. Knows:
- How it performs in different regimes (bull, bear, sideways)
- Which sectors it's best at analyzing
- Which signal combinations are most predictive
- Its own biases and blind spots
- Track record is statistically significant — can calculate real Sharpe ratio

**The system gets smarter every single day it runs.** That's the compounding edge — not just compound interest, but compound intelligence.
