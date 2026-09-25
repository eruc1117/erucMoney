"""
部位規則回測（Iteration 13）
────────────────────────────
風險模組的承諾是：「不論標的波動大小，每筆交易的預期虧損金額一致（約 2% 資金）」。
本腳本直接檢驗這個承諾是否兌現，並與等權重對照。

比較三種配置方式（同一批交易、同一段測試期）：
    等權重         每筆都投入相同比例（基準）
    事後波動率     用**實際**已實現波動率配置（理論上限，實務做不到，僅供對照）
    模型預測       用波動率模型的預測值配置（實際可用的方法）

關鍵指標：
    超限比例   實際虧損超過目標風險（2%）的交易比例——越低代表風控越可靠
    P&L 離散度 各筆損益的標準差——波動率配置的目的就是讓風險均勻，應更低
    最差 5%    尾端風險，實務上最痛的部分

用法：python backtest_risk.py [--holding-days 5] [--risk 0.02]
產出：results/risk_backtest.md
"""

import argparse
import math
import os
import sys
from datetime import datetime

import numpy as np
import pandas as pd

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(BASE_DIR, '..', 'Crawler'))

from features import build_panel, LOAD_SQL   # noqa: E402
from train_volatility import add_vol_features, ewma_vol, folds, load_data  # noqa: E402

RESULTS_DIR = os.path.join(BASE_DIR, 'results')

STOP_SIGMA = 2.0
POSITION_MIN, POSITION_MAX = 0.05, 1.00


def position_from_vol(vol: np.ndarray, risk: float, holding_days: int) -> np.ndarray:
    """與 Crawler/risk_model.py 完全相同的換算，確保回測與線上一致。"""
    stop = STOP_SIGMA * vol * math.sqrt(max(holding_days, 1))
    return np.clip(risk / np.maximum(stop, 1e-8), POSITION_MIN, POSITION_MAX)


def walk_forward_vol(data: pd.DataFrame, cols: list, horizon: int):
    """走查預測波動率（與訓練同一套切分，測試集永遠在訓練集之後）。"""
    from sklearn.ensemble import HistGradientBoostingRegressor
    X = data[cols].values
    y_raw = data['fwd_vol'].values
    y = np.log(np.maximum(y_raw, 1e-8))

    preds, idxs = [], []
    for tr, te in folds(data, horizon):
        reg = HistGradientBoostingRegressor(
            max_iter=400, max_depth=5, learning_rate=0.05, min_samples_leaf=80,
            l2_regularization=1.0, early_stopping=True,
            validation_fraction=0.15, random_state=42)
        reg.fit(X[tr], y[tr])
        preds.append(np.exp(reg.predict(X[te])))
        idxs.append(np.where(te)[0])
    if not preds:
        return None, None
    return np.concatenate(preds), np.concatenate(idxs)


def evaluate(name: str, pos: np.ndarray, ret: np.ndarray, risk: float) -> dict:
    """
    以「持有期報酬 × 部位比例」計算每筆損益。
    超限＝虧損超過目標風險上限（部位規則的核心承諾）。
    """
    pnl = pos * ret
    loss = -np.minimum(pnl, 0)
    return {
        'name': name,
        'n': int(len(pnl)),
        'avg_position': float(pos.mean()),
        'pnl_std': float(pnl.std()),
        'over_limit': float((loss > risk).mean()),
        'worst5': float(np.percentile(pnl, 5)),
        'worst1': float(np.percentile(pnl, 1)),
        'avg_pnl': float(pnl.mean()),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--holding-days', type=int, default=5)
    ap.add_argument('--risk', type=float, default=0.02)
    ap.add_argument('--horizon', type=int, default=20)
    args = ap.parse_args()

    import joblib
    bundle = joblib.load(os.path.join(BASE_DIR, 'saved_models', 'volatility.joblib'))
    cols = bundle['feature_cols']
    horizon = bundle.get('horizon', args.horizon)

    print(f'載入資料（波動率天期 {horizon} 日，持有 {args.holding_days} 日）…')
    data = load_data(horizon)
    data = data[data[cols].notna().all(axis=1)].reset_index(drop=True)

    # 持有期報酬（與波動率天期分開；持有期才是實際承擔風險的期間）
    data = data.sort_values(['stock_id', 'trade_date'])
    data['hold_ret'] = data.groupby('stock_id')['close'].transform(
        lambda s: s.shift(-args.holding_days) / s - 1)
    # 持有期內的實際已實現波動率（「事後波動率」對照組用）
    daily = data.groupby('stock_id')['close'].transform(lambda s: s.pct_change())
    data['hold_vol'] = daily.groupby(data['stock_id']).transform(
        lambda s: s.shift(-args.holding_days).rolling(args.holding_days).std())
    data = data.dropna(subset=['hold_ret', 'hold_vol']).reset_index(drop=True)
    print(f'可用 {len(data)} 筆 / {data["stock_id"].nunique()} 檔')

    pred_vol, idx = walk_forward_vol(data, cols, horizon)
    if pred_vol is None:
        print('走查無有效折')
        return

    sub = data.iloc[idx].reset_index(drop=True)
    ret = sub['hold_ret'].values
    ewma = sub['ewma_vol'].values
    blended = 0.5 * pred_vol + 0.5 * ewma      # 與部署設定一致（blend=avg）

    print(f'測試樣本 {len(sub)} 筆'
          f'（{str(sub["trade_date"].min())[:10]} ~ {str(sub["trade_date"].max())[:10]}）\n')

    # 等權重的比較基準：取模型配置的平均部位，確保兩者資金投入規模相當
    pos_model = position_from_vol(blended, args.risk, args.holding_days)
    rows = [
        evaluate('等權重（固定部位）',
                 np.full(len(ret), pos_model.mean()), ret, args.risk),
        evaluate('EWMA 波動率配置',
                 position_from_vol(ewma, args.risk, args.holding_days), ret, args.risk),
        evaluate('模型預測配置（線上設定）', pos_model, ret, args.risk),
        evaluate('事後實際波動率配置（理論上限）',
                 position_from_vol(sub['hold_vol'].values, args.risk, args.holding_days),
                 ret, args.risk),
    ]

    print(f"{'配置方式':26} {'平均部位':>8} {'超限比例':>8} {'P&L標準差':>10} "
          f"{'最差5%':>8} {'最差1%':>8}")
    print('-' * 78)
    for r in rows:
        print(f"{r['name']:26} {r['avg_position']:7.1%} {r['over_limit']:7.2%} "
              f"{r['pnl_std']:9.3%} {r['worst5']:7.2%} {r['worst1']:7.2%}")

    write_report(rows, args, len(sub))


def write_report(rows, args, n):
    os.makedirs(RESULTS_DIR, exist_ok=True)
    path = os.path.join(RESULTS_DIR, 'risk_backtest.md')
    lines = [
        '# 部位規則回測（Iteration 13）',
        '',
        f'**執行時間：** {datetime.now().strftime("%Y-%m-%d %H:%M")}',
        f'**設定：** 持有 {args.holding_days} 日、單筆風險上限 {args.risk:.0%}、'
        f'停損 {STOP_SIGMA:.0f}σ　**測試樣本：** {n} 筆（走查測試期）',
        '',
        '> 部位規則的承諾是「每筆交易的虧損不超過資金的 '
        f'{args.risk:.0%}」。**超限比例**直接檢驗這個承諾。',
        '> P&L 標準差衡量風險是否均勻——波動率配置的目的正是讓每筆風險一致。',
        '',
        '| 配置方式 | 平均部位 | 超限比例 | P&L 標準差 | 最差 5% | 最差 1% |',
        '|---------|---------|---------|-----------|--------|--------|',
    ]
    for r in rows:
        lines.append(f"| {r['name']} | {r['avg_position']:.1%} | "
                     f"**{r['over_limit']:.2%}** | {r['pnl_std']:.3%} | "
                     f"{r['worst5']:.2%} | {r['worst1']:.2%} |")
    lines += [
        '',
        '## 怎麼讀',
        '',
        '- **等權重**是基準：不看波動一律投入相同比例。',
        '- **事後實際波動率**是理論上限：用未來才知道的真實波動配置，實務做不到，',
        '  用來衡量「即使預測完美，還能改善多少」。',
        '- **模型預測配置**是實際上線的方法。它應該明顯優於等權重，',
        '  並盡量接近事後波動率的表現。',
        '',
        '注意：部位規則**不會提高勝率**，它管的是風險大小的一致性。',
        '平均損益的差異主要來自平均部位不同，不代表策略優劣。',
    ]
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    print(f'\n報告已寫入 {path}')


if __name__ == '__main__':
    main()
