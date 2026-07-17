"""MySQL schema bootstrap for AlphaDesk (with a SQLite fallback)."""
from __future__ import annotations

import re
import sqlite3

from src.shared.db import _config, _require_pymysql, _sqlite_path, _use_sqlite

TICKER = "VARCHAR(24) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin"

DDL_TABLES = [
    f"""
    CREATE TABLE IF NOT EXISTS holdings (
      ticker {TICKER} PRIMARY KEY,
      tracking_since VARCHAR(32),
      thesis LONGTEXT,
      thesis_status VARCHAR(64),
      category VARCHAR(64),
      updated_at VARCHAR(40)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    f"""
    CREATE TABLE IF NOT EXISTS holding_snapshots (
      ticker {TICKER} NOT NULL,
      date VARCHAR(32) NOT NULL,
      price DOUBLE,
      change_pct DOUBLE,
      thesis_status VARCHAR(64),
      notes LONGTEXT,
      PRIMARY KEY (ticker, date),
      KEY idx_snapshots_ticker_date (ticker, date)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS macro_theses (
      title VARCHAR(255) PRIMARY KEY,
      status VARCHAR(64),
      description LONGTEXT,
      affected_tickers LONGTEXT,
      evidence LONGTEXT,
      updated_at VARCHAR(40)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    f"""
    CREATE TABLE IF NOT EXISTS conviction_list (
      ticker {TICKER} PRIMARY KEY,
      thesis LONGTEXT,
      conviction VARCHAR(32),
      source VARCHAR(128),
      analyst_scores LONGTEXT,
      added_at VARCHAR(40),
      last_updated VARCHAR(40)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    f"""
    CREATE TABLE IF NOT EXISTS moonshot_list (
      ticker {TICKER} PRIMARY KEY,
      thesis LONGTEXT,
      conviction VARCHAR(32),
      source VARCHAR(128),
      last_months_increment_list LONGTEXT,
      added_at VARCHAR(40),
      last_updated VARCHAR(40)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    f"""
    CREATE TABLE IF NOT EXISTS strategy_flags (
      id BIGINT AUTO_INCREMENT PRIMARY KEY,
      ticker {TICKER} NOT NULL,
      flag_type VARCHAR(128) NOT NULL,
      flag_date VARCHAR(32) NOT NULL,
      description LONGTEXT,
      trigger_condition LONGTEXT,
      resolved TINYINT(1) NOT NULL DEFAULT 0,
      KEY idx_strategy_flags_active (ticker, resolved)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    f"""
    CREATE TABLE IF NOT EXISTS superinvestor_positions (
      investor VARCHAR(128) NOT NULL,
      ticker {TICKER} NOT NULL,
      shares DOUBLE,
      value_usd DOUBLE,
      portfolio_pct DOUBLE,
      filing_date VARCHAR(32),
      updated_at VARCHAR(40),
      PRIMARY KEY (investor, ticker)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    f"""
    CREATE TABLE IF NOT EXISTS earnings_calls (
      ticker {TICKER} NOT NULL,
      quarter VARCHAR(32) NOT NULL,
      call_date VARCHAR(32),
      summary LONGTEXT,
      guidance LONGTEXT,
      cross_mentions LONGTEXT,
      PRIMARY KEY (ticker, quarter),
      KEY idx_earnings_ticker (ticker)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    f"""
    CREATE TABLE IF NOT EXISTS cross_mentions (
      ticker {TICKER} NOT NULL,
      mentioned_ticker {TICKER} NOT NULL,
      source VARCHAR(128) NOT NULL,
      date VARCHAR(32) NOT NULL,
      context LONGTEXT,
      PRIMARY KEY (ticker, mentioned_ticker, source, date),
      KEY idx_cross_mentions_mentioned (mentioned_ticker)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS prediction_markets (
      id VARCHAR(255) PRIMARY KEY,
      date VARCHAR(32) NOT NULL,
      source VARCHAR(64),
      question LONGTEXT,
      probability DOUBLE,
      metadata LONGTEXT,
      KEY idx_prediction_date (date)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS daily_briefs (
      date VARCHAR(32) PRIMARY KEY,
      macro_summary LONGTEXT,
      portfolio_actions LONGTEXT,
      conviction_changes LONGTEXT,
      moonshot_changes LONGTEXT,
      created_at VARCHAR(40)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS daily_snapshots (
      date VARCHAR(32) PRIMARY KEY,
      snapshot_data LONGTEXT NOT NULL,
      created_at VARCHAR(40),
      KEY idx_daily_snapshots_date (date)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS run_snapshots (
      run_id VARCHAR(80) PRIMARY KEY,
      run_type VARCHAR(32) NOT NULL,
      date VARCHAR(32) NOT NULL,
      snapshot_data LONGTEXT NOT NULL,
      delta LONGTEXT,
      run_cost DOUBLE DEFAULT 0,
      run_duration DOUBLE DEFAULT 0,
      last_consumed_signal_id BIGINT DEFAULT 0,
      created_at VARCHAR(40),
      KEY idx_run_snapshots_date (date),
      KEY idx_run_snapshots_type (run_type)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    f"""
    CREATE TABLE IF NOT EXISTS recommendation_outcomes (
      id BIGINT AUTO_INCREMENT PRIMARY KEY,
      ticker {TICKER} NOT NULL,
      recommendation_date VARCHAR(32) NOT NULL,
      action VARCHAR(32),
      status VARCHAR(64),
      outcome LONGTEXT,
      created_at VARCHAR(40),
      KEY idx_rec_outcomes_ticker (ticker),
      KEY idx_rec_outcomes_status (status)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS thesis_actions (
      id BIGINT AUTO_INCREMENT PRIMARY KEY,
      thesis VARCHAR(255) NOT NULL,
      action VARCHAR(64) NOT NULL,
      action_date VARCHAR(32) NOT NULL,
      details LONGTEXT
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    f"""
    CREATE TABLE IF NOT EXISTS mandate_breaches (
      ticker {TICKER} NOT NULL,
      breach_type VARCHAR(128) NOT NULL,
      severity VARCHAR(32),
      detail LONGTEXT,
      created_at VARCHAR(40),
      updated_at VARCHAR(40),
      PRIMARY KEY (ticker, breach_type)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    f"""
    CREATE TABLE IF NOT EXISTS generated_ideas (
      id BIGINT AUTO_INCREMENT PRIMARY KEY,
      ticker {TICKER},
      title VARCHAR(255),
      thesis LONGTEXT,
      metadata LONGTEXT,
      created_at VARCHAR(40)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS signals (
      id BIGINT AUTO_INCREMENT PRIMARY KEY,
      timestamp VARCHAR(40) NOT NULL,
      signal_type VARCHAR(128) NOT NULL,
      source_agent VARCHAR(128) NOT NULL,
      payload LONGTEXT NOT NULL,
      consumed TINYINT(1) DEFAULT 0,
      KEY idx_signals_type_consumed (signal_type, consumed)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS api_costs (
      id BIGINT AUTO_INCREMENT PRIMARY KEY,
      timestamp VARCHAR(40) NOT NULL,
      date VARCHAR(32) NOT NULL,
      agent VARCHAR(128) NOT NULL,
      input_tokens BIGINT NOT NULL,
      output_tokens BIGINT NOT NULL,
      cost_usd DOUBLE NOT NULL,
      run_id VARCHAR(80),
      KEY idx_api_costs_date (date),
      KEY idx_api_costs_run_id (run_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS narrative_propagation (
      id BIGINT AUTO_INCREMENT PRIMARY KEY,
      narrative LONGTEXT NOT NULL,
      first_seen_source VARCHAR(255) NOT NULL,
      first_seen_date VARCHAR(32) NOT NULL,
      first_seen_detail LONGTEXT NOT NULL,
      current_stage VARCHAR(64) NOT NULL DEFAULT 'expert',
      affected_tickers LONGTEXT NOT NULL,
      stage_history LONGTEXT NOT NULL,
      confidence DOUBLE DEFAULT 0.5,
      last_updated VARCHAR(40) NOT NULL,
      KEY idx_narrative_stage (current_stage),
      KEY idx_narrative_updated (last_updated)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    f"""
    CREATE TABLE IF NOT EXISTS signal_outcomes (
      id BIGINT AUTO_INCREMENT PRIMARY KEY,
      signal_id BIGINT NOT NULL,
      signal_type VARCHAR(128) NOT NULL,
      ticker {TICKER} NOT NULL,
      signal_date VARCHAR(32) NOT NULL,
      price_at_signal DOUBLE,
      price_after_1d DOUBLE,
      price_after_5d DOUBLE,
      price_after_20d DOUBLE,
      outcome VARCHAR(64),
      created_at VARCHAR(40) NOT NULL,
      KEY idx_signal_outcomes_ticker (ticker),
      KEY idx_signal_outcomes_date (signal_date)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS source_reliability (
      id BIGINT AUTO_INCREMENT PRIMARY KEY,
      source_name VARCHAR(255) NOT NULL,
      source_platform VARCHAR(128) NOT NULL,
      total_signals BIGINT DEFAULT 0,
      correct_signals BIGINT DEFAULT 0,
      hit_rate DOUBLE DEFAULT 0,
      avg_lead_time_hours DOUBLE,
      last_updated VARCHAR(40) NOT NULL,
      UNIQUE KEY uq_source_platform (source_name, source_platform),
      KEY idx_source_reliability_platform (source_platform)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    f"""
    CREATE TABLE IF NOT EXISTS street_mention_history (
      id BIGINT AUTO_INCREMENT PRIMARY KEY,
      ticker {TICKER} NOT NULL,
      date VARCHAR(32) NOT NULL,
      mention_count BIGINT DEFAULT 0,
      sentiment DOUBLE,
      metadata LONGTEXT,
      UNIQUE KEY uq_street_ticker_date (ticker, date),
      KEY idx_street_mention_ticker_date (ticker, date)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    f"""
    CREATE TABLE IF NOT EXISTS street_narratives (
      id BIGINT AUTO_INCREMENT PRIMARY KEY,
      ticker {TICKER} NOT NULL,
      date VARCHAR(32) NOT NULL,
      narrative LONGTEXT,
      sentiment DOUBLE,
      KEY idx_street_narratives_ticker_date (ticker, date)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS substack_theses (
      id BIGINT AUTO_INCREMENT PRIMARY KEY,
      date VARCHAR(32) NOT NULL,
      title VARCHAR(255),
      author VARCHAR(255),
      summary LONGTEXT,
      affected_tickers LONGTEXT,
      metadata LONGTEXT,
      KEY idx_substack_theses_date (date)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS substack_macro_signals (
      id BIGINT AUTO_INCREMENT PRIMARY KEY,
      date VARCHAR(32) NOT NULL,
      title VARCHAR(255),
      summary LONGTEXT,
      metadata LONGTEXT,
      KEY idx_substack_macro_signals_date (date)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    f"""
    CREATE TABLE IF NOT EXISTS youtube_mention_history (
      id BIGINT AUTO_INCREMENT PRIMARY KEY,
      ticker {TICKER} NOT NULL,
      date VARCHAR(32) NOT NULL,
      mention_count BIGINT DEFAULT 0,
      views BIGINT DEFAULT 0,
      sentiment DOUBLE,
      metadata LONGTEXT,
      UNIQUE KEY uq_youtube_ticker_date (ticker, date),
      KEY idx_youtube_mention_ticker_date (ticker, date)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    f"""
    CREATE TABLE IF NOT EXISTS youtube_theses (
      id BIGINT AUTO_INCREMENT PRIMARY KEY,
      ticker {TICKER},
      date VARCHAR(32) NOT NULL,
      title VARCHAR(255),
      channel VARCHAR(255),
      summary LONGTEXT,
      metadata LONGTEXT,
      KEY idx_youtube_theses_ticker_date (ticker, date)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS channel_view_history (
      id BIGINT AUTO_INCREMENT PRIMARY KEY,
      channel_name VARCHAR(255) NOT NULL,
      date VARCHAR(32) NOT NULL,
      views BIGINT DEFAULT 0,
      UNIQUE KEY uq_channel_date (channel_name, date),
      KEY idx_channel_views (channel_name, date)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS sector_articles (
      id BIGINT AUTO_INCREMENT PRIMARY KEY,
      title VARCHAR(512) NOT NULL,
      url VARCHAR(1024),
      sector VARCHAR(128),
      published_at VARCHAR(40),
      summary LONGTEXT,
      metadata LONGTEXT,
      KEY idx_sector_articles_title (title(255))
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS snapshots (
      snapshot_id VARCHAR(80) PRIMARY KEY,
      created_at VARCHAR(40) NOT NULL,
      weights_version VARCHAR(80) NOT NULL,
      tickers LONGTEXT NOT NULL,
      signals LONGTEXT NOT NULL,
      scores LONGTEXT
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS idea_scout_runs (
      id BIGINT AUTO_INCREMENT PRIMARY KEY,
      created_at VARCHAR(40) NOT NULL,
      mode VARCHAR(32) NOT NULL,
      as_of VARCHAR(32) NOT NULL,
      idea_count BIGINT NOT NULL,
      cost_usd DOUBLE NOT NULL,
      payload LONGTEXT NOT NULL,
      KEY idx_idea_scout_runs_mode_created (mode, created_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    f"""
    CREATE TABLE IF NOT EXISTS council_runs (
      id BIGINT AUTO_INCREMENT PRIMARY KEY,
      created_at VARCHAR(40) NOT NULL,
      ticker {TICKER} NOT NULL,
      models LONGTEXT NOT NULL,
      panel_count BIGINT NOT NULL,
      cost_usd DOUBLE NOT NULL,
      execution_mode VARCHAR(64) NOT NULL,
      payload LONGTEXT NOT NULL,
      KEY idx_council_runs_ticker_created (ticker, created_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS daily_brief_runs (
      id BIGINT AUTO_INCREMENT PRIMARY KEY,
      created_at VARCHAR(40) NOT NULL,
      run_type VARCHAR(32) NOT NULL,
      as_of VARCHAR(32) NOT NULL,
      run_cost DOUBLE NOT NULL DEFAULT 0,
      payload LONGTEXT NOT NULL,
      KEY idx_brief_run_type_created (run_type, created_at),
      KEY idx_brief_created (created_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS retrospectives (
      id BIGINT AUTO_INCREMENT PRIMARY KEY,
      date VARCHAR(32) NOT NULL,
      content LONGTEXT NOT NULL,
      metadata LONGTEXT,
      created_at VARCHAR(40) NOT NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS user_feedback (
      id BIGINT AUTO_INCREMENT PRIMARY KEY,
      created_at VARCHAR(40) NOT NULL,
      target VARCHAR(255),
      rating VARCHAR(64),
      feedback LONGTEXT
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS user_preferences (
      id BIGINT AUTO_INCREMENT PRIMARY KEY,
      preference_key VARCHAR(255) NOT NULL,
      preference_value LONGTEXT,
      updated_at VARCHAR(40),
      UNIQUE KEY uq_preference_key (preference_key)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS chat_sessions (
      id BIGINT AUTO_INCREMENT PRIMARY KEY,
      chat_id VARCHAR(128) NOT NULL,
      updated_at VARCHAR(40) NOT NULL,
      brief_context LONGTEXT,
      holdings_context LONGTEXT,
      KEY idx_chat_sessions_chat_id (chat_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS reasoning_journal (
      id BIGINT AUTO_INCREMENT PRIMARY KEY,
      date VARCHAR(32) NOT NULL,
      topic VARCHAR(255),
      entry LONGTEXT NOT NULL,
      metadata LONGTEXT,
      created_at VARCHAR(40)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS calibration_profiles (
      id BIGINT AUTO_INCREMENT PRIMARY KEY,
      profile_key VARCHAR(255) NOT NULL,
      profile LONGTEXT NOT NULL,
      updated_at VARCHAR(40),
      UNIQUE KEY uq_profile_key (profile_key)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    f"""
    CREATE TABLE IF NOT EXISTS catalysts (
      id BIGINT AUTO_INCREMENT PRIMARY KEY,
      ticker {TICKER} NOT NULL,
      event_type VARCHAR(128) NOT NULL,
      event_date VARCHAR(32) NOT NULL,
      description LONGTEXT,
      source VARCHAR(128),
      created_at VARCHAR(40),
      UNIQUE KEY uq_catalyst (ticker, event_type, event_date)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS superinvestor_filings (
      id BIGINT AUTO_INCREMENT PRIMARY KEY,
      investor VARCHAR(255) NOT NULL,
      filing_date VARCHAR(32) NOT NULL,
      payload LONGTEXT NOT NULL,
      created_at VARCHAR(40),
      UNIQUE KEY uq_investor_filing (investor, filing_date)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS deployment_runs (
      id BIGINT AUTO_INCREMENT PRIMARY KEY,
      created_at VARCHAR(40) NOT NULL,
      as_of VARCHAR(32) NOT NULL,
      capital DOUBLE NOT NULL DEFAULT 0,
      run_cost DOUBLE NOT NULL DEFAULT 0,
      payload LONGTEXT NOT NULL,
      KEY idx_deployment_created (created_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
]


def _sqlite_translate(ddl: str) -> tuple[str, list[str]]:
    """Translate a MySQL CREATE TABLE into SQLite-compatible DDL.

    SQLite is lenient on column *types* (affinity), so the work is: drop the
    MySQL-only options it rejects (ENGINE/CHARSET/COLLATE/AUTO_INCREMENT), and
    pull inline secondary `KEY name (cols)` indexes out into CREATE INDEX
    statements (SQLite can't declare them inside CREATE TABLE).
    """
    match = re.search(r"CREATE TABLE IF NOT EXISTS (\w+)", ddl)
    table = match.group(1) if match else "tbl"
    sql = ddl

    # Column list that tolerates one level of nesting, e.g. prefix lengths
    # like `title(255)` in `KEY idx (title(255))`.
    cols_pat = r"(?:[^()]|\([^)]*\))*"

    # Pull out non-unique secondary indexes (not UNIQUE KEY, not PRIMARY KEY).
    indexes: list[str] = []
    for name, cols in re.findall(r"(?<!UNIQUE )\bKEY (\w+) \((" + cols_pat + r")\)", sql):
        clean = re.sub(r"\(\d+\)", "", cols)  # strip prefix lengths like title(255)
        indexes.append(f"CREATE INDEX IF NOT EXISTS {name} ON {table} ({clean})")
    sql = re.sub(r",?\s*(?<!UNIQUE )\bKEY \w+ \(" + cols_pat + r"\)", "", sql)

    # UNIQUE KEY name (cols) -> table-level UNIQUE (cols)
    sql = re.sub(
        r"UNIQUE KEY \w+ \((" + cols_pat + r")\)",
        lambda m: "UNIQUE (" + re.sub(r"\(\d+\)", "", m.group(1)) + ")",
        sql,
    )

    # Drop MySQL-only options SQLite rejects.
    sql = re.sub(r"\s+CHARACTER SET \w+", "", sql)
    sql = re.sub(r"\s+COLLATE \w+", "", sql)
    sql = re.sub(r"\)\s*ENGINE=\w+\s+DEFAULT CHARSET=\w+", ")", sql)
    sql = re.sub(r"BIGINT AUTO_INCREMENT PRIMARY KEY", "INTEGER PRIMARY KEY", sql)
    sql = re.sub(r"\s+AUTO_INCREMENT", "", sql)
    sql = re.sub(r",(\s*)\)", r"\1)", sql)  # tidy dangling commas

    return sql.strip(), indexes


def _init_sqlite_schema() -> None:
    path = _sqlite_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    try:
        for ddl in DDL_TABLES:
            create, indexes = _sqlite_translate(ddl)
            conn.execute(create)
            for index in indexes:
                conn.execute(index)
        conn.commit()
    finally:
        conn.close()


def init_schema(target_schema: str | None = None) -> None:
    if _use_sqlite():
        _init_sqlite_schema()
        return
    mysql = _require_pymysql()
    cfg = _config()
    schema = target_schema or cfg["db"]
    root = mysql.connect(
        host=cfg["host"],
        port=cfg["port"],
        user=cfg["user"],
        password=cfg["password"],
        charset="utf8mb4",
        autocommit=True,
        connect_timeout=cfg["connect_timeout"],
    )
    try:
        with root.cursor() as cur:
            cur.execute(f"CREATE DATABASE IF NOT EXISTS `{schema}`")
            cur.execute(f"ALTER DATABASE `{schema}` COLLATE utf8mb4_ai_ci")
            cur.execute(f"USE `{schema}`")
            for ddl in DDL_TABLES:
                cur.execute(ddl)
    finally:
        root.close()
