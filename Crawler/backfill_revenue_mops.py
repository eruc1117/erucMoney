"""
全市場月營收回補：公開資訊觀測站「營業收入彙總表」（Iteration 48，打敗大盤階段 1 的最後一塊資料）

為什麼不走 FinMind：TaiwanStockMonthRevenue 免費等級只能逐檔查，全市場 2,000 檔要 2,000 次呼叫，
匿名額度第一小時後每小時只放約 5 次（Iteration 48 實測）。MOPS 的彙總表**一個市場一個月一頁就是全部公司**：
    https://mopsov.twse.com.tw/nas/t21/{sii|otc}/t21sc03_{民國年}_{月}_{0|1}.html
    sii = 上市、otc = 上櫃；_0 = 國內公司、_1 = KY（國外）公司。單位千元。
2016-10 起到現在約 120 個月 × 4 頁 = 480 次請求，不吃任何額度。

**月份對應（不能錯）**：`stock_revenue_announce.revenue_month` 沿用 FinMind 的慣例＝**公布月**（營收所屬月的次月 1 日）：
民國 115 年 8 月的彙總表（8 月營收）→ revenue_month = 2026-09-01。Iteration 48 用台積電 514,805,337 千元核對過。
只寫 revenue，不碰 announce_date／announce_source（彙總表沒有各公司的公告日；那是另一個未解的問題）。

用法：
    python backfill_revenue_mops.py                       # 2016-10 ~ 上個月，只寫股票池（market_universe）裡的公司
    python backfill_revenue_mops.py --start 2024-01 --end 2024-03
    python backfill_revenue_mops.py --all-companies       # 不篩股票池
"""

import argparse
import logging
import re
import time
from datetime import date
from typing import Optional

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

URL = 'https://mopsov.twse.com.tw/nas/t21/{market}/t21sc03_{roc_year}_{month}_{kind}.html'
MARKETS = ('sii', 'otc')
KINDS = (0, 1)                     # 國內、KY
HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) money-crawler/1.0'}
DELAY = 2.0
RETRY_WAITS = (10, 60, 180)
DEFAULT_START = (2016, 10)         # 2018 回測起點前 15 個月（surprise 基期）
_CODE = re.compile(r'^\d{4}$')


def _num(raw: str) -> Optional[int]:
    s = str(raw or '').replace(',', '').strip()
    if not s or s == '-':
        return None
    try:
        return int(float(s))
    except ValueError:
        return None


def revenue_month_for(year: int, month: int) -> date:
    """營收所屬月 → 表裡的 revenue_month（次月 1 日）。"""
    return date(year + (month == 12), month % 12 + 1, 1)


def parse_summary(html: str, year: int, month: int) -> list[dict]:
    """
    彙總表 → [{stock_id, revenue_month, revenue(元), prev_month_revenue, last_year_revenue, note}]。
    頁面是巢狀表格（每個產業一張），只取「直接子 td ≥ 10 個且第一格是 4 碼代號」的列，外層那些把整張表當一格的列不算。
    """
    soup = BeautifulSoup(html, 'html.parser')
    rm = revenue_month_for(year, month)
    out, seen = [], set()
    for tr in soup.find_all('tr'):
        tds = tr.find_all('td', recursive=False)
        if len(tds) < 10:
            continue
        t = [x.get_text(strip=True) for x in tds]
        sid = t[0]
        if not _CODE.match(sid) or sid in seen:
            continue
        rev = _num(t[2])
        if rev is None:
            continue
        seen.add(sid)
        out.append({'stock_id': sid, 'revenue_month': rm, 'revenue': rev * 1000,
                    'prev_month_revenue': (_num(t[3]) or 0) * 1000 if _num(t[3]) is not None else None,
                    'last_year_revenue': (_num(t[4]) or 0) * 1000 if _num(t[4]) is not None else None,
                    'note': t[10] if len(t) > 10 else ''})
    return out


class MopsFetchError(RuntimeError):
    pass


def fetch_summary(market: str, year: int, month: int, kind: int) -> Optional[str]:
    """回 HTML；該月沒有這頁（例如還沒公布、KY 早期沒有）回 None；被擋或 5xx 重試三次後丟錯。"""
    url = URL.format(market=market, roc_year=year - 1911, month=month, kind=kind)
    last = None
    for i, wait in enumerate((0,) + RETRY_WAITS):
        if wait:
            time.sleep(wait)
        try:
            r = requests.get(url, headers=HEADERS, timeout=60)
        except requests.RequestException as e:
            last = MopsFetchError(f'{url}: {e}')
            logger.warning('[mops-rev] 第 %d 次失敗：%s', i + 1, last)
            continue
        if r.status_code == 404:
            return None
        if r.status_code != 200:
            last = MopsFetchError(f'HTTP {r.status_code} {url}')
            logger.warning('[mops-rev] 第 %d 次失敗：%s', i + 1, last)
            continue
        ct = (r.headers.get('content-type') or '').lower()
        m = re.search(r'charset=([\w-]+)', ct)
        r.encoding = m.group(1) if m else 'big5'
        return r.text
    raise last


def months(start: tuple, end: tuple):
    y, m = start
    while (y, m) <= end:
        yield y, m
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def backfill(start: tuple = DEFAULT_START, end: Optional[tuple] = None, only_universe: bool = True,
             delay: float = DELAY) -> dict:
    from backfill_revenue import upsert
    if end is None:
        today = date.today()
        end = (today.year, today.month - 1) if today.month > 1 else (today.year - 1, 12)
    uni = None
    if only_universe:
        import market_universe
        uni = set(market_universe.ids(include_delisted=True))
    out = {'pages': 0, 'missing_pages': 0, 'rows': 0, 'failed': [], 'months': 0}
    for y, m in months(start, end):
        month_rows = []
        for market in MARKETS:
            for kind in KINDS:
                try:
                    html = fetch_summary(market, y, m, kind)
                except MopsFetchError as e:
                    logger.error('[mops-rev] %d-%02d %s_%d 放棄：%s', y, m, market, kind, e)
                    out['failed'].append((y, m, market, kind))
                    continue
                finally:
                    time.sleep(delay)
                if html is None:
                    out['missing_pages'] += 1
                    continue
                out['pages'] += 1
                rows = parse_summary(html, y, m)
                if uni is not None:
                    rows = [r for r in rows if r['stock_id'] in uni]
                month_rows += rows
        n = upsert([{'stock_id': r['stock_id'], 'revenue_month': r['revenue_month'].isoformat(),
                     'announce_date': None, 'revenue': r['revenue']} for r in month_rows])
        out['rows'] += n
        out['months'] += 1
        logger.info('[mops-rev] %d-%02d：%d 家（累計 %d 個月 %d 列）', y, m, n, out['months'], out['rows'])
    return out


def _ym(s: str) -> tuple:
    y, m = s.split('-')
    return int(y), int(m)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--start', default=f'{DEFAULT_START[0]}-{DEFAULT_START[1]:02d}')
    ap.add_argument('--end', default=None)
    ap.add_argument('--all-companies', action='store_true')
    ap.add_argument('--delay', type=float, default=DELAY)
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s')
    r = backfill(_ym(a.start), _ym(a.end) if a.end else None, only_universe=not a.all_companies, delay=a.delay)
    print(r)


if __name__ == '__main__':
    main()
