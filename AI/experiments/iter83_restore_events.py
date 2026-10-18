"""Iteration 83：用交易所檔（證交所 TWT49U／櫃買除權息、證交所 TWTAUU 減資）重寫事件表。
為什麼：backfill_dividend.py（FinMind）對「權」（股票股利）的列 reference_price = before_price（2890 2026-10-07 FinMind 45.40／45.40，
交易所檔 45.40／44.97），用它重建的 adj_close 會漏掉股票股利；Iteration 83 對 42 檔新追蹤股跑過 backfill_dividend，蓋掉了 2018 起的交易所列。
先重寫 2018 起（全市場，和 job_market_daily 同一條路），再補 2000～2017（追蹤股 2018 以前的歷史也改用交易所事件）。
用法（Crawler 目錄）：PYTHONUTF8=1 python ../AI/experiments/iter83_restore_events.py"""
import logging
import os
import sys
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'Crawler'))
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
import market_data  # noqa: E402

r = market_data.refresh_events(date(2018, 1, 1), date.today())
print('2018 起：', {k: (v if k != 'stock_ids' else len(v)) for k, v in r.items()}, flush=True)
r2 = market_data.refresh_events(date(2000, 1, 1), date(2017, 12, 31))
print('2000～2017：', {k: (v if k != 'stock_ids' else len(v)) for k, v in r2.items()}, flush=True)
