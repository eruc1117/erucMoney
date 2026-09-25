"""
除權息資料回補（Iteration 17）

修正開盤跳空模型的系統性誤差：除權息日的價格缺口是配息／配股造成的
**機械性**結果，與美股隔夜走勢無關，模型卻會把它當成真實跳空學習。

例：2330 於 2026-06-11 除息 6 元，前日收盤 2255.0 → 參考價 2248.99，
    缺口 −0.27% 純粹來自配息。

用法：
    python backfill_dividend.py                    # 全部追蹤股票
    python backfill_dividend.py --stocks 2330 0050
    python backfill_dividend.py --start 2000-01-01
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


def tracked_ids() -> list[str]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT stock_id FROM stock_info "
                        "WHERE is_tracking = TRUE ORDER BY stock_id")
            return [r[0] for r in cur.fetchall()]


def upsert_dividends(rows: list) -> int:
    if not rows:
        return 0
    n = 0
    with get_conn() as conn:
        with conn.cursor() as cur:
            for r in rows:
                cur.execute("""
                    INSERT INTO stock_dividend_result
                        (stock_id, ex_date, before_price, reference_price,
                         dividend, dividend_type)
                    VALUES (%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (stock_id, ex_date) DO UPDATE SET
                        before_price    = EXCLUDED.before_price,
                        reference_price = EXCLUDED.reference_price,
                        dividend        = EXCLUDED.dividend,
                        dividend_type   = EXCLUDED.dividend_type
                """, (r['stock_id'], r['ex_date'], r['before_price'],
                      r['reference_price'], r['dividend'], r['dividend_type']))
                n += 1
        conn.commit()
    logger.info("[stock_dividend_result] upsert %d 筆", n)
    return n


def fetch_dividends(ids: list, start: date, retry_wait: int = 300) -> tuple[int, list]:
    """回補指定股票的除權息事件，回傳 (寫入筆數, 失敗的股票代碼)。

    抽成函式是為了讓排程（scheduler.job_stock）能在每日抓完行情後直接呼叫——
    新增行情而不更新公司行動，adj_close 會用過期的事件表重建。
    """
    today = date.today()
    total, failed = 0, []
    for i, sid in enumerate(ids, 1):
        attempts = 0
        while True:
            attempts += 1
            try:
                sc = FinMindScraper(stock_ids=[sid], start_date=start, end_date=today)
                rows = sc.fetch_dividend_results()
                n = upsert_dividends(rows)
                total += n
                logger.info("[%d/%d] %s %d 筆", i, len(ids), sid, n)
                break
            except Exception as e:
                if retry_wait > 0 and attempts <= 8:
                    logger.warning("[%d/%d] %s 第 %d 次失敗（%s），%d 秒後重試",
                                   i, len(ids), sid, attempts, e, retry_wait)
                    time.sleep(retry_wait)
                    continue
                failed.append(sid)
                logger.error("[%d/%d] %s 放棄：%s", i, len(ids), sid, e)
                break
        time.sleep(2)
    return total, failed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--start', default=DEFAULT_START)
    ap.add_argument('--stocks', nargs='+', default=None)
    ap.add_argument('--retry-wait', type=int, default=300)
    args = ap.parse_args()

    ids = args.stocks or tracked_ids()
    start = date.fromisoformat(args.start)
    logger.info("回補除權息 %d 檔：%s ~ %s", len(ids), start, date.today())

    total, failed = fetch_dividends(ids, start, args.retry_wait)

    logger.info("完成：共 %d 筆%s", total,
                f"；失敗：{' '.join(failed)}" if failed else "")


if __name__ == "__main__":
    main()
