"""
歷史股價批次爬蟲排程

策略：
  - 將目標日期範圍切成 1 個月一段
  - 每段爬完後等待指定秒數，再爬下一段
  - 已有足夠資料的月份自動跳過（支援中斷後繼續）

使用方式：
    python fetch_history.py 2330
    python fetch_history.py 2317 --years 3
    python fetch_history.py 2330 --interval 60   # 改成每月等 60 秒
    python fetch_history.py 2330 --force         # 強制重抓，忽略已有資料
"""

import argparse
import logging
import sys
import time
from datetime import date, timedelta

import psycopg2

from config import DB
from db.repository import upsert_chip_analysis, upsert_daily_prices
from scrapers.finmind_scraper import FinMindScraper

# ── 預設值 ────────────────────────────────────────────────────────────────────
DEFAULT_YEARS    = 5    # 抓取年數
DEFAULT_INTERVAL = 120  # 每月間隔（秒）
SKIP_THRESHOLD   = 15   # 一個月若已有 >= 15 筆視為完整，可跳過

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


# ── 日期工具 ──────────────────────────────────────────────────────────────────

def _monthly_ranges(start: date, end: date):
    """
    將 [start, end] 切成月份片段，每次 yield (month_start, month_end)。
    month_start 固定為月份第 1 天；month_end 為當月最後一天（不超過 end）。
    """
    current = date(start.year, start.month, 1)
    while current <= end:
        if current.month == 12:
            next_month = date(current.year + 1, 1, 1)
        else:
            next_month = date(current.year, current.month + 1, 1)
        month_end = min(next_month - timedelta(days=1), end)
        yield current, month_end
        current = next_month


# ── DB 查詢 ───────────────────────────────────────────────────────────────────

def _count_prices(stock_id: str, start: date, end: date) -> int:
    """回傳該股票在指定月份的行情筆數（用於判斷是否已抓過）"""
    sql = """
        SELECT COUNT(*) FROM stock_daily_prices
        WHERE stock_id = %s AND trade_date BETWEEN %s AND %s
    """
    conn = psycopg2.connect(**DB)
    try:
        with conn.cursor() as cur:
            cur.execute(sql, (stock_id, start, end))
            return cur.fetchone()[0]
    finally:
        conn.close()


# ── 單月爬取 ──────────────────────────────────────────────────────────────────

def _fetch_month(stock_id: str, start: date, end: date) -> tuple[int, int]:
    """
    爬取單月行情 + 籌碼並寫入 DB。

    Returns:
        (price_rows, chip_rows)  — 實際寫入筆數
    """
    scraper = FinMindScraper(
        stock_ids=[stock_id],
        start_date=start,
        end_date=end,
    )
    prices = scraper.fetch_prices()
    chips  = scraper.fetch_chips()

    price_rows = upsert_daily_prices(prices)
    chip_rows  = upsert_chip_analysis(chips)
    return price_rows, chip_rows


# ── 主流程 ────────────────────────────────────────────────────────────────────

def run(
    stock_id: str,
    years: int    = DEFAULT_YEARS,
    interval: int = DEFAULT_INTERVAL,
    force: bool   = False,
):
    today      = date.today()
    start_date = date(today.year - years, today.month, today.day)
    months     = list(_monthly_ranges(start_date, today))
    total      = len(months)

    logger.info("=" * 60)
    logger.info("股票    ：%s", stock_id)
    logger.info("範圍    ：%s ~ %s", start_date, today)
    logger.info("共      ：%d 個月", total)
    logger.info("間隔    ：%d 秒 / 月", interval)
    logger.info("強制重抓：%s", "是" if force else "否（已有資料月份自動跳過）")
    logger.info("=" * 60)

    fetched = 0  # 實際發出請求的月份數

    for i, (m_start, m_end) in enumerate(months, 1):
        label  = m_start.strftime("%Y-%m")
        prefix = f"[{i:>2}/{total}] {label}"

        # ── 跳過已有足夠資料的月份 ────────────────────────────────────────────
        if not force:
            existing = _count_prices(stock_id, m_start, m_end)
            if existing >= SKIP_THRESHOLD:
                logger.info("%s  ✓ 已有 %d 筆，跳過", prefix, existing)
                continue

        # ── 爬取 ──────────────────────────────────────────────────────────────
        logger.info("%s  → 爬取中 (%s ~ %s)", prefix, m_start, m_end)
        try:
            price_rows, chip_rows = _fetch_month(stock_id, m_start, m_end)
            logger.info("%s  ✓ 行情 %d 筆，籌碼 %d 筆", prefix, price_rows, chip_rows)
            fetched += 1
        except Exception as exc:
            logger.error("%s  ✗ 失敗：%s", prefix, exc)
            # 失敗仍照常等待，避免短時間內連續重試
            fetched += 1

        # ── 等待（最後一個月或剩餘全部跳過時不等）────────────────────────────
        remaining_unfetched = sum(
            1 for j, (s, e) in enumerate(months[i:], i + 1)
            if force or _count_prices(stock_id, s, e) < SKIP_THRESHOLD
        )
        if remaining_unfetched > 0:
            logger.info("等待 %d 秒（剩餘約 %d 個月待爬）...\n", interval, remaining_unfetched)
            time.sleep(interval)

    logger.info("=" * 60)
    logger.info("完成！共發出 %d 次請求，資料已寫入 DB。", fetched)
    logger.info("=" * 60)


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="歷史股價批次爬蟲（每月分批，間隔固定秒數）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
範例：
  python fetch_history.py 2330                  # 2330，抓 5 年，每月等 2 分鐘
  python fetch_history.py 2317 --years 3        # 2317，只抓 3 年
  python fetch_history.py 2330 --interval 60    # 縮短等待至 60 秒（測試用）
  python fetch_history.py 2330 --force          # 強制重抓所有月份
        """,
    )
    parser.add_argument("stock_id",
                        help="股票代碼（如 2330）")
    parser.add_argument("--years",    type=int, default=DEFAULT_YEARS,
                        help=f"抓取歷史年數（預設 {DEFAULT_YEARS}）")
    parser.add_argument("--interval", type=int, default=DEFAULT_INTERVAL,
                        help=f"每月間隔秒數（預設 {DEFAULT_INTERVAL}）")
    parser.add_argument("--force",    action="store_true",
                        help="強制重新抓取所有月份（忽略已有資料）")

    args = parser.parse_args()
    run(args.stock_id, years=args.years, interval=args.interval, force=args.force)


if __name__ == "__main__":
    main()
