"""
程式入口點

用法：
  python main.py --mode server                         # 啟動 FastAPI HTTP 伺服器（port 8000）
  python main.py --mode stock                          # 立即爬取今日股票資料並寫入 DB
  python main.py --mode schedule                       # 啟動排程器（持續運行）
  python main.py --mode stock --stocks 2330 2317 2454  # 指定股票代碼
  python main.py --mode stock --date 20260310          # 指定日期
"""

import argparse
import logging
from datetime import date, datetime

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

DEFAULT_STOCK_IDS  = ["2330", "2317", "2454", "2308", "3008"]
NEWS_DEFAULT_START = "2021-03-23"
NEWS_DEFAULT_END   = date.today().isoformat()   # 今日


def run_stock(stock_ids: list[str], target_date: date):
    from scrapers.finmind_scraper import FinMindScraper
    from db.repository import upsert_daily_prices, upsert_chip_analysis, upsert_stock_info
    from db.connection import close_pool
    from datetime import timedelta

    start_date = target_date - timedelta(days=89)   # 抓取近 90 天

    scraper = FinMindScraper(
        stock_ids=stock_ids,
        start_date=start_date,
        end_date=target_date,
    )

    try:
        # 個股基本資訊
        infos = scraper.fetch_stock_info()
        for info in infos:
            upsert_stock_info(**info)

        # 每日行情
        prices      = scraper.fetch_prices()
        price_count = upsert_daily_prices([p for p in prices if p])

        # 三大法人籌碼
        chips      = scraper.fetch_chips()
        chip_count = upsert_chip_analysis(chips)

        logger.info("完成：行情寫入 %d 筆，籌碼寫入 %d 筆", price_count, chip_count)
    finally:
        close_pool()


def run_news(start_date: str, end_date: str):
    from scrapers.news_scraper import NewsScraper
    from db.repository import insert_raw_news_batch, insert_news_articles
    from db.connection import close_pool

    logger.info("新聞爬蟲啟動：%s ~ %s", start_date, end_date)
    try:
        scraper  = NewsScraper()
        articles = scraper.scrape_with_date_range(start_date, end_date)

        insert_raw_news_batch(articles)

        fin_articles = [a for a in articles if a.get('is_financial', False)]
        count = insert_news_articles(fin_articles)
        logger.info("完成：原始 %d 則 → 財金 %d 則寫入 user_news", len(articles), count)
    finally:
        close_pool()


def main():
    parser = argparse.ArgumentParser(description="FinMind Stock Crawler")
    parser.add_argument(
        "--mode",
        choices=["server", "stock", "schedule", "news"],
        required=True,
        help="執行模式",
    )
    parser.add_argument(
        "--stocks",
        nargs="+",
        default=DEFAULT_STOCK_IDS,
        help="股票代碼清單（預設：2330 2317 2454 2308 3008）",
    )
    parser.add_argument(
        "--date",
        default=None,
        help="指定日期，格式 YYYYMMDD（預設：今日）",
    )
    parser.add_argument(
        "--start",
        default=NEWS_DEFAULT_START,
        help="新聞起始日期 YYYY-MM-DD（預設：5 年前）",
    )
    parser.add_argument(
        "--end",
        default=NEWS_DEFAULT_END,
        help="新聞結束日期 YYYY-MM-DD（預設：今日）",
    )
    args = parser.parse_args()

    if args.mode == "server":
        import uvicorn
        from api import app
        logger.info("啟動 FastAPI 伺服器，監聽 http://0.0.0.0:8000")
        uvicorn.run(app, host="0.0.0.0", port=8000)

    elif args.mode == "stock":
        target_date = (
            datetime.strptime(args.date, "%Y%m%d").date()
            if args.date
            else date.today()
        )
        run_stock(args.stocks, target_date)

    elif args.mode == "schedule":
        from scheduler import start
        start()

    elif args.mode == "news":
        run_news(args.start, args.end)


if __name__ == "__main__":
    main()
