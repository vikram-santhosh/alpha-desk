"""Shared MySQL connection pool for AlphaDesk."""
from __future__ import annotations

import contextvars
import os
import re
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from src.utils.logger import get_logger

log = get_logger(__name__)

try:
    import pymysql
    from pymysql.cursors import DictCursor
    from pymysql.err import MySQLError, OperationalError, ProgrammingError
except Exception:  # pragma: no cover - exercised when requirements are absent.
    pymysql = None  # type: ignore[assignment]
    DictCursor = None  # type: ignore[assignment]

    class MySQLError(RuntimeError):
        pass

    class OperationalError(MySQLError):
        pass

    class ProgrammingError(MySQLError):
        pass

try:
    from dbutils.pooled_db import PooledDB

    _HAVE_DBUTILS = True
except Exception:  # pragma: no cover - optional dependency fallback.
    PooledDB = None  # type: ignore[assignment]
    _HAVE_DBUTILS = False


DBError = MySQLError
QMARK_RE = re.compile(r"\?")

_schema_override: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "alphadesk_schema_override", default=None
)
_pool = None
_pool_lock = threading.Lock()


def _config() -> dict[str, Any]:
    return {
        "host": os.environ.get("ALPHADESK_DB_HOST", "127.0.0.1"),
        "port": int(os.environ.get("ALPHADESK_DB_PORT", "3306")),
        "db": os.environ.get("ALPHADESK_DB_NAME", "alphadesk"),
        "user": os.environ.get("ALPHADESK_DB_USER", "alphadesk"),
        "password": os.environ.get("ALPHADESK_DB_PASSWORD", ""),
        "pool_size": int(os.environ.get("ALPHADESK_DB_POOL_SIZE", "5")),
        # Fail fast on an unreachable MySQL so DB-backed endpoints return an error
        # quickly instead of hanging (which surfaces as a client-side timeout).
        "connect_timeout": int(os.environ.get("ALPHADESK_DB_CONNECT_TIMEOUT", "5")),
    }


def get_schema_name() -> str:
    return _schema_override.get() or os.environ.get("ALPHADESK_DB_NAME", "alphadesk")


def set_schema_override(name: str) -> contextvars.Token:
    return _schema_override.set(name)


def clear_schema_override(token: contextvars.Token) -> None:
    _schema_override.reset(token)


def reset_pool() -> None:
    global _pool
    with _pool_lock:
        _pool = None


# ── SQLite fallback ──────────────────────────────────────────────────────────
# When no MySQL client is installed (typical local dev), persist to a local
# SQLite file instead of failing. MySQL stays the default whenever PyMySQL is
# available, so production behavior is unchanged. Override with
# ALPHADESK_DB_BACKEND=sqlite|mysql|auto.

def _use_sqlite() -> bool:
    backend = os.environ.get("ALPHADESK_DB_BACKEND", "auto").strip().lower()
    if backend == "sqlite":
        return True
    if backend == "mysql":
        return False
    return pymysql is None


def _sqlite_path() -> Path:
    return Path(os.environ.get("ALPHADESK_DATA_DIR", "data")) / "alphadesk.db"


def _sqlite_connect() -> "sqlite3.Connection":
    path = _sqlite_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


class _SqliteCursor:
    """Adapts a sqlite3 cursor to the pymysql-DictCursor surface the stores use:
    rewrites %s placeholders to ?, and supports `with conn.cursor() as cur`."""

    def __init__(self, cur: "sqlite3.Cursor") -> None:
        self._cur = cur

    def __enter__(self) -> "_SqliteCursor":
        return self

    def __exit__(self, *_exc: Any) -> bool:
        self._cur.close()
        return False

    @staticmethod
    def _prep(sql: str) -> str:
        return sql.replace("%s", "?")

    def execute(self, sql: str, params: Any = ()) -> "_SqliteCursor":
        self._cur.execute(self._prep(sql), tuple(params or ()))
        return self

    def executemany(self, sql: str, seq_params: Any) -> "_SqliteCursor":
        self._cur.executemany(self._prep(sql), [tuple(p) for p in seq_params])
        return self

    def fetchone(self) -> Any:
        return self._cur.fetchone()

    def fetchall(self) -> list[Any]:
        return list(self._cur.fetchall())

    @property
    def lastrowid(self) -> Any:
        return self._cur.lastrowid

    @property
    def rowcount(self) -> int:
        return int(self._cur.rowcount)

    def close(self) -> None:
        self._cur.close()


class _SqliteConn:
    def __init__(self, conn: "sqlite3.Connection") -> None:
        self._conn = conn

    def cursor(self) -> _SqliteCursor:
        return _SqliteCursor(self._conn.cursor())

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()

    def close(self) -> None:
        self._conn.close()


def _require_pymysql() -> Any:
    if pymysql is None:
        raise DBError("PyMySQL is not installed. Run `python -m pip install -r requirements.txt`.")
    return pymysql


def _build_pool() -> Any:
    mysql = _require_pymysql()
    cfg = _config()
    if _HAVE_DBUTILS and PooledDB is not None:
        return PooledDB(
            creator=mysql,
            maxconnections=cfg["pool_size"],
            mincached=1,
            blocking=True,
            ping=1,
            host=cfg["host"],
            port=cfg["port"],
            user=cfg["user"],
            password=cfg["password"],
            database=cfg["db"],
            charset="utf8mb4",
            cursorclass=DictCursor,
            autocommit=False,
            connect_timeout=cfg["connect_timeout"],
        )
    log.warning("DBUtils not installed; using unpooled per-call MySQL connections")
    return None


def _raw_connection():
    global _pool
    mysql = _require_pymysql()
    cfg = _config()
    if _HAVE_DBUTILS:
        if _pool is None:
            with _pool_lock:
                if _pool is None:
                    _pool = _build_pool()
        return _pool.connection()
    return mysql.connect(
        host=cfg["host"],
        port=cfg["port"],
        user=cfg["user"],
        password=cfg["password"],
        database=cfg["db"],
        charset="utf8mb4",
        cursorclass=DictCursor,
        autocommit=False,
        connect_timeout=cfg["connect_timeout"],
    )


@contextmanager
def get_conn() -> Iterator[Any]:
    if _use_sqlite():
        conn = _SqliteConn(_sqlite_connect())
        try:
            yield conn
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            raise
        finally:
            conn.close()
        return
    conn = _raw_connection()
    schema = _schema_override.get()
    try:
        if schema:
            with conn.cursor() as cur:
                cur.execute(f"USE `{schema}`")
        yield conn
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        conn.close()


@contextmanager
def transaction() -> Iterator[Any]:
    with get_conn() as conn:
        yield conn


def _translate(sql: str) -> str:
    if "?" not in sql:
        return sql
    sql = sql.replace("%", "%%")
    return QMARK_RE.sub("%s", sql)


def query_all(sql: str, params: Any = None) -> list[dict[str, Any]]:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(_translate(sql), tuple(params or ()))
        return list(cur.fetchall())


def query_one(sql: str, params: Any = None) -> dict[str, Any] | None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(_translate(sql), tuple(params or ()))
        return cur.fetchone()


def execute(sql: str, params: Any = None) -> int:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(_translate(sql), tuple(params or ()))
        return int(cur.rowcount)


def execute_many(sql: str, seq_params: Any) -> int:
    with get_conn() as conn, conn.cursor() as cur:
        cur.executemany(_translate(sql), [tuple(p) for p in seq_params])
        return int(cur.rowcount)


executeMany = execute_many
