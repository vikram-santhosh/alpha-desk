# AlphaDesk

Multi-agent investment intelligence system. Four AI agents scan Reddit, news, your portfolio, and the broader market, then synthesize a daily briefing delivered via Telegram.

## Architecture

```
Phase 1 (parallel):  Street Ear + News Desk     (Reddit + news scanning, signal publishing)
Phase 2:             Alpha Scout                 (ticker discovery, screening, recommendations)
Phase 3:             Portfolio Analyst            (technicals, fundamentals, risk, signal consumption)
Phase 4:             Morning Brief synthesis      (Opus 4.6 cross-agent synthesis + Telegram delivery)
```

### Agents

| Agent | What it does |
|-------|-------------|
| **Street Ear** | Scans Reddit (WSB, r/investing, etc.) for ticker mentions, sentiment, and narratives |
| **News Desk** | Fetches market news from Finnhub + NewsAPI, scores relevance and urgency |
| **Alpha Scout** | Discovers new tickers via screening across technical, fundamental, sentiment, and diversification dimensions; generates buy/watch recommendations with investment theses |
| **Portfolio Analyst** | Runs technical + fundamental analysis on your holdings, computes risk metrics, integrates cross-agent signals |

Agents communicate through a SQLite-based **agent bus** — each agent publishes signals that downstream agents consume and cross-reference.

## Prerequisites

- Python 3.11+
- An [Anthropic API key](https://console.anthropic.com/) (powers Claude Opus 4.6 synthesis)
- A [Telegram bot token](https://core.telegram.org/bots#how-do-i-create-a-bot) + your chat ID
- (Optional) [Finnhub API key](https://finnhub.io/) for company news
- (Optional) [NewsAPI key](https://newsapi.org/) for market headlines

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

# Optional (News Desk needs at least one for full coverage)
FINNHUB_API_KEY=your_finnhub_key
NEWSAPI_KEY=your_newsapi_key

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

### 4. (Optional) Customize Alpha Scout

Edit `config/scout.yaml` to adjust screening parameters, scoring weights, sector peer maps, and source toggles. Defaults work well out of the box.

## Running

### Full morning briefing (one-shot)

Runs all 4 agents, synthesizes, and prints the result:

```bash
python -m src.shared.morning_brief
```

To also send it to Telegram:

```bash
python -c "
import asyncio
from dotenv import load_dotenv; load_dotenv()
from src.shared.morning_brief import run
from src.shared.telegram_bot import send_message
import os

result = asyncio.run(run())
send_message(os.getenv('TELEGRAM_CHAT_ID'), result['formatted'])
"
```

### Telegram bot (long-running with daily schedule)

Starts the bot, listens for commands, and automatically sends the full briefing every day at 7:00 AM:

```bash
python -m src.shared.telegram_bot
```

### Individual agents

Run any single agent via the bot commands or programmatically:

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
```

## Telegram Commands

| Command | Description |
|---------|-------------|
| `/brief` | Full morning briefing (all agents + synthesis) |
| `/refresh` | Same as /brief — refresh all data |
| `/portfolio` | Portfolio analysis only |
| `/news` | Market news only |
| `/trending` | Reddit intelligence only |
| `/discover` | Alpha Scout ticker discovery |
| `/cost` | API cost report for today |
| `/status` | System status and recent signals |
| `/help` | List available commands |

## Running on a Schedule

### Option A: Built-in scheduler (recommended)

Run the Telegram bot — it includes a scheduler that fires the full briefing daily at 07:00:

```bash
# Run in the background
nohup python -m src.shared.telegram_bot > data/bot.log 2>&1 &
```

To change the time, edit line 227 in `src/shared/telegram_bot.py`:

```python
schedule.every().day.at("07:00").do(_run_scheduled_brief)
```

### Option B: Cron job

Add to your crontab (`crontab -e`):

```cron
# Daily briefing at 7:00 AM
0 7 * * * cd /path/to/alphadesk && python -c "import asyncio; from dotenv import load_dotenv; load_dotenv(); from src.shared.morning_brief import run; from src.shared.telegram_bot import send_message; import os; r=asyncio.run(run()); send_message(os.getenv('TELEGRAM_CHAT_ID'), r['formatted'])" >> data/cron.log 2>&1
```

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
│   ├── portfolio.yaml          # Your holdings
│   ├── watchlist.yaml          # Tickers to track
│   ├── subreddits.yaml         # Reddit sources for Street Ear
│   └── scout.yaml              # Alpha Scout screening config
├── data/                       # Runtime data (SQLite DBs, logs)
│   ├── agent_bus.db            # Inter-agent signal bus
│   ├── street_ear_tracker.db   # Reddit mention history
│   ├── cost_tracker.db         # API cost tracking
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
│   │   └── cleanup.py
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
│   └── alpha_scout/            # Ticker discovery agent
│       ├── main.py
│       ├── candidate_sourcer.py
│       ├── screener.py
│       ├── synthesizer.py
│       └── formatter.py
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
