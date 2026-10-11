"""只讀：用正式策略的參數把保留期（2024-10-01 → 最新行情）再算一次但**不存**（save=False，不是新實驗），
印指標給 record_check 當證據——用在資料修正（0050 分割還原）之後，看凍結的 #67 和修正後差多少。
    node AI/harness/record_check.js --name holdout-corrected-preview -- python -X utf8 Crawler/holdout_preview_evidence.py
"""
import json
from datetime import date

import portfolio_official as po

st = po.state()
p = po._params(st['candidate_run_id'])
res = po._run_with(p, 'holdout', po.HOLDOUT_START, date.today(), 'holdout-preview', '', save=False)
m = res['metrics']
print('corrected holdout (not saved):', json.dumps({k: m.get(k) for k in ('start', 'end', 'months', 'n_rebalances', 'skipped_months', 'total_return_port', 'total_return_bench',
                                                                            'cagr_port', 'cagr_bench', 'ann_active', 'tracking_error', 'info_ratio', 'mdd_port', 'mdd_bench', 'rel_mdd',
                                                                            'monthly_win_rate', 'turnover_annual', 'unfilled')}, ensure_ascii=False))
print('yearly_active:', m.get('yearly_active'))
