"""
成交量預測模型（Iteration 31）
──────────────────────────────
目標：未來 5 個交易日的平均成交量 ÷ 當前 20 日均量。

## 為什麼是這個題目

`cash_allocator` 目前用價格與振幅推部位大小，完全沒有問過一件事：
**這檔股票吃不吃得下這筆錢。** 同樣 20 萬打進去，日均量 3 萬張的台積電
毫無感覺，日均量 800 張的小型股就是明顯的衝擊成本；而量能會變——
今天量夠不代表你要進場的那幾天量還在。

這是目前所有模型都沒有覆蓋的一塊，而且它不是方向預測。
Iteration 11/30 已經證實這份資料上方向沒有 edge、量級與排序有——
成交量是典型的量級問題。

## 驗證結果（`explore_new_models.py`，2012-05 起 83,636 列）

    模型排序相關 0.4639　持續性基準 0.3588　差距 +0.1051　最差折 +0.0908
    預測前 20% 與後 20% 的實際量能比差 0.80 倍

天真基準是**量能持續**（未來 5 日均量 ≈ 最近 5 日均量），不是常數 1.0——
用常數當基準等於宣告基準沒有排序能力，任何模型都會贏。

## 為什麼不接夜盤與期貨結構

同一批 2018 起樣本上：基礎 0.4479、＋夜盤 0.4540、＋夜盤＋期貨 0.4463。
夜盤的增量 +0.0061 不到部署門檻 +0.01，期貨結構還讓它變差。
成交量是個股自身的量能週期，隔夜的指數層級資訊幫不上忙——這說得通。

## 用途與界線

輸出是「相對量能倍數」，**不是方向訊號**。它在投票裡不佔方向權重，
只做流動性閘門：預測量能萎縮時縮小部位或棄權。
把它當成第四個買賣訊號就會重蹈 Iteration 10 的覆轍。

用法：python train_volume.py [--folds 3]
產出：results/volume_model.md、saved_models/volume.joblib
"""

import argparse
import os
import sys
from datetime import datetime

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.ensemble import HistGradientBoostingRegressor

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, '..', 'Crawler'))

RESULTS_DIR = os.path.join(BASE_DIR, 'results')
MODEL_DIR = os.path.join(BASE_DIR, 'saved_models')

HORIZON = 5
BLOCKS = ['price', 'chip', 'cs', 'market']
DEPLOY_MARGIN = 0.01      # 排序相關須高出持續性基準這麼多

PARAMS = dict(max_iter=400, learning_rate=0.05, max_depth=5,
              min_samples_leaf=60, l2_regularization=1.0, random_state=42)


def load_data(for_inference: bool = False) -> pd.DataFrame:
    """
    統一面板 + 成交量目標。

    for_inference=True 時不剔除目標缺失的列——目標要未來 5 天資料，
    照樣剔除會讓線上預測的基準日永遠落後 5 個交易日（振幅模型首版的 bug）。
    """
    import panel as P
    raw = P.build(blocks=BLOCKS)
    d = raw.sort_values(['stock_id', 'trade_date']).reset_index(drop=True)
    g = d.groupby('stock_id')

    vol20 = g['volume'].transform(lambda s: s.rolling(20, min_periods=10).mean())
    d['vol20'] = vol20
    d['y_volume'] = (g['volume'].transform(lambda s: s.shift(-HORIZON).rolling(HORIZON).mean())
                     / vol20.replace(0, np.nan))
    # 天真基準：量能持續。這是要打敗的對象，不是常數 1.0
    d['base_volume'] = (g['volume'].transform(lambda s: s.rolling(5, min_periods=3).mean())
                        / vol20.replace(0, np.nan))

    cols = [c for c in P.columns_for(BLOCKS) if c in d.columns]
    extra = ['base_volume'] + ([] if for_inference else ['y_volume'])
    d = P.align(d, BLOCKS, extra_required=extra)
    return d, cols


def walk_forward(d, cols, n_folds=3):
    dates = np.sort(d['trade_date'].unique())
    start = int(len(dates) * 0.5)
    bounds = np.linspace(start, len(dates), n_folds + 1).astype(int)
    out = []
    for i in range(n_folds):
        lo, hi = dates[bounds[i]], dates[bounds[i + 1] - 1]
        te = (d['trade_date'] >= lo) & (d['trade_date'] <= hi)
        tr = d['trade_date'] < dates[max(bounds[i] - HORIZON, 0)]
        if tr.sum() < 2000 or te.sum() < 200:
            continue
        m = HistGradientBoostingRegressor(**PARAMS)
        # 量能比值右尾極長（爆量可以到 10 倍以上），取 log 讓損失函數不被少數
        # 極端值主導；評估時再換回原尺度比較
        m.fit(d.loc[tr, cols].values, np.log(d.loc[tr, 'y_volume'].clip(lower=0.05)).values)
        pred = np.exp(m.predict(d.loc[te, cols].values))

        act = d.loc[te, 'y_volume'].values
        base = d.loc[te, 'base_volume'].values
        ok = np.isfinite(pred) & np.isfinite(act) & np.isfinite(base)
        pred, act, base = pred[ok], act[ok], base[ok]

        k = max(int(len(pred) * 0.2), 20)
        order = np.argsort(pred)
        out.append({
            'fold': i + 1, 'from': str(lo)[:10], 'to': str(hi)[:10],
            'n_test': int(ok.sum()),
            'rank_corr': float(spearmanr(pred, act).statistic),
            'base_rank_corr': float(spearmanr(base, act).statistic),
            'corr': float(np.corrcoef(pred, act)[0, 1]),
            'mae': float(np.mean(np.abs(pred - act))),
            'base_mae': float(np.mean(np.abs(base - act))),
            'top20_actual': float(np.mean(act[order[-k:]])),
            'bottom20_actual': float(np.mean(act[order[:k]])),
        })
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--folds', type=int, default=3)
    args = ap.parse_args()

    print('載入統一面板…')
    d, cols = load_data()
    print(f'{len(d):,} 列 / {d["stock_id"].nunique()} 檔　特徵 {len(cols)} 個　'
          f'{d.trade_date.min().date()} ~ {d.trade_date.max().date()}')

    folds = walk_forward(d, cols, args.folds)
    w = np.array([f['n_test'] for f in folds], dtype=float)
    def wm(k): return float(np.sum([f[k] for f in folds] * w) / w.sum())

    rank_corr, base_rank = wm('rank_corr'), wm('base_rank_corr')
    gain = rank_corr - base_rank
    worst = min(f['rank_corr'] - f['base_rank_corr'] for f in folds)
    deploy = gain >= DEPLOY_MARGIN and worst > 0

    print(f'\n走查：排序相關 {rank_corr:.4f}　持續性基準 {base_rank:.4f}　'
          f'差距 {gain:+.4f}　最差折 {worst:+.4f}')
    print(f'預測前 20% 實際量能 {wm("top20_actual"):.2f} 倍　'
          f'後 20% {wm("bottom20_actual"):.2f} 倍')
    print(f'部署判定：{"通過" if deploy else "未通過"}'
          f'（需 +{DEPLOY_MARGIN}，且每一折都不輸基準）')

    write_report(d, cols, folds, rank_corr, base_rank, gain, worst, deploy, args.folds)
    if deploy:
        save_model(d, cols, rank_corr, base_rank)


def save_model(d, cols, rank_corr, base_rank):
    import joblib
    m = HistGradientBoostingRegressor(**dict(PARAMS, early_stopping=True,
                                             validation_fraction=0.15))
    m.fit(d[cols].values, np.log(d['y_volume'].clip(lower=0.05)).values)
    os.makedirs(MODEL_DIR, exist_ok=True)
    path = os.path.join(MODEL_DIR, 'volume.joblib')
    joblib.dump({
        'model': m, 'feature_cols': cols, 'blocks': BLOCKS,
        'log_target': True, 'horizon': HORIZON,
        'trained_at': datetime.now().isoformat(),
        # 推論端據此把「量能倍數」轉成流動性等級，不必自己寫死門檻
        'quantiles': {str(q): float(d['y_volume'].quantile(q))
                      for q in (0.1, 0.25, 0.5, 0.75, 0.9)},
        'walk_forward': {'rank_corr': rank_corr, 'base_rank_corr': base_rank},
    }, path)
    print(f'模型已存 {path}')
    try:
        import model_registry as registry
        v = registry.register_training('volume', train_metrics={
            'rows': len(d), 'features': len(cols), 'horizon': HORIZON,
            'rank_corr': rank_corr})
        if v:
            print(f'已登錄為 volume v{v["version"]}（candidate）')
    except Exception as e:
        print(f'（模型登錄略過：{e}）')


def write_report(d, cols, folds, rank_corr, base_rank, gain, worst, deploy, n_folds):
    os.makedirs(RESULTS_DIR, exist_ok=True)
    path = os.path.join(RESULTS_DIR, 'volume_model.md')
    L = [
        '# 成交量預測模型（Iteration 31）',
        '',
        f'**執行時間：** {datetime.now().strftime("%Y-%m-%d %H:%M")}',
        f'**目標：** 未來 {HORIZON} 個交易日平均成交量 ÷ 當前 20 日均量',
        f'**樣本：** {len(d):,} 列 / {d["stock_id"].nunique()} 檔　'
        f'{d.trade_date.min().date()} ~ {d.trade_date.max().date()}',
        f'**特徵：** {len(cols)} 個（{" + ".join(BLOCKS)}）',
        f'**驗證：** {n_folds} 折擴張視窗走查 + {HORIZON} 日標籤期封存',
        '',
        '| 折 | 測試期 | 測試列 | 排序相關 | 持續性基準 | 相關係數 | MAE | 基準 MAE |',
        '|----|--------|-------|---------|-----------|---------|-----|---------|',
    ]
    for f in folds:
        L.append(f"| {f['fold']} | {f['from']} ~ {f['to']} | {f['n_test']:,} | "
                 f"{f['rank_corr']:.4f} | {f['base_rank_corr']:.4f} | {f['corr']:.4f} | "
                 f"{f['mae']:.4f} | {f['base_mae']:.4f} |")
    L += [
        '',
        f'**加權平均：排序相關 {rank_corr:.4f}，持續性基準 {base_rank:.4f}，'
        f'差距 {gain:+.4f}，最差折 {worst:+.4f}。**',
        f'**部署判定：{"通過" if deploy else "未通過"}**'
        f'（需 +{DEPLOY_MARGIN}，且每一折都不輸基準）。',
        '',
        '## 天真基準為什麼是「量能持續」',
        '',
        '成交量的自相關極強。若拿常數 1.0（未來量＝20 日均量）當基準，',
        '基準的排序相關恆為 0，任何模型都會贏——那是灌水，不是驗證。',
        '要打敗的是「未來 5 日的量像最近 5 日的量」這個假設，它本身就有 0.36 的排序相關。',
        '',
        '## 這不是方向訊號',
        '',
        '輸出是相對量能倍數，與漲跌無關。它在投票中**不佔方向權重**，',
        '只作流動性閘門：預測量能萎縮時縮小部位或棄權。',
        '把量能當買賣訊號會重蹈 Iteration 10 的覆轍（無 edge 的訊號送進固定權重計分）。',
        '',
        '## 為什麼沒接夜盤與期貨結構',
        '',
        '同一批 2018 起樣本：基礎 0.4479、＋夜盤 0.4540、＋夜盤＋期貨結構 0.4463。',
        '夜盤增量 +0.0061 未達門檻 +0.01，期貨結構反而更差。',
        '成交量是個股自身的量能週期，指數層級的隔夜資訊幫不上忙。',
    ]
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(L))
    print(f'報告已寫入 {path}')


if __name__ == '__main__':
    main()
