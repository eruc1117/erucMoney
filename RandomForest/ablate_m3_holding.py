"""
M3 籌碼模型消融：外資真實持股（Iteration 36）
──────────────────────────────────────────
M3 是三個模型裡最該受惠於持股資料的一個——它本來就只看籌碼。
買賣超是流量、持股是存量；M3 現在只有流量。

與 `ablate_m3_exog.py` 分開跑，原因是樣本區間：夜盤／韓日把樣本砍到 2018 起，
持股資料則與籌碼同樣從 2012-05 起。要測持股，就該在 2012 起的完整樣本上測，
否則比的又是資料量不是特徵（Iteration 30 立的規矩）。

判定沿用 M3 口徑：買進方向準確率須高出現行 +1 個百分點，且平均報酬不得變差。

用法：python ablate_m3_holding.py [--folds 5]
產出：results/m3_holding_ablation.md
"""

import argparse
import os
import sys
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CRAWLER_DIR = os.path.join(BASE_DIR, '..', 'Crawler')
sys.path.insert(0, CRAWLER_DIR)
sys.path.insert(0, BASE_DIR)

RESULTS_DIR = os.path.join(BASE_DIR, 'results')
DIR_MARGIN = 0.01


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--folds', type=int, default=5)
    args = ap.parse_args()

    from experiment_m3 import (load_dataset, build_panel, label_alpha,
                               walk_forward, LABEL_HORIZON)
    from m3_features import MODEL_FEATURE_COLS
    from holding_features import attach as attach_holding, HOLDING_FEATURES
    from ablate_m3_exog import aggregate

    print('載入 M3 面板…')
    data = attach_holding(build_panel(load_dataset(), LABEL_HORIZON))

    base = [c for c in MODEL_FEATURE_COLS if c in data.columns]
    hold = [c for c in HOLDING_FEATURES if c in data.columns]
    print(f'現行特徵 {len(base)} 個、持股 {len(hold)} 個')

    variants = [
        ('現行（籌碼+橫斷面）', base),
        ('現行 + 持股', base + hold),
    ]
    all_cols = sorted({c for _, cols in variants for c in cols})
    # 2012 起的完整樣本含一筆 0052 於 2017-06 的零收盤價（ret_5d 變成 inf），
    # 2018 起的 exog 消融沒碰到它。dropna 抓不到 inf，先換成 NaN 再一起丟掉。
    import numpy as np
    data = data.replace([np.inf, -np.inf], np.nan)
    d = data.dropna(subset=all_cols).reset_index(drop=True)
    print(f'共同可用樣本 {len(d):,} 筆 / {d["stock_id"].nunique()} 檔　'
          f'{str(d["trade_date"].min())[:10]} ~ {str(d["trade_date"].max())[:10]}\n')

    rf_params = dict(n_estimators=300, max_depth=8, min_samples_leaf=30,
                     class_weight='balanced_subsample')

    rows = []
    for label, cols in variants:
        folds_out = walk_forward(d, cols, label_alpha, rf_params,
                                 n_folds=args.folds, horizon=LABEL_HORIZON,
                                 gate=0.35, verbose=False)
        m = aggregate(folds_out)
        m['label'] = label
        m['n_features'] = len(cols)
        rows.append(m)
        print(f'  {label:20} 特徵 {len(cols):>2} 個　'
              f'買進方向={m["buy_dir_acc"]:.2%} '
              f'買進平均報酬={m["buy_avg_ret"]:+.2%} '
              f'出手率={m["coverage"]:.1%}（{m["n_long"]} 次買進）')

    cur, cand = rows
    gain = cand['buy_dir_acc'] - cur['buy_dir_acc']
    ret_ok = (cand.get('buy_avg_ret') or 0) >= (cur.get('buy_avg_ret') or 0)
    deploy = gain >= DIR_MARGIN and ret_ok
    print(f'\n持股 vs 現行：方向 {gain:+.2%}，報酬 '
          f'{cand["buy_avg_ret"] - cur["buy_avg_ret"]:+.2%}')
    print(f'部署判定：{"通過" if deploy else "未通過"}'
          f'（需 +{DIR_MARGIN:.0%} 且平均報酬不變差）')

    os.makedirs(RESULTS_DIR, exist_ok=True)
    path = os.path.join(RESULTS_DIR, 'm3_holding_ablation.md')
    lines = [
        '# M3 籌碼模型消融：外資真實持股（Iteration 36）',
        '',
        f'**執行時間：** {datetime.now().strftime("%Y-%m-%d %H:%M")}',
        f'**樣本：** {len(d):,} 筆 / {d["stock_id"].nunique()} 檔，'
        f'{str(d["trade_date"].min())[:10]} ~ {str(d["trade_date"].max())[:10]}',
        f'**驗證：** {args.folds} 折擴張視窗走查 + 標籤期封存（沿用 experiment_m3 口徑）',
        '**標籤：** alpha（剝離大盤 beta）方向，未來 3 個交易日',
        f'**持股特徵：** {", ".join(hold)}',
        '',
        '| 特徵組合 | 特徵數 | 買進方向準確率 | 買進平均報酬 | 出手率 |',
        '|---------|-------|--------------|------------|--------|',
    ]
    for r in rows:
        lines.append(f"| {r['label']} | {r['n_features']} | {r['buy_dir_acc']:.2%} | "
                     f"{r['buy_avg_ret']:+.2%} | {r['coverage']:.1%} |")
    lines += [
        '',
        f'**持股 vs 現行：方向 {gain:+.2%}，報酬 '
        f'{cand["buy_avg_ret"] - cur["buy_avg_ret"]:+.2%}。**',
        f'**部署判定：{"通過" if deploy else "未通過"}**'
        f'（需 +{DIR_MARGIN:.0%} 且平均報酬不得變差）。',
    ]
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    print(f'報告已寫入 {path}')


if __name__ == '__main__':
    main()
