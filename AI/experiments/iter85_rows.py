"""Iteration 85 登記前只看列（不看報酬）：
(1) 放空流量（P65／Wang, Yan & Zheng 2020：放空量 ÷ 成交量）在候選池（流動性前 300）內的覆蓋與分佈——借券賣出 `sbl_sell`、融券賣出 `short_sell` 各自與合計的 21 日累計 ÷ 21 日成交股數；
(2) 產業領先股（P50 Hou 2007）：候選池內有產業別的股票數、各產業成員數（≥ 5 的產業數）、上市／上櫃分別。
五個訊號日：2018-07-11、2019-07-11、2020-07-13、2021-07-12、2023-07-11。用法（Crawler 目錄）：PYTHONUTF8=1 python ../AI/experiments/iter85_rows.py"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'Crawler'))
from db.connection import get_conn  # noqa: E402

DATES = ['2018-07-11', '2019-07-11', '2020-07-13', '2021-07-12', '2023-07-11']

POOL_SQL = """
WITH days AS (SELECT DISTINCT trade_date FROM market_daily_prices WHERE trade_date <= %(d)s ORDER BY 1 DESC LIMIT 60),
liq AS (SELECT stock_id, avg(turnover_value) AS liq, count(*) AS n FROM market_daily_prices WHERE trade_date IN (SELECT trade_date FROM days) GROUP BY 1),
pool AS (SELECT l.stock_id FROM liq l JOIN market_daily_prices p ON p.stock_id = l.stock_id AND p.trade_date = %(d)s
         JOIN market_universe u ON u.stock_id = l.stock_id
         WHERE l.n >= 40 AND l.stock_id <> '2330' AND (u.delisted_date IS NULL OR u.delisted_date > %(d)s) ORDER BY l.liq DESC LIMIT 300),
w AS (SELECT DISTINCT trade_date FROM market_daily_prices WHERE trade_date <= %(d)s ORDER BY 1 DESC LIMIT 21)
SELECT p.stock_id, u.market_type, u.industry_type,
       (SELECT count(*) FROM market_margin_daily m WHERE m.stock_id = p.stock_id AND m.trade_date IN (SELECT trade_date FROM w)) AS m_days,
       (SELECT sum(coalesce(sbl_sell, 0)) FROM market_margin_daily m WHERE m.stock_id = p.stock_id AND m.trade_date IN (SELECT trade_date FROM w)) AS sbl21,
       (SELECT sum(coalesce(short_sell, 0)) FROM market_margin_daily m WHERE m.stock_id = p.stock_id AND m.trade_date IN (SELECT trade_date FROM w)) AS ss21,
       (SELECT sum(volume) FROM market_daily_prices q WHERE q.stock_id = p.stock_id AND q.trade_date IN (SELECT trade_date FROM w)) AS vol21
FROM pool p JOIN market_universe u USING (stock_id)
"""


def q(v, p):
    return float(np.nanpercentile(v, p)) if len(v) else float('nan')


with get_conn() as conn:
    cur = conn.cursor()
    cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'market_daily_prices' ORDER BY ordinal_position")
    print('market_daily_prices 欄位：', [r[0] for r in cur.fetchall()])
    for d in DATES:
        cur.execute(POOL_SQL, {'d': d})
        rows = cur.fetchall()
        n = len(rows)
        has = [r for r in rows if r[3] and r[3] >= 17 and r[6]]
        sbl = np.array([float(r[4]) / float(r[6]) * 100 for r in has])
        ss = np.array([float(r[5]) / float(r[6]) * 100 for r in has])
        tot = sbl + ss
        print(f'\n[{d}] 池 {n} 檔（上市 {sum(1 for r in rows if r[1] == "twse")}／上櫃 {sum(1 for r in rows if r[1] == "tpex")}）；'
              f'21 日內信用表 ≥ 17 天且有成交量 {len(has)} 檔')
        for name, v in (('借券賣出 21 日 ÷ 成交量 %', sbl), ('融券賣出 21 日 ÷ 成交量 %', ss), ('合計 %', tot)):
            print(f'  {name}：= 0 的 {int((v == 0).sum())} 檔（{(v == 0).mean() * 100:.1f}%）、P10 {q(v, 10):.3f}、P50 {q(v, 50):.3f}、P90 {q(v, 90):.3f}、max {v.max():.2f}')
        ind = {}
        for r in rows:
            k = (r[1], (r[2] or '').strip())
            if k[1]:
                ind[k] = ind.get(k, 0) + 1
        big = {k: v for k, v in ind.items() if v >= 5}
        print(f'  產業別有值 {sum(ind.values())}／{n} 檔、產業數 {len(ind)}、成員 ≥ 5 的產業 {len(big)} 個（涵蓋 {sum(big.values())} 檔）：'
              + '、'.join(f'{m}{k}{v}' for (m, k), v in sorted(big.items(), key=lambda x: -x[1])[:8]))
