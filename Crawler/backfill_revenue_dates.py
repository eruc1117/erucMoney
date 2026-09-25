"""
月營收「公布時點」多來源合成（Iteration 39，新聞訊號研究方案階段 1 的前置）
────────────────────────────────────────────────────────────────────────
事件研究的第一道關卡是 N0「時間戳可信嗎」。FinMind 的 create_time 在 2026-03 之前全空，
表裡原本只有 151 筆公布日。這支腳本把公布時點從四個地方補回來，寫進
`stock_revenue_announce.announce_date / announce_ts / announce_source`：

    來源          精度    範圍                 說明
    mops_item     秒      2023-09 起（部分）   user_news 平台「MOPS重大訊息」標題「公告本公司 X 月營收」
    cnyes_item    秒      2024-04 起（大型股） 鉅亨網 tw_revenue 分類「營收速報 - 公司(代號)X月營收…」
    news_item     秒      2023-09 起（部分）   user_news 其他媒體標題含公司名與「X月營收」的最早一則
    finmind       日      2026-03 起           backfill_revenue.py 寫入
    cnyes_list    日      2024-04 起（部分）   鉅亨網每日「YYYY年M月D日台股大型／中小型公司X月營收一覽（新增N家）」，
                                               內文「本次公布…前 3 名」段落的公司（每天最多 6 家，偏極端值），
                                               「彙整前一日公布」→ 公布日 = 清單日 − 1
    estimated     日      其餘                 該股有來源月份的習慣公布日（中位數）；事件研究另外分組，不進主結論

優先序：mops_item > cnyes_item > news_item > finmind > cnyes_list > estimated（高優先者已存在就不覆蓋）。
只有日期的來源，事件研究一律視為「收盤後公布」（有時間戳的樣本 9 成以上在 13:30 之後，
比例由 revenue_event_study.py 每次重算並印出）。

cnyes_item / cnyes_list 會寫入非追蹤股（cnyes_item 每月約 200 家大型股）——之後擴大股票池可直接用；
沒有營收數字的列 revenue 為 NULL，backfill_revenue.py 補。一覽清單的 otherProduct 欄位混了累計排行，
日期不對，不能拿（實測「新增 0 家」的清單也有 7~8 個代號）。

用法：
    python backfill_revenue_dates.py --migrate          # 套用 016 migration（可重跑）
    python backfill_revenue_dates.py --cnyes            # 鉅亨網營收速報（2024-03-01 起，可續跑）
    python backfill_revenue_dates.py --news             # 從 user_news 推 MOPS／媒體公布時點
    python backfill_revenue_dates.py --estimate         # 其餘月份估習慣公布日
    python backfill_revenue_dates.py --all              # 全部（--no-progress 會先清空 cnyes_list 重抓）
    python backfill_revenue_dates.py --report           # 追蹤股各月來源覆蓋表
"""

import argparse
import html
import json
import logging
import os
import random
import re
import time
from datetime import date, datetime, timedelta

import requests

from db.connection import get_conn

logger = logging.getLogger(__name__)

PRIORITY = {'mops_item': 5, 'cnyes_item': 4, 'news_item': 3, 'finmind': 2, 'cnyes_list': 1, 'estimated': 0}
CNYES_START = date(2024, 3, 1)         # tw_revenue 分類 2024-02 仍為 0 則
MIGRATION = '016_revenue_announce_ts.sql'
LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs')
PROGRESS_FILE = os.path.join(LOG_DIR, 'backfill_revenue_dates_progress.json')

RE_ITEM = re.compile(r'營收速報\s*-\s*(.+?)\((\d{4,6})\)\s*(\d{1,2})月(?:份)?(?:合併|自結)?營收')
RE_LIST = re.compile(r'營收速報\s*-\s*(\d{4})年(\d{1,2})月(\d{1,2})日台股(大型|中小型)公司(\d{1,2})月營收一覽(?:（新增(\d+)家）)?')
RE_SYMBOL = re.compile(r'TWS:(\d{4,6}):STOCK')
CN_NUM = '一二三四五六七八九十'


# ── migration ────────────────────────────────────────────────────────────────
def migrate() -> bool:
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'Server', 'migrations', MIGRATION)
    with open(path, encoding='utf-8') as f:
        sql = f.read()
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM _migrations WHERE filename = %s", (MIGRATION,))
            done = cur.fetchone() is not None
            cur.execute(sql)                                   # 全部 IF NOT EXISTS / DROP NOT NULL，可重跑
            if not done:
                cur.execute("INSERT INTO _migrations (filename) VALUES (%s)", (MIGRATION,))
        conn.commit()
    return not done


# ── 寫入 ──────────────────────────────────────────────────────────────────────
def upsert_dates(rows: list) -> int:
    """rows: [{stock_id, revenue_month(date), announce_date(date), announce_ts(datetime|None), source}]。
    回傳實際寫入（新增或覆蓋）筆數。"""
    if not rows:
        return 0
    n = 0
    with get_conn() as conn:
        with conn.cursor() as cur:
            for r in rows:
                pr = PRIORITY[r['source']]
                cur.execute("""
                    INSERT INTO stock_revenue_announce
                        (stock_id, revenue_month, announce_date, announce_ts, announce_source)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (stock_id, revenue_month) DO UPDATE SET
                        announce_date   = EXCLUDED.announce_date,
                        announce_ts     = EXCLUDED.announce_ts,
                        announce_source = EXCLUDED.announce_source,
                        updated_at      = CURRENT_TIMESTAMP
                    WHERE stock_revenue_announce.announce_source IS NULL
                       OR COALESCE((SELECT p FROM (VALUES ('mops_item',5),('cnyes_item',4),('news_item',3),
                                                          ('finmind',2),('cnyes_list',1),('estimated',0)) AS m(s, p)
                                    WHERE m.s = stock_revenue_announce.announce_source), -1) < %s
                       OR (stock_revenue_announce.announce_source = EXCLUDED.announce_source
                           AND (stock_revenue_announce.announce_ts IS NULL
                                OR EXCLUDED.announce_ts < stock_revenue_announce.announce_ts))
                """, (r['stock_id'], r['revenue_month'], r['announce_date'], r['announce_ts'],
                      r['source'], pr))
                n += cur.rowcount
        conn.commit()
    return n


# ── ① 鉅亨網 tw_revenue ─────────────────────────────────────────────────────
def _rev_month(month: int, published: datetime) -> date:
    """標題只有「X月營收」：營收月份一定早於公布月份——同年若 month < 公布月，否則是去年（1 月公布 12 月營收）。"""
    year = published.year if month < published.month else published.year - 1
    return date(year, month, 1)


def _batch_codes(content: str) -> list:
    """每日一覽的內文分段：只有「本次公布…前3名」段落的表格是當批公布的公司；
    「X月營收年增率前5名」是累計排行，日期不對，不能拿。otherProduct 是兩者混在一起，也不能拿。"""
    c = html.unescape(content)
    codes = []
    for m in re.finditer(r'<em>(.*?)</em>(.*?)(?=<em>|<h6>|$)', c, flags=re.S):
        head, body = m.group(1), m.group(2)
        if head.startswith('本次公布'):
            codes += RE_SYMBOL.findall(body)
    return list(dict.fromkeys(codes))


def parse_cnyes_item(it: dict) -> tuple[list, dict | None]:
    """回傳 (dates_rows, news_article_or_None)。清單 → 多筆日期列、不進 user_news；個股快訊 → 一筆 + 文章。"""
    title = (it.get('title') or '').replace('\xa0', ' ').strip()
    ts = it.get('publishAt')
    published = datetime.fromtimestamp(int(ts)) if ts else None
    if not published:
        return [], None

    m = RE_LIST.search(title)
    if m:
        y, mo, d, _size, rev_mo, n_new = m.groups()
        list_day = date(int(y), int(mo), int(d))
        announce = list_day - timedelta(days=1)          # 「彙整前一日公布」
        rev_month = _rev_month(int(rev_mo), datetime.combine(list_day, datetime.min.time()))
        codes = _batch_codes(it.get('content') or '')
        if n_new and int(n_new) == 0 and codes:
            logger.warning('[cnyes_list] %s：新增 0 家卻解析到 %d 個「本次」代號，略過', title, len(codes))
            codes = []
        return [{'stock_id': c, 'revenue_month': rev_month, 'announce_date': announce,
                 'announce_ts': None, 'source': 'cnyes_list'} for c in codes], None

    m = RE_ITEM.search(title)
    if m:
        _name, code, rev_mo = m.groups()
        rev_month = _rev_month(int(rev_mo), published)
        return [{'stock_id': code, 'revenue_month': rev_month, 'announce_date': published.date(),
                 'announce_ts': published, 'source': 'cnyes_item'}], it
    return [], None


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


def reset_source(source: str) -> int:
    """把某來源的公布時點清空（保留營收數字），供重抓。"""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""UPDATE stock_revenue_announce SET announce_date = NULL, announce_ts = NULL,
                           announce_source = NULL, updated_at = CURRENT_TIMESTAMP WHERE announce_source = %s""", (source,))
            n = cur.rowcount
        conn.commit()
    return n


def backfill_cnyes(start: date, end: date, store_news: bool = True, use_progress: bool = True) -> dict:
    import backfill_news as bn
    session = requests.Session()
    stock_map = bn.load_stock_map()
    progress = _load_progress() if use_progress else {}
    totals = {'items': 0, 'lists': 0, 'quick': 0, 'dates': 0, 'news': 0}
    for w_start, w_end in bn._month_windows(start, end):
        key = f'tw_revenue:{w_start:%Y-%m}'
        if use_progress and progress.get(key, {}).get('done') and w_end < date.today():
            continue
        t0 = time.time()
        page, seen = 1, set()
        rows, articles, n_lists = [], [], 0
        while True:
            items = bn._get_page(session, 'tw_revenue',
                                 datetime.combine(w_start, datetime.min.time()),
                                 datetime.combine(w_end, datetime.min.time()), page)
            data = items.get('data') or []
            for it in data:
                if it.get('newsId') in seen:
                    continue
                seen.add(it.get('newsId'))
                dr, art = parse_cnyes_item(it)
                rows += dr
                if art:
                    totals['quick'] += 1
                    a = bn._item_to_article(art, 'tw_revenue', stock_map)
                    if a:
                        articles.append(a)
                elif dr:
                    totals['lists'] += 1
                    n_lists += 1
            if page >= int(items.get('last_page') or 1) or not data:
                break
            page += 1
            time.sleep(random.uniform(*bn.DELAY))
        totals['items'] += len(seen)
        written = upsert_dates(rows)
        news_ins = 0
        if store_news and articles:
            _, news_ins = bn.write_articles(articles)
        totals['dates'] += written
        totals['news'] += news_ins
        print(f'{key}  {len(seen):4d} 則（清單 {n_lists:3d}）  日期列 {len(rows):5d} 寫入 {written:5d}  '
              f'個股快訊 {len(articles):3d} → user_news +{news_ins}  {time.time() - t0:4.0f}s', flush=True)
        if use_progress:
            progress[key] = {'items': len(seen), 'rows': len(rows), 'written': written, 'done': True,
                             'at': datetime.now().isoformat(timespec='seconds')}
            _save_progress(progress)
        time.sleep(random.uniform(*bn.DELAY))
    return totals


# ── ② user_news 推回（MOPS 與媒體標題） ───────────────────────────────────────
def _month_in_title(title: str) -> int | None:
    m = re.search(r'(\d{1,2})月(?:份)?(?:合併|自結|營收|營業收入)', title)
    if m:
        v = int(m.group(1))
        return v if 1 <= v <= 12 else None
    m = re.search(r'([一二三四五六七八九十]{1,3})月(?:份)?(?:合併|自結|營收|營業收入)', title)
    if m:
        s = m.group(1)
        if s == '十':
            return 10
        if s.startswith('十'):
            return 10 + CN_NUM.index(s[1]) + 1
        if s.endswith('十'):
            return 10
        return CN_NUM.index(s) + 1
    return None


def infer_from_news(since: date = date(2023, 9, 1)) -> dict:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT stock_id, stock_name FROM stock_info WHERE is_tracking AND COALESCE(industry_type,'') <> 'ETF'")
            names = {sid: (nm or '').rstrip('*') for sid, nm in cur.fetchall()}
            cur.execute("""
                SELECT platform, title, submitted_at, tickers FROM user_news
                WHERE submitted_at >= %s AND title ~ '月(份)?(合併|自結|營收|營業收入)'
                  AND (title ~ '營收' OR title ~ '營業收入')
            """, (since,))
            news = cur.fetchall()
    best: dict = {}
    for platform, title, ts, tickers in news:
        if not ts:
            continue
        mo = _month_in_title(title)
        if not mo:
            continue
        is_mops = platform == 'MOPS重大訊息'
        for sid, nm in names.items():
            # 媒體標題要出現公司名或「(代號)」；MOPS 標題固定「公司名（代號）主旨」
            if not (nm and nm in title) and f'({sid})' not in title and f'（{sid}）' not in title:
                continue
            if '一覽' in title or '前三' in title or '排行' in title:
                continue
            rev_month = _rev_month(mo, ts)
            lag = (ts.date() - rev_month).days
            if not (28 <= lag <= 50):          # 次月 1 日 ~ 約 20 日；其他是季報／年報回顧
                continue
            src = 'mops_item' if is_mops else 'news_item'
            key = (sid, rev_month, src)
            if key not in best or ts < best[key]:
                best[key] = ts
    rows = [{'stock_id': sid, 'revenue_month': rm, 'announce_date': ts.date(), 'announce_ts': ts, 'source': src}
            for (sid, rm, src), ts in best.items()]
    written = upsert_dates(rows)
    return {'candidates': len(rows), 'written': written,
            'mops': sum(1 for r in rows if r['source'] == 'mops_item')}


# ── ③ 估計（沒有任何來源的月份） ─────────────────────────────────────────────
def estimate_missing(min_known: int = 3) -> dict:
    """公司的公布日在每月是習慣性的（台積電 10 日、佳世達 5 日前後）。用該股有可考來源的月份取
    「公布日 − 營收月次月 1 日」天數的中位數，填到沒有來源的月份，來源標 estimated、優先序最低。
    事件研究把 estimated 另外分組，主結論不用它——估錯一天，反應日會漏到事件前或漂移視窗裡。"""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT r.stock_id, r.revenue_month, r.announce_date, r.announce_source
                FROM stock_revenue_announce r JOIN stock_info i USING (stock_id)
                WHERE i.is_tracking AND COALESCE(i.industry_type,'') <> 'ETF' AND r.revenue IS NOT NULL
                ORDER BY 1, 2""")
            rows = cur.fetchall()
    by_stock: dict = {}
    for sid, rm, ad, src in rows:
        by_stock.setdefault(sid, []).append((rm, ad, src))
    out, n_est = [], 0
    for sid, lst in by_stock.items():
        lags = []
        for rm, ad, src in lst:
            if ad and src and src != 'estimated':
                nxt = date(rm.year + (rm.month == 12), rm.month % 12 + 1, 1)
                lags.append((ad - nxt).days)
        if len(lags) < min_known:
            continue
        lags.sort()
        med = lags[len(lags) // 2]
        for rm, ad, src in lst:
            if ad is None or src == 'estimated':
                nxt = date(rm.year + (rm.month == 12), rm.month % 12 + 1, 1)
                est = nxt + timedelta(days=max(0, med))
                if est > date.today():
                    continue
                out.append({'stock_id': sid, 'revenue_month': rm, 'announce_date': est,
                            'announce_ts': None, 'source': 'estimated'})
                n_est += 1
    written = upsert_dates(out)
    return {'estimated': n_est, 'written': written, 'stocks': len(by_stock)}


# ── 報表 ──────────────────────────────────────────────────────────────────────
def report() -> str:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT r.stock_id, i.stock_name,
                       count(*) FILTER (WHERE r.revenue IS NOT NULL) AS months,
                       count(*) FILTER (WHERE r.announce_date IS NOT NULL) AS dated,
                       count(*) FILTER (WHERE r.announce_ts IS NOT NULL) AS timed,
                       min(r.announce_date), max(r.announce_date)
                FROM stock_revenue_announce r JOIN stock_info i USING (stock_id)
                WHERE i.is_tracking GROUP BY 1, 2 ORDER BY 1""")
            rows = cur.fetchall()
            cur.execute("""SELECT announce_source, count(*) FROM stock_revenue_announce
                           WHERE announce_date IS NOT NULL GROUP BY 1 ORDER BY 2 DESC""")
            src = cur.fetchall()
            cur.execute("""SELECT count(*) FILTER (WHERE announce_ts::time >= '13:30'), count(*)
                           FROM stock_revenue_announce WHERE announce_ts IS NOT NULL""")
            after, timed = cur.fetchone()
    lines = ['stock  name        months dated timed  first       last',
             *[f'{r[0]:<6} {r[1]:<10} {r[2]:6d} {r[3]:5d} {r[4]:5d}  {r[5]}  {r[6]}' for r in rows],
             '', '來源（全市場）：' + '、'.join(f'{s} {n:,}' for s, n in src),
             f'有時間戳的公布中 13:30 之後：{after}/{timed}（{after / timed:.0%}）' if timed else '']
    return '\n'.join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--migrate', action='store_true')
    ap.add_argument('--cnyes', action='store_true')
    ap.add_argument('--news', action='store_true')
    ap.add_argument('--estimate', action='store_true', help='沒有來源的月份用該股習慣公布日估（來源 estimated）')
    ap.add_argument('--all', action='store_true')
    ap.add_argument('--report', action='store_true')
    ap.add_argument('--start', default=CNYES_START.isoformat())
    ap.add_argument('--end', default=date.today().isoformat())
    ap.add_argument('--no-store-news', action='store_true', help='個股快訊不寫 user_news')
    ap.add_argument('--no-progress', action='store_true')
    a = ap.parse_args()
    os.makedirs(LOG_DIR, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
                        handlers=[logging.FileHandler(os.path.join(LOG_DIR, 'backfill_revenue_dates.log'), encoding='utf-8'),
                                  logging.StreamHandler()])
    if a.migrate or a.all:
        print('migration 016：', '套用' if migrate() else '已存在，重跑一次（冪等）')
    if a.cnyes or a.all:
        t0 = time.time()
        if a.no_progress:
            print(f'清空舊 cnyes_list {reset_source("cnyes_list")} 列後重抓')
        t = backfill_cnyes(date.fromisoformat(a.start), date.fromisoformat(a.end),
                           store_news=not a.no_store_news, use_progress=not a.no_progress)
        print(f'鉅亨網營收速報：{t["items"]} 則（清單 {t["lists"]}、個股快訊 {t["quick"]}）→ 日期寫入 {t["dates"]:,}、'
              f'user_news +{t["news"]}，{(time.time() - t0) / 60:.1f} 分')
    if a.news or a.all:
        t = infer_from_news()
        print(f'user_news 推回：候選 {t["candidates"]}（MOPS {t["mops"]}）→ 寫入 {t["written"]}')
    if a.estimate or a.all:
        t = estimate_missing()
        print(f'估計公布日：{t["estimated"]} 個月份（{t["stocks"]} 檔）→ 寫入 {t["written"]}')
    if a.report or a.all:
        print(report())


if __name__ == '__main__':
    main()
