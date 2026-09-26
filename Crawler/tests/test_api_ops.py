"""FastAPI 非模型端點的回應形狀：爬蟲觸發／冷卻／狀態、新聞爬蟲與關鍵字過濾、資料新鮮度與回填、週預測狀態。
背景執行緒換成同步；會上網或算模型的函式全部 monkeypatch。"""
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

import api
import data_freshness
import weekly_forecast
from helpers.fakes import SyncThread


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(api.threading, 'Thread', SyncThread)
    api._running_tasks.clear()
    api._crawl_done_at.clear()
    monkeypatch.setattr(api, '_news_crawl_running', False)
    monkeypatch.setattr(api, '_news_crawl_count', 0)
    monkeypatch.setattr(api, '_news_crawl_mode', '')
    # TestClient 不用 with：不觸發 startup（那會去檢查資料庫）
    return TestClient(api.app)


@pytest.fixture
def fake_run_crawler(monkeypatch):
    """只保留 _run_crawler 的收尾語意：釋放執行中旗標、近期模式更新冷卻。"""
    calls = []

    def fake(stock_id, start_date_str=None, end_date_str=None):
        calls.append((stock_id, start_date_str, end_date_str))
        with api._tasks_lock:
            api._running_tasks.discard(stock_id)
        if not start_date_str:
            with api._cooldown_lock:
                api._crawl_done_at[stock_id] = datetime.now()
    monkeypatch.setattr(api, '_run_crawler', fake)
    return calls


def test_crawler_run_then_cooldown_then_historical(client, fake_run_crawler):
    r = client.post('/crawler/run', json={'stock_id': ' 2330 '})
    assert r.status_code == 200 and r.json() == {'status': 'started', 'task_id': '2330', 'mode': 'recent'}
    assert fake_run_crawler == [('2330', None, None)]
    assert client.get('/crawler/status/2330').json() == {'stock_id': '2330', 'status': 'idle'}

    r = client.post('/crawler/run', json={'stock_id': '2330'})          # 30 分鐘內再按 → rate_limited
    body = r.json()
    assert body['status'] == 'rate_limited' and body['task_id'] == '2330'
    assert 0 < body['retry_after'] <= api.CRAWL_COOLDOWN_SECONDS

    r = client.post('/crawler/run', json={'stock_id': '2330', 'start_date': '2026-01-01', 'end_date': '2026-03-01'})
    assert r.json() == {'status': 'started', 'task_id': '2330', 'mode': 'historical'}    # 歷史補充不受冷卻
    assert fake_run_crawler[-1] == ('2330', '2026-01-01', '2026-03-01')


def test_crawler_run_rejects_concurrent_same_stock(client, fake_run_crawler):
    api._running_tasks.add('2303')
    assert client.post('/crawler/run', json={'stock_id': '2303'}).json() == {'status': 'already_running', 'task_id': '2303'}
    assert client.get('/crawler/status/2303').json()['status'] == 'running'
    assert fake_run_crawler == []


def test_crawler_run_validation(client):
    assert client.post('/crawler/run', json={}).status_code == 422


def test_run_crawler_clamps_history_range(monkeypatch):
    """歷史補充超過 365 天 → 起始日自動往後推；結束日不超過今天。"""
    seen = {}

    class FakeScraper:
        def __init__(self, stock_ids, start_date, end_date):
            seen.update(start=start_date, end=end_date)
        def fetch_stock_info(self): return []
        def fetch_prices(self): return []
        def fetch_chips(self): return []
    import scrapers.finmind_scraper as fm
    from db import repository
    monkeypatch.setattr(fm, 'FinMindScraper', FakeScraper)
    monkeypatch.setattr(repository, 'upsert_stock_info', lambda *a, **k: None)
    monkeypatch.setattr(repository, 'upsert_daily_prices', lambda rows: 0)
    monkeypatch.setattr(repository, 'upsert_chip_analysis', lambda rows: 0)
    api._running_tasks.add('2330')
    api._run_crawler('2330', '2020-01-01', '2099-12-31')
    from datetime import date
    assert seen['end'] == date.today()
    assert (seen['end'] - seen['start']).days == api.HIST_MAX_DAYS
    assert '2330' not in api._running_tasks and '2330' not in api._crawl_done_at    # 歷史模式不更新冷卻


@pytest.fixture
def fake_news(monkeypatch):
    """NewsScraper 與寫入層換成假的，記下寫進 user_news 的文章。"""
    articles = [
        {'title': '台積電法說會釋利多', 'content': '外資調高目標價', 'is_financial': True},
        {'title': '聯電營收月增', 'content': '', 'is_financial': True},
        {'title': '非財金：天氣', 'content': '明天下雨', 'is_financial': False},
    ]
    written = {'raw': None, 'news': None, 'mode': None}

    class FakeNewsScraper:
        def scrape_all(self):
            written['mode'] = 'realtime'; return list(articles)
        def scrape_with_date_range(self, s, e):
            written['mode'] = ('historical', s, e); return list(articles)
    import scrapers.news_scraper as ns
    from db import repository
    monkeypatch.setattr(ns, 'NewsScraper', FakeNewsScraper)
    monkeypatch.setattr(repository, 'insert_raw_news_batch', lambda arts: written.__setitem__('raw', arts) or (len(arts), 0))
    monkeypatch.setattr(repository, 'insert_news_articles', lambda arts: written.__setitem__('news', arts) or len(arts))
    return written


def test_news_crawl_realtime_filters_financial_only(client, fake_news):
    r = client.post('/crawler/news', json={})
    assert r.json() == {'status': 'started', 'mode': 'realtime'}
    assert fake_news['mode'] == 'realtime'
    assert len(fake_news['raw']) == 3 and [a['title'] for a in fake_news['news']] == ['台積電法說會釋利多', '聯電營收月增']
    assert client.get('/crawler/news/status').json() == {'status': 'idle', 'mode': 'realtime', 'last_count': 2}


def test_news_crawl_keyword_filter_and_single_day_history(client, fake_news):
    r = client.post('/crawler/news', json={'start_date': '2026-09-01', 'keywords': [' 台積電 ', '', 'x']})
    assert r.json() == {'status': 'started', 'mode': 'historical'}
    assert fake_news['mode'] == ('historical', '2026-09-01', '2026-09-01')      # 只填 start → 單日
    assert [a['title'] for a in fake_news['raw']] == ['台積電法說會釋利多']          # 關鍵字先過濾再寫入
    assert client.get('/crawler/news/status').json()['last_count'] == 1


def test_news_crawl_already_running(client, monkeypatch):
    monkeypatch.setattr(api, '_news_crawl_running', True)
    monkeypatch.setattr(api, '_news_crawl_mode', 'realtime')
    assert client.post('/crawler/news', json={}).json() == {'status': 'already_running', 'mode': 'realtime'}


def test_data_freshness_endpoints(client, monkeypatch):
    seen = {}
    monkeypatch.setattr(data_freshness, 'check', lambda ids=None: seen.__setitem__('ids', ids) or {'available': True, 'items': [], 'stale': []})
    monkeypatch.setattr(data_freshness, 'last_result', lambda: {'running': False, 'last': None})
    monkeypatch.setattr(data_freshness, 'backfill', lambda ids=None, max_stocks=8: {'ok': True, 'ids': ids, 'max': max_stocks})
    monkeypatch.setattr(data_freshness, 'check_exogenous', lambda: {'available': True, 'items': [], 'problems': []})

    r = client.get('/data/freshness?stock_ids=2330, 2303').json()
    assert seen['ids'] == ['2330', '2303'] and r['startup'] == {'running': False, 'last': None}
    client.get('/data/freshness'); assert seen['ids'] is None
    assert client.post('/data/backfill?stock_ids=2330&max_stocks=3').json() == {'ok': True, 'ids': ['2330'], 'max': 3}
    assert client.post('/data/backfill').json()['max'] == 8
    assert client.get('/data/freshness/exogenous').json()['available'] is True


def test_weekly_forecast_status_and_run(client, monkeypatch):
    state = {'running': False, 'started_at': None, 'last_error': None, 'next_run': '2026-09-27T08:00'}
    monkeypatch.setattr(weekly_forecast, 'status', lambda: dict(state))
    runs = []
    monkeypatch.setattr(weekly_forecast, 'run', lambda trigger='schedule': runs.append(trigger))
    assert client.get('/forecast/weekly/status').json() == state
    assert client.post('/forecast/weekly/run').json() == {'status': 'started'} and runs == ['manual']
    state['running'] = True
    assert client.post('/forecast/weekly/run').json() == {'status': 'already_running'}


@pytest.mark.db
def test_stock_endpoints_against_test_db(client, clean_db):
    """/stocks/{id}、/stocks?max_price、/stocks/{id}/prices 用測試庫跑一遍。"""
    from datetime import date
    db = clean_db
    db.seed_stock('2330', '台積電'); db.seed_stock('2303', '聯電')
    today = date.today()
    db.seed_prices('2330', [today - timedelta(days=2), today - timedelta(days=1)], close=2450, step=10)
    db.seed_prices('2303', [today - timedelta(days=1)], close=160)
    r = client.get('/stocks/2330').json()
    assert r['stock_id'] == '2330' and float(r['close_price']) == 2460 and r['total_net_buy'] is None
    assert client.get('/stocks/9999').status_code == 404
    cheap = client.get('/stocks?max_price=200').json()
    assert [s['stock_id'] for s in cheap] == ['2303']
    assert client.get('/stocks?max_price=0').status_code == 422
    prices = client.get('/stocks/2330/prices?days=5').json()
    assert [p['trade_date'] for p in prices] == [(today - timedelta(days=2)).isoformat(), (today - timedelta(days=1)).isoformat()]
