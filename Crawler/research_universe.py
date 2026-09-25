"""
研究用擴大股票池（Iteration 39 第二輪）：月營收事件研究從 23 檔擴到「鉅亨營收速報有精確公布時間」的股票
────────────────────────────────────────────────────────────────────────
為什麼另開一張表：`stock_daily_prices` 被 LSTM data_loader、rebuild_adj_close、sync_stock_info、新鮮度檢查
當成「追蹤股清單」在用，塞進一百多檔研究股會讓 LSTM 多訓練一百多檔、新鮮度檢查天天報落後。
所以研究股的價格放 `research_daily_prices`（欄位同 stock_daily_prices，沒有 adj_close），
營收與公布時點仍寫 `stock_revenue_announce`（那張表本來就允許非追蹤股）。

候選：`stock_revenue_announce` 裡 announce_source = cnyes_item 的月份數 ≥ --min-months（預設 12）且不是追蹤股。
2026-09 實測：≥12 月 159 檔、2,564 個精確事件（追蹤股只有 353 個）。

FinMind 匿名額度低（config 的 token 為空；文件寫 30 次/小時，實測更寬鬆），每檔價格 1 次、營收 1 次；
遇到額度用盡（HTTP 402 / 429 或 status != 200）等 --retry-wait 秒再試，可中斷續跑（已有資料的檔跳過）。

用法：
    python research_universe.py --create                 # 建 research_daily_prices
    python research_universe.py --prices [--min-months 12] [--limit N]
    python research_universe.py --revenue
    python research_universe.py --all
    python research_universe.py --status
"""

import argparse
import logging
import os
import time
from datetime import date, datetime

import requests
from psycopg2.extras import execute_values

from config import FINMIND
from db.connection import get_conn

logger = logging.getLogger(__name__)
API = 'https://api.finmindtrade.com/api/v4/data'
PRICE_START = '2023-01-01'       # 事件自 2023-09 起，前面留 8 個月給動能與基準
LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs')

DDL = """
CREATE TABLE IF NOT EXISTS research_daily_prices (
    stock_id          VARCHAR(12) NOT NULL,
    trade_date        DATE        NOT NULL,
    open_price        NUMERIC(12, 4),
    high_price        NUMERIC(12, 4),
    low_price         NUMERIC(12, 4),
    close_price       NUMERIC(12, 4),
    volume            BIGINT,
    turnover_value    NUMERIC(20, 2),
    transaction_count INTEGER,
    change_value      NUMERIC(12, 4),
    change_rate       NUMERIC(8, 3),
    fetched_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (stock_id, trade_date)
);
CREATE INDEX IF NOT EXISTS idx_research_prices_date ON research_daily_prices (trade_date);
"""


def create() -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(DDL)
        conn.commit()


def candidates(min_months: int) -> list:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT stock_id, count(*) AS n FROM stock_revenue_announce
                WHERE announce_source = 'cnyes_item'
                  AND stock_id NOT IN (SELECT stock_id FROM stock_info WHERE is_tracking)
                  AND stock_id ~ '^[0-9]{4}$'
                GROUP BY 1 HAVING count(*) >= %s ORDER BY n DESC, stock_id""", (min_months,))
            return [r[0] for r in cur.fetchall()]


def _finmind(dataset: str, sid: str, start: str) -> list:
    params = {'dataset': dataset, 'data_id': sid, 'start_date': start, 'end_date': date.today().isoformat()}
    if FINMIND.get('token'):
        params['token'] = FINMIND['token']
    r = requests.get(API, params=params, timeout=120)
    if r.status_code in (402, 429):
        raise QuotaError(f'HTTP {r.status_code}')
    r.raise_for_status()
    j = r.json()
    if j.get('status') != 200:
        raise QuotaError(f"status {j.get('status')}: {j.get('msg')}")
    return j.get('data') or []


class QuotaError(RuntimeError):
    pass


def _f(v):
    try:
        return None if v is None or v == '' else float(v)
    except (TypeError, ValueError):
        return None


def upsert_prices(sid: str, data: list) -> int:
    rows = []
    for d in data:
        close, spread = _f(d.get('close')), _f(d.get('spread'))
        rate = None
        if close is not None and spread is not None and (close - spread):
            rate = round(spread / (close - spread) * 100, 3)
        rows.append((sid, str(d['date'])[:10], _f(d.get('open')), _f(d.get('max')), _f(d.get('min')), close,
                     int(_f(d.get('Trading_Volume')) or 0), _f(d.get('Trading_money')),
                     int(_f(d.get('Trading_turnover')) or 0), spread, rate))
    if not rows:
        return 0
    with get_conn() as conn:
        with conn.cursor() as cur:
            execute_values(cur, """
                INSERT INTO research_daily_prices (stock_id, trade_date, open_price, high_price, low_price, close_price,
                    volume, turnover_value, transaction_count, change_value, change_rate)
                VALUES %s ON CONFLICT (stock_id, trade_date) DO UPDATE SET
                    open_price = EXCLUDED.open_price, high_price = EXCLUDED.high_price, low_price = EXCLUDED.low_price,
                    close_price = EXCLUDED.close_price, volume = EXCLUDED.volume, turnover_value = EXCLUDED.turnover_value,
                    transaction_count = EXCLUDED.transaction_count, change_value = EXCLUDED.change_value,
                    change_rate = EXCLUDED.change_rate""", rows, page_size=500)
        conn.commit()
    return len(rows)


def _have(table: str, col: str, min_date: date) -> set:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT stock_id FROM {table} GROUP BY 1 HAVING max({col}) >= %s", (min_date,))
            return {r[0] for r in cur.fetchall()}


def run(kind: str, ids: list, retry_wait: int, delay: float) -> dict:
    """kind = prices | revenue。回傳 {'done', 'skipped', 'failed'}。"""
    from backfill_revenue import fetch_revenue, upsert as upsert_revenue
    today = date.today()
    if kind == 'prices':
        have = _have('research_daily_prices', 'trade_date', date(today.year, today.month, 1))
    else:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT stock_id FROM stock_revenue_announce WHERE revenue IS NOT NULL "
                            "GROUP BY 1 HAVING count(*) >= 36")
                have = {r[0] for r in cur.fetchall()}
    out = {'done': 0, 'skipped': 0, 'failed': []}
    for i, sid in enumerate(ids, 1):
        if sid in have:
            out['skipped'] += 1
            continue
        for attempt in range(8):
            try:
                if kind == 'prices':
                    n = upsert_prices(sid, _finmind('TaiwanStockPrice', sid, PRICE_START))
                else:
                    n = upsert_revenue(fetch_revenue(sid, '2013-01-01'))
                print(f'[{i}/{len(ids)}] {kind} {sid} {n} 筆', flush=True)
                out['done'] += 1
                break
            except QuotaError as e:
                print(f'[{i}/{len(ids)}] {kind} {sid} 額度／狀態問題（{e}），等 {retry_wait}s', flush=True)
                time.sleep(retry_wait)
            except Exception as e:       # noqa: BLE001
                logger.warning('%s %s 失敗：%s', kind, sid, e)
                time.sleep(10)
        else:
            out['failed'].append(sid)
        time.sleep(delay)
    return out


def status() -> str:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT count(DISTINCT stock_id), count(*), min(trade_date), max(trade_date) FROM research_daily_prices")
            p = cur.fetchone()
            cur.execute("""SELECT count(DISTINCT r.stock_id) FROM stock_revenue_announce r
                           WHERE r.revenue IS NOT NULL AND r.stock_id IN (SELECT DISTINCT stock_id FROM research_daily_prices)""")
            rv = cur.fetchone()[0]
    return f'research_daily_prices：{p[0]} 檔、{p[1]:,} 列、{p[2]} ~ {p[3]}；其中有營收數字 {rv} 檔'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--create', action='store_true')
    ap.add_argument('--prices', action='store_true')
    ap.add_argument('--revenue', action='store_true')
    ap.add_argument('--all', action='store_true')
    ap.add_argument('--status', action='store_true')
    ap.add_argument('--min-months', type=int, default=12)
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--retry-wait', type=int, default=600)
    ap.add_argument('--delay', type=float, default=2.5)
    a = ap.parse_args()
    os.makedirs(LOG_DIR, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
                        handlers=[logging.FileHandler(os.path.join(LOG_DIR, 'research_universe.log'), encoding='utf-8')])
    if a.create or a.all:
        create()
        print('research_daily_prices 已建立（或已存在）')
    ids = candidates(a.min_months)
    if a.limit:
        ids = ids[:a.limit]
    print(f'候選 {len(ids)} 檔（cnyes_item ≥ {a.min_months} 個月，非追蹤股）  {datetime.now():%H:%M}', flush=True)
    if a.prices or a.all:
        r = run('prices', ids, a.retry_wait, a.delay)
        print(f'價格：完成 {r["done"]}、跳過 {r["skipped"]}、失敗 {r["failed"]}', flush=True)
    if a.revenue or a.all:
        r = run('revenue', ids, a.retry_wait, a.delay)
        print(f'營收：完成 {r["done"]}、跳過 {r["skipped"]}、失敗 {r["failed"]}', flush=True)
    if a.status or a.all:
        print(status())


if __name__ == '__main__':
    main()
