# Iteration 65 證據：三條線末點、保留期快捷區間、TAIEX_TR 涵蓋、N
import json, portfolio_api as pa
from db.connection import get_conn
out = {}
for rid in (68, 69):
    s = pa.get_run(rid, step=1)['series']; f, l = s[0], s[-1]
    out[f'run{rid}'] = {'start': f['d'], 'end': l['d'], 'nav': l['nav'], 'bench': l['bench'], 'idx': l['idx'], 'points': len(s), 'idx_null': sum(p['idx'] is None for p in s)}
s = [p for p in pa.get_run(68, step=1)['series'] if p['d'] >= '2024-10-01']; f, l = s[0], s[-1]
out['run68_holdout_range'] = {'start': f['d'], 'end': l['d'], 'nav': round(l['nav']/f['nav'], 4), 'bench': round(l['bench']/f['bench'], 4), 'idx': round(l['idx']/f['idx'], 4)}
with get_conn() as c:
    cur = c.cursor()
    cur.execute("SELECT count(*), min(trade_date), max(trade_date) FROM index_daily_prices WHERE symbol='TAIEX_TR'"); n, a, b = cur.fetchone()
    out['taiex_tr'] = {'days': n, 'min': str(a), 'max': str(b)}
    cur.execute("SELECT count(*) FROM portfolio_run_series s WHERE s.run_id=68 AND NOT EXISTS (SELECT 1 FROM index_daily_prices i WHERE i.symbol='TAIEX_TR' AND i.trade_date=s.trade_date)")
    out['run68_days_without_index_row'] = cur.fetchone()[0]
    cur.execute("SELECT max(experiment_n), count(*) FROM portfolio_runs"); out['portfolio_runs'] = dict(zip(('max_n', 'rows'), cur.fetchone()))
    cur.execute("SELECT params->>'tsmc_weight' FROM portfolio_runs WHERE id=44"); out['run44_tsmc_weight'] = cur.fetchone()[0]
print(json.dumps(out, ensure_ascii=False, indent=1))
