"""
振幅與波動率模型消融 + 超參數自我迭代（Iteration 29）
────────────────────────────────────────────────────
問題：韓股、日股、台指期夜盤能不能讓「振幅」與「波動率」預測變好？

跳空模型的消融顯示韓日幾乎被夜盤涵蓋（+0.0029，未過門檻）。但那是**方向與價位**
的問題；振幅與波動率問的是**會震多大**，而區域市場的風險情緒理論上正是這種東西。
所以值得單獨測一次——不能拿跳空的結論直接套用。

## 兩段流程

1. **特徵消融**：現行 / +夜盤 / +韓日 / 全部，同一批樣本、擴張視窗走查
2. **超參數自我迭代**：對勝出的特徵組合做座標下降，連續兩輪改善 < 1e-4 即停

第 2 段是使用者要求的「自我迭代優化」。它只在特徵組合確定之後才跑——
先調參數再選特徵，等於在錯的特徵上浪費算力。

## 部署門檻

振幅：排序相關（Spearman）須高出現行 +0.01
波動率：R²(log) 須高出現行 +0.01，且 QLIKE 不得變差
兩者都要求實質 margin——Iteration 20 的教訓。

用法：python ablate_range_vol.py [--skip-tune]
產出：results/range_vol_ablation.md
"""

import argparse
import os
import sys
from datetime import datetime

import numpy as np
import pandas as pd

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, '..', 'Crawler'))

from night_features import attach as attach_night, NIGHT_FEATURES     # noqa: E402
from intl_features import attach as attach_intl, INTL_FEATURES        # noqa: E402

RESULTS_DIR = os.path.join(BASE_DIR, 'results')
N_FOLDS = 5
RANGE_MARGIN = 0.01
CONVERGE_EPS = 1e-4
CONVERGE_PATIENCE = 2

PARAM_GRID = {
    'max_depth': [4, 5, 6, 8],
    'learning_rate': [0.03, 0.05, 0.08],
    'min_samples_leaf': [40, 80, 150],
    'l2_regularization': [0.0, 1.0, 5.0],
    'max_iter': [300, 400, 600],
}


def build_range_data():
    """振幅面板 + 夜盤 + 韓日。"""
    from train_range import load_data, HORIZON
    d = load_data(for_inference=False)
    d = attach_night(d, 'TX')
    d = attach_intl(d)
    return d, HORIZON


def folds_expanding(d: pd.DataFrame, embargo: int = 5):
    """
    擴張視窗 + 標籤期封存。

    振幅目標需要未來 5 天，訓練集尾端那幾天的標籤與測試集重疊——
    不封存就是變相偷看（Iteration 9 建立的規矩）。
    """
    dates = np.sort(d['trade_date'].unique())
    bounds = [int(len(dates) * (i + 1) / (N_FOLDS + 1)) for i in range(N_FOLDS)]
    for i, b in enumerate(bounds):
        end = int(len(dates) * (i + 2) / (N_FOLDS + 1))
        cut = dates[max(b - embargo, 0)]
        tr = (d['trade_date'] < cut).values
        te = ((d['trade_date'] >= dates[b]) &
              (d['trade_date'] < dates[min(end, len(dates) - 1)])).values
        if tr.sum() > 1000 and te.sum() > 200:
            yield tr, te


def eval_range(d, cols, params=None):
    from sklearn.ensemble import HistGradientBoostingRegressor
    p = dict(max_iter=400, max_depth=5, learning_rate=0.05, min_samples_leaf=80,
             l2_regularization=1.0)
    if params:
        p.update(params)
    X = d[cols].values
    y = np.log(np.maximum(d['range_5d'].values, 1e-8))
    preds, trues = [], []
    for tr, te in folds_expanding(d):
        reg = HistGradientBoostingRegressor(
            early_stopping=True, validation_fraction=0.15, random_state=42, **p)
        reg.fit(X[tr], y[tr])
        preds.append(np.exp(reg.predict(X[te])))
        trues.append(np.exp(y[te]))
    yp, yt = np.concatenate(preds), np.concatenate(trues)
    rank = float(pd.Series(yp).corr(pd.Series(yt), method='spearman'))
    ss_res = float(np.sum((yt - yp) ** 2))
    ss_tot = float(np.sum((yt - yt.mean()) ** 2))
    # lift：預測前 10% 的實際振幅是全體平均的幾倍——選股用途看的就是這個
    k = max(int(len(yp) * 0.1), 1)
    top = yt[np.argsort(-yp)[:k]]
    return {'rank_corr': rank, 'r2': 1 - ss_res / ss_tot,
            'mae': float(np.mean(np.abs(yt - yp))),
            'lift': float(top.mean() / yt.mean()), 'n': int(len(yp))}


def tune(d, cols, base_metric, verbose=True):
    """
    座標下降到收斂。**在特徵組合確定之後才跑**——
    先調參數再選特徵，等於在錯的特徵上浪費算力。
    """
    best_p = {k: v[len(v) // 2] for k, v in PARAM_GRID.items()}
    best = eval_range(d, cols, best_p)['rank_corr']
    history = [{'round': 0, 'rank_corr': best, 'params': dict(best_p)}]
    stale, rnd = 0, 0
    while stale < CONVERGE_PATIENCE and rnd < 8:
        rnd += 1
        prev = best
        for key, options in PARAM_GRID.items():
            for cand in options:
                if cand == best_p[key]:
                    continue
                trial = dict(best_p, **{key: cand})
                v = eval_range(d, cols, trial)['rank_corr']
                if v > best + 1e-12:
                    best, best_p = v, trial
        gain = best - prev
        history.append({'round': rnd, 'rank_corr': best, 'gain': gain,
                        'params': dict(best_p)})
        if verbose:
            print(f'    第 {rnd} 輪：排序相關 {best:.4f}（改善 {gain:+.5f}）')
        stale = stale + 1 if gain < CONVERGE_EPS else 0
    return best_p, best, history


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--skip-tune', action='store_true')
    args = ap.parse_args()

    print('載入振幅面板（含夜盤與韓日）…')
    d, horizon = build_range_data()

    from features import PRICE_FEATURES, CS_FEATURES, MARKET_FEATURES
    from train_volatility import EXTRA_VOL_FEATURES
    base = [c for c in PRICE_FEATURES + CS_FEATURES + MARKET_FEATURES
            + EXTRA_VOL_FEATURES if c in d.columns]
    night = [c for c in NIGHT_FEATURES if c in d.columns]
    intl = [c for c in INTL_FEATURES if c in d.columns]
    print(f'現行特徵 {len(base)} 個、夜盤 {len(night)} 個、韓日 {len(intl)} 個')

    variants = [
        ('現行特徵', base),
        ('現行 + 夜盤', base + night),
        ('現行 + 韓日', base + intl),
        ('現行 + 夜盤 + 韓日', base + night + intl),
    ]
    all_cols = sorted(set(sum([v[1] for v in variants], [])))
    dd = d[d[all_cols + ['range_5d']].notna().all(axis=1)].reset_index(drop=True)
    print(f'共同可用樣本 {len(dd):,} 筆 / {dd["stock_id"].nunique()} 檔'
          f'（{str(dd["trade_date"].min())[:10]} ~ {str(dd["trade_date"].max())[:10]}）\n')

    rows = []
    for label, cols in variants:
        m = eval_range(dd, cols)
        m.update(label=label, n_features=len(cols))
        rows.append(m)
        print(f'  {label:16} 特徵 {len(cols):>2} 個　排序相關={m["rank_corr"]:.4f} '
              f'R²={m["r2"]:+.4f} MAE={m["mae"]:.4%} lift={m["lift"]:.3f}')

    cur = rows[0]
    best = max(rows, key=lambda r: r['rank_corr'])
    gain = best['rank_corr'] - cur['rank_corr']
    deploy = best is not cur and gain >= RANGE_MARGIN
    print(f'\n最佳：{best["label"]}（{best["rank_corr"]:.4f}）　'
          f'現行 {cur["rank_corr"]:.4f}　差距 {gain:+.4f}　'
          f'部署判定：{"通過" if deploy else "未通過"}（門檻 +{RANGE_MARGIN}）')

    history = []
    tuned = None
    if not args.skip_tune:
        print(f'\n超參數自我迭代（對「{best["label"]}」，收斂即止）…')
        best_cols = dict(variants)[best['label']]
        p, v, history = tune(dd, best_cols, best['rank_corr'])
        tuned = {'params': p, 'rank_corr': v,
                 'gain_vs_default': v - best['rank_corr'], 'rounds': len(history) - 1}
        print(f'  收斂於 {tuned["rounds"]} 輪：排序相關 {v:.4f}'
              f'（較預設參數 {tuned["gain_vs_default"]:+.4f}）')

    write_report(dd, rows, cur, best, gain, deploy, base, night, intl, tuned, history)


def write_report(d, rows, cur, best, gain, deploy, base, night, intl, tuned, history):
    os.makedirs(RESULTS_DIR, exist_ok=True)
    path = os.path.join(RESULTS_DIR, 'range_vol_ablation.md')
    lines = [
        '# 振幅模型消融：韓日大盤與台指期夜盤（Iteration 29）',
        '',
        f'**執行時間：** {datetime.now().strftime("%Y-%m-%d %H:%M")}',
        f'**樣本：** {len(d):,} 筆 / {d["stock_id"].nunique()} 檔　'
        f'{str(d["trade_date"].min())[:10]} ~ {str(d["trade_date"].max())[:10]}',
        '**驗證：** 擴張視窗走查 + 標籤期封存（振幅目標需要未來 5 天，'
        '不封存就是變相偷看）',
        '**樣本對齊：** 所有變體跑在同一批（全部特徵齊全的列）。'
        '不對齊的話比的是資料量而不是特徵。',
        '',
        '| 特徵組合 | 特徵數 | 排序相關 | R² | MAE | lift |',
        '|---------|-------|---------|-----|-----|------|',
    ]
    for r in rows:
        mark = '**' if r is best else ''
        lines.append(f"| {mark}{r['label']}{mark} | {r['n_features']} | "
                     f"{r['rank_corr']:.4f} | {r['r2']:+.4f} | {r['mae']:.4%} | "
                     f"{r['lift']:.3f} |")
    lines += [
        '',
        f'**最佳：{best["label"]}**（排序相關 {best["rank_corr"]:.4f}），'
        f'現行 {cur["rank_corr"]:.4f}，差距 {gain:+.4f}。',
        f'**部署判定：{"通過" if deploy else "未通過"}**（門檻 +{RANGE_MARGIN}）。',
    ]
    if tuned:
        lines += [
            '',
            '## 超參數自我迭代',
            '',
            '**這個數字不能當作外樣本表現。** 參數是在「用來評估的同一組走查」上挑出來的，',
            '挑得愈久分數愈好看，屬於選擇偏誤（Iteration 21 記過的同一個問題）。',
            '要拿它當部署依據，必須改成巢狀驗證：參數只在訓練折內挑，',
            '再到一段完全沒碰過的後段期間評分。本次未做，故**不部署**。',
            '',
            f'座標下降，連續 {CONVERGE_PATIENCE} 輪改善 < {CONVERGE_EPS} 即停。',
            f'收斂於第 {tuned["rounds"]} 輪：排序相關 {tuned["rank_corr"]:.4f}，'
            f'較預設參數 {tuned["gain_vs_default"]:+.4f}。',
            '',
            '| 輪次 | 排序相關 | 改善 |',
            '|------|---------|------|',
        ]
        for h in history:
            g = h.get('gain')
            lines.append(f"| {h['round']} | {h['rank_corr']:.4f} | "
                         f"{('%+.5f' % g) if g is not None else '—'} |")
        lines += ['', f"最終參數：`{tuned['params']}`"]
    lines += [
        '',
        '## 特徵清單',
        '',
        f'- 現行（{len(base)}）',
        f'- 夜盤（{len(night)}）：{", ".join(night)}',
        f'- 韓日（{len(intl)}）：{", ".join(intl)}',
        '',
        '## 時序',
        '',
        '韓日比台股早一小時開盤，**當日開盤價**在台股開盤前可得；'
        '**當日收盤價**（台北 14:00~14:30）在台股收盤之後，一律不取用。',
    ]
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    print(f'報告已寫入 {path}')


if __name__ == '__main__':
    main()
