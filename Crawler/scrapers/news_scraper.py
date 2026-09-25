"""
新聞爬蟲 — Yahoo Finance 台灣 & CNN Business
支援兩種模式：
  1. 即時模式（NewsScraper.scrape_all）
     直接爬取當前首頁，適合取得最新標題
  2. 歷史模式（NewsScraper.scrape_with_date_range）
     透過 Common Crawl CDX API + HTTP Range Request + warcio
     流程：
       ① collinfo.json → 找出對應日期的 CC 索引及正確的 CDX API URL
       ② CDX API（matchType=prefix）→ 取 warc_filename / offset / length
       ③ HTTP Range Request（只下載幾 KB，不下載整個 WARC 檔）
       ④ warcio 解析 WARC 位元流
       ⑤ BeautifulSoup 萃取 og:title / h1 標題與內文
"""

import json
import logging
import re
import time
import random
from datetime import date, datetime, timedelta
from io import BytesIO
from typing import Optional

from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from warcio.archiveiterator import ArchiveIterator
import requests

from config import REQUEST_TIMEOUT, MAX_RETRIES
from utils.user_agents import get_headers

# jieba 關鍵詞抽取（載入時靜默初始化）
try:
    import jieba
    import jieba.analyse
    jieba.setLogLevel(60)          # 關閉 jieba 初始化 log
    _JIEBA_OK = True
except ImportError:
    _JIEBA_OK = False

# 財經停用詞（避免抽出無意義高頻詞）
_STOP_WORDS = {
    '的', '了', '在', '是', '我', '有', '和', '就', '不', '人', '都', '一',
    '一個', '上', '也', '很', '到', '說', '要', '去', '你', '會', '著',
    '沒有', '看', '好', '自己', '這', '那', '大', '來', '以', '為',
    'the', 'a', 'an', 'of', 'in', 'on', 'at', 'to', 'for', 'is', 'are',
    'was', 'were', 'be', 'been', 'by', 'with', 'as', 'or', 'and', 'but',
    'this', 'that', 'it', 'its', 'from', 'has', 'have', 'had',
}

logger = logging.getLogger(__name__)

# ── 常數 ──────────────────────────────────────────────────────────────────────

CC_COLLINFO_URL = 'https://index.commoncrawl.org/collinfo.json'
CC_S3_BASE      = 'https://data.commoncrawl.org/'
CDX_LIMIT       = 200     # 每個來源每次最多取幾筆 CDX 記錄

# 即時爬取用 URL
REALTIME_URLS = {
    'Yahoo Finance 台灣': 'https://tw.finance.yahoo.com/',
    'CNN Business':      'https://edition.cnn.com/business',
}

# ── 財金新聞來源（CDX matchType=prefix）────────────────────────────────────
# 只抓財金相關子網域 / 路徑，避免爬到娛樂、體育等無關內容
FINANCE_SOURCES = [
    # 平台名稱                    CDX URL pattern
    ('Yahoo Finance 台灣',        'tw.finance.yahoo.com'),
    ('CNN Business',              'edition.cnn.com/business'),
    ('鉅亨網',                    'news.cnyes.com/news/id'),      # 個別文章路徑
    ('聯合財經',                  'money.udn.com/money/story'),
    ('自由財經',                  'ec.ltn.com.tw/article'),
]

# 過濾掉明顯是首頁/分類頁的標題（非個別文章）
_SKIP_TITLES = {
    'Yahoo新聞', 'Yahoo 新聞', 'Yahoo Finance', 'Yahoo奇摩股市',
    'Business News - Latest Headlines on CNN Business | CNN Business',
    'CNN Business', 'CNN',
    '鉅亨網', '聯合新聞網', '自由財經',
}

# ── 財金關鍵詞集合（文章至少命中 1 個才入庫）─────────────────────────────
_FINANCE_TERMS = {
    # 台股/市場
    '股價', '股票', '漲停', '跌停', '加權', '上市', '上櫃', '興櫃',
    '法人', '外資', '投信', '自營商', '三大法人', '融資', '融券',
    '本益比', '殖利率', '除權', '除息', '配股', '配息', 'ETF',
    # 財報/營運
    '營收', '獲利', '毛利', '淨利', '盈餘', 'EPS', '營業利益',
    '財報', '法說會', '年報', '季報', '毛利率',
    # 總經/貨幣
    '利率', '升息', '降息', '通膨', '央行', '聯準會', 'Fed',
    '匯率', '美元', 'GDP', '景氣', '貨幣政策',
    # 英文
    'stock', 'market', 'earnings', 'revenue', 'dividend', 'share',
    'investment', 'fund', 'bond', 'rate', 'inflation', 'Fed',
    'nasdaq', 'dow', 's&p', 'etf', 'ipo', 'buyback',
    # 知名台股
    '台積電', 'TSMC', '鴻海', '聯發科', '台達電', '廣達', '緯創',
    # Target.md 目標股票（代碼 + 公司名）
    '2303', '聯電',
    '2323', '中環',
    '2344', '華邦電',
    '2313', '華通',
    '2409', '友達',
    '3481', '群創',
    '2337', '旺宏',
    '2324', '仁寶',
    '2353', '宏碁',
    '2352', '佳世達',
    '2449', '京元電子',
    '6116', '彩晶',
    '2312', '金寶',
    '2367', '燿華',
    '2388', '威盛',
    '6239', '力成',
    '3037', '欣興',
    '2356', '英業達',
    '5483', '中美晶',
    '3231', '緯創',
}


# ── 工具函式 ───────────────────────────────────────────────────────────────────

def _is_financial(text: str) -> bool:
    """
    快速判斷文章是否屬於財金內容。
    文字中至少命中 1 個財金關鍵詞才回傳 True。
    """
    lower = text.lower()
    return any(kw in lower for kw in _FINANCE_TERMS)


def _extract_keywords(text: str, topk: int = 10) -> list:
    """
    從標題 + 內文抽取關鍵詞。
    有 jieba：使用 TF-IDF 演算法；無 jieba：回退至英文單詞頻率。
    """
    if not text or len(text.strip()) < 5:
        return []

    if _JIEBA_OK:
        try:
            kws = jieba.analyse.extract_tags(text, topK=topk * 2, withWeight=False)
            return [w for w in kws if len(w) >= 2 and w.lower() not in _STOP_WORDS][:topk]
        except Exception:
            pass

    # 回退：英文單詞統計
    words = re.findall(r'[A-Za-z]{3,}', text)
    freq: dict = {}
    for w in words:
        wl = w.lower()
        if wl not in _STOP_WORDS:
            freq[wl] = freq.get(wl, 0) + 1
    return [w for w, _ in sorted(freq.items(), key=lambda x: -x[1])][:topk]


def _auto_tickers(text: str) -> list:
    """
    從文本自動偵測台股代碼（4-5 位數字，範圍 1000-99999）。

    註（Iteration 10）：此函式用裸數字比對，會把「台股收在 44396 點」的 44396
    誤判為股號，且不驗證代碼是否真實存在。新流程改用
    `rss_news_scraper.tag_tickers`（比對股號標註格式與 stock_info 公司名）。
    本函式僅保留給舊的 Common Crawl 路徑使用。
    """
    matches = re.findall(r'\b[0-9]{4,5}\b', text or '')
    return list(dict.fromkeys(t for t in matches if 1000 <= int(t) <= 99999))


def _tracked_stock_codes() -> list:
    """取得 is_tracking 的股票代碼清單（供個股定向爬取）。"""
    try:
        from db.connection import get_conn
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute('SELECT stock_id FROM stock_info WHERE is_tracking = true '
                            'ORDER BY stock_id')
                return [r[0] for r in cur.fetchall()]
    except Exception as e:
        logger.warning('[news] 讀取追蹤清單失敗，略過個股定向爬取：%s', e)
        return []


def _build_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=MAX_RETRIES,
        backoff_factor=1.5,
        status_forcelist=[500, 502, 503, 504],
        allowed_methods=['GET'],
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount('https://', adapter)
    session.mount('http://', adapter)
    return session


def _extract_from_soup(soup: BeautifulSoup, platform: str) -> Optional[dict]:
    """
    從 BeautifulSoup 物件萃取新聞標題與內文。
    優先順序：og:title meta → h1 → 放棄
    """
    # ① og:title（WARC 存檔中最可靠的標題來源）
    og = soup.find('meta', property='og:title')
    if og and og.get('content', '').strip():
        title = og['content'].strip()
    else:
        # ② 依來源不同使用不同 h1 選擇器
        if 'yahoo' in platform.lower():
            el = soup.select_one('.caas-header h1, h1.caas-title, h1')
        else:
            el = soup.select_one('h1.headline__text, h1.pg-headline, h1')
        title = el.get_text(strip=True) if el else ''

    if not title or len(title) < 5:
        return None

    # 過濾首頁/分類頁標題
    if title in _SKIP_TITLES or title.endswith('| CNN Business') and len(title) < 30:
        return None

    # 內文摘要（前 5 段）— 覆蓋所有來源的選擇器
    paras = soup.select(
        # Yahoo Finance / 新聞
        'div.caas-body p, h1.caas-title ~ div p, '
        # CNN Business
        '.article__content p, .zn-body__paragraph, '
        # 鉅亨網
        '.post-content p, .article-body p, '
        # 聯合財經
        '.article-body__editor p, .article-content p, '
        # 自由財經
        '.text p, .boxTitle + div p, '
        # 通用
        'article p'
    )
    content = '\n'.join(p.get_text(strip=True) for p in paras[:5])
    combined = title + ' ' + content
    tickers  = _auto_tickers(combined)
    keywords = _extract_keywords(combined)

    return {'platform': platform, 'title': title, 'content': content,
            'tickers': tickers, 'keywords': keywords}


def _parse_yahoo_soup(soup: BeautifulSoup, platform: str) -> list:
    """從 Yahoo Finance 台灣頁面萃取新聞標題列表（即時用）"""
    results, seen = [], set()
    for a in soup.select('a[href]'):
        href = a.get('href', '')
        # 文章 URL：結尾為 -數字.html（Yahoo 文章固定格式）或含 /news/
        if not (re.search(r'-\d+\.html$', href) or '/news/' in href or '/story/' in href):
            continue
        # 排除 topic / archive / 廣告頁
        if any(skip in href for skip in ['/topic/', '/archive', 'yahoo.com/.']):
            continue
        title = a.get_text(strip=True)
        # 排除廣告（以 | 包圍）、過短、重複
        if not title or len(title) < 8 or title in seen or title.startswith('|'):
            continue
        seen.add(title)
        results.append({
            'platform': platform,
            'title':    title,
            'content':  '',
            'tickers':  _auto_tickers(title),
            'keywords': _extract_keywords(title),
        })
    return results[:25]


def _parse_cnn_soup(soup: BeautifulSoup, platform: str) -> list:
    """從 CNN Business 頁面萃取新聞標題列表（即時用）"""
    results, seen = [], set()
    for el in soup.select('a[data-link-type="article"]'):
        title = el.get_text(strip=True)
        # 排除攝影師版權行與過短文字（真正標題至少 5 個單字）
        if not title or len(title) < 15 or title in seen:
            continue
        word_count = len(title.split())
        if word_count < 5:
            continue
        if re.search(r'^[\w\s]+/[\w\s/]+$', title) and len(title) < 60:
            continue
        seen.add(title)
        results.append({
            'platform': platform,
            'title':    title,
            'content':  '',
            'tickers':  _auto_tickers(title),
            'keywords': _extract_keywords(title),
        })
    return results[:25]


# ── Common Crawl 歷史爬蟲 ─────────────────────────────────────────────────────

class CommonCrawlScraper:
    """
    Common Crawl 歷史新聞爬蟲
    ① collinfo.json  → 找最接近目標日期的 CC 索引，取得正確的 cdx-api URL
    ② CDX API        → 查詢 URL pattern，取 warc_filename / offset / length
    ③ Range Request  → 只下載目標 WARC 區塊（幾百 KB）
    ④ warcio         → 解析 WARC 位元流
    ⑤ BeautifulSoup  → 萃取 og:title / h1 標題
    """

    def __init__(self):
        self.session = _build_session()

    # ── ① 找 CC 索引 ─────────────────────────────────────────────────────────

    def _get_cdx_api_urls(self, start_date: str, end_date: str) -> list:
        """
        從 collinfo.json 找出所有落在 [start_date, end_date] 內的 CC 集合，
        回傳 [(coll_id, cdx_api_url), ...] 列表（依時間排序）。
        5 年約有 50 個集合，每個覆蓋約 2 個月。
        """
        try:
            resp = self.session.get(CC_COLLINFO_URL, headers=get_headers(), timeout=15)
            collections = resp.json()
        except Exception as e:
            logger.warning('[cc] collinfo 查詢失敗: %s', e)
            return []

        start = date.fromisoformat(start_date)
        end   = date.fromisoformat(end_date)
        results = []

        for coll in collections:
            coll_id = coll.get('id', '')
            cdx_api = coll.get('cdx-api', '')
            if not cdx_api:
                continue
            parts = coll_id.split('-')
            if len(parts) != 4 or parts[:2] != ['CC', 'MAIN']:
                continue
            try:
                year, week = int(parts[2]), int(parts[3])
                approx = datetime.strptime(f'{year} {week} 1', '%G %V %u').date()
                if start <= approx <= end:
                    results.append((coll_id, cdx_api))
            except ValueError:
                continue

        results.sort(key=lambda x: x[0])
        logger.info('[cc] 找到 %d 個 CC 集合（%s ~ %s）', len(results), start_date, end_date)
        return results

    # ── ② 查詢 CDX API ───────────────────────────────────────────────────────

    def _query_cdx(self, cdx_api_url: str, url_pattern: str,
                   from_ts: str, to_ts: str) -> list:
        """
        向 CC CDX API 查詢指定 URL pattern 在時間範圍內的 WARC 記錄。
        使用 matchType=prefix 取得路徑下的所有頁面。
        回傳包含 filename / offset / length / url 的 dict 列表。
        """
        query_url = (
            f'{cdx_api_url}'
            f'?url={url_pattern}&output=json&limit={CDX_LIMIT}'
            f'&from={from_ts}&to={to_ts}'
            f'&matchType=prefix&filter=status:200'
        )
        try:
            resp = self.session.get(query_url, headers=get_headers(), timeout=20)
            tasks = []
            for line in resp.text.strip().splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    if rec.get('filename') and rec.get('offset') and rec.get('length'):
                        tasks.append(rec)
                except json.JSONDecodeError:
                    continue
            logger.info('[cc] CDX %s: %d 筆', url_pattern[:40], len(tasks))
            return tasks
        except Exception as e:
            logger.warning('[cc] CDX 查詢失敗 %s: %s', url_pattern, e)
            return []

    # ── ③④⑤ Range Request → warcio → BeautifulSoup ──────────────────────────

    def _fetch_warc_record(self, task: dict, platform: str) -> Optional[dict]:
        """
        根據 CDX 記錄執行 HTTP Range Request，
        用 warcio 解析 WARC 位元流，再用 BeautifulSoup 萃取標題。
        """
        target_url = CC_S3_BASE + task['filename']
        offset     = int(task['offset'])
        length     = int(task['length'])

        range_headers = {
            **get_headers(),
            'Range': f'bytes={offset}-{offset + length - 1}',
        }

        try:
            response = requests.get(
                target_url,
                headers=range_headers,
                stream=True,
                timeout=60,
            )
            response.raise_for_status()

            raw_data = BytesIO(response.content)
            for record in ArchiveIterator(raw_data):
                if record.rec_type != 'response':
                    continue
                html_content = record.content_stream().read()
                soup = BeautifulSoup(html_content, 'html.parser')
                result = _extract_from_soup(soup, platform)
                if result:
                    logger.debug('[cc] 解析成功: %s', result['title'][:60])
                    return result

        except Exception as e:
            logger.warning('[cc] Range Request 失敗 %s: %s', task.get('url', '')[:60], e)

        return None

    # ── 完整流程 ──────────────────────────────────────────────────────────────

    def scrape_date_range(self, start_date: str, end_date: str) -> list:
        """
        爬取指定日期範圍的財金歷史新聞。
        ① 取所有 CC 集合 ② CDX 查詢（僅財金路徑）
        ③ Range Request ④ warcio ⑤ 萃取 ⑥ 財金關鍵詞過濾
        5 年約 50 個集合 × 5 來源 × 200 筆 = 最多 50,000 次請求
        """
        start = date.fromisoformat(start_date)
        end   = date.fromisoformat(end_date)
        if end < start:
            start, end = end, start

        from_ts = start.strftime('%Y%m%d') + '000000'
        to_ts   = end.strftime('%Y%m%d')   + '235959'

        collections = self._get_cdx_api_urls(str(start), str(end))
        if not collections:
            logger.error('[cc] 無法取得任何 CC 集合，放棄歷史爬取')
            return []

        total_coll  = len(collections)
        all_results = []
        seen_urls   = set()   # 跨集合去重

        print(f'\n{"="*60}', flush=True)
        print(f'  新聞爬蟲啟動  {start_date} ~ {end_date}', flush=True)
        print(f'  共 {total_coll} 個 CC 集合 × {len(FINANCE_SOURCES)} 個來源', flush=True)
        print(f'{"="*60}\n', flush=True)

        for coll_idx, (coll_id, cdx_api_url) in enumerate(collections, 1):
            print(f'[{coll_idx}/{total_coll}] 集合 {coll_id}', flush=True)

            for platform, url_pattern in FINANCE_SOURCES:
                tasks = self._query_cdx(cdx_api_url, url_pattern, from_ts, to_ts)
                print(f'  └─ {platform}：CDX {len(tasks)} 筆', flush=True)

                for art_idx, task in enumerate(tasks, 1):
                    src_url = task.get('url', '')
                    if src_url in seen_urls:
                        print(f'     [{art_idx}/{len(tasks)}] 已重複，跳過', flush=True)
                        continue
                    seen_urls.add(src_url)

                    wait = random.uniform(60, 300)
                    print(f'     [{art_idx}/{len(tasks)}] 等待 {wait:.0f}s ...', flush=True)
                    time.sleep(wait)

                    result = self._fetch_warc_record(task, platform)
                    if not result:
                        print(f'     [{art_idx}/{len(tasks)}] 解析失敗，跳過', flush=True)
                        continue

                    combined = result['title'] + ' ' + result['content']
                    result['source_url']   = src_url
                    result['published_at'] = task.get('timestamp', '')
                    result['is_financial'] = _is_financial(combined)
                    all_results.append(result)

                    flag = '✓ 財金' if result['is_financial'] else '✗ 略過'
                    print(f'     [{art_idx}/{len(tasks)}] {flag} | 累計 {len(all_results)} 則 | {result["title"][:40]}', flush=True)

                wait = random.uniform(60, 300)
                print(f'  換來源，等待 {wait:.0f}s ...\n', flush=True)
                time.sleep(wait)

        fin_count = sum(1 for r in all_results if r.get('is_financial'))
        print(f'\n{"="*60}', flush=True)
        print(f'  爬取完成', flush=True)
        print(f'  原始：{len(all_results)} 則  財金：{fin_count} 則  非財金：{len(all_results)-fin_count} 則', flush=True)
        print(f'{"="*60}\n', flush=True)
        logger.info('[cc] 歷史爬取完成：共 %d 則（財金 %d / 非財金 %d）（%s ~ %s）',
                    len(all_results), fin_count, len(all_results) - fin_count, start, end)
        return all_results


# ── 即時爬蟲 + 對外統一介面 ───────────────────────────────────────────────────

class NewsScraper:
    """
    新聞爬蟲統一介面
      scrape_all()                          即時爬取首頁
      scrape_with_date_range(start, end)    Common Crawl 歷史爬取
    """

    def __init__(self):
        self.session = _build_session()
        self._cc     = CommonCrawlScraper()

    def _get(self, url: str, referer: str = '') -> Optional[BeautifulSoup]:
        time.sleep(random.uniform(60, 300))
        try:
            resp = self.session.get(
                url, headers=get_headers(referer=referer), timeout=REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            return BeautifulSoup(resp.text, 'html.parser')
        except Exception as e:
            logger.warning('[news] GET %s 失敗: %s', url, e)
            return None

    # ── 即時 ──────────────────────────────────────────────────────────────────

    def scrape_yahoo_finance_tw(self) -> list:
        url  = REALTIME_URLS['Yahoo Finance 台灣']
        soup = self._get(url, referer='https://tw.yahoo.com/')
        if not soup:
            return []
        result = _parse_yahoo_soup(soup, 'Yahoo Finance 台灣')
        logger.info('[news/yahoo-tw] 即時: %d 則', len(result))
        return result

    def scrape_cnn_business(self) -> list:
        url  = REALTIME_URLS['CNN Business']
        soup = self._get(url, referer='https://edition.cnn.com/')
        if not soup:
            return []
        result = _parse_cnn_soup(soup, 'CNN Business')
        logger.info('[news/cnn] 即時: %d 則', len(result))
        return result

    def scrape_all(self, stock_codes: list = None) -> list:
        """
        即時爬取所有來源（Iteration 10 起改用 RSS/API 來源）。

        舊實作只解析 Yahoo/CNN 首頁的連結文字，產出的文章 content 恆為空字串、
        tickers 恆為空陣列、也沒有發布時間（見 rss_news_scraper 檔頭說明）。
        新實作改用公開 RSS 與鉅亨網 API，並逐則驗證內文品質。

        stock_codes 未指定時自動取 is_tracking 清單，以確保個股新聞覆蓋。
        """
        from scrapers.rss_news_scraper import scrape_news

        if stock_codes is None:
            stock_codes = _tracked_stock_codes()

        result = scrape_news(self.session, stock_codes=stock_codes)
        st = result['stats']
        logger.info(
            '[news] 候選 %d → 保留 %d 則（內文：API %d / 原文 %d / 摘要 %d；'
            '不合格 %d、內文與摘要不符 %d、非財金 %d）；有個股標記 %d 則',
            st['candidates'], st['kept'], st['content_from_api'], st['content_fetched'],
            st['content_from_summary'], st['content_failed'],
            st['mismatch_rejected'], st['not_financial'], st['tagged'],
        )
        return result['articles']

    def scrape_legacy_homepages(self) -> list:
        """舊的首頁標題爬法（內文恆空）。僅保留供比較，正常流程勿用。"""
        all_news = []
        all_news.extend(self.scrape_yahoo_finance_tw())
        all_news.extend(self.scrape_cnn_business())
        logger.info('[news] 即時合計: %d 則', len(all_news))
        return all_news

    # ── 歷史（Common Crawl）──────────────────────────────────────────────────

    def scrape_with_date_range(self, start_date: str, end_date: str) -> list:
        """透過 Common Crawl 爬取歷史新聞"""
        return self._cc.scrape_date_range(start_date, end_date)
