"""第十代第二批跑之前只看列：借券賣出餘額 = 0 的列比例（`nsir` 的並列、`momsx` 保留的那群）、流動性前 300 裡沒有融資融券列的比例、融資餘額 21 日變動要兩天都有列的覆蓋。
不看報酬。用法（Crawler 目錄）：PYTHONUTF8=1 python ../AI/experiments/iter82_sir_rows.py"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'Crawler'))
from db.connection import get_conn  # noqa: E402

with get_conn() as conn:
    cur = conn.cursor()
    cur.execute("""
        WITH p AS (
          SELECT p.stock_id, p.trade_date, rank() OVER (PARTITION BY p.trade_date ORDER BY p.turnover_value DESC NULLS LAST) AS rk,
                 m.sbl_balance, m.margin_balance
          FROM market_daily_prices p LEFT JOIN market_margin_daily m USING (stock_id, trade_date)
          WHERE p.trade_date BETWEEN '2018-01-01' AND '2024-09-30' AND p.adj_close > 0)
        SELECT CASE WHEN rk <= 300 THEN '1-300' WHEN rk <= 1000 THEN '301-1000' ELSE '>1000' END AS bucket,
               count(*) AS n, count(*) FILTER (WHERE sbl_balance IS NULL) AS no_row, count(*) FILTER (WHERE sbl_balance = 0) AS sbl0,
               count(*) FILTER (WHERE sbl_balance > 0) AS sbl_pos
        FROM p GROUP BY 1 ORDER BY 1""")
    for b, n, no_row, z, pos in cur.fetchall():
        print(f'{b}: 股票日 {n:,}；沒融資融券列 {no_row / n:.1%}；借券餘額 = 0 {z / n:.1%}；> 0 {pos / n:.1%}')
    cur.execute("""SELECT count(*) FILTER (WHERE sbl_balance = 0), count(*), count(DISTINCT stock_id) FROM market_margin_daily WHERE trade_date BETWEEN '2018-01-01' AND '2024-09-30'""")
    z, n, ns = cur.fetchone()
    print(f'全表 2018-01～2024-09：借券餘額 = 0 的列 {z:,}／{n:,}（{z / n:.1%}）、{ns} 檔')
