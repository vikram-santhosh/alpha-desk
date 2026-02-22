# AlphaDesk

Multi-agent investment intelligence system. Five AI agents scan Reddit, news, your portfolio, the broader market, and macro/conviction signals, then synthesize a daily briefing delivered via Telegram.

## Architecture

```
Phase 1 (parallel):  Street Ear + News Desk     (Reddit + news scanning, signal publishing)
Phase 2:             Alpha Scout                 (ticker discovery, screening, recommendations)
Phase 3:             Portfolio Analyst            (technicals, fundamentals, risk, signal consumption)
Phase 4:             Advisor                      (memory-driven conviction, macro, moonshots, actions)
Phase 5:             Morning Brief synthesis      (Opus 4.6 cross-agent synthesis + Telegram delivery)
```

### Agents

| Agent | What it does |
|-------|-------------|
| **Street Ear** | Scans Reddit (WSB, r/investing, etc.) for ticker mentions, sentiment, and narratives |
| **News Desk** | Fetches market news from Finnhub + NewsAPI, scores relevance and urgency |
| **Alpha Scout** | Discovers new tickers via screening across technical, fundamental, sentiment, and diversification dimensions; generates buy/watch recommendations with investment theses |
| **Portfolio Analyst** | Runs technical + fundamental analysis on your holdings, computes risk metrics, integrates cross-agent signals |
| **Advisor** | Memory-driven personal investment advisor — tracks conviction list, macro theses, earnings intelligence, prediction markets, and moonshot ideas with persistent state |

Agents communicate through a SQLite-based **agent bus** — each agent publishes signals that downstream agents consume and cross-reference.

### Advisor Decision Engines

The Advisor runs five specialized engines:

| Engine | Data sources | Purpose |
|--------|-------------|---------|
| **Conviction Manager** | Guidance, crowd sentiment, smart money, fundamentals, analyst consensus | Evaluates tickers against 5 evidence sources with a 25% CAGR gate for promotion |
| **Macro Analyst** | FRED (fed funds, yield curve, inflation), yfinance | Tests macro theses against real data, tracks regime changes |
| **Earnings Analyzer** | Financial Modeling Prep transcripts | Tracks earnings calls, management guidance, cross-company mentions |
| **Prediction Market** | Polymarket, Kalshi | Monitors Fed policy odds, recession probability, trade/fiscal outcomes |
| **Moonshot Manager** | Agent bus signals, thematic screens | Manages small-cap disruptors, catalyst plays, turnarounds (max 3% allocation) |

## Prerequisites

- Python 3.11+
- An [Anthropic API key](https://console.anthropic.com/) (powers Claude Opus 4.6 synthesis)
- A [Telegram bot token](https://core.telegram.org/bots#how-do-i-create-a-bot) + your chat ID

Optional API keys (for full coverage):

| Key | Source | What it powers |
|-----|--------|---------------|
| Finnhub | [finnhub.io](https://finnhub.io/) | Company news per ticker |
| NewsAPI | [newsapi.org](https://newsapi.org/) | Market headlines |
| FRED | [fred.stlouisfed.org](https://fred.stlouisfed.org/docs/api/api_key.html) | Macro indicators (rates, yield curve, inflation) |
| FMP | [financialmodelingprep.com](https://site.financialmodelingprep.com/developer/docs) | Earnings call transcripts + guidance |
| Kalshi | [kalshi.com](https://kalshi.com/) | Prediction market data |

## Setup

### 1. Clone and install dependencies

```bash
git clone <your-repo-url> alphadesk
cd alphadesk
pip install -r requirements.txt
```

### 2. Configure environment variables

```bash
cp .env.example .env
```

Edit `.env` with your keys:

```env
# Required
ANTHROPIC_API_KEY=sk-ant-...
TELEGRAM_BOT_TOKEN=123456:ABC-DEF...
TELEGRAM_CHAT_ID=your_numeric_chat_id

# News & market data (at least one recommended)
FINNHUB_API_KEY=your_finnhub_key
NEWSAPI_KEY=your_newsapi_key

# Advisor layer
FRED_API_KEY=your_fred_key
FMP_API_KEY=your_fmp_key
KALSHI_API_KEY=your_kalshi_key

# Optional: daily API spend cap in USD (default: $20)
DAILY_COST_CAP=20.00
```

**Getting your Telegram chat ID:** Send any message to your bot, then visit `https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates` — your chat ID is in the response under `message.chat.id`.

### 3. Configure your portfolio

Edit `config/portfolio.yaml`:

```yaml
holdings:
  - ticker: AAPL
    shares: 100
    cost_basis: 150.00
  - ticker: GOOG
    shares: 30
    cost_basis: 142.20
```

Edit `config/watchlist.yaml`:

```yaml
tickers: [NVDA, META, AVGO, TSLA]
```

### 4. Configure the Advisor

Edit `config/advisor.yaml` to set your holdings with investment theses, macro theses, superinvestors to track, strategy parameters (hold periods, position limits, CAGR gates), and moonshot archetypes. Defaults work well out of the box.

### 5. (Optional) Customize Alpha Scout

Edit `config/scout.yaml` to adjust screening parameters, scoring weights, sector peer maps, and source toggles. Defaults work well out of the box.

## Running

### Full daily briefing (one-shot)

Runs all 5 agents, synthesizes, and prints the result:

```bash
python -m src.shared.morning_brief
```

### Telegram bot (long-running with daily schedule)

Starts the bot, listens for commands, and automatically sends the Advisor briefing every day at 7:00 AM:

```bash
python -m src.shared.telegram_bot
```

### Docker

```bash
docker compose up -d
```

This builds the image, mounts `data/` and `config/` as volumes, and runs the Telegram bot with auto-restart.

### Individual agents

```bash
# Portfolio analysis only
python -c "
import asyncio
from src.portfolio_analyst.main import run
result = asyncio.run(run())
print(result['formatted'])
"

# Alpha Scout discovery only
python -c "
import asyncio
from src.alpha_scout.main import run
result = asyncio.run(run())
print(result['formatted'])
"

# Advisor only
python -c "
import asyncio
from src.advisor.main import run
result = asyncio.run(run())
print(result['formatted'])
"
```

## Telegram Commands

### Advisor

| Command | Description |
|---------|-------------|
| `/advisor` | Full 5-section advisor brief |
| `/holdings` | Portfolio check-in |
| `/macro` | Macro & market context |
| `/conviction` | Conviction list (top 3-5 names) |
| `/moonshot` | Moonshot ideas |
| `/action` | Strategy actions (add/trim/hold) |

### Core Agents

| Command | Description |
|---------|-------------|
| `/brief` | Full morning briefing (all agents + synthesis) |
| `/refresh` | Same as /brief — refresh all data |
| `/portfolio` | Portfolio analysis only |
| `/news` | Market news only |
| `/trending` | Reddit intelligence only |
| `/discover` | Alpha Scout ticker discovery |

### System

| Command | Description |
|---------|-------------|
| `/cost` | API cost report for today |
| `/status` | System status and recent signals |
| `/help` | List available commands |

## Running on a Schedule

### Option A: Built-in scheduler (recommended)

Run the Telegram bot — it includes a scheduler that fires the Advisor briefing daily at 07:00:

```bash
# Run in the background
nohup python -m src.shared.telegram_bot > data/bot.log 2>&1 &
```

### Option B: Docker (recommended for servers)

```bash
docker compose up -d
```

The container auto-restarts on failure and persists data via volume mounts.

### Option C: systemd service (Linux)

Create `/etc/systemd/system/alphadesk.service`:

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

```bash
sudo systemctl enable alphadesk
sudo systemctl start alphadesk
```

## Project Structure

```
alphadesk/
├── config/
│   ├── portfolio.yaml          # Your holdings (shares + cost basis)
│   ├── watchlist.yaml          # Tickers to track
│   ├── subreddits.yaml         # Reddit sources for Street Ear
│   ├── scout.yaml              # Alpha Scout screening config
│   └── advisor.yaml            # Advisor config (holdings, macro theses, strategy)
├── data/                       # Runtime data (SQLite DBs, logs)
│   ├── agent_bus.db            # Inter-agent signal bus
│   ├── street_ear_tracker.db   # Reddit mention history
│   ├── cost_tracker.db         # API cost tracking
│   ├── advisor_memory.db       # Advisor persistent memory
│   └── alphadesk.log           # Application log
├── src/
│   ├── shared/                 # Shared infrastructure
│   │   ├── agent_bus.py        # SQLite pub/sub for inter-agent signals
│   │   ├── config_loader.py    # YAML config loading
│   │   ├── cost_tracker.py     # API cost tracking with budget cap
│   │   ├── morning_brief.py    # Master orchestrator
│   │   ├── security.py         # Env validation, input sanitization
│   │   └── telegram_bot.py     # Bot commands + scheduling
│   ├── utils/
│   │   ├── logger.py           # Structured logging
│   │   └── cleanup.py          # Data cleanup utilities
│   ├── street_ear/             # Reddit intelligence agent
│   │   ├── main.py
│   │   ├── reddit_fetcher.py
│   │   ├── analyzer.py
│   │   ├── tracker.py
│   │   └── formatter.py
│   ├── news_desk/              # News intelligence agent
│   │   ├── main.py
│   │   ├── news_fetcher.py
│   │   ├── analyzer.py
│   │   └── formatter.py
│   ├── portfolio_analyst/      # Portfolio analysis agent
│   │   ├── main.py
│   │   ├── price_fetcher.py
│   │   ├── technical_analyzer.py
│   │   ├── fundamental_analyzer.py
│   │   ├── risk_analyzer.py
│   │   └── formatter.py
│   ├── alpha_scout/            # Ticker discovery agent
│   │   ├── main.py
│   │   ├── candidate_sourcer.py
│   │   ├── screener.py
│   │   ├── synthesizer.py
│   │   └── formatter.py
│   └── advisor/                # Personal investment advisor
│       ├── main.py
│       ├── memory.py           # SQLite persistent memory
│       ├── conviction_manager.py
│       ├── macro_analyst.py
│       ├── earnings_analyzer.py
│       ├── prediction_market.py
│       ├── moonshot_manager.py
│       ├── holdings_monitor.py
│       ├── strategy_engine.py
│       ├── valuation_engine.py
│       ├── superinvestor_tracker.py
│       └── formatter.py
├── Dockerfile
├── docker-compose.yaml
└── requirements.txt
```

## Cost Management

AlphaDesk tracks API costs in real time. Claude Opus 4.6 pricing: $15/MTok input, $75/MTok output.

- Default daily cap: **$20** (configurable via `DAILY_COST_CAP` in `.env`)
- When the cap is hit, synthesis steps are skipped and raw agent outputs are delivered instead
- Check spend anytime with `/cost` in Telegram

A typical full briefing costs ~$0.30-0.50 depending on market activity and number of tickers.

## Logs

All logs go to both stdout and `data/alphadesk.log`:

```bash
tail -f data/alphadesk.log
```
