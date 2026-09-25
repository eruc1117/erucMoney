"""
批次爬取 Target.md 所有股票的 5 年歷史資料

策略：
  - 解析 Target.md 取得完整股票清單
  - 逐支股票，依月份分批爬取（一次 1 個月）
  - 每次爬完後隨機等待 20 秒 ~ 3 分鐘，模擬人工操作節奏
  - 已有足夠資料的月份自動跳過（支援中斷後繼續）

使用方式：
    python fetch_all_history.py                       # 全部股票，抓 5 年
    python fetch_all_history.py --years 3             # 只抓 3 年
    python fetch_all_history.py --stock 2330          # 只跑指定股票（其餘跳過）
    python fetch_all_history.py --force               # 強制重抓，忽略已有資料
"""

import argparse
import logging
import random
import re
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import psycopg2

from config import DB
from db.repository import upsert_chip_analysis, upsert_daily_prices
from scrapers.finmind_scraper import FinMindScraper

# ── 設定 ──────────────────────────────────────────────────────────────────────

TARGET_MD      = Path(__file__).parent.parent / "AI" / "UserDoc" / "Target.md"
DEFAULT_YEARS  = 5
DELAY_MIN_SEC  = 20    # 最短等待秒數
DELAY_MAX_SEC  = 180   # 最長等待秒數（3 分鐘）
SKIP_THRESHOLD = 15    # 一個月有 >= 15 筆交易日資料視為完整，自動跳過

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


# ── 解析 Target.md ────────────────────────────────────────────────────────────

def parse_targets(path: Path) -> list[tuple[str, str]]:
    """
    解析 CSV 格式的 Target.md，回傳 [(stock_id, company_name), ...]。
    格式：股票代碼,公司名稱,... （第一行為標題，自動跳過）
    """
    results = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("股票代碼"):
            continue
        parts = line.split(",", 2)
        if len(parts) >= 2 and re.match(r"^\d{4,5}$", parts[0].strip()):
            results.append((parts[0].strip(), parts[1].strip()))
    return results


# ── 日期工具 ──────────────────────────────────────────────────────────────────

def monthly_ranges(start: date, end: date):
    """將 [start, end] 切成月份片段，yield (month_start, month_end)。"""
    current = date(start.year, start.month, 1)
    while current <= end:
        if current.month == 12:
            next_month = date(current.year + 1, 1, 1)
        else:
            next_month = date(current.year, current.month + 1, 1)
        month_end = min(next_month - timedelta(days=1), end)
        yield current, month_end
        current = next_month


# ── DB 工具 ───────────────────────────────────────────────────────────────────

def count_prices(stock_id: str, start: date, end: date) -> int:
    """回傳該股票在指定月份範圍內的行情筆數。"""
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

def fetch_month(stock_id: str, start: date, end: date) -> tuple[int, int]:
    """爬取單月行情 + 籌碼並寫入 DB，回傳 (price_rows, chip_rows)。"""
    scraper = FinMindScraper(stock_ids=[stock_id], start_date=start, end_date=end)
    prices  = scraper.fetch_prices()
    chips   = scraper.fetch_chips()
    return upsert_daily_prices(prices), upsert_chip_analysis(chips)


# ── 主流程 ────────────────────────────────────────────────────────────────────

def run(
    years:      int  = DEFAULT_YEARS,
    force:      bool = False,
    only_stock: str  = None,
):
    # 解析股票清單
    targets = parse_targets(TARGET_MD)
    if not targets:
        logger.error("Target.md 解析失敗，請確認路徑：%s", TARGET_MD)
        sys.exit(1)

    # 若指定 --stock，只保留該支
    if only_stock:
        targets = [(sid, name) for sid, name in targets if sid == only_stock]
        if not targets:
            logger.error("Target.md 中找不到股票 %s", only_stock)
            sys.exit(1)

    today      = date.today()
    start_date = date(today.year - years, today.month, today.day)
    all_months = list(monthly_ranges(start_date, today))

    logger.info("=" * 65)
    logger.info("股票數量  ：%d 支", len(targets))
    logger.info("歷史範圍  ：%s ~ %s（%d 個月）", start_date, today, len(all_months))
    logger.info("等待區間  ：%d ~ %d 秒（隨機）", DELAY_MIN_SEC, DELAY_MAX_SEC)
    logger.info("強制重抓  ：%s", "是" if force else "否（已有月份自動跳過）")
    logger.info("=" * 65)

    total_stocks  = len(targets)
    total_fetched = 0   # 累計實際發出的請求次數

    for si, (stock_id, name) in enumerate(targets, 1):
        logger.info("")
        logger.info("▶  [股票 %d/%d] %s %s", si, total_stocks, stock_id, name)

        # 計算這支股票需要爬哪幾個月
        need = [
            (m_start, m_end)
            for m_start, m_end in all_months
            if force or count_prices(stock_id, m_start, m_end) < SKIP_THRESHOLD
        ]
        skip_count = len(all_months) - len(need)

        if skip_count:
            logger.info("   跳過已完整月份：%d 個月 | 待爬：%d 個月", skip_count, len(need))
        if not need:
            logger.info("   此股票資料已完整，略過。")
            continue

        for mi, (m_start, m_end) in enumerate(need, 1):
            label  = m_start.strftime("%Y-%m")
            prefix = f"   [{mi:>2}/{len(need)}] {label}"

            logger.info("%s → 爬取中 ...", prefix)
            try:
                p, c = fetch_month(stock_id, m_start, m_end)
                logger.info("%s ✓  行情 %d 筆，籌碼 %d 筆", prefix, p, c)
                total_fetched += 1
            except Exception as exc:
                logger.error("%s ✗  失敗：%s", prefix, exc)
                total_fetched += 1  # 失敗也計入，仍需等待避免連打

            # 判斷是否還有後續工作；最後一次不等
            is_last_request = (mi == len(need)) and (si == total_stocks)
            if not is_last_request:
                delay = random.randint(DELAY_MIN_SEC, DELAY_MAX_SEC)
                logger.info("   等待 %d 秒後繼續 ...", delay)
                time.sleep(delay)

    logger.info("")
    logger.info("=" * 65)
    logger.info("全部完成！共發出 %d 次爬蟲請求。", total_fetched)
    logger.info("=" * 65)


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="批次爬取 Target.md 所有股票的歷史行情與籌碼",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
範例：
  python fetch_all_history.py                     # 全部 20 支，5 年歷史
  python fetch_all_history.py --years 3           # 只抓近 3 年
  python fetch_all_history.py --stock 2330        # 只跑 2330（其他跳過）
  python fetch_all_history.py --force             # 強制重抓所有月份
        """,
    )
    parser.add_argument("--years",  type=int, default=DEFAULT_YEARS,
                        help=f"抓取歷史年數（預設 {DEFAULT_YEARS}）")
    parser.add_argument("--stock",  type=str, default=None,
                        help="只爬指定股票代碼（如 2330），其餘略過")
    parser.add_argument("--force",  action="store_true",
                        help="強制重新抓取所有月份")
    args = parser.parse_args()

    run(years=args.years, force=args.force, only_stock=args.stock)


if __name__ == "__main__":
    main()
