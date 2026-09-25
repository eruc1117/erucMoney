"""
線上 M3 模型診斷（Iteration 9）

直接走 model3_chip.get_signal 的線上推論路徑，對全部追蹤股票印出訊號分布，
確認信心門檻與賣出政策的實際效果（Iteration 9 發現 v1 門檻 0.45 會擋下全部 22 檔）。
"""
import os
import sys

import joblib
import pandas as pd

CRAWLER_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'Crawler')
sys.path.insert(0, CRAWLER_DIR)

from db.connection import get_conn   # noqa: E402
import model3_chip as m3             # noqa: E402

MODEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          'saved_models', 'm3_chip_rf.joblib')

bundle = joblib.load(MODEL_PATH)
print(f"模型版本 v{bundle.get('version', 1)}　trained_at={bundle.get('trained_at')}")
print(f"門檻={bundle.get('proba_gate')}　賣出政策={bundle.get('sell_policy')}")
wf = bundle.get('metrics_walk_forward', {})
if wf:
    print(f"走查方向準確率={wf.get('dir_acc'):.2%}　"
          f"買進 {wf.get('n_long')} 次 {wf.get('long_dir_acc'):.2%} "
          f"平均 {wf.get('long_avg_ret'):+.2%}")
print()

with get_conn() as conn:
    stocks = pd.read_sql("SELECT stock_id FROM stock_info WHERE is_tracking = true "
                         "ORDER BY stock_id", conn)['stock_id'].tolist()

rows = []
for sid in stocks:
    r = m3.get_signal(sid)
    rows.append({'stock_id': sid, 'signal': r['signal'],
                 'confidence': r['confidence'], 'engine': r.get('engine', 'rule'),
                 'reason': r['reason'][:58]})

out = pd.DataFrame(rows)
pd.set_option('display.width', 220)
print(out.to_string(index=False))

print('\n訊號分布：', out['signal'].value_counts().to_dict())
print('推論引擎：', out['engine'].value_counts().to_dict())
print(f"實際出手（非 Hold）：{(out['signal'] != 'Hold').sum()} / {len(out)} 檔")
