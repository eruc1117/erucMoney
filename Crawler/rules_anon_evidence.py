"""只讀：不帶 token 打正式 Node API 的條件規則模擬，印結果給 record_check 當證據（Iteration 61）。
    node AI/harness/record_check.js --name rules-anon -- python -X utf8 Crawler/rules_anon_evidence.py
"""
import json
import sys
import urllib.request

STOP = [   # 頁面模板「停損停利」套在 2330（--template stop）
    {'stock_id': '2330', 'when': {'type': 'on_date', 'date': '2024-01-02'}, 'then': {'side': 'buy', 'qty': 100000, 'unit': '元'}, 'max_times': 1, 'only_if_flat': False},
    {'stock_id': '2330', 'when': {'type': 'loss_from_cost', 'x': 10}, 'then': {'side': 'sell', 'unit': '全部'}, 'max_times': None, 'only_if_flat': False},
    {'stock_id': '2330', 'when': {'type': 'gain_from_cost', 'x': 20}, 'then': {'side': 'sell', 'unit': '全部'}, 'max_times': None, 'only_if_flat': False},
]
rules = [
    {'stock_id': '2330', 'when': {'type': 'cross_above_ma', 'n': 20}, 'then': {'side': 'buy', 'qty': 100000, 'unit': '元'}, 'max_times': None, 'only_if_flat': True},
    {'stock_id': '2330', 'when': {'type': 'cross_below_ma', 'n': 20}, 'then': {'side': 'sell', 'unit': '全部'}, 'max_times': None, 'only_if_flat': False},
    {'stock_id': '0050', 'when': {'type': 'monthly_day', 'd': 5}, 'then': {'side': 'buy', 'qty': 10000, 'unit': '元'}, 'max_times': None, 'only_if_flat': False},
]
if '--template' in sys.argv and sys.argv[sys.argv.index('--template') + 1] == 'stop':
    rules = STOP
capital = 1_000_000 if rules is STOP else 300000
body = json.dumps({'rules': rules, 'start': '2024-01-02', 'end': '2024-09-30', 'capital': capital}).encode('utf-8')
req = urllib.request.Request('http://localhost:3001/sim/rules', data=body, headers={'Content-Type': 'application/json'}, method='POST')
d = json.load(urllib.request.urlopen(req, timeout=180))
if not d.get('available'):
    print(d); sys.exit(1)
print('POST /sim/rules（匿名）', {k: d[k] for k in ('available', 'start', 'end', 'capital', 'n_rules', 'n_days', 'realized_pnl', 'costs')})
print('metrics', {k: d['metrics'][k] for k in ('total_return', 'bench_return', 'active_return', 'mdd_port')})
print('rules', d['rules'])
print('trades', [(t['date'], t['rule'], t['side'], t['stock_id'], t['shares'], t['price']) for t in d['trades']][:12], '… 共', len(d['trades']))
print('triggers', len(d['triggers']), 'final', d['final'])
