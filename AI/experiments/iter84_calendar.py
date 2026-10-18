"""Iteration 84 審查補證據（只讀）：2021-12-31 與 2021-12-30 在 market_daily_prices 的列數——dev 段末 12-31 有沒有交易。
用法（Crawler 目錄）：PYTHONUTF8=1 python ../AI/experiments/iter84_calendar.py"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'Crawler'))
from db.connection import get_conn  # noqa: E402

with get_conn() as conn:
    cur = conn.cursor()
    cur.execute("SELECT trade_date, count(*) FROM market_daily_prices WHERE trade_date BETWEEN '2021-12-29' AND '2022-01-03' GROUP BY 1 ORDER BY 1")
    print('market_daily_prices 2021-12-29～2022-01-03 各日列數：', cur.fetchall())
    cur.execute("SELECT max(trade_date) FROM market_daily_prices WHERE trade_date <= '2021-12-31'")
    print('2021-12-31 以前最後一個交易日：', cur.fetchone()[0])
