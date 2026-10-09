"""只讀：不帶 token 打正式 Node API 的公開模擬端點，印結果給 record_check 當證據（Iteration 60）。
    node AI/harness/record_check.js --name sim-anon -- python -X utf8 Crawler/sim_anon_evidence.py
"""
import json
import sys
import urllib.request

BASE = 'http://localhost:3001'
body = json.dumps({'text': '2024-01-15 買 2330 10股\n2024-01-15 買 0050 100000元\n2024-06-03 賣 2330 全部',
                   'start': '2024-01-02', 'end': '2024-09-30', 'capital': 300000}).encode('utf-8')
req = urllib.request.Request(f'{BASE}/sim/run', data=body, headers={'Content-Type': 'application/json'}, method='POST')
d = json.load(urllib.request.urlopen(req, timeout=120))
if not d.get('available'):
    print(d); sys.exit(1)
print('POST /sim/run（匿名）', {k: d[k] for k in ('available', 'start', 'end', 'capital', 'n_instructions', 'n_days', 'realized_pnl', 'costs')})
print('metrics', {k: d['metrics'][k] for k in ('total_return', 'bench_return', 'active_return', 'ann_active', 'mdd_port')})
print('trades', [(t['line'], t['asked'], t['date'], t['side'], t['stock_id'], t['shares'], t['price']) for t in d['trades']])
print('skipped', d['skipped'], 'errors', d['errors'], 'final', d['final'])
r = urllib.request.urlopen(f'{BASE}/sim/replay?start=2024-01-11&end=2024-03-31', timeout=120)
rp = json.load(r)
print('GET /sim/replay（匿名） status', r.status, {k: rp.get(k) for k in ('available', 'start', 'end', 'n_lists', 'cached')})
