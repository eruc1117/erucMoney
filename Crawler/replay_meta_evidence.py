"""只讀：印回放的事實（清單數、檔數、交易日數、範圍、兩個版本的總報酬）給 record_check 當證據。
    node AI/harness/record_check.js --name replay-meta -- python -X utf8 Crawler/replay_meta_evidence.py
"""
import json
import sys
import urllib.request

url = 'http://localhost:8000/trading/engine/replay?start=2018-11-12&end=2024-09-30'
d = json.load(urllib.request.urlopen(url, timeout=120))
if not d.get('available'):
    print(d); sys.exit(1)
print({k: d[k] for k in ('run_id', 'run_name', 'start', 'end', 'n_lists', 'n_days', 'n_stocks', 'notes', 'cached')})
for v in ('engine', 'plain'):
    m = d['variants'][v]['metrics']
    print(v, {k: m[k] for k in ('total_return', 'bench_return', 'ann_active', 'info_ratio', 'rel_mdd')}, d['variants'][v]['stats'])
