"""程式交易回放（Iteration 59）：引擎規則 vs 照單全收套在測試行情上；停損與限價的差距、範圍夾回候選期間、快取。測試庫。"""
import importlib.util
from datetime import date
from pathlib import Path

import pytest

import trading_replay as rp

_spec = importlib.util.spec_from_file_location('_tpp', Path(__file__).parent / 'test_portfolio_paper.py')
_tpp = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(_tpp)
_seed_market, DAYS = _tpp._seed_market, _tpp.DAYS

pytestmark = pytest.mark.db


def _seed_run(db, run_id=901, start=date(2026, 10, 1), end=date(2026, 10, 31)):
    db.execute("""INSERT INTO portfolio_runs (id, experiment_n, name, signal, segment, period_start, period_end, metrics)
                  VALUES (%s, %s, 'replay-test', 'win3+mom', 'dev', %s, %s, '{}')""", (run_id, run_id, start, end))


def _seed_positions(db, run_id, rd, weights):
    for i, (sid, w) in enumerate(weights.items(), 1):
        db.execute("INSERT INTO portfolio_positions (run_id, rebalance_date, exec_date, stock_id, rank, target_weight, filled) VALUES (%s, %s, NULL, %s, %s, %s, TRUE)",
                   (run_id, rd, sid, i, w))


def test_replay_engine_vs_plain_with_stop_loss(clean_db):
    db = clean_db
    rp._CACHE.clear()
    # 1111 在 10/13 買進後 10/14 收 80（−20%）→ 引擎停損單限價 79.6，10/15 開盤 82 × 0.99 = 81.18 ≥ 限價 → 賣掉；照單全收抱著
    _seed_market(db, {'1111': [100, 100, 100, 80, 82], '2222': [50, 50, 50, 50, 55], '2330': [1000] * 5})
    _seed_run(db)
    _seed_positions(db, 901, date(2026, 10, 9), {'1111': 0.5, '2222': 0.5})
    r = rp.replay(date(2026, 10, 9), date(2026, 10, 15), capital=100_000, run_id=901)
    assert r['available'] and r['n_lists'] == 1 and r['n_days'] == 4 and r['cached'] is False
    e, p = r['variants']['engine'], r['variants']['plain']
    # 兩邊都在 10/13 開盤成交（開盤 99 ≤ 限價 100.5）
    assert e['stats']['filled'] == 3 and p['stats']['filled'] == 2        # 引擎多一筆停損成交
    assert e['stats']['stop_loss'] == 1 and p['stats']['stop_loss'] == 0
    assert len(e['stop_losses']) == 1 and e['stop_losses'][0]['stock_id'] == '1111' and e['stop_losses'][0]['sold'] == pytest.approx(82 * 0.99)
    assert e['stop_losses'][0]['pnl'] < 0 and e['stop_loss_pnl'] == e['stop_losses'][0]['pnl']
    # 引擎停損後現金多、1111 沒了；照單全收還抱著
    assert e['last_holdings'] == 1 and p['last_holdings'] == 2
    # 期末淨值：引擎在 81.18 賣掉又付稅；照單全收用 82 收盤估——引擎略輸
    em, pm = e['metrics'], p['metrics']
    assert em['end'] == '2026-10-15' and pm['start'] == '2026-10-09'
    assert em['total_return'] < pm['total_return']
    assert set(r['engine_minus_plain']) >= {'total_return', 'active_return'}
    assert len(e['series']) == 4 and e['series'][0]['nav'] == 1.0 and e['series'][0]['bench'] == 1.0
    assert em['bench_return'] == pytest.approx(104 / 101 - 1, abs=1e-4)   # 0050 從 10/9 的 101 到 10/15 的 104
    # 第二次同參數：快取
    assert rp.replay(date(2026, 10, 9), date(2026, 10, 15), capital=100_000, run_id=901)['cached'] is True


def test_replay_limit_miss_requotes_and_range_clamp(clean_db):
    db = clean_db
    rp._CACHE.clear()
    # 1111 每天 +3%：引擎限價買不到、重掛三次取消；照單全收第一天就買到
    _seed_market(db, {'1111': [100, 103, 106.09, 109.27, 112.55], '2330': [1000] * 5})
    _seed_run(db, start=date(2026, 10, 1), end=date(2026, 10, 15))
    _seed_positions(db, 901, date(2026, 10, 8), {'1111': 1.0})
    r = rp.replay(date(2026, 9, 1), date(2026, 12, 31), capital=10_000, run_id=901, rules={'max_attempts': 3})
    assert r['start'] == '2026-10-08' and r['end'] == '2026-10-15'
    assert any('夾回' in n for n in r['notes']) and any('保留期' in n for n in r['notes'])
    e, p = r['variants']['engine'], r['variants']['plain']
    assert e['stats']['filled'] == 0 and e['stats']['unfilled'] == 2 and e['stats']['cancelled'] == 1
    assert p['stats']['filled'] == 1 and p['last_holdings'] == 1
    assert e['metrics']['total_return'] == 0.0 and p['metrics']['total_return'] > 0
    # 沒清單的區間
    assert rp.replay(date(2026, 10, 9), date(2026, 10, 15), run_id=901)['available'] is False
    assert rp.replay(date(2026, 10, 1), date(2026, 10, 15), run_id=999)['available'] is False
