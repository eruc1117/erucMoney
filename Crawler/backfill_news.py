"""
鉅亨網 API 歷史新聞回填（Iteration 38）
────────────────────────────────────────
現有新聞管線只有「排程器活著的那幾個小時」才有資料（最近 14 天只有 4 天有新聞），
RSS 無法回填。鉅亨網的分類 API 支援 `startAt / endAt / page`，內文隨 API 附帶，
2023-09 起的資料實測都在（tw_stock 一週約 280 則、headline 約 550 則）。
本腳本用它把新聞歷史一次補到 3 年，寫入與即時管線相同的兩張表：

    news_crawl_raw   全部（source_url 唯一，重複自動跳過）
    user_news        財金文章（標題唯一，重複自動跳過）

分類與 scope（scope 欄位 Iteration 38 階段 2 才落地，這裡先用 platform 區分）：

    tw_stock   → platform「鉅亨網」      台股（與即時管線相同）
    us_stock   → platform「鉅亨網美股」  美股
    headline   → platform「鉅亨網頭條」  頭條（總經／國際，多與前兩類重疊，newsId 去重）

可續跑：logs/backfill_news_progress.json 記錄每個 (分類, 月份) 的完成狀態，
中斷後重跑會跳過已完成的月份。

用法：
    python backfill_news.py                                   # 2023-09-01 ~ 今天，三個分類
    python backfill_news.py --start 2024-08-01 --end 2024-08-31 --categories tw_stock
    python backfill_news.py --dry-run                         # 只抓不寫，看數量
"""

import argparse
import json
import logging
import os
import random
import sys
import time
from datetime import date, datetime, timedelta

import requests

from scrapers.news_scraper import _extract_keywords, _is_financial
from scrapers.rss_news_scraper import _strip_html, clean_title, load_stock_map, tag_tickers
from utils.user_agents import get_headers

logger = logging.getLogger(__name__)

API = 'https://news.cnyes.com/api/v3/news/category/{cat}'
PAGE_SIZE = 30
DELAY = (1.0, 2.0)          # 每頁之間的禮貌延遲（秒）
MAX_RETRY = 4

CATEGORIES = {
    'tw_stock': {'platform': '鉅亨網',     'scope': 'TW',     'always_financial': True},
    'us_stock': {'platform': '鉅亨網美股', 'scope': 'US',     'always_financial': True},
    'headline': {'platform': '鉅亨網頭條', 'scope': 'GLOBAL', 'always_financial': False},
    # 營收速報（2024-04 起）：不在預設回填清單，由 backfill_revenue_dates.py 使用——
    # 每日「一覽」清單不進 user_news（那是幾百家公司的名單，不是個股新聞），只取個股快訊
    'tw_revenue': {'platform': '鉅亨網營收', 'scope': 'TW', 'always_financial': True},
}
DEFAULT_START = '2023-09-01'

LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs')
PROGRESS_FILE = os.path.join(LOG_DIR, 'backfill_news_progress.json')


# ── 進度檔 ────────────────────────────────────────────────────────────────────
def _load_progress() -> dict:
    try:
        with open(PROGRESS_FILE, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save_progress(p: dict) -> None:
    os.makedirs(LOG_DIR, exist_ok=True)
    tmp = PROGRESS_FILE + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(p, f, ensure_ascii=False, indent=1)
    os.replace(tmp, PROGRESS_FILE)


# ── API ───────────────────────────────────────────────────────────────────────
def _get_page(session, cat: str, start: datetime, end: datetime, page: int) -> dict:
    """回傳 items dict（含 data / total / last_page）。重試後仍失敗丟例外。"""
    url = API.format(cat=cat)
    params = {'limit': PAGE_SIZE, 'startAt': int(start.timestamp()),
              'endAt': int(end.timestamp()), 'page': page}
    last_err = None
    for attempt in range(MAX_RETRY):
        try:
            resp = session.get(url, params=params, headers=get_headers(), timeout=30)
            if resp.status_code == 429:
                raise RuntimeError('429 rate limited')
            resp.raise_for_status()
            return resp.json()['items']
        except Exception as e:      # noqa: BLE001
            last_err = e
            wait = 5 * (attempt + 1) + random.uniform(0, 3)
            logger.warning('[backfill] %s p%d 失敗（%s），%.0fs 後重試', cat, page, e, wait)
            time.sleep(wait)
    raise RuntimeError(f'{cat} page {page} 重試 {MAX_RETRY} 次仍失敗：{last_err}')


def _item_to_article(it: dict, cat: str, stock_map: dict) -> dict | None:
    meta = CATEGORIES[cat]
    title = clean_title(it.get('title', ''))
    if not title:
        return None
    ts = it.get('publishAt')
    content = _strip_html(it.get('content')) or _strip_html(it.get('summary'))
    combined = title + ' ' + content

    # 鉅亨網自己的個股標記（market: [{code, name, ...}]）優先，再補公司名比對
    tickers = []
    for m in it.get('market') or []:
        code = str(m.get('code') or '').strip()
        if code and code in stock_map:
            tickers.append(code)
    tickers += tag_tickers(combined, stock_map)
    tickers = list(dict.fromkeys(tickers))

    keywords = [k for k in (it.get('keyword') or []) if isinstance(k, str) and k.strip()]
    if not keywords:
        keywords = _extract_keywords(combined)

    return {
        'platform':     meta['platform'],
        'title':        title,
        'content':      content,
        'content_kind': 'api',
        'tickers':      tickers,
        'keywords':     keywords[:10],
        'source_url':   f"https://news.cnyes.com/news/id/{it.get('newsId')}",
        'published_at': datetime.fromtimestamp(ts) if ts else None,
        'is_financial': meta['always_financial'] or _is_financial(combined),
        'news_id':      it.get('newsId'),
        'scope':        meta['scope'],
    }


def fetch_range(session, cat: str, start: datetime, end: datetime,
                stock_map: dict, seen_ids: set) -> list:
    """抓一個分類在 [start, end) 的全部新聞，回傳 article dict 清單。"""
    out = []
    page = 1
    while True:
        items = _get_page(session, cat, start, end, page)
        data = items.get('data') or []
        last_page = int(items.get('last_page') or 1)
        for it in data:
            nid = it.get('newsId')
            if nid in seen_ids:
                continue
            seen_ids.add(nid)
            art = _item_to_article(it, cat, stock_map)
            if art:
                out.append(art)
        if page >= last_page or not data:
            break
        page += 1
        time.sleep(random.uniform(*DELAY))
    return out


# ── 寫入 ──────────────────────────────────────────────────────────────────────
def _ensure_title_index() -> None:
    """insert_news_articles 逐筆用標題查重；6 萬筆沒索引會退化成 O(n²)。"""
    from db.connection import get_conn
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute('CREATE INDEX IF NOT EXISTS idx_user_news_title ON user_news (title)')
        conn.commit()


def write_articles(articles: list) -> tuple[int, int]:
    from db.repository import insert_raw_news_batch, insert_news_articles
    raw_ins, _ = insert_raw_news_batch(articles)
    news_ins = insert_news_articles([a for a in articles if a['is_financial']])
    return raw_ins, news_ins


# ── 主流程 ────────────────────────────────────────────────────────────────────
def _month_windows(start: date, end: date):
    cur = date(start.year, start.month, 1)
    while cur <= end:
        nxt = date(cur.year + (cur.month == 12), cur.month % 12 + 1, 1)
        yield max(cur, start), min(nxt, end + timedelta(days=1))
        cur = nxt


def backfill(start: date, end: date, categories: list, dry_run: bool = False,
             use_progress: bool = True) -> dict:
    """回填 [start, end] 的新聞。回傳 {'fetched', 'raw_inserted', 'news_inserted'}。"""
    session = requests.Session()
    stock_map = load_stock_map()
    progress = _load_progress() if use_progress else {}
    seen_ids: set = set()
    totals = {'fetched': 0, 'raw_inserted': 0, 'news_inserted': 0}

    if not dry_run:
        _ensure_title_index()

    for cat in categories:
        for w_start, w_end in _month_windows(start, end):
            key = f'{cat}:{w_start:%Y-%m}'
            if use_progress and progress.get(key, {}).get('done') and w_end.date() < date.today():
                logger.info('[backfill] %s 已完成，跳過', key)
                continue
            t0 = time.time()
            arts = fetch_range(session,
                               cat,
                               datetime.combine(w_start, datetime.min.time()),
                               datetime.combine(w_end, datetime.min.time()),
                               stock_map, seen_ids)
            raw_ins = news_ins = 0
            if arts and not dry_run:
                raw_ins, news_ins = write_articles(arts)
            totals['fetched'] += len(arts)
            totals['raw_inserted'] += raw_ins
            totals['news_inserted'] += news_ins
            tagged = sum(1 for a in arts if a['tickers'])
            logger.info('[backfill] %s 抓 %d 則（有個股 %d）→ raw +%d / user_news +%d，%.0fs',
                        key, len(arts), tagged, raw_ins, news_ins, time.time() - t0)
            print(f'{key}  抓 {len(arts):5d}  個股 {tagged:4d}  raw +{raw_ins:5d}  '
                  f'user_news +{news_ins:5d}  {time.time() - t0:5.0f}s', flush=True)
            if use_progress and not dry_run:
                progress[key] = {'fetched': len(arts), 'tagged': tagged, 'raw_inserted': raw_ins,
                                 'news_inserted': news_ins, 'done': True,
                                 'at': datetime.now().isoformat(timespec='seconds')}
                _save_progress(progress)
            time.sleep(random.uniform(*DELAY))
    return totals


def backfill_gap(since: datetime, categories: list = ('tw_stock',)) -> dict:
    """排程器補跑用：把 since 到現在的新聞補回來（不用進度檔，範圍小）。"""
    return backfill(since.date(), date.today(), list(categories), use_progress=False)


def main():
    ap = argparse.ArgumentParser(description='鉅亨網 API 歷史新聞回填')
    ap.add_argument('--start', default=DEFAULT_START)
    ap.add_argument('--end', default=date.today().isoformat())
    ap.add_argument('--categories', default='tw_stock,us_stock,headline',
                    help='逗號分隔：' + ','.join(CATEGORIES))
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--no-progress', action='store_true', help='忽略進度檔，全部重抓')
    args = ap.parse_args()

    cats = [c.strip() for c in args.categories.split(',') if c.strip()]
    bad = [c for c in cats if c not in CATEGORIES]
    if bad:
        sys.exit(f'未知分類：{bad}，可用：{list(CATEGORIES)}')

    os.makedirs(LOG_DIR, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        handlers=[logging.FileHandler(os.path.join(LOG_DIR, 'backfill_news.log'), encoding='utf-8')],
    )

    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)
    print(f'回填 {start} ~ {end}  分類 {cats}  {"(dry-run)" if args.dry_run else ""}', flush=True)
    t0 = time.time()
    totals = backfill(start, end, cats, dry_run=args.dry_run, use_progress=not args.no_progress)
    print(f'\n完成：抓 {totals["fetched"]} 則，news_crawl_raw +{totals["raw_inserted"]}，'
          f'user_news +{totals["news_inserted"]}，耗時 {(time.time() - t0) / 60:.1f} 分', flush=True)


if __name__ == '__main__':
    main()
