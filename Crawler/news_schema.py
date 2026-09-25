"""
新聞資料表結構（Iteration 38 階段 2）
──────────────────────────────────────
把方案文件的 11 張表落到專案既有的 PostgreSQL（不另開 Parquet / SQLite）。
只新增，不改既有欄位語意；全部 IF NOT EXISTS，可重複執行。

新表：
    instrument_alias     標的別名（台積電 / 台積 / TSMC → 2330）
    trading_calendar     兩市交易日與收盤時間，日級對齊用
    news_price_link      新聞 → (ticker, market, effective_date)，方案第 10 表
    news_daily_features  每檔每個 effective_date 的新聞特徵（歷史可回算，取代只寫當天的 news_features）
    news_llm_feature     LLM 結構化抽取結果（news_pilot/scripts/05_load_db.py 寫入）
既有表加欄位：
    user_news            source_url / published_at_utc / language / scope / source_tier /
                         content_kind / dedup_group_id / is_canonical

用法：
    python news_schema.py                # 全部
    python news_schema.py --tables-only  # 只建新表，不 ALTER user_news（回填進行中時用）
"""

import argparse
import logging

from db.connection import get_conn

logger = logging.getLogger(__name__)

NEW_TABLES = [
    """
    CREATE TABLE IF NOT EXISTS instrument_alias (
        alias       TEXT NOT NULL,
        ticker      TEXT NOT NULL,           -- 台股純代碼（2330）；美股大寫（NVDA）
        market      TEXT NOT NULL DEFAULT 'TW',
        language    TEXT NOT NULL DEFAULT 'zh',
        alias_type  TEXT NOT NULL DEFAULT 'full_name',  -- full_name / short_name / brand / product / chairman / code
        priority    SMALLINT NOT NULL DEFAULT 1,        -- 越小越可信
        is_active   BOOLEAN NOT NULL DEFAULT TRUE,
        PRIMARY KEY (alias, ticker)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_instrument_alias_ticker ON instrument_alias (ticker)",
    """
    CREATE TABLE IF NOT EXISTS trading_calendar (
        market            TEXT NOT NULL,     -- TW / US
        trade_date        DATE NOT NULL,
        is_open           BOOLEAN NOT NULL DEFAULT TRUE,
        close_time_local  TIME NOT NULL,     -- TW 13:30 / US 16:00
        PRIMARY KEY (market, trade_date)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS news_price_link (
        news_id         INTEGER NOT NULL REFERENCES user_news(id) ON DELETE CASCADE,
        ticker          TEXT NOT NULL,
        market          TEXT NOT NULL,
        published_at    TIMESTAMP NOT NULL,  -- 本地時間（與 user_news.submitted_at 同）
        effective_date  DATE NOT NULL,       -- 新聞可影響的第一個收盤日
        lag_days        SMALLINT NOT NULL,   -- effective_date − 發布日
        link_reason     TEXT NOT NULL,       -- direct_ticker / sector / scope_global
        PRIMARY KEY (news_id, ticker, market)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_news_price_link_ticker_date ON news_price_link (ticker, effective_date)",
    """
    CREATE TABLE IF NOT EXISTS news_daily_features (
        stock_id           TEXT NOT NULL,
        effective_date     DATE NOT NULL,
        n_articles         INTEGER NOT NULL DEFAULT 0,   -- 本股當日新聞數
        sentiment_mean     REAL,                          -- 本股新聞字典情緒均值（無新聞 NULL）
        sentiment_sum      REAL,
        n_pos              INTEGER NOT NULL DEFAULT 0,
        n_neg              INTEGER NOT NULL DEFAULT 0,
        strong_kw_hit      INTEGER NOT NULL DEFAULT 0,   -- 強效關鍵字正負淨命中
        market_n_articles  INTEGER NOT NULL DEFAULT 0,   -- 全市場當日新聞數
        market_sentiment   REAL,                          -- 全市場當日情緒均值
        computed_at        TIMESTAMP NOT NULL DEFAULT NOW(),
        PRIMARY KEY (stock_id, effective_date)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS news_llm_feature (
        news_id           INTEGER NOT NULL REFERENCES user_news(id) ON DELETE CASCADE,
        model             TEXT NOT NULL,
        event_type        TEXT NOT NULL,
        direction         TEXT NOT NULL,
        magnitude         SMALLINT NOT NULL,
        is_expected       BOOLEAN NOT NULL,
        affected_tickers  TEXT[] NOT NULL DEFAULT '{}',
        affected_sectors  TEXT[] NOT NULL DEFAULT '{}',
        scope             TEXT NOT NULL,
        confidence        REAL,
        rationale         TEXT,
        raw_json          JSONB,
        extracted_at      TIMESTAMP NOT NULL DEFAULT NOW(),
        PRIMARY KEY (news_id, model)
    )
    """,
]

ALTER_USER_NEWS = [
    "ALTER TABLE user_news ADD COLUMN IF NOT EXISTS source_url       TEXT",
    "ALTER TABLE user_news ADD COLUMN IF NOT EXISTS published_at_utc TIMESTAMPTZ",
    "ALTER TABLE user_news ADD COLUMN IF NOT EXISTS language         TEXT",
    "ALTER TABLE user_news ADD COLUMN IF NOT EXISTS scope            TEXT",       # GLOBAL / US / TW
    "ALTER TABLE user_news ADD COLUMN IF NOT EXISTS source_tier      SMALLINT",   # 1~3
    "ALTER TABLE user_news ADD COLUMN IF NOT EXISTS content_kind     TEXT",       # api / body / summary / user
    "ALTER TABLE user_news ADD COLUMN IF NOT EXISTS dedup_group_id   INTEGER",
    "ALTER TABLE user_news ADD COLUMN IF NOT EXISTS is_canonical     BOOLEAN NOT NULL DEFAULT TRUE",
    "CREATE INDEX IF NOT EXISTS idx_user_news_source_url ON user_news (source_url)",
    "CREATE INDEX IF NOT EXISTS idx_user_news_submitted_at ON user_news (submitted_at)",
    "CREATE INDEX IF NOT EXISTS idx_user_news_title ON user_news (title)",
]


def apply(tables_only: bool = False) -> None:
    stmts = NEW_TABLES + ([] if tables_only else ALTER_USER_NEWS)
    with get_conn() as conn:
        with conn.cursor() as cur:
            for s in stmts:
                cur.execute(s)
        conn.commit()
    logger.info('[news_schema] 套用 %d 句 DDL（tables_only=%s）', len(stmts), tables_only)


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--tables-only', action='store_true')
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    apply(tables_only=a.tables_only)
    print('done')
