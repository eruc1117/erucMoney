"""MOPS 重大訊息與月營收：發言時間戳與來源、營收月份對應、重複公告的去重鍵、被擋重試。"""
import json
from datetime import date, datetime

import pytest
import responses

import backfill_mops
import backfill_revenue
import backfill_revenue_dates as brd


# ── MOPS 公告 ─────────────────────────────────────────────────────────────────
def test_parse_mops_table_roc_date_and_time(fx):
    items = backfill_mops._parse(fx('mops_month.html'))
    # 壞日期、不存在的日期、欄數不足的列都不進來；重複的兩列都保留（去重在寫入層以 source_url 判）
    assert len(items) == 3
    first = items[0]
    assert first['code'] == '2330' and first['name'] == '台積電'
    assert first['date'] == datetime(2026, 9, 10, 17, 23, 5)        # 民國 115 → 2026，含秒
    assert first['subject'] == '公告本公司115年8月營收'
    assert items[2]['date'] == datetime(2026, 9, 23, 9, 5, 0)       # 時間只有 HH:MM 也可


def test_to_article_carries_announce_ts_and_source():
    item = {'code': '2330', 'name': '台積電', 'date': datetime(2026, 9, 10, 17, 23, 5), 'subject': '公告本公司115年8月營收'}
    a = backfill_mops.to_article(item)
    assert a['platform'] == backfill_mops.PLATFORM == 'MOPS重大訊息'
    assert a['published_at'] == datetime(2026, 9, 10, 17, 23, 5)     # 精確到秒的發言時間
    assert a['source_url'] == 'mops://2330/2026-09-10T17:23:05'       # 唯一鍵：同一則公告重抓也是同一把
    assert a['tickers'] == ['2330'] and a['content_kind'] == 'filing' and a['is_financial'] is True
    assert a['title'].startswith('台積電（2330）')
    # 同一則公告解析兩次 → 同一個 source_url，寫入層 ON CONFLICT 會擋掉第二筆
    assert backfill_mops.to_article(dict(item))['source_url'] == a['source_url']


def test_month_iterator_crosses_year():
    assert list(backfill_mops._months('2025-11', '2026-02')) == [(2025, 11), (2025, 12), (2026, 1), (2026, 2)]
    assert list(backfill_mops._months('2026-03', '2026-02')) == []


@responses.activate
def test_fetch_month_blocked_then_ok(fx):
    """被「安全性考量」擋 → 等一輪再試（sleep 已 no-op）；查無 → 空清單。"""
    responses.post(backfill_mops.URL, body='<html>安全性考量</html>')
    responses.post(backfill_mops.URL, body=fx('mops_month.html'))
    import requests
    items = backfill_mops.fetch_month(requests.Session(), '2330', 2026, 9)
    assert len(items) == 3 and len(responses.calls) == 2
    sent = responses.calls[1].request.body
    assert 'co_id=2330' in sent and 'year=115' in sent and 'month=09' in sent    # 民國年、兩位數月份

    responses.reset()
    responses.post(backfill_mops.URL, body='<html>查無資料</html>')
    assert backfill_mops.fetch_month(requests.Session(), '2330', 2026, 9) == []


@responses.activate
def test_fetch_month_gives_up_after_max_retry():
    for _ in range(backfill_mops.MAX_RETRY):
        responses.post(backfill_mops.URL, status=503)
    import requests
    with pytest.raises(RuntimeError, match='重試'):
        backfill_mops.fetch_month(requests.Session(), '2330', 2026, 9)


# ── 月營收（FinMind）──────────────────────────────────────────────────────────
@responses.activate
def test_fetch_revenue_month_vs_create_time(fx):
    responses.get(backfill_revenue.API, json=json.loads(fx('finmind_revenue.json')))
    rows = backfill_revenue.fetch_revenue('2330', '2025-01-01')
    assert len(rows) == 2                                    # date 空的列丟掉
    assert rows[0] == {'stock_id': '2330', 'revenue_month': '2026-07-01', 'announce_date': '2026-07-10', 'revenue': 260000000000}
    assert rows[1]['announce_date'] is None                  # 2026-03 之前 create_time 全空 → None，不能拿 date 當公布日
    q = responses.calls[0].request.url
    assert 'dataset=TaiwanStockMonthRevenue' in q and 'data_id=2330' in q


# ── 公布時點的多來源解析 ──────────────────────────────────────────────────────
@pytest.mark.parametrize('month, published, expected', [
    (8, datetime(2026, 9, 10), date(2026, 8, 1)),      # 9 月公布 8 月營收
    (12, datetime(2026, 1, 8), date(2025, 12, 1)),     # 1 月公布去年 12 月
    (9, datetime(2026, 9, 30), date(2025, 9, 1)),      # 同月不可能是當月 → 去年
])
def test_rev_month_mapping(month, published, expected):
    assert brd._rev_month(month, published) == expected


@pytest.mark.parametrize('title, expected', [
    ('公告本公司115年8月營收', 8), ('八月份合併營收', 8), ('十月營收', 10), ('十二月自結營收', 12),
    ('十一月營業收入', 11), ('沒有月份', None), ('13月營收', None), ('營收創新高', None),
])
def test_month_in_title(title, expected):
    assert brd._month_in_title(title) == expected


def test_parse_cnyes_item_quick_report_vs_daily_list():
    item = {'title': '營收速報 - 台積電(2330)8月營收2,600億元創新高', 'publishAt': 1789030980, 'content': ''}
    rows, art = brd.parse_cnyes_item(item)
    assert art is item and len(rows) == 1
    r = rows[0]
    assert r['stock_id'] == '2330' and r['source'] == 'cnyes_item'
    assert r['announce_ts'] == datetime.fromtimestamp(1789030980) and r['announce_date'] == r['announce_ts'].date()
    assert r['revenue_month'] == brd._rev_month(8, r['announce_ts'])

    listing = {'title': '營收速報 - 2026年9月11日台股大型公司8月營收一覽（新增3家）', 'publishAt': 1789030980,
               'content': '<em>本次公布營收年增率前3名</em>TWS:2330:STOCK TWS:2303:STOCK<em>8月營收年增率前5名</em>TWS:9999:STOCK'}
    rows, art = brd.parse_cnyes_item(listing)
    assert art is None
    assert [r['stock_id'] for r in rows] == ['2330', '2303']          # 累計排行段落不拿
    assert rows[0]['source'] == 'cnyes_list' and rows[0]['announce_ts'] is None
    assert rows[0]['announce_date'] == date(2026, 9, 10)               # 清單日 − 1
    assert rows[0]['revenue_month'] == date(2026, 8, 1)

    zero = dict(listing, title='營收速報 - 2026年9月11日台股大型公司8月營收一覽（新增0家）')
    assert brd.parse_cnyes_item(zero)[0] == []                          # 新增 0 家卻有代號 → 不信
    assert brd.parse_cnyes_item({'title': 'x', 'publishAt': None}) == ([], None)


def test_source_priority_order():
    assert brd.PRIORITY['mops_item'] > brd.PRIORITY['cnyes_item'] > brd.PRIORITY['news_item'] \
        > brd.PRIORITY['finmind'] > brd.PRIORITY['cnyes_list'] > brd.PRIORITY['estimated']
