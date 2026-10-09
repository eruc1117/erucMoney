"""
月調倉實驗日誌的讀取層（Iteration 51）：給 FastAPI /portfolio/* 用，前端「月調倉」頁顯示。

只讀 portfolio_runs / portfolio_positions / portfolio_run_series；不跑回測。
"""

from typing import Optional

from db.connection import get_conn

THRESHOLDS = {'ann_active': 0.03, 'info_ratio': 0.5, 'dsr': 0.95, 'turnover_min': 3.0, 'turnover_max': 6.0}
SEGMENT_LABEL = {'dev': '開發期', 'valid': '驗證期', 'holdout': '保留期', 'paper': '紙上交易', 'live': '實單'}


def _run_row(r) -> dict:
    (rid, run_at, n, name, signal, segment, ps, pe, params, metrics, n_reb, notes, tag) = r
    return {'id': rid, 'run_at': run_at.isoformat() if run_at else None, 'experiment_n': n, 'name': name, 'signal': signal,
            'segment': segment, 'segment_label': SEGMENT_LABEL.get(segment, segment), 'period_start': str(ps), 'period_end': str(pe),
            'params': params or {}, 'metrics': metrics or {}, 'n_rebalances': n_reb, 'notes': notes, 'tag': tag}


_COLS = "id, run_at, experiment_n, name, signal, segment, period_start, period_end, params, metrics, n_rebalances, notes, tag"


def list_runs() -> dict:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT {_COLS} FROM portfolio_runs ORDER BY experiment_n")
            runs = [_run_row(r) for r in cur.fetchall()]
            cur.execute("SELECT DISTINCT run_id FROM portfolio_run_series")
            with_series = {r[0] for r in cur.fetchall()}
    for r in runs:
        r['has_series'] = r['id'] in with_series
    return {'runs': runs, 'n_total': len(runs), 'thresholds': THRESHOLDS}


def get_run(run_id: int, step: int = 1) -> Optional[dict]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT {_COLS} FROM portfolio_runs WHERE id = %s", (run_id,))
            row = cur.fetchone()
            if not row:
                return None
            run = _run_row(row)
            cur.execute("SELECT trade_date, nav, bench FROM portfolio_run_series WHERE run_id = %s ORDER BY trade_date", (run_id,))
            pts = cur.fetchall()
            cur.execute("SELECT max(rebalance_date) FROM portfolio_positions WHERE run_id = %s", (run_id,))
            last = cur.fetchone()[0]
            positions = []
            if last:
                cur.execute("""SELECT stock_id, rank, signal_value, target_weight, filled, exec_date FROM portfolio_positions
                               WHERE run_id = %s AND rebalance_date = %s ORDER BY rank NULLS LAST, stock_id""", (run_id, last))
                positions = [{'stock_id': s, 'rank': rk, 'signal_value': float(sv) if sv is not None else None,
                              'target_weight': float(w), 'filled': f, 'exec_date': str(e) if e else None}
                             for s, rk, sv, w, f, e in cur.fetchall()]
    step = max(1, step)
    series = [{'d': str(d), 'nav': float(n), 'bench': float(b)} for i, (d, n, b) in enumerate(pts) if i % step == 0 or i == len(pts) - 1]
    return {'run': run, 'series': series, 'positions': positions, 'last_rebalance': str(last) if last else None,
            'thresholds': THRESHOLDS}


def live_list() -> Optional[dict]:
    """portfolio_live_list：候選策略算到最近訊號日的目標持股（現在該買哪些）。"""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT l.computed_at, l.run_id, l.rebalance_date, l.exec_date, l.stock_id, l.stock_name, l.rank, l.signal_value, l.target_weight, l.is_new,
                                  p.close_price, p.trade_date
                           FROM portfolio_live_list l
                           LEFT JOIN LATERAL (SELECT close_price, trade_date FROM market_daily_prices m
                                              WHERE m.stock_id = l.stock_id AND m.close_price > 0 ORDER BY trade_date DESC LIMIT 1) p ON TRUE
                           WHERE l.rebalance_date = (SELECT max(rebalance_date) FROM portfolio_live_list)
                           ORDER BY l.rank NULLS LAST, l.stock_id""")
            rows = cur.fetchall()
    if not rows:
        return None
    return {'computed_at': rows[0][0].isoformat(), 'run_id': rows[0][1], 'rebalance_date': str(rows[0][2]), 'exec_date': str(rows[0][3]) if rows[0][3] else None,
            'price_date': max((str(pd) for *_, pd in rows if pd), default=None),
            'items': [{'stock_id': s, 'stock_name': nm, 'rank': rk, 'signal_value': float(sv) if sv is not None else None,
                       'target_weight': float(w), 'is_new': bool(new),
                       'price': float(px) if px is not None else None, 'price_date': str(pd) if pd else None}
                      for _, _, _, _, s, nm, rk, sv, w, new, px, pd in rows]}


def paper() -> dict:
    """紙上交易：狀態、檢討、最近成交。"""
    import portfolio_paper
    r = portfolio_paper.review()
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT rebalance_date, trade_date, stock_id, side, shares, price, gross, fee, tax, filled, note
                           FROM portfolio_paper_trades WHERE stock_id <> '-' ORDER BY trade_date DESC, side, stock_id LIMIT 200""")
            trades = [{'rebalance_date': str(a), 'trade_date': str(b), 'stock_id': c, 'side': d, 'shares': e, 'price': float(f), 'gross': float(g),
                       'fee': float(h), 'tax': float(i), 'filled': j, 'note': k} for a, b, c, d, e, f, g, h, i, j, k in cur.fetchall()]
            cur.execute("""SELECT stock_id, SUM(CASE WHEN side = 'buy' THEN shares ELSE -shares END) FROM portfolio_paper_trades
                           WHERE filled AND stock_id <> '-' GROUP BY 1 HAVING SUM(CASE WHEN side = 'buy' THEN shares ELSE -shares END) <> 0 ORDER BY 1""")
            held = [{'stock_id': s, 'shares': int(n)} for s, n in cur.fetchall()]
    if r and r.get('state'):
        r['state']['started_on'] = str(r['state']['started_on'])
    return {'opened': r is not None, 'review': r, 'trades': trades, 'holdings': held,
            'pending': [str(d) for d in portfolio_paper.pending_lists(__import__('datetime').date.today() + __import__('datetime').timedelta(days=1))]}


def candidates() -> dict:
    """tag = 'candidate' 的列（開發期、驗證期、全期間），加上全期間那列的最後持股。"""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT {_COLS} FROM portfolio_runs WHERE tag = 'candidate' ORDER BY period_start, period_end")
            runs = [_run_row(r) for r in cur.fetchall()]
            runs.sort(key=lambda r: r['period_start'], reverse=True)
            runs.sort(key=lambda r: r['period_end'])          # 開發期、驗證期、全期間（同一結束日時起點晚的在前）
            cur.execute("SELECT max(experiment_n) FROM portfolio_runs")
            n_total = cur.fetchone()[0] or 0
    full = min(runs, key=lambda r: (r['period_end'].replace('-', '') * -1 if False else -int(r['period_end'].replace('-', '')), r['period_start'])) if runs else None   # 結束日最晚、起點最早的那列 = 全期間
    detail = get_run(full['id'], step=5) if full else None
    return {'candidates': runs, 'full': detail, 'n_total': n_total, 'thresholds': THRESHOLDS,
            'holdout_opened': any(r['segment'] == 'holdout' for r in list_runs()['runs']),
            'current_list': live_list()}
