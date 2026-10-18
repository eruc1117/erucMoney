"""
全市場外資持股與發行股數 market_foreign_holding_daily：回補、每日更新、狀態與檢查（Iteration 81，Papers.md P70～P72 的資料前提）。

來源是交易所官方檔（證交所 fund/MI_QFIIS、櫃買 insti/qfii），一天兩次呼叫拿全市場，不吃 FinMind 額度——
和 market_institutional_daily（Iteration 71）同一條路線（scrapers/exchange_daily.py）。只留 market_universe 裡的代號。
寫入前逐列檢查「持股比率 ≈ 持有股數 ÷ 發行股數」，格式變了會在解析時擋下。

用法：
    python holding_data.py --backfill [--start 2018-01-01] [--end 2026-10-17] [--limit N] [--delay 1.5]
    python holding_data.py --update [--date 2026-10-17]      # 單日（排程用）
    python holding_data.py --status
    python holding_data.py --check
"""

import argparse
import logging
import time
from datetime import date
from typing import Optional

from psycopg2.extras import execute_values

from db.connection import get_conn
import market_data
import market_universe
from scrapers import exchange_daily as ex

logger = logging.getLogger(__name__)

HOLDING_START = date(2018, 1, 1)
EXCHANGE_DELAY = 1.5
FULL_DAY_MIN_ROWS = 800

COLS = ('stock_id', 'trade_date', 'shares_issued', 'foreign_shares', 'foreign_ratio', 'source')


def upsert_rows(rows: list[dict]) -> int:
    if not rows:
        return 0
    with get_conn() as conn:
        with conn.cursor() as cur:
            execute_values(cur, f"""
                INSERT INTO market_foreign_holding_daily ({', '.join(COLS)}) VALUES %s
                ON CONFLICT (stock_id, trade_date) DO UPDATE SET
                    shares_issued = EXCLUDED.shares_issued, foreign_shares = EXCLUDED.foreign_shares, foreign_ratio = EXCLUDED.foreign_ratio,
                    source = EXCLUDED.source, fetched_at = CURRENT_TIMESTAMP
            """, [tuple(r.get(c) for c in COLS) for r in rows], page_size=1000)
        conn.commit()
    return len(rows)


def update_day(d: date, universe: Optional[set] = None, delay: float = 1.0) -> dict:
    """抓一天的上市＋上櫃外資持股。休市（證交所 stat 不是 OK）回 {'holiday': True}。"""
    tw = ex.parse_twse_holding(ex.fetch_twse_holding(d))
    if not tw:
        return {'date': d, 'holiday': True}
    time.sleep(delay)
    tp = ex.parse_tpex_holding(ex.fetch_tpex_holding(d))
    tw = ex.drop_transfer_duplicates(tw, tp)
    uni = universe if universe is not None else set(market_universe.ids(include_delisted=True))
    keep = [r for r in tw + tp if r['stock_id'] in uni]
    n = upsert_rows(keep)
    return {'date': d, 'holiday': False, 'twse': sum(1 for r in keep if r['source'] == 'twse'),
            'tpex': sum(1 for r in keep if r['source'] == 'tpex'), 'rows': n, 'dropped': len(tw) + len(tp) - len(keep)}


def _days_have(min_rows: int = FULL_DAY_MIN_ROWS) -> set:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT trade_date FROM market_foreign_holding_daily GROUP BY 1 HAVING count(*) >= %s", (min_rows,))
            return {r[0] for r in cur.fetchall()}


def backfill(start: date = HOLDING_START, end: Optional[date] = None, delay: float = EXCHANGE_DELAY, limit: int = 0) -> dict:
    end = end or date.today()
    have = _days_have()
    days = [d for d in market_data.trading_days(start, end) if d not in have]
    if limit:
        days = days[:limit]
    uni = set(market_universe.ids(include_delisted=True))
    out = {'days': 0, 'rows': 0, 'holidays': 0, 'failed': [], 'total': len(days)}
    for i, d in enumerate(days, 1):
        try:
            r = update_day(d, universe=uni, delay=delay)
        except Exception as e:      # noqa: BLE001
            logger.error('[holding] %s 失敗：%s', d, e)
            out['failed'].append((d, str(e)))
            time.sleep(delay)
            continue
        if r.get('holiday'):
            out['holidays'] += 1
        else:
            out['days'] += 1
            out['rows'] += r['rows']
            logger.info('[holding] (%d/%d) %s：上市 %d、上櫃 %d，略過 %d', i, len(days), d, r['twse'], r['tpex'], r['dropped'])
        time.sleep(delay)
    return out


def status() -> str:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT count(DISTINCT trade_date), min(trade_date), max(trade_date), count(*), count(DISTINCT stock_id)
                           FROM market_foreign_holding_daily""")
            n_days, d0, d1, n, n_s = cur.fetchone()
    return f'market_foreign_holding_daily：{n_s} 檔、{n:,} 列、{n_days} 個交易日、{d0} ~ {d1}'


def check(start: date = HOLDING_START) -> dict:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT trade_date FROM market_daily_prices WHERE trade_date >= %s GROUP BY 1 HAVING count(*) >= %s
                           EXCEPT SELECT trade_date FROM market_foreign_holding_daily GROUP BY 1 HAVING count(*) >= %s ORDER BY 1""",
                        (start, market_data.FULL_DAY_MIN_ROWS, FULL_DAY_MIN_ROWS))
            missing_days = [r[0] for r in cur.fetchall()]
            cur.execute("""SELECT count(*) FILTER (WHERE h.stock_id IS NULL), count(*)
                           FROM market_daily_prices p LEFT JOIN market_foreign_holding_daily h USING (stock_id, trade_date)
                           WHERE p.trade_date >= %s AND p.trade_date IN (SELECT trade_date FROM market_foreign_holding_daily GROUP BY 1 HAVING count(*) >= %s)""",
                        (start, FULL_DAY_MIN_ROWS))
            n_missing, n_total = cur.fetchone()
            cur.execute("SELECT count(*) FROM market_foreign_holding_daily WHERE foreign_ratio < 0 OR foreign_ratio > 100 OR foreign_shares > shares_issued")
            n_bad = cur.fetchone()[0]
    return {'missing_days': missing_days, 'stock_days_without': n_missing, 'stock_days': n_total, 'bad': n_bad}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--backfill', action='store_true')
    ap.add_argument('--update', action='store_true')
    ap.add_argument('--status', action='store_true')
    ap.add_argument('--check', action='store_true')
    ap.add_argument('--start', default=HOLDING_START.isoformat())
    ap.add_argument('--end')
    ap.add_argument('--date')
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--delay', type=float, default=EXCHANGE_DELAY)
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s')
    if a.backfill:
        r = backfill(date.fromisoformat(a.start), date.fromisoformat(a.end) if a.end else None, delay=a.delay, limit=a.limit)
        print(f"回補 {r['days']} 個交易日、{r['rows']:,} 列，休市 {r['holidays']}，失敗 {len(r['failed'])}（待補 {r['total']}）")
        for d, e in r['failed'][:20]:
            print('  失敗', d, e[:120])
    if a.update:
        d = date.fromisoformat(a.date) if a.date else date.today()
        print(update_day(d))
    if a.status:
        print(status())
    if a.check:
        r = check()
        print(f"日線有、本表沒有的交易日 {len(r['missing_days'])} 天{('：' + ', '.join(map(str, r['missing_days'][:10]))) if r['missing_days'] else ''}；"
              f"兩表都有的日子裡，有日線沒本表列的股票日 {r['stock_days_without']:,}／{r['stock_days']:,}（{r['stock_days_without'] / max(r['stock_days'], 1):.2%}）；"
              f"比率異常或持股 > 發行的列 {r['bad']}")


if __name__ == '__main__':
    main()
