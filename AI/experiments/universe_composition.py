"""全市場表涵蓋範圍（只讀）：market_universe 依市場別／證券種類／在市與否的檔數，market_daily_prices 最近一日的檔數與起訖日。
用法（Crawler 目錄）：PYTHONUTF8=1 python ../AI/experiments/universe_composition.py"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'Crawler'))
from db.connection import get_conn  # noqa: E402

with get_conn() as conn:
    cur = conn.cursor()
    cur.execute("""SELECT coalesce(market_type, '(NULL)'), coalesce(security_type, '(NULL)'), delisted_date IS NULL, count(*)
                   FROM market_universe GROUP BY 1, 2, 3 ORDER BY 1, 2, 3""")
    print('market_universe（市場別、證券種類、在市、檔數）：')
    for r in cur.fetchall():
        print('  ', r)
    cur.execute("SELECT count(*), count(*) FILTER (WHERE delisted_date IS NULL), min(listing_date), max(listing_date) FROM market_universe")
    print('總計：%d 檔、在市 %d 檔、上市日 %s～%s' % cur.fetchone())
    cur.execute("SELECT max(trade_date) FROM market_daily_prices")
    last = cur.fetchone()[0]
    cur.execute("""SELECT coalesce(u.market_type, '(NULL)'), count(*) FROM market_daily_prices p JOIN market_universe u USING (stock_id)
                   WHERE p.trade_date = %s GROUP BY 1 ORDER BY 1""", (last,))
    print(f'market_daily_prices 最近一日 {last} 各市場別檔數：', cur.fetchall())
    cur.execute("SELECT min(trade_date), max(trade_date), count(DISTINCT stock_id) FROM market_daily_prices")
    print('market_daily_prices 起訖與曾出現的股票數：%s～%s、%d 檔' % cur.fetchone())
    cur.execute("SELECT stock_id, stock_name, market_type, security_type FROM market_universe WHERE stock_id IN ('0050','2330','6446','7769','8913','00878')")
    print('例子：', cur.fetchall())
