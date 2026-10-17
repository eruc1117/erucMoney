"""Iteration 76 證據：對正式庫 Stock 的唯讀查詢（贏過大盤清單的構成、#44／#68 的持股端點輸出），
輸出經 node AI/harness/record_check.js --name positions-evidence-76 進 checks.json，迭代紀錄的數字指回這裡。

執行：cd Crawler && PYTHONUTF8=1 python ../AI/experiments/iter76_evidence.py
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'Crawler'))

import portfolio_api as pa                      # noqa: E402
from db.connection import get_conn              # noqa: E402

with get_conn() as c:
    cur = c.cursor()
    cur.execute("SELECT count(*), max(id), max(experiment_n) FROM portfolio_runs"); print('portfolio_runs count/max id/max n:', cur.fetchone())
    cur.execute("""SELECT count(*) FILTER (WHERE (metrics->>'ann_active')::float > 0),
                          count(*) FILTER (WHERE (metrics->>'ann_active')::float > 0 AND coalesce(tag, '') <> 'void'),
                          count(*) FILTER (WHERE (metrics->>'ann_active')::float >= 0.03 AND (metrics->>'info_ratio')::float >= 0.5)
                   FROM portfolio_runs""")
    print('ann_active>0 / ann_active>0 且非 void / 過年化主動與 IR 門檻:', cur.fetchone())
    cur.execute("SELECT tag, count(*) FROM portfolio_runs GROUP BY 1 ORDER BY 1"); print('tag 分布:', cur.fetchall())
    cur.execute("SELECT id, experiment_n, name, segment, metrics->>'ann_active' FROM portfolio_runs WHERE tag = 'void' ORDER BY id"); print('void 列:', cur.fetchall())
    cur.execute("SELECT id, segment, tag, metrics->>'ann_active' FROM portfolio_runs WHERE segment IN ('live', 'holdout') ORDER BY id"); print('live/holdout 列:', cur.fetchall())
    cur.execute("SELECT count(*) FROM portfolio_positions p LEFT JOIN market_universe u ON u.stock_id = p.stock_id WHERE u.stock_id IS NULL"); print('positions 缺名稱:', cur.fetchone())
    cur.execute("SELECT run_id, count(DISTINCT rebalance_date), count(*) FROM portfolio_positions WHERE run_id IN (44, 68) GROUP BY 1 ORDER BY 1"); print('#44/#68 調倉次數、列數:', cur.fetchall())

for rid in (44, 68):
    t = time.perf_counter(); o = pa.run_positions(rid); ms = round((time.perf_counter() - t) * 1000, 1)
    rows = sum(len(g['positions']) for g in o['rebalances'])
    print(f'run_positions({rid}): n_rebalances={o["n_rebalances"]} n_stocks={o["n_stocks"]} rows={rows} json_KB={len(json.dumps(o, ensure_ascii=False)) // 1024} ms={ms} last={o["rebalances"][-1]["rebalance_date"]}')
    print('  frequent:', [(f['stock_id'], f['stock_name'], f['times']) for f in o['frequent'][:5]])
print('run_positions(999999):', pa.run_positions(999999))
