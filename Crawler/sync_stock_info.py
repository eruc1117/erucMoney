"""
同步 stock_info 基本資料

以 stock_daily_prices 實際存在的股票為準，透過 FinMind taiwan_stock_info()
補齊 stock_info 的名稱 / 市場別 / 產業別；並清除「無名稱且無任何行情資料」的殘留列。

用法：
    python sync_stock_info.py            # 同步 + 清理
    python sync_stock_info.py --dry-run  # 只顯示將執行的動作，不寫入
"""

import argparse
import logging
from datetime import date

from db.connection import get_conn
from db.repository import upsert_stock_info
from scrapers.finmind_scraper import FinMindScraper

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)


def price_stock_ids() -> list[str]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT stock_id FROM stock_daily_prices ORDER BY stock_id")
            return [r[0] for r in cur.fetchall()]


def orphan_info_rows() -> list[str]:
    """stock_info 中名稱缺漏（或名稱=代碼）且完全沒有行情資料的殘留列。"""
    sql = """
        SELECT i.stock_id
        FROM stock_info i
        LEFT JOIN (SELECT DISTINCT stock_id FROM stock_daily_prices) p USING (stock_id)
        WHERE p.stock_id IS NULL
          AND (i.stock_name IS NULL OR i.stock_name = '' OR i.stock_name = i.stock_id)
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            return [r[0] for r in cur.fetchall()]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="只顯示動作，不寫入 DB")
    args = parser.parse_args()

    ids = price_stock_ids()
    logger.info("行情表共 %d 檔股票：%s", len(ids), " ".join(ids))

    scraper = FinMindScraper(stock_ids=ids, start_date=date.today())
    raw = scraper.fetch_stock_info()

    # FinMind 同一檔股票可能回傳多筆（泛用「電子工業」+ 具體產業別），
    # 去重並優先保留具體產業別
    dedup: dict[str, dict] = {}
    for info in raw:
        sid = info["stock_id"]
        if sid not in dedup or dedup[sid]["industry_type"] in (None, "", "電子工業"):
            dedup[sid] = info
    infos = list(dedup.values())
    logger.info("FinMind 取得 %d 筆原始資料，去重後 %d 檔", len(raw), len(infos))

    fetched = {info["stock_id"] for info in infos}
    missing = [sid for sid in ids if sid not in fetched]
    if missing:
        logger.warning("FinMind 查無以下股票（可能已下市）：%s", " ".join(missing))

    if args.dry_run:
        for info in infos:
            logger.info("[dry-run] upsert：%(stock_id)s %(stock_name)s %(market_type)s %(industry_type)s", info)
    else:
        for info in infos:
            upsert_stock_info(**info)
        logger.info("已 upsert %d 筆 stock_info", len(infos))

    orphans = orphan_info_rows()
    if orphans:
        if args.dry_run:
            logger.info("[dry-run] 將刪除殘留列：%s", " ".join(orphans))
        else:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM stock_info WHERE stock_id = ANY(%s)", (orphans,))
                conn.commit()
            logger.info("已刪除殘留列：%s", " ".join(orphans))
    else:
        logger.info("無殘留列需清理")


if __name__ == "__main__":
    main()
