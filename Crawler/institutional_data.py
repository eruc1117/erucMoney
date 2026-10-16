"""
全市場三大法人買賣超 market_institutional_daily：回補、每日更新、狀態與檢查（Iteration 71，Papers.md P18／P44 的資料前提）。

來源是交易所官方檔（證交所 fund/T86、櫃買 insti/dailyTrade），一天兩次呼叫拿全市場，不吃 FinMind 額度——
和 market_daily_prices 同一條路線（scrapers/exchange_daily.py）。只留 market_universe 裡的代號（ETF、權證、債券略過）。
寫入前逐列驗證「三大法人合計 = 外資 + 投信 + 自營」，格式變了會在解析時擋下，不會寫錯欄。

用法：
    python institutional_data.py --backfill [--start 2018-01-01] [--end 2026-10-15] [--limit N] [--delay 2]
    python institutional_data.py --update [--date 2026-10-15]      # 單日（排程用）
    python institutional_data.py --status
    python institutional_data.py --check                           # 對 market_daily_prices 的覆蓋率
"""

import argparse
import logging
import time
from datetime import date, timedelta
from typing import Optional

from psycopg2.extras import execute_values

from db.connection import get_conn
import market_data
import market_universe
from scrapers import exchange_daily as ex

logger = logging.getLogger(__name__)

INSTI_START = date(2018, 1, 1)
EXCHANGE_DELAY = 2.0
FULL_DAY_MIN_ROWS = 800        # 上市＋上櫃一天約 1,600 檔；少於這個數就當這天沒補過

COLS = ('stock_id', 'trade_date', 'foreign_buy', 'foreign_sell', 'foreign_net', 'trust_buy', 'trust_sell', 'trust_net',
        'dealer_buy', 'dealer_sell', 'dealer_net', 'total_net', 'source')


def upsert_rows(rows: list[dict]) -> int:
    if not rows:
        return 0
    with get_conn() as conn:
        with conn.cursor() as cur:
            execute_values(cur, f"""
                INSERT INTO market_institutional_daily ({', '.join(COLS)}) VALUES %s
                ON CONFLICT (stock_id, trade_date) DO UPDATE SET
                    foreign_buy = EXCLUDED.foreign_buy, foreign_sell = EXCLUDED.foreign_sell, foreign_net = EXCLUDED.foreign_net,
                    trust_buy = EXCLUDED.trust_buy, trust_sell = EXCLUDED.trust_sell, trust_net = EXCLUDED.trust_net,
                    dealer_buy = EXCLUDED.dealer_buy, dealer_sell = EXCLUDED.dealer_sell, dealer_net = EXCLUDED.dealer_net,
                    total_net = EXCLUDED.total_net, source = EXCLUDED.source, fetched_at = CURRENT_TIMESTAMP
            """, [tuple(r.get(c) for c in COLS) for r in rows], page_size=1000)
        conn.commit()
    return len(rows)


def update_day(d: date, universe: Optional[set] = None, delay: float = 1.0) -> dict:
    """抓一天的上市＋上櫃三大法人買賣超。休市（證交所 stat 不是 OK）回 {'holiday': True}。"""
    rows = ex.parse_twse_institutional(ex.fetch_twse_institutional(d))
    if not rows:
        return {'date': d, 'holiday': True}
    time.sleep(delay)
    tpex_rows = ex.parse_tpex_institutional(ex.fetch_tpex_institutional(d))
    uni = universe if universe is not None else set(market_universe.ids(include_delisted=True))
    keep = [r for r in rows + tpex_rows if r['stock_id'] in uni]
    n = upsert_rows(keep)
    return {'date': d, 'holiday': False, 'twse': sum(1 for r in keep if r['source'] == 'twse'),
            'tpex': sum(1 for r in keep if r['source'] == 'tpex'), 'rows': n, 'dropped': len(rows) + len(tpex_rows) - len(keep)}


def _days_have(min_rows: int = FULL_DAY_MIN_ROWS) -> set:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT trade_date FROM market_institutional_daily GROUP BY 1 HAVING count(*) >= %s", (min_rows,))
            return {r[0] for r in cur.fetchall()}


def backfill(start: date = INSTI_START, end: Optional[date] = None, delay: float = EXCHANGE_DELAY, limit: int = 0) -> dict:
    """按交易日抓；已有資料的日子跳過，可中斷續跑。失敗的日子記下來、繼續跑下一天。"""
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
            logger.error('[insti] %s 失敗：%s', d, e)
            out['failed'].append((d, str(e)))
            time.sleep(delay)
            continue
        if r.get('holiday'):
            out['holidays'] += 1
        else:
            out['days'] += 1
            out['rows'] += r['rows']
            logger.info('[insti] (%d/%d) %s：上市 %d、上櫃 %d，略過 %d', i, len(days), d, r['twse'], r['tpex'], r['dropped'])
        time.sleep(delay)
    return out


def status() -> str:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT count(DISTINCT trade_date), min(trade_date), max(trade_date), count(*), count(DISTINCT stock_id)
                           FROM market_institutional_daily""")
            n_days, d0, d1, n, n_s = cur.fetchone()
    return f'market_institutional_daily：{n_s} 檔、{n:,} 列、{n_days} 個交易日、{d0} ~ {d1}'


def check(start: date = INSTI_START) -> dict:
    """對 market_daily_prices 的覆蓋：日線有、法人表沒有的交易日；兩表都有的日子裡有日線但沒法人列的股票比例。"""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT trade_date FROM market_daily_prices WHERE trade_date >= %s GROUP BY 1 HAVING count(*) >= %s
                           EXCEPT SELECT trade_date FROM market_institutional_daily GROUP BY 1 HAVING count(*) >= %s ORDER BY 1""",
                        (start, market_data.FULL_DAY_MIN_ROWS, FULL_DAY_MIN_ROWS))
            missing_days = [r[0] for r in cur.fetchall()]
            cur.execute("""SELECT count(*) FILTER (WHERE i.stock_id IS NULL), count(*)
                           FROM market_daily_prices p
                           LEFT JOIN market_institutional_daily i USING (stock_id, trade_date)
                           WHERE p.trade_date >= %s AND p.trade_date IN (SELECT trade_date FROM market_institutional_daily GROUP BY 1 HAVING count(*) >= %s)""",
                        (start, FULL_DAY_MIN_ROWS))
            n_missing, n_total = cur.fetchone()
            cur.execute("SELECT count(*) FROM market_institutional_daily WHERE foreign_net + trust_net + dealer_net <> total_net")
            n_bad = cur.fetchone()[0]
    return {'missing_days': missing_days, 'stock_days_without_insti': n_missing, 'stock_days': n_total,
            'identity_violations': n_bad}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--backfill', action='store_true')
    ap.add_argument('--update', action='store_true')
    ap.add_argument('--status', action='store_true')
    ap.add_argument('--check', action='store_true')
    ap.add_argument('--start', default=INSTI_START.isoformat())
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
        print(f"日線有、法人表沒有的交易日 {len(r['missing_days'])} 天{('：' + ', '.join(map(str, r['missing_days'][:10]))) if r['missing_days'] else ''}；"
              f"兩表都有的日子裡，有日線沒法人列的股票日 {r['stock_days_without_insti']:,}／{r['stock_days']:,}"
              f"（{r['stock_days_without_insti'] / max(r['stock_days'], 1):.2%}）；合計不等的列 {r['identity_violations']}")


if __name__ == '__main__':
    main()
