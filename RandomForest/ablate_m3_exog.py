"""
M3 籌碼模型消融：外生特徵（Iteration 30）
─────────────────────────────────────────
三個迴歸模型（跳空／振幅／波動率）已在 `UnifiedModel/optimise_all.py` 用巢狀走查
測過。M3 是分類器、標籤與評估口徑都不同，所以獨立一支。

## 測什麼

M3 預測未來 3 個交易日的 alpha 方向（剝離大盤 beta）。它現在只看籌碼與橫斷面，
完全沒有外部輸入。要測的是：

    現行（籌碼＋橫斷面）
    ＋ 台指期夜盤
    ＋ 韓日開盤
    ＋ 兩者

## 為什麼期望值不高，但仍值得測

夜盤與韓日定價的是**隔夜到開盤**那一段，而 M3 的目標是**未來三天的 alpha**。
Iteration 15 已證實隔夜資訊在開盤瞬間被吸收，Iteration 28 也證實它對
收盤到收盤沒有幫助。所以先驗上不看好。

但 M3 的標籤是 **alpha**（剝離大盤）而非原始報酬，這是先前實驗沒涵蓋的組合：
區域市場的風險情緒有沒有可能預示「哪些個股會跑贏大盤」，是一個獨立的問題。
不測就只是猜。

## 判定

沿用 M3 既有的走查與評估口徑（`experiment_m3.py` 的 walk_forward），
比較買進側方向準確率與平均報酬。要取代現行設定，方向準確率須高出 +1 個百分點
且平均報酬不得變差。

用法：python ablate_m3_exog.py [--folds 5]
產出：results/m3_exog_ablation.md
"""

import argparse
import os
import sys
from datetime import datetime

import numpy as np
import pandas as pd

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CRAWLER_DIR = os.path.join(BASE_DIR, '..', 'Crawler')
sys.path.insert(0, CRAWLER_DIR)
sys.path.insert(0, BASE_DIR)

RESULTS_DIR = os.path.join(BASE_DIR, 'results')
DIR_MARGIN = 0.01      # 方向準確率須高出現行 1 個百分點


def aggregate(folds_out) -> dict:
    """
    逐折結果彙總。**以出手次數加權**，不是簡單平均——
    某一折只出手三次卻全中，簡單平均會讓它和一折出手三百次的等重。
    M3 的賣出側已被部署政策抑制，故主指標看買進（long）側。
    """
    folds = folds_out[0] if isinstance(folds_out, tuple) else folds_out
    n_long = sum(int(f.get('n_long') or 0) for f in folds)
    n_calls = sum(int(f.get('n_calls') or 0) for f in folds)
    def wavg(key, weight_key):
        num = sum((f.get(key) or 0) * (f.get(weight_key) or 0)
                  for f in folds if f.get(key) == f.get(key))
        den = sum((f.get(weight_key) or 0) for f in folds if f.get(key) == f.get(key))
        return num / den if den else float('nan')
    return {
        'buy_dir_acc': wavg('long_dir_acc', 'n_long'),
        'buy_avg_ret': wavg('long_avg_ret', 'n_long'),
        'dir_acc': wavg('dir_acc', 'n_calls'),
        'coverage': float(np.mean([f.get('coverage') or 0 for f in folds])),
        'n_long': n_long, 'n_calls': n_calls, 'folds': len(folds),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--folds', type=int, default=5)
    args = ap.parse_args()

    from experiment_m3 import (load_dataset, build_panel, label_alpha,
                               walk_forward, LABEL_HORIZON)
    from m3_features import MODEL_FEATURE_COLS
    from night_features import attach as attach_night, NIGHT_FEATURES
    from intl_features import attach as attach_intl, INTL_FEATURES

    print('載入 M3 面板…')
    raw = load_dataset()
    data = build_panel(raw, LABEL_HORIZON)
    data = attach_intl(attach_night(data, 'TX'))

    base = [c for c in MODEL_FEATURE_COLS if c in data.columns]
    night = [c for c in NIGHT_FEATURES if c in data.columns]
    intl = [c for c in INTL_FEATURES if c in data.columns]
    print(f'現行特徵 {len(base)} 個、夜盤 {len(night)} 個、韓日 {len(intl)} 個')

    variants = [
        ('現行（籌碼+橫斷面）', base),
        ('現行 + 夜盤', base + night),
        ('現行 + 韓日', base + intl),
        ('現行 + 夜盤 + 韓日', base + night + intl),
    ]
    # 同一批樣本，否則比的是資料量不是特徵
    all_cols = sorted({c for _, cols in variants for c in cols})
    d = data.dropna(subset=all_cols).reset_index(drop=True)
    print(f'共同可用樣本 {len(d):,} 筆 / {d["stock_id"].nunique()} 檔\n')

    # random_state / n_jobs 由 walk_forward 自己帶，這裡再給一次會撞參數
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

    cur = rows[0]
    def key(r):
        v = r.get('buy_dir_acc')
        return v if v == v else 0.0      # NaN 視為 0
    best = max(rows, key=key)
    gain = key(best) - key(cur)
    ret_ok = (best.get('buy_avg_ret') or 0) >= (cur.get('buy_avg_ret') or 0)
    deploy = best is not cur and gain >= DIR_MARGIN and ret_ok

    print(f'\n最佳：{best["label"]}（買進方向 {key(best):.2%}）　'
          f'現行 {key(cur):.2%}　差距 {gain:+.2%}')
    print(f'部署判定：{"通過" if deploy else "未通過"}'
          f'（需 +{DIR_MARGIN:.0%} 且平均報酬不變差）')

    write_report(d, rows, cur, best, gain, deploy, base, night, intl, args.folds)


def write_report(d, rows, cur, best, gain, deploy, base, night, intl, folds):
    os.makedirs(RESULTS_DIR, exist_ok=True)
    path = os.path.join(RESULTS_DIR, 'm3_exog_ablation.md')
    lines = [
        '# M3 籌碼模型消融：台指期夜盤與韓日開盤（Iteration 30）',
        '',
        f'**執行時間：** {datetime.now().strftime("%Y-%m-%d %H:%M")}',
        f'**樣本：** {len(d):,} 筆 / {d["stock_id"].nunique()} 檔',
        f'**驗證：** {folds} 折擴張視窗走查 + 標籤期封存（沿用 experiment_m3 口徑）',
        '**標籤：** alpha（剝離大盤 beta）方向，未來 3 個交易日',
        '',
        '| 特徵組合 | 特徵數 | 買進方向準確率 | 買進平均報酬 | 出手率 |',
        '|---------|-------|--------------|------------|--------|',
    ]
    for r in rows:
        mark = '**' if r is best else ''
        lines.append(f"| {mark}{r['label']}{mark} | {r['n_features']} | "
                     f"{r['buy_dir_acc']:.2%} | "
                     f"{r['buy_avg_ret']:+.2%} | "
                     f"{r['coverage']:.1%} |")
    lines += [
        '',
        f'**最佳：{best["label"]}**，現行 {cur["label"]}，差距 {gain:+.2%}。',
        f'**部署判定：{"通過" if deploy else "未通過"}**'
        f'（需 +{DIR_MARGIN:.0%} 且平均報酬不得變差）。',
        '',
        '## 先驗上為什麼不看好，仍要測',
        '',
        '夜盤與韓日定價的是「隔夜到開盤」那一段。Iteration 15 已證實這段資訊',
        '在開盤瞬間被吸收，Iteration 28 也證實它對收盤到收盤沒有幫助。',
        '',
        '但 M3 的標籤是 **alpha**（剝離大盤）而非原始報酬——',
        '「區域風險情緒能不能預示哪些個股跑贏大盤」是一個獨立的問題，',
        '不測就只是猜。',
    ]
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    print(f'報告已寫入 {path}')


if __name__ == '__main__':
    main()
