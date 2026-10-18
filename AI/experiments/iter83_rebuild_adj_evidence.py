"""Iteration 83 收尾（只讀）：adj_close 重建後的旁證——三檔（1529、2364、3043）有沒有出現在任何回測持股裡（有的話那些 run 的輸入已變）、
`rebuild_adj_close.load_events` 警告略過的 8913 2018-06-04 那筆是什麼。用法（Crawler 目錄）：PYTHONUTF8=1 python ../AI/experiments/iter83_rebuild_adj_evidence.py"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'Crawler'))
from db.connection import get_conn  # noqa: E402

with get_conn() as conn:
    cur = conn.cursor()
    cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' AND table_name LIKE 'portfolio%%' ORDER BY 1")
    tables = [r[0] for r in cur.fetchall()]
    print('portfolio 表：', tables)
    for t in tables:
        cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name = %s AND column_name IN ('stock_id', 'run_id') ORDER BY 1", (t,))
        cols = [r[0] for r in cur.fetchall()]
        if cols == ['run_id', 'stock_id']:
            cur.execute(f"SELECT stock_id, count(DISTINCT run_id), count(*) FROM {t} WHERE stock_id IN ('1529','2364','3043') GROUP BY 1")
            print(f'{t} 裡三檔出現：', cur.fetchall())
            cur.execute(f"""SELECT p.stock_id, p.run_id, r.name, r.segment, min(p.rebalance_date), max(p.rebalance_date) FROM {t} p JOIN portfolio_runs r ON r.id = p.run_id
                            WHERE p.stock_id IN ('1529','2364','3043') GROUP BY 1, 2, 3, 4 ORDER BY 1, 2""")
            print(f'{t} 哪些 run：', cur.fetchall())
    cur.execute("SELECT count(*) FROM portfolio_runs"); print('portfolio_runs N：', cur.fetchone()[0])
    cur.execute("SELECT stock_id, ex_date, before_price, reference_price, dividend_type FROM stock_dividend_result WHERE stock_id = '8913' AND ex_date = '2018-06-04'")
    print('8913 2018-06-04 事件列：', cur.fetchall())
    cur.execute("SELECT trade_date, close_price, adj_close FROM market_daily_prices WHERE stock_id = '8913' AND trade_date BETWEEN '2018-05-28' AND '2018-06-06' ORDER BY 1")
    print('8913 行情：', cur.fetchall())
    cur.execute("SELECT stock_id, stock_name, market_type, delisted_date FROM market_universe WHERE stock_id IN ('8913','1529','2364','3043')")
    print('市場別：', cur.fetchall())
