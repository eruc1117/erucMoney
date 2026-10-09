"""
程式交易引擎（Iteration 58）：選股、進出場、停損、下單規則寫成程式，每天由排程跑；人只看結果。
────────────────────────────────────────────────────────────────────────────
規則（state.rules 可改，缺的用 RULES_DEFAULT）：
    選股      候選策略（portfolio_runs 的 run_id，預設 #44）每月 11 日起第一個交易日收盤算清單（沿用 portfolio_paper）
    進出場    清單出來那天收盤後產生調倉委託（不在清單的全賣、超過目標的賣超過部分、不足的買），下一個交易日開盤成交
    停損      每天收盤檢查：持股收盤 ≤ 成本 × (1 − stop_loss_pct) → 隔天全賣（stop_loss）；
              帳戶相對 0050 的回撤 ≤ −rel_dd_guard → 暫停新買單（guard），賣單照送
    下單      零股限價：買 = 收盤 × (1 + limit_slip)、賣 = 收盤 × (1 − limit_slip)；沒成交隔天用新收盤重掛，最多 max_attempts 次
    券商      paper（模擬帳戶，成交寫 portfolio_paper_trades）／kgi（接口在 brokers/kgi.py，尚未接）
每一步都寫 trading_events；委託單在 trading_orders 走 pending → filled／unfilled（重掛）／cancelled／rejected。

用法：
    python trading_engine.py --enable [--mode paper] [--broker paper] [--run-id 44]
    python trading_engine.py --disable
    python trading_engine.py --daily [--date 2026-10-14]
    python trading_engine.py --status
"""
import argparse
import json
import logging
import math
from datetime import date, datetime
from typing import Optional

import portfolio_paper as pp
import trading_rules as tr
from db.connection import get_conn

logger = logging.getLogger(__name__)

RULES_DEFAULT = tr.RULES_DEFAULT      # 規則本體在 trading_rules.py（引擎與回放共用）


# ── 狀態 ──────────────────────────────────────────────────────────────────────

def state() -> Optional[dict]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT enabled, mode, broker, run_id, rules, last_run_at, last_error FROM trading_engine_state WHERE id = 1")
            r = cur.fetchone()
    if not r:
        return None
    rules = {**RULES_DEFAULT, **(r[4] or {})}
    return {'enabled': r[0], 'mode': r[1], 'broker': r[2], 'run_id': r[3], 'rules': rules,
            'last_run_at': r[5].isoformat() if r[5] else None, 'last_error': r[6]}


def configure(enabled: Optional[bool] = None, mode: Optional[str] = None, broker: Optional[str] = None,
              run_id: Optional[int] = None, rules: Optional[dict] = None) -> dict:
    """開關與規則。live 模式一定配 kgi；paper 一定配 paper（模式和券商不能亂配）。"""
    if mode and mode not in ('paper', 'live'):
        raise ValueError('mode 只能是 paper 或 live')
    if mode == 'live':
        broker = 'kgi'
    if mode == 'paper':
        broker = 'paper'
    if broker and broker not in ('paper', 'kgi'):
        raise ValueError('broker 只能是 paper 或 kgi')
    if rules:
        bad = set(rules) - set(RULES_DEFAULT)
        if bad:
            raise ValueError(f'不認識的規則：{sorted(bad)}')
        for k, v in rules.items():
            if not isinstance(v, (int, float)) or v < 0:
                raise ValueError(f'規則 {k} 要是 ≥ 0 的數字')
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO trading_engine_state (id) VALUES (1) ON CONFLICT (id) DO NOTHING")
            cur.execute("SELECT rules FROM trading_engine_state WHERE id = 1")
            cur_rules = cur.fetchone()[0] or {}
            new_rules = {**cur_rules, **(rules or {})}
            cur.execute("""UPDATE trading_engine_state SET enabled = COALESCE(%s, enabled), mode = COALESCE(%s, mode), broker = COALESCE(%s, broker),
                           run_id = COALESCE(%s, run_id), rules = %s, updated_at = CURRENT_TIMESTAMP WHERE id = 1""",
                        (enabled, mode, broker, run_id, json.dumps(new_rules)))
        conn.commit()
    log_event('config', detail={'enabled': enabled, 'mode': mode, 'broker': broker, 'run_id': run_id, 'rules': rules})
    return state()


def _set_run(error: Optional[str]):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE trading_engine_state SET last_run_at = CURRENT_TIMESTAMP, last_error = %s WHERE id = 1", (error,))
        conn.commit()


def log_event(kind: str, stock_id: Optional[str] = None, detail: Optional[dict] = None):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO trading_events (kind, stock_id, detail) VALUES (%s, %s, %s)", (kind, stock_id, json.dumps(detail or {}, default=str)))
        conn.commit()


# ── 委託單 ────────────────────────────────────────────────────────────────────

def _insert_orders(rows: list) -> int:
    if not rows:
        return 0
    with get_conn() as conn:
        with conn.cursor() as cur:
            from psycopg2.extras import execute_values
            execute_values(cur, """INSERT INTO trading_orders (mode, broker, order_date, rebalance_date, stock_id, side, shares, limit_price, reason, note)
                                   VALUES %s""", rows)
        conn.commit()
    return len(rows)


def pending_orders(before: Optional[date] = None) -> list:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT id, order_date, rebalance_date, stock_id, side, shares, limit_price, reason, attempts
                           FROM trading_orders WHERE status = 'pending' AND (%s::date IS NULL OR order_date < %s) ORDER BY order_date, id""", (before, before))
            return [{'id': a, 'order_date': b, 'rebalance_date': c, 'stock_id': d, 'side': e, 'shares': f,
                     'limit_price': float(g) if g is not None else None, 'reason': h, 'attempts': i} for a, b, c, d, e, f, g, h, i in cur.fetchall()]


def lists_without_orders(since: date, today: date) -> list:
    """開戶後、今天以前（含）已算出但還沒產生委託的清單日期（舊的在前）。清單和持股相同時會留一筆 0 股的痕跡，不會每天重算。"""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT DISTINCT rebalance_date FROM portfolio_live_list l
                           WHERE rebalance_date >= %s AND rebalance_date <= %s
                             AND NOT EXISTS (SELECT 1 FROM trading_orders o WHERE o.rebalance_date = l.rebalance_date AND o.reason IN ('rebalance', 'exit'))
                           ORDER BY 1""", (since, today))
            return [r[0] for r in cur.fetchall()]


def orders_exist_for(rd: date) -> bool:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM trading_orders WHERE rebalance_date = %s AND reason IN ('rebalance', 'exit') LIMIT 1", (rd,))
            return cur.fetchone() is not None


def _limit(side: str, close: float, slip: float) -> float:
    return tr.limit_price(side, close, slip)


def gen_rebalance_orders(rd: date, st: dict, broker) -> dict:
    """清單 rd 收盤後：以 rd 的收盤估目標股數（成交在下一個交易日開盤）。同一份清單只產生一次。規則在 trading_rules.rebalance_orders。"""
    if orders_exist_for(rd):
        return {'rebalance_date': rd, 'orders': 0, 'skipped': 'already'}
    targets = dict(pp.load_list(rd))
    held = broker.positions()
    cash = broker.cash()
    ids = sorted(set(targets) | set(held))
    close = {s: pp.last_close(s, rd) for s in ids}
    for s in targets:
        if not close.get(s):
            log_event('no_quote', s, {'rebalance_date': str(rd)})
    guard = relative_drawdown_breached(rd, st)
    orders = tr.rebalance_orders(targets, held, cash, close, st['rules'], rd, rd, guard=guard)
    if guard:
        would_buy = tr.rebalance_orders(targets, held, cash, close, st['rules'], rd, rd, guard=False)
        skipped = sum(1 for o in would_buy if o['side'] == 'buy')
        if skipped:
            log_event('guard', detail={'rebalance_date': str(rd), 'skipped_buys': skipped, 'rule': 'rel_dd_guard'})
    rows = [(st['mode'], st['broker'], rd, rd, o['stock_id'], o['side'], o['shares'], o['limit_price'], o['reason'], None) for o in orders]
    n = _insert_orders(rows)
    if n == 0:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""INSERT INTO trading_orders (mode, broker, order_date, rebalance_date, stock_id, side, shares, reason, status, note)
                               VALUES (%s, %s, %s, %s, '-', 'buy', 0, 'rebalance', 'filled', '清單與持股相同，無委託')""", (st['mode'], st['broker'], rd, rd))
            conn.commit()
    log_event('orders', detail={'rebalance_date': str(rd), 'n': n, 'sell': sum(1 for r in rows if r[5] == 'sell'), 'buy': sum(1 for r in rows if r[5] == 'buy'), 'guard': guard})
    return {'rebalance_date': rd, 'orders': n, 'guard': guard}


def avg_costs() -> dict:
    """{stock_id: 平均成本}：只看模擬帳戶的買進（含手續費）。live 接上後改問券商。"""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT stock_id, SUM(gross + fee) / NULLIF(SUM(shares), 0) FROM portfolio_paper_trades
                           WHERE filled AND side = 'buy' AND stock_id <> '-' GROUP BY stock_id""")
            return {s: float(c) for s, c in cur.fetchall() if c is not None}


def gen_stop_loss_orders(d: date, st: dict, broker) -> list:
    """d 收盤：持股收盤 ≤ 成本 × (1 − stop_loss_pct) 就隔天全賣；已有待成交賣單的不重複。規則在 trading_rules.stop_loss_orders。"""
    held = broker.positions()
    if not held:
        return []
    costs = avg_costs()
    pend = {o['stock_id'] for o in pending_orders() if o['side'] == 'sell'}
    px = pp.day_prices(d, list(held))
    close = {s: px.get(s, {}).get('close') for s in held}
    orders = tr.stop_loss_orders(held, costs, close, st['rules'], d, pend)
    rows, hit = [], []
    for o in orders:
        rows.append((st['mode'], st['broker'], d, None, o['stock_id'], 'sell', o['shares'], o['limit_price'], 'stop_loss', o['note']))
        hit.append({'stock_id': o['stock_id'], 'close': o['close'], 'cost': o['cost'], 'shares': o['shares']})
        log_event('stop_loss', o['stock_id'], {'date': str(d), 'close': o['close'], 'cost': o['cost'], 'shares': o['shares']})
    _insert_orders(rows)
    return hit


def relative_drawdown_breached(d: date, st: dict) -> bool:
    """帳戶淨值對 0050 的相對回撤（從開戶起）是否超過 rel_dd_guard。"""
    r = pp.review()
    if not r or not r.get('days') or r.get('bench_return') is None:
        return False
    rel = (1 + r['port_return']) / (1 + r['bench_return']) - 1
    return rel <= -st['rules']['rel_dd_guard']


def send_pending(exec_date: date, st: dict, broker) -> dict:
    """把 order_date < exec_date 的待成交單送券商，依結果更新；未成交的重掛（新限價）或取消。"""
    orders = pending_orders(before=exec_date)
    if not orders:
        return {'sent': 0, 'filled': 0, 'unfilled': 0, 'cancelled': 0, 'rejected': 0}
    fills = broker.execute(orders, exec_date)
    by_id = {o['id']: o for o in orders}
    out = {'sent': len(orders), 'filled': 0, 'unfilled': 0, 'cancelled': 0, 'rejected': 0}
    with get_conn() as conn:
        with conn.cursor() as cur:
            for f in fills:
                o = by_id[f.order_id]
                if f.status == 'filled':
                    cur.execute("""UPDATE trading_orders SET status = 'filled', filled_shares = %s, filled_price = %s, filled_at = %s, broker_ref = %s,
                                   attempts = attempts + 1, note = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s""",
                                (f.filled_shares, f.filled_price, exec_date, f.broker_ref, f.note, f.order_id))
                    out['filled'] += 1
                    log_event('fill', o['stock_id'], {'order_id': o['id'], 'side': o['side'], 'shares': f.filled_shares, 'price': f.filled_price, 'date': str(exec_date), 'reason': o['reason']})
                elif f.status == 'rejected':
                    cur.execute("UPDATE trading_orders SET status = 'rejected', attempts = attempts + 1, note = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s", (f.note, f.order_id))
                    out['rejected'] += 1
                    log_event('rejected', o['stock_id'], {'order_id': o['id'], 'note': f.note})
                else:
                    nq = tr.requote(o, pp.last_close(o['stock_id'], exec_date), st['rules'], exec_date)   # 與回放同一份重掛／取消規則
                    if nq['status'] == 'cancelled':
                        cur.execute("UPDATE trading_orders SET status = 'cancelled', attempts = %s, note = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s",
                                    (nq['attempts'], f"{f.note}；重掛 {nq['attempts']} 次後取消", f.order_id))
                        out['cancelled'] += 1
                        log_event('cancelled', o['stock_id'], {'order_id': o['id'], 'attempts': nq['attempts'], 'note': f.note})
                    else:
                        cur.execute("""UPDATE trading_orders SET attempts = %s, order_date = %s, limit_price = %s, note = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s""",
                                    (nq['attempts'], exec_date, nq['limit_price'], f"{f.note}；重掛（第 {nq['attempts']} 次）", f.order_id))
                        out['unfilled'] += 1
                        log_event('unfilled', o['stock_id'], {'order_id': o['id'], 'attempts': nq['attempts'], 'note': f.note, 'new_limit': nq['limit_price']})
        conn.commit()
    return out


# ── 每日 ──────────────────────────────────────────────────────────────────────

def run_daily(today: Optional[date] = None) -> dict:
    """排程入口（取代紙上交易的 run_daily，當引擎開著時）。順序：送待成交單 → 結算 → 停損檢查 → 訊號日算清單與調倉單。可補跑。"""
    today = today or date.today()
    st = state()
    if not st or not st['enabled']:
        return {'skipped': '引擎未啟用（python trading_engine.py --enable）'}
    from brokers import make_broker, BrokerNotConfigured
    broker = make_broker(st['broker'])
    ok, why = broker.configured()
    if not ok:
        _set_run(why); log_event('error', detail={'where': 'broker', 'msg': why})
        return {'skipped': why}
    acct = pp.state()
    out = {'sent': [], 'marked': 0, 'stop_loss': [], 'new_list': None, 'orders': []}
    try:
        days = pp.market_days(acct['started_on'], today)
        if not days:
            _set_run(None); return {**out, 'skipped': '起始日到今天沒有行情'}
        # 1. 待成交單：每張在它 order_date 之後第一個有行情的日子成交
        for d in days:
            if pending_orders(before=d):
                r = send_pending(d, st, broker)
                if r['sent']:
                    out['sent'].append({'date': str(d), **r})
        # 2. 結算（紙上）
        if st['mode'] == 'paper':
            done = pp.marked_days()
            for d in days:
                if d not in done:
                    pp.mark(d); out['marked'] += 1
        # 3. 訊號日：清單＋調倉單（補跑：本月與上月）
        for y, m in ((today.year, today.month), ((today.year if today.month > 1 else today.year - 1), (today.month - 1) or 12)):
            sd = pp.signal_date_for_month(y, m, today)
            if sd and sd >= acct['started_on'] and not pp.list_exists(sd):
                r = pp.make_list(sd, st['run_id'] or acct['run_id'])
                out['new_list'] = {'rebalance_date': str(sd), 'n': r['n'], 'new': r['new']}
                log_event('signal', detail={'rebalance_date': str(sd), 'n': r['n'], 'new': r['new']})
        for rd in lists_without_orders(acct['started_on'], today):
            out['orders'].append(gen_rebalance_orders(rd, st, broker))
        # 4. 停損：今天（或最後一個有行情的日子）收盤檢查
        last = days[-1]
        out['stop_loss'] = gen_stop_loss_orders(last, st, broker)
        _set_run(None)
    except BrokerNotConfigured as e:
        _set_run(str(e)); log_event('error', detail={'where': 'broker', 'msg': str(e)}); out['error'] = str(e)
    except Exception as e:                                  # 記下來讓觀察頁看得到，再往上丟給排程器
        _set_run(f'{type(e).__name__}: {e}'); log_event('error', detail={'where': 'run_daily', 'msg': str(e)})
        raise
    return out


# ── 觀察與預測 ───────────────────────────────────────────────────────────────

def list_orders(limit: int = 200, status: Optional[str] = None) -> list:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT o.id, o.mode, o.broker, o.order_date, o.rebalance_date, o.stock_id, u.stock_name, o.side, o.shares, o.limit_price, o.reason,
                                  o.status, o.attempts, o.filled_shares, o.filled_price, o.filled_at, o.broker_ref, o.note, o.created_at
                           FROM trading_orders o LEFT JOIN market_universe u ON u.stock_id = o.stock_id
                           WHERE o.stock_id <> '-' AND (%s::text IS NULL OR o.status = %s) ORDER BY o.order_date DESC, o.id DESC LIMIT %s""", (status, status, limit))
            cols = ['id', 'mode', 'broker', 'order_date', 'rebalance_date', 'stock_id', 'stock_name', 'side', 'shares', 'limit_price', 'reason',
                    'status', 'attempts', 'filled_shares', 'filled_price', 'filled_at', 'broker_ref', 'note', 'created_at']
            out = []
            for r in cur.fetchall():
                d = dict(zip(cols, r))
                for k in ('order_date', 'rebalance_date', 'filled_at', 'created_at'):
                    d[k] = d[k].isoformat() if d[k] else None
                for k in ('limit_price', 'filled_price'):
                    d[k] = float(d[k]) if d[k] is not None else None
                out.append(d)
            return out


def list_events(limit: int = 100) -> list:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, ts, kind, stock_id, detail FROM trading_events ORDER BY ts DESC, id DESC LIMIT %s", (limit,))
            return [{'id': a, 'ts': b.isoformat(), 'kind': c, 'stock_id': d, 'detail': e} for a, b, c, d, e in cur.fetchall()]


def stop_loss_watch() -> list:
    """每檔持股：成本、最後收盤、停損價、距離停損還有多少。"""
    st = state()
    held = pp.holdings()
    if not held:
        return []
    costs = avg_costs()
    pct = (st or {'rules': RULES_DEFAULT})['rules']['stop_loss_pct']
    out = []
    today = date.today()
    for s, n in sorted(held.items()):
        c = pp.last_close(s, today); cost = costs.get(s)
        stop = cost * (1 - pct) if cost else None
        out.append({'stock_id': s, 'shares': n, 'cost': round(cost, 2) if cost else None, 'last': c, 'stop': round(stop, 2) if stop else None,
                    'pnl_pct': round(c / cost - 1, 4) if (c and cost) else None,
                    'to_stop_pct': round(c / stop - 1, 4) if (c and stop) else None})
    return out


def status() -> dict:
    st = state() or {'enabled': False, 'mode': 'paper', 'broker': 'paper', 'run_id': None, 'rules': RULES_DEFAULT, 'last_run_at': None, 'last_error': None}
    from brokers import make_broker
    ok, why = make_broker(st['broker']).configured()
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT status, count(*) FROM trading_orders WHERE stock_id <> '-' GROUP BY status")
            counts = {k: v for k, v in cur.fetchall()}
            cur.execute("SELECT max(rebalance_date) FROM portfolio_live_list")
            last_list = cur.fetchone()[0]
    acct = pp.state()
    today = date.today()
    nxt = next_signal_date(today)
    return {'engine': st, 'broker_ready': ok, 'broker_note': why, 'account': {**acct, 'started_on': str(acct['started_on'])} if acct else None,
            'orders': counts, 'last_list': str(last_list) if last_list else None, 'next_signal_date': str(nxt) if nxt else None,
            'rules_text': rules_text(st['rules']), 'watch': stop_loss_watch(), 'pending': pending_orders()}


def next_signal_date(today: date) -> date:
    """下一個訊號日（估）：本月 11 日起第一個平日還沒到就是它，過了就下個月；只避週末、不知道假日。"""
    def first_weekday(y, m):
        d = date(y, m, pp.SIGNAL_DAY)
        while d.weekday() >= 5:
            d = date.fromordinal(d.toordinal() + 1)
        return d
    d = first_weekday(today.year, today.month)
    if d >= today and not pp.signal_date_for_month(today.year, today.month, today):
        return d
    y, m = (today.year + 1, 1) if today.month == 12 else (today.year, today.month + 1)
    return first_weekday(y, m)


def rules_text(r: dict) -> dict:
    return {
        '選股': '候選策略（portfolio_runs 標記 candidate）每月 11 日起第一個交易日收盤算清單：流動性前 300、win3+mom 前 20 檔分三批輪動、台積電固定持 0050 權重',
        '進出場': '清單出來當天收盤後產生調倉委託（退出的全賣、超過目標的賣超過部分、不足的買），下一個交易日開盤成交',
        '停損': (f"持股收盤 ≤ 成本 × (1 − {r['stop_loss_pct']:.0%}) 隔天全賣" if 0 < r['stop_loss_pct'] < 1 else '個股停損關閉（回放顯示停損對月動能策略有害）')
               + f"；帳戶相對 0050 落後 {r['rel_dd_guard']:.0%} 暫停新買單",
        '下單': f"零股限價：買 = 收盤 × (1 + {r['limit_slip']:.1%})、賣 = 收盤 × (1 − {r['limit_slip']:.1%})；未成交隔天用新收盤重掛，最多 {int(r['max_attempts'])} 次",
    }


def _phi(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def forecast() -> dict:
    """預測交易結果：候選回測的年化主動報酬與追蹤誤差，推 1／3／6／12 個月的主動報酬期望、95% 區間、贏過 0050 的機率；
    加上從開戶起的「預期淨值帶」給觀察頁和實際淨值疊圖。假設月主動報酬近似常態、彼此獨立——這是近似，不是保證。"""
    acct = pp.state()
    st = state()
    run_id = (st or {}).get('run_id') or (acct or {}).get('run_id') or 44
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT metrics, name FROM portfolio_runs WHERE id = %s", (run_id,))
            r = cur.fetchone()
    m = (r[0] if r else {}) or {}
    ann, te = m.get('ann_active'), m.get('tracking_error')
    if ann is None or not te:
        return {'run_id': run_id, 'available': False, 'reason': '候選的 ann_active／tracking_error 不在 portfolio_runs.metrics'}
    horizons = []
    for h in (1, 3, 6, 12):
        mu = (1 + ann) ** (h / 12) - 1
        sd = te * math.sqrt(h / 12)
        horizons.append({'months': h, 'expected_active': round(mu, 4), 'sd': round(sd, 4), 'lo95': round(mu - 1.96 * sd, 4), 'hi95': round(mu + 1.96 * sd, 4),
                         'p_beat': round(_phi(mu / sd), 3) if sd > 0 else None})
    rv = pp.review() if acct else None
    band = []
    if acct:
        for k in range(0, 13):
            mu = (1 + ann) ** (k / 12) - 1; sd = te * math.sqrt(k / 12)
            band.append({'month': k, 'mid': round(1 + mu, 4), 'lo': round(1 + mu - 1.96 * sd, 4), 'hi': round(1 + mu + 1.96 * sd, 4)})
    actual = None
    if rv and rv.get('days') and rv.get('bench_return') is not None:
        months = max(1e-9, rv['days'] / 21)
        mu = (1 + ann) ** (months / 12) - 1; sd = te * math.sqrt(months / 12)
        z = (rv['active_return'] - mu) / sd if sd > 0 else None
        actual = {'days': rv['days'], 'months': round(months, 2), 'active_return': rv['active_return'], 'expected': round(mu, 4), 'sd': round(sd, 4),
                  'z': round(z, 2) if z is not None else None, 'within_band': (abs(z) <= 1.96) if z is not None else None}
    return {'run_id': run_id, 'run_name': r[1] if r else None, 'available': True,
            'inputs': {'ann_active': ann, 'tracking_error': te, 'info_ratio': m.get('info_ratio'), 'monthly_win_rate': m.get('monthly_win_rate'), 'dsr': m.get('dsr')},
            'horizons': horizons, 'band': band, 'actual': actual, 'started_on': str(acct['started_on']) if acct else None,
            'caveat': '月主動報酬假設近似常態且獨立；DSR 0.13 表示候選本身還不能排除運氣——預測是「如果回測成立會長這樣」，不是保證'}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--enable', action='store_true'); ap.add_argument('--disable', action='store_true')
    ap.add_argument('--mode', default=None); ap.add_argument('--broker', default=None); ap.add_argument('--run-id', type=int, default=None)
    ap.add_argument('--daily', action='store_true'); ap.add_argument('--date', default=None)
    ap.add_argument('--status', action='store_true')
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s')
    if a.enable or a.disable or a.mode or a.broker or a.run_id:
        print(configure(enabled=True if a.enable else (False if a.disable else None), mode=a.mode, broker=a.broker, run_id=a.run_id))
    if a.daily:
        print(run_daily(date.fromisoformat(a.date) if a.date else None))
    if a.status or not (a.enable or a.disable or a.daily):
        s = status()
        print(json.dumps({k: s[k] for k in ('engine', 'broker_ready', 'broker_note', 'orders', 'last_list', 'next_signal_date')}, ensure_ascii=False, indent=1, default=str))


if __name__ == '__main__':
    main()
