"""資料新鮮度：落後用「市場上有的交易日」算（週末假日不算）、stale 判斷、外生資料三張表、一次最多 N 檔、額度用完提早停。"""
from datetime import date, timedelta

import pytest

import data_freshness

pytestmark = pytest.mark.db

D = [date(2026, 9, 18), date(2026, 9, 22), date(2026, 9, 23), date(2026, 9, 24)]   # 9/19–21 週末，9/18 週五


@pytest.fixture
def seeded(clean_db):
    db = clean_db
    for sid in ('2330', '2303', '0050'):
        db.seed_stock(sid)
    db.seed_prices('2330', D)                # 最新
    db.seed_prices('2303', D[:2])            # 落後 2 個交易日（9/23、9/24），不是 2 個日曆天以外的東西
    db.seed_prices('0050', D[:1])            # 只到 9/18：落後 3 個交易日（週末不算）
    return db


def test_check_counts_trading_days_not_calendar_days(seeded):
    out = data_freshness.check(['2330', '2303', '0050', '9999'])
    assert out['available'] and out['market_last'] == '2026-09-24'
    by = {i['stock_id']: i for i in out['items']}
    assert by['2330'] == {'stock_id': '2330', 'last_date': '2026-09-24', 'rows': 4, 'days_behind': 0, 'stale': False}
    assert by['2303']['days_behind'] == 2 and by['2303']['stale'] is True
    assert by['0050']['days_behind'] == 3                       # 9/18 → 9/24 差 6 個日曆天、3 個交易日
    assert by['9999'] == {'stock_id': '9999', 'last_date': None, 'rows': 0, 'days_behind': 4, 'stale': True}
    assert [i['stock_id'] for i in out['stale']] == ['0050', '2303', '9999']
    assert out['market_gap_days'] == (date.today() - date(2026, 9, 24)).days
    assert out['market_stale'] == (out['market_gap_days'] > data_freshness.STALE_MARKET_DAYS)


def test_check_default_ids_come_from_predictions_and_holdings(seeded):
    db = seeded
    assert data_freshness.check()['items'] == []                # 沒有預測、沒有持股 → 沒東西要顧
    db.execute("INSERT INTO saved_predictions (stock_id, model_key, predictions, market) VALUES ('2303','m','[]','tw'), ('TSM','m','[]','us')")
    db.execute("INSERT INTO users (username, password_hash, role) VALUES ('u','x','user')")
    db.execute("INSERT INTO user_holdings (stock_id, shares, avg_cost, user_id) VALUES ('0050', 1, 100, 1)")
    ids = [i['stock_id'] for i in data_freshness.check()['items']]
    assert ids == ['0050', '2303']                              # 美股的 TSM 不進台股補齊


def test_check_without_any_prices(clean_db):
    out = data_freshness.check(['2330'])
    assert out['available'] is False and '沒有任何行情' in out['reason']


def test_backfill_limits_batch_and_reports_remaining(seeded, monkeypatch):
    calls = []

    class FakeScraper:
        def __init__(self, stock_ids, start_date, end_date=None):
            calls.append((stock_ids[0], start_date))
        def fetch_prices(self):
            sid, start = calls[-1]
            from models.stock import StockDailyPrice
            return [StockDailyPrice(stock_id=sid, trade_date=d, close_price=1.0) for d in D if d >= start]
        def fetch_chips(self):
            return []
        def fetch_foreign_holding(self):
            raise RuntimeError('Requests reach the upper limit')      # 外資持股額度用完不影響行情
    import scrapers.finmind_scraper as fm
    monkeypatch.setattr(fm, 'FinMindScraper', FakeScraper)

    res = data_freshness.backfill(['2330', '2303', '0050', '9999'], max_stocks=2)
    assert res['ok'] and [f['stock_id'] for f in res['filled']] == ['0050', '2303']   # 只補前 2 檔（依代碼序）
    assert res['remaining'] == 1 and '尚有 1 檔待補' in res['reason']
    assert calls[0] == ('0050', date(2026, 9, 19)) and calls[1] == ('2303', date(2026, 9, 23))   # 從最後一天的隔天起補
    assert res['filled'][0]['prices'] == 3 and res['filled'][0]['holding'] == 0
    after = data_freshness.check(['0050', '2303'])
    assert all(not i['stale'] for i in after['items'])


def test_backfill_quota_exhausted_stops_that_stock(seeded, monkeypatch):
    class Dead:
        def __init__(self, *a, **k): pass
        def fetch_prices(self): raise RuntimeError('Requests reach the upper limit')
    import scrapers.finmind_scraper as fm
    monkeypatch.setattr(fm, 'FinMindScraper', Dead)
    res = data_freshness.backfill(['2303'], max_stocks=8)
    assert res['ok'] and res['filled'] == [] and res['failed'][0]['stock_id'] == '2303'
    assert 'upper limit' in res['failed'][0]['error'] and '1 檔失敗' in res['reason']


def test_backfill_nothing_stale(seeded):
    res = data_freshness.backfill(['2330'])
    assert res == {'ok': True, 'filled': [], 'remaining': 0, 'reason': '所有相關股票的行情都已是最新'}


def test_check_exogenous_three_tables(clean_db):
    db = clean_db
    today = date.today()
    db.execute("INSERT INTO us_daily_prices (ticker, trade_date, close_price) VALUES ('SPY', %s, 1)", (today - timedelta(days=1),))
    db.execute("INSERT INTO futures_daily (futures_id, trade_date, session, contract_date, close_price) VALUES ('TX', %s, 'day', '202610', 1)", (today - timedelta(days=9),))
    out = data_freshness.check_exogenous()
    assert out['available'] and [i['key'] for i in out['items']] == ['us', 'futures', 'index']
    by = {i['key']: i for i in out['items']}
    assert by['us']['stale'] is False and by['us']['days_behind'] == 1
    assert by['futures']['stale'] is True and by['futures']['days_behind'] == 9
    assert by['index']['stale'] is True and by['index']['last_date'] is None
    assert len(out['problems']) == 2 and '韓日指數沒有任何資料' in out['problems'][1]


def test_refill_exogenous_isolates_each_source(clean_db, monkeypatch):
    import sys, types
    us = types.ModuleType('backfill_us'); us.run = lambda start, retry_wait, pause: {'rows': 5, 'failed': []}
    fut = types.ModuleType('backfill_futures'); fut.DEFAULT_IDS = ['TX']
    def boom(*a, **k): raise RuntimeError('FinMind 402')
    fut.backfill = boom
    idx = types.ModuleType('backfill_index'); idx.run = lambda start: 7
    for name, m in (('backfill_us', us), ('backfill_futures', fut), ('backfill_index', idx)):
        monkeypatch.setitem(sys.modules, name, m)
    res = data_freshness.refill_exogenous(days=30)
    assert res['us'] == {'rows': 5, 'failed': []} and res['index'] == 7
    assert 'error' in res['futures'] and 'FinMind 402' in res['futures']['error']     # 一個來源掛掉不影響其他兩個
