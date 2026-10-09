"""
階段 4 紙上交易（Iteration 54）：候選策略的模擬帳戶
────────────────────────────────────────────────
規則與回測一模一樣，只是用真的、逐日進來的行情：
    訊號日  每月 11 日或之後第一個有行情的交易日，收盤後用候選參數算清單（portfolio_backtest.current_list，點時）
    成交    訊號日的次一交易日開盤價，整數股（零股），單邊手續費 0.0855%、賣出證交稅 0.3%；
            一字鎖漲跌停（高 = 低且相對前收 ≥ 9.5%）不成交，記 filled=false
    結算    每個交易日收盤：淨值 = 現金 + 持股市值；0050 還原收盤同列存，對 0050 的主動報酬從這裡算
    檢討    從起始日起：總報酬、0050、主動報酬、逐月主動報酬，對照回測候選的月主動報酬分布
每天 18:40 由 scheduler.job_portfolio_paper 跑 run_daily(today)：先成交上一個清單 → 結算 → 若今天是訊號日就算新清單。
漏跑幾天也沒關係：每一步都以「該日是否已處理」判斷，補跑會按日期順序補齊。

用法：
    python portfolio_paper.py --start [--capital 1000000] [--run-id 44]   # 開戶（只能一次）
    python portfolio_paper.py --daily [--date 2026-10-14]                  # 跑一天（排程用）
    python portfolio_paper.py --status
"""

import argparse
import logging
import math
from datetime import date, timedelta
from typing import Optional

from db.connection import get_conn

logger = logging.getLogger(__name__)

FEE_RATE = 0.000855
TAX_RATE = 0.003
LIMIT_LOCK = 0.095
SIGNAL_DAY = 11
BENCH = '0050'
TSMC = '2330'


# ── 狀態 ──────────────────────────────────────────────────────────────────────

def state() -> Optional[dict]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT started_on, start_capital, cash, run_id FROM portfolio_paper_state WHERE id = 1")
            r = cur.fetchone()
    return None if not r else {'started_on': r[0], 'start_capital': float(r[1]), 'cash': float(r[2]), 'run_id': r[3]}


def start(capital: float = 1_000_000, run_id: int = 44, started_on: Optional[date] = None) -> dict:
    """開戶：全現金。已開過就拒絕（不能重來，否則紙上交易就不是紙上交易）。"""
    if state():
        raise RuntimeError('模擬帳戶已經開了；要重來請手動清三張 portfolio_paper_* 表，並在文件記下理由')
    started_on = started_on or date.today()
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO portfolio_paper_state (id, started_on, start_capital, cash, run_id) VALUES (1, %s, %s, %s, %s)",
                        (started_on, capital, capital, run_id))
        conn.commit()
    logger.info('[paper] 開戶：%s 起、資金 %.0f、候選 run %s', started_on, capital, run_id)
    return state()


def holdings(as_of: Optional[date] = None) -> dict:
    """{stock_id: shares}，由成交紀錄重放（只算 filled）；as_of 給了就只算該日（含）以前的成交——補結算過去的日子要用。"""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT stock_id, SUM(CASE WHEN side = 'buy' THEN shares ELSE -shares END) FROM portfolio_paper_trades
                           WHERE filled AND stock_id <> '-' AND (%s::date IS NULL OR trade_date <= %s)
                           GROUP BY stock_id HAVING SUM(CASE WHEN side = 'buy' THEN shares ELSE -shares END) <> 0""", (as_of, as_of))
            return {s: int(n) for s, n in cur.fetchall()}


def cash_as_of(d: date) -> float:
    """該日收盤時的現金 = 起始資金 + 賣出淨收 − 買進支出（只算 filled、trade_date ≤ d）。"""
    st = state()
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT COALESCE(SUM(CASE WHEN side = 'sell' THEN gross - fee - tax ELSE -(gross + fee) END), 0)
                           FROM portfolio_paper_trades WHERE filled AND stock_id <> '-' AND trade_date <= %s""", (d,))
            flow = float(cur.fetchone()[0])
    return round(st['start_capital'] + flow, 2)


# ── 行情 ──────────────────────────────────────────────────────────────────────

def market_days(start: date, end: date) -> list:
    """有全市場行情的日子（market_daily_prices 列數 ≥ 500 才算一個交易日）。"""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT trade_date FROM market_daily_prices WHERE trade_date BETWEEN %s AND %s
                           GROUP BY 1 HAVING count(*) >= 500 ORDER BY 1""", (start, end))
            return [r[0] for r in cur.fetchall()]


def day_prices(d: date, ids: list) -> dict:
    """{stock_id: {open, high, low, close, prev_close}}；0050 從 stock_daily_prices（還原價）來。"""
    if not ids:
        return {}
    out = {}
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT m.stock_id, m.open_price, m.high_price, m.low_price, m.close_price,
                                  (SELECT close_price FROM market_daily_prices p WHERE p.stock_id = m.stock_id AND p.trade_date < m.trade_date
                                   ORDER BY p.trade_date DESC LIMIT 1)
                           FROM market_daily_prices m WHERE m.trade_date = %s AND m.stock_id = ANY(%s)""", (d, list(ids)))
            for sid, o, h, l, c, pc in cur.fetchall():
                out[sid] = {'open': float(o) if o else None, 'high': float(h) if h else None, 'low': float(l) if l else None,
                            'close': float(c) if c else None, 'prev_close': float(pc) if pc else None}
    return out


def bench_close(d: date) -> Optional[float]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT adj_close FROM stock_daily_prices WHERE stock_id = %s AND trade_date = %s", (BENCH, d))
            r = cur.fetchone()
    return float(r[0]) if r and r[0] else None


def last_close(sid: str, d: date) -> Optional[float]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT close_price FROM market_daily_prices WHERE stock_id = %s AND trade_date <= %s ORDER BY trade_date DESC LIMIT 1", (sid, d))
            r = cur.fetchone()
    return float(r[0]) if r and r[0] else None


# ── 訊號日與清單 ──────────────────────────────────────────────────────────────

def signal_date_for_month(y: int, m: int, today: date) -> Optional[date]:
    """該月 11 日起第一個有行情的交易日（≤ today）；還沒到就 None。"""
    days = market_days(date(y, m, SIGNAL_DAY), min(today, date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1)))
    return days[0] if days else None


def list_exists(rebalance_date: date) -> bool:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM portfolio_live_list WHERE rebalance_date = %s LIMIT 1", (rebalance_date,))
            return cur.fetchone() is not None


def make_list(rebalance_date: date, run_id: int) -> dict:
    import portfolio_backtest as pb
    return pb.current_list(run_id, as_of=rebalance_date)


def load_list(rebalance_date: date) -> list:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT stock_id, target_weight FROM portfolio_live_list WHERE rebalance_date = %s ORDER BY rank NULLS LAST, stock_id", (rebalance_date,))
            return [(s, float(w)) for s, w in cur.fetchall()]


def pending_lists(today: date) -> list:
    """已算出、還沒成交、訊號日 < today 的清單日期（舊的在前）。"""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT DISTINCT rebalance_date FROM portfolio_live_list l
                           WHERE rebalance_date < %s AND NOT EXISTS (SELECT 1 FROM portfolio_paper_trades t WHERE t.rebalance_date = l.rebalance_date)
                           ORDER BY 1""", (today,))
            return [r[0] for r in cur.fetchall()]


# ── 成交 ──────────────────────────────────────────────────────────────────────

def fill(rebalance_date: date, exec_date: date) -> dict:
    """照清單在 exec_date 開盤成交：先賣後買、整數股、現金不夠按比例縮；一字鎖死不成交。"""
    st = state()
    targets = dict(load_list(rebalance_date))
    held = holdings()
    ids = sorted(set(targets) | set(held))
    px = day_prices(exec_date, ids)
    cash = st['cash']
    nav_open = cash + sum(n * (px.get(s, {}).get('open') or last_close(s, exec_date) or 0.0) for s, n in held.items())
    rows, unfilled = [], []

    def locked(p):
        return p and p['high'] is not None and p['high'] == p['low'] and p['prev_close'] and abs(p['open'] / p['prev_close'] - 1) >= LIMIT_LOCK

    # 賣：不在清單裡的全賣；在清單裡但超過目標的賣掉超過的部分
    for s, n in held.items():
        p = px.get(s)
        if not p or not p['open']:
            continue                     # 沒行情（停牌）：留著，下次再說
        target_val = targets.get(s, 0.0) * nav_open
        cur_val = n * p['open']
        if cur_val - target_val < p['open']:
            continue                     # 差不到一股
        sell = n if s not in targets else int(math.floor((cur_val - target_val) / p['open']))
        if sell <= 0:
            continue
        gross = sell * p['open']
        if locked(p):
            rows.append((rebalance_date, exec_date, s, 'sell', sell, p['open'], gross, 0, 0, False, '一字鎖死未成交'))
            unfilled.append(s)
            continue
        fee, tax = round(gross * FEE_RATE, 2), round(gross * TAX_RATE, 2)
        cash += gross - fee - tax
        rows.append((rebalance_date, exec_date, s, 'sell', sell, p['open'], gross, fee, tax, True, None))
        held[s] = n - sell
    # 買：先算需要多少，現金不夠按比例縮
    buys = []
    for s, w in targets.items():
        p = px.get(s)
        if not p or not p['open']:
            continue
        target_val = w * nav_open
        cur_val = held.get(s, 0) * p['open']
        if target_val - cur_val < p['open']:
            continue
        buys.append((s, target_val - cur_val, p))
    need = sum(v * (1 + FEE_RATE) for _, v, _ in buys)
    scale = min(1.0, cash / need) if need > 0 else 1.0
    for s, val, p in buys:
        shares = int(math.floor(val * scale / p['open']))
        if shares <= 0:
            continue
        gross = shares * p['open']
        if locked(p):
            rows.append((rebalance_date, exec_date, s, 'buy', shares, p['open'], gross, 0, 0, False, '一字鎖死未成交'))
            unfilled.append(s)
            continue
        fee = round(gross * FEE_RATE, 2)
        if gross + fee > cash:
            shares = int(math.floor(cash / (p['open'] * (1 + FEE_RATE))))
            if shares <= 0:
                continue
            gross = shares * p['open']; fee = round(gross * FEE_RATE, 2)
        cash -= gross + fee
        rows.append((rebalance_date, exec_date, s, 'buy', shares, p['open'], gross, fee, 0, True, None))
    with get_conn() as conn:
        with conn.cursor() as cur:
            from psycopg2.extras import execute_values
            if rows:
                execute_values(cur, """INSERT INTO portfolio_paper_trades (rebalance_date, trade_date, stock_id, side, shares, price, gross, fee, tax, filled, note)
                                       VALUES %s""", rows)
            else:
                # 清單和持股一樣、沒有任何單：也要留一筆痕跡，否則這份清單會一直被當成「還沒成交」
                cur.execute("""INSERT INTO portfolio_paper_trades (rebalance_date, trade_date, stock_id, side, shares, price, gross, fee, tax, filled, note)
                               VALUES (%s, %s, '-', 'buy', 0, 0, 0, 0, 0, TRUE, '清單與持股相同，無交易')""", (rebalance_date, exec_date))
            cur.execute("UPDATE portfolio_paper_state SET cash = %s, updated_at = CURRENT_TIMESTAMP WHERE id = 1", (round(cash, 2),))
        conn.commit()
    n_buy = sum(1 for r in rows if r[3] == 'buy' and r[9]); n_sell = sum(1 for r in rows if r[3] == 'sell' and r[9])
    logger.info('[paper] %s 清單於 %s 成交：買 %d、賣 %d、未成交 %d，現金 %.0f', rebalance_date, exec_date, n_buy, n_sell, len(unfilled), cash)
    return {'rebalance_date': rebalance_date, 'exec_date': exec_date, 'buys': n_buy, 'sells': n_sell,
            'unfilled': unfilled, 'cash': round(cash, 2)}


# ── 結算 ──────────────────────────────────────────────────────────────────────

def mark(d: date) -> dict:
    """該日收盤結算：持股與現金都以該日為準（補跑過去的日子才不會用到之後的成交）。"""
    held = holdings(d)
    cash = cash_as_of(d)
    px = day_prices(d, list(held))
    value = sum(n * (px.get(s, {}).get('close') or last_close(s, d) or 0.0) for s, n in held.items())
    nav = cash + value
    b = bench_close(d)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO portfolio_paper_nav (trade_date, nav, cash, bench_close, n_holdings) VALUES (%s, %s, %s, %s, %s)
                           ON CONFLICT (trade_date) DO UPDATE SET nav = EXCLUDED.nav, cash = EXCLUDED.cash, bench_close = EXCLUDED.bench_close, n_holdings = EXCLUDED.n_holdings""",
                        (d, round(nav, 2), cash, b, len(held)))
        conn.commit()
    return {'date': d, 'nav': round(nav, 2), 'cash': cash, 'bench': b, 'n_holdings': len(held)}


def marked_days() -> set:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT trade_date FROM portfolio_paper_nav")
            return {r[0] for r in cur.fetchall()}


# ── 每日 ──────────────────────────────────────────────────────────────────────

def run_daily(today: Optional[date] = None) -> dict:
    """排程入口。順序：成交待成交的清單 → 結算到今天 → 今天若是訊號日就算清單。全部可補跑。"""
    today = today or date.today()
    st = state()
    if not st:
        return {'skipped': '模擬帳戶還沒開（python portfolio_paper.py --start）'}
    out = {'filled': [], 'marked': 0, 'new_list': None}
    days = market_days(st['started_on'], today)
    if not days:
        out['skipped'] = '起始日到今天沒有行情'
        return out
    # 1. 成交：每一份待成交清單，在它之後第一個有行情的日子開盤成交
    for rd in pending_lists(today):
        later = [x for x in days if x > rd]
        if not later:
            continue
        out['filled'].append(fill(rd, later[0]))
    # 2. 結算：起始日起每個有行情、還沒結算的日子
    done = marked_days()
    for d in days:
        if d not in done:
            mark(d); out['marked'] += 1
    # 3. 訊號日：本月（與上月，補跑用）11 日起第一個交易日，還沒有清單就算
    for y, m in ((today.year, today.month), ((today.year if today.month > 1 else today.year - 1), (today.month - 1) or 12)):
        sd = signal_date_for_month(y, m, today)
        if sd and sd >= st['started_on'] and not list_exists(sd):
            r = make_list(sd, st['run_id'])
            out['new_list'] = {'rebalance_date': str(sd), 'n': r['n'], 'new': r['new']}
            logger.info('[paper] 訊號日 %s 清單 %d 檔（新進 %s）', sd, r['n'], r['new'])
    return out


# ── 檢討 ──────────────────────────────────────────────────────────────────────

def review() -> Optional[dict]:
    """起始日起：總報酬、0050、主動報酬、逐月主動報酬；對照候選回測的月主動報酬。"""
    st = state()
    if not st:
        return None
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT trade_date, nav, cash, bench_close, n_holdings FROM portfolio_paper_nav ORDER BY 1")
            rows = cur.fetchall()
            cur.execute("SELECT metrics FROM portfolio_runs WHERE id = %s", (st['run_id'],))
            m = cur.fetchone()
            bt = (m[0] if m else {}) or {}
    if not rows:
        return {'state': st, 'days': 0}
    first_b = next((float(b) for _, _, _, b, _ in rows if b), None)
    nav0 = st['start_capital']
    series = [{'d': str(d), 'nav': float(n) / nav0, 'bench': (float(b) / first_b) if (b and first_b) else None, 'cash': float(c), 'n': k}
              for d, n, c, b, k in rows]
    last = series[-1]
    port_ret = last['nav'] - 1
    bench_ret = (last['bench'] - 1) if last['bench'] is not None else None
    # 逐月：月底淨值
    by_month = {}
    for p in series:
        by_month[p['d'][:7]] = p
    months = sorted(by_month)
    monthly = []
    prev = {'nav': 1.0, 'bench': 1.0}
    for mkey in months:
        p = by_month[mkey]
        if p['bench'] is None:
            continue
        r_p, r_b = p['nav'] / prev['nav'] - 1, p['bench'] / prev['bench'] - 1
        monthly.append({'month': mkey, 'port': round(r_p, 4), 'bench': round(r_b, 4), 'active': round(r_p - r_b, 4)})
        prev = p
    expected = {'ann_active': bt.get('ann_active'), 'monthly_win_rate': bt.get('monthly_win_rate'), 'tracking_error': bt.get('tracking_error'),
                'monthly_active_mean': (round((1 + bt['ann_active']) ** (1 / 12) - 1, 4) if bt.get('ann_active') is not None else None)}
    return {'state': st, 'days': len(series), 'since': series[0]['d'], 'as_of': last['d'], 'port_return': round(port_ret, 4),
            'bench_return': round(bench_ret, 4) if bench_ret is not None else None,
            'active_return': round(port_ret - bench_ret, 4) if bench_ret is not None else None,
            'nav': round(float(rows[-1][1]), 2), 'cash': round(float(rows[-1][2]), 2), 'n_holdings': rows[-1][4],
            'monthly': monthly, 'expected': expected, 'series': series[::max(1, len(series) // 300)]}


def status() -> str:
    st = state()
    if not st:
        return '模擬帳戶還沒開'
    r = review()
    return (f"模擬帳戶 {st['started_on']} 起、資金 {st['start_capital']:,.0f}、現金 {st['cash']:,.0f}；結算 {r.get('days', 0)} 日"
            + (f"；淨值 {r['nav']:,.0f}（{r['port_return'] * 100:+.2f}%，0050 {(r['bench_return'] or 0) * 100:+.2f}%）" if r.get('days') else ''))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--start', action='store_true'); ap.add_argument('--capital', type=float, default=1_000_000); ap.add_argument('--run-id', type=int, default=44)
    ap.add_argument('--daily', action='store_true'); ap.add_argument('--date', default=None)
    ap.add_argument('--status', action='store_true')
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s')
    if a.start:
        print(start(a.capital, a.run_id))
    if a.daily:
        print(run_daily(date.fromisoformat(a.date) if a.date else None))
    if a.status or a.start or a.daily:
        print(status())


if __name__ == '__main__':
    main()
