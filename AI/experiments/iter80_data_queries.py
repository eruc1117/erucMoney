"""Iteration 80 的資料查詢輸出（給紀錄引用；只看列、不看報酬）：殖利率 > 50 的列是哪幾檔、2018-01～2024-09 殖利率 > 30% 與本益比缺值的列數、
portfolio_runs 全表相對最大落後的最小值。用法（在 Crawler 目錄）：PYTHONUTF8=1 python ../AI/experiments/iter80_data_queries.py"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'Crawler'))
from db.connection import get_conn  # noqa: E402

with get_conn() as c:
    cur = c.cursor()
    cur.execute("""SELECT stock_id, count(*), min(trade_date), max(trade_date), max(dividend_yield), max(dividend_per_share), min(close_price), source
                   FROM market_valuation_daily WHERE dividend_yield < 0 OR dividend_yield > 50 GROUP BY stock_id, source ORDER BY 2 DESC""")
    rows = cur.fetchall()
    print(f'殖利率 < 0 或 > 50 的列：{sum(r[1] for r in rows)} 列、{len(rows)} 檔')
    for r in rows:
        print('  ', r[0], f'{r[1]} 列', r[2], '~', r[3], f'殖利率最大 {r[4]}', f'每股股利 {r[5]}（櫃買才有）', f'收盤最低 {r[6]}（上市才有）', r[7])
    cur.execute("""SELECT count(*) FILTER (WHERE dividend_yield > 30), count(DISTINCT stock_id) FILTER (WHERE dividend_yield > 30),
                          count(*) FILTER (WHERE pe IS NULL), count(*)
                   FROM market_valuation_daily WHERE trade_date BETWEEN '2018-01-01' AND '2024-09-30'""")
    a, b, c_, d = cur.fetchone()
    print(f'2018-01-01～2024-09-30 估值表：{d:,} 列；殖利率 > 30% {a:,} 列、{b} 檔（{a / d:.2%}）；本益比缺值 {c_:,} 列（{c_ / d:.1%}）')
    cur.execute("""SELECT experiment_n, name, segment, (metrics->>'rel_mdd')::float, (metrics->>'tracking_error')::float
                   FROM portfolio_runs WHERE metrics ? 'rel_mdd' ORDER BY (metrics->>'rel_mdd')::float DESC LIMIT 3""")
    print('portfolio_runs 相對最大落後最小（最接近 0）的三列（experiment_n, name, segment, rel_mdd, tracking_error）：')
    for r in cur.fetchall():
        print('  ', r)
    cur.execute("""SELECT experiment_n, name, segment, (metrics->>'tracking_error')::float
                   FROM portfolio_runs WHERE metrics ? 'tracking_error' ORDER BY (metrics->>'tracking_error')::float LIMIT 3""")
    print('portfolio_runs 追蹤誤差最小的三列：')
    for r in cur.fetchall():
        print('  ', r)
    cur.execute("SELECT count(*) FROM portfolio_runs WHERE metrics ? 'rel_mdd'")
    print('有 rel_mdd 的列數', cur.fetchone()[0], '／全表', end=' ')
    cur.execute("SELECT count(*) FROM portfolio_runs")
    print(cur.fetchone()[0])
