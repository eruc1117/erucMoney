"""
全模型消融 + 巢狀自我迭代（Iteration 30）
────────────────────────────────────────
Iteration 29 跑了自我迭代，排序相關從 0.6568 拉到 0.6675，然後我把那個數字
作廢了——因為參數是在「**用來評估的同一組走查**」上挑出來的。挑得愈久分數愈好看，
那是選擇偏誤，不是模型變好。

這支腳本把它做對：**巢狀走查**。

## 巢狀走查是什麼

    外層折 k：訓練期 = 前 k 段，測試期 = 第 k+1 段
        └─ 內層：只在「訓練期」裡再切走查，挑特徵組合與超參數
        └─ 用挑出來的設定重訓整個訓練期，到外層測試期評分 ← 這才是外樣本

關鍵是**測試期在挑選過程中完全沒被看過**。單層走查的問題在於：
你用整段走查的分數去挑參數，那段資料就不再是外樣本了。

## 另一個輸出比分數本身更重要：設定穩定性

腳本會印出「每一折各自挑中了什麼」。如果三折挑出三種不同的設定，
那代表選擇過程主要在跟隨雜訊——即使平均分數上升，也不該部署。
**分數會騙人，穩定性不會。**

## 部署門檻

外層平均分數須高出「現行部署設定」（同樣以巢狀流程評分）達 margin 以上，
且勝出的設定至少要在多數折中被選中。

用法：
    python optimise_all.py                 # 全部模型
    python optimise_all.py --models gap    # 只跑某一個
    python optimise_all.py --quick         # 縮小參數格點，快速確認流程
產出：results/optimise_all.md
"""

import argparse
import json
import os
import sys
from datetime import datetime

import numpy as np
import pandas as pd

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, '..', 'Crawler'))

RESULTS_DIR = os.path.join(BASE_DIR, 'results')

OUTER_FOLDS = 3
INNER_FOLDS = 2
CONVERGE_EPS = 1e-4
CONVERGE_PATIENCE = 2
MAX_ROUNDS = 6
DEPLOY_MARGIN = 0.01        # 外層平均分數須高出現行設定這麼多
STABILITY_MIN = 2 / 3       # 勝出設定至少要在這麼多比例的折中被選中
STOCK_FILTER = None         # --stocks：只取部分股票做流程驗證，正式評估不用

PARAM_GRID = {
    'max_depth': [4, 5, 6, 8],
    'learning_rate': [0.03, 0.05, 0.08],
    'min_samples_leaf': [40, 80, 150],
    'l2_regularization': [0.0, 1.0, 5.0],
    'max_iter': [300, 400, 600],
}
QUICK_GRID = {
    'max_depth': [4, 6],
    'learning_rate': [0.05, 0.08],
    'min_samples_leaf': [80],
    'l2_regularization': [1.0],
    'max_iter': [300],
}
DEFAULT_PARAMS = dict(max_iter=400, max_depth=5, learning_rate=0.05,
                      min_samples_leaf=80, l2_regularization=1.0)


# ── 模型定義 ──────────────────────────────────────────────────────────────────
def _feature_pools(d):
    from us_features import US_FEATURES
    from night_features import NIGHT_FEATURES
    from intl_features import INTL_FEATURES
    from holding_features import HOLDING_FEATURES
    return ([c for c in US_FEATURES if c in d.columns],
            [c for c in NIGHT_FEATURES if c in d.columns],
            [c for c in INTL_FEATURES if c in d.columns],
            [c for c in HOLDING_FEATURES if c in d.columns])


def _attach_holding(d):
    """外資真實持股（Iteration 36）。as-of 逐檔合併，缺的股票留 NaN 由 dropna 處理。"""
    from holding_features import attach
    return attach(d)


def load_gap():
    from train_gap import load_dataset, SELF_FEATURES
    d = _attach_holding(load_dataset(adjust_dividend=True))
    us, night, intl, hold = _feature_pools(d)
    self_c = [c for c in SELF_FEATURES if c in d.columns]
    variants = {
        '自身': self_c,
        '自身+美股': us + self_c,
        '自身+夜盤': night + self_c,
        '自身+美股+夜盤（現行）': us + night + self_c,
        '自身+夜盤+韓日': night + intl + self_c,
        '自身+全部': us + night + intl + self_c,
        '現行+持股': us + night + self_c + hold,
    }
    return d, 'gap', variants, '自身+美股+夜盤（現行）', 0, False


def _range_vol_panel():
    from train_range import load_data
    from night_features import attach as attach_night
    from intl_features import attach as attach_intl
    d = load_data(for_inference=False)
    return _attach_holding(attach_intl(attach_night(d, 'TX')))


def load_range():
    from features import PRICE_FEATURES, CS_FEATURES, MARKET_FEATURES
    from train_volatility import EXTRA_VOL_FEATURES
    d = _range_vol_panel()
    us, night, intl, hold = _feature_pools(d)
    base = [c for c in PRICE_FEATURES + CS_FEATURES + MARKET_FEATURES
            + EXTRA_VOL_FEATURES if c in d.columns]
    # Iteration 30 部署了 v2（+夜盤+韓日），現行基準要對到它，不是 v1
    variants = {
        'v1（價量）': base,
        'v1+夜盤': base + night,
        'v1+韓日': base + intl,
        'v2（+夜盤+韓日，現行）': base + night + intl,
        '現行+持股': base + night + intl + hold,
    }
    # 目標取對數：振幅是右偏的正值，直接回歸會被少數極端值主導
    d = d.assign(_target=np.log(np.maximum(d['range_5d'].values, 1e-8)))
    return d, '_target', variants, 'v2（+夜盤+韓日，現行）', 5, True


def load_volatility():
    from features import PRICE_FEATURES, CS_FEATURES, MARKET_FEATURES
    from train_volatility import EXTRA_VOL_FEATURES
    d = _range_vol_panel()
    # 目標：未來 20 個交易日的已實現波動（與部署版本同口徑）
    g = d.sort_values(['stock_id', 'trade_date']).groupby('stock_id')
    d = d.sort_values(['stock_id', 'trade_date']).copy()
    d['_vol_fwd'] = g['ret_1d'].transform(lambda s: s.shift(-20).rolling(20).std())
    d = d[d['_vol_fwd'] > 0].copy()
    d['_target'] = np.log(d['_vol_fwd'])
    us, night, intl, hold = _feature_pools(d)
    base = [c for c in PRICE_FEATURES + CS_FEATURES + MARKET_FEATURES
            + EXTRA_VOL_FEATURES if c in d.columns]
    # Iteration 30 部署了 v2（+夜盤），現行基準對到它
    variants = {
        'v1（價量）': base,
        'v2（+夜盤，現行）': base + night,
        'v1+韓日': base + intl,
        'v1+夜盤+韓日': base + night + intl,
        '現行+持股': base + night + hold,
    }
    return d, '_target', variants, 'v2（+夜盤，現行）', 20, True


def load_volume():
    """
    成交量模型（Iteration 31）。目標：未來 5 日均量 ÷ 20 日均量，取對數，看排序。
    現行 = price+chip+cs+market 四個區塊；Iteration 31 已測過夜盤（+0.0061 未過門檻）。
    """
    from train_volume import load_data
    d, cols = load_data(for_inference=False)
    d = _attach_holding(d)
    d['_target'] = np.log(d['y_volume'].clip(lower=0.05))
    _, _, _, hold = _feature_pools(d)
    variants = {
        '現行': list(cols),
        '現行+持股': list(cols) + hold,
    }
    return d, '_target', variants, '現行', 5, True


MODELS = {'gap': load_gap, 'range': load_range, 'volatility': load_volatility,
          'volume': load_volume}


# ── 走查切分 ──────────────────────────────────────────────────────────────────
def make_folds(dates_idx, n_folds, embargo):
    """
    擴張視窗。embargo 是標籤期封存：目標若需要未來 N 天，訓練集尾端那 N 天的
    標籤與測試期重疊，不封存就是變相偷看（Iteration 9 立的規矩）。
    """
    uniq = np.sort(np.unique(dates_idx))
    bounds = [int(len(uniq) * (i + 1) / (n_folds + 1)) for i in range(n_folds)]
    for i, b in enumerate(bounds):
        end = int(len(uniq) * (i + 2) / (n_folds + 1))
        cut = uniq[max(b - embargo, 0)]
        tr = dates_idx < cut
        te = (dates_idx >= uniq[b]) & (dates_idx < uniq[min(end, len(uniq) - 1)])
        if tr.sum() > 500 and te.sum() > 100:
            yield tr, te


def score(y_true, y_pred, rank_metric: bool) -> float:
    """
    振幅／波動率看**排序能力**（選股只需要排序對），跳空看相關係數。
    兩者都是「愈高愈好」，方便統一比較。
    """
    if rank_metric:
        v = pd.Series(y_pred).corr(pd.Series(y_true), method='spearman')
    else:
        v = np.corrcoef(y_pred, y_true)[0, 1] if np.std(y_pred) > 0 else 0.0
    return float(v) if np.isfinite(v) else 0.0


def fit_score(d, cols, target, params, folds, rank_metric):
    from sklearn.ensemble import HistGradientBoostingRegressor
    X, y = d[cols].values, d[target].values
    preds, trues = [], []
    for tr, te in folds:
        reg = HistGradientBoostingRegressor(
            early_stopping=True, validation_fraction=0.15,
            random_state=42, **params)
        reg.fit(X[tr], y[tr])
        preds.append(reg.predict(X[te]))
        trues.append(y[te])
    if not preds:
        return None
    return score(np.concatenate(trues), np.concatenate(preds), rank_metric)


def inner_search(d_tr, variants, target, embargo, rank_metric, grid, verbose=False):
    """
    在**訓練期之內**再切走查，挑特徵組合與超參數。座標下降至收斂。

    這裡看到的每一分資料都屬於訓練期——外層測試期在這個函式裡完全不存在。
    """
    dates = d_tr['trade_date'].values
    folds = list(make_folds(dates, INNER_FOLDS, embargo))
    if not folds:
        return None

    # 先挑特徵組合（用預設參數），再挑參數——
    # 反過來等於在錯的特徵上調參數，浪費算力也容易挑到雜訊
    best_var, best_score = None, -np.inf
    for name, cols in variants.items():
        s = fit_score(d_tr, cols, target, DEFAULT_PARAMS, folds, rank_metric)
        if s is not None and s > best_score:
            best_var, best_score = name, s

    cols = variants[best_var]
    best_p = dict(DEFAULT_PARAMS)
    stale, rnd = 0, 0
    while stale < CONVERGE_PATIENCE and rnd < MAX_ROUNDS:
        rnd += 1
        prev = best_score
        for key, options in grid.items():
            for cand in options:
                if cand == best_p.get(key):
                    continue
                trial = dict(best_p, **{key: cand})
                s = fit_score(d_tr, cols, target, trial, folds, rank_metric)
                if s is not None and s > best_score + 1e-12:
                    best_score, best_p = s, trial
        gain = best_score - prev
        if verbose:
            print(f'      內層第 {rnd} 輪：{best_score:.4f}（{gain:+.5f}）')
        stale = stale + 1 if gain < CONVERGE_EPS else 0

    return {'variant': best_var, 'params': best_p,
            'inner_score': best_score, 'rounds': rnd}


def nested_evaluate(name, loader, grid, verbose=True):
    print(f'\n=== {name} ===')
    d, target, variants, current_key, embargo, rank_metric = loader()
    if STOCK_FILTER:
        d = d[d['stock_id'].astype(str).str.strip().isin(STOCK_FILTER)]

    all_cols = sorted({c for cols in variants.values() for c in cols})
    d = d[d[all_cols + [target]].notna().all(axis=1)].reset_index(drop=True)
    d = d.sort_values('trade_date').reset_index(drop=True)
    print(f'樣本 {len(d):,} 筆 / {d["stock_id"].nunique()} 檔　'
          f'{str(d["trade_date"].min())[:10]} ~ {str(d["trade_date"].max())[:10]}'
          f'　封存 {embargo} 日')

    dates = d['trade_date'].values
    outer = list(make_folds(dates, OUTER_FOLDS, embargo))
    if not outer:
        print('  外層折不足，略過')
        return None

    picked, tuned_scores, base_scores = [], [], []
    for i, (tr, te) in enumerate(outer, 1):
        d_tr = d[tr].reset_index(drop=True)
        sel = inner_search(d_tr, variants, target, embargo, rank_metric, grid,
                           verbose=verbose)
        if sel is None:
            continue
        # 用挑出來的設定重訓整個訓練期，只在外層測試期評分
        s_tuned = fit_score(d, variants[sel['variant']], target, sel['params'],
                            [(tr, te)], rank_metric)
        s_base = fit_score(d, variants[current_key], target, DEFAULT_PARAMS,
                           [(tr, te)], rank_metric)
        picked.append(sel)
        tuned_scores.append(s_tuned)
        base_scores.append(s_base)
        print(f'  折 {i}：內層挑中「{sel["variant"]}」（內層 {sel["inner_score"]:.4f}、'
              f'{sel["rounds"]} 輪收斂）→ 外樣本 {s_tuned:.4f}'
              f'　現行設定同期 {s_base:.4f}')

    if not tuned_scores:
        return None

    mean_tuned = float(np.mean(tuned_scores))
    mean_base = float(np.mean(base_scores))
    gain = mean_tuned - mean_base

    # 穩定性：勝出設定在幾折中被選中。三折挑出三種設定，代表在跟隨雜訊
    from collections import Counter
    cnt = Counter(p['variant'] for p in picked)
    top_variant, top_n = cnt.most_common(1)[0]
    stability = top_n / len(picked)

    deploy = gain >= DEPLOY_MARGIN and stability >= STABILITY_MIN
    print(f'  外層平均：迭代後 {mean_tuned:.4f}　現行 {mean_base:.4f}　'
          f'差距 {gain:+.4f}')
    print(f'  設定穩定性：{top_variant} 在 {top_n}/{len(picked)} 折被選中'
          f'（{stability:.0%}）')
    print(f'  部署判定：{"通過" if deploy else "未通過"}'
          f'（需 {DEPLOY_MARGIN:+} 且穩定性 ≥ {STABILITY_MIN:.0%}）')

    return {
        'name': name, 'n': len(d), 'stocks': int(d['stock_id'].nunique()),
        'metric': '排序相關' if rank_metric else '相關係數',
        'folds': len(picked), 'picked': picked,
        'tuned_scores': tuned_scores, 'base_scores': base_scores,
        'mean_tuned': mean_tuned, 'mean_base': mean_base, 'gain': gain,
        'top_variant': top_variant, 'stability': stability, 'deploy': deploy,
        'current_key': current_key,
    }


def write_report(results, quick):
    os.makedirs(RESULTS_DIR, exist_ok=True)
    path = os.path.join(RESULTS_DIR, 'optimise_all_holding.md')
    lines = [
        '# 全模型消融 + 巢狀自我迭代：外資真實持股（Iteration 36）',
        '',
        f'**執行時間：** {datetime.now().strftime("%Y-%m-%d %H:%M")}',
        f'**流程：** 外層 {OUTER_FOLDS} 折擴張視窗；每折在**訓練期之內**再切 '
        f'{INNER_FOLDS} 折挑特徵與超參數（座標下降至收斂），'
        f'再用挑出的設定到外層測試期評分',
        f'**格點：** {"快速（縮小）" if quick else "完整"}',
        '',
        'Iteration 35 補進外資真實持股（存量）。這裡用 Iteration 30 建立的巢狀走查',
        '測「現行 + 持股」是否值得部署——測試期完全隔離在挑選過程之外。',
        '',
        '| 模型 | 指標 | 樣本 | 迭代後（外樣本） | 現行設定 | 差距 | 勝出組合 | 穩定性 | 判定 |',
        '|------|------|------|----------------|---------|------|---------|--------|------|',
    ]
    for r in results:
        if not r:
            continue
        lines.append(
            f"| {r['name']} | {r['metric']} | {r['n']:,} | {r['mean_tuned']:.4f} | "
            f"{r['mean_base']:.4f} | {r['gain']:+.4f} | {r['top_variant']} | "
            f"{r['stability']:.0%} | {'**部署**' if r['deploy'] else '不部署'} |")

    lines += ['', '## 每一折挑中了什麼', '',
              '**這張表比上面的分數更值得看。** 若各折挑出的組合不一致，',
              '代表選擇過程主要在跟隨雜訊——即使平均分數上升也不該部署。', '']
    for r in results:
        if not r:
            continue
        lines += [f'### {r["name"]}', '',
                  '| 折 | 內層挑中 | 內層分數 | 收斂輪數 | 外樣本分數 | 現行設定同期 |',
                  '|----|---------|---------|---------|-----------|------------|']
        for i, (p, t, b) in enumerate(zip(r['picked'], r['tuned_scores'],
                                          r['base_scores']), 1):
            lines.append(f"| {i} | {p['variant']} | {p['inner_score']:.4f} | "
                         f"{p['rounds']} | {t:.4f} | {b:.4f} |")
        lines += ['', '每折挑中的超參數：', '']
        for i, p in enumerate(r['picked'], 1):
            lines.append(f"- 折 {i}：`{json.dumps(p['params'], sort_keys=True)}`")
        lines.append('')

    lines += [
        '## 判讀',
        '',
        f'部署門檻：外層平均須高出現行設定 {DEPLOY_MARGIN:+}，'
        f'且勝出組合至少在 {STABILITY_MIN:.0%} 的折中被選中。',
        '',
        '兩個條件缺一不可。只看分數會讓「剛好在某一折運氣好」的設定通過；',
        '只看穩定性則可能留下一個穩定但沒有提升的組合。',
    ]
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    print(f'\n報告已寫入 {path}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--models', nargs='+', default=list(MODELS))
    ap.add_argument('--quick', action='store_true')
    ap.add_argument('--stocks', nargs='+', default=None,
                    help='只取部分股票（流程驗證用）')
    args = ap.parse_args()
    global STOCK_FILTER
    STOCK_FILTER = args.stocks

    grid = QUICK_GRID if args.quick else PARAM_GRID
    results = []
    for name in args.models:
        if name not in MODELS:
            print(f'未知模型：{name}')
            continue
        try:
            results.append(nested_evaluate(name, MODELS[name], grid))
        except Exception as e:
            print(f'  {name} 失敗：{type(e).__name__}: {str(e)[:160]}')
    write_report(results, args.quick)
    return results


if __name__ == '__main__':
    main()
