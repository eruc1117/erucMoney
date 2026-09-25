"""
行情資料回補工具

背景：finmind_scraper 曾因 FinMind 欄名對應錯誤（"Trading Volume" vs "Trading_Volume"），
導致 stock_daily_prices 的 volume / turnover_value / transaction_count 全為 NULL；
且行情資料停留在過去。修正欄名後以本工具一次回補。

FinMind taiwan_stock_daily 支援單一呼叫抓整段日期範圍 → 每檔股票僅 1 次 API 呼叫，
22 檔共 22 次，匿名額度（30 次/h）內可完成。

用法：
    python backfill_prices.py                     # 全部追蹤股票，2021-03-01 ~ 今日
    python backfill_prices.py --start 2026-03-01  # 自訂起始日
    python backfill_prices.py --chips             # 同時回補籌碼（額外 22 次呼叫，注意額度）
    python backfill_prices.py --holding-only      # 只回補外資持股統計（Iteration 35，每檔 1 次呼叫）
"""

import argparse
import logging
import time
from datetime import date

from db.connection import get_conn
from db.repository import upsert_daily_prices, upsert_chip_analysis, upsert_foreign_holding
from scrapers.finmind_scraper import FinMindScraper

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

DEFAULT_START = "2021-03-01"


def tracked_ids() -> list[str]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT stock_id FROM stock_info WHERE is_tracking = TRUE ORDER BY stock_id")
            return [r[0] for r in cur.fetchall()]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default=DEFAULT_START, help="起始日 YYYY-MM-DD")
    parser.add_argument("--chips", action="store_true", help="同時回補三大法人籌碼")
    parser.add_argument("--chips-only", action="store_true", help="只回補籌碼（不抓行情）")
    parser.add_argument("--holding", action="store_true", help="同時回補外資持股統計")
    parser.add_argument("--holding-only", action="store_true", help="只回補外資持股統計（不抓行情、籌碼）")
    parser.add_argument("--stocks", nargs="+", default=None,
                        help="只回補指定股票（省略則為全部追蹤股票）")
    parser.add_argument("--retry-wait", type=int, default=600,
                        help="疑似額度耗盡時等待秒數後重試（預設 600；0=不重試）")
    args = parser.parse_args()

    do_prices  = not (args.chips_only or args.holding_only)
    do_chips   = args.chips or args.chips_only
    do_holding = args.holding or args.holding_only

    # --stocks 可指定尚未列入追蹤清單的代碼（例如新加入的 ETF）
    ids = args.stocks if args.stocks else tracked_ids()
    start = date.fromisoformat(args.start)
    today = date.today()
    logger.info("回補 %d 檔：%s ~ %s（行情=%s 籌碼=%s 外資持股=%s）",
                len(ids), start, today, do_prices, do_chips, do_holding)

    total_prices, total_chips, total_holding, failed = 0, 0, 0, []
    for i, sid in enumerate(ids, 1):
        attempts = 0
        while True:
            attempts += 1
            try:
                scraper = FinMindScraper(stock_ids=[sid], start_date=start, end_date=today)
                msg = f"[{i}/{len(ids)}] {sid}"
                ok = True
                if do_prices:
                    prices = scraper.fetch_prices()
                    n = upsert_daily_prices([p for p in prices if p])
                    total_prices += n
                    msg += f" 行情 {n} 筆"
                if do_chips:
                    chips = scraper.fetch_chips()
                    # fetch_chips 內部吃掉例外只留 log；空結果視為疑似被限流
                    if not chips:
                        ok = False
                    c = upsert_chip_analysis(chips)
                    total_chips += c
                    msg += f" 籌碼 {c} 筆"
                if do_holding:
                    holding = scraper.fetch_foreign_holding()
                    if not holding:
                        ok = False
                    h = upsert_foreign_holding(holding)
                    total_holding += h
                    msg += f" 外資持股 {h} 筆"
                if ok:
                    logger.info(msg)
                    break
                raise RuntimeError("籌碼／外資持股回傳空（疑似額度耗盡）")
            except Exception as e:
                if args.retry_wait > 0 and attempts <= 12:
                    logger.warning("[%d/%d] %s 第 %d 次失敗（%s），%d 秒後重試",
                                   i, len(ids), sid, attempts, e, args.retry_wait)
                    time.sleep(args.retry_wait)
                    continue
                failed.append(sid)
                logger.error("[%d/%d] %s 放棄：%s", i, len(ids), sid, e)
                break
        time.sleep(2)   # 呼叫間隔，降低被限流機率

    logger.info("完成：行情共 %d 筆，籌碼共 %d 筆，外資持股共 %d 筆%s",
                total_prices, total_chips, total_holding,
                f"；失敗：{' '.join(failed)}" if failed else "")

    # 本工具只寫 close_price，新增的列 adj_close 是 NULL；而算報酬一律用
    # adj_close（Iteration 18）。不重建的話那幾天等於不存在，且症狀看起來
    # 只是「還沒有資料」。排程走 scheduler._refresh_adj_close 自動處理，
    # 手動跑就得自己補這一步。
    if do_prices:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT COUNT(*) FROM stock_daily_prices
                    WHERE adj_close IS NULL AND trade_date >= %s
                """, (start,))
                missing = cur.fetchone()[0]
        if missing:
            logger.warning("尚有 %d 筆 adj_close 未建立 → 請接著執行："
                           "python backfill_dividend.py --start %s && "
                           "python rebuild_adj_close.py", missing, start)


if __name__ == "__main__":
    main()
