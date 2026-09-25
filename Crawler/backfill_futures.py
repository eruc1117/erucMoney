"""
期貨日／夜盤行情回補（Iteration 28）

台指期夜盤是台股開盤前的直接定價，探測顯示它對個股跳空的相關（0.567）
高於費半（0.483），且幾乎吃掉美股的全部資訊。這支工具把它補進資料庫。

## 只存近月，且用成交量挑

FinMind 一次回傳所有契約月份與價差交易。處理方式：
  · 契約月份含 '/' 的是價差交易，不是單一契約報價 → 剔除
  · 近月＝當日該時段**成交量最大**的契約。用「最小契約月」會在結算日前後
    挑到即將到期、流動性已移轉的那一口，價格代表性差

## session 語意（實測確認，搞反就是未來資訊洩漏）

`after_market` 列的收盤價幾乎等於**同一個 trade_date** 的日盤開盤價
（中位數差 0.185%）——亦即它領先同日開盤。所以特徵要這樣接：
預測 D 日開盤跳空時，用的是 D 日那列的 after_market，不是 D-1 的。

用法：
    python backfill_futures.py                       # TX + MTX，2018 起
    python backfill_futures.py --ids TX --start 2020-01-01
    python backfill_futures.py --ids TX MTX CDF      # 加台積電股票期
"""

import argparse
import logging
import time
from datetime import date

import pandas as pd

from db.connection import get_conn

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

DEFAULT_IDS = ['TX', 'MTX']
DEFAULT_START = '2018-01-01'      # 夜盤 2017-05 開放，留一段暖身
CHUNK_DAYS = 365                  # FinMind 單次範圍過大會被截斷，分年抓


def fetch_range(futures_id: str, start: date, end: date) -> pd.DataFrame:
    """抓一段期間的近月日／夜盤。回傳已整理成資料表欄位的 DataFrame。"""
    from FinMind.data import DataLoader
    dl = DataLoader()
    df = dl.taiwan_futures_daily(futures_id=futures_id,
                                 start_date=start.isoformat(),
                                 end_date=end.isoformat())
    if df is None or df.empty:
        return pd.DataFrame()

    df = df[~df['contract_date'].astype(str).str.contains('/')]
    df = df[df['volume'] > 0]
    if df.empty:
        return pd.DataFrame()

    idx = df.groupby(['date', 'trading_session'])['volume'].idxmax()
    near = df.loc[idx].copy()
    out = pd.DataFrame({
        'futures_id': futures_id,
        'trade_date': pd.to_datetime(near['date']).dt.date,
        'session': near['trading_session'],
        'contract_date': near['contract_date'].astype(str),
        'open_price': near['open'], 'high_price': near['max'],
        'low_price': near['min'], 'close_price': near['close'],
        'volume': near['volume'],
        'open_interest': near.get('open_interest', 0),
    })
    # 收盤價為 0 的列是無效報價（無成交的遠月殘留），留著會汙染報酬率
    return out[out['close_price'] > 0].reset_index(drop=True)


def upsert(rows: pd.DataFrame) -> int:
    if rows.empty:
        return 0
    from psycopg2.extras import execute_values
    values = [(r.futures_id, r.trade_date, r.session, r.contract_date,
               float(r.open_price), float(r.high_price), float(r.low_price),
               float(r.close_price), int(r.volume or 0), int(r.open_interest or 0))
              for r in rows.itertuples()]
    with get_conn() as conn:
        with conn.cursor() as cur:
            execute_values(cur, """
                INSERT INTO futures_daily
                  (futures_id, trade_date, session, contract_date,
                   open_price, high_price, low_price, close_price, volume, open_interest)
                VALUES %s
                ON CONFLICT (futures_id, trade_date, session) DO UPDATE SET
                  contract_date = EXCLUDED.contract_date,
                  open_price = EXCLUDED.open_price, high_price = EXCLUDED.high_price,
                  low_price  = EXCLUDED.low_price,  close_price = EXCLUDED.close_price,
                  volume = EXCLUDED.volume, open_interest = EXCLUDED.open_interest
            """, values)
        conn.commit()
    return len(values)


def backfill(ids, start: date, end: date, pause: float = 1.0) -> dict:
    total = {}
    for fid in ids:
        n = 0
        cur = start
        while cur <= end:
            chunk_end = min(cur + pd.Timedelta(days=CHUNK_DAYS - 1).to_pytimedelta(), end)
            try:
                df = fetch_range(fid, cur, chunk_end)
                n += upsert(df)
                logger.info('%s %s ~ %s：%d 筆', fid, cur, chunk_end, len(df))
            except Exception as e:
                logger.warning('%s %s ~ %s 失敗：%s', fid, cur, chunk_end, str(e)[:120])
            cur = chunk_end + pd.Timedelta(days=1).to_pytimedelta()
            time.sleep(pause)          # FinMind 匿名額度有限，別打太快
        total[fid] = n
    return total


def summary() -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT futures_id, session, count(*), min(trade_date), max(trade_date),
                       round(avg(volume))
                  FROM futures_daily GROUP BY 1, 2 ORDER BY 1, 2
            """)
            print('\n代號   時段            筆數    起始         最新         日均量')
            for fid, ses, n, a, b, v in cur.fetchall():
                print(f'{fid:<6} {ses:<14} {n:>6}  {a}  {b}  {int(v or 0):>9,}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--ids', nargs='+', default=DEFAULT_IDS)
    ap.add_argument('--start', default=DEFAULT_START)
    ap.add_argument('--pause', type=float, default=1.0)
    args = ap.parse_args()

    start = date.fromisoformat(args.start)
    end = date.today()
    logger.info('回補 %s：%s ~ %s', args.ids, start, end)
    total = backfill(args.ids, start, end, args.pause)
    logger.info('完成：%s', total)
    summary()


if __name__ == '__main__':
    main()
