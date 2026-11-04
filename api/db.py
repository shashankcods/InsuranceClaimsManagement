"""Database access: pooled connections, query helpers, MySQL error -> HTTP mapping."""
import os
from contextlib import contextmanager
from pathlib import Path

import mysql.connector
from mysql.connector import pooling

ROOT = Path(__file__).resolve().parent.parent


def _load_env():
    env = {}
    f = ROOT / ".env"
    if f.exists():
        for line in f.read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return {k: os.environ.get(k, v) for k, v in env.items()}


ENV = _load_env()
_pool = None


def get_pool():
    """One pool per process. autocommit=True: the stored procedures own their transactions."""
    global _pool
    if _pool is None:
        _pool = pooling.MySQLConnectionPool(
            pool_name="insurance_pool", pool_size=int(ENV.get("DB_POOL_SIZE", 10)), pool_reset_session=True,
            host=ENV.get("DB_HOST", "127.0.0.1"), port=int(ENV.get("DB_PORT", 3306)),
            user=ENV["DB_USER"], password=ENV["DB_PASSWORD"],
            database=os.environ.get("DB_NAME", ENV.get("DB_NAME")),
            autocommit=True, charset="utf8mb4", collation="utf8mb4_0900_ai_ci")
    return _pool


@contextmanager
def connection():
    conn = get_pool().get_connection()
    try:
        yield conn
    finally:
        conn.close()  # returns it to the pool


def query(sql, params=None):
    with connection() as conn:
        cur = conn.cursor(dictionary=True)
        cur.execute(sql, params or ())
        return cur.fetchall()


def query_one(sql, params=None):
    rows = query(sql, params)
    return rows[0] if rows else None


def execute(sql, params=None):
    """Run one DML statement; returns (rowcount, lastrowid)."""
    with connection() as conn:
        cur = conn.cursor()
        cur.execute(sql, params or ())
        return cur.rowcount, cur.lastrowid


def callproc(name, args):
    """Call a stored procedure; returns the args tuple with OUT values filled in."""
    with connection() as conn:
        cur = conn.cursor()
        result = cur.callproc(name, args)
        for _ in cur.stored_results():
            pass
        return result


# ---------------- error mapping (design doc section 8) ----------------
CONFLICT = {1644, 1062, 1451, 1452, 1213, 1205}  # our SIGNALs, duplicate key, FK violations, deadlock / lock timeout (retry)
UNPROCESSABLE = {3819, 1048, 1366, 1292, 1406, 1364, 1265}  # CHECK, NOT NULL, bad values


def http_status_for(err: mysql.connector.Error) -> int:
    if err.errno in CONFLICT:
        return 409
    if err.errno in UNPROCESSABLE:
        return 422
    return 500
