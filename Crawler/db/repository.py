"""
資料庫寫入層 (Repository)
對應 DB.md 中的三張 PostgreSQL 表：
  - stock_info
  - stock_daily_prices
  - stock_chip_analysis
  - stock_foreign_holding（外資絕對持股，Iteration 35）

所有 INSERT 使用 ON CONFLICT DO UPDATE（UPSERT），
重複執行不會產生錯誤，資料會被最新值覆蓋。
"""

import logging
from datetime import date

from psycopg2.extras import execute_values

from db.connection import get_conn
from models.stock import StockDailyPrice, StockChipAnalysis, StockForeignHolding

logger = logging.getLogger(__name__)


# ── news_crawl_raw（財金過濾中介表）─────────────────────────────────────────

_RAW_TABLE_CREATED = False   # 只建表一次

def _ensure_raw_table(cur) -> None:
    """建立 news_crawl_raw 中介表（若不存在）。"""
    global _RAW_TABLE_CREATED
    if _RAW_TABLE_CREATED:
        return
    cur.execute("""
        CREATE TABLE IF NOT EXISTS news_crawl_raw (
            id           SERIAL PRIMARY KEY,
            platform     TEXT,
            title        TEXT,
            content      TEXT,
            tickers      TEXT[],
            keywords     TEXT[],
            source_url   TEXT UNIQUE,          -- CC 原始 URL，用於去重
            published_at TEXT,                 -- CC timestamp（YYYYMMDDHHMMSS）
            is_financial BOOLEAN NOT NULL,     -- 財金關鍵詞過濾結果
            scraped_at   TIMESTAMP DEFAULT NOW()
        )
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_news_crawl_raw_is_financial
            ON news_crawl_raw (is_financial)
    """)
    _RAW_TABLE_CREATED = True


def insert_raw_news_batch(articles: list) -> tuple[int, int]:
    """
    批次寫入爬取的原始新聞至中介表 news_crawl_raw。
    以 source_url 為唯一鍵，重複時跳過（ON CONFLICT DO NOTHING）。

    Returns:
        (inserted, skipped) — 實際新增筆數、跳過（重複）筆數
    """
    if not articles:
        return 0, 0

    inserted = 0
    skipped  = 0

    with get_conn() as conn:
        with conn.cursor() as cur:
            _ensure_raw_table(cur)
            for art in articles:
                src_url = art.get('source_url') or ''
                cur.execute("""
                    INSERT INTO news_crawl_raw
                        (platform, title, content, tickers, keywords,
                         source_url, published_at, is_financial)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (source_url) DO NOTHING
                """, (
                    art.get('platform', ''),
                    (art.get('title') or '').strip() or '(無標題)',
                    art.get('content', ''),
                    art.get('tickers', []),
                    art.get('keywords', []),
                    src_url or None,          # 空字串改為 NULL，避免 UNIQUE 衝突
                    # published_at 欄位型別為 TEXT：datetime 一律轉 ISO 字串
                    (art['published_at'].isoformat()
                     if hasattr(art.get('published_at'), 'isoformat')
                     else (art.get('published_at') or '')),
                    bool(art.get('is_financial', False)),
                ))
                if cur.rowcount:
                    inserted += 1
                else:
                    skipped += 1
        conn.commit()

    logger.info('[news_raw] 中介表寫入 %d 筆，跳過重複 %d 筆', inserted, skipped)
    return inserted, skipped


# ── user_news ──────────────────────────────────────────────────────────────────

def insert_news_articles(articles: list) -> int:
    """
    批次寫入爬取的新聞，跳過已存在的相同 (platform, title) 記錄。

    Returns:
        實際新增的筆數
    """
    if not articles:
        return 0

    count = 0
    with get_conn() as conn:
        with conn.cursor() as cur:
            for art in articles:
                platform = art.get('platform', '')
                title    = art.get('title', '').strip() or '(無標題)'
                content  = art.get('content', '')
                tickers  = art.get('tickers', [])
                keywords = art.get('keywords', [])
                # 真實發布時間（Iteration 10 起由 RSS 提供）。
                # 舊版一律用 CURRENT_TIMESTAMP，使 model2 的時間衰減權重
                # （T+0=1.0 / T+1=0.6 / T+2=0.3）永遠把舊聞當成今日新聞。
                published = art.get('published_at')

                # 跳過重複（相同標題即視為同一則，跨來源亦然）。
                # Iteration 38：有發布時間時以「標題 + 發布日」判重——MOPS 重大訊息
                # 同一主旨（「本公司代子公司公告取得固定收益證券」）每月都會再發一次，
                # 只看標題會把不同日期的公告當成重複（實測 6,574 則只進了 3,945 則）。
                if published:
                    cur.execute(
                        'SELECT 1 FROM user_news WHERE title = %s AND submitted_at::date = %s::date LIMIT 1',
                        (title, published),
                    )
                else:
                    cur.execute('SELECT 1 FROM user_news WHERE title = %s LIMIT 1', (title,))
                if cur.fetchone():
                    continue

                if published:
                    cur.execute(
                        'INSERT INTO user_news (platform, title, content, tickers,'
                        ' keywords, submitted_at) VALUES (%s, %s, %s, %s, %s, %s)',
                        (platform, title, content, tickers, keywords, published),
                    )
                else:
                    cur.execute(
                        'INSERT INTO user_news (platform, title, content, tickers, keywords)'
                        ' VALUES (%s, %s, %s, %s, %s)',
                        (platform, title, content, tickers, keywords),
                    )
                count += 1
        conn.commit()

    logger.info('[news] 新增 %d 則（跳過重複）', count)
    return count


# ── stock_info ─────────────────────────────────────────────────────────────────

def upsert_stock_info(stock_id: str, stock_name: str,
                      market_type: str = None, industry_type: str = None) -> None:
    """
    新增或更新個股基本資訊。
    若 stock_id 已存在，更新 stock_name / market_type / industry_type。
    """
    sql = """
        INSERT INTO stock_info (stock_id, stock_name, market_type, industry_type)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (stock_id) DO UPDATE SET
            stock_name    = EXCLUDED.stock_name,
            market_type   = EXCLUDED.market_type,
            industry_type = EXCLUDED.industry_type,
            updated_at    = CURRENT_TIMESTAMP;
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (stock_id, stock_name, market_type, industry_type))
        conn.commit()
    logger.debug("[stock_info] upsert: %s %s", stock_id, stock_name)


# ── stock_daily_prices ─────────────────────────────────────────────────────────

def upsert_daily_prices(prices: list[StockDailyPrice]) -> int:
    """
    批次寫入每日行情資料。
    主鍵 (stock_id, trade_date) 衝突時，更新所有價格欄位。

    Returns:
        實際寫入筆數
    """
    if not prices:
        return 0

    sql = """
        INSERT INTO stock_daily_prices (
            stock_id, trade_date,
            open_price, high_price, low_price, close_price,
            volume, turnover_value, transaction_count,
            change_value, change_rate
        )
        VALUES %s
        ON CONFLICT (stock_id, trade_date) DO UPDATE SET
            open_price        = EXCLUDED.open_price,
            high_price        = EXCLUDED.high_price,
            low_price         = EXCLUDED.low_price,
            close_price       = EXCLUDED.close_price,
            volume            = EXCLUDED.volume,
            turnover_value    = EXCLUDED.turnover_value,
            transaction_count = EXCLUDED.transaction_count,
            change_value      = EXCLUDED.change_value,
            change_rate       = EXCLUDED.change_rate;
    """

    rows = [
        (
            p.stock_id,
            p.trade_date,
            p.open_price,
            p.high_price,
            p.low_price,
            p.close_price,
            p.volume,
            p.turnover_value,
            p.transaction_count,
            p.change_value,
            p.change_rate,
        )
        for p in prices
    ]

    with get_conn() as conn:
        with conn.cursor() as cur:
            execute_values(cur, sql, rows)
        conn.commit()

    logger.info("[stock_daily_prices] upsert %d 筆", len(rows))
    return len(rows)


# ── stock_chip_analysis ────────────────────────────────────────────────────────

def upsert_chip_analysis(chips: list[StockChipAnalysis]) -> int:
    """
    批次寫入三大法人籌碼資料。
    主鍵 (stock_id, trade_date) 衝突時，更新所有籌碼欄位。

    Returns:
        實際寫入筆數
    """
    if not chips:
        return 0

    sql = """
        INSERT INTO stock_chip_analysis (
            stock_id, trade_date,
            foreign_investor_buy, investment_trust_buy,
            dealer_buy, total_net_buy, foreign_holding_ratio
        )
        VALUES %s
        ON CONFLICT (stock_id, trade_date) DO UPDATE SET
            foreign_investor_buy  = EXCLUDED.foreign_investor_buy,
            investment_trust_buy  = EXCLUDED.investment_trust_buy,
            dealer_buy            = EXCLUDED.dealer_buy,
            total_net_buy         = EXCLUDED.total_net_buy,
            foreign_holding_ratio = EXCLUDED.foreign_holding_ratio;
    """

    rows = [
        (
            c.stock_id,
            c.trade_date,
            c.foreign_investor_buy,
            c.investment_trust_buy,
            c.dealer_buy,
            c.total_net_buy,
            c.foreign_holding_ratio,
        )
        for c in chips
    ]

    with get_conn() as conn:
        with conn.cursor() as cur:
            execute_values(cur, sql, rows)
        conn.commit()

    logger.info("[stock_chip_analysis] upsert %d 筆", len(rows))
    return len(rows)


# ── stock_foreign_holding（外資絕對持股）────────────────────────────────────

_HOLDING_TABLE_CREATED = False

def _ensure_foreign_holding_table(cur) -> None:
    """建立 stock_foreign_holding（若不存在）。

    刻意**不放進 stock_chip_analysis**：那張表是 M3 籌碼模型與 UnifiedModel 的
    特徵來源，而持股統計的日期集合與買賣超不完全一致（例如停牌日只有其中一邊）。
    塞在同一張表會多出一批買賣超全 NULL 的列，模型端看不出那是「沒交易」還是
    「沒抓到」。分開放，兩邊各自完整。
    """
    global _HOLDING_TABLE_CREATED
    if _HOLDING_TABLE_CREATED:
        return
    cur.execute("""
        CREATE TABLE IF NOT EXISTS stock_foreign_holding (
            stock_id                  VARCHAR(10)   NOT NULL,
            trade_date                DATE          NOT NULL,
            foreign_shares            BIGINT,          -- 外資持有股數（股）
            foreign_ratio             NUMERIC(6, 2),   -- 外資持股比例 (%)
            foreign_upper_limit_ratio NUMERIC(6, 2),   -- 外資投資上限 (%)
            shares_issued             BIGINT,          -- 已發行股數（股）
            PRIMARY KEY (stock_id, trade_date)
        )
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_foreign_holding_date
            ON stock_foreign_holding (trade_date DESC)
    """)
    _HOLDING_TABLE_CREATED = True


def upsert_foreign_holding(rows_in: list[StockForeignHolding]) -> int:
    """
    批次寫入外資持股統計。主鍵 (stock_id, trade_date) 衝突時更新所有欄位。

    Returns:
        實際寫入筆數
    """
    if not rows_in:
        return 0

    sql = """
        INSERT INTO stock_foreign_holding (
            stock_id, trade_date,
            foreign_shares, foreign_ratio, foreign_upper_limit_ratio, shares_issued
        )
        VALUES %s
        ON CONFLICT (stock_id, trade_date) DO UPDATE SET
            foreign_shares            = EXCLUDED.foreign_shares,
            foreign_ratio             = EXCLUDED.foreign_ratio,
            foreign_upper_limit_ratio = EXCLUDED.foreign_upper_limit_ratio,
            shares_issued             = EXCLUDED.shares_issued;
    """
    rows = [
        (h.stock_id, h.trade_date, h.foreign_shares, h.foreign_ratio,
         h.foreign_upper_limit_ratio, h.shares_issued)
        for h in rows_in
    ]

    with get_conn() as conn:
        with conn.cursor() as cur:
            _ensure_foreign_holding_table(cur)
            execute_values(cur, sql, rows)
        conn.commit()

    logger.info("[stock_foreign_holding] upsert %d 筆", len(rows))
    return len(rows)
