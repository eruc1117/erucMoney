"""
新聞爬蟲 v2 — 公開免費來源（Iteration 10）

取代舊的首頁標題爬法。舊法三個問題（皆已實測確認）：
  1. `_parse_yahoo_soup` / `_parse_cnn_soup` 產生的 dict 寫死 `'content': ''`
     → user_news 最近 50 筆內文長度全為 0，M2 只能對標題做情緒分析
  2. tickers 全為 `{}` → M2 的 `stock_articles` 特徵恆為 0，
     22 檔股票拿到完全相同的新聞訊號（Iteration 9 觀察到的「全 Buy」根因）
  3. 沒有發布時間 → 時間衰減權重（T+0=1.0 / T+1=0.6 / T+2=0.3）失效

三類來源（皆為公開免費介面，2026-08-06 實測可用）：

| 類別 | 來源 | 內文取得方式 | 用途 |
|------|------|-------------|------|
| A 個股定向 | Yahoo 個股 RSS `?s=CODE.TW` | 抓原文頁 | 個股新聞與法說會公告 |
| B 結構化 | 鉅亨網 JSON API | **API 直接回傳內文** | 量大且穩定，免抓原文頁 |
| C 一般財經 | 中央社／經濟日報／自由財經 RSS | 抓原文頁 | 總經與大盤 |

失效來源（勿再加入，除非確認已恢復）：
  · 工商時報 `rss/realtimenews-money.xml`、鉅亨網 `rss/tw_stock` → 404
  · Google News RSS 可正確做個股標記，但其 link 為 JS redirect，
    base64 解碼與跟隨轉址皆無法還原原始網址 → 取不到內文，故不採用
"""

import html as _html
import logging
import random
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Optional

import requests
from bs4 import BeautifulSoup

from utils.user_agents import get_headers

logger = logging.getLogger(__name__)

# ── 來源設定 ────────────────────────────────────────────────────────────────
GENERAL_FEEDS = [
    ('中央社財經',   'https://feeds.feedburner.com/rsscna/finance'),
    ('經濟日報證券', 'https://money.udn.com/rssfeed/news/1001/5590?ch=money'),
    ('經濟日報產業', 'https://money.udn.com/rssfeed/news/1001/5591?ch=money'),
    ('自由財經',     'https://news.ltn.com.tw/rss/business.xml'),
]

# 國際頭條（Iteration 38 階段 3）：scope GLOBAL，英文；抓原文頁（實測 article > p 可用，內文約 3,000 字）
GLOBAL_FEEDS = [
    ('BBC Business', 'https://feeds.bbci.co.uk/news/business/rss.xml'),
    ('BBC World',    'https://feeds.bbci.co.uk/news/world/rss.xml'),
]
GLOBAL_FEED_LIMIT = 15

YAHOO_STOCK_RSS = 'https://tw.stock.yahoo.com/rss?s={code}.TW'

CNYES_API = ('https://news.cnyes.com/api/v3/news/category/tw_stock_news'
             '?limit={limit}')

# 內文容器選擇器（由精確到寬鬆；實測 cna/udn/ltn 分別命中前三個）
_CONTENT_SELECTORS = [
    'div.paragraph',              # 中央社
    'div#story_body_content',     # 經濟日報（舊版）
    'div.text',                   # 自由時報
    'article',                    # 經濟日報（新版）與多數新版型
    'div[itemprop="articleBody"]',
    'div.article-body', 'div.caas-body', 'div.story',
]

# 禮貌性延遲（秒）。舊爬蟲每次請求等 60~300 秒導致實際跑不完；
# RSS 與文章頁是公開靜態內容，數秒級延遲已足夠禮貌。
DELAY_RANGE = (1.2, 3.0)

# 兩種內文來源有不同的合格標準，混為一談會誤殺：
#   MIN_BODY_LEN    抓取原文頁的結果低於此 → 判定「抓取失敗」（非文章太短）
#   MIN_SUMMARY_LEN RSS 摘要本來就短，只要不是空的即可用於情緒與個股標記
MIN_BODY_LEN = 120
MIN_SUMMARY_LEN = 40
MAX_ITEMS_PER_FEED = 25

# 內文若命中這些字樣且過短，代表抓到提示頁而非新聞
_BOILERPLATE = ['請開啟javascript', 'enable javascript', '您的瀏覽器不支援',
                '訂閱電子報', '請先登入', 'access denied', '404 not found']

# 標題尾端的相對時間文字（Yahoo 版型會把它併進連結文字）
_REL_TIME_RE = re.compile(r'\s*\d+\s*(分鐘|小時|天|週|個月)前\s*$')

# 台股股號標註格式：（2330）、(2330)、(2330-TW)、【2330】
_CODE_IN_TEXT_RE = re.compile(r'[（(【]\s*(\d{4,6})(?:-TW)?\s*[）)】]')


def _sleep():
    time.sleep(random.uniform(*DELAY_RANGE))


def _strip_html(s: str) -> str:
    """去標籤 + 還原 HTML 實體（鉅亨網 API 的 content 是雙重跳脫的）。"""
    if not s:
        return ''
    text = _html.unescape(str(s))
    text = re.sub(r'<[^>]+>', ' ', text)
    return re.sub(r'\s+', ' ', text).strip()


def clean_title(title: str) -> str:
    """去除標題尾端的「7 小時前」等相對時間文字與來源後綴。"""
    t = _REL_TIME_RE.sub('', (title or '').strip())
    t = re.sub(r'\s*[-–|｜]\s*(自由財經|經濟日報|中央社 CNA|Yahoo奇摩股市|鉅亨網)\s*$', '', t)
    return t.strip()


def _parse_pubdate(raw: str) -> Optional[datetime]:
    """解析 RSS pubDate（RFC 2822），統一轉為 naive 本地時間。"""
    if not raw:
        return None
    try:
        dt = parsedate_to_datetime(raw)
        return dt.astimezone().replace(tzinfo=None) if dt.tzinfo else dt
    except Exception:
        for fmt in ('%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d'):
            try:
                return datetime.strptime(raw[:19], fmt)
            except ValueError:
                continue
    return None


# ── ① 來源讀取 ──────────────────────────────────────────────────────────────
def fetch_rss_items(session, platform: str, url: str, limit: int = MAX_ITEMS_PER_FEED) -> list:
    """讀取 RSS，回傳 [{platform,title,link,published_at,summary,content}, ...]。"""
    try:
        resp = session.get(url, headers=get_headers(), timeout=25)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
    except Exception as e:
        logger.warning('[news2] %s RSS 讀取失敗：%s', platform, e)
        return []

    out = []
    for it in root.findall('.//item')[:limit]:
        def g(tag):
            el = it.find(tag)
            return (el.text or '').strip() if el is not None and el.text else ''

        title, link = clean_title(g('title')), g('link')
        if not title or not link:
            continue
        out.append({'platform': platform, 'title': title, 'link': link,
                    'published_at': _parse_pubdate(g('pubDate')),
                    'summary': _strip_html(g('description')), 'content': ''})
    return out


def fetch_cnyes_items(session, limit: int = 30) -> list:
    """
    鉅亨網 JSON API —— content 直接隨 API 回傳，不需再抓原文頁。
    這是最穩定也最快的來源。
    """
    try:
        resp = session.get(CNYES_API.format(limit=limit), headers=get_headers(), timeout=25)
        resp.raise_for_status()
        data = resp.json()['items']['data']
    except Exception as e:
        logger.warning('[news2] 鉅亨網 API 失敗：%s', e)
        return []

    out = []
    for it in data:
        title = clean_title(it.get('title', ''))
        if not title:
            continue
        ts = it.get('publishAt')
        out.append({
            'platform':     '鉅亨網',
            'title':        title,
            'link':         f"https://news.cnyes.com/news/id/{it.get('newsId')}",
            'published_at': datetime.fromtimestamp(ts) if ts else None,
            'summary':      _strip_html(it.get('summary')),
            'content':      _strip_html(it.get('content')),
        })
    logger.info('[news2] 鉅亨網 API：%d 則（內文隨 API 附帶）', len(out))
    return out


# ── ② 內文抓取與驗證 ────────────────────────────────────────────────────────
def fetch_article_content(session, url: str) -> str:
    """
    抓取文章原文頁並萃取內文；失敗回空字串（呼叫端改用 RSS 摘要）。

    **刻意不做「全頁 <p>」的通用 fallback**：實測 Yahoo 的排行類文章
    `article` 容器為空，全頁掃描會把側欄其他文章的內文掃進來，
    造成標題與內文張冠李戴（情緒與個股標記全被歸到錯的新聞上）。
    寧可回空字串退回摘要，也不要抓到別篇文章。
    """
    try:
        resp = session.get(url, headers=get_headers(), timeout=25)
        resp.raise_for_status()
    except Exception as e:
        logger.debug('[news2] 內文抓取失敗 %s：%s', url[:70], e)
        return ''

    soup = BeautifulSoup(resp.text, 'html.parser')
    for tag in soup(['script', 'style', 'nav', 'header', 'footer', 'aside', 'form']):
        tag.decompose()

    for sel in _CONTENT_SELECTORS:
        for node in soup.select(sel):
            paras = [p.get_text(strip=True) for p in node.find_all('p')]
            text = ' '.join(t for t in paras if len(t) > 15)
            if len(text) >= MIN_BODY_LEN:
                return text
    return ''


def _matches_summary(summary: str, content: str) -> bool:
    """
    交叉驗證：RSS 摘要通常取自文章開頭，故抓回的內文應與摘要有明顯重疊。
    重疊過低代表抓到的是別篇文章（見 fetch_article_content 的說明）。
    摘要太短時無從判斷，一律放行。
    """
    s = re.sub(r'\s+', '', summary or '')
    c = re.sub(r'\s+', '', content or '')
    if len(s) < 30 or not c:
        return True
    if s[:24] in c:                      # 摘要開頭直接出現在內文
        return True
    grams = {s[i:i + 6] for i in range(0, max(len(s) - 6, 1), 3)}
    hit = sum(1 for g in grams if g in c)
    return hit / max(len(grams), 1) >= 0.3


def validate_content(title: str, content: str, kind: str = 'body') -> tuple:
    """
    內文品質檢查，回傳 (是否合格, 原因)。

    這是本迭代的重點：舊爬蟲從不檢查內文，於是「內文全空」這件事
    從 Iteration 2 一路無人發現，直到 Iteration 10 才查出來。

    kind='body'    抓取原文頁的結果，門檻高（低於門檻視為抓取失敗）
    kind='summary' RSS 摘要，本來就短，門檻低
    """
    floor = MIN_SUMMARY_LEN if kind == 'summary' else MIN_BODY_LEN
    if not content or len(content) < floor:
        return False, f'內文過短（{len(content or "")} 字 < {floor}）'

    low = content.lower()
    for bp in _BOILERPLATE:
        if bp in low and len(content) < 300:
            return False, f'疑似提示頁（命中「{bp}」）'

    # 中文標題的文章，內文中日韓字比例過低多半是抓到導覽列或英文樣板
    if re.search(r'[一-鿿]', title):
        cjk = len(re.findall(r'[一-鿿]', content))
        if cjk / max(len(content), 1) < 0.25:
            return False, f'中文比例過低（{cjk}/{len(content)}）'

    if len(set(content)) < 30:
        return False, '字元變化過少（疑為樣板）'

    return True, 'ok'


# ── ③ 個股標記 ──────────────────────────────────────────────────────────────
def load_stock_map() -> dict:
    """從 stock_info 讀取 {股票代碼: 公司名稱}。"""
    try:
        from db.connection import get_conn
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute('SELECT stock_id, stock_name FROM stock_info')
                return {r[0]: (r[1] or '') for r in cur.fetchall()}
    except Exception as e:
        logger.warning('[news2] 讀取 stock_info 失敗，個股標記停用：%s', e)
        return {}


def tag_tickers(text: str, stock_map: dict) -> list:
    """
    標記個股代碼。兩種依據：
      1. 台股慣用標註格式「公司名（2330）」「(2330-TW)」——精確度高
      2. 公司名稱直接比對

    僅回傳存在於 stock_info 的代碼。舊 `_auto_tickers` 用裸數字比對，
    會把「台股收在 44396 點」的 44396 誤判為股號。
    """
    if not text or not stock_map:
        return []
    found = [c for c in _CODE_IN_TEXT_RE.findall(text) if c in stock_map]
    found += [code for code, name in stock_map.items()
              if name and len(name) >= 2 and name in text]
    # Iteration 38：別名表（台積 / TSMC / 台灣50 / 國巨 去星號）。表不存在即略過。
    try:
        import news_alias
        found += [c for c in news_alias.match(text) if c in stock_map]
    except Exception:
        pass
    return list(dict.fromkeys(found))


# ── ④ 主流程 ────────────────────────────────────────────────────────────────
def scrape_news(session, stock_codes: list = None, max_articles: int = 150,
                max_fetches: int = 90, fetch_full: bool = True) -> dict:
    """
    爬取三類來源並回傳可直接入庫的文章清單。

    stock_codes：要定向抓取的股票代碼（通常是 is_tracking 清單）
    max_fetches：最多為幾則抓取原文頁（時間的主要成本；超出者改用 RSS 摘要）
    Returns: {'articles': [...], 'stats': {...}}

    來源順序刻意為「鉅亨網 → 一般財經 → 個股定向」：
    鉅亨網的內文隨 API 附帶、不佔抓取預算，先處理等於免費多拿一批完整內文。
    """
    from scrapers.news_scraper import _extract_keywords, _is_financial

    stock_map = load_stock_map()
    logger.info('[news2] 個股標記字典 %d 檔', len(stock_map))

    raw, seen = [], set()

    def add(items):
        for it in items:
            key = re.sub(r'\W+', '', it['title'])[:36]
            if key and key not in seen:
                seen.add(key)
                raw.append(it)

    # A 鉅亨網（內文隨 API 附帶，不需抓原文頁）
    add(fetch_cnyes_items(session, limit=30))
    _sleep()

    # B 一般財經
    for platform, url in GENERAL_FEEDS:
        add(fetch_rss_items(session, platform, url))
        _sleep()

    # B2 國際頭條（BBC）：量少但 scope GLOBAL，方案文件的「世界頭條」層
    for platform, url in GLOBAL_FEEDS:
        add(fetch_rss_items(session, platform, url, limit=GLOBAL_FEED_LIMIT))
        _sleep()

    # C 個股定向（量最大，放最後以免佔滿抓取預算）
    for code in (stock_codes or []):
        add(fetch_rss_items(session, f'Yahoo個股{code}',
                            YAHOO_STOCK_RSS.format(code=code), limit=12))
        _sleep()

    logger.info('[news2] 去重後 %d 則候選', len(raw))

    stats = {'candidates': len(raw), 'content_from_api': 0, 'content_fetched': 0,
             'content_from_summary': 0, 'mismatch_rejected': 0,
             'content_failed': 0, 'not_financial': 0, 'tagged': 0,
             'kept': 0, 'reasons': {}}

    articles = []
    fetches_used = 0
    for it in raw[:max_articles]:
        content, kind = it.get('content') or '', 'api'
        if content:
            stats['content_from_api'] += 1
        elif fetch_full and fetches_used < max_fetches:
            _sleep()
            fetches_used += 1
            body = fetch_article_content(session, it['link'])
            if body and not _matches_summary(it['summary'], body):
                # 抓到的內文與摘要對不上 → 多半是別篇文章，改用摘要
                stats['mismatch_rejected'] += 1
                logger.debug('[news2] 內文與摘要不符，改用摘要：%s', it['title'][:40])
                body = ''
            if len(body) > len(it['summary']):
                content, kind = body, 'body'
                stats['content_fetched'] += 1
            else:
                content, kind = it['summary'], 'summary'
                stats['content_from_summary'] += 1
        else:
            content, kind = it['summary'], 'summary'
            stats['content_from_summary'] += 1

        ok, reason = validate_content(it['title'], content,
                                      kind='summary' if kind == 'summary' else 'body')
        if not ok:
            stats['content_failed'] += 1
            k = reason.split('（')[0]
            stats['reasons'][k] = stats['reasons'].get(k, 0) + 1
            continue

        combined = it['title'] + ' ' + content
        is_global = any(it['platform'] == p for p, _ in GLOBAL_FEEDS)
        if not is_global and not _is_financial(combined):
            stats['not_financial'] += 1
            continue

        tickers = tag_tickers(combined, stock_map)
        if tickers:
            stats['tagged'] += 1

        articles.append({
            'platform':     it['platform'],
            'title':        it['title'],
            'content':      content,
            'content_kind': kind,          # api / body / summary，供品質追蹤
            'tickers':      tickers,
            'keywords':     _extract_keywords(combined),
            'source_url':   it['link'],
            'published_at': it['published_at'],
            'is_financial': True,
        })

    stats['fetches_used'] = fetches_used

    stats['kept'] = len(articles)
    return {'articles': articles, 'stats': stats}
