"""啟動引擎（紙上）並印狀態給 record_check 當證據（2026-10-09 使用者指示：停損 0、限價 ±2%）。
    node AI/harness/record_check.js --name engine-enable -- python -X utf8 Crawler/engine_enable_evidence.py
"""
import json
import urllib.request

BASE = 'http://localhost:8000'


def call(path, body=None):
    data = json.dumps(body).encode('utf-8') if body is not None else None
    req = urllib.request.Request(f'{BASE}{path}', data=data, headers={'Content-Type': 'application/json'}, method='POST' if body is not None else 'GET')
    return json.load(urllib.request.urlopen(req, timeout=300))


st = call('/trading/engine/config', {'enabled': True, 'mode': 'paper', 'run_id': 44, 'rules': {'stop_loss_pct': 0, 'limit_slip': 0.02}})
print('config →', st)
r = call('/trading/engine/run', {})
print('run_daily →', r)
s = call('/trading/engine/status')
print('status →', {k: s[k] for k in ('engine', 'broker_ready', 'broker_note', 'orders', 'last_list', 'next_signal_date')})
print('rules_text →', s['rules_text'])
