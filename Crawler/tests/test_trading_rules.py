"""程式交易規則（純函式，不碰資料庫）：調倉委託、停損、限價成交、重掛。引擎與回放共用這一份。"""
import math

import pytest

import trading_rules as tr

R = dict(tr.RULES_DEFAULT)


def test_limit_price_and_none_means_market():
    assert tr.limit_price('buy', 100, 0.005) == 100.5 and tr.limit_price('sell', 100, 0.005) == 99.5
    assert tr.limit_price('buy', 100, None) is None


def test_rebalance_orders_sells_first_then_buys_scaled_by_budget():
    targets = {'A': 0.5, 'B': 0.5}
    held = {'C': 100}                                     # 不在清單 → 全賣
    close = {'A': 100.0, 'B': 50.0, 'C': 20.0}
    orders = tr.rebalance_orders(targets, held, cash=1000.0, close=close, rules=R, order_date='d', rebalance_date='d')
    assert orders[0] == {'order_date': 'd', 'rebalance_date': 'd', 'stock_id': 'C', 'side': 'sell', 'shares': 100, 'limit_price': 19.9, 'reason': 'exit'}
    buys = {o['stock_id']: o for o in orders[1:]}
    nav = 1000 + 100 * 20
    budget = 1000 + 100 * 20 * (1 - tr.FEE_RATE - tr.TAX_RATE)
    need = (0.5 * nav + 0.5 * nav) * (1 + tr.FEE_RATE)
    scale = min(1.0, budget / need)
    assert buys['A']['shares'] == math.floor(0.5 * nav * scale / 100) and buys['A']['limit_price'] == 100.5
    assert buys['B']['shares'] == math.floor(0.5 * nav * scale / 50)
    # 守門：只剩賣單
    g = tr.rebalance_orders(targets, held, 1000.0, close, R, 'd', 'd', guard=True)
    assert [o['side'] for o in g] == ['sell']
    # 市價（照單全收）：limit None
    m = tr.rebalance_orders(targets, {}, 1000.0, close, R, 'd', 'd', slip=None)
    assert all(o['limit_price'] is None for o in m)
    # 已達標或差不到一股：不動
    assert tr.rebalance_orders({'A': 1.0}, {'A': 10}, 0.0, {'A': 100.0}, R, 'd', 'd') == []


def test_stop_loss_orders():
    held = {'A': 10, 'B': 10, 'C': 10}
    cost = {'A': 100.0, 'B': 100.0}                      # C 沒成本（不知道）→ 不判
    close = {'A': 84.0, 'B': 86.0, 'C': 50.0}
    out = tr.stop_loss_orders(held, cost, close, R, 'd')
    assert [o['stock_id'] for o in out] == ['A'] and out[0]['shares'] == 10 and out[0]['limit_price'] == round(84 * 0.995, 2) and out[0]['reason'] == 'stop_loss'
    assert tr.stop_loss_orders(held, cost, close, R, 'd', pending_sell={'A'}) == []


def test_fill_orders_limit_lock_reject_and_cash():
    px = {'A': {'open': 100.0, 'high': 101, 'low': 99, 'close': 100, 'prev_close': 100},
          'L': {'open': 110.0, 'high': 110.0, 'low': 110.0, 'close': 110, 'prev_close': 100}}   # 一字鎖漲停
    orders = [
        {'stock_id': 'A', 'side': 'buy', 'shares': 5, 'limit_price': 100.5, 'reason': 'rebalance'},      # 成交
        {'stock_id': 'A', 'side': 'buy', 'shares': 5, 'limit_price': 99.0, 'reason': 'rebalance'},       # 開盤高於限價
        {'stock_id': 'L', 'side': 'buy', 'shares': 1, 'limit_price': None, 'reason': 'rebalance'},       # 鎖死
        {'stock_id': 'Z', 'side': 'buy', 'shares': 1, 'limit_price': None, 'reason': 'rebalance'},       # 沒行情
        {'stock_id': 'A', 'side': 'sell', 'shares': 3, 'limit_price': 101.0, 'reason': 'exit'},          # 開盤低於限價
        {'stock_id': 'Q', 'side': 'sell', 'shares': 3, 'limit_price': None, 'reason': 'exit'},           # 沒持股
    ]
    px['Q'] = px['A']
    res = tr.fill_orders(orders, px, held={}, cash=1000.0)
    st = [f['status'] for f in res['fills']]
    # 先賣後買：兩張賣單排前面
    assert st == ['unfilled', 'rejected', 'filled', 'unfilled', 'unfilled', 'unfilled']
    assert res['held'] == {'A': 5} and res['cash'] == pytest.approx(1000 - 500 - round(500 * tr.FEE_RATE, 2), abs=0.01)
    # 賣：有稅、賣超過持股縮到持股
    res2 = tr.fill_orders([{'stock_id': 'A', 'side': 'sell', 'shares': 99, 'limit_price': 99.0, 'reason': 'exit'}], px, {'A': 5}, 0.0)
    f = res2['fills'][0]
    assert f['status'] == 'filled' and f['filled_shares'] == 5 and f['tax'] == round(500 * tr.TAX_RATE, 2) and res2['held'] == {}
    # 買：現金不夠縮單、完全沒錢拒絕
    res3 = tr.fill_orders([{'stock_id': 'A', 'side': 'buy', 'shares': 100, 'limit_price': None, 'reason': 'rebalance'}], px, {}, 350.0)
    assert res3['fills'][0]['filled_shares'] == 3
    assert tr.fill_orders([{'stock_id': 'A', 'side': 'buy', 'shares': 1, 'limit_price': None, 'reason': 'rebalance'}], px, {}, 10.0)['fills'][0]['status'] == 'rejected'


def test_requote_then_cancel():
    o = {'stock_id': 'A', 'side': 'buy', 'shares': 5, 'limit_price': 100.5, 'order_date': 'd1', 'attempts': 0}
    r1 = tr.requote(o, 103.0, R, 'd2')
    assert r1['status'] == 'pending' and r1['attempts'] == 1 and r1['limit_price'] == round(103 * 1.005, 2) and r1['order_date'] == 'd2'
    r2 = tr.requote(r1, 104.0, R, 'd3')
    r3 = tr.requote(r2, 105.0, R, 'd4')
    assert r2['status'] == 'pending' and r3['status'] == 'cancelled' and r3['attempts'] == 3
    # 市價單重掛仍是市價
    assert tr.requote({'side': 'sell', 'limit_price': None, 'attempts': 0}, 50.0, R, 'd')['limit_price'] is None
