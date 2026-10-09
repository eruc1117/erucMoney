"""程式交易引擎（Iteration 58）：開關與規則、清單 → 委託單（限價）→ 紙上成交、未成交重掛與取消、停損、相對回撤守門、預測。測試庫。"""
from datetime import date

import pytest

import portfolio_paper as pp
import trading_engine as te
import importlib.util
from pathlib import Path

# 行情與清單的 seed 和紙上交易測試共用（直接載該檔，不依賴 tests 是不是套件）
_spec = importlib.util.spec_from_file_location('_tpp', Path(__file__).parent / 'test_portfolio_paper.py')
_tpp = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(_tpp)
_seed_list, _seed_market, DAYS = _tpp._seed_list, _tpp._seed_market, _tpp.DAYS

pytestmark = pytest.mark.db


def _setup(db, closes, lock=None, capital=1_000_000):
    _seed_market(db, closes, lock)
    pp.start(capital=capital, run_id=None, started_on=date(2026, 10, 9))
    te.configure(enabled=True, mode='paper')
    return te.state()


def test_configure_validates_and_pairs_mode_with_broker(clean_db):
    assert te.state() is None
    st = te.configure(enabled=True, mode='live')
    assert st['broker'] == 'kgi' and st['enabled'] and st['rules']['stop_loss_pct'] == 0.15
    st = te.configure(mode='paper', rules={'stop_loss_pct': 0.2})
    assert st['broker'] == 'paper' and st['rules']['stop_loss_pct'] == 0.2 and st['rules']['limit_slip'] == 0.005
    with pytest.raises(ValueError):
        te.configure(rules={'nope': 1})
    with pytest.raises(ValueError):
        te.configure(mode='x')
    # live + 凱基沒設定：run_daily 停下來記錯誤，不送單
    _seed_market(clean_db, {'1111': [100] * 5})
    pp.start(capital=1000, run_id=None, started_on=date(2026, 10, 9))
    te.configure(mode='live')
    r = te.run_daily(date(2026, 10, 14))
    assert 'skipped' in r and '凱基' in r['skipped']
    assert te.state()['last_error'] and te.list_events(5)[0]['kind'] == 'error'


def test_list_to_orders_to_fills(clean_db, monkeypatch):
    db = clean_db
    _setup(db, {'1111': [100, 100, 100, 100, 110], '2222': [50, 50, 50, 50, 45], '2330': [1000] * 5})
    monkeypatch.setattr(pp, 'make_list', lambda rd, run_id: {'n': 0, 'new': []})
    _seed_list(db, date(2026, 10, 13), {'2330': 0.5, '1111': 0.25, '2222': 0.25})
    # 10/13 收盤：清單出來 → 三張買單，限價 = 收盤 × 1.005
    r = te.run_daily(date(2026, 10, 13))
    assert r['orders'] == [{'rebalance_date': date(2026, 10, 13), 'orders': 3, 'guard': False}]
    pend = te.pending_orders()
    assert {o['stock_id']: o['limit_price'] for o in pend} == {'2330': 1005.0, '1111': 100.5, '2222': 50.25}
    assert all(o['side'] == 'buy' and o['reason'] == 'rebalance' for o in pend)
    # 股數：以 10/13 收盤估、留手續費
    import math
    assert {o['stock_id']: o['shares'] for o in pend} == {s: math.floor(w * 1_000_000 / (1 + pp.FEE_RATE) / c) for s, w, c in (('2330', 0.5, 1000), ('1111', 0.25, 100), ('2222', 0.25, 50))}
    # 10/14 開盤 = 收盤 × 0.99 ≤ 限價 → 全部成交，寫進模擬帳戶
    r = te.run_daily(date(2026, 10, 14))
    assert r['sent'] == [{'date': '2026-10-14', 'sent': 3, 'filled': 3, 'unfilled': 0, 'cancelled': 0, 'rejected': 0}]
    assert te.pending_orders() == []
    held = pp.holdings()
    assert set(held) == {'2330', '1111', '2222'} and held['2330'] == pend[0]['shares'] if pend[0]['stock_id'] == '2330' else True
    filled = te.list_orders(status='filled')
    assert len(filled) == 3 and all(o['filled_price'] == pytest.approx(c * 0.99) for o, c in ((next(x for x in filled if x['stock_id'] == '1111'), 100),))
    assert db.query("SELECT count(*) FROM portfolio_paper_trades WHERE filled")[0][0] == 3
    assert r['marked'] == 1                                             # 10/9、10/13 在前一次跑過，這次只補 10/14
    kinds = [e['kind'] for e in te.list_events(20)]
    assert 'fill' in kinds and 'orders' in kinds
    # 再跑一天：沒有重複送單、沒有重複清單
    r2 = te.run_daily(date(2026, 10, 15))
    assert r2['sent'] == [] and r2['orders'] == []
    st = te.status()
    assert st['engine']['enabled'] and st['broker_ready'] and st['orders'] == {'filled': 3}
    assert len(st['watch']) == 3 and all(w['stop'] == pytest.approx(w['cost'] * 0.85, abs=0.01) for w in st['watch'])


def test_unfilled_requotes_then_cancels(clean_db, monkeypatch):
    db = clean_db
    # 1111 每天漲 3%：開盤（收盤 × 0.99）永遠高於前一日收盤 × 1.005 → 買不到；重掛兩次後第三次取消
    closes = [100, 103, 106.09, 109.27, 112.55]
    _setup(db, {'1111': closes, '2330': [1000] * 5})
    te.configure(rules={'max_attempts': 3})
    monkeypatch.setattr(pp, 'make_list', lambda rd, run_id: {'n': 0, 'new': []})
    _seed_list(db, date(2026, 10, 8), {'1111': 1.0})
    # 把開戶日移到 10/8 讓 10/8 的清單算數
    db.execute("UPDATE portfolio_paper_state SET started_on = '2026-10-08'")
    te.run_daily(date(2026, 10, 8))
    o = te.pending_orders()[0]
    assert o['limit_price'] == 100.5
    te.run_daily(date(2026, 10, 9))        # 開盤 103 × 0.99 = 101.97 > 100.5 → 未成交，重掛 limit = 103 × 1.005
    o = te.pending_orders()[0]
    assert o['attempts'] == 1 and o['order_date'] == date(2026, 10, 9) and o['limit_price'] == pytest.approx(103.52, abs=0.01)
    te.run_daily(date(2026, 10, 13))       # 106.09 × 0.99 = 105.03 > 103.52 → 第二次
    assert te.pending_orders()[0]['attempts'] == 2
    te.run_daily(date(2026, 10, 14))       # 第三次 → 取消
    assert te.pending_orders() == []
    c = te.list_orders(status='cancelled')
    assert len(c) == 1 and c[0]['attempts'] == 3 and '取消' in c[0]['note']
    assert pp.holdings() == {}


def test_stop_loss_and_guard(clean_db, monkeypatch):
    db = clean_db
    # 1111 10/13 買進（開盤 99）後 10/14 收 80（−19%）→ 10/14 收盤觸發停損 → 10/15 開盤賣
    _setup(db, {'1111': [100, 100, 100, 80, 70], '2222': [50] * 5, '2330': [1000] * 5})
    monkeypatch.setattr(pp, 'make_list', lambda rd, run_id: {'n': 0, 'new': []})
    db.execute("UPDATE portfolio_paper_state SET started_on = '2026-10-08'")
    _seed_list(db, date(2026, 10, 9), {'1111': 0.5, '2222': 0.5})
    te.run_daily(date(2026, 10, 9)); te.run_daily(date(2026, 10, 13))
    assert set(pp.holdings()) == {'1111', '2222'}
    r = te.run_daily(date(2026, 10, 14))
    assert [h['stock_id'] for h in r['stop_loss']] == ['1111']
    so = te.pending_orders()[0]
    assert so['reason'] == 'stop_loss' and so['side'] == 'sell' and so['limit_price'] == pytest.approx(80 * 0.995, abs=0.01)
    r = te.run_daily(date(2026, 10, 15))   # 10/15 開盤 70 × 0.99 = 69.3 < 限價 79.6 → 未成交，重掛（限價單賣不掉就是賣不掉）
    assert r['sent'][0]['unfilled'] == 1 and te.pending_orders()[0]['attempts'] == 1
    assert '1111' in pp.holdings()
    # 停損單還在就不重複開
    r = te.run_daily(date(2026, 10, 15))
    assert r['stop_loss'] == [] and len(te.pending_orders()) == 1
    # 相對回撤守門：帳戶已經大輸 0050 → 新清單只產生賣單
    te.configure(rules={'rel_dd_guard': 0.01})
    _seed_list(db, date(2026, 10, 15), {'2330': 1.0})
    te.run_daily(date(2026, 10, 15))
    g = te.list_events(30)
    assert any(e['kind'] == 'guard' for e in g)
    sides = {(o['stock_id'], o['side']) for o in te.pending_orders()}
    assert ('2222', 'sell') in sides and ('2330', 'buy') not in sides


def test_forecast_math(clean_db):
    db = clean_db
    db.execute("""INSERT INTO portfolio_runs (id, experiment_n, name, signal, segment, period_start, period_end, metrics)
                  VALUES (44, 44, 'cand', 'win3+mom', 'dev', '2018-01-01', '2024-09-30', '{"ann_active": 0.0705, "tracking_error": 0.125, "info_ratio": 0.564, "dsr": 0.129}')""")
    f = te.forecast()
    assert f['available'] and f['run_id'] == 44
    h12 = next(h for h in f['horizons'] if h['months'] == 12)
    assert h12['expected_active'] == pytest.approx(0.0705, abs=1e-4) and h12['sd'] == pytest.approx(0.125, abs=1e-4)
    assert h12['p_beat'] == pytest.approx(0.714, abs=0.005)            # Φ(0.0705/0.125)
    h1 = f['horizons'][0]
    assert h1['months'] == 1 and h1['sd'] == pytest.approx(0.125 / 12 ** 0.5, abs=1e-4) and h1['p_beat'] < h12['p_beat']
    assert f['band'] == [] and f['actual'] is None                     # 沒開戶就沒有淨值帶
    assert '不是保證' in f['caveat']
    db.execute("DELETE FROM portfolio_runs WHERE id = 44")
    assert te.forecast()['available'] is False
