"""自訂交易指令模擬（Iteration 60）：文字解析、當天開盤成交、金額換股、全部賣出、順延、略過、對 0050 的指標。"""
import importlib.util
from datetime import date
from pathlib import Path

import pytest

import trading_sim as ts

_spec = importlib.util.spec_from_file_location('_tpp', Path(__file__).parent / 'test_portfolio_paper.py')
_tpp = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(_tpp)
_seed_market, DAYS = _tpp._seed_market, _tpp.DAYS


def test_parse_instructions_formats_and_errors():
    text = """# 註解
2024-01-15 買 2330 10股
2024/01/16 buy 2454 2張
20240117 買 0050 50,000元
2024-06-03 賣 2330 全部
2024-06-03 sell 2454 500
2024-06-04 賣 0050 all
這行壞掉
2024-13-01 買 2330 1股
2024-06-05 賣 2330 100元
2024-06-05 買 2330 0股
"""
    p = ts.parse_instructions(text)
    assert [e['line'] for e in p['errors']] == [8, 9, 10, 11]
    its = p['instructions']
    assert [(i['date'].isoformat(), i['side'], i['stock_id'], i['shares'], i['amount'], i['all']) for i in its] == [
        ('2024-01-15', 'buy', '2330', 10, None, False), ('2024-01-16', 'buy', '2454', 2000, None, False), ('2024-01-17', 'buy', '0050', None, 50000.0, False),
        ('2024-06-03', 'sell', '2330', None, None, True), ('2024-06-03', 'sell', '2454', 500, None, False), ('2024-06-04', 'sell', '0050', None, None, True)]
    assert ts.parse_instructions('')['instructions'] == []


@pytest.mark.db
def test_simulate_buy_amount_sell_all_and_metrics(clean_db):
    db = clean_db
    # DAYS = 10/8、10/9、10/13、10/14、10/15；開盤 = 收盤 × 0.99
    _seed_market(db, {'1111': [100, 100, 100, 110, 120], '2222': [50, 50, 50, 50, 50], '2330': [1000] * 5})
    text = """2026-10-09 買 1111 10股
2026-10-10 買 2222 5000元      # 10/10 沒行情 → 10/13 開盤
2026-10-14 賣 1111 全部
2026-10-15 賣 9999 全部         # 沒行情的代號
2026-10-15 賣 2222 999股        # 超過持股 → 縮到持股
"""
    r = ts.run_text(text, date(2026, 10, 8), date(2026, 10, 15), capital=10_000)
    assert r['available'] and r['errors'] == [] and r['n_days'] == 5
    t = {(x['line'], x['side']): x for x in r['trades']}
    assert t[(1, 'buy')]['date'] == '2026-10-09' and t[(1, 'buy')]['price'] == 99.0 and t[(1, 'buy')]['shares'] == 10
    assert t[(2, 'buy')]['date'] == '2026-10-13' and t[(2, 'buy')]['shares'] == int(5000 // 49.5) and t[(2, 'buy')]['price'] == 49.5
    assert t[(3, 'sell')]['date'] == '2026-10-14' and t[(3, 'sell')]['shares'] == 10 and t[(3, 'sell')]['price'] == pytest.approx(110 * 0.99)
    assert t[(3, 'sell')]['pnl'] == pytest.approx((110 * 0.99 - (990 + round(990 * 0.000855, 2)) / 10) * 10 - t[(3, 'sell')]['fee'] - t[(3, 'sell')]['tax'], abs=0.05)
    assert t[(5, 'sell')]['shares'] == t[(2, 'buy')]['shares'] and t[(5, 'sell')]['note'] == '部分'
    assert [s['line'] for s in r['skipped']] == [4] and '沒有行情' in r['skipped'][0]['reason']
    assert r['final']['holdings'] == [] and r['final']['cash'] == pytest.approx(r['final']['value'])
    m = r['metrics']
    assert m['start'] == '2026-10-08' and m['end'] == '2026-10-15' and m['bench_return'] == pytest.approx(104 / 100 - 1, abs=1e-4)
    assert m['total_return'] == pytest.approx(r['final']['value'] / 10_000 - 1, abs=1e-4)
    assert len(r['series']) == 5 and r['series'][0]['nav'] == 1.0
    assert r['realized_pnl'] == pytest.approx(sum(x['pnl'] for x in r['trades'] if x['pnl'] is not None), abs=0.01)


@pytest.mark.db
def test_simulate_guards(clean_db):
    _seed_market(clean_db, {'1111': [100] * 5})
    assert ts.simulate([], date(2026, 10, 8), date(2026, 10, 15))['available'] is False
    assert '不在期間內' in ts.run_text('2026-11-01 買 1111 1股', date(2026, 10, 8), date(2026, 10, 15))['reason']
    assert ts.run_text('亂七八糟', date(2026, 10, 8), date(2026, 10, 15))['errors'][0]['line'] == 1
    assert '沒有全市場行情' in ts.run_text('2020-01-02 買 1111 1股', date(2020, 1, 1), date(2020, 1, 31))['reason']
    assert '最多' in ts.simulate([{'date': date(2020, 1, 2), 'side': 'buy', 'stock_id': '1111', 'shares': 1, 'amount': None, 'all': False, 'line': 1}], date(2010, 1, 1), date(2026, 10, 15))['reason']
    # 0050 不在全市場日線、只在 stock_daily_prices（seed 只有收盤 100、101…）：開盤用收盤，10/9 買在 101
    r0 = ts.run_text('2026-10-09 買 0050 3股', date(2026, 10, 8), date(2026, 10, 15), capital=1000)
    assert r0['skipped'] == [] and r0['trades'][0]['price'] == 101.0 and r0['trades'][0]['stock_id'] == '0050'
    # 10/8 當天買、期末沒賣：以期末收盤估值；鎖死那天順延
    r = ts.run_text('2026-10-08 買 1111 5股', date(2026, 10, 8), date(2026, 10, 15), capital=1000)
    assert r['trades'][0]['date'] == '2026-10-08' and r['final']['holdings'][0] == {'stock_id': '1111', 'shares': 5, 'last': 100.0, 'value': 500.0, 'avg_cost': pytest.approx(99.0 + round(495 * 0.000855, 2) / 5, abs=0.01)}
