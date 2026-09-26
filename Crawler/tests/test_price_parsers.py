"""價量解析：TWSE JSON 與 FinMind DataFrame → StockDailyPrice；除權息／減資列；額度耗盡。"""
import json
from datetime import date

import pandas as pd
import pytest
import responses

from config import TWSE_API
from helpers.fakes import FakeDataLoader, patch_finmind
from scrapers import twse_scraper
from scrapers.finmind_scraper import FinMindScraper, _to_float, _to_int


# ── TWSE 工具函式 ─────────────────────────────────────────────────────────────
@pytest.mark.parametrize('raw, expected', [
    ('1,234.50', 1234.5), ('  2,460.00 ', 2460.0), ('--', None), ('', None), ('X', None),
    ('+', None), ('-', None), ('１２３', 123.0), ('abc', None), ('-20.00', -20.0),
])
def test_parse_float(raw, expected):
    assert twse_scraper._parse_float(raw) == expected


@pytest.mark.parametrize('raw, expected', [
    ('23,456,789', 23456789), ('--', None), ('', None), ('１,０００', 1000), ('12.5', None),
])
def test_parse_int(raw, expected):
    assert twse_scraper._parse_int(raw) == expected


def test_find_row_by_roc_date():
    rows = [['115/09/19', 'a'], ['115/09/22', 'b'], [], ['115/9/22', 'c']]
    assert twse_scraper._find_row_by_date(rows, date(2026, 9, 22))[1] == 'b'
    assert twse_scraper._find_row_by_date(rows, date(2026, 9, 1)) is None


# ── TWSE API 端到端（responses 攔截）───────────────────────────────────────────
@pytest.fixture
def twse(monkeypatch):
    monkeypatch.setattr(twse_scraper.TWSEScraper, '_random_delay', lambda self: None)
    return twse_scraper.TWSEScraper(['2330'], date(2026, 9, 22))


@responses.activate
def test_twse_daily_price_parses_thousands_and_signs(twse, fx):
    responses.get(TWSE_API['stock_day'], json=json.loads(fx('twse_stock_day.json')))
    p = twse.fetch_daily_price('2330', date(2026, 9, 22))
    assert p.stock_id == '2330' and p.trade_date == date(2026, 9, 22)
    assert p.volume == 14557662 and p.turnover_value == 36107476200.0
    assert p.open_price == 2470.0 and p.close_price == 2460.0
    assert p.change_value == -20.0 and p.transaction_count == 31204
    assert isinstance(p.volume, int) and isinstance(p.close_price, float)


@responses.activate
def test_twse_halted_day_yields_nulls_not_crash(twse, fx):
    responses.get(TWSE_API['stock_day'], json=json.loads(fx('twse_stock_day.json')))
    p = twse.fetch_daily_price('2330', date(2026, 9, 23))     # 全部 -- 的停牌列
    assert p is not None
    assert p.open_price is None and p.close_price is None and p.volume is None and p.change_value is None


@responses.activate
def test_twse_fullwidth_digits(twse, fx):
    responses.get(TWSE_API['stock_day'], json=json.loads(fx('twse_stock_day.json')))
    p = twse.fetch_daily_price('2330', date(2026, 9, 24))
    assert p.volume == 1234 and p.open_price == 2460.0 and p.transaction_count == 1000


@responses.activate
def test_twse_missing_day_and_bad_stat(twse, fx):
    responses.get(TWSE_API['stock_day'], json=json.loads(fx('twse_stock_day.json')))
    assert twse.fetch_daily_price('2330', date(2026, 9, 1)) is None      # 月內沒有那天
    responses.replace(responses.GET, TWSE_API['stock_day'], json={'stat': '很抱歉，沒有符合條件的資料!'})
    assert twse.fetch_daily_price('2330', date(2026, 9, 22)) is None


@responses.activate
def test_twse_empty_body_and_http_error(twse):
    responses.get(TWSE_API['stock_day'], body='')                       # 空回應 → JSON 失敗 → None
    assert twse.fetch_daily_price('2330', date(2026, 9, 22)) is None
    responses.replace(responses.GET, TWSE_API['stock_day'], status=403)
    assert twse.fetch_daily_price('2330', date(2026, 9, 22)) is None


# ── FinMind ───────────────────────────────────────────────────────────────────
def _daily_df():
    return pd.DataFrame([
        {'date': '2026-09-19', 'stock_id': '2330', 'Trading_Volume': 23456789, 'Trading_money': 5.789e10,
         'open': 2450, 'max': 2480, 'min': 2440, 'close': 2480, 'spread': 20, 'Trading_turnover': 45678},
        # 除權息當天：spread 相對前收，close - spread = 除息參考價基準
        {'date': '2026-09-22', 'stock_id': '2330', 'Trading_Volume': 14557662, 'Trading_money': 3.6e10,
         'open': 2470, 'max': 2485, 'min': 2455, 'close': 2460, 'spread': -20, 'Trading_turnover': 31204},
        {'date': '2026-09-23', 'stock_id': '2330', 'Trading_Volume': float('nan'), 'Trading_money': None,
         'open': None, 'max': None, 'min': None, 'close': float('nan'), 'spread': 0, 'Trading_turnover': None},
    ])


def test_finmind_prices_field_mapping_and_change_rate(monkeypatch):
    loader = patch_finmind(monkeypatch, FakeDataLoader({'taiwan_stock_daily': _daily_df()}))
    rows = FinMindScraper(['2330'], date(2026, 9, 19), date(2026, 9, 23)).fetch_prices()
    assert [r.trade_date for r in rows] == [date(2026, 9, 19), date(2026, 9, 22), date(2026, 9, 23)]
    a, b, c = rows
    assert a.volume == 23456789 and a.turnover_value == 5.789e10 and a.transaction_count == 45678
    assert a.change_value == 20 and a.change_rate == round(20 / 2460 * 100, 3)
    assert b.volume == 14557662 and b.transaction_count == 31204
    assert b.change_rate == round(-20 / 2480 * 100, 3)
    # NaN / None → None，不是 0
    assert c.volume is None and c.close_price is None and c.change_rate is None
    assert loader.calls[0][1] == {'stock_id': '2330', 'start_date': '2026-09-19', 'end_date': '2026-09-23'}


def test_finmind_legacy_column_names_with_spaces(monkeypatch):
    """FinMind 曾把欄名從 'Trading Volume' 改成 'Trading_Volume'（那次讓 volume 全 NULL）；兩種都要對到。"""
    legacy = pd.DataFrame([{'date': '2026-09-22', 'Trading Volume': 14557662, 'Trading money': 3.6e10,
                            'open': 2470, 'max': 2485, 'min': 2455, 'close': 2460, 'spread': -20, 'Trading turnover': 31204}])
    patch_finmind(monkeypatch, FakeDataLoader({'taiwan_stock_daily': legacy}))
    b = FinMindScraper(['2330'], date(2026, 9, 22)).fetch_prices()[0]
    assert b.volume == 14557662 and b.turnover_value == 3.6e10 and b.transaction_count == 31204


def test_finmind_empty_response_yields_no_rows(monkeypatch):
    patch_finmind(monkeypatch, FakeDataLoader({'taiwan_stock_daily': pd.DataFrame()}))
    assert FinMindScraper(['2330'], date(2026, 9, 1)).fetch_prices() == []


def test_finmind_rate_limit_is_swallowed_per_stock(monkeypatch, caplog):
    """額度耗盡：FinMind SDK 丟例外 → 該檔略過並記 error，其他檔照抓。"""
    err = Exception('Requests reach the upper limit')
    loader = FakeDataLoader({'taiwan_stock_daily': lambda **kw: _daily_df() if kw['stock_id'] == '2303' else None})
    calls = {'n': 0}

    def daily(**kw):
        calls['n'] += 1
        if kw['stock_id'] == '2330':
            raise err
        return _daily_df()
    loader.frames['taiwan_stock_daily'] = daily
    patch_finmind(monkeypatch, loader)
    with caplog.at_level('ERROR'):
        rows = FinMindScraper(['2330', '2303'], date(2026, 9, 19)).fetch_prices()
    assert {r.stock_id for r in rows} == {'2303'}
    assert 'upper limit' in caplog.text and calls['n'] == 2


@responses.activate
def test_finmind_revenue_quota_exhausted_raises():
    """backfill_revenue 直接打 REST：402 額度耗盡要當失敗（raise），不能當成空資料寫入。"""
    import backfill_revenue
    responses.get(backfill_revenue.API, status=402, json={'msg': 'Requests reach the upper limit', 'status': 402})
    with pytest.raises(Exception):
        backfill_revenue.fetch_revenue('2330', '2026-01-01')


def test_dividend_and_capital_reduction_rows(monkeypatch):
    div = pd.DataFrame([
        {'date': '2026-06-12', 'before_price': 1000, 'reference_price': 996, 'stock_and_cache_dividend': 4.0, 'stock_or_cache_dividend': '息'},
        {'date': '2026-06-13', 'before_price': 1000, 'reference_price': 0, 'stock_and_cache_dividend': 0, 'stock_or_cache_dividend': ''},   # 無參考價 → 略過
    ])
    red = pd.DataFrame([
        {'date': '2022-10-11', 'ClosingPriceonTheLastTradingDay': 14.70, 'PostReductionReferencePrice': 15.87, 'ReasonforCapitalReduction': '彌補虧損'},
        {'date': '2022-10-12', 'ClosingPriceonTheLastTradingDay': 0, 'PostReductionReferencePrice': 15.87, 'ReasonforCapitalReduction': 'x'},
    ])
    patch_finmind(monkeypatch, FakeDataLoader({'taiwan_stock_dividend_result': div,
                                               'taiwan_stock_capital_reduction_reference_price': red}))
    sc = FinMindScraper(['2330'], date(2022, 1, 1))
    d = sc.fetch_dividend_results()
    assert len(d) == 1 and d[0]['ex_date'] == date(2026, 6, 12) and d[0]['reference_price'] == 996 and d[0]['dividend_type'] == '息'
    r = sc.fetch_capital_reductions()
    assert len(r) == 1 and r[0]['reference_price'] == 15.87 and r[0]['before_price'] == 14.70


def test_stock_info_filters_to_requested_ids(monkeypatch):
    info = pd.DataFrame([
        {'stock_id': '2330', 'stock_name': ' 台積電 ', 'industry_category': '半導體業', 'type': 'twse'},
        {'stock_id': '2303', 'stock_name': '聯電', 'industry_category': '', 'type': ''},
        {'stock_id': '9999', 'stock_name': '不要', 'industry_category': 'x', 'type': 'twse'},
    ])
    patch_finmind(monkeypatch, FakeDataLoader({'taiwan_stock_info': info}))
    rows = FinMindScraper(['2330', '2303'], date(2026, 1, 1)).fetch_stock_info()
    assert {r['stock_id'] for r in rows} == {'2330', '2303'}
    assert rows[0]['stock_name'] == '台積電'
    assert rows[1]['industry_type'] is None and rows[1]['market_type'] == '上市'


@pytest.mark.parametrize('val, f, i', [
    (None, None, None), ('1.5', 1.5, 1), (float('nan'), None, None), ('x', None, None), (3, 3.0, 3),
])
def test_to_float_to_int(val, f, i):
    assert _to_float(val) == f and _to_int(val) == i
