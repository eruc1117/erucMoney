"""
DATA-005 收尾：刪除 news_crawl_raw 裡 published_at 為空字串的舊爬蟲資料
────────────────────────────────────────────────────────────────────
Iteration 10 之後的新聞管線一律寫入發布時間（實測 1,958 / 2,008 筆有效），
只剩最早那 50 筆（舊 Yahoo／CNN 首頁爬法）沒有日期。它們不在模型資料路徑上
（DATA-005 補充），留著只會讓日期查詢報錯。

跟 DATA-006 後續一樣：先備份成 CSV 再刪，可用 \\copy 還原。

用法：python cleanup_news_raw.py           # 只查證、不刪
      python cleanup_news_raw.py --apply   # 備份後刪除
"""

import argparse
import csv
import os
from datetime import date

from db.connection import get_conn

BACKUP = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'AI', 'Doc', 'Bugs',
                      f'news_crawl_raw_deleted_{date.today().strftime("%Y%m%d")}.csv')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true')
    args = ap.parse_args()

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT platform, count(*), min(scraped_at)::text, max(scraped_at)::text "
                        "FROM news_crawl_raw WHERE published_at = '' GROUP BY platform")
            groups = cur.fetchall()
            cur.execute("SELECT count(*) FROM news_crawl_raw WHERE published_at <> ''")
            keep = cur.fetchone()[0]
            print(f'有日期、保留：{keep} 筆')
            for g in groups:
                print(f'無日期、待刪：{g[0]} {g[1]} 筆（scraped_at {g[2]} ~ {g[3]}）')
            if not args.apply:
                print('（未加 --apply，不做任何變更）')
                return
            cur.execute("SELECT * FROM news_crawl_raw WHERE published_at = '' ORDER BY id")
            rows = cur.fetchall()
            cols = [d[0] for d in cur.description]
            with open(BACKUP, 'w', newline='', encoding='utf-8') as f:
                w = csv.writer(f)
                w.writerow(cols)
                w.writerows(rows)
            cur.execute("DELETE FROM news_crawl_raw WHERE published_at = ''")
            print(f'已刪除 {cur.rowcount} 筆，備份於 {os.path.abspath(BACKUP)}')
        conn.commit()


if __name__ == '__main__':
    main()
