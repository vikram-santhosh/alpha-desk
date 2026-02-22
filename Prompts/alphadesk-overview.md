# AlphaDesk — Project Overview

**Version:** 0.1 (Weekend MVP)
**Authors:** Vikram + [Friend's Name]
**Date:** February 2026
**Status:** Pre-build planning

---

## What Is AlphaDesk?

AlphaDesk is a **multi-agent AI investment research system** that automates the daily workflow of a serious retail investor. Instead of spending 1-2 hours every morning checking portfolios, reading news, scanning Reddit, watching YouTube recaps, and tracking macro events across 10+ browser tabs — AlphaDesk does it all and delivers a single curated briefing to your WhatsApp or Telegram.

The key insight: this isn't a dashboard or a chatbot. It's a **team of specialist AI agents** that each monitor a different part of the market, reason about what they find, and communicate with each other and with you like analysts on a trading desk.

---

## The Problem We're Solving

Every serious retail investor does some version of this daily ritual:

| Activity | Time Spent | Tools Used |
|----------|-----------|------------|
| Check portfolio P&L | 10-15 min | Brokerage app, Yahoo Finance |
| Read stock-specific news | 15-20 min | Finnhub, Bloomberg, Google News |
| Watch YouTube market recaps | 20-30 min | YouTube (multiple channels) |
| Scan Reddit for sentiment | 15-20 min | r/wallstreetbets, r/investing, r/stocks |
| Read Substack newsletters | 10-15 min | Email, Substack app |
| Check earnings calendar | 5-10 min | Finnhub, Earnings Whispers |
| Track macro/political news | 10-15 min | Twitter, news sites |
| Stress test / think about risk | 10-15 min | Mental math, spreadsheets |

**Total: 1.5 - 2.5 hours/day** of scattered, manual research.

The information exists. The sources are available. The problem is synthesis — connecting a Reddit thread about AWS to your AMZN position to the upcoming CPI print to your portfolio's tech concentration. No single tool does this. AlphaDesk does.

---

## The Product Vision

You wake up, open your Telegram group chat, and your team has already been working:

> **Street Ear** — 6:15 AM
> 🔥 Unusual Reddit activity on RKLB — 3.4x normal mentions across r/wallstreetbets and r/stocks. Narrative: "Neutron launch window confirmed." Sentiment is strongly bullish. This is 7.1% of our book.

> **Portfolio Analyst** — 6:20 AM
> 📊 Morning snapshot: Total $487K, up $3.8K (+0.79%) overnight. AMZN concentration at 47.8% — that's the highest since October. Street Ear flagged RKLB buzz, which is our 4th largest position.

> **Macro Strategist** — 6:25 AM
> 🌍 CPI drops tomorrow at 8:30 AM. Consensus 2.8%. If it comes in hot, expect tech to sell off. Our 68% tech concentration makes this high-impact. Fed speakers Waller and Bostic on the calendar today.

Then you reply: "What should I do about AMZN before CPI?" — and the team debates.

**That's AlphaDesk.** Not a report. Not a dashboard. A living conversation with your investment research team.

---

## The Agent Team

AlphaDesk consists of 7 specialist agents + 1 orchestrator. Each agent has a distinct role, personality, and data domain.

### Weekend MVP (What We're Building First)

| Agent | Codename | Role | Data Sources |
|-------|----------|------|-------------|
| **Reddit Intelligence** | Street Ear | Monitors financial subreddits, extracts tickers, scores sentiment, detects narratives | Reddit (public JSON API) |
| **Portfolio Tracker** | Portfolio Analyst | Tracks holdings, calculates P&L, flags concentration risk | yfinance, local YAML config |
| **Orchestrator** | Morning Brief | Combines all agent outputs into one daily briefing | All agents' outputs |

### Phase 2 (Weeks 2-4)

| Agent | Codename | Role | Data Sources |
|-------|----------|------|-------------|
| **News Aggregator** | News Desk | Stock-specific news with AI-scored relevance and sentiment | Finnhub, NewsAPI |
| **Video Analyst** | Media Analyst | YouTube transcript summaries with ticker extraction | yt-dlp, YouTube RSS |
| **Economic Tracker** | Macro Strategist | Fed, CPI, politics mapped to portfolio sector exposure | FRED, NewsAPI |

### Phase 3 (Weeks 5-8)

| Agent | Codename | Role | Data Sources |
|-------|----------|------|-------------|
| **Earnings Tracker** | Earnings Analyst | Earnings call analysis, guidance extraction, beat/miss scoring | SEC EDGAR, Finnhub |
| **Risk Engine** | The Quant | Monte Carlo simulations, VaR, scenario analysis | yfinance historical data |
| **Idea Generator** | The Scout | Cross-agent signal aggregation, portfolio gap analysis | All agents' outputs |

---

## How It's Different

| Tool | What It Does | What It Doesn't Do |
|------|-------------|-------------------|
| **Bloomberg Terminal** | Gives you data | Doesn't synthesize across sources or know your portfolio |
| **ChatGPT / Claude** | Answers questions | Doesn't proactively monitor or remember your holdings |
| **Trading Bots** | Execute trades | Don't reason about context or provide research |
| **Dexter (virattt)** | Deep financial statement analysis on demand | Single agent, reactive, no social/news/macro, no portfolio awareness |
| **AlphaDesk** | Team of agents that proactively monitor, reason, debate, and brief you | — |

---

## Technology Stack

| Layer | Technology | Why |
|-------|-----------|-----|
| Language | Python 3.11+ | Best ecosystem for finance + AI |
| LLM | Claude API (Haiku for bulk, Sonnet for synthesis) | Best reasoning quality for financial analysis |
| Reddit Data | Public JSON API (requests) | Free, no credentials needed, zero setup |
| Stock Data | yfinance | Free, comprehensive, no API key needed |
| Database | SQLite | Zero setup, file-based, perfect for local agent |
| Delivery | Telegram Bot API | Free, reliable, rich formatting |
| Build Tool | Claude Code | Pair programming from terminal |
| News (Phase 2) | Finnhub + NewsAPI | Free tiers sufficient |
| Macro (Phase 2) | FRED API | Free, official Federal Reserve data |
| Transcripts (Phase 2) | yt-dlp | Free, open source, no API key |

**Total ongoing cost: ~$15-30/month** (almost entirely Claude API usage for the agents' analysis)

---

## Security Model

**This project runs on an office laptop, so security is non-negotiable.**

1. **All credentials in `.env` file** — never committed to git, never hardcoded
2. **`.gitignore` excludes** all sensitive files (.env, databases, API logs, cached data)
3. **No brokerage API connections** — portfolio is a local YAML file, no trading capability
4. **No Reddit credentials stored** — uses public JSON API, no OAuth, no account access, read-only
5. **Telegram bot is private** — only responds to your specific chat ID
6. **All API calls audited** — every Claude API call logged with cost and token count
7. **No third-party dependencies from untrusted sources** — all packages are well-known PyPI libraries
8. **Data stays local** — SQLite on disk, no cloud storage, no external databases
9. **Docker isolation available** — can run in a container to sandbox from the host system

See the Architecture Document for the full security specification.

---

## Project Structure

```
alphadesk/
├── config/                     # User configuration (git-tracked, no secrets)
│   ├── portfolio.yaml          # Your stock holdings
│   ├── watchlist.yaml          # Stocks you're monitoring
│   └── subreddits.yaml         # Which subreddits to track
│
├── src/
│   ├── street_ear/             # Agent 1: Reddit Intelligence
│   │   ├── __init__.py
│   │   ├── reddit_fetcher.py   # Public JSON API data collection
│   │   ├── analyzer.py         # LLM ticker extraction + sentiment
│   │   ├── tracker.py          # Rolling state, narrative detection
│   │   ├── formatter.py        # Telegram message formatting
│   │   └── main.py             # Agent orchestrator
│   │
│   ├── portfolio_analyst/      # Agent 2: Portfolio Tracker
│   │   ├── __init__.py
│   │   ├── price_fetcher.py    # yfinance real-time prices
│   │   ├── risk_analyzer.py    # Concentration, sector exposure
│   │   ├── formatter.py        # Telegram message formatting
│   │   └── main.py             # Agent orchestrator
│   │
│   ├── shared/                 # Cross-agent infrastructure
│   │   ├── __init__.py
│   │   ├── agent_bus.py        # Inter-agent signal passing
│   │   ├── morning_brief.py    # Master orchestrator
│   │   ├── telegram_bot.py     # Shared Telegram delivery + commands
│   │   ├── config_loader.py    # YAML config loading
│   │   ├── cost_tracker.py     # API cost monitoring
│   │   └── security.py         # Input validation, secret management
│   │
│   └── utils/
│       ├── __init__.py
│       └── logger.py           # Structured logging
│
├── data/                       # Runtime data (git-ignored)
│   ├── reddit_posts.db         # SQLite — Reddit data
│   ├── agent_bus.db            # SQLite — inter-agent signals
│   ├── api_log.jsonl           # API call audit log
│   ├── reports/                # Archived briefings
│   └── cache/                  # Temporary cache files
│
├── tests/                      # Unit and integration tests
│   ├── test_reddit_fetcher.py
│   ├── test_analyzer.py
│   └── test_tracker.py
│
├── .env                        # Secrets (git-ignored, NEVER committed)
├── .env.example                # Template showing required keys
├── .gitignore                  # Excludes .env, data/, __pycache__/
├── requirements.txt            # Python dependencies
├── Dockerfile                  # Optional: containerized execution
├── docker-compose.yaml         # Optional: one-command startup
└── README.md                   # Setup + usage guide
```

---

## How to Collaborate

### Work Split for the Weekend

**Person A (e.g., Vikram):**
- Street Ear agent (Reddit pipeline + LLM analysis + narrative detection)
- Telegram bot setup + message formatting
- Morning briefing orchestrator

**Person B (e.g., Friend):**
- Portfolio Analyst agent (yfinance + risk analysis)
- Agent bus (inter-agent communication)
- Testing + Docker containerization

### How to Work in Parallel

1. Clone the repo: `git clone https://github.com/vikram-santhosh/alpha-desk.git`
2. Create your own `.env` file (copy from `.env.example`, fill in your keys)
3. Person A works in `src/street_ear/` and `src/shared/telegram_bot.py`
4. Person B works in `src/portfolio_analyst/` and `src/shared/agent_bus.py`
5. Both share `config/` files (portfolio.yaml, watchlist.yaml)
6. Push at milestones, pull before starting each session
7. Merge via git at the end of each half-day

### Communication During Build

- Share this document + Architecture doc + Prompts doc
- Use a shared Telegram group for testing (both can see bot outputs)
- Check in at: Saturday noon, Saturday evening, Sunday noon

---

## Success Criteria for the Weekend

By Sunday evening, we should have:

- [ ] Street Ear agent fetching Reddit data from 8+ subreddits
- [ ] LLM analysis extracting tickers and scoring sentiment
- [ ] Narrative detection flagging unusual activity
- [ ] Portfolio Analyst showing real-time P&L and concentration risk
- [ ] Agent bus passing signals between Street Ear → Portfolio Analyst
- [ ] Morning briefing combining both agents into one Telegram message
- [ ] Cron-style scheduling (every 4 hours during market hours)
- [ ] All credentials secured in .env, all data git-ignored
- [ ] Total weekend API cost < $50 (Claude Code + agent API calls)

---

## What's After the Weekend

Week 2-3: Add News Desk + YouTube Digest agents
Week 4-5: Add Macro Strategist + Earnings Analyst
Week 6-7: Add Quant (Monte Carlo) + Scout (idea generation)
Week 8: Polish, Docker packaging, open source release on GitHub

**Long-term vision:** Publish as an open-source project on GitHub. The multi-agent investment research team that anyone can run locally for ~$20/month.
