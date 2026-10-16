"""交易模擬的資料來源（Iteration 75）：合成行情同代號同種子不受期間與同批影響、兩個模擬器用合成來源跑完不連庫、
真實來源仍走原本三個函式、API 的 source／seed 參數與 400。"""
from datetime import date

import pytest
from fastapi.testclient import TestClient

import api
import portfolio_paper as pp
import synthetic_market as sm
import trading_replay as rp
import trading_sim as ts
import trading_strategy as st
from helpers import fake_market as fm


@pytest.fixture
def no_db(monkeypatch):
    import db.connection as dbc
    for mod in (dbc, pp, rp):
        monkeypatch.setattr(mod, 'get_conn', fm._no_db)


def test_series_deterministic_across_windows_and_batches():
    a = sm.SyntheticSource(1)
    p1 = a.load_prices_any(['2330'], date(2020, 1, 1), date(2020, 12, 31))
    p2 = a.load_prices_any(['2330', '0050', 'ABCD'], date(2019, 6, 1), date(2023, 12, 31))
    assert len(p1) == 262 and all(p2[d]['2330'] == p1[d]['2330'] for d in p1)     # 2020 平日數；同代號不受期間與同批影響
    assert sm.SyntheticSource(2).load_prices_any(['2330'], date(2020, 1, 1), date(2020, 1, 31)) != a.load_prices_any(['2330'], date(2020, 1, 1), date(2020, 1, 31))
    assert a.load_bench(date(2020, 1, 1), date(2020, 1, 31)) == {d: r['0050']['close'] for d, r in a.load_prices_any(['0050'], date(2020, 1, 1), date(2020, 1, 31)).items()}
    assert a.market_days(date(2009, 1, 1), date(2010, 1, 8)) == [date(2010, 1, 1), date(2010, 1, 4), date(2010, 1, 5), date(2010, 1, 6), date(2010, 1, 7), date(2010, 1, 8)]
    for d, row in p1.items():
        p = row['2330']
        assert p['low'] <= min(p['open'], p['close']) <= max(p['open'], p['close']) <= p['high']
    assert a.describe() == {'kind': 'synthetic', 'seed': 1, 'label': '合成測試資料（種子 1）'}


def test_get_source_validation():
    assert isinstance(sm.get_source('real'), sm.DbSource) and isinstance(sm.get_source(None), sm.DbSource)
    assert sm.get_source('SYNTHETIC', 7).seed == 7
    with pytest.raises(ValueError):
        sm.get_source('fake')
    with pytest.raises(ValueError):
        sm.get_source('synthetic', -1)
    with pytest.raises(ValueError):
        sm.get_source('synthetic', sm.MAX_SEED + 1)


def test_simulators_run_on_synthetic_without_db(no_db):
    src = sm.SyntheticSource(3)
    r = ts.run_text('2022-01-03 買 2330 10股\n2022-01-03 買 0050 50000元\n2022-12-01 賣 2330 全部', date(2022, 1, 1), date(2022, 12, 31), 200_000, src)
    fm.check_invariants(r, 200_000)
    assert r['source']['kind'] == 'synthetic' and r['caveat'].startswith(sm.SYNTHETIC_CAVEAT) and len(r['trades']) == 3
    rules = [{'stock_id': '2454', 'when': {'type': 'monthly_day', 'd': 5}, 'then': {'side': 'buy', 'qty': 10_000, 'unit': '元'}},
             {'stock_id': '2454', 'when': {'type': 'loss_from_cost', 'x': 10}, 'then': {'side': 'sell', 'unit': '全部'}}]
    r2 = st.simulate_rules(rules, date(2021, 1, 1), date(2022, 12, 31), 500_000, src)
    fm.check_invariants(r2, 500_000)
    assert r2['source'] == {'kind': 'synthetic', 'seed': 3, 'label': '合成測試資料（種子 3）'} and r2['rules'][0]['fired'] == 24
    assert r2['caveat'].startswith(sm.SYNTHETIC_CAVEAT)
    # 同種子重跑一字不差
    assert st.simulate_rules(rules, date(2021, 1, 1), date(2022, 12, 31), 500_000, sm.SyntheticSource(3)) == r2
    # 期間早於 EPOCH → 不可用
    assert not ts.run_text('2005-01-03 買 2330 10股', date(2005, 1, 1), date(2005, 1, 31), 100_000, src)['available']


def test_db_source_calls_original_functions(monkeypatch):
    calls = []
    monkeypatch.setattr(pp, 'market_days', lambda s, e: calls.append('days') or [])
    monkeypatch.setattr(rp, 'load_bench', lambda s, e: calls.append('bench') or {})
    monkeypatch.setattr(ts, 'load_prices_any', lambda ids, s, e: calls.append('prices') or {})
    src = sm.DbSource()
    assert src.market_days(date(2024, 1, 1), date(2024, 1, 2)) == [] and src.load_prices_any(['2330'], date(2024, 1, 1), date(2024, 1, 2)) == {} and src.load_bench(date(2024, 1, 1), date(2024, 1, 2)) == {}
    assert calls == ['days', 'prices', 'bench'] and src.describe()['kind'] == 'real'
    assert not ts.run_text('2024-01-02 買 2330 1股', date(2024, 1, 1), date(2024, 1, 31))['available']      # 預設來源 = 真實（被換掉的 market_days 回空）


def test_api_source_and_seed(no_db):
    client = TestClient(api.app)
    body = {'text': '2022-01-03 買 2330 10股', 'start': '2022-01-01', 'end': '2022-03-31', 'capital': 100000, 'source': 'synthetic', 'seed': 9}
    r = client.post('/trading/sim', json=body)
    assert r.status_code == 200 and r.json()['source'] == {'kind': 'synthetic', 'seed': 9, 'label': '合成測試資料（種子 9）'} and r.json()['available']
    rules = [{'stock_id': '2330', 'when': {'type': 'price_above', 'x': 1}, 'then': {'side': 'buy', 'qty': 1, 'unit': '股'}}]
    r = client.post('/trading/sim/rules', json={'rules': rules, 'start': '2022-01-01', 'end': '2022-03-31', 'source': 'synthetic', 'seed': 9})
    assert r.status_code == 200 and r.json()['source']['seed'] == 9 and r.json()['rules'][0]['fired'] == 1
    assert client.post('/trading/sim', json={**body, 'source': 'nope'}).status_code == 400
    assert client.post('/trading/sim/rules', json={'rules': rules, 'start': '2022-01-01', 'end': '2022-03-31', 'source': 'synthetic', 'seed': -5}).status_code == 400
    # 預設 real → 會去碰 get_conn → 被 no_db 攔下（證明預設沒有悄悄變成合成）
    with pytest.raises(RuntimeError, match='不得連資料庫'):
        client.post('/trading/sim', json={k: v for k, v in body.items() if k not in ('source', 'seed')})
