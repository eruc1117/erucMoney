"""
全市場融資融券與借券賣出 market_margin_daily：回補、每日更新、狀態與檢查（Iteration 81，Papers.md P62、P65～P68 的資料前提）。

來源是交易所官方檔（證交所 MI_MARGN＋TWT93U、櫃買 margin/balance＋margin/sbl），一天四次呼叫拿全市場，不吃 FinMind 額度——
和 market_institutional_daily（Iteration 71）同一條路線（scrapers/exchange_daily.py）。只留 market_universe 裡的代號。
單位一律存股（張 × 1,000）；兩張表共有的「融券餘額」在寫入前逐列對位檢查，格式變了會在解析時擋下。

用法：
    python margin_data.py --backfill [--start 2018-01-01] [--end 2026-10-17] [--limit N] [--delay 1.5]
    python margin_data.py --update [--date 2026-10-17]      # 單日（排程用）
    python margin_data.py --status
    python margin_data.py --check                           # 對 market_daily_prices 的覆蓋率、異常值
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

MARGIN_START = date(2018, 1, 1)
EXCHANGE_DELAY = 1.5
FULL_DAY_MIN_ROWS = 800        # 上市約 1,000 檔＋上櫃約 700 檔有信用交易；少於這個數就當這天沒補過

COLS = ('stock_id', 'trade_date', 'margin_buy', 'margin_sell', 'margin_balance', 'short_buy', 'short_sell', 'short_balance',
        'sbl_sell', 'sbl_balance', 'source')


def upsert_rows(rows: list[dict]) -> int:
    if not rows:
        return 0
    with get_conn() as conn:
        with conn.cursor() as cur:
            execute_values(cur, f"""
                INSERT INTO market_margin_daily ({', '.join(COLS)}) VALUES %s
                ON CONFLICT (stock_id, trade_date) DO UPDATE SET
                    margin_buy = EXCLUDED.margin_buy, margin_sell = EXCLUDED.margin_sell, margin_balance = EXCLUDED.margin_balance,
                    short_buy = EXCLUDED.short_buy, short_sell = EXCLUDED.short_sell, short_balance = EXCLUDED.short_balance,
                    sbl_sell = EXCLUDED.sbl_sell, sbl_balance = EXCLUDED.sbl_balance, source = EXCLUDED.source, fetched_at = CURRENT_TIMESTAMP
            """, [tuple(r.get(c) for c in COLS) for r in rows], page_size=1000)
        conn.commit()
    return len(rows)


def update_day(d: date, universe: Optional[set] = None, delay: float = 1.0) -> dict:
    """抓一天的上市＋上櫃融資融券與借券。休市（證交所 stat 不是 OK）回 {'holiday': True}。"""
    tw = ex.parse_twse_margin(ex.fetch_twse_margin(d))
    if not tw:
        return {'date': d, 'holiday': True}
    time.sleep(delay)
    tw = ex.merge_margin_sbl(tw, ex.parse_twse_sbl(ex.fetch_twse_sbl(d)), f'TWSE {d}')
    time.sleep(delay)
    tp = ex.parse_tpex_margin(ex.fetch_tpex_margin(d))
    time.sleep(delay)
    tp = ex.merge_margin_sbl(tp, ex.parse_tpex_sbl(ex.fetch_tpex_sbl(d)), f'TPEx {d}')
    tw = ex.drop_transfer_duplicates(tw, tp)
    uni = universe if universe is not None else set(market_universe.ids(include_delisted=True))
    keep = [r for r in tw + tp if r['stock_id'] in uni]
    n = upsert_rows(keep)
    return {'date': d, 'holiday': False, 'twse': sum(1 for r in keep if r['source'] == 'twse'),
            'tpex': sum(1 for r in keep if r['source'] == 'tpex'), 'rows': n, 'dropped': len(tw) + len(tp) - len(keep),
            'no_sbl': sum(1 for r in keep if r['sbl_balance'] is None)}


def _days_have(min_rows: int = FULL_DAY_MIN_ROWS) -> set:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT trade_date FROM market_margin_daily GROUP BY 1 HAVING count(*) >= %s", (min_rows,))
            return {r[0] for r in cur.fetchall()}


def backfill(start: date = MARGIN_START, end: Optional[date] = None, delay: float = EXCHANGE_DELAY, limit: int = 0) -> dict:
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
            logger.error('[margin] %s 失敗：%s', d, e)
            out['failed'].append((d, str(e)))
            time.sleep(delay)
            continue
        if r.get('holiday'):
            out['holidays'] += 1
        else:
            out['days'] += 1
            out['rows'] += r['rows']
            logger.info('[margin] (%d/%d) %s：上市 %d、上櫃 %d，略過 %d，無借券欄 %d', i, len(days), d, r['twse'], r['tpex'], r['dropped'], r['no_sbl'])
        time.sleep(delay)
    return out


def status() -> str:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT count(DISTINCT trade_date), min(trade_date), max(trade_date), count(*), count(DISTINCT stock_id),
                                  count(*) FILTER (WHERE sbl_balance IS NOT NULL) FROM market_margin_daily""")
            n_days, d0, d1, n, n_s, n_sbl = cur.fetchone()
    return f'market_margin_daily：{n_s} 檔、{n:,} 列、{n_days} 個交易日、{d0} ~ {d1}；有借券欄 {n_sbl / max(n, 1):.1%}'


def check(start: date = MARGIN_START) -> dict:
    """對 market_daily_prices 的覆蓋：日線有、本表沒有的交易日；兩表都有的日子裡有日線沒本表列的股票比例（沒有信用交易資格的股票本來就不在表裡）；負餘額列。"""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT trade_date FROM market_daily_prices WHERE trade_date >= %s GROUP BY 1 HAVING count(*) >= %s
                           EXCEPT SELECT trade_date FROM market_margin_daily GROUP BY 1 HAVING count(*) >= %s ORDER BY 1""",
                        (start, market_data.FULL_DAY_MIN_ROWS, FULL_DAY_MIN_ROWS))
            missing_days = [r[0] for r in cur.fetchall()]
            cur.execute("""SELECT count(*) FILTER (WHERE m.stock_id IS NULL), count(*)
                           FROM market_daily_prices p LEFT JOIN market_margin_daily m USING (stock_id, trade_date)
                           WHERE p.trade_date >= %s AND p.trade_date IN (SELECT trade_date FROM market_margin_daily GROUP BY 1 HAVING count(*) >= %s)""",
                        (start, FULL_DAY_MIN_ROWS))
            n_missing, n_total = cur.fetchone()
            cur.execute("SELECT count(*) FROM market_margin_daily WHERE margin_balance < 0 OR short_balance < 0 OR sbl_balance < 0")
            n_neg = cur.fetchone()[0]
    return {'missing_days': missing_days, 'stock_days_without': n_missing, 'stock_days': n_total, 'negative': n_neg}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--backfill', action='store_true')
    ap.add_argument('--update', action='store_true')
    ap.add_argument('--status', action='store_true')
    ap.add_argument('--check', action='store_true')
    ap.add_argument('--start', default=MARGIN_START.isoformat())
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
              f"負餘額的列 {r['negative']}")


if __name__ == '__main__':
    main()
