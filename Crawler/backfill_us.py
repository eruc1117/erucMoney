"""
美股資料回補（Iteration 14）

為何要美股：台股在美股收盤後開盤，**隔夜美股走勢是台股次日的領先資訊**，
而現有模型完全沒有這項輸入。半導體類股（NVDA/AMD/MU/TSM ADR）與台灣電子股
的連動尤其直接。

標的選擇原則——每一檔都要有明確的預期作用，不是湊數：
    指數        SPY  大盤情緒 / QQQ  科技股情緒
    半導體      SOXX 費半 ETF、NVDA、AMD、MU（記憶體）、INTC、AVGO
    台股 ADR    TSM（台積電 ADR，與 2330 直接對應）、UMC（聯電 ADR，對應 2303）
    大型科技    AAPL、MSFT（供應鏈需求端）

用法：
    python backfill_us.py                    # 全部標的，回溯至 1990
    python backfill_us.py --tickers NVDA TSM
    python backfill_us.py --start 2015-01-01
"""

import argparse
import logging
import time
from datetime import date

from db.connection import get_conn
from scrapers.finmind_scraper import FinMindScraper

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

DEFAULT_START = "1990-01-01"

# 標的清單是 us_panel、排程回補、前端下拉的唯一來源。
# Iteration 14 挑了前 12 檔；Iteration 34 依「訊號來自台灣」重新檢討，
# 以巢狀走查（UnifiedModel/select_us_universe.py）加入 11 檔與台灣供應鏈
# 有明確機制的標的，原 12 檔全數過門檻留任。
# SPY／QQQ／SOXX 是大盤特徵的來源（us_panel 的 usmkt／cs 區塊），不可移除。
TICKERS = [
    ('SPY',  'SPDR S&P 500 ETF',          'index'),
    ('QQQ',  'Invesco QQQ Trust',          'index'),
    ('SOXX', 'iShares Semiconductor ETF',  'semiconductor'),
    ('SMH',  'VanEck Semiconductor ETF',   'semiconductor'),
    ('NVDA', 'NVIDIA',                     'semiconductor'),
    ('AMD',  'Advanced Micro Devices',     'semiconductor'),
    ('MU',   'Micron Technology',          'semiconductor'),
    ('INTC', 'Intel',                      'semiconductor'),
    ('AVGO', 'Broadcom',                   'semiconductor'),
    ('QCOM', 'Qualcomm',                   'semiconductor'),
    ('MRVL', 'Marvell',                    'semiconductor'),
    ('ASML', 'ASML Holding',               'equipment'),
    ('AMAT', 'Applied Materials',          'equipment'),
    ('LRCX', 'Lam Research',               'equipment'),
    ('KLAC', 'KLA',                        'equipment'),
    ('TSM',  'TSMC ADR',                   'tw_adr'),
    ('UMC',  'UMC ADR',                    'tw_adr'),
    ('ASX',  'ASE Technology ADR',         'tw_adr'),
    ('HIMX', 'Himax ADR',                  'tw_adr'),
    ('SIMO', 'Silicon Motion ADR',         'tw_adr'),
    # EWT 本身就是台股（在美國時區交易）：台股當日盤預測它的開盤跳空近乎套套邏輯。
    # 留著是因為「台股 ETF 今晚在美國會怎麼開」對使用者仍有用，但報表不拿它撐平均。
    ('EWT',  'iShares MSCI Taiwan ETF',    'tw_etf'),
    ('AAPL', 'Apple',                      'bigtech'),
    ('MSFT', 'Microsoft',                  'bigtech'),
]


def ensure_tickers():
    with get_conn() as conn:
        with conn.cursor() as cur:
            for t, name, cat in TICKERS:
                cur.execute("""
                    INSERT INTO us_tickers (ticker, name, category)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (ticker) DO UPDATE
                        SET name = EXCLUDED.name, category = EXCLUDED.category
                """, (t, name, cat))
        conn.commit()


def upsert_us_prices(rows: list) -> int:
    if not rows:
        return 0
    n = 0
    with get_conn() as conn:
        with conn.cursor() as cur:
            for r in rows:
                # 收盤價非正的列直接跳過（停牌／無成交日），避免報酬率計算爆炸
                if not r.get('close_price') or r['close_price'] <= 0:
                    continue
                cur.execute("""
                    INSERT INTO us_daily_prices
                        (ticker, trade_date, open_price, high_price, low_price,
                         close_price, adj_close, volume)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (ticker, trade_date) DO UPDATE SET
                        open_price  = EXCLUDED.open_price,
                        high_price  = EXCLUDED.high_price,
                        low_price   = EXCLUDED.low_price,
                        close_price = EXCLUDED.close_price,
                        adj_close   = EXCLUDED.adj_close,
                        volume      = EXCLUDED.volume
                """, (r['ticker'], r['trade_date'], r['open_price'], r['high_price'],
                      r['low_price'], r['close_price'], r['adj_close'], r['volume']))
                n += 1
        conn.commit()
    logger.info("[us_daily_prices] upsert %d 筆", n)
    return n


def run(start=None, tickers=None, retry_wait: int = 0, pause: float = 2.0) -> dict:
    """
    可被匯入的回補入口（排程用）。回傳 {'rows': n, 'failed': [...]}。

    `retry_wait=0` 是排程的預設：額度耗盡時直接放棄這一輪，不要在排程執行緒裡
    睡半小時——下一次排程會再補一次，而缺一天的美股資料不值得卡住整個排程。
    """
    ensure_tickers()
    tickers = list(tickers) if tickers else [t for t, _, _ in TICKERS]
    start = start or date.fromisoformat(DEFAULT_START)
    if isinstance(start, str):
        start = date.fromisoformat(start)
    today = date.today()
    logger.info("回補美股 %d 檔：%s ~ %s", len(tickers), start, today)

    total, failed = 0, []
    for i, tk in enumerate(tickers, 1):
        attempts = 0
        while True:
            attempts += 1
            try:
                sc = FinMindScraper(stock_ids=[tk], start_date=start, end_date=today)
                rows = sc.fetch_us_prices()
                if not rows:
                    raise RuntimeError("回傳空（疑似額度耗盡或標的不存在）")
                n = upsert_us_prices(rows)
                total += n
                logger.info("[%d/%d] %s %d 筆", i, len(tickers), tk, n)
                break
            except Exception as e:
                if retry_wait > 0 and attempts <= 8:
                    logger.warning("[%d/%d] %s 第 %d 次失敗（%s），%d 秒後重試",
                                   i, len(tickers), tk, attempts, e, retry_wait)
                    time.sleep(retry_wait)
                    continue
                failed.append(tk)
                logger.error("[%d/%d] %s 放棄：%s", i, len(tickers), tk, e)
                break
        time.sleep(pause)

    logger.info("完成：共 %d 筆%s", total,
                f"；失敗：{' '.join(failed)}" if failed else "")
    return {'rows': total, 'failed': failed}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--start', default=DEFAULT_START)
    ap.add_argument('--tickers', nargs='+', default=None)
    ap.add_argument('--retry-wait', type=int, default=300)
    args = ap.parse_args()

    run(start=date.fromisoformat(args.start), tickers=args.tickers,
        retry_wait=args.retry_wait)


if __name__ == "__main__":
    main()
