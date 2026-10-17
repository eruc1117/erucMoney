"""Iteration 77 證據：淨值曲線（portfolio_run_series）覆蓋哪些 run，贏過大盤清單裡幾列有圖。唯讀。
執行：cd Crawler && PYTHONUTF8=1 python ../AI/experiments/iter77_evidence.py（經 record_check.js --name series-evidence-77）
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'Crawler'))

from db.connection import get_conn   # noqa: E402

with get_conn() as c:
    cur = c.cursor()
    cur.execute("SELECT count(DISTINCT run_id), count(*), min(run_id), max(run_id) FROM portfolio_run_series"); print('有曲線的 run 數 / 總點數 / 最小 id / 最大 id:', cur.fetchone())
    cur.execute("SELECT run_id, count(*) FROM portfolio_run_series WHERE run_id IN (44, 68) GROUP BY 1 ORDER BY 1"); print('#44／#68 點數:', cur.fetchall())
    cur.execute("""SELECT count(*) FILTER (WHERE EXISTS (SELECT 1 FROM portfolio_run_series s WHERE s.run_id = r.id)),
                          count(*) FILTER (WHERE NOT EXISTS (SELECT 1 FROM portfolio_run_series s WHERE s.run_id = r.id))
                   FROM portfolio_runs r WHERE (metrics->>'ann_active')::float > 0 AND coalesce(tag, '') <> 'void'""")
    print('贏過大盤清單（年化主動 > 0 且非 void）有曲線 / 沒曲線:', cur.fetchone())
    cur.execute("""SELECT array_agg(id ORDER BY id) FROM portfolio_runs r WHERE (metrics->>'ann_active')::float > 0 AND coalesce(tag, '') <> 'void'
                   AND NOT EXISTS (SELECT 1 FROM portfolio_run_series s WHERE s.run_id = r.id)""")
    print('沒曲線的列 id:', cur.fetchone()[0])
