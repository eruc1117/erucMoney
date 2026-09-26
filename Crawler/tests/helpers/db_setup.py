"""
測試資料庫：建立 CRAWLER_TEST_DB 並把 schema 建到最新。

順序與正式環境一樣：
    1. Crawler/db/schema.sql                 股票基本表
    2. helpers/base_tables.sql               Node API 啟動時建的 user_news / saved_predictions / voting_results / news_features
    3. Server/migrations/*.sql               依檔名順序，記錄在 _migrations（與 Server/lib/migrate.js 相同規則）
    4. news_schema.NEW_TABLES + ALTER_USER_NEWS、repository 的 news_crawl_raw / stock_foreign_holding
只在名字以 _test 結尾的資料庫上動作。
"""
import os
from pathlib import Path

import psycopg2

import config

CRAWLER = Path(__file__).resolve().parent.parent.parent
SERVER_MIGRATIONS = CRAWLER.parent / 'Server' / 'migrations'
BASE_TABLES = Path(__file__).resolve().parent / 'base_tables.sql'

# 測試會寫到的表（truncate 順序無關：用 CASCADE）
WRITABLE_TABLES = [
    'stock_info', 'stock_daily_prices', 'stock_chip_analysis', 'stock_foreign_holding',
    'stock_dividend_result', 'stock_capital_reduction', 'stock_revenue_announce',
    'user_news', 'news_crawl_raw', 'news_features', 'news_price_link', 'news_daily_features',
    'instrument_alias', 'trading_calendar', 'saved_predictions', 'user_holdings', 'user_trades',
    'us_daily_prices', 'us_tickers', 'futures_daily', 'index_daily_prices',
    'voting_results', 'weekly_forecast_runs', 'weekly_forecasts', 'users',
]


def _guard():
    name = config.DB['dbname']
    if not name.endswith('_test'):
        raise RuntimeError(f'拒絕對非測試資料庫 {name} 動作')
    return name


def _admin_conn():
    return psycopg2.connect(host=config.DB['host'], port=config.DB['port'], dbname='postgres',
                            user=config.DB['user'], password=config.DB['password'], connect_timeout=5)


def ensure_database() -> str:
    """沒有就 CREATE DATABASE；回傳名字。"""
    name = _guard()
    conn = _admin_conn()
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT 1 FROM pg_database WHERE datname = %s', (name,))
            if not cur.fetchone():
                cur.execute(f'CREATE DATABASE "{name}"')
    finally:
        conn.close()
    return name


def _exec_sql(cur, sql: str) -> None:
    cur.execute(sql)


def apply_schema() -> None:
    _guard()
    from db.connection import get_conn
    from db import repository
    import news_schema
    with get_conn() as conn:
        with conn.cursor() as cur:
            _exec_sql(cur, (CRAWLER / 'db' / 'schema.sql').read_text(encoding='utf-8'))
            _exec_sql(cur, BASE_TABLES.read_text(encoding='utf-8'))
            cur.execute("""
                CREATE TABLE IF NOT EXISTS _migrations (
                    id SERIAL PRIMARY KEY, filename VARCHAR(200) UNIQUE NOT NULL,
                    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
            for f in sorted(SERVER_MIGRATIONS.glob('*.sql')):
                cur.execute('SELECT 1 FROM _migrations WHERE filename = %s', (f.name,))
                if cur.fetchone():
                    continue
                _exec_sql(cur, f.read_text(encoding='utf-8'))
                cur.execute('INSERT INTO _migrations (filename) VALUES (%s)', (f.name,))
            for stmt in news_schema.NEW_TABLES + news_schema.ALTER_USER_NEWS:
                cur.execute(stmt)
            repository._ensure_raw_table(cur)
            repository._ensure_foreign_holding_table(cur)
        conn.commit()


def truncate_all() -> None:
    _guard()
    from db.connection import get_conn
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE'")
            existing = {r[0] for r in cur.fetchall()}
            tables = [t for t in WRITABLE_TABLES if t in existing]
            if tables:
                cur.execute('TRUNCATE ' + ', '.join(f'"{t}"' for t in tables) + ' RESTART IDENTITY CASCADE')
        conn.commit()


def query(sql: str, params=None):
    from db.connection import get_conn
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall() if cur.description else None


def execute(sql: str, params=None) -> int:
    from db.connection import get_conn
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            n = cur.rowcount
        conn.commit()
    return n


def seed_stock(stock_id: str, name: str = None, industry: str = '半導體業', tracking: bool = True) -> None:
    execute("""INSERT INTO stock_info (stock_id, stock_name, market_type, industry_type, is_tracking)
               VALUES (%s, %s, 'twse', %s, %s) ON CONFLICT (stock_id) DO UPDATE SET
               stock_name = EXCLUDED.stock_name, industry_type = EXCLUDED.industry_type, is_tracking = EXCLUDED.is_tracking""",
            (stock_id, name or f'股票{stock_id}', industry, tracking))


def seed_prices(stock_id: str, dates: list, close: float = 100.0, step: float = 1.0) -> None:
    """每個日期一列，收盤依序 +step。"""
    for i, d in enumerate(dates):
        c = close + i * step
        execute("""INSERT INTO stock_daily_prices (stock_id, trade_date, open_price, high_price, low_price, close_price, volume)
                   VALUES (%s, %s, %s, %s, %s, %s, 1000) ON CONFLICT (stock_id, trade_date) DO UPDATE SET close_price = EXCLUDED.close_price""",
                (stock_id, d, c, c + 1, c - 1, c))
