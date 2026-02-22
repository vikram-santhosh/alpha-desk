# AlphaDesk — Technical Architecture

**Version:** 0.1 (Weekend MVP)
**Date:** February 2026
**Audience:** Engineers building or contributing to AlphaDesk

---

## Table of Contents

1. System Overview
2. Architecture Diagram
3. Data Flow
4. Agent Design
5. Inter-Agent Communication
6. Security Architecture
7. Data Storage
8. API Cost Model
9. Deployment
10. Failure Modes

---

## 1. System Overview

AlphaDesk is a **locally-run, multi-agent investment intelligence system**. There is no cloud infrastructure, no hosted backend, no external database. Everything runs on your machine as Python processes, stores data in SQLite, and delivers output via Telegram Bot API.

**Core principles:**
- **Local-first:** All data and processing stays on your machine
- **Security-first:** No brokerage connections, no write access to any platform, strict secret management
- **Cost-efficient:** Claude Haiku for bulk analysis (~$0.001/call), Sonnet only for synthesis (~$0.01/call)
- **Modular:** Each agent is independent and can be run, tested, or disabled individually
- **Observable:** Every API call, every analysis, every signal is logged and auditable

---

## 2. Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                        YOUR LAPTOP (LOCAL)                          │
│                                                                     │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │                    MORNING BRIEF ORCHESTRATOR                  │  │
│  │          (src/shared/morning_brief.py)                         │  │
│  │                                                                │  │
│  │   1. Triggers agents in sequence                               │  │
│  │   2. Collects outputs                                          │  │
│  │   3. Passes signals via Agent Bus                              │  │
│  │   4. Formats combined briefing                                 │  │
│  │   5. Sends to Telegram                                         │  │
│  └──────────┬──────────────────┬──────────────────────────────────┘  │
│             │                  │                                     │
│      ┌──────▼──────┐   ┌──────▼──────┐                              │
│      │ STREET EAR  │   │ PORTFOLIO   │     (Future agents           │
│      │ (Agent 1)   │   │ ANALYST     │      plug in here)           │
│      │             │   │ (Agent 2)   │                              │
│      │ Reddit      │   │             │                              │
│      │ Fetcher     │   │ Price       │                              │
│      │   ↓         │   │ Fetcher     │                              │
│      │ Analyzer    │   │   ↓         │                              │
│      │ (Claude API)│   │ Risk        │                              │
│      │   ↓         │   │ Analyzer    │                              │
│      │ Tracker     │   │   ↓         │                              │
│      │   ↓         │   │ Formatter   │                              │
│      │ Formatter   │   │             │                              │
│      └──────┬──────┘   └──────┬──────┘                              │
│             │                  │                                     │
│      ┌──────▼──────────────────▼──────┐                              │
│      │         AGENT BUS              │                              │
│      │    (src/shared/agent_bus.py)   │                              │
│      │    SQLite: data/agent_bus.db   │                              │
│      │                                │                              │
│      │  Street Ear writes signals:    │                              │
│      │  → "RKLB unusual mentions"     │                              │
│      │  → "AMZN sentiment reversal"   │                              │
│      │                                │                              │
│      │  Portfolio Analyst reads them:  │                              │
│      │  → "RKLB is 7.1% of book"     │                              │
│      │  → "AMZN position update"      │                              │
│      └───────────────────────────────┘                              │
│                                                                     │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │                    SHARED INFRASTRUCTURE                       │  │
│  │                                                                │  │
│  │  ┌──────────────┐ ┌──────────────┐ ┌────────────────────────┐ │  │
│  │  │ Config       │ │ Cost Tracker │ │ Telegram Bot           │ │  │
│  │  │ Loader       │ │ (API audit)  │ │ (delivery + commands)  │ │  │
│  │  │ (YAML)       │ │ (JSONL log)  │ │                        │ │  │
│  │  └──────────────┘ └──────────────┘ └────────────────────────┘ │  │
│  │                                                                │  │
│  │  ┌──────────────┐ ┌──────────────┐ ┌────────────────────────┐ │  │
│  │  │ Security     │ │ Logger       │ │ .env                   │ │  │
│  │  │ (validation) │ │ (structured) │ │ (secrets, git-ignored) │ │  │
│  │  └──────────────┘ └──────────────┘ └────────────────────────┘ │  │
│  └───────────────────────────────────────────────────────────────┘  │
└──────────────────────────┬──────────────────────────────────────────┘
                           │
           ┌───────────────┼───────────────┐
           ▼               ▼               ▼
  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
  │ Claude API   │ │ Reddit       │ │ Telegram     │
  │ (Anthropic)  │ │ (Public JSON)│ │ Bot API      │
  │              │ │              │ │              │
  │ Haiku: bulk  │ │ No auth      │ │ Send only    │
  │ Sonnet: synth│ │ Read-only    │ │ Private chat │
  └──────────────┘ └──────────────┘ └──────────────┘
           ▼
  ┌──────────────┐
  │ yfinance     │
  │ (Yahoo Fin)  │
  │              │
  │ Price data   │
  │ No API key   │
  └──────────────┘
```

---

## 3. Data Flow

### 3.1 Street Ear Pipeline

```
TRIGGER: Cron (every 4 hrs) or /refresh command
   │
   ▼
┌─────────────────────────────────────────────────┐
│ Step 1: FETCH (reddit_fetcher.py)               │
│                                                  │
│ For each subreddit in config:                    │
│   → HTTP GET: /r/{sub}/hot.json?limit=50         │
│   → HTTP GET: /r/{sub}/rising.json?limit=25      │
│   → HTTP GET: /r/{sub}/new.json?limit=25         │
│   → Filter: min_score OR min_comments            │
│   → Dedup: skip if post_id already in DB         │
│   → High-engagement: fetch /comments/{id}.json   │
│   → Store in SQLite: posts + comments tables     │
│   → 2-second delay between requests              │
│                                                  │
│ Rate: ~30 req/min (self-throttled, no auth)      │
│ Cost: FREE                                       │
│ Time: ~60-120 seconds                            │
└──────────────────────┬──────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────┐
│ Step 2: ANALYZE (analyzer.py)                    │
│                                                  │
│ Batch unanalyzed posts (groups of 10):           │
│   → Claude Haiku: extract tickers               │
│     (explicit, company names, informal refs)     │
│   → Claude Haiku: score sentiment (-2 to +2)    │
│   → Claude Haiku: categorize (DD, meme, etc.)   │
│   → Cross-reference with portfolio + watchlist   │
│   → Store in SQLite: post_tickers, post_analysis │
│                                                  │
│ Rate: ~50 requests per run                       │
│ Cost: ~$0.005-0.02 per run (Haiku)              │
│ Time: ~60-90 seconds                             │
└──────────────────────┬──────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────┐
│ Step 3: TRACK (tracker.py)                       │
│                                                  │
│ Calculate rolling statistics:                    │
│   → Mention count per ticker (24h window)        │
│   → 7-day rolling average per ticker             │
│   → Unusual activity: current > 3x average       │
│   → Sentiment shift: 3-day avg reversal          │
│   → Multi-sub convergence: 3+ subs same ticker   │
│                                                  │
│ For unusual tickers:                             │
│   → Claude Haiku: summarize forming narrative    │
│                                                  │
│ Output: signals dict with alerts                 │
│ Cost: ~$0.001-0.005 per run (few Haiku calls)   │
│ Time: ~15-30 seconds                             │
└──────────────────────┬──────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────┐
│ Step 4: FORMAT + DELIVER (formatter.py)          │
│                                                  │
│ Structure: Holdings → Watchlist → Trending → DD  │
│ Truncate to 4000 chars (Telegram limit)          │
│ Send via Telegram Bot API (HTML parse mode)      │
│ Archive to data/reports/ as timestamped .md      │
│                                                  │
│ Cost: FREE                                       │
│ Time: ~2 seconds                                 │
└─────────────────────────────────────────────────┘
```

### 3.2 Portfolio Analyst Pipeline

```
TRIGGER: Cron (6 AM, 12 PM, 5 PM) or /portfolio command
   │
   ▼
┌─────────────────────────────────────────────────┐
│ Step 1: FETCH PRICES (price_fetcher.py)          │
│                                                  │
│ Load portfolio from config/portfolio.yaml        │
│ For each holding:                                │
│   → yfinance: current price, day change, volume  │
│ Calculate:                                       │
│   → Current value per position                   │
│   → Total portfolio value                        │
│   → Daily P&L ($ and %)                          │
│   → Current weight per position                  │
│                                                  │
│ Cost: FREE (yfinance, no API key)               │
│ Time: ~5-10 seconds                              │
└──────────────────────┬──────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────┐
│ Step 2: RISK ANALYSIS (risk_analyzer.py)         │
│                                                  │
│ Concentration risk:                              │
│   → Flag any position > 30% weight               │
│   → Flag top-2 concentration > 60%               │
│ Sector exposure:                                 │
│   → Map tickers to sectors                       │
│   → Flag sector > 50% (e.g., "68% tech")        │
│ Check Agent Bus for signals:                     │
│   → Any Street Ear alerts on holdings?           │
│   → Annotate portfolio with social signals       │
│                                                  │
│ Cost: FREE (local computation)                   │
│ Time: ~2 seconds                                 │
└──────────────────────┬──────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────┐
│ Step 3: FORMAT + DELIVER                         │
│                                                  │
│ Portfolio snapshot table                         │
│ Concentration warnings                           │
│ Social signal annotations from Agent Bus         │
│ Send via Telegram                                │
│                                                  │
│ Cost: FREE                                       │
│ Time: ~2 seconds                                 │
└─────────────────────────────────────────────────┘
```

### 3.3 Morning Brief (Combined Flow)

```
6:00 AM ─→ Cron triggers morning_brief.py
            │
            ├─→ Street Ear runs full pipeline
            │   └─→ Writes signals to Agent Bus
            │
            ├─→ Portfolio Analyst runs
            │   └─→ Reads signals from Agent Bus
            │       └─→ Annotates portfolio with Reddit intel
            │
            ├─→ Orchestrator collects both outputs
            │   └─→ Claude Sonnet: synthesize into unified briefing
            │       (this is the ONE Sonnet call per run)
            │
            └─→ Send combined briefing to Telegram
                └─→ Archive to data/reports/

Total time: ~3-5 minutes
Total cost per run: ~$0.02-0.05
```

---

## 4. Agent Design

### 4.1 Agent Interface

Every agent follows the same interface pattern:

```python
class Agent:
    def run(self, force: bool = False) -> AgentOutput:
        """Run the full agent pipeline. Returns structured output."""
        pass

    def get_signals(self) -> list[Signal]:
        """Return signals for other agents to consume."""
        pass

    def consume_signals(self, signals: list[Signal]) -> None:
        """React to signals from other agents."""
        pass

    def format_output(self) -> str:
        """Format output for Telegram delivery."""
        pass
```

### 4.2 Agent Output Schema

```python
@dataclass
class AgentOutput:
    agent_name: str
    timestamp: datetime
    summary: str                    # Human-readable summary
    signals: list[Signal]           # Signals for other agents
    telegram_message: str           # Formatted Telegram message
    metadata: dict                  # Cost, timing, post counts, etc.

@dataclass
class Signal:
    source_agent: str
    signal_type: str                # "unusual_mentions", "sentiment_reversal", etc.
    ticker: str
    severity: str                   # "low", "medium", "high", "critical"
    payload: dict                   # Arbitrary data
    created_at: datetime
```

---

## 5. Inter-Agent Communication

### 5.1 Agent Bus

The Agent Bus is a SQLite-backed message passing system. Agents don't call each other directly — they publish signals and consume them.

**Table: `signals`**

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PRIMARY KEY | Auto-increment |
| source_agent | TEXT | "street_ear", "portfolio_analyst", etc. |
| signal_type | TEXT | "unusual_mentions", "sentiment_reversal", etc. |
| ticker | TEXT | Stock ticker or NULL for non-ticker signals |
| severity | TEXT | "low", "medium", "high", "critical" |
| payload | TEXT (JSON) | Arbitrary structured data |
| created_at | TIMESTAMP | When the signal was created |
| consumed_by | TEXT (JSON) | List of agents that have read this signal |
| expires_at | TIMESTAMP | Auto-expire after 24 hours |

**Signal Types:**

| Type | Source | Consumed By | Meaning |
|------|--------|-------------|---------|
| `unusual_mentions` | Street Ear | Portfolio Analyst | Ticker at 3x+ normal Reddit activity |
| `sentiment_reversal` | Street Ear | Portfolio Analyst | Sentiment flipped from bull→bear or vice versa |
| `narrative_forming` | Street Ear | Morning Brief | New narrative emerging around a ticker |
| `multi_sub_convergence` | Street Ear | Morning Brief | Same ticker trending in 3+ subreddits |
| `concentration_warning` | Portfolio Analyst | Morning Brief | Position > 30% of portfolio |
| `high_exposure_event` | Portfolio Analyst | Morning Brief | A flagged ticker is a large holding |

### 5.2 Why Not Direct Function Calls?

Direct function calls create tight coupling. The bus pattern means:
- Agents can be developed and tested independently
- New agents plug in without modifying existing agents
- Agents can run on different schedules
- Failed agents don't crash other agents
- Signal history is queryable and debuggable

---

## 6. Security Architecture

### ⚠️ CRITICAL: This runs on an office laptop. Security is non-negotiable.

### 6.1 Threat Model

| Threat | Mitigation |
|--------|-----------|
| API keys leaked to git | `.env` in `.gitignore`, pre-commit hook checks |
| Data exfiltration | No outbound connections except Reddit JSON, Claude API, Telegram API, yfinance |
| Malicious Reddit content (prompt injection) | All Reddit text sanitized before LLM calls |
| Claude API cost runaway | Daily cost cap ($1/day default), circuit breaker |
| Telegram bot hijacked | Only responds to whitelisted chat_id(s) |
| SQLite DB contains sensitive data | DB files in data/ directory, git-ignored, no cloud sync |
| Office network monitoring | All API calls are HTTPS, no sensitive data in URLs |
| Process running with full user permissions | Use Docker container to sandbox (optional) |

### 6.2 Secret Management

```
.env file structure:

# Reddit (no credentials needed — public JSON API)
REDDIT_USER_AGENT=AlphaDesk/1.0 (investment research bot)

# Claude API
ANTHROPIC_API_KEY=...

# Telegram
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...          # Only this chat ID can interact with the bot
TELEGRAM_ALLOWED_USERS=...    # Comma-separated list of allowed user IDs

# Safety
DAILY_API_COST_CAP=1.00       # Stop making Claude API calls if exceeded
ENABLE_TELEGRAM_SEND=true     # Set to false during development
```

**Rules:**
1. `.env` is NEVER committed to git
2. `.env.example` shows required keys with placeholder values
3. `src/shared/security.py` validates all env vars on startup
4. If any required secret is missing, the program refuses to start
5. Secrets are loaded ONCE at startup, never re-read, never logged

### 6.3 Input Sanitization

Reddit content is user-generated and potentially malicious. Before sending any Reddit text to Claude API:

```python
def sanitize_for_llm(text: str) -> str:
    """
    Sanitize user-generated Reddit text before sending to Claude.
    Prevents prompt injection and removes dangerous content.
    """
    # 1. Truncate to max length (prevent context stuffing)
    text = text[:2000]

    # 2. Remove common prompt injection patterns
    injection_patterns = [
        r'ignore\s+(previous|above|all)\s+instructions',
        r'you\s+are\s+now',
        r'system\s*:',
        r'<\|.*?\|>',
        r'\[INST\]',
        r'\[/INST\]',
        r'<<SYS>>',
    ]
    for pattern in injection_patterns:
        text = re.sub(pattern, '[FILTERED]', text, flags=re.IGNORECASE)

    # 3. Remove null bytes and control characters
    text = ''.join(c for c in text if c.isprintable() or c in '\n\t')

    # 4. Escape XML/HTML entities
    text = html.escape(text)

    return text
```

### 6.4 Network Allowlist

The application should ONLY make outbound connections to:

| Destination | Protocol | Purpose |
|-------------|----------|---------|
| `www.reddit.com` | HTTPS | Reddit public JSON API (read-only, no auth) |
| `api.anthropic.com` | HTTPS | Claude API |
| `api.telegram.org` | HTTPS | Telegram Bot API |
| `query1.finance.yahoo.com` | HTTPS | yfinance data |
| `query2.finance.yahoo.com` | HTTPS | yfinance data |

No other outbound connections should be made. If running in Docker, this can be enforced at the network level.

### 6.5 Pre-Commit Security Hook

```bash
#!/bin/bash
# .git/hooks/pre-commit
# Prevent accidental secret commits

# Check for .env file
if git diff --cached --name-only | grep -q '\.env$'; then
    echo "ERROR: Attempting to commit .env file!"
    exit 1
fi

# Check for API key patterns in staged files
if git diff --cached | grep -iE '(sk-ant-|bot[0-9]+:|reddit_client)' | grep -v '\.example'; then
    echo "ERROR: Possible API key detected in commit!"
    exit 1
fi
```

### 6.6 Telegram Bot Security

```python
ALLOWED_CHAT_IDS = set(
    int(x.strip())
    for x in os.getenv('TELEGRAM_ALLOWED_USERS', '').split(',')
    if x.strip()
)

def is_authorized(update) -> bool:
    """Only respond to whitelisted users."""
    chat_id = update.get('message', {}).get('chat', {}).get('id')
    if chat_id not in ALLOWED_CHAT_IDS:
        logger.warning(f"Unauthorized Telegram access attempt from chat_id: {chat_id}")
        return False
    return True
```

---

## 7. Data Storage

### 7.1 SQLite Schema — reddit_posts.db

```sql
CREATE TABLE posts (
    id TEXT PRIMARY KEY,           -- Reddit post ID
    subreddit TEXT NOT NULL,
    title TEXT NOT NULL,
    selftext TEXT,
    author TEXT,
    score INTEGER,
    num_comments INTEGER,
    upvote_ratio REAL,
    url TEXT,
    flair TEXT,
    created_utc TIMESTAMP,
    fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    analyzed BOOLEAN DEFAULT FALSE
);

CREATE TABLE comments (
    id TEXT PRIMARY KEY,           -- Reddit comment ID
    post_id TEXT NOT NULL,
    body TEXT,
    author TEXT,
    score INTEGER,
    created_utc TIMESTAMP,
    fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (post_id) REFERENCES posts(id)
);

CREATE TABLE post_tickers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id TEXT NOT NULL,
    ticker TEXT NOT NULL,
    mentioned_as TEXT,             -- "explicit", "company_name", "informal"
    priority TEXT,                 -- "holding", "watchlist", "other"
    FOREIGN KEY (post_id) REFERENCES posts(id)
);

CREATE TABLE post_analysis (
    post_id TEXT PRIMARY KEY,
    sentiment INTEGER,             -- -2 to +2
    confidence TEXT,               -- "low", "medium", "high"
    category TEXT,                 -- "DD", "news_reaction", "earnings", etc.
    analyzed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    model_used TEXT,               -- "haiku", "sonnet"
    tokens_in INTEGER,
    tokens_out INTEGER,
    FOREIGN KEY (post_id) REFERENCES posts(id)
);

CREATE TABLE ticker_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    date DATE NOT NULL,
    mention_count INTEGER,
    avg_7d REAL,
    sentiment_avg REAL,
    is_unusual BOOLEAN DEFAULT FALSE,
    UNIQUE(ticker, date)
);

CREATE TABLE narratives (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    date DATE NOT NULL,
    narrative_summary TEXT,
    post_count INTEGER,
    avg_sentiment REAL,
    subreddits TEXT,               -- JSON list of source subreddits
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for common queries
CREATE INDEX idx_posts_subreddit ON posts(subreddit);
CREATE INDEX idx_posts_created ON posts(created_utc);
CREATE INDEX idx_posts_analyzed ON posts(analyzed);
CREATE INDEX idx_tickers_ticker ON post_tickers(ticker);
CREATE INDEX idx_tickers_priority ON post_tickers(priority);
CREATE INDEX idx_stats_ticker_date ON ticker_stats(ticker, date);
```

### 7.2 Data Retention

| Data | Retention | Reason |
|------|----------|--------|
| Posts | 30 days | Rolling analysis window |
| Comments | 7 days | Only needed for recent context |
| Analysis | 30 days | Match post retention |
| Ticker stats | 90 days | Long-term trend tracking |
| Narratives | 90 days | Historical narrative tracking |
| Agent bus signals | 24 hours | Short-lived inter-agent comms |
| API audit log | 90 days | Cost tracking and debugging |
| Report archives | Indefinite | Historical briefings |

A nightly cleanup job should enforce these retention policies.

---

## 8. API Cost Model

### 8.1 Per-Run Costs

| Operation | Model | Est. Calls | Cost/Call | Total |
|-----------|-------|-----------|-----------|-------|
| Ticker extraction (batches of 10) | Haiku | ~30 | $0.0003 | $0.009 |
| Sentiment scoring (batched) | Haiku | ~30 | $0.0003 | $0.009 |
| Narrative summarization | Haiku | ~3 | $0.0005 | $0.0015 |
| Morning brief synthesis | Sonnet | 1 | $0.01 | $0.01 |
| **Total per run** | | | | **~$0.03** |

### 8.2 Daily Costs (5 runs/day)

| Component | Daily Cost |
|-----------|-----------|
| Street Ear (5 runs × $0.02) | $0.10 |
| Morning Brief synthesis (3 runs × $0.01) | $0.03 |
| **Daily total** | **~$0.13** |
| **Monthly total** | **~$4.00** |

### 8.3 Cost Safety Controls

```python
class CostTracker:
    """Track and limit Claude API spending."""

    def __init__(self, daily_cap: float = 1.00):
        self.daily_cap = daily_cap
        self.log_file = "data/api_log.jsonl"

    def can_make_call(self) -> bool:
        """Check if we're under the daily cap."""
        today_cost = self._get_today_total()
        return today_cost < self.daily_cap

    def log_call(self, model, tokens_in, tokens_out, cost):
        """Log every API call for auditing."""
        entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "model": model,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "cost_usd": cost,
        }
        with open(self.log_file, "a") as f:
            f.write(json.dumps(entry) + "\n")
```

---

## 9. Deployment

### 9.1 Local (Recommended for Weekend)

```bash
# Clone and setup
git clone [repo-url]
cd alphadesk
cp .env.example .env
# Edit .env with your actual keys

# Install dependencies
pip install -r requirements.txt

# Test individual agents
python -m src.street_ear.main
python -m src.portfolio_analyst.main

# Run combined morning brief
python -m src.shared.morning_brief --send

# Start the Telegram bot (long-running)
python -m src.shared.telegram_bot
```

### 9.2 Scheduled Execution (cron)

```bash
# crontab -e
# Street Ear: every 4 hours during market hours (6 AM - 10 PM PST)
0 6,10,14,18,22 * * * cd ~/alphadesk && python -m src.street_ear.main --send 2>> data/cron.log

# Morning Brief: 6:30 AM PST daily
30 6 * * * cd ~/alphadesk && python -m src.shared.morning_brief --send 2>> data/cron.log

# Portfolio Snapshot: 3 times daily
0 6,12,17 * * * cd ~/alphadesk && python -m src.portfolio_analyst.main --send 2>> data/cron.log

# Nightly cleanup: midnight
0 0 * * * cd ~/alphadesk && python -m src.utils.cleanup 2>> data/cron.log
```

### 9.3 Docker (Recommended for Office Laptop)

```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ src/
COPY config/ config/

# No .env in image — mount at runtime
# No data/ in image — mount as volume

CMD ["python", "-m", "src.shared.telegram_bot"]
```

```yaml
# docker-compose.yaml
version: '3.8'
services:
  alphadesk:
    build: .
    env_file: .env
    volumes:
      - ./data:/app/data
      - ./config:/app/config
    restart: unless-stopped
    # Network: only allow outbound to known APIs
    # (enforced via Docker network policy if needed)
```

---

## 10. Failure Modes

| Failure | Detection | Recovery |
|---------|-----------|----------|
| Reddit API down | HTTP error/timeout | Use cached data, note "stale data" in output |
| Claude API down | Anthropic SDK raises exception | Skip LLM analysis, show raw mention counts only |
| Claude API cost cap hit | CostTracker returns False | Skip LLM calls, log warning, send partial report |
| Telegram API down | HTTP error on send | Save report to data/reports/, retry in 5 min |
| yfinance down | Exception on price fetch | Use last known prices, note "prices may be stale" |
| SQLite corruption | Integrity check fails | Recreate tables, lose history (acceptable for MVP) |
| Invalid Reddit content | Sanitization catches it | Filter and continue, log sanitized content |
| Rate limit hit (any API) | 429 response | Exponential backoff with max 3 retries |

Every failure mode should log the error, attempt graceful degradation, and never crash the entire pipeline. A partial report is always better than no report.
