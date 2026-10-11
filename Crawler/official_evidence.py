"""只讀：印正式策略相關的資料事實給 record_check 當證據（Iteration 64 審查要的）。
    node AI/harness/record_check.js --name official-evidence -- python -X utf8 Crawler/official_evidence.py
"""
from db.connection import get_conn

with get_conn() as conn:
    with conn.cursor() as cur:
        cur.execute("SELECT filename FROM _migrations WHERE filename LIKE '027%'"); print('migrations 027:', cur.fetchall())
        cur.execute("SELECT id, name, tag, (metrics->>'total_return_port')::float, (metrics->>'total_return_bench')::float, (metrics->>'start'), (metrics->>'end') FROM portfolio_runs WHERE id IN (67, 68, 69) ORDER BY id")
        print('runs 67/68 (id, name, tag, total_port, total_bench, start, end):'); [print('  ', r) for r in cur.fetchall()]
        for rid in (67, 69):
            cur.execute("SELECT rebalance_date FROM portfolio_positions WHERE run_id = %s GROUP BY 1 ORDER BY 1", (rid,))
            rds = [str(r[0]) for r in cur.fetchall()]; print(f'#{rid} rebalance dates:', len(rds), rds[:3], '…', rds[-2:])
        cur.execute("SELECT metrics FROM portfolio_runs WHERE id = 69"); m = cur.fetchone()[0]
        print('#69 metrics:', {k: m.get(k) for k in ('start','end','months','n_rebalances','skipped_months','total_return_port','total_return_bench','cagr_port','cagr_bench','ann_active','tracking_error','info_ratio','mdd_port','mdd_bench','rel_mdd','monthly_win_rate','turnover_annual','cost_drag_annual','tsmc_weight_mean')})
        print('#69 yearly:', m.get('yearly_active'))
        cur.execute("SELECT id, tag, notes FROM portfolio_runs WHERE id IN (67, 69)"); print('tags:', [(a, b, (c or '')[:60]) for a, b, c in cur.fetchall()])
        cur.execute("SELECT holdout_run_id, live_run_id FROM portfolio_official"); print('official ids:', cur.fetchone())
        cur.execute("SELECT count(*), min(trade_date), max(trade_date) FROM stock_daily_prices WHERE stock_id='0050' AND trade_date BETWEEN '2025-06-11' AND '2025-06-17'")
        print('0050 rows 2025-06-11~17:', cur.fetchone())
        cur.execute("SELECT count(DISTINCT trade_date), min(trade_date), max(trade_date) FROM market_daily_prices WHERE trade_date BETWEEN '2025-06-11' AND '2025-06-17'")
        print('market trading days 2025-06-11~17:', cur.fetchone())
        cur.execute("""SELECT to_char(revenue_month,'YYYY-MM') m, count(*) FILTER (WHERE announce_date IS NOT NULL) n_ann,
                              count(*) FILTER (WHERE announce_date IS NOT NULL AND date_trunc('month', announce_date) = date_trunc('month', revenue_month)) same_month
                       FROM stock_revenue_announce WHERE revenue_month BETWEEN '2024-04-01' AND '2026-09-01' GROUP BY 1 ORDER BY 1""")
        print('revenue announce (month, with_date, same_month_as_revenue):'); [print('  ', r) for r in cur.fetchall()]
