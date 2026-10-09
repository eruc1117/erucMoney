"""
條件規則模擬（Iteration 61）：使用者設「條件 → 買／賣」的規則，逐日用實際行情判斷、觸發就下單，給收益對 0050。公開、只讀。

規則（JSON，一條一個 dict）：
    {"stock_id": "2330",
     "when": {"type": "cross_below_ma", "n": 20},          # 條件（見 CONDITIONS）
     "then": {"side": "sell", "qty": null, "unit": "全部"},  # 動作：buy／sell；unit 股／張／元／全部
     "max_times": 1,                                         # 最多觸發幾次（null = 不限）
     "only_if_flat": true,                                   # 買：沒持股才買（避免每天加碼）；賣：有持股才賣（本來就是）
     "cooldown": 0}                                          # 觸發後幾個交易日內不再觸發
條件在每個交易日**收盤**判斷，動作在**下一個交易日開盤**市價成交（和引擎一樣）；日期類條件（monthly_day、on_date）在當天開盤成交。
指標用還原收盤算：MA(n)、RSI(n，Wilder)、n 日報酬；成本用模擬帳戶的平均成本（含手續費）。
成交、價格、指標算法與其他模擬同一份（trading_rules.fill_orders、trading_replay.load_prices／_metrics）。
"""
import math
from datetime import date
from typing import Optional

import pandas as pd

import portfolio_paper as pp
import trading_replay as rp
import trading_rules as tr
from trading_sim import load_prices_any

MAX_RULES = 50
MAX_YEARS = 8

# type → (需要的參數, 說明模板)
CONDITIONS = {
    'price_below':      (['x'],      '收盤 < {x}'),
    'price_above':      (['x'],      '收盤 > {x}'),
    'cross_above_ma':   (['n'],      '收盤由下往上穿過 {n} 日均線'),
    'cross_below_ma':   (['n'],      '收盤由上往下跌破 {n} 日均線'),
    'above_ma':         (['n'],      '收盤在 {n} 日均線之上'),
    'below_ma':         (['n'],      '收盤在 {n} 日均線之下'),
    'rsi_below':        (['n', 'x'], 'RSI({n}) < {x}'),
    'rsi_above':        (['n', 'x'], 'RSI({n}) > {x}'),
    'change_below':     (['n', 'x'], '{n} 日報酬 ≤ {x}%'),
    'change_above':     (['n', 'x'], '{n} 日報酬 ≥ {x}%'),
    'loss_from_cost':   (['x'],      '比平均成本低 {x}%（停損）'),
    'gain_from_cost':   (['x'],      '比平均成本高 {x}%（停利）'),
    'monthly_day':      (['d'],      '每月 {d} 日起第一個交易日'),
    'on_date':          (['date'],   '{date} 當天'),
}
UNITS = ('股', '張', '元', '全部')


def rule_text(r: dict) -> str:
    w, t = r['when'], r['then']
    cond = CONDITIONS[w['type']][1].format(**{k: w.get(k) for k in CONDITIONS[w['type']][0]})
    act = ('買 ' if t['side'] == 'buy' else '賣 ') + ('全部' if t.get('unit') == '全部' else f"{t.get('qty')}{t.get('unit', '股')}")
    return f"{r['stock_id']}：{cond} → {act}"


def validate_rules(rules: list) -> list:
    """回錯誤清單（空 = 合法）。"""
    errs = []
    if not isinstance(rules, list) or not rules:
        return ['rules 要是非空陣列']
    if len(rules) > MAX_RULES:
        return [f'規則最多 {MAX_RULES} 條']
    for i, r in enumerate(rules, 1):
        if not isinstance(r, dict):
            errs.append(f'第 {i} 條不是物件'); continue
        sid = str(r.get('stock_id', '')).strip().upper()
        if not (4 <= len(sid) <= 6):
            errs.append(f'第 {i} 條：股票代號看不懂')
        w, t = r.get('when') or {}, r.get('then') or {}
        if w.get('type') not in CONDITIONS:
            errs.append(f'第 {i} 條：條件 {w.get("type")} 不認識'); continue
        for k in CONDITIONS[w['type']][0]:
            if k == 'date':
                try:
                    date.fromisoformat(str(w.get('date')))
                except (TypeError, ValueError):
                    errs.append(f'第 {i} 條：日期要是 YYYY-MM-DD')
            elif not isinstance(w.get(k), (int, float)):
                errs.append(f'第 {i} 條：條件缺參數 {k}')
            elif k == 'n' and not (1 <= w[k] <= 250):
                errs.append(f'第 {i} 條：{k} 要在 1～250')
            elif k == 'd' and not (1 <= w[k] <= 28):
                errs.append(f'第 {i} 條：每月幾號要在 1～28')
        if t.get('side') not in ('buy', 'sell'):
            errs.append(f'第 {i} 條：動作要是 buy 或 sell')
        unit = t.get('unit', '股')
        if unit not in UNITS:
            errs.append(f'第 {i} 條：單位要是 股／張／元／全部')
        if unit == '全部' and t.get('side') == 'buy':
            errs.append(f'第 {i} 條：買進不能用「全部」')
        if unit != '全部' and not (isinstance(t.get('qty'), (int, float)) and t['qty'] > 0):
            errs.append(f'第 {i} 條：數量要 > 0')
        if unit == '元' and t.get('side') == 'sell':
            errs.append(f'第 {i} 條：賣出請用股數或「全部」')
    return errs


def _indicators(closes: pd.Series, rules_for_stock: list) -> dict:
    """只算這檔用得到的指標；回 {name: Series}。"""
    out = {}
    for r in rules_for_stock:
        w = r['when']; t = w['type']
        if t in ('cross_above_ma', 'cross_below_ma', 'above_ma', 'below_ma'):
            out.setdefault(f"ma{w['n']}", closes.rolling(int(w['n'])).mean())
        elif t in ('rsi_below', 'rsi_above'):
            n = int(w['n'])
            if f'rsi{n}' not in out:
                delta = closes.diff()
                up = delta.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
                dn = (-delta.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
                rs = up / dn.replace(0, float('nan'))
                out[f'rsi{n}'] = 100 - 100 / (1 + rs)
        elif t in ('change_below', 'change_above'):
            out.setdefault(f"chg{w['n']}", closes.pct_change(int(w['n'])) * 100)
    return out


def _check(r: dict, d: date, i: int, closes: pd.Series, ind: dict, held: int, avg_cost: Optional[float]) -> Optional[dict]:
    """條件成立回 {'value': …}，否則 None。i 是 d 在 closes 的位置。"""
    w = r['when']; t = w['type']
    c = float(closes.iloc[i])
    if t == 'price_below':
        return {'value': c} if c < w['x'] else None
    if t == 'price_above':
        return {'value': c} if c > w['x'] else None
    if t in ('cross_above_ma', 'cross_below_ma', 'above_ma', 'below_ma'):
        ma = ind[f"ma{w['n']}"]
        m = ma.iloc[i]
        if m != m:
            return None
        if t == 'above_ma':
            return {'value': round(c / m - 1, 4)} if c > m else None
        if t == 'below_ma':
            return {'value': round(c / m - 1, 4)} if c < m else None
        if i == 0:
            return None
        pc, pm = float(closes.iloc[i - 1]), ma.iloc[i - 1]
        if pm != pm:
            return None
        if t == 'cross_above_ma':
            return {'value': round(m, 2)} if (pc <= pm and c > m) else None
        return {'value': round(m, 2)} if (pc >= pm and c < m) else None
    if t in ('rsi_below', 'rsi_above'):
        v = ind[f"rsi{w['n']}"].iloc[i]
        if v != v:
            return None
        ok = v < w['x'] if t == 'rsi_below' else v > w['x']
        return {'value': round(float(v), 1)} if ok else None
    if t in ('change_below', 'change_above'):
        v = ind[f"chg{w['n']}"].iloc[i]
        if v != v:
            return None
        ok = v <= w['x'] if t == 'change_below' else v >= w['x']
        return {'value': round(float(v), 2)} if ok else None
    if t in ('loss_from_cost', 'gain_from_cost'):
        if held <= 0 or not avg_cost:
            return None
        chg = (c / avg_cost - 1) * 100
        ok = chg <= -w['x'] if t == 'loss_from_cost' else chg >= w['x']
        return {'value': round(chg, 2)} if ok else None
    return None


def simulate_rules(rules: list, start: date, end: date, capital: float = 1_000_000) -> dict:
    errs = validate_rules(rules)
    if errs:
        return {'available': False, 'reason': '規則有問題', 'errors': errs}
    if end < start or (end - start).days > MAX_YEARS * 366:
        return {'available': False, 'reason': f'期間要正向且最多 {MAX_YEARS} 年'}
    rules = [{**r, 'stock_id': str(r['stock_id']).strip().upper(), 'max_times': r.get('max_times', 1 if r['when']['type'] not in ('monthly_day',) else None),
              'only_if_flat': r.get('only_if_flat', r['then']['side'] == 'buy' and r['when']['type'] not in ('monthly_day', 'on_date')),
              'cooldown': int(r.get('cooldown') or 0)} for r in rules]
    days = pp.market_days(start, end)
    if len(days) < 2:
        return {'available': False, 'reason': '這段期間沒有全市場行情（資料從 2018-01 起）'}
    ids = sorted({r['stock_id'] for r in rules})
    # 指標要暖機：多抓 420 天（250 日均線也夠）
    warm_start = date.fromordinal(start.toordinal() - 420)
    prices = load_prices_any(ids, warm_start, end)
    bench = rp.load_bench(start, end)
    closes, ind = {}, {}
    for s in ids:
        ser = pd.Series({d: prices[d][s]['close'] for d in sorted(prices) if s in prices[d] and prices[d][s].get('close')})
        closes[s] = ser
        ind[s] = _indicators(ser, [r for r in rules if r['stock_id'] == s])
    missing = [s for s in ids if closes[s].empty]
    pos = {s: {d: i for i, d in enumerate(closes[s].index)} for s in ids}

    cash, held = float(capital), {}
    cost_total, cost_shares = {}, {}
    fired = [0] * len(rules); last_fire = [None] * len(rules)
    pending = []                      # 等下一個交易日開盤的單
    triggers, trades, nav_rows = [], [], []
    last_close = {}
    cost_sum = traded_sum = 0.0

    def avg_cost(s):
        return cost_total[s] / cost_shares[s] if cost_shares.get(s) else None

    def make_order(r, idx, d, exec_now):
        t = r['then']; s = r['stock_id']
        shares = None
        if t.get('unit') == '全部':
            shares = held.get(s, 0)
        elif t.get('unit') == '張':
            shares = int(t['qty'] * 1000)
        elif t.get('unit') == '股':
            shares = int(t['qty'])
        return {'rule': idx, 'stock_id': s, 'side': t['side'], 'shares': shares, 'amount': t['qty'] if t.get('unit') == '元' else None,
                'limit_price': None, 'reason': 'rule', 'signal_date': d, 'exec_now': exec_now}

    def execute(orders, d, px):
        nonlocal cash, held, cost_sum, traded_sum
        ready = []
        for o in orders:
            p = px.get(o['stock_id'])
            sh = o['shares']
            if o['amount'] is not None:
                sh = int(math.floor(o['amount'] / p['open'])) if p and p.get('open') else 0
            if o['side'] == 'sell' and o['shares'] is None:
                sh = held.get(o['stock_id'], 0)
            if not sh or sh <= 0:
                triggers.append({'date': str(d), 'signal_date': str(o['signal_date']), 'rule': o['rule'], 'text': rule_text(rules[o['rule']]), 'result': 'skipped',
                                 'note': '沒有持股可賣' if o['side'] == 'sell' else ('沒行情' if not p else '金額不夠買一股')})
                continue
            ready.append({**o, 'shares': sh})
        if not ready:
            return
        res = tr.fill_orders(ready, px, held, cash)
        held, cash = res['held'], res['cash']
        for f in res['fills']:
            o = f['order']; idx = o['rule']
            if f['status'] == 'filled':
                sh, price = f['filled_shares'], f['filled_price']
                traded_sum += f['gross']; cost_sum += f['fee'] + f['tax']
                pnl = None
                if o['side'] == 'buy':
                    cost_total[o['stock_id']] = cost_total.get(o['stock_id'], 0.0) + f['gross'] + f['fee']
                    cost_shares[o['stock_id']] = cost_shares.get(o['stock_id'], 0) + sh
                else:
                    ac = avg_cost(o['stock_id']) or price
                    pnl = round((price - ac) * sh - f['fee'] - f['tax'], 2)
                    cost_total[o['stock_id']] = cost_total.get(o['stock_id'], 0.0) - ac * sh
                    cost_shares[o['stock_id']] = cost_shares.get(o['stock_id'], 0) - sh
                    if cost_shares[o['stock_id']] <= 0:
                        cost_total.pop(o['stock_id'], None); cost_shares.pop(o['stock_id'], None)
                trades.append({'date': str(d), 'signal_date': str(o['signal_date']), 'rule': idx, 'text': rule_text(rules[idx]), 'stock_id': o['stock_id'],
                               'side': o['side'], 'shares': sh, 'price': price, 'gross': round(f['gross'], 2), 'fee': f['fee'], 'tax': f['tax'], 'pnl': pnl})
                triggers.append({'date': str(d), 'signal_date': str(o['signal_date']), 'rule': idx, 'text': rule_text(rules[idx]), 'result': 'filled',
                                 'note': f"{'買' if o['side'] == 'buy' else '賣'} {sh} 股 @ {price}"})
            else:
                triggers.append({'date': str(d), 'signal_date': str(o['signal_date']), 'rule': idx, 'text': rule_text(rules[idx]), 'result': f['status'], 'note': f.get('note')})

    for di, d in enumerate(days):
        px = prices.get(d, {})
        for s, p in px.items():
            if p.get('close'):
                last_close[s] = p['close']
        # 1. 開盤：執行前一日收盤觸發的單 ＋ 日期類今天觸發的單
        todo = [o for o in pending]
        pending = []
        for idx, r in enumerate(rules):
            w = r['when']; t = w['type']
            hit = None
            if t == 'monthly_day':
                # 本月 d 日起第一個交易日 = 今天是本月第一個 ≥ d 日的交易日
                if d.day >= w['d'] and not any(x.month == d.month and x.year == d.year and x.day >= w['d'] for x in days[:di]):
                    hit = {'value': None}
            elif t == 'on_date':
                od = date.fromisoformat(str(w['date']))
                if d >= od and not any(x >= od for x in days[:di]):
                    hit = {'value': None}
            if hit and _can_fire(r, idx, fired, last_fire, di, held):
                fired[idx] += 1; last_fire[idx] = di
                todo.append(make_order(r, idx, d, True))
        if todo:
            execute(todo, d, px)
        # 2. 結算
        value = sum(n * last_close.get(s, 0.0) for s, n in held.items())
        nav_rows.append((d, cash + value, cash, bench.get(d)))
        # 3. 收盤：判斷指標類條件 → 明天開盤
        for idx, r in enumerate(rules):
            t = r['when']['type']
            if t in ('monthly_day', 'on_date'):
                continue
            s = r['stock_id']
            if d not in pos.get(s, {}):
                continue
            i = pos[s][d]
            hit = _check(r, d, i, closes[s], ind[s], held.get(s, 0), avg_cost(s))
            if hit and _can_fire(r, idx, fired, last_fire, di, held):
                fired[idx] += 1; last_fire[idx] = di
                pending.append(make_order(r, idx, d, False))
                triggers.append({'date': str(d), 'signal_date': str(d), 'rule': idx, 'text': rule_text(rules[idx]), 'result': 'triggered',
                                 'note': f"條件值 {hit['value']}" if hit.get('value') is not None else ''})
    sim = {'nav_rows': nav_rows, 'traded_sum': traded_sum, 'cost_sum': cost_sum}
    m = rp._metrics(sim, capital)
    final_holdings = [{'stock_id': s, 'shares': n, 'last': last_close.get(s), 'value': round(n * last_close.get(s, 0.0), 2),
                       'avg_cost': round(avg_cost(s), 2) if avg_cost(s) else None} for s, n in sorted(held.items())]
    return {'available': True, 'start': str(start), 'end': str(end), 'capital': capital, 'n_rules': len(rules), 'n_days': len(days),
            'rules': [{'i': i, 'text': rule_text(r), 'fired': fired[i], 'max_times': r['max_times']} for i, r in enumerate(rules)],
            'missing': missing, 'metrics': m, 'series': rp._series(sim, capital), 'trades': trades, 'triggers': triggers[-400:],
            'final': {'cash': round(cash, 2), 'holdings': final_holdings, 'value': round(cash + sum(h['value'] for h in final_holdings), 2)},
            'realized_pnl': round(sum((t['pnl'] or 0) for t in trades), 2), 'costs': round(cost_sum, 2),
            'caveat': '條件在收盤判斷、下一個交易日開盤市價成交（日期類當天開盤）；指標用還原收盤；手續費 0.0855%、賣出稅 0.3%、無滑價。規則是你設的，這只回答「照這些規則做會怎樣」，過去成立不代表未來。'}


def _can_fire(r, idx, fired, last_fire, di, held) -> bool:
    if r['max_times'] is not None and fired[idx] >= r['max_times']:
        return False
    if r['cooldown'] and last_fire[idx] is not None and di - last_fire[idx] <= r['cooldown']:
        return False
    s = r['stock_id']; side = r['then']['side']
    if side == 'buy' and r['only_if_flat'] and held.get(s, 0) > 0:
        return False
    if side == 'sell' and held.get(s, 0) <= 0:
        return False
    return True
