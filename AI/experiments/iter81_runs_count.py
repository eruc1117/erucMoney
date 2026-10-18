"""portfolio_runs 的 N 沒動（Iteration 81 是資料工作）。用法（在 Crawler 目錄）：PYTHONUTF8=1 python ../AI/experiments/iter81_runs_count.py"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'Crawler'))
from db.connection import get_conn  # noqa: E402

with get_conn() as c:
    cur = c.cursor()
    cur.execute('SELECT max(experiment_n), count(*), max(run_at) FROM portfolio_runs')
    print('portfolio_runs max(experiment_n), count(*), max(run_at):', cur.fetchone())
