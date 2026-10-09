"""條件規則模擬（Iteration 61）：驗證、價格／均線／成本／報酬／日期條件、收盤判斷隔天成交、只買一次、停損停利、觸發紀錄。"""
import importlib.util
from datetime import date
from pathlib import Path

import pytest

import trading_strategy as st

_spec = importlib.util.spec_from_file_location('_tpp', Path(__file__).parent / 'test_portfolio_paper.py')
_tpp = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(_tpp)
_seed_market, DAYS = _tpp._seed_market, _tpp.DAYS   # 10/8、10/9、10/13、10/14、10/15；開盤 = 收盤 × 0.99


def test_validate_and_rule_text():
    ok = [{'stock_id': '2330', 'when': {'type': 'cross_below_ma', 'n': 20}, 'then': {'side': 'sell', 'unit': '全部'}}]
    assert st.validate_rules(ok) == []
    assert st.rule_text(ok[0]) == '2330：收盤由上往下跌破 20 日均線 → 賣 全部'
    assert st.rule_text({'stock_id': '0050', 'when': {'type': 'monthly_day', 'd': 5}, 'then': {'side': 'buy', 'qty': 10000, 'unit': '元'}}) == '0050：每月 5 日起第一個交易日 → 買 10000元'
    bad = st.validate_rules([
        {'stock_id': '23', 'when': {'type': 'nope'}, 'then': {'side': 'buy', 'qty': 1}},
        {'stock_id': '2330', 'when': {'type': 'rsi_below', 'n': 14}, 'then': {'side': 'buy', 'qty': 0, 'unit': '股'}},
        {'stock_id': '2330', 'when': {'type': 'on_date', 'date': 'x'}, 'then': {'side': 'buy', 'qty': 1, 'unit': '全部'}},
        {'stock_id': '2330', 'when': {'type': 'price_below', 'x': 10}, 'then': {'side': 'sell', 'qty': 100, 'unit': '元'}},
    ])
    assert len(bad) >= 5 and st.validate_rules([]) == ['rules 要是非空陣列']   # 條件壞掉的那條不再往下驗動作


@pytest.mark.db
def test_price_and_cost_rules_fire_next_open(clean_db):
    db = clean_db
    # 1111：100、100、100、80、82 → 10/14 收盤 80 跌破 90 → 10/15 開盤 81.18 賣；成本條件
    _seed_market(db, {'1111': [100, 100, 100, 80, 82], '2222': [50, 55, 60, 66, 70]})
    rules = [
        {'stock_id': '1111', 'when': {'type': 'on_date', 'date': '2026-10-09'}, 'then': {'side': 'buy', 'qty': 10, 'unit': '股'}},          # 10/9 開盤 99 買
        {'stock_id': '1111', 'when': {'type': 'loss_from_cost', 'x': 15}, 'then': {'side': 'sell', 'unit': '全部'}},                        # 10/14 收 80 < 99×0.85 → 10/15 賣
        {'stock_id': '2222', 'when': {'type': 'price_above', 'x': 52}, 'then': {'side': 'buy', 'qty': 1000, 'unit': '元'}},                 # 10/9 收 55 > 52 → 10/13 開盤 59.4 買，只買一次
        {'stock_id': '2222', 'when': {'type': 'gain_from_cost', 'x': 10}, 'then': {'side': 'sell', 'unit': '全部'}},                       # 成本 ≈ 59.4 → 10/14 收 66 ≥ +10% → 10/15 開 69.3 賣
    ]
    r = st.simulate_rules(rules, date(2026, 10, 8), date(2026, 10, 15), capital=10_000)
    assert r['available'] and r['n_rules'] == 4 and r['missing'] == []
    t = {(x['rule'], x['side']): x for x in r['trades']}
    assert t[(0, 'buy')]['date'] == '2026-10-09' and t[(0, 'buy')]['price'] == 99.0
    assert t[(1, 'sell')]['date'] == '2026-10-15' and t[(1, 'sell')]['signal_date'] == '2026-10-14' and t[(1, 'sell')]['shares'] == 10 and t[(1, 'sell')]['price'] == pytest.approx(82 * 0.99)
    assert t[(2, 'buy')]['date'] == '2026-10-13' and t[(2, 'buy')]['shares'] == int(1000 // 59.4)
    assert t[(3, 'sell')]['date'] == '2026-10-15' and t[(3, 'sell')]['pnl'] > 0
    assert [x['fired'] for x in r['rules']] == [1, 1, 1, 1]            # price_above 每天都成立但 only_if_flat＋max_times 1
    assert r['final']['holdings'] == []
    kinds = {(x['rule'], x['result']) for x in r['triggers']}
    assert (1, 'triggered') in kinds and (1, 'filled') in kinds and (0, 'filled') in kinds
    assert r['metrics']['bench_return'] == pytest.approx(104 / 100 - 1, abs=1e-4)


@pytest.mark.db
def test_ma_cross_monthly_and_rsi(clean_db):
    db = clean_db
    # 2 日均線：收盤 100、100、100、110、95 → 10/14 由下往上穿（110 > ma 105、前一日 100 ≤ 100）→ 10/15 買；10/15 跌破（95 < 102.5）→ 期末沒執行
    _seed_market(db, {'1111': [100, 100, 100, 110, 95], '0050x': [1] * 5})
    rules = [
        {'stock_id': '1111', 'when': {'type': 'cross_above_ma', 'n': 2}, 'then': {'side': 'buy', 'qty': 5, 'unit': '股'}, 'only_if_flat': False},   # 每月那條已持有 1 股，要關掉「沒持股才買」
        {'stock_id': '1111', 'when': {'type': 'cross_below_ma', 'n': 2}, 'then': {'side': 'sell', 'unit': '全部'}},
        {'stock_id': '1111', 'when': {'type': 'monthly_day', 'd': 9}, 'then': {'side': 'buy', 'qty': 1, 'unit': '股'}, 'max_times': None},   # 10/9 第一個 ≥ 9 日的交易日
        {'stock_id': '1111', 'when': {'type': 'rsi_below', 'n': 2, 'x': 30}, 'then': {'side': 'buy', 'qty': 1, 'unit': '股'}},
    ]
    r = st.simulate_rules(rules, date(2026, 10, 8), date(2026, 10, 15), capital=5_000)
    assert r['available']
    by = {}
    for x in r['trades']:
        by.setdefault(x['rule'], []).append(x)
    assert by[2][0]['date'] == '2026-10-09' and len(by[2]) == 1                      # 每月一次
    assert by[0][0]['date'] == '2026-10-15' and by[0][0]['signal_date'] == '2026-10-14'
    assert 1 not in by                                                               # 跌破在最後一天收盤觸發，沒有下一個交易日
    assert any(x['rule'] == 1 and x['result'] == 'triggered' for x in r['triggers'])
    assert 3 not in by                                                               # RSI(2) 在 10/15 才跌到低檔（95），同樣沒機會執行
    assert len(r['final']['holdings']) == 1 and r['final']['holdings'][0]['shares'] == 6


def test_group_validate_and_text():
    g = {'stock_id': '2330', 'when': {'op': 'and', 'conds': [{'type': 'monthly_day', 'd': 5}, {'type': 'below_ma', 'n': 60}]}, 'then': {'side': 'buy', 'qty': 20000, 'unit': '元'}}
    assert st.validate_rules([g]) == []
    assert st.rule_text(g) == '2330：（每月 5 日起第一個交易日 且 收盤在 60 日均線之下） → 買 20000元'
    nested = {'stock_id': '2330', 'when': {'op': 'or', 'conds': [{'type': 'rsi_below', 'n': 14, 'x': 30}, {'op': 'and', 'conds': [{'type': 'below_ma', 'n': 20}, {'type': 'change_below', 'n': 5, 'x': -5}]}]}, 'then': {'side': 'buy', 'qty': 1, 'unit': '股'}}
    assert st.validate_rules([nested]) == [] and st.rule_text(nested).startswith('2330：（RSI(14) < 30 或 （收盤在 20 日均線之下 且 5 日報酬 ≤ -5%）） →')
    assert st.has_date_leaf(g['when']) and not st.has_date_leaf(nested['when'])
    bad = st.validate_rules([
        {'stock_id': '2330', 'when': {'op': 'xor', 'conds': [{'type': 'price_below', 'x': 1}]}, 'then': {'side': 'buy', 'qty': 1, 'unit': '股'}},
        {'stock_id': '2330', 'when': {'op': 'and', 'conds': []}, 'then': {'side': 'buy', 'qty': 1, 'unit': '股'}},
        {'stock_id': '2330', 'when': {'op': 'and', 'conds': [{'op': 'and', 'conds': [{'op': 'and', 'conds': [{'type': 'price_below', 'x': 1}]}]}]}, 'then': {'side': 'buy', 'qty': 1, 'unit': '股'}},
    ])
    assert len(bad) == 3 and 'op' in bad[0] and '1～8' in bad[1] and '兩層' in bad[2]


@pytest.mark.db
def test_and_or_groups_fire_correctly(clean_db):
    db = clean_db
    # 1111 收盤 100、100、100、80、82；2 日均線 10/14 = 90
    _seed_market(db, {'1111': [100, 100, 100, 80, 82]})
    rules = [
        # AND：跌破 2 日均線 且 5 日… 用 price_below 90 代替：10/14 收 80 兩個都成立 → 10/15 開盤買
        {'stock_id': '1111', 'when': {'op': 'and', 'conds': [{'type': 'cross_below_ma', 'n': 2}, {'type': 'price_below', 'x': 90}]}, 'then': {'side': 'buy', 'qty': 3, 'unit': '股'}, 'only_if_flat': False},
        # AND 失敗：跌破均線 且 收盤 < 50 → 永遠不成立
        {'stock_id': '1111', 'when': {'op': 'and', 'conds': [{'type': 'cross_below_ma', 'n': 2}, {'type': 'price_below', 'x': 50}]}, 'then': {'side': 'buy', 'qty': 3, 'unit': '股'}, 'only_if_flat': False},
        # OR：收盤 < 50 或 收盤 > 95 → 10/8 就成立（100 > 95）→ 10/9 開盤買，只買一次
        {'stock_id': '1111', 'when': {'op': 'or', 'conds': [{'type': 'price_below', 'x': 50}, {'type': 'price_above', 'x': 95}]}, 'then': {'side': 'buy', 'qty': 2, 'unit': '股'}, 'only_if_flat': False},
        # 日期 且 指標：每月 13 日起第一個交易日（10/13）且 前一日（10/9）收盤 < 150 → 10/13 開盤買；當天開盤判斷
        {'stock_id': '1111', 'when': {'op': 'and', 'conds': [{'type': 'monthly_day', 'd': 13}, {'type': 'price_below', 'x': 150}]}, 'then': {'side': 'buy', 'qty': 1, 'unit': '股'}, 'only_if_flat': False},
        # 日期 且 指標不成立：每月 13 日 且 前一日收盤 < 50 → 不買
        {'stock_id': '1111', 'when': {'op': 'and', 'conds': [{'type': 'monthly_day', 'd': 13}, {'type': 'price_below', 'x': 50}]}, 'then': {'side': 'buy', 'qty': 1, 'unit': '股'}, 'only_if_flat': False},
    ]
    r = st.simulate_rules(rules, date(2026, 10, 8), date(2026, 10, 15), capital=5_000)
    assert r['available']
    by = {}
    for x in r['trades']:
        by.setdefault(x['rule'], []).append(x)
    assert by[2][0]['date'] == '2026-10-09' and len(by[2]) == 1
    assert by[3][0]['date'] == '2026-10-13' and by[3][0]['signal_date'] == '2026-10-13'
    assert 4 not in by and 1 not in by
    assert by[0][0]['date'] == '2026-10-15' and by[0][0]['signal_date'] == '2026-10-14' and by[0][0]['shares'] == 3
    trig = next(t for t in r['triggers'] if t['rule'] == 0 and t['result'] == 'triggered')
    assert '條件值' in trig['note']
    assert [x['fired'] for x in r['rules']] == [1, 0, 1, 1, 0]

