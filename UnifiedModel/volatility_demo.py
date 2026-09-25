"""
波動率 vs 方向：可預測性對照實驗（Iteration 12 附錄）
─────────────────────────────────────────────────────
用途：具體說明「預測波動率比預測方向容易得多」這句話的實際差距。
全部在同一份資料、同一套走查驗證下比較，口徑一致。

三個問題：
  A 方向     未來 N 日報酬是正是負                 → 基準 = 永遠喊多數類
  B 波動率   未來 N 日的實現波動率是多少（迴歸）    → 基準 = 用過去 N 日波動率直接外推
  C 大幅波動 未來 N 日絕對報酬是否 > 門檻（分類）    → 基準 = 永遠喊多數類

用法：python volatility_demo.py [--horizon 5] [--big-move 0.05]
產出：results/volatility_demo.md
"""

import argparse
import os
import sys
from datetime import datetime

import numpy as np
import pandas as pd

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(BASE_DIR, '..', 'Crawler'))

from features import ALL_FEATURES, build_panel, LOAD_SQL   # noqa: E402

RESULTS_DIR = os.path.join(BASE_DIR, 'results')
N_FOLDS = 5


def load_data(horizon: int) -> pd.DataFrame:
    from db.connection import get_conn
    with get_conn() as conn:
        raw = pd.read_sql(LOAD_SQL, conn)

    panel = build_panel(raw).sort_values(['stock_id', 'trade_date'])
    g = panel.groupby('stock_id')

    # 未來 N 日報酬（方向與大幅波動用）
    panel['fwd_ret'] = g['close'].transform(lambda s: s.shift(-horizon) / s - 1)

    # 未來 N 日實現波動率＝未來 N 個日報酬的標準差
    daily = g['close'].transform(lambda s: s.pct_change())
    panel['fwd_vol'] = (daily.groupby(panel['stock_id'])
                        .transform(lambda s: s.shift(-horizon).rolling(horizon).std()))
    # 過去 N 日已實現波動率（天真基準線：直接拿它當預測值）
    panel['past_vol'] = daily.groupby(panel['stock_id']).transform(
        lambda s: s.rolling(horizon).std())

    return panel.dropna(subset=['fwd_ret', 'fwd_vol', 'past_vol']).reset_index(drop=True)


def folds(data: pd.DataFrame, horizon: int):
    dates = np.sort(data['trade_date'].unique())
    start = int(len(dates) * 0.5)
    bounds = np.linspace(start, len(dates), N_FOLDS + 1).astype(int)
    for i in range(N_FOLDS):
        te_lo, te_hi = dates[bounds[i]], dates[bounds[i + 1] - 1]
        embargo = dates[max(bounds[i] - horizon, 0)]
        tr = (data['trade_date'] < embargo).values
        te = ((data['trade_date'] >= te_lo) & (data['trade_date'] <= te_hi)).values
        if tr.sum() > 500 and te.sum() > 50:
            yield tr, te


def run_classification(data, cols, y, horizon, name):
    """回傳 (準確率, 基準準確率, 樣本數)。"""
    from sklearn.ensemble import HistGradientBoostingClassifier
    X = data[cols].values
    preds, trues = [], []
    for tr, te in folds(data, horizon):
        clf = HistGradientBoostingClassifier(
            max_iter=300, max_depth=4, learning_rate=0.05, min_samples_leaf=100,
            l2_regularization=1.0, early_stopping=True,
            validation_fraction=0.15, random_state=42)
        clf.fit(X[tr], y[tr])
        preds.append(clf.predict(X[te]))
        trues.append(y[te])
    p, t = np.concatenate(preds), np.concatenate(trues)
    base = max(t.mean(), 1 - t.mean())
    return float((p == t).mean()), float(base), len(t)


def run_regression(data, cols, horizon):
    """波動率迴歸；回傳模型與天真基準線的 (相關係數, R², MAE)。"""
    from sklearn.ensemble import HistGradientBoostingRegressor
    X = data[cols].values
    y = data['fwd_vol'].values
    naive = data['past_vol'].values

    preds, trues, naives = [], [], []
    for tr, te in folds(data, horizon):
        reg = HistGradientBoostingRegressor(
            max_iter=300, max_depth=4, learning_rate=0.05, min_samples_leaf=100,
            l2_regularization=1.0, early_stopping=True,
            validation_fraction=0.15, random_state=42)
        reg.fit(X[tr], y[tr])
        preds.append(reg.predict(X[te]))
        trues.append(y[te])
        naives.append(naive[te])

    p, t, nv = np.concatenate(preds), np.concatenate(trues), np.concatenate(naives)

    def stats(pred):
        ss_res = np.sum((t - pred) ** 2)
        ss_tot = np.sum((t - t.mean()) ** 2)
        return {'corr': float(np.corrcoef(pred, t)[0, 1]),
                'r2': float(1 - ss_res / ss_tot),
                'mae': float(np.mean(np.abs(t - pred)))}

    return stats(p), stats(nv), len(t)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--horizon', type=int, default=5)
    ap.add_argument('--big-move', type=float, default=0.05)
    args = ap.parse_args()
    h = args.horizon

    print(f'載入資料（天期 {h} 日）…')
    data = load_data(h)
    print(f'面板 {len(data)} 筆 / {data["stock_id"].nunique()} 檔\n')

    cols = [c for c in ALL_FEATURES if data[c].notna().all()]
    data = data[data[cols].notna().all(axis=1)].reset_index(drop=True)
    print(f'使用 {len(cols)} 個特徵，可用 {len(data)} 列\n')

    # A 方向
    y_dir = (data['fwd_ret'] > 0).astype(int).values
    acc_d, base_d, n_d = run_classification(data, cols, y_dir, h, '方向')
    print(f'A 方向      準確率 {acc_d:.2%}　基準 {base_d:.2%}　'
          f'超越基準 {acc_d - base_d:+.2%}　(n={n_d})')

    # C 大幅波動
    y_big = (data['fwd_ret'].abs() > args.big_move).astype(int).values
    acc_b, base_b, n_b = run_classification(data, cols, y_big, h, '大幅波動')
    print(f'C 大幅波動  準確率 {acc_b:.2%}　基準 {base_b:.2%}　'
          f'超越基準 {acc_b - base_b:+.2%}　(n={n_b}，'
          f'實際發生率 {y_big.mean():.1%})')

    # B 波動率迴歸
    m, nv, n_v = run_regression(data, cols, h)
    print(f'B 波動率    模型 相關係數={m["corr"]:.3f} R²={m["r2"]:.3f}')
    print(f'            天真 相關係數={nv["corr"]:.3f} R²={nv["r2"]:.3f}'
          f'（直接拿過去 {h} 日波動率外推）')

    lines = [
        '# 波動率 vs 方向：可預測性對照（Iteration 12 附錄）',
        '',
        f'**執行時間：** {datetime.now().strftime("%Y-%m-%d %H:%M")}',
        f'**天期：** {h} 日　**大幅波動門檻：** ±{args.big_move:.0%}',
        f'**資料：** {len(data)} 列 / {data["stock_id"].nunique()} 檔，'
        f'{len(cols)} 個特徵，{N_FOLDS} 折走查驗證 + 標籤期封存',
        '',
        '## 分類問題',
        '',
        '| 問題 | 準確率 | 基準（永遠喊多數類） | 超越基準 |',
        '|------|-------|--------------------|---------|',
        f'| A 未來 {h} 日漲還是跌 | {acc_d:.2%} | {base_d:.2%} | **{acc_d - base_d:+.2%}** |',
        f'| C 未來 {h} 日是否波動超過 ±{args.big_move:.0%} | {acc_b:.2%} | {base_b:.2%} | **{acc_b - base_b:+.2%}** |',
        '',
        '## 波動率迴歸（預測未來實現波動率的數值）',
        '',
        '| 方法 | 相關係數 | R² | MAE |',
        '|------|---------|-----|-----|',
        f'| 模型（{len(cols)} 特徵） | **{m["corr"]:.3f}** | {m["r2"]:.3f} | {m["mae"]:.5f} |',
        f'| 天真基準（過去 {h} 日波動率直接外推） | {nv["corr"]:.3f} | {nv["r2"]:.3f} | {nv["mae"]:.5f} |',
        '',
        '## 解讀',
        '',
        '相關係數可直接對照 Iteration 11 的 M1 回測：',
        '那裡「預測價格變動 vs 實際變動」的相關係數只有 **+0.05**（等於沒有資訊）。',
        '波動率的相關係數若明顯高於此，即證明它承載了真實可預測的結構。',
        '',
        '**實務用途**（波動率預測不是拿來決定買賣方向的）：',
        '',
        '- **部位大小**：預測高波動 → 縮小部位，讓每筆交易的風險金額維持一致',
        '- **停損距離**：依預測波動率設停損，而非固定百分比，避免被正常震盪掃出場',
        '- **選擇權**：波動率就是選擇權定價的核心輸入，可直接轉為交易決策',
        '- **擇時觀望**：預測到大幅波動但方向不明時，最好的動作往往是不進場',
    ]
    os.makedirs(RESULTS_DIR, exist_ok=True)
    path = os.path.join(RESULTS_DIR, 'volatility_demo.md')
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    print(f'\n報告已寫入 {path}')


if __name__ == '__main__':
    main()
