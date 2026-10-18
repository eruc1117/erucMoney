"""Iteration 85 重搜檢查（只讀）：#109 之前 portfolio_runs 裡有沒有任何 sblf／indlead 成分的列（登記第 31 行的陳述要有證據）。
用法（Crawler 目錄）：PYTHONUTF8=1 python ../AI/experiments/iter85_nosearch.py"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'Crawler'))
from db.connection import get_conn  # noqa: E402

with get_conn() as conn:
    cur = conn.cursor()
    cur.execute("""SELECT experiment_n, name, signal FROM portfolio_runs
                   WHERE (signal LIKE '%%sblf%%' OR signal LIKE '%%indlead%%' OR name LIKE '%%sblf%%' OR name LIKE '%%indlead%%') ORDER BY 1""")
    rows = cur.fetchall()
    before = [r for r in rows if r[0] < 109]
    print(f'含 sblf／indlead 的列：{len(rows)}（#109 之前 {len(before)} 列）：', rows)
    cur.execute("SELECT experiment_n, signal FROM portfolio_runs WHERE signal LIKE '%%sir%%' OR signal LIKE '%%indmom%%' OR signal LIKE '%%relmom%%' ORDER BY 1")
    print('鄰近家族（餘額 sir、產業動能 indmom／relmom）：', cur.fetchall())
