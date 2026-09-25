"""
美股開盤跳空預測（Iteration 32）
────────────────────────────────
預測目標：美股 D 日 **開盤 ÷ D−1 收盤 − 1**，12 檔美股／ETF 各自一個預測。

## 為什麼是這個題目

`explore_us.py` 一次量了四個目標，結論很乾脆（2018-01 ~ 2026-09、23,388 列走查）：

| 目標 | 只用美股自身 | 加台股＋韓日 | 天真基準 |
|------|------------|-------------|---------|
| 開盤跳空 | 相關 0.0085、方向 50.29% | **相關 0.2781、方向 60.68%** | 多數類別 55.48% |
| 盤中（D 收÷D 開） | 相關 0.0217、方向 49.53% | 相關 0.0163、方向 49.43% | 多數類別 51.45% |
| 全日 | 相關 0.0126、方向 50.26% | 相關 0.1589、方向 54.68% | 多數類別 53.00% |
| 未來 20 日波動率 | QLIKE −6.4542 | QLIKE −6.4625 | **EWMA −6.4645（更好）** |

三件事同時成立：

1. **只用美股自己的歷史，什麼都預測不出來**（相關 0.0085 ≈ 0）。
   這與 Iteration 11 在台股得到的結論一致——價格序列本身沒有訊號。
2. **亞洲時區的當日資訊有真實的增量**，而且幾乎是唯一的來源。
   這正是跳空模型（Iteration 16）的鏡像：那邊美股 D−1 → 台股 D，這邊台股 D → 美股 D。
3. **可交易的那一段（盤中）依然不可預測。** 跳空發生在開盤瞬間，
   和台股跳空模型一樣，它是參考資訊不是買賣訊號。

波動率則是誠實的負面結果：相關與 R²(log) 都比 EWMA 好（0.680 vs 0.645、+0.581），
但 QLIKE 輸給 EWMA。依 Iteration 13 立下的門檻（QLIKE 須先優於 EWMA）**不部署**。
台股波動率模型贏得了這個門檻、美股沒有——不改門檻去遷就結果。

## 為什麼不用台指期夜盤（這是最容易犯的錯）

`futures_daily` 上 trade_date 標記為 D+1 的 `after_market` 那一列，
時間是 D 15:00 ~ D+1 05:00 台北時間 ＝ D 03:00 ~ D 17:00 ET，
**涵蓋整段美股 D 日盤**。拿它預測美股 D 就是把答案當特徵。
本模型只用 `position`（日盤，D 01:45 ET 收），而消融也顯示它沒有增量
（0.2741 vs 0.2781），故最終版本連日盤都不納入。

用法：python train_us_gap.py [--folds 4]
產出：results/us_gap_model.md、saved_models/us_gap.joblib
"""

import argparse
import os
import sys
from datetime import datetime

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, '..', 'Crawler'))

RESULTS_DIR = os.path.join(BASE_DIR, 'results')
MODEL_DIR = os.path.join(BASE_DIR, 'saved_models')

HORIZON = 1
BLOCKS = ['own', 'usmkt', 'cs', 'tw', 'asia']
TARGET = 'y_gap'
BASELINE = 'own_gap_prev'          # 天真基準：跳空持續（實測是負相關，等於沒有）

# 部署門檻：方向要贏多數類別、相關要有實質水準，而且**每一折都不能輸**。
# 平均贏、某一折輸，代表贏的是某段特定行情，不是穩定的關係。
DEPLOY_DIR_MARGIN = 0.02
DEPLOY_MIN_CORR = 0.15

PARAMS = dict(max_iter=400, learning_rate=0.05, max_depth=5,
              min_samples_leaf=60, l2_regularization=1.0, random_state=42)


def load_data(for_inference: bool = False):
    """
    美股面板 + 跳空目標。

    for_inference=True 時不要求目標欄存在——線上預測的是「還沒開盤的那一天」，
    照樣剔除會讓基準日永遠落後一天（振幅模型首版踩過的坑）。
    """
    import us_panel
    panel = us_panel.build(blocks=BLOCKS)
    if panel.empty:
        return panel, []
    cols = [c for c in us_panel.columns_for(BLOCKS) if c in panel.columns]
    extra = [] if for_inference else [TARGET, BASELINE]
    d = us_panel.align(panel, BLOCKS, extra_required=extra)
    return d, cols


def _metrics(pred, act, base):
    up = act > 0
    return {
        'n_test': int(len(pred)),
        'corr': float(np.corrcoef(pred, act)[0, 1]),
        'base_corr': float(np.corrcoef(base, act)[0, 1]),
        'dir_acc': float(np.mean((pred > 0) == up)),
        'dir_base': float(max(up.mean(), 1 - up.mean())),
        'mae': float(np.mean(np.abs(pred - act))),
        'zero_mae': float(np.mean(np.abs(act))),
        'base_mae': float(np.mean(np.abs(base - act))),
    }


def walk_forward(d, cols, n_folds=4):
    dates = np.sort(d['trade_date'].unique())
    bounds = np.linspace(int(len(dates) * 0.5), len(dates), n_folds + 1).astype(int)
    folds, per_ticker = [], []
    for i in range(n_folds):
        lo, hi = dates[bounds[i]], dates[bounds[i + 1] - 1]
        te = (d['trade_date'] >= lo) & (d['trade_date'] <= hi)
        tr = d['trade_date'] < dates[max(bounds[i] - HORIZON, 0)]
        if tr.sum() < 2000 or te.sum() < 200:
            continue
        m = HistGradientBoostingRegressor(**PARAMS)
        m.fit(d.loc[tr, cols].values, d.loc[tr, TARGET].values)
        pred = m.predict(d.loc[te, cols].values)
        sub = d.loc[te, ['ticker', TARGET, BASELINE]].copy()
        sub['pred'] = pred
        sub = sub[np.isfinite(sub['pred']) & np.isfinite(sub[TARGET])
                  & np.isfinite(sub[BASELINE])]

        row = {'fold': i + 1, 'from': str(lo)[:10], 'to': str(hi)[:10]}
        row.update(_metrics(sub['pred'].values, sub[TARGET].values, sub[BASELINE].values))
        folds.append(row)
        for tk, g in sub.groupby('ticker'):
            if len(g) < 50:
                continue
            r = _metrics(g['pred'].values, g[TARGET].values, g[BASELINE].values)
            r.update(ticker=tk, fold=i + 1)
            per_ticker.append(r)
    return folds, pd.DataFrame(per_ticker)


def weighted(folds, key):
    w = np.array([f['n_test'] for f in folds], float)
    return float(np.sum([f[key] for f in folds] * w) / w.sum())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--folds', type=int, default=4)
    ap.add_argument('--no-save', action='store_true')
    args = ap.parse_args()

    print('建立美股面板…')
    d, cols = load_data()
    if d.empty:
        print('面板是空的——先跑 python Crawler/backfill_us.py')
        return
    print(f'{len(d):,} 列 / {d["ticker"].nunique()} 檔　特徵 {len(cols)} 個　'
          f'{d.trade_date.min().date()} ~ {d.trade_date.max().date()}')

    folds, per_ticker = walk_forward(d, cols, args.folds)
    if not folds:
        print('樣本不足，無法走查')
        return

    corr, dir_acc = weighted(folds, 'corr'), weighted(folds, 'dir_acc')
    dir_base, mae = weighted(folds, 'dir_base'), weighted(folds, 'mae')
    zero_mae = weighted(folds, 'zero_mae')
    worst_dir = min(f['dir_acc'] - f['dir_base'] for f in folds)
    deploy = (corr >= DEPLOY_MIN_CORR
              and dir_acc - dir_base >= DEPLOY_DIR_MARGIN
              and worst_dir > 0)

    print(f'\n走查：相關 {corr:.4f}　方向 {dir_acc*100:.2f}%'
          f'（多數類別 {dir_base*100:.2f}%，最差折 {worst_dir*100:+.2f}pp）')
    print(f'　　　MAE {mae*100:.3f}%　猜 0 的 MAE {zero_mae*100:.3f}%')
    print(f'部署判定：{"通過" if deploy else "未通過"}'
          f'（需相關 ≥{DEPLOY_MIN_CORR}、方向贏多數類別 {DEPLOY_DIR_MARGIN*100:.0f}pp 以上，'
          f'且每折都贏）')

    tk_summary = summarise_tickers(per_ticker)
    print('\n分標的（走查加權）：')
    for r in tk_summary:
        print(f"  {r['ticker']:<5} 相關 {r['corr']:.3f}　方向 {r['dir_acc']*100:5.2f}%"
              f"（多數類別 {r['dir_base']*100:5.2f}%）　MAE {r['mae']*100:.3f}%")

    write_report(d, cols, folds, tk_summary, corr, dir_acc, dir_base,
                 mae, zero_mae, worst_dir, deploy, args.folds)
    if deploy and not args.no_save:
        save_model(d, cols, corr, dir_acc, dir_base, tk_summary)


def summarise_tickers(per_ticker: pd.DataFrame) -> list:
    """各標的跨折的加權平均。前端要顯示「這一檔的預測可不可信」，靠的就是這份。"""
    if per_ticker.empty:
        return []
    out = []
    for tk, g in per_ticker.groupby('ticker'):
        w = g['n_test'].values.astype(float)
        out.append({
            'ticker': tk,
            'n_test': int(w.sum()),
            'corr': float(np.sum(g['corr'] * w) / w.sum()),
            'dir_acc': float(np.sum(g['dir_acc'] * w) / w.sum()),
            'dir_base': float(np.sum(g['dir_base'] * w) / w.sum()),
            'mae': float(np.sum(g['mae'] * w) / w.sum()),
        })
    return sorted(out, key=lambda r: -r['corr'])


def save_model(d, cols, corr, dir_acc, dir_base, tk_summary):
    import joblib
    m = HistGradientBoostingRegressor(**dict(PARAMS, early_stopping=True,
                                             validation_fraction=0.15))
    m.fit(d[cols].values, d[TARGET].values)
    os.makedirs(MODEL_DIR, exist_ok=True)
    path = os.path.join(MODEL_DIR, 'us_gap.joblib')
    joblib.dump({
        'model': m, 'feature_cols': cols, 'blocks': BLOCKS,
        'horizon': HORIZON, 'target': TARGET,
        'trained_at': datetime.now().isoformat(),
        'tickers': sorted(d['ticker'].unique().tolist()),
        # 推論端據此把預測值換成「這是大跳空還是普通波動」，不必自己寫死門檻
        'quantiles': {str(q): float(d[TARGET].quantile(q))
                      for q in (0.05, 0.25, 0.5, 0.75, 0.95)},
        'walk_forward': {'corr': corr, 'dir_acc': dir_acc, 'dir_base': dir_base},
        # 分標的表現：前端逐檔標示可信度用，別讓使用者以為 12 檔一樣準
        'per_ticker': {r['ticker']: r for r in tk_summary},
    }, path)
    print(f'\n模型已存 {path}')
    try:
        import model_registry as registry
        v = registry.register_training('us_gap', train_metrics={
            'rows': len(d), 'features': len(cols), 'horizon': HORIZON,
            'corr': corr, 'dir_acc': dir_acc, 'dir_base': dir_base})
        if v:
            print(f'已登錄為 us_gap v{v["version"]}（candidate）')
    except Exception as e:
        print(f'（模型登錄略過：{e}）')


def write_report(d, cols, folds, tk_summary, corr, dir_acc, dir_base,
                 mae, zero_mae, worst_dir, deploy, n_folds):
    os.makedirs(RESULTS_DIR, exist_ok=True)
    path = os.path.join(RESULTS_DIR, 'us_gap_model.md')
    L = [
        '# 美股開盤跳空預測（Iteration 32 建立，Iteration 34 擴為 23 檔）', '',
        f'**執行時間：** {datetime.now().strftime("%Y-%m-%d %H:%M")}',
        '**目標：** 美股 D 日開盤 ÷ D−1 收盤 − 1',
        f'**樣本：** {len(d):,} 列 / {d["ticker"].nunique()} 檔　'
        f'{d.trade_date.min().date()} ~ {d.trade_date.max().date()}',
        f'**特徵：** {len(cols)} 個（{" + ".join(BLOCKS)}）',
        f'**驗證：** {n_folds} 折擴張視窗走查 + 1 日標籤期封存', '',
        '| 折 | 測試期 | 測試列 | 相關 | 方向 | 多數類別 | MAE | 猜 0 的 MAE |',
        '|----|--------|-------|------|------|---------|-----|-----------|',
    ]
    for f in folds:
        L.append(f"| {f['fold']} | {f['from']} ~ {f['to']} | {f['n_test']:,} | "
                 f"{f['corr']:.4f} | {f['dir_acc']*100:.2f}% | {f['dir_base']*100:.2f}% | "
                 f"{f['mae']*100:.3f}% | {f['zero_mae']*100:.3f}% |")
    L += [
        '',
        f'**加權平均：相關 {corr:.4f}、方向 {dir_acc*100:.2f}%'
        f'（多數類別 {dir_base*100:.2f}%，最差折 {worst_dir*100:+.2f}pp）、'
        f'MAE {mae*100:.3f}%（猜 0：{zero_mae*100:.3f}%）。**',
        f'**部署判定：{"通過" if deploy else "未通過"}**'
        f'（需相關 ≥{DEPLOY_MIN_CORR}、方向贏多數類別 {DEPLOY_DIR_MARGIN*100:.0f}pp、每折都贏）。',
        '',
        '## 分標的',
        '',
        '各標的的準確度差很多，前端要逐檔標示——否則使用者會以為每一檔都一樣準。',
        'EWT 本身就是台股（在美國時區交易），它的成績是套套邏輯，不代表模型能預測美股。',
        '',
        '| 標的 | 測試列 | 相關 | 方向 | 多數類別 | MAE |',
        '|------|-------|------|------|---------|-----|',
    ]
    for r in tk_summary:
        L.append(f"| {r['ticker']} | {r['n_test']:,} | {r['corr']:.3f} | "
                 f"{r['dir_acc']*100:.2f}% | {r['dir_base']*100:.2f}% | {r['mae']*100:.3f}% |")
    L += [
        '',
        '## 界線：這不是買賣訊號',
        '',
        '跳空發生在開盤那一刻，事後無法交易——與台股跳空模型（Iteration 16）完全相同。',
        '而 `explore_us.py` 已量到「盤中」那一段（開盤後唯一可交易的部分）',
        '相關僅 0.02、方向 49.4%，**低於多數類別 51.45%**。',
        '所以本模型的用途是盤前參考與掛單價位，不是方向訊號，也不進任何投票計分。',
        '',
        '## MAE 幾乎沒有改善，這要說清楚',
        '',
        f'模型 MAE {mae*100:.3f}%、直接猜 0 是 {zero_mae*100:.3f}%——量級預測的改善很小。',
        '模型抓到的是**方向與排序**，不是幅度。用途要跟著這個事實走：',
        '「明天大概開高還是開低、幅度算不算大」可以參考，「開高 1.2%」不要當真。',
    ]
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(L))
    print(f'報告已寫入 {path}')


if __name__ == '__main__':
    main()
