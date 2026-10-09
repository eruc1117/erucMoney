"""
月調倉回測（Iteration 49，打敗大盤計畫階段 2）
────────────────────────────────────────────
給定訊號，模擬「每月 11 日收盤算訊號、次一交易日開盤以限價單成交、持有到下次調倉」的做多組合，
對手是 0050（含息，adj_close）。所有指標都算在主動報酬（組合減 0050）上。

機制：
    成交價  次一交易日開盤（adj_open = open × adj_close ÷ close，與還原價同一基準）
    成本    單邊手續費 0.0855% + 賣出證交稅 0.3% + 單邊滑價 0.15%（流動性 200 名以後 0.3%）
    未成交  成交日一字鎖漲跌停（高 = 低且相對前收 ≥ 9.5%）的單不成交，資金留現金、持股照舊
    下市    持股沒有價格超過 30 個交易日 → 以最後一個收盤強制平倉（含成本）
    股利    adj_close 已含息（再投入），與 0050 同一基準
    緩衝    上期持股仍在前 40 名就不賣（年換手從約 12 倍壓到 4~6 倍）
資料三段：dev 2018-01~2021-12、valid 2022-01~2024-09、holdout 2024-10~（只能看一次，--holdout-once 才跑）。
每次 run 寫 portfolio_runs（experiment_n 全域遞增）＋ portfolio_positions；DSR 用日誌裡的 N 與各版本月 Sharpe 變異數。

用法：
    python portfolio_backtest.py --signal sue --segment dev
    python portfolio_backtest.py --signal win --segment dev --tsmc-weight 0.0 --notes "第一版"
    python portfolio_backtest.py --signal ar0 --segment valid
    python portfolio_backtest.py --list            # 實驗日誌
"""

import argparse
import json
import logging
from datetime import date, datetime
from typing import Optional

import numpy as np
import pandas as pd

from db.connection import get_conn
import dsr as dsr_mod
import portfolio_signal as ps

logger = logging.getLogger(__name__)

COSTS = {'fee': 0.000855, 'tax': 0.003, 'slip': 0.0015, 'slip_small': 0.003, 'small_rank': 200}
SEGMENTS = {'dev': (date(2018, 1, 1), date(2021, 12, 31)),
            'valid': (date(2022, 1, 1), date(2024, 9, 30)),
            'holdout': (date(2024, 10, 1), None)}
FORCE_LIQ_DAYS = 30
RESULTS_DIR = None   # main() 設成 UnifiedModel/results


# ── 模擬 ──────────────────────────────────────────────────────────────────────

def simulate(mkt: ps.Market, sur: pd.DataFrame, signal: str, start: date, end: date, top_n: int = 20, buffer: int = 40,
             universe_n: int = 300, excl_limit_pct: float = 0.10, tsmc_weight: Optional[float] = None,
             costs: dict = COSTS, tranches: int = 1, weighting: str = 'equal') -> dict:
    schedule = ps.rebalance_schedule(mkt, start, end)
    if not schedule:
        raise RuntimeError('期間內沒有任何調倉日')
    first_exec = schedule[0][1]
    days = [pd.Timestamp(x) for x in mkt.days if first_exec <= pd.Timestamp(x) <= pd.Timestamp(end)]
    exec_map = {e: s for s, e in schedule}

    cash, units = 1.0, {}               # units：以還原價計的單位數，value = units × adj
    last_px, last_seen = {}, {}
    nav, positions, trades = [], [], []
    cost_total, traded_total = 0.0, 0.0
    holdings_order: list = []
    skipped: list = []
    tranche_queue: list = []            # 分批模式：每個月進場的那批名單，滿 tranches 批就把最舊的賣掉
    tsmc_log: list = []                 # 每次調倉用的台積電權重（'est' 時是估計值）

    def price_row(frame, d):
        return frame.loc[d]

    for d in days:
        adj_row = price_row(mkt.adj, d)
        if d in exec_map:
            s = exec_map[d]
            ids = ps.eligible(mkt, s, universe_n, excl_limit_pct)
            scores = ps.scores_on(signal, mkt, sur, s, ids)
            if len(scores) < (top_n if tranches == 1 else max(1, top_n // tranches)):
                # 這個月訊號不足（例如 AR₀ 在沒有精確公告日的年份）：不調倉、照舊持有，不算一次換手
                skipped.append(s.date())
                nav_val = cash + sum(u * (adj_row.get(sid) if pd.notna(adj_row.get(sid, np.nan)) else last_px.get(sid, 0.0)) for sid, u in units.items())
                nav.append((d, nav_val))
                continue
            liq_s = mkt.liq.loc[s] if weighting == 'liq' else None
            if tsmc_weight == 'est':
                w_tsmc = ps.estimate_tsmc_weight(mkt, s)
                w_tsmc = ps.TSMC_WEIGHT_FALLBACK if w_tsmc is None else w_tsmc
            else:
                w_tsmc = tsmc_weight
            tsmc_log.append((s.date(), w_tsmc))
            if tranches > 1:
                release = tranche_queue.pop(0) if len(tranche_queue) >= tranches else []
                held_now = [sid for sid in holdings_order if sid in units]
                targets = ps.build_targets(scores, held_now, top_n, buffer, w_tsmc, weighting, liq_s,
                                           tranche_new=max(1, top_n // tranches), release=release)
                prev_set = set(held_now) - set(release)
                tranche_queue.append([sid for sid in targets['stock_id'] if sid not in prev_set and sid != ps.TSMC])
            else:
                targets = ps.build_targets(scores, holdings_order, top_n, buffer, w_tsmc, weighting, liq_s)
            open_row = price_row(mkt.adj_open, d)
            locked_row = price_row(mkt.locked, d)
            liq_rank = mkt.liq.loc[s].rank(ascending=False)
            # 以今天開盤價估值
            held_val = {sid: u * (open_row.get(sid) if pd.notna(open_row.get(sid, np.nan)) else last_px.get(sid, 0.0)) for sid, u in units.items()}
            nav_open = cash + sum(held_val.values())
            tgt = {r.stock_id: r.target_weight * nav_open for r in targets.itertuples(index=False)}
            filled = {}
            # 先賣
            for sid in list(units):
                want = tgt.get(sid, 0.0)
                cur = held_val.get(sid, 0.0)
                px = open_row.get(sid, np.nan)
                if cur - want <= 1e-12 or pd.isna(px) or px <= 0:
                    continue
                if bool(locked_row.get(sid, False)):
                    filled[sid] = False
                    continue
                sell_val = cur - want
                slip = costs['slip_small'] if liq_rank.get(sid, 1e9) > costs['small_rank'] else costs['slip']
                proceeds = sell_val * (1 - costs['fee'] - costs['tax'] - slip)
                cost_total += sell_val - proceeds
                traded_total += sell_val
                cash += proceeds
                units[sid] -= sell_val / px
                if units[sid] <= 1e-12 or want <= 0:
                    units.pop(sid, None)
                trades.append((d, sid, 'sell', sell_val))
            # 再買（現金不夠就按比例縮）
            buys = {}
            for sid, want in tgt.items():
                cur = units.get(sid, 0.0) * open_row.get(sid, np.nan) if sid in units else 0.0
                cur = 0.0 if pd.isna(cur) else cur
                px = open_row.get(sid, np.nan)
                if want - cur <= 1e-12 or pd.isna(px) or px <= 0:
                    continue
                if bool(locked_row.get(sid, False)):
                    filled[sid] = False
                    continue
                slip = costs['slip_small'] if liq_rank.get(sid, 1e9) > costs['small_rank'] else costs['slip']
                buys[sid] = (want - cur, px, slip)
            need = sum(v * (1 + costs['fee'] + sl) for v, _, sl in buys.values())
            scale = min(1.0, cash / need) if need > 0 else 1.0        # 現金不夠（成本吃掉的那一點）就全部按比例縮
            for sid, (val, px, slip) in buys.items():
                val *= scale
                outlay = val * (1 + costs['fee'] + slip)
                if outlay > cash:
                    val = cash / (1 + costs['fee'] + slip)
                    outlay = cash
                cost_total += outlay - val
                traded_total += val
                cash -= outlay
                units[sid] = units.get(sid, 0.0) + val / px
                filled.setdefault(sid, True)
                trades.append((d, sid, 'buy', val))
            holdings_order = [sid for sid in targets['stock_id'] if sid in units and sid != ps.TSMC]
            for r in targets.itertuples(index=False):
                positions.append({'rebalance_date': s.date(), 'exec_date': d.date(), 'stock_id': r.stock_id, 'rank': r.rank,
                                  'signal_value': r.signal_value, 'target_weight': r.target_weight, 'filled': filled.get(r.stock_id, True)})
        # 收盤估值；沒價格的沿用最後價，太久沒價格就強制平倉
        value = 0.0
        for sid in list(units):
            px = adj_row.get(sid, np.nan)
            if pd.notna(px) and px > 0:
                last_px[sid], last_seen[sid] = px, d
            elif sid in last_seen and (np.searchsorted(mkt.days, np.datetime64(d)) - np.searchsorted(mkt.days, np.datetime64(last_seen[sid]))) > FORCE_LIQ_DAYS:
                val = units[sid] * last_px[sid]
                proceeds = val * (1 - costs['fee'] - costs['tax'] - costs['slip_small'])
                cost_total += val - proceeds
                cash += proceeds
                units.pop(sid)
                trades.append((d, sid, 'forced_sell', val))
                continue
            value += units[sid] * last_px.get(sid, 0.0)
        nav.append((d, cash + value))

    nav = pd.Series(dict(nav)).sort_index()
    return {'nav': nav, 'positions': pd.DataFrame(positions), 'trades': trades, 'cost_total': cost_total,
            'traded_total': traded_total, 'n_rebalances': len(schedule) - len(skipped), 'skipped': skipped, 'schedule': schedule,
            'tsmc_log': tsmc_log}


# ── 指標 ──────────────────────────────────────────────────────────────────────

def _max_drawdown(x: pd.Series) -> float:
    peak = x.cummax()
    return float((x / peak - 1).min())


def metrics(nav: pd.Series, bench: pd.Series, sim: dict) -> dict:
    b = bench.reindex(nav.index).ffill()
    b = b / b.iloc[0]
    n = nav / nav.iloc[0]
    years = len(n) / 252
    r_p, r_b = n.pct_change().dropna(), b.pct_change().dropna()
    active_d = (r_p - r_b).dropna()
    cagr_p = n.iloc[-1] ** (1 / years) - 1
    cagr_b = b.iloc[-1] ** (1 / years) - 1
    ann_active = (1 + cagr_p) / (1 + cagr_b) - 1
    te = float(active_d.std() * np.sqrt(252))
    m_p = n.resample('ME').last().pct_change().dropna()
    m_b = b.resample('ME').last().pct_change().dropna()
    m_act = (m_p - m_b).dropna()
    rel = (1 + active_d).cumprod()
    avg_nav = float(nav.mean())
    return {
        'start': str(n.index[0].date()), 'end': str(n.index[-1].date()), 'years': round(years, 2), 'months': int(len(m_act)),
        'cagr_port': round(float(cagr_p), 4), 'cagr_bench': round(float(cagr_b), 4), 'ann_active': round(float(ann_active), 4),
        'tracking_error': round(te, 4), 'info_ratio': round(float(ann_active / te), 3) if te > 0 else None,
        'sharpe_m_active': round(dsr_mod.sharpe(list(m_act.values)), 4),
        'monthly_win_rate': round(float((m_p.reindex(m_act.index) > m_b.reindex(m_act.index)).mean()), 3),
        'mdd_port': round(_max_drawdown(n), 4), 'mdd_bench': round(_max_drawdown(b), 4), 'rel_mdd': round(_max_drawdown(rel), 4),
        'turnover_annual': round(float(sim['traded_total'] / avg_nav / years), 2),
        'cost_drag_annual': round(float(sim['cost_total'] / avg_nav / years), 4),
        'n_rebalances': sim['n_rebalances'],
        'unfilled': int((~sim['positions']['filled']).sum()) if len(sim['positions']) else 0,
        'skipped_months': len(sim.get('skipped', [])),
        'tsmc_weight_mean': (round(float(np.mean([w for _, w in sim.get('tsmc_log', []) if w is not None])), 3)
                             if any(w is not None for _, w in sim.get('tsmc_log', [])) else None),
        'total_return_port': round(float(n.iloc[-1] - 1), 4), 'total_return_bench': round(float(b.iloc[-1] - 1), 4),
        'yearly_active': {str(y): round(float((1 + g).prod() - 1), 4) for y, g in m_act.groupby(m_act.index.year)},
    }, m_act


# ── 日誌 ──────────────────────────────────────────────────────────────────────

def experiment_log() -> pd.DataFrame:
    with get_conn() as conn:
        return pd.read_sql("SELECT id, run_at, experiment_n, name, signal, segment, period_start, period_end, metrics, n_rebalances, notes "
                           "FROM portfolio_runs ORDER BY experiment_n", conn)


def next_n_and_var() -> tuple:
    log = experiment_log()
    n = int(log['experiment_n'].max()) + 1 if len(log) else 1
    srs = [m.get('sharpe_m_active') for m in log['metrics']] if len(log) else []
    srs = [float(x) for x in srs if x is not None]
    var = float(np.var(srs)) if len(srs) >= 2 else 0.0
    return n, var


def series_frame(nav: pd.Series, bench: pd.Series) -> pd.DataFrame:
    b = bench.reindex(nav.index).ffill()
    return pd.DataFrame({'nav': nav / nav.iloc[0], 'bench': b / b.iloc[0]})


def save_series(run_id: int, series: pd.DataFrame) -> int:
    from psycopg2.extras import execute_values
    rows = [(run_id, d.date(), round(float(r.nav), 6), round(float(r.bench), 6)) for d, r in series.iterrows()]
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM portfolio_run_series WHERE run_id = %s", (run_id,))
            execute_values(cur, "INSERT INTO portfolio_run_series (run_id, trade_date, nav, bench) VALUES %s", rows, page_size=2000)
        conn.commit()
    return len(rows)


def save_run(n: int, name: str, signal: str, segment: str, start: date, end: date, params: dict, met: dict,
             positions: pd.DataFrame, notes: str, series: Optional[pd.DataFrame] = None) -> int:
    from psycopg2.extras import execute_values
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO portfolio_runs (experiment_n, name, signal, segment, period_start, period_end, params, metrics, n_rebalances, notes)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                        (n, name, signal, segment, start, end, json.dumps(params, ensure_ascii=False), json.dumps(met, ensure_ascii=False),
                         met.get('n_rebalances', 0), notes))
            run_id = cur.fetchone()[0]
            if len(positions):
                execute_values(cur, """INSERT INTO portfolio_positions (run_id, rebalance_date, exec_date, stock_id, rank, signal_value, target_weight, filled)
                                       VALUES %s ON CONFLICT DO NOTHING""",
                               [(run_id, r.rebalance_date, r.exec_date, r.stock_id, None if pd.isna(r.rank) else int(r.rank),
                                 None if pd.isna(r.signal_value) else float(r.signal_value), float(r.target_weight), bool(r.filled))
                                for r in positions.itertuples(index=False)], page_size=1000)
        conn.commit()
    if series is not None:
        save_series(run_id, series)
    return run_id


def attach_series(run_id: int) -> dict:
    """用日誌裡存的參數重算一次，把淨值曲線與 yearly_active 補到那一列。不是新的實驗，N 不動。"""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT signal, segment, period_start, period_end, params, metrics FROM portfolio_runs WHERE id = %s", (run_id,))
            row = cur.fetchone()
    if not row:
        raise ValueError(f'run {run_id} 不存在')
    signal, segment, ps, pe, params, met_old = row
    res = run(signal, segment, ps, pe, params.get('top_n', 20), params.get('buffer', 40), params.get('universe_n', 300),
              params.get('excl_limit_pct', 0.10), params.get('tsmc_weight'), params.get('costs', COSTS), save=False,
              tranches=params.get('tranches', 1), weighting=params.get('weighting', 'equal'))
    n = save_series(run_id, series_frame(res['nav'], res['bench']))
    met_old = dict(met_old or {})
    met_old['yearly_active'] = res['metrics']['yearly_active']
    drift = abs(float(met_old.get('ann_active', 0)) - res['metrics']['ann_active'])
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE portfolio_runs SET metrics = %s WHERE id = %s", (json.dumps(met_old, ensure_ascii=False), run_id))
        conn.commit()
    return {'run_id': run_id, 'points': n, 'recomputed_ann_active': res['metrics']['ann_active'], 'logged_ann_active': met_old.get('ann_active'),
            'drift': round(drift, 6)}


def current_list(run_id: int, as_of: Optional[date] = None) -> dict:
    """
    用候選那一列的參數，從它的 period_start 一路算到 as_of（預設今天），只取最後一次調倉的目標持股寫進 portfolio_live_list。
    保留期（2024-10 起）的淨值與指標在這裡**不算、不存、不印**——這個函式的輸出只有名單。
    """
    as_of = as_of or date.today()
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT signal, period_start, params FROM portfolio_runs WHERE id = %s", (run_id,))
            row = cur.fetchone()
    if not row:
        raise ValueError(f'run {run_id} 不存在')
    signal, start, params = row
    prices = ps.load_prices(start, as_of)
    mkt = ps.Market(prices, ps.load_universe_meta())
    sur = ps.surprises(ps.load_revenue(start))
    sim = simulate(mkt, sur, signal, start, as_of, params.get('top_n', 20), params.get('buffer', 40), params.get('universe_n', 300),
                   params.get('excl_limit_pct', 0.10), params.get('tsmc_weight'), params.get('costs', COSTS),
                   params.get('tranches', 1), params.get('weighting', 'equal'))
    pos = sim['positions']
    if not len(pos):
        raise RuntimeError('沒有任何調倉')
    last = pos['rebalance_date'].max()
    cur_rows = pos[pos['rebalance_date'] == last]
    prev_dates = sorted(pos['rebalance_date'].unique())
    prev = set(pos[pos['rebalance_date'] == prev_dates[-2]]['stock_id']) if len(prev_dates) > 1 else set()
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT stock_id, stock_name FROM market_universe")
            names = dict(cur.fetchall())
            names.setdefault(ps.TSMC, '台積電')
            cur.execute("DELETE FROM portfolio_live_list")
            from psycopg2.extras import execute_values
            execute_values(cur, """INSERT INTO portfolio_live_list (run_id, rebalance_date, exec_date, stock_id, stock_name, rank, signal_value, target_weight, is_new)
                                   VALUES %s""",
                           [(run_id, r.rebalance_date, r.exec_date, r.stock_id, names.get(r.stock_id), None if pd.isna(r.rank) else int(r.rank),
                             None if pd.isna(r.signal_value) else float(r.signal_value), float(r.target_weight), r.stock_id not in prev)
                            for r in cur_rows.itertuples(index=False)])
        conn.commit()
    return {'run_id': run_id, 'rebalance_date': str(last), 'exec_date': str(cur_rows['exec_date'].iloc[0]), 'n': int(len(cur_rows)),
            'new': sorted(set(cur_rows['stock_id']) - prev)}


def tag_run(run_id: int, tag: Optional[str]) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE portfolio_runs SET tag = %s WHERE id = %s", (tag, run_id))
        conn.commit()


# ── 入口 ──────────────────────────────────────────────────────────────────────

def run(signal: str, segment: str = 'dev', start: Optional[date] = None, end: Optional[date] = None, top_n: int = 20, buffer: int = 40,
        universe_n: int = 300, excl_limit_pct: float = 0.10, tsmc_weight: Optional[float] = None, costs: dict = COSTS,
        name: Optional[str] = None, notes: str = '', save: bool = True, tranches: int = 1, weighting: str = 'equal',
        _cache: Optional[dict] = None) -> dict:
    """tsmc_weight：None（不持台積電）、數字（固定權重）、'est'（每次調倉用 estimate_tsmc_weight 估 0050 的台積電權重）。"""
    seg_start, seg_end = SEGMENTS.get(segment, (None, None))
    start = start or seg_start
    end = end or seg_end or date.today()
    if start is None:
        raise ValueError('要給 segment 或 start')
    t0 = datetime.now()
    key = (start, end)
    if _cache is not None and _cache.get('key') == key:
        mkt, sur = _cache['mkt'], _cache['sur']
    else:
        prices = ps.load_prices(start, end)
        meta = ps.load_universe_meta()
        mkt = ps.Market(prices, meta)
        sur = ps.surprises(ps.load_revenue(start))
        if _cache is not None:
            _cache.update({'key': key, 'mkt': mkt, 'sur': sur})
    sim = simulate(mkt, sur, signal, start, end, top_n, buffer, universe_n, excl_limit_pct, tsmc_weight, costs, tranches, weighting)
    bench = mkt.adj[ps.BENCH].dropna()
    met, m_act = metrics(sim['nav'], bench, sim)
    n, var = next_n_and_var()
    d = dsr_mod.deflated_sharpe(list(m_act.values), n, var)
    met.update({'experiment_n': n, 'dsr': round(d['dsr'], 4), 'sr_star_m': round(d['sr_star'], 4), 'var_sharpe_prior': round(var, 6),
                'skew_m': round(d['skew'], 3), 'kurt_m': round(d['kurt'], 3)})
    params = {'signal': signal, 'top_n': top_n, 'buffer': buffer, 'universe_n': universe_n, 'excl_limit_pct': excl_limit_pct,
              'tsmc_weight': tsmc_weight, 'costs': costs, 'segment': segment, 'tranches': tranches, 'weighting': weighting}
    name = name or f'{signal}-{segment}-top{top_n}' + (f'-t{tranches}' if tranches > 1 else f'-b{buffer}') + (f'-u{universe_n}' if universe_n != 300 else '') + ('-liq' if weighting == 'liq' else '') + (f'-tsmc{tsmc_weight}' if tsmc_weight else '')
    run_id = save_run(n, name, signal, segment, start, met_end(met), params, met, sim['positions'], notes,
                      series=series_frame(sim['nav'], bench)) if save else None
    logger.info('[backtest] #%d %s：主動報酬 %+.2f%%/年、IR %s、DSR %.3f、換手 %.1f 倍、成本 %.2f%%/年（%.0f 秒）',
                n, name, met['ann_active'] * 100, met['info_ratio'], met['dsr'], met['turnover_annual'], met['cost_drag_annual'] * 100,
                (datetime.now() - t0).total_seconds())
    return {'run_id': run_id, 'name': name, 'metrics': met, 'monthly_active': m_act, 'nav': sim['nav'], 'bench': bench,
            'positions': sim['positions'], 'params': params, 'experiment_n': n}


def met_end(met: dict) -> date:
    return date.fromisoformat(met['end'])


def report_md(res: dict) -> str:
    m, p = res['metrics'], res['params']
    L = [f"# 月調倉回測 #{m['experiment_n']}：{res['name']}", '',
         f"**期間：** {m['start']} ~ {m['end']}（{m['years']} 年、{m['months']} 個月、{m['n_rebalances']} 次調倉）　**對手：** 0050 含息",
         f"**規則：** 訊號 `{p['signal']}`、流動性前 {p['universe_n']}、排除漲停前 {int(p['excl_limit_pct'] * 100)}%、前 {p['top_n']} 檔{'等權' if p.get('weighting', 'equal') == 'equal' else '成交金額加權'}、"
         + (f"分 {p['tranches']} 批輪動" if p.get('tranches', 1) > 1 else f"緩衝 {p['buffer']} 名") + f"、台積電權重 {p['tsmc_weight']}",
         f"**成本：** 單邊手續費 {p['costs']['fee'] * 100:.4f}%、賣出稅 {p['costs']['tax'] * 100:.1f}%、滑價 {p['costs']['slip'] * 100:.2f}%（小型股 {p['costs']['slip_small'] * 100:.2f}%）", '',
         '| 指標 | 組合 | 0050 |', '|---|---|---|',
         f"| 年化報酬 | {m['cagr_port'] * 100:+.2f}% | {m['cagr_bench'] * 100:+.2f}% |",
         f"| 總報酬 | {m['total_return_port'] * 100:+.1f}% | {m['total_return_bench'] * 100:+.1f}% |",
         f"| 最大回撤 | {m['mdd_port'] * 100:.1f}% | {m['mdd_bench'] * 100:.1f}% |", '',
         '| 主動報酬指標 | 值 | 門檻 |', '|---|---|---|',
         f"| 年化主動報酬 | **{m['ann_active'] * 100:+.2f}%** | ≥ +3% |",
         f"| 追蹤誤差 | {m['tracking_error'] * 100:.1f}% | |",
         f"| 資訊比率 | {m['info_ratio']} | ≥ 0.5 |",
         f"| 月 Sharpe（主動） | {m['sharpe_m_active']} | |",
         f"| DSR（N = {m['experiment_n']}，SR* = {m['sr_star_m']}） | **{m['dsr']}** | ≥ 0.95 |",
         f"| 月勝率 | {m['monthly_win_rate'] * 100:.0f}% | |",
         f"| 相對 0050 最大落後 | {m['rel_mdd'] * 100:.1f}% | ≤ 10pp 於 0050 回撤 |",
         f"| 年換手（單邊） | {m['turnover_annual']} 倍 | 3~6 倍 |",
         f"| 成本占年報酬 | {m['cost_drag_annual'] * 100:.2f}% | |",
         f"| 未成交單 | {m['unfilled']} | |",
         f"| 訊號不足而未調倉的月 | {m.get('skipped_months', 0)} | |",
         f"| 台積電平均權重 | {m.get('tsmc_weight_mean')} | |", '']
    ma = res['monthly_active']
    if len(ma):
        L += ['## 逐年主動報酬', '', '| 年 | 主動報酬 | 月數 |', '|---|---|---|']
        for y, g in ma.groupby(ma.index.year):
            L.append(f"| {y} | {((1 + g).prod() - 1) * 100:+.2f}% | {len(g)} |")
        L.append('')
    pos = res['positions']
    if len(pos):
        last = pos[pos['rebalance_date'] == pos['rebalance_date'].max()].sort_values('rank', na_position='last')
        L += [f"## 最後一次持股（{last['rebalance_date'].iloc[0]}）", '', '| 排名 | 代碼 | 訊號值 | 權重 | 成交 |', '|---|---|---|---|---|']
        for r in last.itertuples(index=False):
            L.append(f"| {'' if pd.isna(r.rank) else int(r.rank)} | {r.stock_id} | {'' if pd.isna(r.signal_value) else f'{r.signal_value:+.3f}'} | {r.target_weight * 100:.1f}% | {'是' if r.filled else '未成交'} |")
    return '\n'.join(L) + '\n'


def main():
    global RESULTS_DIR
    import os
    RESULTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'UnifiedModel', 'results')
    ap = argparse.ArgumentParser()
    ap.add_argument('--signal', help="sue / win / ar0 / mom / win3，或用 + 組合（排名平均），例如 win+mom")
    ap.add_argument('--segment', choices=list(SEGMENTS), default='dev')
    ap.add_argument('--start'); ap.add_argument('--end')
    ap.add_argument('--top-n', type=int, default=20); ap.add_argument('--buffer', type=int, default=40)
    ap.add_argument('--universe-n', type=int, default=300); ap.add_argument('--excl-limit-pct', type=float, default=0.10)
    ap.add_argument('--tsmc-weight', default=None, help="數字＝固定權重；est＝用滾動迴歸估 0050 的台積電權重")
    ap.add_argument('--tranches', type=int, default=1, help='分批輪動：每月只換 1/K（K 個月持有期）')
    ap.add_argument('--weighting', choices=['equal', 'liq'], default='equal')
    ap.add_argument('--name'); ap.add_argument('--notes', default='')
    ap.add_argument('--no-save', action='store_true')
    ap.add_argument('--holdout-once', action='store_true', help='保留期只能看一次：沒有這個旗標不跑 holdout')
    ap.add_argument('--list', action='store_true')
    ap.add_argument('--attach-series', type=int, metavar='RUN_ID', help='用日誌裡的參數重算、補存淨值曲線（不算新實驗）')
    ap.add_argument('--tag', nargs=2, metavar=('RUN_ID', 'TAG'), help="標記一列，例如 44 candidate；TAG 給 none 清掉")
    ap.add_argument('--current-list', type=int, metavar='RUN_ID', help='用候選參數算到今天的目標持股，寫 portfolio_live_list（不算保留期績效）')
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s')
    if a.attach_series:
        print(attach_series(a.attach_series))
        return
    if a.tag:
        tag_run(int(a.tag[0]), None if a.tag[1] == 'none' else a.tag[1])
        print('tagged', a.tag)
        return
    if a.current_list:
        print(current_list(a.current_list))
        return
    if a.list:
        log = experiment_log()
        for r in log.itertuples(index=False):
            m = r.metrics
            print(f"#{r.experiment_n:>3} {r.run_at:%Y-%m-%d %H:%M} {r.name:<28} {r.signal:<4} {r.segment:<7} {r.period_start}~{r.period_end} "
                  f"主動 {m.get('ann_active', 0) * 100:+.2f}% IR {m.get('info_ratio')} DSR {m.get('dsr')} 換手 {m.get('turnover_annual')}  {r.notes or ''}")
        return
    if not a.signal:
        ap.error('--signal 必填')
    if a.segment == 'holdout' and not a.holdout_once:
        ap.error('holdout 只能看一次：確定要看就加 --holdout-once，並在 --notes 寫下理由')
    tw = None if a.tsmc_weight in (None, '', 'none') else ('est' if a.tsmc_weight == 'est' else float(a.tsmc_weight))
    res = run(a.signal, a.segment, date.fromisoformat(a.start) if a.start else None, date.fromisoformat(a.end) if a.end else None,
              a.top_n, a.buffer, a.universe_n, a.excl_limit_pct, tw, COSTS, a.name, a.notes, save=not a.no_save,
              tranches=a.tranches, weighting=a.weighting)
    md = report_md(res)
    print(md)
    if not a.no_save:
        os.makedirs(RESULTS_DIR, exist_ok=True)
        path = os.path.join(RESULTS_DIR, f"portfolio_{res['metrics']['experiment_n']:03d}_{a.signal}_{a.segment}.md")
        with open(path, 'w', encoding='utf-8') as f:
            f.write(md)
        print('報表：', os.path.abspath(path))


if __name__ == '__main__':
    main()
