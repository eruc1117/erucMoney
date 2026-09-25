"""
跳空模型特徵消融（Iteration 28）
────────────────────────────────
問題：台指期夜盤要不要進跳空模型？進了之後美股還留不留？

探測階段的相關性顯示夜盤（0.567）優於費半（0.483），而且幾乎吃掉美股的資訊
（美股額外貢獻 R² 僅 +0.0104）。但**相關性好看不等於加進模型會變好**——
Iteration 14→15 的美股結論翻案、Iteration 20 的事件特徵都是這樣栽的。
所以這裡跑完整的擴張視窗走查，一組一組比。

## 比什麼

    自身          只有個股波動與歷史跳空統計（下限）
    自身+美股     現行部署版本（走查相關 0.5874）
    自身+夜盤     用夜盤取代美股
    自身+美股+夜盤 兩者都要
    夜盤單因子    只有 night_ret 一個特徵（看它單獨能走多遠）

## 部署門檻

新組合要取代現行版本，走查相關必須高出 **+0.02** 以上。
Iteration 20 的教訓：沒有 margin 的門檻等於沒有門檻——當時 +0.0011 的雜訊
也能通過「有提升就採用」。

用法：python ablate_gap.py
產出：results/gap_ablation.md
"""

import os
import sys
from datetime import datetime

import numpy as np
import pandas as pd

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, '..', 'Crawler'))

from train_gap import load_dataset, folds, evaluate, SELF_FEATURES   # noqa: E402
from us_features import US_FEATURES                                  # noqa: E402
from night_features import NIGHT_FEATURES                            # noqa: E402
from intl_features import INTL_FEATURES                              # noqa: E402

RESULTS_DIR = os.path.join(BASE_DIR, 'results')
DEPLOY_MARGIN = 0.02        # 走查相關須高出現行版本這麼多才換


def fit_eval(d: pd.DataFrame, cols: list) -> dict:
    from sklearn.ensemble import HistGradientBoostingRegressor
    X, y = d[cols].values, d['gap'].values
    preds, trues = [], []
    for tr, te in folds(d):
        reg = HistGradientBoostingRegressor(
            max_iter=400, max_depth=5, learning_rate=0.05, min_samples_leaf=60,
            l2_regularization=1.0, early_stopping=True,
            validation_fraction=0.15, random_state=42)
        reg.fit(X[tr], y[tr])
        preds.append(reg.predict(X[te]))
        trues.append(y[te])
    return evaluate(np.concatenate(trues), np.concatenate(preds))


def main():
    print('載入資料（含夜盤）…')
    data = load_dataset(adjust_dividend=True)
    us_cols = [c for c in US_FEATURES if c in data.columns]
    night_cols = [c for c in NIGHT_FEATURES if c in data.columns]
    intl_cols = [c for c in INTL_FEATURES if c in data.columns]
    print(f'美股特徵 {len(us_cols)} 個、夜盤特徵 {len(night_cols)} 個、'
          f'韓日特徵 {len(intl_cols)} 個、個股特徵 {len(SELF_FEATURES)} 個')

    variants = [
        ('自身特徵（下限）', SELF_FEATURES),
        ('自身 + 美股', us_cols + SELF_FEATURES),
        ('自身 + 夜盤', night_cols + SELF_FEATURES),
        ('自身 + 韓日', intl_cols + SELF_FEATURES),
        ('自身 + 美股 + 夜盤（現行）', us_cols + night_cols + SELF_FEATURES),
        ('自身 + 夜盤 + 韓日', night_cols + intl_cols + SELF_FEATURES),
        ('自身 + 美股 + 夜盤 + 韓日（全部）',
         us_cols + night_cols + intl_cols + SELF_FEATURES),
        ('夜盤單因子 night_ret', ['night_ret']),
        ('韓日開盤單因子 asia_open_ret', ['asia_open_ret']),
    ]

    # 所有變體必須跑在**同一批樣本**上，否則比的是不同的資料，不是不同的特徵。
    # 夜盤 2018 起才有，美股與個股特徵的可用期間也不同——取交集。
    all_cols = sorted(set(sum([v[1] for v in variants], [])))
    d = data[data[all_cols + ['gap']].notna().all(axis=1)].reset_index(drop=True)
    print(f'共同可用樣本 {len(d):,} 筆 / {d["stock_id"].nunique()} 檔'
          f'（{str(d["trade_date"].min())[:10]} ~ {str(d["trade_date"].max())[:10]}）\n')

    rows = []
    for label, cols in variants:
        m = fit_eval(d, cols)
        m['label'] = label
        m['n_features'] = len(cols)
        rows.append(m)
        print(f'  {label:22} 特徵 {len(cols):>2} 個　相關={m["corr"]:.4f} '
              f'R²={m["r2"]:+.4f} MAE={m["mae"]:.4%} 方向={m["dir_acc"]:.2%}')

    cur = next(r for r in rows if r['label'] == '自身 + 美股 + 夜盤（現行）')
    best = max(rows, key=lambda r: r['corr'])
    gain = best['corr'] - cur['corr']
    deploy = best['label'] != cur['label'] and gain >= DEPLOY_MARGIN

    print(f'\n最佳：{best["label"]}（相關 {best["corr"]:.4f}）'
          f'　現行：{cur["corr"]:.4f}　差距 {gain:+.4f}')
    print(f'部署判定：{"通過" if deploy else "未通過"}'
          f'（門檻 +{DEPLOY_MARGIN}）')

    write_report(d, rows, cur, best, gain, deploy, us_cols, night_cols, intl_cols)
    return best, deploy


def write_report(d, rows, cur, best, gain, deploy, us_cols, night_cols, intl_cols):
    os.makedirs(RESULTS_DIR, exist_ok=True)
    path = os.path.join(RESULTS_DIR, 'gap_ablation.md')
    lines = [
        '# 跳空模型特徵消融：台指期夜盤（Iteration 28）',
        '',
        f'**執行時間：** {datetime.now().strftime("%Y-%m-%d %H:%M")}',
        f'**樣本：** {len(d):,} 筆 / {d["stock_id"].nunique()} 檔　'
        f'{str(d["trade_date"].min())[:10]} ~ {str(d["trade_date"].max())[:10]}',
        f'**驗證：** 擴張視窗走查（跳空是當日事件，訓練集無需封存）',
        '',
        '所有變體跑在**同一批樣本**上——夜盤 2018 起才有，若各自取可用期間，',
        '比的就是不同的資料而不是不同的特徵。',
        '',
        '| 特徵組合 | 特徵數 | 相關係數 | R² | MAE | 方向準確率 |',
        '|---------|-------|---------|-----|-----|-----------|',
    ]
    for r in rows:
        mark = '**' if r is best else ''
        lines.append(f"| {mark}{r['label']}{mark} | {r['n_features']} | "
                     f"{r['corr']:.4f} | {r['r2']:+.4f} | {r['mae']:.4%} | "
                     f"{r['dir_acc']:.2%} |")
    lines += [
        '',
        f'**最佳：{best["label"]}**（相關 {best["corr"]:.4f}），'
        f'現行部署版本 {cur["corr"]:.4f}，差距 {gain:+.4f}。',
        '',
        f'**部署判定：{"通過" if deploy else "未通過"}**'
        f'（門檻 +{DEPLOY_MARGIN}）。'
        'Iteration 20 的教訓：沒有 margin 的門檻等於沒有門檻——'
        '當時「有提升就採用」讓 +0.0011 的雜訊也通過了。',
        '',
        '## 特徵清單',
        '',
        f'- 美股（{len(us_cols)}）：{", ".join(us_cols)}',
        f'- 夜盤（{len(night_cols)}）：{", ".join(night_cols)}',
        f'- 韓日（{len(intl_cols)}）：{", ".join(intl_cols)}',
        f'- 個股（{len(SELF_FEATURES)}）：{", ".join(SELF_FEATURES)}',
        '',
        '## 時序（搞反就是未來資訊洩漏）',
        '',
        '`futures_daily` 的 `after_market` 那一列，其收盤價幾乎等於**同一個 trade_date**',
        '的日盤開盤價（中位數差 0.185%）——它領先同日開盤。所以預測 D 日跳空時，',
        '用的是 D 日那列的夜盤；當日 `position`（日盤）的任何欄位都不能碰。',
    ]
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    print(f'報告已寫入 {path}')


if __name__ == '__main__':
    main()
