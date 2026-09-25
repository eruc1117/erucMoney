"""
用別名表重新標記 user_news 的 tickers（Iteration 38）。

回填時 instrument_alias 還不存在，十幾萬則新聞只靠 stock_info 公司名與「（2330）」格式標記；
「台積」「TSMC」「台灣50」都漏了。本腳本對全部（或 --since 之後）新聞重算 tag_tickers，
只更新有變化的列，之後要再跑 `news_align.py --link --features` 讓連結與特徵跟上。

用法：python news_retag.py [--since 2023-09-01] [--dry-run]
"""
import argparse
import logging
from datetime import date

from db.connection import get_conn
from scrapers.rss_news_scraper import load_stock_map, tag_tickers

logger = logging.getLogger(__name__)


def run(since: date = None, dry_run: bool = False) -> dict:
    stock_map = load_stock_map()
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT id, title, content, tickers FROM user_news
                           WHERE %s::date IS NULL OR submitted_at >= %s::date""", (since, since))
            rows = cur.fetchall()
    changed, added_total = [], 0
    for rid, title, content, old in rows:
        old = list(old or [])
        new = tag_tickers((title or '') + ' ' + (content or ''), stock_map)
        merged = list(dict.fromkeys(old + new))       # 只增不減：API 給的 market 標記要保留
        if merged != old:
            changed.append((merged, rid))
            added_total += len(merged) - len(old)
    stats = {'rows': len(rows), 'changed': len(changed), 'tickers_added': added_total}
    if not dry_run and changed:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.executemany("UPDATE user_news SET tickers = %s WHERE id = %s", changed)
            conn.commit()
    logger.info('[retag] %s', stats)
    return stats


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--since', default=None)
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    print(run(date.fromisoformat(a.since) if a.since else None, a.dry_run))
