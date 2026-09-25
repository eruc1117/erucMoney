"""
公開資訊觀測站（MOPS）重大訊息回填（Iteration 38 階段 1c）
────────────────────────────────────────────────────────
台股版 8-K：官方、附股號、有精確發言時間（17:23 發言 → 收盤後 → 歸 T+1）。
方案文件把它當台股事件主幹；Iteration 38 改為鉅亨網 API 之外的**事件層補充**。

端點：舊版 `mopsov.twse.com.tw/mops/web/ajax_t05st01`（新版 mops.twse.com.tw 對程式回「安全性考量」頁）。
依公司 + 民國年月查詢，回 HTML 表格：公司代號、公司名稱、發言日期、發言時間、主旨。
只存主旨（內文要再點一層，事件分類用主旨已足夠）。

寫入：news_crawl_raw（source_url = mops://代碼/日期T時間，唯一）與 user_news（platform「MOPS重大訊息」，
tickers = [代碼]）。追蹤股 26 檔 × 37 個月 ≈ 960 次請求，每次間隔 3~6 秒，約 1 小時。
可續跑：logs/backfill_mops_progress.json。

用法：
    python backfill_mops.py                          # 追蹤股，2023-09 ~ 今天
    python backfill_mops.py --stocks 2330,2303 --start 2024-08 --end 2024-08
    python backfill_mops.py --dry-run
"""

import argparse
import json
import logging
import os
import random
import re
import time
from datetime import date, datetime

import requests
from bs4 import BeautifulSoup

from utils.user_agents import get_headers

logger = logging.getLogger(__name__)

URL = 'https://mopsov.twse.com.tw/mops/web/ajax_t05st01'
PLATFORM = 'MOPS重大訊息'
DELAY = (3.0, 6.0)
BLOCK_WAIT = 90
MAX_RETRY = 3
DEFAULT_START = '2023-09'

LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs')
PROGRESS_FILE = os.path.join(LOG_DIR, 'backfill_mops_progress.json')

_ROC_DATE = re.compile(r'^(\d{2,3})/(\d{1,2})/(\d{1,2})$')


def _tracked() -> list:
    from db.connection import get_conn
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT stock_id FROM stock_info WHERE is_tracking ORDER BY stock_id")
            return [r[0] for r in cur.fetchall()]


def _months(start: str, end: str):
    y, m = map(int, start.split('-'))
    ey, em = map(int, end.split('-'))
    while (y, m) <= (ey, em):
        yield y, m
        m += 1
        if m > 12:
            y, m = y + 1, 1


def _parse(html: str) -> list:
    """回傳 [{code, name, date(datetime), subject}]。"""
    soup = BeautifulSoup(html, 'html.parser')
    out = []
    for tr in soup.find_all('tr'):
        tds = [td.get_text(' ', strip=True).replace('\xa0', ' ').strip() for td in tr.find_all('td')]
        if len(tds) < 5:
            continue
        code, name, d, t, subject = tds[0], tds[1], tds[2], tds[3], tds[4]
        m = _ROC_DATE.match(d)
        if not m or not re.match(r'^\d{1,2}:\d{2}(:\d{2})?$', t):
            continue
        yy, mm, dd = int(m.group(1)) + 1911, int(m.group(2)), int(m.group(3))
        try:
            hh, mi, ss = (list(map(int, t.split(':'))) + [0])[:3]
            when = datetime(yy, mm, dd, hh, mi, ss)
        except ValueError:
            continue
        out.append({'code': code, 'name': name, 'date': when, 'subject': subject})
    return out


def fetch_month(session, code: str, year: int, month: int) -> list:
    data = {'encodeURIComponent': '1', 'step': '1', 'firstin': '1', 'off': '1',
            'queryName': 'co_id', 'inpuType': 'co_id', 'TYPEK': 'all',
            'co_id': code, 'year': str(year - 1911), 'month': f'{month:02d}'}
    headers = {**get_headers(), 'Referer': 'https://mopsov.twse.com.tw/mops/web/t05st01'}
    for attempt in range(MAX_RETRY):
        try:
            r = session.post(URL, data=data, headers=headers, timeout=40)
            if r.status_code != 200 or '安全性考量' in r.text or 'Overrun' in r.text:
                logger.warning('[mops] %s %d/%02d 被擋（%s），等 %ds', code, year, month, r.status_code, BLOCK_WAIT)
                time.sleep(BLOCK_WAIT)
                continue
            if '查無' in r.text or '無符合' in r.text:
                return []
            return _parse(r.text)
        except Exception as e:  # noqa: BLE001
            logger.warning('[mops] %s %d/%02d 失敗：%s', code, year, month, e)
            time.sleep(10 * (attempt + 1))
    raise RuntimeError(f'{code} {year}/{month:02d} 重試 {MAX_RETRY} 次仍失敗')


def to_article(item: dict) -> dict:
    when = item['date']
    return {
        'platform':     PLATFORM,
        'title':        f"{item['name']}（{item['code']}）{item['subject']}",
        'content':      item['subject'],
        'content_kind': 'filing',
        'tickers':      [item['code']],
        'keywords':     [],
        'source_url':   f"mops://{item['code']}/{when.isoformat(timespec='seconds')}",
        'published_at': when,
        'is_financial': True,
    }


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


def backfill(stocks: list, start: str, end: str, dry_run: bool = False) -> dict:
    from db.repository import insert_raw_news_batch, insert_news_articles
    session = requests.Session()
    progress = {} if dry_run else _load_progress()
    totals = {'fetched': 0, 'raw_inserted': 0, 'news_inserted': 0}
    today = date.today()
    for code in stocks:
        for y, m in _months(start, end):
            key = f'{code}:{y}-{m:02d}'
            if progress.get(key, {}).get('done') and (y, m) < (today.year, today.month):
                continue
            items = fetch_month(session, code, y, m)
            arts = [to_article(i) for i in items]
            raw_ins = news_ins = 0
            if arts and not dry_run:
                raw_ins, _ = insert_raw_news_batch(arts)
                news_ins = insert_news_articles(arts)
            totals['fetched'] += len(arts)
            totals['raw_inserted'] += raw_ins
            totals['news_inserted'] += news_ins
            print(f'{key}  {len(arts):3d} 則  raw +{raw_ins:3d}  user_news +{news_ins:3d}', flush=True)
            logger.info('[mops] %s %d 則 → raw +%d / user_news +%d', key, len(arts), raw_ins, news_ins)
            if not dry_run:
                progress[key] = {'fetched': len(arts), 'done': True,
                                 'at': datetime.now().isoformat(timespec='seconds')}
                _save_progress(progress)
            time.sleep(random.uniform(*DELAY))
    return totals


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--stocks', default=None, help='逗號分隔；預設 is_tracking 清單')
    ap.add_argument('--start', default=DEFAULT_START, help='YYYY-MM')
    ap.add_argument('--end', default=date.today().strftime('%Y-%m'))
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()
    os.makedirs(LOG_DIR, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
                        handlers=[logging.FileHandler(os.path.join(LOG_DIR, 'backfill_mops.log'), encoding='utf-8')])
    stocks = [s.strip() for s in a.stocks.split(',')] if a.stocks else _tracked()
    print(f'MOPS 回填 {a.start} ~ {a.end}，{len(stocks)} 檔 {"(dry-run)" if a.dry_run else ""}', flush=True)
    t0 = time.time()
    t = backfill(stocks, a.start, a.end, dry_run=a.dry_run)
    print(f'\n完成：{t["fetched"]} 則，raw +{t["raw_inserted"]}，user_news +{t["news_inserted"]}，'
          f'{(time.time() - t0) / 60:.1f} 分', flush=True)


if __name__ == '__main__':
    main()
