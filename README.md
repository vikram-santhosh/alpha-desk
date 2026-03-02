# AlphaDesk

**Multi-agent investment intelligence that replaces 2 hours of daily research with a single Telegram briefing.**

Seven AI agents scan Reddit, news, Substack, YouTube, your portfolio, the broader market, and macro/conviction signals — then a synthesis layer produces an actionable daily brief delivered via Telegram.

## Architecture

```mermaid
flowchart TD
    subgraph sources["Data Sources"]
        R["Reddit\nr/wsb · r/investing · r/stocks"]
        N["News APIs\nFinnhub · NewsAPI"]
        S["Substack RSS\nConfigured newsletters"]
        Y["YouTube API\nConfigured channels"]
        PF["Portfolio\nyfinance · FRED · FMP · Kalshi"]
    end

    subgraph phase1["Phase 1 — Parallel Ingestion"]
        SE["Street Ear\nReddit intelligence"]
        ND["News Desk\n10 concurrent batches\ngemini-2.5-flash"]
        SUB["Substack Ear\nNewsletter analysis"]
        YT["YouTube Ear\nTranscript analysis"]
    end

    subgraph phase2["Phase 2 — Discovery"]
        AS["Alpha Scout\nTicker discovery + screening\ngemini-2.5-pro"]
    end

    subgraph phase3["Phase 3 — Portfolio"]
        PA["Portfolio Analyst\nTechnicals · Fundamentals · Risk\ngemini-2.5-pro"]
    end

    subgraph phase4["Phase 4 — Synthesis"]
        AD["Advisor\ngemini-2.5-pro"]
        subgraph committee["Analyst Committee"]
            GR["Growth Analyst"]
            VA["Value Analyst"]
            RO["Risk Officer"]
            SK["Skeptic Agent"]
        end
        CM["Conviction Manager"]
        MM["Moonshot Manager"]
        ST["Strategy Engine"]
    end

    subgraph delivery["Delivery"]
        TG["Telegram\nCondensed brief"]
        EM["Email\nVerbose memo + charts"]
    end

    subgraph infra["Shared Infrastructure"]
        BUS[("Agent Bus\nSQLite pub/sub")]
        SHIM["gemini_compat.py\nAnthropic → Gemini shim"]
        COST["Cost Tracker\nDaily cap enforcement"]
    end

    R --> SE
    N --> ND
    S --> SUB
    Y --> YT
    PF --> PA

    SE -->|signals| BUS
    ND -->|signals| BUS
    SUB -->|signals| BUS
    YT -->|signals| BUS

    BUS --> AS
    BUS --> PA
    BUS --> AD

    AS -->|candidates| AD
    PA -->|holdings analysis| AD

    AD --- committee
    AD --- CM
    AD --- MM
    AD --- ST

    AD --> TG
    AD --> EM

    SHIM -.->|backs all LLM calls| phase1
    SHIM -.->|backs all LLM calls| phase2
    SHIM -.->|backs all LLM calls| phase3
    SHIM -.->|backs all LLM calls| phase4
    COST -.->|tracks spend| SHIM
```

**Typical runtime:** ~3.5 minutes. **Typical cost:** ~$8/run (Gemini 2.5 Pro + Flash).

## LLM Backend

AlphaDesk uses **Google Gemini** via an Anthropic-compatible shim (`src/shared/gemini_compat.py`). All agent code calls the standard `anthropic` SDK interface; the shim routes to the right Gemini model automatically.

| Claude tier called by agents | Gemini model used | Thinking |
|---|---|---|
| `claude-haiku-*` | `gemini-2.5-flash` | Disabled (`budget=0`) — fast JSON extraction |
| `claude-sonnet-*` | `gemini-2.5-pro` | Capped at 512 tokens |
| `claude-opus-*` | `gemini-2.5-pro` | Capped at 512 tokens |

> **Why thinking is capped:** Gemini 2.5 Pro runs a mandatory thinking phase that shares the `max_output_tokens` budget. Without a cap, thinking can consume the entire budget and produce empty visible output.

## Agents

| Agent | Role | Data Sources | Key Output |
|-------|------|-------------|------------|
| **Street Ear** | Reddit intelligence | r/wallstreetbets, r/investing, r/stocks | Unusual mentions, sentiment reversals, narrative formation |
| **News Desk** | Market news analysis | Finnhub, NewsAPI | Scored headlines, macro events, sector news |
| **Substack Ear** | Long-form newsletter analysis | Configured Substack feeds | Analyst theses, deep-dive summaries |
| **YouTube Ear** | Finance video transcripts | Configured YouTube channels | Video summaries, key insights from creators |
| **Alpha Scout** | Ticker discovery | All agents + screening | Buy/watch recommendations with investment theses |
| **Portfolio Analyst** | Holdings analysis | yfinance, agent bus signals | Technicals, fundamentals, risk metrics |
| **Advisor** | Investment synthesis | All of the above + memory | 5-section daily brief with actions |

### Analyst Committee (inside Advisor)

| Sub-Agent | Perspective | Produces |
|-----------|------------|----------|
| **Growth Analyst** | Revenue acceleration, TAM, competitive moats | Growth scores, catalysts, moat assessment |
| **Value Analyst** | Valuation, margin of safety, capital allocation | Value scores, regime classification, fair value |
| **Risk Officer** | Correlation, concentration, drawdown scenarios | Risk flags, max drawdown scenario, correlation warnings |
| **Skeptic Agent** | Adversarial challenge to every recommendation | Confidence modifier, invalidation conditions, base rates |
| **Delta Engine** | Day-over-day change detection | High/medium/low significance changes |
| **Catalyst Tracker** | Event calendar (FOMC, CPI, earnings) | Next 30 days of catalysts with impact estimates |

## Quick Start

### 1. Clone and install

```bash
git clone <your-repo-url> alphadesk
cd alphadesk
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env` with your keys:

```env
# Required
GEMINI_API_KEY=AIza...
TELEGRAM_BOT_TOKEN=123456:ABC-DEF...
TELEGRAM_CHAT_ID=your_numeric_chat_id

# News (at least one recommended)
FINNHUB_API_KEY=your_finnhub_key
NEWSAPI_KEY=your_newsapi_key

# Advisor layer
FRED_API_KEY=your_fred_key
FMP_API_KEY=your_fmp_key
KALSHI_API_KEY=your_kalshi_key

# YouTube Ear (optional)
YOUTUBE_API_KEY=your_youtube_data_api_v3_key

# Daily spend cap (default $20)
DAILY_COST_CAP=20.00
```

### 3. Configure your portfolio

Edit `config/advisor.yaml` with your holdings, macro theses, and strategy parameters. You can also create `private/portfolio.yaml` to keep holdings out of version control:

```yaml
holdings:
  - ticker: NVDA
    category: core
    thesis: "AI CapEx beneficiary — dominant GPU franchise"
    shares: 100
    entry_price: 95.00
  - ticker: AMZN
    category: core
    thesis: "AWS re-acceleration + retail margin expansion"
    shares: 50
    entry_price: 160.00
```

### 4. Configure content sources

**YouTube channels** (`config/youtube_channels.yaml`):
```yaml
max_video_age_hours: 48
channels:
  - name: Patrick Boyle
    channel_id: UCM45lRp6mfZMF1dSITOIqUQ
  - name: The Plain Bagel
    channel_id: UCFCEuCsyWP0YkP3CZ3Mr01Q
```

**Substack feeds** (`config/substack_feeds.yaml`): add the RSS URLs of newsletters you follow.

### 5. First run

```bash
# Full morning brief (all agents + synthesis)
python -m src.shared.morning_brief

# Or start the Telegram bot (long-running with daily schedule)
python -m src.shared.telegram_bot
```

## Configuration

| File | Purpose |
|------|---------|
| `config/advisor.yaml` | Holdings, macro theses, strategy params, v2 settings |
| `config/portfolio.yaml` | Holdings with shares and cost basis |
| `config/watchlist.yaml` | Additional tickers to track |
| `config/scout.yaml` | Alpha Scout screening parameters |
| `config/subreddits.yaml` | Reddit sources for Street Ear |
| `config/youtube_channels.yaml` | YouTube channels for YouTube Ear |
| `config/substack_feeds.yaml` | Substack RSS feeds for Substack Ear |
| `private/portfolio.yaml` | Private holdings override (git-ignored) |
| `.env` | API keys and secrets (git-ignored) |

## Sample Output

```
☀️ ALPHADESK DAILY BRIEF — Mar 01, 2026
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

SECTION 1 - WHAT CHANGED TODAY
Quiet day — VIX at 14.5, 10Y at 4.25%. NVDA up 2.3% on
continued CapEx guidance from MSFT earnings call. No thesis
changes.

SECTION 2 - ANALYST CONSENSUS & DISAGREEMENTS
• Growth and Value agree: NVDA remains best risk-reward in semis
• Risk Officer flags 65% portfolio exposure to AI CapEx narrative
• Value Analyst says AVGO is stretched at 38x forward P/E

SECTION 3 - ACTIONS
No action. All theses intact.

SECTION 4 - WHAT TO WATCH THIS WEEK
• FOMC minutes Wednesday — watch for rate cut language
• NVDA earnings Thursday — CapEx thesis validation

SECTION 5 - PORTFOLIO HEALTH
Risk score: 42/100. Concentration in semis/AI remains primary concern.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
AlphaDesk | ~$8.00 today | 3m 36s
```

## Cost Estimate

| Mode | Estimated Cost | Notes |
|------|---------------|-------|
| Full daily brief | ~$7–10/run | News Desk (46 batches on Flash) is the main driver |
| Individual command | ~$0.10–0.50 | Single section (e.g., `/holdings`, `/macro`) |
| Backtest (5 days) | ~$4–6 | Full pipeline replay with real LLM calls |
| Backtest (skip committee) | ~$0.10–0.50 | Rule-based engines only, near-zero API cost |
| Weekly retrospective | ~$0.50 | Self-assessment + pattern analysis |

**Model pricing used:**

| Model | Input | Output |
|-------|-------|--------|
| `gemini-2.5-pro` | $1.25 / M tokens | $10.00 / M tokens |
| `gemini-2.5-flash` | $0.075 / M tokens | $0.30 / M tokens |

Default daily cap: **$20** (configurable via `DAILY_COST_CAP` in `.env`). When exceeded, synthesis steps are skipped and raw data is delivered.

## Pipeline Timing

| Phase | Agent(s) | Typical Time |
|-------|----------|-------------|
| Phase 1 | Street Ear + News Desk + Substack Ear + YouTube Ear (parallel) | ~135s |
| Phase 2 | Alpha Scout | ~20s |
| Phase 3 | Portfolio Analyst | ~15s |
| Phase 4 | Advisor synthesis | ~25s |
| **Total** | | **~3–4 minutes** |

**News Desk is the bottleneck.** It splits articles into batches of 5 and calls Gemini 2.5 Flash concurrently (up to 10 workers). Each Flash call takes ~3s; with 46 batches and 10 workers that's ~5 rounds. Pro-tier synthesis calls take ~25s each due to the mandatory thinking phase.

## Telegram Commands

### Morning Brief

| Command | Description |
|---------|-------------|
| `/brief` | Full morning briefing (all agents + synthesis) |
| `/news` | Market news only |
| `/trending` | Reddit intelligence only |
| `/discover` | Alpha Scout ticker discovery |
| `/portfolio` | Portfolio analysis only |

### Advisor

| Command | Description |
|---------|-------------|
| `/advisor` | Full daily brief (analyst committee + all sections) |
| `/holdings` | Portfolio check-in with P&L |
| `/macro` | Macro & market context |
| `/conviction` | Conviction list (top 3-5 names) |
| `/moonshot` | Moonshot ideas (1-2 asymmetric bets) |
| `/action` | Strategy actions (add/trim/hold) |

### Intelligence

| Command | Description |
|---------|-------------|
| `/delta` | What changed since yesterday |
| `/catalysts` | Upcoming catalysts (30d calendar) |
| `/scorecard` | Recommendation track record |
| `/retro` | Weekly retrospective & self-assessment |
| `/report` | Latest verbose report file path |

### System

| Command | Description |
|---------|-------------|
| `/cost` | API cost report for today |
| `/status` | System status and recent signals |
| `/help` | List all available commands |

## Project Structure

```
alphadesk/
├── config/
│   ├── advisor.yaml            # Holdings, theses, strategy, v2 settings
│   ├── portfolio.yaml          # Holdings with shares + cost basis
│   ├── watchlist.yaml          # Additional tickers to track
│   ├── scout.yaml              # Alpha Scout screening config
│   ├── subreddits.yaml         # Reddit sources for Street Ear
│   ├── youtube_channels.yaml   # YouTube channels for YouTube Ear
│   └── substack_feeds.yaml     # Substack RSS feeds
├── src/
│   ├── advisor/                # Investment advisor (24 modules)
│   │   ├── main.py             # Pipeline orchestrator
│   │   ├── memory.py           # SQLite persistent memory
│   │   ├── formatter.py        # Telegram output formatter
│   │   ├── verbose_formatter.py # Full investment memo generator
│   │   ├── analyst_committee.py # Growth + Value + Risk + CIO synthesis
│   │   ├── skeptic_agent.py    # Adversarial recommendation testing
│   │   ├── delta_engine.py     # Day-over-day change detection
│   │   ├── catalyst_tracker.py # Event calendar (FOMC, CPI, earnings)
│   │   ├── conviction_manager.py # 5-source evidence-based conviction list
│   │   ├── moonshot_manager.py # Asymmetric bet tracking
│   │   ├── strategy_engine.py  # Add/trim/hold recommendations
│   │   ├── valuation_engine.py # DCF-based target prices
│   │   ├── macro_analyst.py    # FRED macro indicators + thesis testing
│   │   ├── holdings_monitor.py # Daily holdings check-in with memory
│   │   ├── earnings_analyzer.py # Earnings calls + management guidance
│   │   ├── prediction_market.py # Polymarket + Kalshi crowd sentiment
│   │   ├── superinvestor_tracker.py # 13F filings + insider activity
│   │   ├── outcome_scorer.py   # Recommendation track record
│   │   └── retrospective.py    # Weekly self-assessment
│   ├── street_ear/             # Reddit intelligence agent
│   ├── news_desk/              # News intelligence agent (concurrent batching)
│   ├── substack_ear/           # Substack newsletter agent
│   ├── youtube_ear/            # YouTube transcript agent
│   ├── portfolio_analyst/      # Portfolio analysis agent
│   ├── alpha_scout/            # Ticker discovery agent
│   ├── backtest/               # Backtesting framework
│   ├── report/                 # Report delivery CLI
│   ├── shared/                 # Cross-agent infrastructure
│   │   ├── agent_bus.py        # SQLite pub/sub for inter-agent signals
│   │   ├── gemini_compat.py    # Anthropic→Gemini compatibility shim
│   │   ├── config_loader.py    # YAML config loading
│   │   ├── cost_tracker.py     # API cost tracking with budget cap
│   │   ├── morning_brief.py    # Primary pipeline orchestrator
│   │   ├── telegram_bot.py     # Bot commands + scheduling
│   │   ├── email_reporter.py   # SMTP email delivery
│   │   ├── report_generator.py # HTML report with sparklines
│   │   ├── security.py         # Env validation, input sanitization
│   │   └── schemas.py          # Shared data schemas
│   └── utils/
│       ├── logger.py           # Structured logging
│       └── cleanup.py          # Data cleanup utilities
├── tests/
├── Dockerfile
├── docker-compose.yaml
├── requirements.txt
├── .env.example
└── README.md
```

## API Keys

| Key | Required | Source | What It Powers |
|-----|----------|--------|---------------|
| `GEMINI_API_KEY` | Yes | [Google AI Studio](https://aistudio.google.com/app/apikey) | All LLM analysis (Pro + Flash) |
| `TELEGRAM_BOT_TOKEN` | Yes | [BotFather](https://t.me/BotFather) | Daily brief delivery |
| `TELEGRAM_CHAT_ID` | Yes | See setup guide | Message routing |
| `FINNHUB_API_KEY` | Recommended | [finnhub.io](https://finnhub.io/) | Company news per ticker |
| `NEWSAPI_KEY` | Recommended | [newsapi.org](https://newsapi.org/) | Market headlines |
| `FRED_API_KEY` | Recommended | [fred.stlouisfed.org](https://fred.stlouisfed.org/docs/api/api_key.html) | Macro indicators (rates, yield curve) |
| `YOUTUBE_API_KEY` | Optional | [Google Cloud Console](https://console.cloud.google.com/) | YouTube Data API v3 for YouTube Ear |
| `FMP_API_KEY` | Optional | [financialmodelingprep.com](https://site.financialmodelingprep.com/) | Earnings transcripts + guidance |
| `KALSHI_API_KEY` | Optional | [kalshi.com](https://kalshi.com/) | Prediction market data |
| `SMTP_USER` | Optional | Your email provider | Email report delivery |
| `SMTP_PASS` | Optional | Your email provider | Email report delivery |
| `REPORT_EMAIL_TO` | Optional | — | Email recipient address |

## Running on a Schedule

### Option A: Telegram bot (recommended)

Fires the full morning briefing daily at 07:00, delivers to Telegram:

```bash
python -m src.shared.telegram_bot
```

### Option B: Docker

```bash
docker compose up -d
```

### Option C: systemd (Linux)

```ini
[Unit]
Description=AlphaDesk Telegram Bot
After=network.target

[Service]
Type=simple
User=your_user
WorkingDirectory=/path/to/alphadesk
ExecStart=/path/to/python -m src.shared.telegram_bot
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

## Running Tests

```bash
python -m pytest
```

## Backtesting

```bash
# Quick backtest (skip LLM calls, near-zero cost)
python -m src.backtest --days 5 --skip-committee

# Full backtest with analyst committee (~$4-6)
python -m src.backtest --days 5

# Dry run (show config, estimate cost)
python -m src.backtest --days 30 --dry-run
```

Output: `backtests/{date}/results.json`, `summary.md`, `signals.csv` with per-agent hit rates, confusion matrices, and forward-looking returns.

## Roadmap

### Built

- [x] 7 AI agents: Street Ear, News Desk, Substack Ear, YouTube Ear, Alpha Scout, Portfolio Analyst, Advisor
- [x] SQLite agent bus for inter-agent pub/sub
- [x] Analyst committee (Growth + Value + Risk + CIO Editor)
- [x] Delta engine (day-over-day change detection)
- [x] Catalyst tracker (FOMC, CPI, earnings calendar)
- [x] Skeptic agent (adversarial recommendation testing)
- [x] Conviction pipeline (5-source evidence testing + 25% CAGR gate)
- [x] Moonshot manager (disruptors, catalyst plays, turnarounds)
- [x] Outcome tracking + weekly retrospective
- [x] Backtesting framework with per-agent metrics
- [x] Verbose investment memos (Markdown + HTML)
- [x] Email delivery with sparkline charts
- [x] Prediction market integration (Polymarket + Kalshi)
- [x] Superinvestor tracking (13F filings)
- [x] Concurrent news batch processing (10 workers, ~9x speedup)
- [x] Gemini 2.5 Pro + Flash dual-model backend with Anthropic-compatible shim

### Planned

- [ ] Correlation risk analysis (portfolio-level thesis concentration)
- [ ] Position sizing guidance (target weight recommendations)
- [ ] Tax-lot awareness (hold period before trim recs)
- [ ] Web dashboard for report browsing

## License

MIT
