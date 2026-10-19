"""Iteration 88 審查補證據（只讀）：2026-10-12 的 portfolio_live_list 對正式策略 live 列 #68 自己的 portfolio_positions 逐檔比（代碼、權重）；
trading_orders 對 2026-10-12 清單的張數與股數；9 月→10 月 #68 持股進出。用法（Crawler 目錄）：PYTHONUTF8=1 python ../AI/experiments/iter88_positions_check.py"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'Crawler'))
from db.connection import get_conn  # noqa: E402

with get_conn() as conn:
    cur = conn.cursor()
    cur.execute("""SELECT coalesce(p.stock_id, l.stock_id), round(p.target_weight, 6), round(l.target_weight, 6)
                   FROM (SELECT * FROM portfolio_positions WHERE run_id = 68 AND rebalance_date = '2026-10-12') p
                   FULL JOIN (SELECT * FROM portfolio_live_list WHERE rebalance_date = '2026-10-12') l ON l.stock_id = p.stock_id ORDER BY 1""")
    rows = cur.fetchall()
    diff = [r for r in rows if r[1] is None or r[2] is None or r[1] != r[2]]
    print(f'2026-10-12：#68 持股對 live 清單 {len(rows)} 檔、不同 {len(diff)} 筆 {diff}')
    cur.execute("SELECT stock_id FROM portfolio_positions WHERE run_id = 68 AND rebalance_date = '2026-09-11'")
    s9 = {r[0] for r in cur.fetchall()}
    s10 = {r[0] for r in rows}
    print(f'#68 9 月→10 月：進 {sorted(s10 - s9)}、出 {sorted(s9 - s10)}；10 月清單 is_new 的檔數：', end='')
    cur.execute("SELECT count(*) FILTER (WHERE is_new) FROM portfolio_live_list WHERE rebalance_date = '2026-10-12'")
    print(cur.fetchone()[0])
    cur.execute("SELECT status, count(*), sum(shares), min(order_date), max(order_date) FROM trading_orders WHERE rebalance_date = '2026-10-12' AND stock_id <> '-' GROUP BY 1")
    print('trading_orders 2026-10-12：', cur.fetchall())
    cur.execute("SELECT kind, count(*) FROM trading_events WHERE ts >= '2026-10-19 22:00' GROUP BY 1")
    print('trading_events 今晚：', cur.fetchall())
