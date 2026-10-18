"""Iteration 83：追蹤股擴到 68 檔後對全部追蹤股跑一次新鮮度檢查（data_freshness.check，只讀），列出落後的股票。
用法（Crawler 目錄）：PYTHONUTF8=1 python ../AI/experiments/iter83_freshness.py"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'Crawler'))
import data_freshness  # noqa: E402

from db.connection import get_conn  # noqa: E402

with get_conn() as conn:          # check() 預設只看預測比對與持股用到的股票；這裡明確給全部追蹤股
    cur = conn.cursor()
    cur.execute("SELECT stock_id FROM stock_info WHERE is_tracking ORDER BY 1")
    ids = [r[0] for r in cur.fetchall()]
r = data_freshness.check(ids)
print(f'檢查 {len(ids)} 檔追蹤股、回報 {len(r.get("items", []))} 檔')
stale = r.get('stale', [])
print({k: v for k, v in r.items() if k not in ('stocks', 'stale', 'note')})
print(f"落後 {len(stale)} 檔：", [(s['stock_id'], s.get('last_date'), s.get('lag_days', s.get('lag'))) for s in stale][:20])
