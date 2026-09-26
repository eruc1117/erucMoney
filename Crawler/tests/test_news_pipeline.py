"""新聞管線：來源解析（RSS／鉅亨網 API／原文頁／舊首頁）、標題清理與時區、內文驗證、個股標記與別名、
去重（SimHash）、日級對齊、來源登記表、鉅亨網回填分頁與重試。全部不上網、不碰資料庫。"""
import json
from datetime import date, datetime, timedelta

import pytest
import requests
import responses
from bs4 import BeautifulSoup

import backfill_news
import news_align
import news_alias
import news_dedup
import news_sources
from scrapers import news_scraper, rss_news_scraper as rss


# ── 標題／時間／HTML 清理 ─────────────────────────────────────────────────────
@pytest.mark.parametrize('raw, expected', [
    ('台積電法說會 3 小時前', '台積電法說會'),
    ('聯電營收 - 中央社 CNA', '聯電營收'),
    ('友達漲停｜鉅亨網', '友達漲停'),
    ('  兩邊有空白 2 天前 ', '兩邊有空白'),
    ('', ''), (None, ''),
])
def test_clean_title(raw, expected):
    assert rss.clean_title(raw) == expected


def test_strip_html_double_escaped():
    assert rss._strip_html('&lt;p&gt;友達 &nbsp;漲停&lt;/p&gt;') == '友達 漲停'     # 去標籤、&nbsp; 當空白
    assert rss._strip_html(None) == ''


def test_parse_pubdate_normalises_to_naive_local():
    """RFC 2822 帶時區 → 轉本地後去掉 tzinfo；ISO 字串走 fallback；壞字串 None。"""
    dt = rss._parse_pubdate('Fri, 26 Sep 2026 02:30:00 +0000')
    assert dt.tzinfo is None
    expected = datetime(2026, 9, 26, 2, 30).replace(tzinfo=__import__('datetime').timezone.utc).astimezone().replace(tzinfo=None)
    assert dt == expected
    assert rss._parse_pubdate('2026-09-26T10:15:00+08:00') == datetime(2026, 9, 26, 10, 15)
    assert rss._parse_pubdate('2026-09-26') == datetime(2026, 9, 26)
    assert rss._parse_pubdate('not a date') is None and rss._parse_pubdate('') is None


# ── 來源解析 ──────────────────────────────────────────────────────────────────
@responses.activate
def test_fetch_rss_items(fx):
    url = 'https://feeds.feedburner.com/rsscna/finance'
    responses.get(url, body=fx('rss_cna.xml').encode('utf-8'), content_type='application/xml')
    items = rss.fetch_rss_items(requests.Session(), '中央社財經', url)
    assert [i['title'] for i in items] == ['台積電（2330）法說會釋利多 外資調高目標價', '聯電 8 月營收月增 4.2%']   # 相對時間、來源後綴去掉；空標題／無連結略過
    assert items[0]['published_at'] == datetime(2026, 9, 26, 10, 15).replace(tzinfo=__import__('datetime').timezone(timedelta(hours=8))).astimezone().replace(tzinfo=None)
    assert items[0]['summary'] == '台積電今日召開法說會， 釋出第四季展望優於預期。'   # 去標籤、還原實體
    assert items[0]['content'] == '' and items[0]['platform'] == '中央社財經'
    assert rss.fetch_rss_items(requests.Session(), '中央社財經', url, limit=1) and len(rss.fetch_rss_items(requests.Session(), 'x', url, limit=1)) == 1


@responses.activate
def test_fetch_rss_items_network_failure_is_empty():
    url = 'https://example.invalid/rss.xml'
    responses.get(url, status=500)
    assert rss.fetch_rss_items(requests.Session(), 'x', url) == []


@responses.activate
def test_fetch_cnyes_items(fx):
    responses.get(rss.CNYES_API.format(limit=30), json=json.loads(fx('cnyes_api.json')))
    items = rss.fetch_cnyes_items(requests.Session())
    assert len(items) == 2                                    # 無標題的丟掉
    a = items[0]
    assert a['platform'] == '鉅亨網' and a['link'] == 'https://news.cnyes.com/news/id/5001'
    assert a['published_at'] == datetime.fromtimestamp(1790405400)
    assert a['content'] == '友達 (2409-TW) 今日以漲停作收， 群創同步走高。'    # API 內文雙重跳脫還原


@responses.activate
def test_fetch_article_content_uses_article_container_not_nav(fx):
    url = 'https://www.cna.com.tw/news/afe/202609260101.aspx'
    responses.get(url, body=fx('article_cna.html').encode('utf-8'), content_type='text/html; charset=utf-8')
    text = rss.fetch_article_content(requests.Session(), url)
    assert text.startswith('台積電今日召開法說會') and '導覽列' not in text and '版權所有' not in text
    assert '短' not in text                                    # 過短的段落不算內文
    responses.replace(responses.GET, url, status=404)
    assert rss.fetch_article_content(requests.Session(), url) == ''


def test_validate_content_rules():
    body = '台積電今日召開法說會，釋出第四季展望優於預期，外資隨即調高目標價至三千元，並維持買進評等不變；法人指出先進製程需求持續強勁。' * 2
    ok, _ = rss.validate_content('台積電法說會', body)
    assert ok
    assert rss.validate_content('台積電法說會', '太短')[0] is False
    assert rss.validate_content('台積電', '請開啟javascript 才能閱讀' + 'x' * 100)[0] is False
    assert rss.validate_content('台積電法說會', 'this is mostly english text ' * 6)[0] is False        # 中文標題、內文幾乎沒中文
    assert rss.validate_content('台積電法說會', '台積電' * 60)[0] is False                              # 字元變化過少
    assert rss.validate_content('x', '摘要不長也可以', kind='summary')[0] is False
    assert rss.validate_content('x', '摘要只要超過四十個字元就可以通過這個門檻，因為本來就是摘要不是全文，門檻本來就比原文頁低很多。', kind='summary')[0] is True


def test_matches_summary():
    assert rss._matches_summary('短', '任何內文') is True
    s = '台積電今日召開法說會，釋出第四季展望優於預期，外資隨即調高目標價至三千元'
    assert rss._matches_summary(s, '前言。' + s + '後續') is True
    assert rss._matches_summary(s, '完全不同的另一篇文章的內文，講的是聯電的營收與展望，與台積電無關。' * 2) is False


def test_legacy_soup_parsers(fx):
    soup = BeautifulSoup(fx('yahoo_home.html'), 'html.parser')
    ys = news_scraper._parse_yahoo_soup(soup, 'Yahoo Finance 台灣')
    assert [y['title'] for y in ys] == ['台積電法說會後外資大買超三萬張', '聯電 8 月營收月增 4.2% 創同期新高']  # 去重、分類頁、廣告、過短、非文章頁
    cs = news_scraper._parse_cnn_soup(BeautifulSoup(fx('cnn_home.html'), 'html.parser'), 'CNN Business')
    assert [c['title'] for c in cs] == ['Fed minutes show officials split over pace of rate cuts',
                                        'TSMC raises outlook as AI chip demand accelerates again']
    art = news_scraper._extract_from_soup(BeautifulSoup(fx('article_cna.html'), 'html.parser'), '中央社')
    assert art['title'] == '台積電法說會釋利多 外資調高目標價'          # og:title 優先
    assert news_scraper._is_financial('台積電 營收 創新高') is True
    assert news_scraper._auto_tickers('台股收在 44396 點，2330 與 2303 走強') == ['44396', '2330', '2303']   # 舊法的已知缺陷：裸數字


# ── 個股標記與別名 ────────────────────────────────────────────────────────────
STOCK_MAP = {'2330': '台積電', '2303': '聯電', '2327': '國巨*', '0050': '元大台灣50', '2883': '凱基金'}


@pytest.fixture
def alias_map(monkeypatch):
    m = {'zh': {'台積': ['2330'], '台積電': ['2330'], '台灣50': ['0050'], '國巨': ['2327'], '開發金': ['2883']},
         'en': {'tsmc': ['2330'], 'umc': ['2303'], 'via technologies': ['2388']}}
    import re
    m['en_re'] = re.compile(r'\b(' + '|'.join(re.escape(a) for a in sorted(m['en'], key=len, reverse=True)) + r')\b', re.IGNORECASE)
    monkeypatch.setattr(news_alias, 'load_alias_map', lambda force=False: m)
    return m


def test_tag_tickers_code_format_and_names(alias_map):
    assert rss.tag_tickers('台積電（2330）與聯電(2303-TW)、【0050】', STOCK_MAP) == ['2330', '2303', '0050']
    assert rss.tag_tickers('台股收在 44396 點', STOCK_MAP) == []                     # 裸數字不算
    assert rss.tag_tickers('（9999）不存在的代碼', STOCK_MAP) == []
    assert rss.tag_tickers('', STOCK_MAP) == [] and rss.tag_tickers('台積電', {}) == []


def test_alias_match_zh_substring_and_en_whole_word(alias_map):
    assert news_alias.match('台積法說會與 TSMC ADR', alias_map) == ['2330']         # 去重、依出現順序
    assert news_alias.match('台灣50 反彈；國巨* 大漲', alias_map) == ['0050', '2327']  # 星號名稱靠別名
    assert news_alias.match('umc 與 UMC', alias_map) == ['2303']                    # 英文大小寫不分
    assert news_alias.match('circumcision via email', alias_map) == []              # 整字比對：via ≠ VIA Technologies
    assert news_alias.match('開發金', alias_map) == ['2883']                        # 簡稱
    assert news_alias.match('', alias_map) == [] and news_alias.match('x', {}) == []


def test_tag_tickers_uses_alias_when_available(alias_map):
    assert rss.tag_tickers('台積 法說', STOCK_MAP) == ['2330']


def test_norm_name_strips_markers():
    assert news_alias._norm_name('國巨*') == '國巨' and news_alias._norm_name(' 台 積 電 ') == '台積電'


# ── 來源登記表 ────────────────────────────────────────────────────────────────
def test_sources_registry():
    assert news_sources.info('鉅亨網') == (2, 'TW', 'zh')
    assert news_sources.scope('BBC World') == 'GLOBAL' and news_sources.tier('MOPS重大訊息') == 1
    assert news_sources.info('Yahoo個股 2330') == (3, 'TW', 'zh')
    assert news_sources.info('') == news_sources.DEFAULT == news_sources.info('沒登記的')


# ── 去重 ──────────────────────────────────────────────────────────────────────
def test_normalize_title_and_simhash_distance():
    assert news_dedup.normalize_title('台積電 漲 3%！') == news_dedup.normalize_title('台積電漲3.2%')   # 數字統一、標點去掉、全形→半形
    a = news_dedup.simhash('台積電法說會釋利多 外資調高目標價')
    b = news_dedup.simhash('台積電法說會釋利多，外資調高目標價!')
    c = news_dedup.simhash('聯電八月營收月增百分之四')
    assert news_dedup.hamming(a, b) <= news_dedup.HAMMING_MAX
    assert news_dedup.hamming(a, c) > news_dedup.HAMMING_MAX


def test_group_rows_prefers_tier_then_earliest_and_respects_window():
    t0 = datetime(2026, 9, 26, 10, 0)
    rows = [
        (1, '台積電法說會釋利多 外資調高目標價', '鉅亨網', t0 + timedelta(hours=1)),       # tier 2
        (2, '台積電法說會釋利多，外資調高目標價!', '中央社財經', t0 + timedelta(hours=3)),   # tier 1 → canonical
        (3, '台積電法說會釋利多 外資調高目標價', 'Yahoo Finance 台灣', t0 + timedelta(days=10)),  # 超過 3 天窗口 → 不併
        (4, '聯電八月營收月增百分之四', '鉅亨網', t0),
        (5, None, '鉅亨網', t0), (6, '沒有時間', '鉅亨網', None),
    ]
    mapping = news_dedup.group_rows(rows)
    assert mapping == {1: 2, 2: 2}
    assert news_dedup.tier_of('中央社財經') == 1


# ── 日級對齊 ──────────────────────────────────────────────────────────────────
def test_effective_date_rules():
    days = [date(2026, 9, 22), date(2026, 9, 23), date(2026, 9, 24), date(2026, 9, 25), date(2026, 9, 29)]   # 9/26 週五休市（模擬假日）、週末
    eff = news_align.effective_date
    assert eff(datetime(2026, 9, 23, 9, 0), days) == (date(2026, 9, 23), 0)          # 收盤前 → 當日
    assert eff(datetime(2026, 9, 23, 13, 30), days) == (date(2026, 9, 24), 1)        # 13:30 起算收盤後 → 下一交易日
    assert eff(datetime(2026, 9, 25, 15, 0), days) == (date(2026, 9, 29), 4)         # 週五收盤後跨假日與週末
    assert eff(datetime(2026, 9, 26, 10, 0), days) == (date(2026, 9, 29), 3)         # 休市日 → 下一交易日
    assert eff(datetime(2026, 9, 27, 10, 0), days) == (date(2026, 9, 29), 2)         # 週六
    assert eff(datetime(2026, 10, 1, 9, 0), days) == (date(2026, 10, 1), 0)          # 日曆之外、平日收盤前 → 外推當日
    assert eff(datetime(2026, 10, 2, 15, 0), days) == (date(2026, 10, 5), 3)         # 日曆之外、週五收盤後 → 下週一
    assert eff(datetime(2026, 9, 23, 15, 0), days, market='US') == (date(2026, 9, 23), 0)   # 美股 16:00 收盤


# ── 鉅亨網回填 ────────────────────────────────────────────────────────────────
def test_month_windows():
    w = list(backfill_news._month_windows(date(2026, 1, 15), date(2026, 3, 3)))
    assert w == [(date(2026, 1, 15), date(2026, 2, 1)), (date(2026, 2, 1), date(2026, 3, 1)), (date(2026, 3, 1), date(2026, 3, 4))]


def test_item_to_article_tickers_keywords_scope(alias_map, fx):
    it = json.loads(fx('cnyes_api.json'))['items']['data'][0]
    a = backfill_news._item_to_article(it, 'tw_stock', {'2409': '友達', '3481': '群創'})
    assert a['tickers'] == ['2409', '3481']            # API 自帶標記（不存在的 9999 丟掉）+ 公司名比對
    assert a['keywords'] == ['友達', '光電'] and a['scope'] == 'TW' and a['platform'] == '鉅亨網'
    assert a['is_financial'] is True and a['source_url'] == 'https://news.cnyes.com/news/id/5001'
    assert a['published_at'] == datetime.fromtimestamp(1790405400)
    assert backfill_news._item_to_article({'title': '', 'publishAt': 1}, 'tw_stock', {}) is None


@responses.activate
def test_get_page_retries_on_429_then_succeeds():
    url = backfill_news.API.format(cat='tw_stock')
    responses.get(url, status=429)
    responses.get(url, json={'items': {'data': [], 'total': 0, 'last_page': 1}})
    out = backfill_news._get_page(requests.Session(), 'tw_stock', datetime(2026, 9, 1), datetime(2026, 9, 2), 1)
    assert out['last_page'] == 1 and len(responses.calls) == 2
    q = responses.calls[0].request.url
    assert 'startAt=' in q and 'endAt=' in q and 'page=1' in q


@responses.activate
def test_get_page_gives_up():
    url = backfill_news.API.format(cat='tw_stock')
    for _ in range(backfill_news.MAX_RETRY):
        responses.get(url, status=500)
    with pytest.raises(RuntimeError, match='重試'):
        backfill_news._get_page(requests.Session(), 'tw_stock', datetime(2026, 9, 1), datetime(2026, 9, 2), 1)
