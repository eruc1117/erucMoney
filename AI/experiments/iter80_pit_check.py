"""估值表點時性檢查（Iteration 80，strategy-critic 要求；不算 N）：
（1）上市股「股利年度」由 106 切到 107 的日期是否因股而異（點時）還是全市場同一天（事後重算）；
（2）估值表的收盤價是否等於同日 market_daily_prices 的收盤價；
（3）portfolio_runs 裡含 dy／ep 的 run 是否只有 #99～#102 且全是 dev。
用法（在 Crawler 目錄）：PYTHONUTF8=1 python ../AI/experiments/iter80_pit_check.py"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'Crawler'))
from db.connection import get_conn  # noqa: E402

with get_conn() as c:
    cur = c.cursor()
    cur.execute("""
        WITH x AS (
          SELECT stock_id, trade_date, dividend_year,
                 lag(dividend_year) OVER (PARTITION BY stock_id ORDER BY trade_date) AS prev
          FROM market_valuation_daily WHERE source = 'twse' AND trade_date BETWEEN '2018-01-01' AND '2018-12-31')
        SELECT trade_date, count(*) FROM x WHERE prev IS NOT NULL AND dividend_year = prev + 1 GROUP BY 1 ORDER BY 2 DESC""")
    rows = cur.fetchall()
    total = sum(r[1] for r in rows)
    print(f'上市股 2018 年內股利年度 +1 的切換（2018-01-02 的值是 105）：{total} 檔次、分布在 {len(rows)} 個交易日；最多的五天：', [(str(d), n) for d, n in rows[:5]])
    print('   切換日前五名合計占比 {:.0%}'.format(sum(n for _, n in rows[:5]) / max(total, 1)))
    cur.execute("""
        WITH x AS (
          SELECT stock_id, trade_date, dividend_year,
                 lag(dividend_year) OVER (PARTITION BY stock_id ORDER BY trade_date) AS prev
          FROM market_valuation_daily WHERE source = 'tpex' AND trade_date BETWEEN '2018-01-01' AND '2018-12-31')
        SELECT trade_date, count(*) FROM x WHERE prev IS NOT NULL AND dividend_year = prev + 1 GROUP BY 1 ORDER BY 2 DESC""")
    rows = cur.fetchall()
    total = sum(r[1] for r in rows)
    print(f'上櫃股 2018 年內股利年度 +1 的切換：{total} 檔次、分布在 {len(rows)} 個交易日；最多的五天：', [(str(d), n) for d, n in rows[:5]])
    cur.execute("""
        SELECT count(*), count(*) FILTER (WHERE abs(v.close_price - p.close_price) > 0.005)
        FROM market_valuation_daily v JOIN market_daily_prices p USING (stock_id, trade_date)
        WHERE v.source = 'twse' AND v.close_price IS NOT NULL AND v.trade_date BETWEEN '2018-01-01' AND '2024-09-30'""")
    n, bad = cur.fetchone()
    print(f'上市估值表收盤價對 market_daily_prices 同日收盤：{n:,} 列，不等的 {bad:,}（{bad / max(n, 1):.3%}）')
    print('櫃買檔的股利年度與每股股利在年內是否變動（1264 德麥、3105 穩懋，2018～2019）：')
    for sid in ('1264', '3105'):
        cur.execute("""SELECT dividend_year, dividend_per_share, min(trade_date), max(trade_date), count(*) FROM market_valuation_daily
                       WHERE stock_id = %s AND trade_date BETWEEN '2018-01-01' AND '2019-12-31' GROUP BY 1, 2 ORDER BY 3""", (sid,))
        print('  ', sid, [(y, float(dps), str(a), str(b), n) for y, dps, a, b, n in cur.fetchall()])
    print('   對照（網路，2026-10-17 WebSearch 摘要，未留存網頁）：穩懋現金股利 2018 年除息 7.00 元（2018-07-03）、2019 年 5.00 元（2019-07-01）'
          '［https://www.wantgoo.com/stock/3105/enterprise-value/dividend-yield］；德麥 2017 年度 10.5 元、2018 年度 11 元［https://www.wantgoo.com/stock/1264/profitability/dividend-payout-ratio］——'
          '櫃買檔在 2018-01-02 就印 7.00／10.5（年度 106），早於當年春天的董事會決議：櫃買的歷史殖利率**不是點時**，年初到公告前含未來資訊。')
    print('本益比隱含的 EPS（日線收盤 ÷ 估值表本益比，取兩位）在 2018 年的切換日——在季報日跳就是點時：')
    for sid in ('1264', '3105', '1101', '2330'):
        cur.execute("""SELECT round(p.close_price / v.pe, 2), min(v.trade_date), count(*)
                       FROM market_valuation_daily v JOIN market_daily_prices p USING (stock_id, trade_date)
                       WHERE v.stock_id = %s AND v.pe IS NOT NULL AND v.trade_date BETWEEN '2018-01-01' AND '2018-12-31'
                       GROUP BY 1 ORDER BY 2""", (sid,))
        rows = cur.fetchall()
        print('  ', sid, ('tpex' if sid in ('1264', '3105') else 'twse'), [(float(e), str(d), n) for e, d, n in rows])
    print('全部上櫃股：隱含 EPS（日線收盤 ÷ 本益比）對前一交易日變動 > 1% 的檔次，2018 年按日排序前五、以及 1 月第一個交易日——若 1 月 2 日是大量切換日就是和殖利率一樣的年度重算：')
    cur.execute("""
        WITH e AS (
          SELECT v.stock_id, v.trade_date, p.close_price / v.pe AS eps
          FROM market_valuation_daily v JOIN market_daily_prices p USING (stock_id, trade_date)
          WHERE v.source = 'tpex' AND v.pe IS NOT NULL AND v.pe > 0 AND v.trade_date BETWEEN '2017-12-25' AND '2018-12-31'),
        x AS (SELECT stock_id, trade_date, eps, lag(eps) OVER (PARTITION BY stock_id ORDER BY trade_date) AS prev FROM e)
        SELECT trade_date, count(*) FILTER (WHERE abs(eps / prev - 1) > 0.01), count(*) FROM x
        WHERE prev IS NOT NULL AND trade_date >= '2018-01-01' GROUP BY 1 ORDER BY 2 DESC""")
    rows = cur.fetchall()
    print('   前五天：', [(str(d), c, t) for d, c, t in rows[:5]])
    print('   2018-01-02 無法檢查（表從該日起、沒有前一日）；改看 2019、2020 年 1 月第一個交易日對前一交易日的變動：')
    for y in (2019, 2020):
        cur.execute("""
            WITH e AS (
              SELECT v.stock_id, v.trade_date, p.close_price / v.pe AS eps
              FROM market_valuation_daily v JOIN market_daily_prices p USING (stock_id, trade_date)
              WHERE v.source = 'tpex' AND v.pe IS NOT NULL AND v.pe > 0 AND v.trade_date BETWEEN %s AND %s),
            x AS (SELECT stock_id, trade_date, eps, lag(eps) OVER (PARTITION BY stock_id ORDER BY trade_date) AS prev FROM e)
            SELECT trade_date, count(*) FILTER (WHERE abs(eps / prev - 1) > 0.01), count(*) FROM x
            WHERE prev IS NOT NULL AND trade_date >= %s GROUP BY 1 ORDER BY 1 LIMIT 1""", (f'{y - 1}-12-20', f'{y}-01-10', f'{y}-01-01'))
        r = cur.fetchone()
        print(f'   {y} 年 1 月第一個交易日：', (str(r[0]), r[1], r[2]) if r else None, '（變動 > 1% 的檔次／有前一日可比的檔數）')
    print('上市股財報年/季（fin_period）在 2018 年的切換日分布前五（逐股在季報公告後切換就是點時）：')
    cur.execute("""
        WITH x AS (SELECT stock_id, trade_date, fin_period, lag(fin_period) OVER (PARTITION BY stock_id ORDER BY trade_date) AS prev
                   FROM market_valuation_daily WHERE source = 'twse' AND trade_date BETWEEN '2017-12-25' AND '2018-12-31')
        SELECT trade_date, count(*) FROM x WHERE prev IS NOT NULL AND fin_period <> prev AND trade_date >= '2018-01-01' GROUP BY 1 ORDER BY 2 DESC""")
    rows = cur.fetchall()
    print('   ', [(str(d), c) for d, c in rows[:5]], f'；共 {len(rows)} 個切換日、{sum(c for _, c in rows)} 檔次')
    print('兩市 1 月第一個交易日的股利年度眾數（民國年 − 1 ＝ 去年度；民國年 − 2 ＝ 前年度）：')
    for y in (2018, 2019, 2020):
        cur.execute("""SELECT source, mode() WITHIN GROUP (ORDER BY dividend_year) FROM market_valuation_daily
                       WHERE trade_date = (SELECT min(trade_date) FROM market_valuation_daily WHERE trade_date >= %s) GROUP BY 1 ORDER BY 1""", (f'{y}-01-01',))
        print(f'   {y}（民國 {y - 1911}）：', cur.fetchall())
    cur.execute("""SELECT experiment_n, name, (metrics->>'tracking_error')::float FROM portfolio_runs
                   WHERE segment = 'dev' AND metrics ? 'tracking_error' ORDER BY (metrics->>'tracking_error')::float LIMIT 4""")
    print('portfolio_runs 開發期追蹤誤差最小的四列：', cur.fetchall())
    print('上市檔的股利年度切換（2330 台積電）：')
    cur.execute("""SELECT dividend_year, min(trade_date), max(trade_date) FROM market_valuation_daily
                   WHERE stock_id = '2330' AND trade_date BETWEEN '2018-01-01' AND '2019-12-31' GROUP BY 1 ORDER BY 2""")
    print('  ', [(y, str(a), str(b)) for y, a, b in cur.fetchall()], '——105 → 106 在 2018-02-26（董事會之後），逐股不同日：上市檔是點時。')
    cur.execute("SELECT experiment_n, name, segment FROM portfolio_runs WHERE signal ~ '(^|\\+)(dy|ep)($|\\+|~)' ORDER BY 1")
    print('portfolio_runs 含 dy／ep 的 run：', cur.fetchall())
