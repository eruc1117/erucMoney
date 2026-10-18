"""Iteration 83：追蹤股三張表（FinMind）對全市場三張表（交易所檔）逐列對照，證明 tracked_sync 可以用交易所表補 FinMind 的缺列。
只讀不寫。用法（Crawler 目錄）：PYTHONUTF8=1 python ../AI/experiments/iter83_compare.py"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'Crawler'))
from db.connection import get_conn  # noqa: E402

with get_conn() as conn:
    cur = conn.cursor()
    cur.execute("SELECT count(*) FILTER (WHERE is_tracking), count(*) FROM stock_info")
    print('stock_info 追蹤 %d／%d 檔' % cur.fetchone())
    cur.execute("""
        SELECT count(*), count(*) FILTER (WHERE s.close_price = m.close_price),
               count(*) FILTER (WHERE s.open_price = m.open_price AND s.high_price = m.high_price AND s.low_price = m.low_price),
               count(*) FILTER (WHERE s.volume = m.volume), count(*) FILTER (WHERE s.volume <> m.volume AND i.market_type = 'tpex'),
               count(*) FILTER (WHERE s.change_value = m.change_value), count(*) FILTER (WHERE s.change_value <> m.change_value),
               count(*) FILTER (WHERE m.change_value IS NULL), count(*) FILTER (WHERE s.adj_close IS NOT NULL AND m.adj_close IS NOT NULL),
               count(*) FILTER (WHERE s.adj_close IS NOT NULL AND m.adj_close IS NOT NULL AND abs(s.adj_close - m.adj_close) <= 0.0005 * m.adj_close)
        FROM stock_daily_prices s JOIN market_daily_prices m USING (stock_id, trade_date) JOIN stock_info i USING (stock_id)
        WHERE s.trade_date >= '2018-01-01' AND i.is_tracking""")
    n, close, ohl, vol, vol_tpex, chg, chg_diff, chg_null, adj_n, adj_eq = cur.fetchone()
    print(f'日線 2018 起共有股票日 {n:,}：收盤相同 {close / n:.1%}、開高低相同 {ohl / n:.1%}、成交量相同 {vol / n:.1%}'
          f'（不同的 {n - vol:,} 列裡上櫃 {vol_tpex:,}）、漲跌相同 {chg / n:.1%}、漲跌不同 {chg_diff}、交易所檔漲跌 NULL {chg_null:,}（{chg_null / n:.1%}）、'
          f'adj_close 兩邊都有 {adj_n:,} 列、差 ≤ 0.05% 的 {adj_eq / adj_n:.1%}')
    cur.execute("""
        SELECT count(*), count(*) FILTER (WHERE s.foreign_investor_buy = m.foreign_net AND s.investment_trust_buy = m.trust_net AND s.dealer_buy = m.dealer_net AND s.total_net_buy = m.total_net)
        FROM stock_chip_analysis s JOIN market_institutional_daily m USING (stock_id, trade_date) JOIN stock_info i USING (stock_id)
        WHERE s.trade_date >= '2018-01-01' AND i.is_tracking""")
    n, eq = cur.fetchone()
    print(f'三大法人 2018 起共有股票日 {n:,}：外資／投信／自營／合計四欄全同 {eq / n:.1%}')
    cur.execute("""
        SELECT count(*), count(*) FILTER (WHERE s.foreign_shares = m.foreign_shares AND s.shares_issued = m.shares_issued),
               count(*) FILTER (WHERE abs(s.foreign_ratio - m.foreign_ratio) <= 0.011)
        FROM stock_foreign_holding s JOIN market_foreign_holding_daily m USING (stock_id, trade_date) JOIN stock_info i USING (stock_id)
        WHERE s.trade_date >= '2018-01-01' AND i.is_tracking""")
    n, eq, ratio = cur.fetchone()
    print(f'外資持股 2018 起共有股票日 {n:,}：持股股數與發行股數相同 {eq / n:.1%}、比率差 ≤ 0.01 {ratio / n:.1%}')
    cur.execute("""
        SELECT i.stock_id, count(s.*), count(s.*) FILTER (WHERE s.adj_close IS NULL), min(s.trade_date), max(s.trade_date),
               (SELECT count(*) FROM stock_chip_analysis c WHERE c.stock_id = i.stock_id), (SELECT count(*) FROM stock_foreign_holding h WHERE h.stock_id = i.stock_id)
        FROM stock_info i LEFT JOIN stock_daily_prices s USING (stock_id) WHERE i.is_tracking GROUP BY 1 ORDER BY 1""")
    rows = cur.fetchall()
    bad = [r for r in rows if r[2] or r[1] == 0]
    print(f'追蹤股 {len(rows)} 檔：行情 {sum(r[1] for r in rows):,} 列、adj_close NULL {sum(r[2] for r in rows):,} 列、籌碼 {sum(r[5] for r in rows):,} 列、外資持股 {sum(r[6] for r in rows):,} 列；最新交易日 {max(r[4] for r in rows)}')
    print('最早交易日分布：', sorted((r[3].isoformat(), r[0]) for r in rows)[:3], '…', sorted((r[3].isoformat(), r[0]) for r in rows)[-3:])
    if bad:
        print('有問題：', bad)
