"""
亞洲主要指數回補（Iteration 29）：韓股 KOSPI、日股 Nikkei 225

為何是這兩個：它們比台股早一小時開盤，開盤價在台股開盤前就知道。

    韓國 KRX  09:00 KST = 08:00 台北
    日本 TSE  09:00 JST = 08:00 台北
    台灣 TWSE 09:00 台北

FinMind 沒有國際指數，改用 yfinance。指數沒有成交量的話會是 0，正常。

用法：
    python backfill_index.py                      # 兩個指數，2015 起
    python backfill_index.py --symbols ^KS11 --start 2020-01-01
"""

import argparse
import logging
from datetime import date, timedelta

import pandas as pd

from db.connection import get_conn

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

SYMBOLS = ['^KS11', '^N225']
DEFAULT_START = '2015-01-01'


def fetch(symbols, start: str, end: str) -> pd.DataFrame:
    import yfinance as yf
    raw = yf.download(symbols, start=start, end=end, progress=False,
                      auto_adjust=False, group_by='column')
    if raw is None or raw.empty:
        return pd.DataFrame()

    frames = []
    for sym in symbols:
        try:
            sub = pd.DataFrame({
                'trade_date': raw.index.date,
                'open_price': raw[('Open', sym)].values,
                'high_price': raw[('High', sym)].values,
                'low_price': raw[('Low', sym)].values,
                'close_price': raw[('Close', sym)].values,
                'volume': raw[('Volume', sym)].values if ('Volume', sym) in raw.columns else 0,
            })
        except KeyError:
            logger.warning('%s 無資料', sym)
            continue
        sub['symbol'] = sym
        # 指數在休市日會回傳 NaN 列，留著會讓報酬率算出 NaN 缺口
        sub = sub.dropna(subset=['close_price'])
        sub = sub[sub['close_price'] > 0]
        frames.append(sub)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def upsert(df: pd.DataFrame) -> int:
    if df.empty:
        return 0
    from psycopg2.extras import execute_values
    values = [(r.symbol, r.trade_date, float(r.open_price), float(r.high_price),
               float(r.low_price), float(r.close_price), int(r.volume or 0))
              for r in df.itertuples()]
    with get_conn() as conn:
        with conn.cursor() as cur:
            execute_values(cur, """
                INSERT INTO index_daily_prices
                  (symbol, trade_date, open_price, high_price, low_price,
                   close_price, volume)
                VALUES %s
                ON CONFLICT (symbol, trade_date) DO UPDATE SET
                  open_price = EXCLUDED.open_price, high_price = EXCLUDED.high_price,
                  low_price = EXCLUDED.low_price, close_price = EXCLUDED.close_price,
                  volume = EXCLUDED.volume
            """, values)
        conn.commit()
    return len(values)


def run(symbols=None, start=None) -> int:
    """可被匯入的回補入口（排程用）。回傳寫入筆數。"""
    symbols = list(symbols) if symbols else SYMBOLS
    start = str(start or DEFAULT_START)
    # yfinance 的 end 不含端點，用 today 會永遠少抓當日（韓日收盤早於台股，
    # 當日資料在台股盤後就已可取得，漏掉等於白白晚一天）。
    end = (date.today() + timedelta(days=1)).isoformat()
    logger.info('回補 %s：%s ~ %s（end 不含端點）', symbols, start, end)
    n = upsert(fetch(symbols, start, end))
    logger.info('寫入 %d 筆', n)
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--symbols', nargs='+', default=SYMBOLS)
    ap.add_argument('--start', default=DEFAULT_START)
    args = ap.parse_args()

    run(args.symbols, args.start)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT symbol, count(*), min(trade_date), max(trade_date)
                  FROM index_daily_prices GROUP BY 1 ORDER BY 1
            """)
            print('\n代號     筆數    起始         最新')
            for sym, c, a, b in cur.fetchall():
                print(f'{sym:<8} {c:>5}  {a}  {b}')


if __name__ == '__main__':
    main()
