"""Iteration 84 前置（只讀）：資料更新後月調倉重算之前，先看輸入動了沒——
(1) 要重算的 run 的參數與指標；(2) #44 存的 0050 含息淨值曲線對今天 `stock_daily_prices` 0050 adj_close 重建的淨值（同起點）差多少；
(3) 全市場表 adj_close 2018 起 NULL／非正列數；(4) 0050 在 `stock_daily_prices` 的事件列（除息）筆數與最近一筆。
用法（Crawler 目錄）：PYTHONUTF8=1 python ../AI/experiments/iter84_inputs.py"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'Crawler'))
from db.connection import get_conn  # noqa: E402

RUNS = [30, 38, 44, 87, 88, 90, 92, 94, 96, 106, 108, 54, 58, 62]
KEYS = ['ann_active', 'info_ratio', 'tracking_error', 'rel_mdd', 'cagr_port', 'cagr_bench', 'n_rebalances', 'experiment_n', 'dsr']

with get_conn() as conn:
    cur = conn.cursor()
    cur.execute("SELECT id, name, signal, segment, period_start, period_end, params, metrics, tag FROM portfolio_runs WHERE id = ANY(%s) ORDER BY id", (RUNS,))
    print('run | name | signal | segment | 期間 | tag | 參數（非預設） | 指標')
    for rid, name, sig, seg, ps_, pe, params, met, tag in cur.fetchall():
        p = {k: v for k, v in params.items() if k not in ('signal', 'segment', 'costs')}
        print(f'#{rid} | {name} | {sig} | {seg} | {ps_}～{pe} | {tag} | {json.dumps(p, ensure_ascii=False)} | ' + ', '.join(f'{k}={met.get(k)}' for k in KEYS))
    cur.execute("SELECT trade_date, bench FROM portfolio_run_series WHERE run_id = 44 ORDER BY 1")
    stored = cur.fetchall()
    if stored:
        d0, dn = stored[0][0], stored[-1][0]
        cur.execute("SELECT trade_date, adj_close FROM stock_daily_prices WHERE stock_id = '0050' AND trade_date BETWEEN %s AND %s AND adj_close IS NOT NULL ORDER BY 1", (d0, dn))
        now = dict(cur.fetchall())
        base = float(now[d0])
        diffs = []
        for d, b in stored:
            if d in now:
                diffs.append((d, float(b), float(now[d]) / base))
        worst = max(diffs, key=lambda x: abs(x[2] / x[1] - 1))
        print(f'#44 存的 0050 淨值 {len(stored)} 點（{d0}～{dn}）對今天重建：共有 {len(diffs)} 點、最大相對差 {abs(worst[2] / worst[1] - 1) * 100:.4f}%（{worst[0]} 存 {worst[1]:.6f} 今 {worst[2]:.6f}）、期末 存 {diffs[-1][1]:.6f} 今 {diffs[-1][2]:.6f}')
    else:
        print('#44 沒有存淨值曲線')
    cur.execute("SELECT count(*) FILTER (WHERE adj_close IS NULL), count(*) FILTER (WHERE adj_close <= 0), count(*) FROM market_daily_prices WHERE trade_date >= '2018-01-01'")
    print('全市場表 2018 起 adj_close NULL／≤0／總列：%d／%d／%d' % cur.fetchone())
    cur.execute("SELECT count(*), max(ex_date) FROM stock_dividend_result WHERE stock_id = '0050'")
    print('0050 除息事件：%d 筆、最近 %s' % cur.fetchone())
    cur.execute("SELECT count(*), min(trade_date), max(trade_date) FROM stock_daily_prices WHERE stock_id = '0050' AND adj_close IS NOT NULL")
    print('0050 行情（adj 有值）：%d 列、%s～%s' % cur.fetchone())
    cur.execute("SELECT max(experiment_n), count(*) FROM portfolio_runs"); print('portfolio_runs：N %d、列數 %d' % cur.fetchone())
