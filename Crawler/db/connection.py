"""
PostgreSQL 連線管理
使用 psycopg2 SimpleConnectionPool，最小 1 條、最大 5 條連線。
"""

import logging
from contextlib import contextmanager

import psycopg2
from psycopg2 import pool

from config import DB

logger = logging.getLogger(__name__)

_pool: pool.SimpleConnectionPool | None = None


def get_pool() -> pool.SimpleConnectionPool:
    """取得（或初始化）連線池"""
    global _pool
    if _pool is None:
        _pool = pool.SimpleConnectionPool(
            minconn=1,
            maxconn=5,
            host=DB["host"],
            port=DB["port"],
            dbname=DB["dbname"],
            user=DB["user"],
            password=DB["password"],
        )
        logger.info("PostgreSQL 連線池已建立（%s:%s/%s）", DB["host"], DB["port"], DB["dbname"])
    return _pool


@contextmanager
def get_conn():
    """
    從連線池借出一條連線，使用 with 語法自動歸還。

    用法：
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(...)
            conn.commit()
    """
    p = get_pool()
    conn = p.getconn()
    try:
        yield conn
    except Exception:
        conn.rollback()
        raise
    finally:
        p.putconn(conn)


def close_pool():
    """關閉所有連線（程式結束時呼叫）"""
    global _pool
    if _pool:
        _pool.closeall()
        _pool = None
        logger.info("PostgreSQL 連線池已關閉")
