"""
自訂交易指令模擬（Iteration 60）：使用者寫幾行指令——哪天買賣哪檔、多少股或多少錢——設定期間與資金，用實際日線跑完，
給收益對 0050。給未登入者用，所以只讀資料庫、不寫任何東西。

指令文字，一行一筆（# 開頭是註解）：
    2024-01-15 買 2330 10股            # 整數股（零股）
    2024-01-15 買 2454 2張             # 張 = 1000 股
    2024-02-01 買 0050 50000元          # 用金額，執行那天開盤換算成股數
    2024-06-03 賣 2330 全部
    2024-06-03 賣 2454 500股
    2024/07/01 sell 0050 all            # 英文、斜線日期也可以
執行：指令日當天若有行情就在當天開盤成交，否則下一個有行情的交易日；市價（照單全收），一字鎖死那天不成交、順延一天。
費率與其他模擬一致：手續費 0.0855%、賣出證交稅 0.3%；價格用還原價（持股含息，與 0050 含息對稱）。
沒賣的持股以期末收盤估值。對 0050 的指標算法與回放（trading_replay）同一份。
"""
import math
import re
from datetime import date, datetime
from typing import Optional

import portfolio_paper as pp
import trading_replay as rp
import trading_rules as tr

MAX_INSTRUCTIONS = 200
MAX_YEARS = 8

_LINE = re.compile(r'^\s*(?P<date>\d{4}[-/.]?\d{1,2}[-/.]?\d{1,2})\s+(?P<side>買進|買入|買|buy|b|賣出|賣|sell|s)\s+(?P<sid>[0-9A-Za-z]{4,6})\s*(?P<qty>.*?)\s*$', re.IGNORECASE)
_QTY = re.compile(r'^(?P<num>[\d,]+(?:\.\d+)?)\s*(?P<unit>股|張|元|shares?|lots?|twd|nt\$?)?$', re.IGNORECASE)


def _parse_date(s: str) -> Optional[date]:
    s = s.replace('/', '-').replace('.', '-')
    for fmt in ('%Y-%m-%d', '%Y%m%d'):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def parse_instructions(text: str) -> dict:
    """文字 → [{line, date, side, stock_id, shares, amount, all}]；壞行收進 errors（行號、原文、原因），不丟例外。"""
    items, errors = [], []
    for i, raw in enumerate((text or '').splitlines(), 1):
        line = raw.split('#', 1)[0].strip()          # 行尾 # 之後是註解
        if not line:
            continue
        m = _LINE.match(line)
        if not m:
            errors.append({'line': i, 'text': raw, 'reason': '格式：日期 買/賣 代號 數量（10股、2張、50000元、全部）'}); continue
        d = _parse_date(m['date'])
        if not d:
            errors.append({'line': i, 'text': raw, 'reason': f"日期看不懂：{m['date']}"}); continue
        side = 'buy' if m['side'].lower() in ('買進', '買入', '買', 'buy', 'b') else 'sell'
        sid = m['sid'].upper()
        qty = (m['qty'] or '').strip()
        it = {'line': i, 'date': d, 'side': side, 'stock_id': sid, 'shares': None, 'amount': None, 'all': False}
        if side == 'sell' and (qty in ('', '全部', '全賣', '清倉') or qty.lower() == 'all'):
            it['all'] = True
        else:
            q = _QTY.match(qty)
            if not q:
                errors.append({'line': i, 'text': raw, 'reason': f'數量看不懂：{qty or "（空）"}（10股、2張、50000元、全部）'}); continue
            num = float(q['num'].replace(',', ''))
            unit = (q['unit'] or '股').lower()
            if unit in ('元', 'twd', 'nt$', 'nt'):
                if side == 'sell':
                    errors.append({'line': i, 'text': raw, 'reason': '賣出請用股數或「全部」'}); continue
                it['amount'] = num
            elif unit in ('張', 'lot', 'lots'):
                it['shares'] = int(num * 1000)
            else:
                it['shares'] = int(num)
            if it['shares'] is not None and it['shares'] <= 0 or it['amount'] is not None and it['amount'] <= 0:
                errors.append({'line': i, 'text': raw, 'reason': '數量要大於 0'}); continue
        items.append(it)
    items.sort(key=lambda x: (x['date'], x['line']))
    return {'instructions': items, 'errors': errors}


def load_prices_any(ids: list, start: date, end: date) -> dict:
    """先找全市場日線；找不到的（0050 這類 ETF、追蹤股）再到 stock_daily_prices 找，合併成同一份。"""
    prices = rp.load_prices(ids, start, end)
    have = {s for d in prices for s in prices[d]}
    missing = [s for s in ids if s not in have]
    if missing:
        extra = rp.load_prices(missing, start, end, table='stock_daily_prices')
        for d, row in extra.items():
            prices.setdefault(d, {}).update(row)
    return prices


def simulate(instructions: list, start: date, end: date, capital: float = 1_000_000) -> dict:
    """照指令在實際日線上成交，逐日結算對 0050。回指標、淨值序列、成交、略過的指令、期末持股。"""
    if end < start:
        return {'available': False, 'reason': 'end 要晚於 start'}
    if (end - start).days > MAX_YEARS * 366:
        return {'available': False, 'reason': f'期間最多 {MAX_YEARS} 年'}
    if not instructions:
        return {'available': False, 'reason': '沒有指令'}
    if len(instructions) > MAX_INSTRUCTIONS:
        return {'available': False, 'reason': f'指令最多 {MAX_INSTRUCTIONS} 筆'}
    bad = [it for it in instructions if not (start <= it['date'] <= end)]
    if bad:
        return {'available': False, 'reason': f"{len(bad)} 筆指令的日期不在期間內（例：第 {bad[0]['line']} 行 {bad[0]['date']}）"}
    days = pp.market_days(start, end)
    if len(days) < 2:
        return {'available': False, 'reason': '這段期間沒有全市場行情（資料從 2018-01 起）'}
    ids = sorted({it['stock_id'] for it in instructions})
    prices = load_prices_any(ids, start, end)
    bench = rp.load_bench(start, end)
    have_quote = {s for d in prices for s in prices[d]}
    unknown = [s for s in ids if s not in have_quote]

    cash, held = float(capital), {}
    cost_total, cost_shares = {}, {}
    pending = [dict(it, attempts=0) for it in instructions if it['stock_id'] not in unknown]
    skipped = [{'line': it['line'], 'date': str(it['date']), 'stock_id': it['stock_id'], 'reason': '這檔在期間內沒有行情（代號錯或不在全市場日線）'} for it in instructions if it['stock_id'] in unknown]
    last_close, nav_rows, trades = {}, [], []
    cost_sum = traded_sum = 0.0
    for d in days:
        px = prices.get(d, {})
        for s, p in px.items():
            if p.get('close'):
                last_close[s] = p['close']
        todo = [o for o in pending if o['date'] <= d]
        pending = [o for o in pending if o['date'] > d]
        orders = []
        for o in todo:
            p = px.get(o['stock_id'])
            shares = o['shares']
            if o['side'] == 'sell' and o['all']:
                shares = held.get(o['stock_id'], 0)
            if o['amount'] is not None:
                shares = int(math.floor(o['amount'] / p['open'])) if p and p.get('open') else 0
            if shares <= 0:
                if not p or not p.get('open'):
                    o['attempts'] += 1                   # 沒行情：順延，和股數型一樣最多 5 次
                    if o['attempts'] < 5:
                        o['date'] = d; pending.append(o)
                    else:
                        skipped.append({'line': o['line'], 'date': str(d), 'stock_id': o['stock_id'], 'reason': '連續 5 個交易日沒行情'})
                    continue
                skipped.append({'line': o['line'], 'date': str(d), 'stock_id': o['stock_id'], 'reason': '沒有持股可賣' if o['side'] == 'sell' else '金額不夠買一股'}); continue
            orders.append({'line': o['line'], 'date': o['date'], 'stock_id': o['stock_id'], 'side': o['side'], 'shares': shares, 'limit_price': None, 'reason': 'instruction', 'src': o})
        if orders:
            res = tr.fill_orders(orders, px, held, cash)
            held, cash = res['held'], res['cash']
            for f in res['fills']:
                o = f['order']
                if f['status'] == 'filled':
                    sh, price = f['filled_shares'], f['filled_price']
                    traded_sum += f['gross']; cost_sum += f['fee'] + f['tax']
                    pnl = None
                    if o['side'] == 'buy':
                        cost_total[o['stock_id']] = cost_total.get(o['stock_id'], 0.0) + f['gross'] + f['fee']
                        cost_shares[o['stock_id']] = cost_shares.get(o['stock_id'], 0) + sh
                    else:
                        ac = cost_total.get(o['stock_id'], 0.0) / cost_shares[o['stock_id']] if cost_shares.get(o['stock_id']) else price
                        pnl = round((price - ac) * sh - f['fee'] - f['tax'], 2)
                        cost_total[o['stock_id']] = cost_total.get(o['stock_id'], 0.0) - ac * sh
                        cost_shares[o['stock_id']] = cost_shares.get(o['stock_id'], 0) - sh
                        if cost_shares[o['stock_id']] <= 0:
                            cost_total.pop(o['stock_id'], None); cost_shares.pop(o['stock_id'], None)
                    trades.append({'line': o['line'], 'asked': str(o['date']), 'date': str(d), 'stock_id': o['stock_id'], 'side': o['side'], 'shares': sh, 'price': price,
                                   'gross': round(f['gross'], 2), 'fee': f['fee'], 'tax': f['tax'], 'pnl': pnl,
                                   'note': ('部分' if o['src']['shares'] and sh < o['src']['shares'] else None)})
                elif f['status'] == 'unfilled' and f.get('note') in ('一字鎖死', '沒行情') and o['src']['attempts'] < 5:
                    o['src']['attempts'] += 1; o['src']['date'] = d
                    pending.append(o['src'])                  # 順延到下一個有行情的日子（最多 5 天）
                else:
                    skipped.append({'line': o['line'], 'date': str(d), 'stock_id': o['stock_id'], 'reason': f.get('note') or f['status']})
        value = sum(n * last_close.get(s, 0.0) for s, n in held.items())
        nav_rows.append((d, cash + value, cash, bench.get(d)))
    for o in pending:
        skipped.append({'line': o['line'], 'date': str(o['date']), 'stock_id': o['stock_id'], 'reason': '期間內沒輪到執行'})
    sim = {'nav_rows': nav_rows, 'traded_sum': traded_sum, 'cost_sum': cost_sum}
    m = rp._metrics(sim, capital)
    final_holdings = [{'stock_id': s, 'shares': n, 'last': last_close.get(s), 'value': round(n * last_close.get(s, 0.0), 2),
                       'avg_cost': round(cost_total[s] / cost_shares[s], 2) if cost_shares.get(s) else None} for s, n in sorted(held.items())]
    return {'available': True, 'start': str(start), 'end': str(end), 'capital': capital, 'n_instructions': len(instructions), 'n_days': len(days),
            'metrics': m, 'series': rp._series(sim, capital), 'trades': trades, 'skipped': sorted(skipped, key=lambda x: x['line']),
            'final': {'cash': round(cash, 2), 'holdings': final_holdings, 'value': round(cash + sum(h['value'] for h in final_holdings), 2)},
            'realized_pnl': round(sum((t['pnl'] or 0) for t in trades), 2), 'costs': round(cost_sum, 2),
            'caveat': '指令日當天開盤市價成交（沒行情順延）；價格是還原價、持股含息，和 0050 含息對稱；手續費 0.0855%、賣出稅 0.3%、沒有滑價。這是「照你說的做會怎樣」，不是建議。'}


def run_text(text: str, start: date, end: date, capital: float = 1_000_000) -> dict:
    p = parse_instructions(text)
    if p['errors'] and not p['instructions']:
        return {'available': False, 'reason': '指令全部看不懂', 'errors': p['errors']}
    out = simulate(p['instructions'], start, end, capital)
    out['errors'] = p['errors']
    out['parsed'] = [{**it, 'date': str(it['date'])} for it in p['instructions']]
    return out
