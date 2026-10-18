"""Iteration 83 審查補證據（只讀；FinMind 1 次呼叫）：FinMind 與交易所的除權息列對照、事件表 2018 以前的筆數、2014～2016 減資筆數、
追蹤股 adj_close NULL 的列是不是 close_price ≤ 0、2327 的 FinMind 起日、6446 上櫃期間成交量差、全市場減資 factor ≥ 5、追蹤股 factor > 5 的事件、
月營收列數、別名筆數、7769／6446 市場別。用法（Crawler 目錄）：PYTHONUTF8=1 python ../AI/experiments/iter83_evidence.py"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'Crawler'))
from db.connection import get_conn  # noqa: E402
from scrapers.finmind_scraper import FinMindScraper  # noqa: E402

NEW = "2454 2308 2317 3711 2383 2881 1303 2891 3017 2882 2887 2345 2382 2360 2885 2884 2408 2059 3443 2357 6669 3653 2886 2890 3008 2301 2412 3665 2892 2880 4958 2368 6446 1216 2395 8046 7769 5880 2603 4904 3045 6505".split()

fm = {(r['stock_id'], r['ex_date']): r for r in FinMindScraper(stock_ids=['2890', '2313'], start_date=date(2026, 1, 1)).fetch_dividend_results()}
with get_conn() as conn:
    cur = conn.cursor()
    cur.execute("SELECT stock_id, ex_date, before_price, reference_price, dividend_type FROM stock_dividend_result WHERE stock_id IN ('2890','2313') AND ex_date >= '2026-01-01' ORDER BY 1, 2")
    print('除權息列 FinMind 對 交易所（事件表現值）：')
    for sid, d, b, r, t in cur.fetchall():
        f = fm.get((sid, d))
        print(f'  {sid} {d} {t}：FinMind {f["before_price"] if f else None}／{f["reference_price"] if f else None}　交易所 {b}／{r}')
    cur.execute("SELECT count(*), min(ex_date) FROM stock_dividend_result WHERE ex_date < '2018-01-01'"); print('事件表 2018 以前除權息：%d 筆、最早 %s' % cur.fetchone())
    cur.execute("SELECT count(*), count(DISTINCT stock_id) FROM stock_capital_reduction WHERE ex_date < '2018-01-01'"); print('事件表 2018 以前減資：%d 筆、%d 檔' % cur.fetchone())
    cur.execute("SELECT count(*) FROM stock_capital_reduction WHERE ex_date BETWEEN '2014-01-01' AND '2016-12-31'"); print('減資 2014～2016：%d 筆' % cur.fetchone())
    cur.execute("SELECT stock_id, ex_date, before_price, reference_price, reason FROM stock_capital_reduction WHERE stock_id = '2408'"); print('2408 減資：', cur.fetchall())
    cur.execute("""SELECT count(*), count(*) FILTER (WHERE close_price IS NULL OR close_price <= 0), count(DISTINCT stock_id)
                   FROM stock_daily_prices s JOIN stock_info i USING (stock_id) WHERE i.is_tracking AND adj_close IS NULL""")
    print('追蹤股 adj_close NULL：%d 列、其中 close_price ≤ 0 或 NULL %d 列、%d 檔' % cur.fetchone())
    cur.execute("""SELECT count(*) FROM stock_daily_prices s JOIN stock_info i USING (stock_id) WHERE i.is_tracking AND adj_close IS NOT NULL AND (close_price IS NULL OR close_price <= 0)""")
    print('追蹤股 close ≤ 0 但 adj 有值：%d 列' % cur.fetchone())
    cur.execute("SELECT min(trade_date), max(trade_date), count(*) FROM stock_daily_prices WHERE stock_id = '2327'"); print('2327 行情：%s ～ %s、%d 列' % cur.fetchone())
    cur.execute("SELECT min(trade_date) FROM stock_daily_prices WHERE stock_id = '2327' AND trade_date > '2025-01-01' AND volume IS NOT NULL"); print('（補列前 FinMind 的 2327 起日是 2025-08-08，見 logs/backfill_prices_iter83 之前的 stock_daily_prices；這裡只驗現值）')
    cur.execute("""SELECT count(*), min(s.trade_date), max(s.trade_date), round(avg((s.volume - m.volume)::numeric / NULLIF(m.volume, 0)) * 100, 2)
                   FROM stock_daily_prices s JOIN market_daily_prices m USING (stock_id, trade_date) WHERE stock_id = '6446' AND s.trade_date >= '2018-01-01' AND s.volume <> m.volume""")
    print('6446 成交量不同：%d 列、%s ～ %s、FinMind 平均多 %s%%' % cur.fetchone())
    cur.execute("SELECT stock_id, ex_date, round(reference_price / before_price, 2) FROM stock_capital_reduction WHERE ex_date >= '2018-01-01' AND reference_price / before_price >= 5 ORDER BY 2")
    print('全市場 2018 起減資 factor ≥ 5：', cur.fetchall())
    cur.execute("""SELECT r.stock_id, r.ex_date, round(r.reference_price / r.before_price, 2) FROM stock_capital_reduction r JOIN stock_info i USING (stock_id)
                   WHERE i.is_tracking AND r.reference_price / r.before_price >= 5""")
    print('追蹤股減資 factor ≥ 5：', cur.fetchall())
    cur.execute("SELECT count(*), count(DISTINCT stock_id) FROM stock_revenue_announce WHERE stock_id = ANY(%s)", (NEW,)); print('新 42 檔月營收：%d 列、%d 檔' % cur.fetchone())
    cur.execute("SELECT count(*) FROM instrument_alias WHERE ticker = ANY(%s)", (NEW,)); print('新 42 檔別名：%d 筆' % cur.fetchone())
    cur.execute("SELECT stock_id, market_type FROM stock_info WHERE stock_id IN ('7769', '6446')"); print('市場別現值：', cur.fetchall())
    cur.execute("SELECT count(*), count(*) FILTER (WHERE is_tracking) FROM stock_info"); print('stock_info：%d 檔、追蹤 %d 檔' % cur.fetchone())
