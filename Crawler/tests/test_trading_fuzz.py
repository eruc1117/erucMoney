"""交易模擬的合成假資料與隨機不變量測試（Iteration 74）：不連資料庫（沒有 db marker；get_conn 被攔下）。
8 年 × 61 檔的假行情上，50 條隨機規則、200 筆隨機指令各跑多個種子，驗帳務不變量；另測一字鎖、0050 回退路徑、產生器可重現。"""
import random
from datetime import date

import pytest

import portfolio_paper as pp
import trading_replay as rp
import trading_sim as ts
import trading_strategy as st
from helpers import fake_market as fm

START, END = date(2018, 1, 1), date(2025, 12, 31)
IDS = [fm.BENCH] + [f'{1000 + i}' for i in range(60)]
STOCKS = IDS[1:]
CAPITAL = 1_000_000


@pytest.fixture(scope='module')
def market():
    return fm.make_market(IDS, START, END, seed=7, lock_prob=0.003)


@pytest.fixture
def days(market, monkeypatch):
    fm.patch(monkeypatch, market)
    return [d for d in sorted(market) if START <= d <= END]


def test_generator_reproducible_and_ohlc_sane():
    a = fm.make_market(['1111', '0050'], date(2020, 1, 1), date(2020, 3, 31), seed=3, warmup_days=0)
    b = fm.make_market(['1111', '0050'], date(2020, 1, 1), date(2020, 3, 31), seed=3, warmup_days=0)
    assert a == b and len(a) == 65                                   # 2020-01-01～03-31 的平日數
    prev = None
    for d in sorted(a):
        p = a[d]['1111']
        assert p['low'] <= min(p['open'], p['close']) <= max(p['open'], p['close']) <= p['high']
        assert p['prev_close'] == prev
        if prev:
            assert abs(p['close'] / prev - 1) <= 0.1 + 1e-6            # 漲跌停夾住
        prev = p['close']
    assert fm.make_market(['1111'], date(2020, 1, 1), date(2020, 3, 31), seed=4, warmup_days=0) != a


def test_patch_blocks_every_db_path(market, monkeypatch):
    fm.patch(monkeypatch, market)
    import db.connection as dbc
    for f in (dbc.get_conn, pp.get_conn, rp.get_conn):
        with pytest.raises(RuntimeError, match='不得連資料庫'):
            f()
    # 路由照正式庫：0050 只在 stock_daily_prices、其他只在 market_daily_prices
    assert rp.load_prices(['0050', '1000'], START, date(2018, 1, 10)) and all('0050' not in row for row in rp.load_prices(['0050', '1000'], START, date(2018, 1, 10)).values())
    assert all(set(row) == {'0050'} for row in rp.load_prices(['0050', '1000'], START, date(2018, 1, 10), table='stock_daily_prices').values())
    assert len(pp.market_days(START, END)) == len([d for d in market if START <= d <= END])


@pytest.mark.parametrize('seed', range(5))
def test_fuzz_rules_invariants(market, days, seed):
    rng = random.Random(seed)
    rules = fm.random_rules(STOCKS, rng, st.MAX_RULES, market, CAPITAL)
    assert st.validate_rules(rules) == []
    r = st.simulate_rules(rules, START, END, CAPITAL)
    fm.check_invariants(r, CAPITAL)
    assert r['n_rules'] == st.MAX_RULES and r['n_days'] == len(days) and r['missing'] == []
    assert sum(x['fired'] for x in r['rules']) >= len([t for t in r['triggers'] if t['result'] == 'filled'])
    for i, x in enumerate(r['rules']):
        if x['max_times'] is not None:
            assert x['fired'] <= x['max_times'], x
    assert r['metrics']['years'] == pytest.approx(len(days) / 252, abs=0.01)


@pytest.mark.parametrize('seed', range(5))
def test_fuzz_instructions_invariants(market, days, seed):
    rng = random.Random(seed)
    text = fm.random_instructions(STOCKS, days, rng, ts.MAX_INSTRUCTIONS, market, CAPITAL)
    r = ts.run_text(text, START, END, CAPITAL)
    assert r['errors'] == [] and r['n_instructions'] == ts.MAX_INSTRUCTIONS
    fm.check_invariants(r, CAPITAL)
    assert len(r['trades']) + len(r['skipped']) == ts.MAX_INSTRUCTIONS            # 每筆指令最後不是成交就是略過（順延最多 5 次）
    assert len(r['trades']) >= 10, '資金按比例縮放後應有可觀成交'
    assert all(t['date'] >= t['asked'] for t in r['trades'])                       # 只能順延、不能提前
    for t in r['trades']:
        assert date.fromisoformat(t['date']).weekday() < 5


def test_rules_on_bench_use_fallback_table(days):
    rules = [{'stock_id': '0050', 'when': {'type': 'monthly_day', 'd': 1}, 'then': {'side': 'buy', 'qty': 10_000, 'unit': '元'}}]
    r = st.simulate_rules(rules, START, END, CAPITAL)
    fm.check_invariants(r, CAPITAL)
    assert r['missing'] == [] and r['rules'][0]['fired'] == 96 and len(r['trades']) == 96        # 8 年 × 12 個月
    assert r['final']['holdings'][0]['stock_id'] == '0050'


def test_locked_stock_never_fills(monkeypatch):
    m = fm.make_market(['0050', '1111', '2222'], date(2021, 1, 1), date(2021, 12, 31), seed=5, lock_ids=('1111',))
    fm.patch(monkeypatch, m)
    days = [d for d in sorted(m) if d.year == 2021]
    text = '\n'.join(f'{d} 買 1111 100股' for d in days[::20]) + f'\n{days[0]} 買 2222 100股'
    r = ts.run_text(text, date(2021, 1, 1), date(2021, 12, 31), CAPITAL)
    fm.check_invariants(r, CAPITAL)
    assert {t['stock_id'] for t in r['trades']} == {'2222'}
    assert {s['stock_id'] for s in r['skipped']} == {'1111'} and all(s['reason'] in ('一字鎖死', '期間內沒輪到執行') for s in r['skipped'])
    rules = [{'stock_id': '1111', 'when': {'type': 'monthly_day', 'd': 1}, 'then': {'side': 'buy', 'qty': 1, 'unit': '張'}}]
    r2 = st.simulate_rules(rules, date(2021, 1, 1), date(2021, 12, 31), CAPITAL)
    fm.check_invariants(r2, CAPITAL)
    assert r2['trades'] == [] and r2['rules'][0]['fired'] == 12 and r2['final']['cash'] == CAPITAL
    assert sum(1 for t in r2['triggers'] if t['result'] == 'unfilled' and t['note'] == '一字鎖死') == 12


def test_period_limits_still_enforced(days):
    r = st.simulate_rules([{'stock_id': '1000', 'when': {'type': 'price_above', 'x': 1}, 'then': {'side': 'buy', 'qty': 1, 'unit': '股'}}],
                          START, date(2026, 6, 30), CAPITAL)
    assert not r['available'] and '8 年' in r['reason']
    r = ts.run_text('2020-01-06 買 1000 1股', START, date(2026, 6, 30), CAPITAL)
    assert not r['available'] and '8 年' in r['reason']
