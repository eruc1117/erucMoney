"""各段回測列數（只讀）：portfolio_runs 依 segment 的總數、年化主動 > 0 的數（儀表板「贏過大盤的回測」的篩選）、期間；live／holdout 列的名稱。
用法（Crawler 目錄）：PYTHONUTF8=1 python ../AI/experiments/segment_counts.py"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'Crawler'))
from db.connection import get_conn  # noqa: E402

with get_conn() as conn:
    cur = conn.cursor()
    cur.execute("""SELECT segment, count(*), count(*) FILTER (WHERE (metrics->>'ann_active')::float > 0),
                          count(*) FILTER (WHERE (metrics->>'ann_active')::float > 0 AND coalesce(tag, '') <> 'void'),
                          min(period_start), max(period_end) FROM portfolio_runs GROUP BY 1 ORDER BY 1""")
    print('segment | 列數 | 主動 > 0 | 主動 > 0 且非作廢 | 最早起 | 最晚迄')
    for r in cur.fetchall():
        print(' | '.join(str(x) for x in r))
    cur.execute("SELECT id, experiment_n, name, segment, period_start, period_end, tag, round((metrics->>'ann_active')::numeric * 100, 2) FROM portfolio_runs WHERE segment NOT IN ('dev', 'valid') OR tag IS NOT NULL ORDER BY id")
    print('\n非 dev／valid 或有 tag 的列：')
    for r in cur.fetchall():
        print('  ', r)
