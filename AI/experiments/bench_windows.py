"""0050 在兩個「候選持現金」窗口的還原收盤報酬（Iteration 73 讀法的佐證；不算 N）。用法：cd Crawler && python ../AI/experiments/bench_windows.py"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'Crawler'))
from db.connection import get_conn  # noqa: E402

with get_conn() as c:
    cur = c.cursor()
    for a, b in (('2018-01-02', '2018-10-31'), ('2022-01-03', '2022-08-31')):
        cur.execute("SELECT trade_date, adj_close FROM stock_daily_prices WHERE stock_id = '0050' AND trade_date IN (%s, %s) ORDER BY 1", (a, b))
        rows = cur.fetchall()
        (d0, x), (d1, y) = rows
        print(f"0050 adj_close {d0} {float(x):.2f} -> {d1} {float(y):.2f}：{(float(y) / float(x) - 1) * 100:+.1f}%")
