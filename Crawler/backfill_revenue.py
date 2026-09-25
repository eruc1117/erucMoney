"""
月營收回補（Iteration 20 建；Iteration 39 改）

用途：事件研究與意外程度（surprise）。台股強制每月 10 日前公布上月營收，是每年 12 次、
時間戳可考的排程型事件（新聞訊號研究方案階段 1）。

**欄位陷阱**：FinMind `TaiwanStockMonthRevenue` 的
    date        = 營收所屬月份（例如 2026-07-01 代表 6 月營收）
    create_time = 實際公布日（例如 2026-07-13）——**2026-03 之前全部是空字串**
兩者相差約兩週，混用會讓事件時間點整整錯開半個月。

Iteration 39 起：沒有 create_time 的月份也存（announce_date NULL），因為算 surprise 要用前 15 個月的
營收數字；公布時點另由 backfill_revenue_dates.py 從鉅亨網營收速報／MOPS／媒體標題補上，
本腳本只在既有來源為空或同為 finmind 時才寫 announce_date。

用法：
    python backfill_revenue.py                  # 全部追蹤股票
    python backfill_revenue.py --stocks 2330
"""

import argparse
import logging
import time
from datetime import date

import requests

from config import FINMIND
from db.connection import get_conn

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

API = 'https://api.finmindtrade.com/api/v4/data'
DEFAULT_START = "2013-01-01"     # IFRS 合併營收起；surprise 只需事件前 15 個月


def tracked_ids() -> list[str]:
    """有價格資料的個股（ETF 沒有月營收，略過）。"""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT DISTINCT p.stock_id FROM stock_daily_prices p
                           LEFT JOIN stock_info i ON i.stock_id = p.stock_id
                           WHERE COALESCE(i.industry_type, '') <> 'ETF' ORDER BY 1""")
            return [r[0] for r in cur.fetchall()]


def fetch_revenue(sid: str, start: str) -> list:
    params = {'dataset': 'TaiwanStockMonthRevenue', 'data_id': sid,
              'start_date': start, 'end_date': date.today().isoformat()}
    token = FINMIND.get('token', '')
    if token:
        params['token'] = token
    r = requests.get(API, params=params, timeout=120)
    r.raise_for_status()
    data = r.json().get('data') or []

    rows = []
    for d in data:
        announce = str(d.get('create_time') or '')[:10]
        month = str(d.get('date') or '')[:10]
        if not month:
            continue
        rows.append({
            'stock_id': sid,
            'revenue_month': month,
            'announce_date': announce or None,     # 2026-03 之前為 None，由 backfill_revenue_dates 補
            'revenue': d.get('revenue'),
        })
    return rows


def upsert(rows: list) -> int:
    if not rows:
        return 0
    n = 0
    with get_conn() as conn:
        with conn.cursor() as cur:
            for r in rows:
                # 公布日只在「新值非空」且「既有來源為空或同為 finmind」時覆蓋——
                # 精確到秒的來源（mops_item / cnyes_item / news_item）與 cnyes_list 都不動
                cur.execute("""
                    INSERT INTO stock_revenue_announce
                        (stock_id, revenue_month, announce_date, revenue, announce_source)
                    VALUES (%s,%s,%s,%s, CASE WHEN %s::date IS NULL THEN NULL ELSE 'finmind' END)
                    ON CONFLICT (stock_id, revenue_month) DO UPDATE SET
                        revenue         = COALESCE(EXCLUDED.revenue, stock_revenue_announce.revenue),
                        announce_date   = CASE WHEN EXCLUDED.announce_date IS NOT NULL
                                                AND stock_revenue_announce.announce_source IS DISTINCT FROM 'mops_item'
                                                AND stock_revenue_announce.announce_source IS DISTINCT FROM 'cnyes_item'
                                                AND stock_revenue_announce.announce_source IS DISTINCT FROM 'news_item'
                                                AND stock_revenue_announce.announce_source IS DISTINCT FROM 'cnyes_list'
                                               THEN EXCLUDED.announce_date
                                               ELSE stock_revenue_announce.announce_date END,
                        announce_source = CASE WHEN EXCLUDED.announce_date IS NOT NULL
                                                AND stock_revenue_announce.announce_source IS NULL
                                               THEN 'finmind'
                                               ELSE stock_revenue_announce.announce_source END,
                        updated_at      = CURRENT_TIMESTAMP
                """, (r['stock_id'], r['revenue_month'], r['announce_date'],
                      r['revenue'], r['announce_date']))
                n += 1
        conn.commit()
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--start', default=DEFAULT_START)
    ap.add_argument('--stocks', nargs='+', default=None)
    ap.add_argument('--retry-wait', type=int, default=300)
    args = ap.parse_args()

    ids = args.stocks or tracked_ids()
    logger.info("回補月營收公布日 %d 檔（自 %s）", len(ids), args.start)

    total, failed = 0, []
    for i, sid in enumerate(ids, 1):
        attempts = 0
        while True:
            attempts += 1
            try:
                rows = fetch_revenue(sid, args.start)
                n = upsert(rows)
                total += n
                logger.info("[%d/%d] %s %d 筆", i, len(ids), sid, n)
                break
            except Exception as e:
                if args.retry_wait > 0 and attempts <= 6:
                    logger.warning("[%d/%d] %s 失敗（%s），%d 秒後重試",
                                   i, len(ids), sid, e, args.retry_wait)
                    time.sleep(args.retry_wait)
                    continue
                failed.append(sid)
                logger.error("[%d/%d] %s 放棄：%s", i, len(ids), sid, e)
                break
        time.sleep(2)

    logger.info("完成：共 %d 筆%s", total,
                f"；失敗：{' '.join(failed)}" if failed else "")


if __name__ == "__main__":
    main()
