"""
程式交易的規則（純函式，不碰資料庫）——引擎（trading_engine.py，每天真的跑）和回放（trading_replay.py，套在歷史行情上）用同一份，
這樣「接上之後會怎樣」的模擬和實際執行的規則才是同一套，不會模擬一套、執行一套。

    rebalance_orders(targets, held, cash, close, rules, ...)   清單 → 調倉委託（退出全賣、超過賣超過、不足買；買單按現金＋賣出淨額縮）
    stop_loss_orders(held, avg_cost, close, rules, ...)        收盤跌破成本 × (1 − stop_loss_pct) → 隔天全賣
    fill_orders(orders, prices, held, cash)                    用隔天行情模擬零股限價單成交（開盤 ≤／≥ 限價；鎖死、沒行情不成交）
    requote(order, close, rules)                               未成交：新收盤重掛或取消
費率與模擬帳戶一致：單邊手續費 0.0855%、賣出證交稅 0.3%；一字鎖漲跌停 = 高 = 低且相對前收 ≥ 9.5%。
"""
import math
from typing import Optional

FEE_RATE = 0.000855
TAX_RATE = 0.003
LIMIT_LOCK = 0.095

RULES_DEFAULT = {
    'stop_loss_pct': 0.15,      # 個股：收盤跌破成本 15% 就出場（0 = 關閉）
    'rel_dd_guard': 0.10,       # 帳戶：相對 0050 落後 10% 就停新買單
    'limit_slip': 0.005,        # 限價：收盤 ±0.5%
    'max_attempts': 3,          # 未成交重掛次數
}


def limit_price(side: str, close: float, slip: float) -> Optional[float]:
    """限價單的價格；slip 為 None 代表市價（照單全收）。"""
    if slip is None:
        return None
    return round(close * (1 + slip if side == 'buy' else 1 - slip), 2)


def rebalance_orders(targets: dict, held: dict, cash: float, close: dict, rules: dict, order_date, rebalance_date,
                     guard: bool = False, slip: Optional[float] = 'rules') -> list:
    """
    targets {sid: weight}、held {sid: shares}、close {sid: 收盤}（order_date 當天）。
    回 [{order_date, rebalance_date, stock_id, side, shares, limit_price, reason}]，先賣後買。
    guard=True 時不產生買單（相對回撤守門）。slip='rules' 用 rules['limit_slip']；None 代表市價。
    """
    slip = rules['limit_slip'] if slip == 'rules' else slip
    nav = cash + sum(n * (close.get(s) or 0.0) for s, n in held.items())
    out, sells_val = [], 0.0
    for s, n in sorted(held.items()):
        c = close.get(s)
        if not c or n <= 0:
            continue
        target_val = targets.get(s, 0.0) * nav
        cur_val = n * c
        if cur_val - target_val < c:
            continue
        sell = n if s not in targets else int(math.floor((cur_val - target_val) / c))
        if sell <= 0:
            continue
        out.append({'order_date': order_date, 'rebalance_date': rebalance_date, 'stock_id': s, 'side': 'sell', 'shares': sell,
                    'limit_price': limit_price('sell', c, slip), 'reason': 'exit' if s not in targets else 'rebalance'})
        sells_val += sell * c * (1 - FEE_RATE - TAX_RATE)
    if guard:
        return out
    buys = []
    for s, w in targets.items():
        c = close.get(s)
        if not c:
            continue
        target_val = w * nav
        cur_val = held.get(s, 0) * c
        if target_val - cur_val < c:
            continue
        buys.append((s, target_val - cur_val, c))
    need = sum(v * (1 + FEE_RATE) for _, v, _ in buys)
    budget = cash + sells_val
    scale = min(1.0, budget / need) if need > 0 else 1.0
    for s, val, c in sorted(buys, key=lambda x: -x[1]):
        shares = int(math.floor(val * scale / c))
        if shares > 0:
            out.append({'order_date': order_date, 'rebalance_date': rebalance_date, 'stock_id': s, 'side': 'buy', 'shares': shares,
                        'limit_price': limit_price('buy', c, slip), 'reason': 'rebalance'})
    return out


def stop_loss_orders(held: dict, avg_cost: dict, close: dict, rules: dict, order_date, pending_sell: set = frozenset()) -> list:
    """收盤 ≤ 成本 × (1 − stop_loss_pct) → 隔天全賣；已有待成交賣單的不重複。回 [{..., reason: 'stop_loss', note}]。"""
    pct, slip = rules['stop_loss_pct'], rules['limit_slip']
    if not pct or pct <= 0 or pct >= 1:
        return []                                   # 0（或 ≥ 1）= 關閉停損
    out = []
    for s, n in sorted(held.items()):
        c = close.get(s); cost = avg_cost.get(s)
        if not c or not cost or n <= 0 or s in pending_sell:
            continue
        if c <= cost * (1 - pct):
            out.append({'order_date': order_date, 'rebalance_date': None, 'stock_id': s, 'side': 'sell', 'shares': n,
                        'limit_price': limit_price('sell', c, slip), 'reason': 'stop_loss',
                        'note': f'收盤 {c} ≤ 成本 {cost:.2f} × (1 − {pct})', 'cost': round(cost, 2), 'close': c})
    return out


def is_locked(p: dict) -> bool:
    return bool(p and p.get('high') is not None and p['high'] == p['low'] and p.get('prev_close') and abs(p['open'] / p['prev_close'] - 1) >= LIMIT_LOCK)


def fill_orders(orders: list, prices: dict, held: dict, cash: float) -> dict:
    """
    用成交日行情模擬一批委託：先賣後買。prices {sid: {open, high, low, close, prev_close}}。
    回 {'fills': [{order, status, filled_shares, filled_price, fee, tax, note}], 'held': 新持股, 'cash': 新現金}。
    status：filled／unfilled（限價沒碰到、鎖死、沒行情）／rejected（沒持股可賣、現金不夠）。
    """
    held = dict(held)
    fills = []
    for o in sorted(orders, key=lambda x: 0 if x['side'] == 'sell' else 1):
        sid, side, shares, limit = o['stock_id'], o['side'], int(o['shares']), o.get('limit_price')
        p = prices.get(sid)
        if not p or not p.get('open'):
            fills.append({'order': o, 'status': 'unfilled', 'note': '沒行情'}); continue
        if is_locked(p):
            fills.append({'order': o, 'status': 'unfilled', 'note': '一字鎖死'}); continue
        open_ = p['open']
        if side == 'sell':
            if limit is not None and open_ < float(limit):
                fills.append({'order': o, 'status': 'unfilled', 'note': f'開盤 {open_} 低於限價 {float(limit)}'}); continue
            have = held.get(sid, 0)
            if shares > have:
                if have <= 0:
                    fills.append({'order': o, 'status': 'rejected', 'note': '沒有持股可賣'}); continue
                shares = have
            gross = shares * open_
            fee, tax = round(gross * FEE_RATE, 2), round(gross * TAX_RATE, 2)
            cash += gross - fee - tax
            held[sid] = have - shares
            if held[sid] == 0:
                del held[sid]
            fills.append({'order': o, 'status': 'filled', 'filled_shares': shares, 'filled_price': open_, 'fee': fee, 'tax': tax, 'gross': gross})
        else:
            if limit is not None and open_ > float(limit):
                fills.append({'order': o, 'status': 'unfilled', 'note': f'開盤 {open_} 高於限價 {float(limit)}'}); continue
            if shares * open_ * (1 + FEE_RATE) > cash:
                shares = int(math.floor(cash / (open_ * (1 + FEE_RATE))))
            if shares <= 0:
                fills.append({'order': o, 'status': 'rejected', 'note': '現金不夠'}); continue
            gross = shares * open_
            fee = round(gross * FEE_RATE, 2)
            cash -= gross + fee
            held[sid] = held.get(sid, 0) + shares
            fills.append({'order': o, 'status': 'filled', 'filled_shares': shares, 'filled_price': open_, 'fee': fee, 'tax': 0.0, 'gross': gross})
    return {'fills': fills, 'held': held, 'cash': round(cash, 2)}


def requote(order: dict, close: Optional[float], rules: dict, exec_date) -> dict:
    """未成交後：attempts + 1；到上限就 cancelled，否則用新收盤重掛（order_date 改成 exec_date）。回新的 order dict（含 status）。"""
    o = dict(order)
    o['attempts'] = int(o.get('attempts', 0)) + 1
    if o['attempts'] >= int(rules['max_attempts']):
        o['status'] = 'cancelled'
        return o
    if close:
        o['limit_price'] = limit_price(o['side'], close, rules['limit_slip']) if o.get('limit_price') is not None else None
    o['order_date'] = exec_date
    o['status'] = 'pending'
    return o
