"""Iteration 84 審查補證據（只讀）：#38 相對最大落後日誌 −16.65% 對重算 −16.64% 的那 0.01 pp 是不是捨入——
用 #38 存的淨值曲線（portfolio_run_series）與重算的淨值各算未捨入的相對最大落後，並印兩條 0050 淨值的最大相對差。
用法（Crawler 目錄）：PYTHONUTF8=1 PYTHONWARNINGS=ignore python ../AI/experiments/iter84_mdd38.py"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'Crawler'))
import portfolio_backtest as pb  # noqa: E402
from db.connection import get_conn  # noqa: E402


def rel_mdd(nav, bench):
    b = bench.reindex(nav.index).ffill()
    b = b / b.iloc[0]
    n = nav / nav.iloc[0]
    active_d = (n.pct_change().dropna() - b.pct_change().dropna()).dropna()
    rel = (1 + active_d).cumprod()
    return float(pb._max_drawdown(rel))


with get_conn() as conn:
    cur = conn.cursor()
    cur.execute("SELECT signal, segment, period_start, period_end, params, metrics FROM portfolio_runs WHERE id = 38")
    signal, seg, ps_, pe, params, met = cur.fetchone()
    cur.execute("SELECT trade_date, nav, bench FROM portfolio_run_series WHERE run_id = 38 ORDER BY 1")
    rows = cur.fetchall()
idx = pd.to_datetime([r[0] for r in rows])
nav_old = pd.Series([float(r[1]) for r in rows], index=idx)
bench_old = pd.Series([float(r[2]) for r in rows], index=idx)
res = pb.run(signal, seg, ps_, pe, params['top_n'], params['buffer'], params['universe_n'], params['excl_limit_pct'], params['tsmc_weight'],
             params.get('costs', pb.COSTS), save=False, tranches=params['tranches'], weighting=params['weighting'])
nav_new, bench_new = res['nav'], res['bench']
b_new = bench_new.reindex(nav_new.index).ffill()
b_new = b_new / b_new.iloc[0]
print(f'#38 存的曲線 {len(nav_old)} 點、重算 {len(nav_new)} 點')
print(f'相對最大落後（未捨入）：存的曲線 {rel_mdd(nav_old, bench_old):.6f}、重算 {rel_mdd(nav_new, bench_new):.6f}；日誌 metrics rel_mdd {met["rel_mdd"]}')
nav_ratio = (nav_new.reindex(nav_old.index) / nav_old)
print(f'組合淨值逐日比值 max|r−1| {float((nav_ratio - 1).abs().max()):.2e}；0050 淨值逐日 max|r−1| {float((b_new.reindex(bench_old.index) / bench_old - 1).abs().max()):.2e}')
print(f'存的 nav 小數位：{str(rows[10][1])}（NUMERIC(14,6) 捨到小數第 6 位）')
