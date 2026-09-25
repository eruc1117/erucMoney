"""
從 user_news 抽樣 300 則做 LLM 抽取試跑（方案文件「訂閱方案小範圍試跑」）。

方案原本要另外抓 300 則（01_fetch.py）；Iteration 38 回填後 user_news 已有三年資料，
直接抽即可。三類 × 三個時間窗口：

    類別（以 platform 判）：TW = 鉅亨網（台股）、US = 鉅亨網美股、GLOBAL = 鉅亨網頭條
    窗口：2024-08-05 ± 7 天（全球股災）、2025-04-02 ± 14 天（對等關稅）、2025-11-10 ~ 11-21（平靜期）

輸出：
    data/input.jsonl             每行 {news_id, category, published_at, title, content, tickers}
    data/gold_60_template.csv    每類 20 則，留給人工標註（或先由 Claude 標、人工核對）

用法：
    python scripts/02_prepare.py [--per-category 100] [--seed 42]
"""

import argparse
import csv
import json
import os
import random
import sys
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(os.path.dirname(ROOT), 'Crawler'))

from db.connection import get_conn  # noqa: E402

CATEGORIES = {'TW': '鉅亨網', 'US': '鉅亨網美股', 'GLOBAL': '鉅亨網頭條'}
WINDOWS = [
    ('crash_2024_08', date(2024, 7, 29), date(2024, 8, 12)),
    ('tariff_2025_04', date(2025, 3, 19), date(2025, 4, 16)),
    ('calm_2025_11', date(2025, 11, 10), date(2025, 11, 21)),
]
MAX_CONTENT = 700


def fetch(platform: str, start: date, end: date) -> list:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, submitted_at, title, content, tickers FROM user_news
                WHERE platform = %s AND submitted_at >= %s AND submitted_at < %s
                  AND length(coalesce(content, '')) >= 80
                ORDER BY id
            """, (platform, start, end + timedelta(days=1)))
            return cur.fetchall()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--per-category', type=int, default=100)
    ap.add_argument('--seed', type=int, default=42)
    a = ap.parse_args()
    rng = random.Random(a.seed)

    os.makedirs(os.path.join(ROOT, 'data'), exist_ok=True)
    picked = []
    per_window = a.per_category // len(WINDOWS)
    for cat, platform in CATEGORIES.items():
        for name, s, e in WINDOWS:
            rows = fetch(platform, s, e)
            take = rng.sample(rows, min(per_window, len(rows)))
            print(f'{cat:6s} {name:16s} 可用 {len(rows):4d} 抽 {len(take):3d}')
            for rid, pub, title, content, tickers in take:
                picked.append({'news_id': rid, 'category': cat, 'window': name,
                               'published_at': pub.isoformat(timespec='minutes'),
                               'title': title, 'content': (content or '')[:MAX_CONTENT],
                               'tickers': tickers or []})

    rng.shuffle(picked)
    out = os.path.join(ROOT, 'data', 'input.jsonl')
    with open(out, 'w', encoding='utf-8') as f:
        for p in picked:
            f.write(json.dumps(p, ensure_ascii=False) + '\n')
    print(f'\n寫出 {len(picked)} 則 → {out}')

    gold = os.path.join(ROOT, 'data', 'gold_60_template.csv')
    with open(gold, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f)
        w.writerow(['news_id', 'category', 'title', 'event_type', 'direction', 'magnitude',
                    'is_expected', 'affected_tickers', 'scope', 'note'])
        for cat in CATEGORIES:
            for p in [x for x in picked if x['category'] == cat][:20]:
                w.writerow([p['news_id'], cat, p['title'], '', '', '', '', '', '', ''])
    print(f'黃金標準模板（每類 20 則，空欄待填）→ {gold}')


if __name__ == '__main__':
    main()
