"""
程式交易回放（Iteration 59）：把引擎的整套規則（限價、重掛、停損、守門）套在過去的行情上，看「接上之後」會賺還是賠，
並和「照單全收」（紙上交易原本的成交方式：次日開盤、沒有限價、沒有停損）對照。

    replay(start, end, capital, rules, run_id=44) → {'variants': {'engine': …, 'plain': …}, …}

清單從候選回測存下的 portfolio_positions（run 44：2018-11-12 ～ 2024-09-11，每月一份目標權重）來，所以回放的範圍只能在候選的期間內；
保留期（2024-10 起）沒有清單，也不該在這裡偷開——超出範圍會被夾回去並在回應裡說明。
規則與引擎共用 trading_rules.py（同一份程式）；行情用 market_daily_prices、0050 還原收盤當對手。
"""
import json
import logging
import math
import time
from datetime import date, timedelta
from typing import Optional

import numpy as np
import pandas as pd

import portfolio_paper as pp
import trading_rules as tr
from db.connection import get_conn

logger = logging.getLogger(__name__)

_CACHE: dict = {}
CACHE_MAX = 16


def load_lists(run_id: int, start: date, end: date) -> dict:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT rebalance_date, stock_id, target_weight FROM portfolio_positions
                           WHERE run_id = %s AND rebalance_date BETWEEN %s AND %s ORDER BY rebalance_date, rank NULLS LAST""", (run_id, start, end))
            out = {}
            for rd, sid, w in cur.fetchall():
                out.setdefault(rd, {})[sid] = float(w)
    return out


def run_period(run_id: int) -> Optional[tuple]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT period_start, period_end, name FROM portfolio_runs WHERE id = %s", (run_id,))
            r = cur.fetchone()
    return (r[0], r[1], r[2]) if r else None


def load_prices(ids: list, start: date, end: date) -> dict:
    """{trade_date: {sid: {open, high, low, close, prev_close}}}，**還原價**：開高低收都乘上 adj_close ÷ close 的係數，
    持股才含息（除權息那天不會憑空掉一截），和對手 0050 的 adj_close 對稱；回測（portfolio_signal）也是用還原價。
    前收用每檔自己的上一筆（含 start 之前一筆）。沒有 adj_close 的列用原始價。"""
    with get_conn() as conn:
        df = pd.read_sql("""SELECT stock_id, trade_date, open_price, high_price, low_price, close_price, adj_close FROM market_daily_prices
                            WHERE stock_id = ANY(%s) AND trade_date BETWEEN %s AND %s ORDER BY stock_id, trade_date""",
                         conn, params=(list(ids), start - timedelta(days=15), end))
    if df.empty:
        return {}
    for c in ('open_price', 'high_price', 'low_price', 'close_price', 'adj_close'):
        df[c] = pd.to_numeric(df[c], errors='coerce')
    factor = (df['adj_close'] / df['close_price']).where((df['adj_close'] > 0) & (df['close_price'] > 0), 1.0)
    for c in ('open_price', 'high_price', 'low_price', 'close_price'):
        df[c] = df[c] * factor
    df['prev_close'] = df.groupby('stock_id')['close_price'].shift(1)
    df = df[df['trade_date'] >= start]
    out = {}
    f = lambda v: round(float(v), 4) if v == v and v else None
    for row in df.itertuples(index=False):
        out.setdefault(row.trade_date, {})[row.stock_id] = {'open': f(row.open_price), 'high': f(row.high_price), 'low': f(row.low_price),
                                                            'close': f(row.close_price), 'prev_close': f(row.prev_close)}
    return out


def load_bench(start: date, end: date) -> dict:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT trade_date, adj_close FROM stock_daily_prices WHERE stock_id = %s AND trade_date BETWEEN %s AND %s AND adj_close IS NOT NULL ORDER BY 1",
                        (pp.BENCH, start, end))
            return {d: float(c) for d, c in cur.fetchall()}


# ── 模擬 ──────────────────────────────────────────────────────────────────────

def _simulate(engine: bool, days: list, lists: dict, prices: dict, bench: dict, capital: float, rules: dict) -> dict:
    cash, held = float(capital), {}
    cost_total, cost_shares = {}, {}        # 平均成本（含手續費）
    pending = []
    last_close = {}
    nav_rows, trades, stop_losses = [], [], []
    stats = {'orders': 0, 'filled': 0, 'unfilled': 0, 'cancelled': 0, 'rejected': 0, 'stop_loss': 0, 'guard_days': 0, 'rebalances': 0}
    cost_sum = traded_sum = 0.0
    bench0 = None

    def avg_cost():
        return {s: cost_total[s] / cost_shares[s] for s in cost_shares if cost_shares[s] > 0}

    for d in days:
        px = prices.get(d, {})
        for s, p in px.items():
            if p.get('close'):
                last_close[s] = p['close']
        # 1. 送單：order_date < d 的
        todo = [o for o in pending if o['order_date'] < d]
        pending = [o for o in pending if o['order_date'] >= d]
        if todo:
            res = tr.fill_orders(todo, px, held, cash)
            held, cash = res['held'], res['cash']
            for f in res['fills']:
                o = f['order']
                if f['status'] == 'filled':
                    stats['filled'] += 1
                    sh, price = f['filled_shares'], f['filled_price']
                    traded_sum += f['gross']; cost_sum += f['fee'] + f['tax']
                    pnl = None
                    if o['side'] == 'buy':
                        cost_total[o['stock_id']] = cost_total.get(o['stock_id'], 0.0) + f['gross'] + f['fee']
                        cost_shares[o['stock_id']] = cost_shares.get(o['stock_id'], 0) + sh
                    else:
                        ac = (cost_total.get(o['stock_id'], 0.0) / cost_shares[o['stock_id']]) if cost_shares.get(o['stock_id']) else price
                        pnl = round((price - ac) * sh - f['fee'] - f['tax'], 2)
                        cost_total[o['stock_id']] = cost_total.get(o['stock_id'], 0.0) - ac * sh
                        cost_shares[o['stock_id']] = cost_shares.get(o['stock_id'], 0) - sh
                        if cost_shares[o['stock_id']] <= 0:
                            cost_total.pop(o['stock_id'], None); cost_shares.pop(o['stock_id'], None)
                    trades.append({'date': str(d), 'stock_id': o['stock_id'], 'side': o['side'], 'shares': sh, 'price': price, 'reason': o['reason'], 'pnl': pnl})
                    if o['reason'] == 'stop_loss':
                        stop_losses.append({'date': str(d), 'stock_id': o['stock_id'], 'shares': sh, 'cost': o.get('cost'), 'trigger_close': o.get('close'), 'sold': price, 'pnl': pnl})
                elif f['status'] == 'rejected':
                    stats['rejected'] += 1
                else:
                    if engine:
                        nq = tr.requote(o, last_close.get(o['stock_id']), rules, d)
                        if nq['status'] == 'cancelled':
                            stats['cancelled'] += 1
                        else:
                            stats['unfilled'] += 1; pending.append(nq)
                    else:
                        stats['cancelled'] += 1          # 照單全收：鎖死／沒行情就算了，和紙上交易一樣
        # 2. 結算
        value = sum(n * last_close.get(s, 0.0) for s, n in held.items())
        nav = cash + value
        b = bench.get(d)
        if b and bench0 is None:
            bench0 = b
        nav_rows.append((d, nav, cash, b))
        close_d = {s: last_close.get(s) for s in set(held) | set(lists.get(d, {}))}
        # 3. 訊號日：調倉單
        if d in lists:
            stats['rebalances'] += 1
            guard = False
            if engine and bench0 and b:
                rel = (nav / capital) / (b / bench0) - 1
                guard = rel <= -rules['rel_dd_guard']
            if guard:
                stats['guard_days'] += 1
            orders = tr.rebalance_orders(lists[d], held, cash, close_d, rules, d, d, guard=guard, slip=rules['limit_slip'] if engine else None)
            for o in orders:
                o['attempts'] = 0
            stats['orders'] += len(orders)
            pending += orders
        # 4. 停損
        if engine and held:
            pend_sell = {o['stock_id'] for o in pending if o['side'] == 'sell'}
            sl = tr.stop_loss_orders(held, avg_cost(), close_d, rules, d, pend_sell)
            for o in sl:
                o['attempts'] = 0
            stats['stop_loss'] += len(sl); stats['orders'] += len(sl)
            pending += sl
    return {'nav_rows': nav_rows, 'trades': trades, 'stop_losses': stop_losses, 'stats': stats, 'cost_sum': cost_sum, 'traded_sum': traded_sum,
            'held': held, 'cash': cash, 'avg_cost': avg_cost(), 'last_close': last_close}


def _max_drawdown(x: pd.Series) -> float:
    return float((x / x.cummax() - 1).min())


def _metrics(sim: dict, capital: float) -> dict:
    rows = [(d, nav, b) for d, nav, _, b in sim['nav_rows'] if b]
    if len(rows) < 2:
        return {}
    idx = pd.to_datetime([r[0] for r in rows])
    n = pd.Series([r[1] for r in rows], index=idx) / capital
    b = pd.Series([r[2] for r in rows], index=idx); b = b / b.iloc[0]
    years = len(n) / 252
    r_p, r_b = n.pct_change().dropna(), b.pct_change().dropna()
    act_d = (r_p - r_b).dropna()
    cagr_p = float(n.iloc[-1] ** (1 / years) - 1); cagr_b = float(b.iloc[-1] ** (1 / years) - 1)
    ann_active = (1 + cagr_p) / (1 + cagr_b) - 1
    te = float(act_d.std() * np.sqrt(252)) if len(act_d) > 1 else 0.0
    m_p = n.resample('ME').last().pct_change().dropna(); m_b = b.resample('ME').last().pct_change().dropna()
    m_act = (m_p - m_b).dropna()
    rel = (1 + act_d).cumprod()
    avg_nav = float((n * capital).mean())
    y_p = n.resample('YE').last(); y_b = b.resample('YE').last()
    y_p = pd.concat([pd.Series([1.0], index=[idx[0] - pd.Timedelta(days=1)]), y_p]); y_b = pd.concat([pd.Series([1.0], index=[idx[0] - pd.Timedelta(days=1)]), y_b])
    yearly = {str(k.year): round(float(v), 4) for k, v in ((y_p / y_p.shift(1)) / (y_b / y_b.shift(1)) - 1).dropna().items()}
    monthly = [{'month': k.strftime('%Y-%m'), 'port': round(float(m_p.get(k, 0)), 4), 'bench': round(float(m_b.get(k, 0)), 4), 'active': round(float(v), 4)} for k, v in m_act.items()]
    return {
        'start': str(idx[0].date()), 'end': str(idx[-1].date()), 'years': round(years, 2), 'months': len(m_act),
        'total_return': round(float(n.iloc[-1] - 1), 4), 'bench_return': round(float(b.iloc[-1] - 1), 4), 'active_return': round(float(n.iloc[-1] / b.iloc[-1] - 1), 4),
        'cagr_port': round(cagr_p, 4), 'cagr_bench': round(cagr_b, 4), 'ann_active': round(float(ann_active), 4),
        'tracking_error': round(te, 4), 'info_ratio': round(float(ann_active / te), 3) if te > 0 else None,
        'monthly_win_rate': round(float((m_p.reindex(m_act.index) > m_b.reindex(m_act.index)).mean()), 3) if len(m_act) else None,
        'mdd_port': round(_max_drawdown(n), 4), 'mdd_bench': round(_max_drawdown(b), 4), 'rel_mdd': round(_max_drawdown(rel), 4),
        'turnover_annual': round(sim['traded_sum'] / avg_nav / years, 2) if avg_nav and years else None,
        'cost_drag_annual': round(sim['cost_sum'] / avg_nav / years, 4) if avg_nav and years else None,
        'final_nav': round(float(n.iloc[-1] * capital), 2), 'yearly_active': yearly, 'monthly': monthly,
    }


def _series(sim: dict, capital: float, max_points: int = 400) -> list:
    rows = [r for r in sim['nav_rows'] if r[3]]
    if not rows:
        return []
    b0 = rows[0][3]
    step = max(1, len(rows) // max_points)
    picked = rows[::step]
    if picked[-1] is not rows[-1]:
        picked.append(rows[-1])
    return [{'d': str(d), 'nav': round(nav / capital, 4), 'bench': round(b / b0, 4), 'cash': round(c, 0)} for d, nav, c, b in picked]


def replay(start: date, end: date, capital: float = 1_000_000, rules: Optional[dict] = None, run_id: int = 44) -> dict:
    t0 = time.time()
    rules = {**tr.RULES_DEFAULT, **{k: v for k, v in (rules or {}).items() if k in tr.RULES_DEFAULT and v is not None}}
    key = json.dumps([str(start), str(end), capital, rules, run_id], sort_keys=True)
    if key in _CACHE:
        return {**_CACHE[key], 'cached': True}
    period = run_period(run_id)
    if not period:
        return {'available': False, 'reason': f'run {run_id} 不在 portfolio_runs'}
    p_start, p_end, run_name = period
    notes = []
    if end > p_end:
        notes.append(f'結束日 {end} 超過候選回測期間 {p_end}（保留期 2024-10 起沒有清單，也不在這裡開），已夾回 {p_end}')
        end = p_end
    if start < p_start:
        notes.append(f'起始日 {start} 早於候選期間 {p_start}，已夾回')
        start = p_start
    lists = load_lists(run_id, start, end)
    if not lists:
        return {'available': False, 'reason': f'{start} ～ {end} 沒有 run {run_id} 的清單（候選清單從 2018-11-12 起）', 'notes': notes}
    first_list = min(lists)
    if start < first_list:
        start = first_list
        notes.append(f'第一份清單是 {first_list}，回放從這天開始')
    days = pp.market_days(start, end)
    if len(days) < 2:
        return {'available': False, 'reason': '這段期間沒有全市場行情', 'notes': notes}
    ids = sorted({s for lst in lists.values() for s in lst})
    prices = load_prices(ids, start, end)
    bench = load_bench(start, end)
    variants = {}
    for name, engine in (('engine', True), ('plain', False)):
        sim = _simulate(engine, days, lists, prices, bench, capital, rules)
        m = _metrics(sim, capital)
        variants[name] = {'metrics': m, 'series': _series(sim, capital), 'stats': sim['stats'], 'cost_total': round(sim['cost_sum'], 2),
                          'traded_total': round(sim['traded_sum'], 2), 'n_trades': len(sim['trades']),
                          'stop_losses': sim['stop_losses'][-200:], 'stop_loss_pnl': round(sum((s['pnl'] or 0) for s in sim['stop_losses']), 2),
                          'last_holdings': len(sim['held']), 'trades_tail': sim['trades'][-60:]}
    e, p = variants['engine']['metrics'], variants['plain']['metrics']
    diff = {k: round(e[k] - p[k], 4) for k in ('total_return', 'active_return', 'ann_active', 'tracking_error', 'rel_mdd', 'cost_drag_annual', 'turnover_annual')
            if e.get(k) is not None and p.get(k) is not None}
    out = {'available': True, 'run_id': run_id, 'run_name': run_name, 'start': str(start), 'end': str(end), 'capital': capital, 'rules': rules,
           'n_lists': len(lists), 'n_days': len(days), 'n_stocks': len(ids), 'notes': notes, 'variants': variants, 'engine_minus_plain': diff,
           'computed_in_s': round(time.time() - t0, 2), 'cached': False,
           'caveat': '回放用候選回測存下的每月清單（含當時的台積電權重估計）與實際日線（還原價，持股含息，和 0050 含息對稱）；限價成交以隔天開盤對限價判斷，沒有盤中路徑、沒有流動性衝擊、沒有滑價。'
                     '「照單全收」= 紙上交易原本的成交方式。兩者差距主要來自停損與限價沒成交——這是規則的代價或好處，不是新的選股訊號。'}
    if len(_CACHE) >= CACHE_MAX:
        _CACHE.pop(next(iter(_CACHE)))
    _CACHE[key] = out
    return out


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--start', default='2018-11-12'); ap.add_argument('--end', default='2024-09-30')
    ap.add_argument('--capital', type=float, default=1_000_000); ap.add_argument('--run-id', type=int, default=44)
    ap.add_argument('--stop-loss', type=float, default=None); ap.add_argument('--slip', type=float, default=None)
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO)
    r = replay(date.fromisoformat(a.start), date.fromisoformat(a.end), a.capital, {'stop_loss_pct': a.stop_loss, 'limit_slip': a.slip}, a.run_id)
    if not r.get('available'):
        print(r); return
    for name in ('engine', 'plain'):
        m = r['variants'][name]['metrics']; s = r['variants'][name]['stats']
        print(f"{name:7s} 總報酬 {m['total_return'] * 100:+.1f}%（0050 {m['bench_return'] * 100:+.1f}%）年化主動 {m['ann_active'] * 100:+.2f}% IR {m['info_ratio']} "
              f"相對最大落後 {m['rel_mdd'] * 100:.1f}% 換手 {m['turnover_annual']} 成本 {m['cost_drag_annual'] * 100:.2f}%/年 | 委託 {s['orders']} 成交 {s['filled']} 重掛 {s['unfilled']} 取消 {s['cancelled']} 停損 {s['stop_loss']}")
    print('engine − plain:', r['engine_minus_plain'], '|', r['notes'], f"{r['computed_in_s']}s")


if __name__ == '__main__':
    main()
