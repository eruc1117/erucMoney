"""
波動率預測模型訓練與優化（Iteration 13）
────────────────────────────────────────
為何做這個：Iteration 12 證實方向預測沒有 edge（超越基準 −0.09%），
但波動率的相關係數達 0.508（對照 M1 價格變動預測僅 0.05）。
波動率預測不用來決定買賣方向，而是用來**管理風險**：部位大小與停損距離。

本腳本比較數個設計選擇，全部在同一套走查驗證下進行：

  目標變換   raw / log —— 波動率右偏，raw 的 MSE 會被高波動離群值主導
  特徵組合   基礎價量 / 加入多尺度波動 / 加入 Parkinson 高低價估計量
  基準線     天真外推（過去 N 日波動率）、EWMA（RiskMetrics λ=0.94）

評估指標（波動率預測的標準做法，不只看 R²）：
  相關係數   排序能力（部位大小只需要排序對）
  R²         解釋變異比例（在 log 空間計算，避免離群值主導）
  QLIKE      波動率預測的標準損失函數，對「低估波動」懲罰較重
             —— 這符合實務：低估風險的代價遠大於高估

用法：
    python train_volatility.py                    # 全部變體
    python train_volatility.py --horizons 5 10 20
產出：
    saved_models/volatility.joblib（最佳變體，需優於 EWMA 基準才部署）
    results/volatility_experiment.md
"""

import argparse
import os
import sys
from datetime import datetime

import numpy as np
import pandas as pd

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(BASE_DIR, '..', 'Crawler'))

from night_features import NIGHT_FEATURES   # noqa: E402
from features import build_panel, LOAD_SQL, PRICE_FEATURES, CS_FEATURES, \
    MARKET_FEATURES   # noqa: E402

RESULTS_DIR = os.path.join(BASE_DIR, 'results')
MODEL_DIR = os.path.join(BASE_DIR, 'saved_models')
N_FOLDS = 5

# 多尺度波動與高低價估計量（本迭代新增，供消融比較）
EXTRA_VOL_FEATURES = [
    'vol_60d', 'vol_ratio_5_20', 'vol_ratio_20_60',
    'parkinson_5d', 'parkinson_20d', 'range_pct', 'range_ma5',
    'gap_abs_ma5', 'ret_abs_ma5', 'ret_abs_ma20',
]


def add_vol_features(panel: pd.DataFrame) -> pd.DataFrame:
    """補上專為波動率預測設計的特徵。"""
    p = panel.sort_values(['stock_id', 'trade_date']).copy()
    g = p.groupby('stock_id')

    ret1 = g['close'].transform(lambda s: s.pct_change())
    p['vol_60d'] = ret1.groupby(p['stock_id']).transform(lambda s: s.rolling(60).std())
    p['vol_ratio_5_20'] = p['vol_5d'] / (p['vol_20d'] + 1e-9)
    p['vol_ratio_20_60'] = p['vol_20d'] / (p['vol_60d'] + 1e-9)

    # Parkinson 估計量：用當日高低價估波動，統計效率高於收盤對收盤
    hl = np.log(p['high'] / (p['low'] + 1e-9)) ** 2 / (4 * np.log(2))
    p['parkinson_5d'] = np.sqrt(hl.groupby(p['stock_id']).transform(
        lambda s: s.rolling(5).mean()))
    p['parkinson_20d'] = np.sqrt(hl.groupby(p['stock_id']).transform(
        lambda s: s.rolling(20).mean()))

    p['range_pct'] = (p['high'] - p['low']) / (p['close'] + 1e-9)
    p['range_ma5'] = p['range_pct'].groupby(p['stock_id']).transform(
        lambda s: s.rolling(5).mean())
    p['gap_abs_ma5'] = p['gap_pct'].abs().groupby(p['stock_id']).transform(
        lambda s: s.rolling(5).mean())
    p['ret_abs_ma5'] = ret1.abs().groupby(p['stock_id']).transform(
        lambda s: s.rolling(5).mean())
    p['ret_abs_ma20'] = ret1.abs().groupby(p['stock_id']).transform(
        lambda s: s.rolling(20).mean())
    return p


def ewma_vol(ret: pd.Series, lam: float = 0.94) -> pd.Series:
    """RiskMetrics EWMA 波動率——業界標準基準線，比天真外推強得多。"""
    var = ret.pow(2).ewm(alpha=1 - lam, adjust=False).mean()
    return np.sqrt(var)


def load_data(horizon: int) -> pd.DataFrame:
    """
    日報酬一律使用**除權息調整後**的版本（Iteration 17）。

    未調整時，一次除權息的機械性跌幅（最大實測 22.06%）會落在 20 日滾動窗內，
    汙染其後 20 筆樣本的波動度估計——463 筆事件實際影響 9,260 筆（5.54%），
    而非只有事件當天的 0.28%。
    實測改善：R²(log) +0.4729 → +0.4827、QLIKE −6.4799 → −6.4974。
    """
    from db.connection import get_conn
    from dividend_adj import adjusted_returns

    with get_conn() as conn:
        raw = pd.read_sql(LOAD_SQL, conn)

    panel = add_vol_features(build_panel(raw))
    panel = panel.sort_values(['stock_id', 'trade_date']).reset_index(drop=True)
    daily = pd.Series(adjusted_returns(panel).values, index=panel.index)
    g = panel.groupby('stock_id')

    # 目標：未來 horizon 日的實現波動率
    panel['fwd_vol'] = daily.groupby(panel['stock_id']).transform(
        lambda s: s.shift(-horizon).rolling(horizon).std())
    # 基準線
    panel['naive_vol'] = daily.groupby(panel['stock_id']).transform(
        lambda s: s.rolling(horizon).std())
    panel['ewma_vol'] = daily.groupby(panel['stock_id']).transform(ewma_vol)

    panel['fwd_ret'] = g['close'].transform(lambda s: s.shift(-horizon) / s - 1)

    # ── 外生特徵（Iteration 30 巢狀走查通過）─────────────────────────────
    # 訓練與推論共用這條路徑，確保兩邊的特徵集完全一致——
    # 只在訓練端加特徵，推論時 bundle 的 feature_cols 會找不到欄位而整個失效。
    # 波動率只加夜盤：巢狀走查三折**一致**挑中「現行+夜盤」（3/3），
    # 韓日則未被選中——不硬塞沒被選上的特徵。
    from night_features import attach as attach_night
    panel = attach_night(panel, 'TX')

    return panel.dropna(subset=['fwd_vol', 'naive_vol', 'ewma_vol']).reset_index(drop=True)


# ── 評估 ────────────────────────────────────────────────────────────────────
def qlike(actual: np.ndarray, pred: np.ndarray) -> float:
    """
    QLIKE 損失：ln(σ̂²) + σ²/σ̂²。波動率預測的標準損失函數。
    對「低估波動」的懲罰明顯重於高估——符合風控實務（低估風險代價更大）。
    數值越小越好。
    """
    a2 = np.maximum(actual, 1e-8) ** 2
    p2 = np.maximum(pred, 1e-8) ** 2
    return float(np.mean(np.log(p2) + a2 / p2))


def score(actual: np.ndarray, pred: np.ndarray) -> dict:
    la, lp = np.log(np.maximum(actual, 1e-8)), np.log(np.maximum(pred, 1e-8))
    ss_res = np.sum((la - lp) ** 2)
    ss_tot = np.sum((la - la.mean()) ** 2)
    return {
        'corr': float(np.corrcoef(pred, actual)[0, 1]),
        'r2_log': float(1 - ss_res / ss_tot),
        'qlike': qlike(actual, pred),
        'mae': float(np.mean(np.abs(actual - pred))),
    }


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


def run_variant(data, cols, horizon, log_target: bool):
    from sklearn.ensemble import HistGradientBoostingRegressor
    X = data[cols].values
    y_raw = data['fwd_vol'].values
    y = np.log(np.maximum(y_raw, 1e-8)) if log_target else y_raw

    preds, trues, idxs = [], [], []
    for tr, te in folds(data, horizon):
        reg = HistGradientBoostingRegressor(
            max_iter=400, max_depth=5, learning_rate=0.05, min_samples_leaf=80,
            l2_regularization=1.0, early_stopping=True,
            validation_fraction=0.15, random_state=42)
        reg.fit(X[tr], y[tr])
        p = reg.predict(X[te])
        preds.append(np.exp(p) if log_target else np.maximum(p, 1e-8))
        trues.append(y_raw[te])
        idxs.append(np.where(te)[0])
    if not preds:
        return None, None, None
    return (np.concatenate(preds), np.concatenate(trues), np.concatenate(idxs))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--horizons', type=int, nargs='+', default=[5, 10, 20])
    args = ap.parse_args()

    all_rows = []
    best = None

    for h in args.horizons:
        print(f'\n=== 天期 {h} 日 ===')
        data = load_data(h)
        base_cols = [c for c in PRICE_FEATURES + CS_FEATURES + MARKET_FEATURES
                     if c in data.columns]
        variants = {
            '基礎價量特徵': base_cols,
            '＋多尺度波動與高低價': base_cols + EXTRA_VOL_FEATURES,
            # Iteration 30 巢狀走查：三折**一致**挑中此組合，且每折都贏過現行
            # （外樣本排序相關 0.6483 vs 0.6329）。納入候選讓部署流程自己決定。
            '＋多尺度波動與高低價＋夜盤':
                base_cols + EXTRA_VOL_FEATURES
                + [c for c in NIGHT_FEATURES if c in data.columns],
        }
        # 只保留無缺失的列（各變體共用同一份，確保可比）
        need = sorted(set(sum(variants.values(), [])))
        d = data[data[need].notna().all(axis=1)].reset_index(drop=True)
        print(f'可用 {len(d)} 列 / {d["stock_id"].nunique()} 檔')

        # 基準線
        for name, col in (('天真外推', 'naive_vol'), ('EWMA(λ=0.94)', 'ewma_vol')):
            te_idx = np.concatenate([np.where(te)[0] for _, te in folds(d, h)])
            s = score(d['fwd_vol'].values[te_idx], d[col].values[te_idx])
            s.update({'horizon': h, 'name': f'基準：{name}', 'is_base': True})
            all_rows.append(s)
            print(f"  基準 {name:14} 相關={s['corr']:.3f} "
                  f"R²(log)={s['r2_log']:+.3f} QLIKE={s['qlike']:.4f}")

        ewma_qlike = next(r['qlike'] for r in all_rows
                          if r['horizon'] == h and 'EWMA' in r['name'])

        for vname, cols in variants.items():
            for log_t in (False, True):
                pred, true, idx = run_variant(d, cols, h, log_t)
                if pred is None:
                    continue
                label = f"{vname}／{'log 目標' if log_t else 'raw 目標'}"
                ewma_te = d['ewma_vol'].values[idx]

                # 模型擅長排序（相關係數／R² 較高），EWMA 擅長不低估突發波動
                # （QLIKE 較好）。三種組合方式一併評估後再挑。
                candidates = {
                    label: pred,
                    f'{label}＋EWMA 平均': 0.5 * pred + 0.5 * ewma_te,
                    f'{label}＋EWMA 取大': np.maximum(pred, ewma_te),
                }
                for cname, cpred in candidates.items():
                    s = score(true, cpred)
                    s.update({'horizon': h, 'name': cname, 'is_base': False,
                              'n_features': len(cols)})
                    all_rows.append(s)
                    beat = '✓' if s['qlike'] < ewma_qlike else '✗'
                    print(f"  {cname:40} 相關={s['corr']:.3f} "
                          f"R²(log)={s['r2_log']:+.3f} QLIKE={s['qlike']:.4f}"
                          f" 勝EWMA:{beat}")
                    # 兩段式選取：
                    #   門檻 QLIKE 必須優於 EWMA 基準（不得比業界標準基準更會低估風險）
                    #   目標 通過門檻者中取 R²(log) 最高——部位大小靠的是排序能力，
                    #        純看 QLIKE 會選到「取大」這種犧牲排序換保守的變體
                    if s['qlike'] < ewma_qlike and (best is None or s['r2_log'] > best['r2_log']):
                        best = {**s, 'cols': cols, 'log_target': log_t,
                                'horizon': h, 'data_rows': len(d),
                                'blend': ('avg' if '平均' in cname else
                                          'max' if '取大' in cname else 'none'),
                                'ewma_qlike': ewma_qlike}

    write_report(all_rows, best)
    if best:
        print(f"\n最佳：{best['name']}（天期 {best['horizon']}）"
              f" QLIKE={best['qlike']:.4f}（EWMA 基準 {best['ewma_qlike']:.4f}）"
              f" 相關={best['corr']:.3f}")
        save_best(best)
    else:
        print('\n沒有任何變體在 QLIKE 上勝過 EWMA 基準 → **不部署**'
              '（直接使用 EWMA 即可，不需要模型）')


def save_best(best):
    """以最佳設定在全部資料上重訓並存檔，供推論使用。"""
    import joblib
    from sklearn.ensemble import HistGradientBoostingRegressor

    d = load_data(best['horizon'])
    d = d[d[best['cols']].notna().all(axis=1)].reset_index(drop=True)
    y_raw = d['fwd_vol'].values
    y = np.log(np.maximum(y_raw, 1e-8)) if best['log_target'] else y_raw

    reg = HistGradientBoostingRegressor(
        max_iter=400, max_depth=5, learning_rate=0.05, min_samples_leaf=80,
        l2_regularization=1.0, early_stopping=True,
        validation_fraction=0.15, random_state=42)
    reg.fit(d[best['cols']].values, y)

    os.makedirs(MODEL_DIR, exist_ok=True)
    path = os.path.join(MODEL_DIR, 'volatility.joblib')
    joblib.dump({
        'model': reg, 'feature_cols': best['cols'],
        'log_target': best['log_target'], 'horizon': best['horizon'],
        # 推論端必須套用同樣的組合方式，否則與驗證口徑不一致
        'blend': best.get('blend', 'none'),      # none / avg / max（與 EWMA 組合）
        'ewma_lambda': 0.94,
        'trained_at': datetime.now().isoformat(),
        'metrics_walk_forward': {k: best[k] for k in
                                 ('corr', 'r2_log', 'qlike', 'mae')},
        'ewma_qlike_baseline': best.get('ewma_qlike'),
        # 部位大小換算用：訓練集波動率分位數
        'vol_quantiles': {str(q): float(np.quantile(y_raw, q))
                          for q in (0.1, 0.25, 0.5, 0.75, 0.9)},
    }, path)
    print(f'模型已存 {path}')
    _register('volatility', {'horizon': best['horizon'], 'blend': best.get('blend'),
                             'n_features': len(best['cols'])})


def write_report(rows, best):
    os.makedirs(RESULTS_DIR, exist_ok=True)
    path = os.path.join(RESULTS_DIR, 'volatility_experiment.md')
    lines = [
        '# 波動率模型實驗報告（Iteration 13）',
        '',
        f'**執行時間：** {datetime.now().strftime("%Y-%m-%d %H:%M")}',
        f'**驗證：** {N_FOLDS} 折擴張視窗走查 + 標籤期封存',
        '',
        '> QLIKE 是波動率預測的標準損失函數（越小越好），',
        '> 對「低估波動」的懲罰重於高估——符合風控實務。',
        '> R² 在 log 空間計算，避免高波動離群值主導。',
        '',
        '| 天期 | 設定 | 相關係數 | R²(log) | QLIKE | MAE |',
        '|------|------|---------|---------|-------|-----|',
    ]
    for r in sorted(rows, key=lambda x: (x['horizon'], x['qlike'])):
        mark = '' if r.get('is_base') else '**'
        lines.append(f"| {r['horizon']} | {mark}{r['name']}{mark} | {r['corr']:.3f} | "
                     f"{r['r2_log']:+.3f} | {r['qlike']:.4f} | {r['mae']:.5f} |")
    if best:
        lines += ['', '## 最佳設定', '',
                  f"**{best['name']}**（天期 {best['horizon']} 日，{best['n_features']} 個特徵）",
                  '',
                  f"- 相關係數 {best['corr']:.3f}",
                  f"- R²(log) {best['r2_log']:+.3f}",
                  f"- QLIKE {best['qlike']:.4f}",
                  '',
                  '對照組：Iteration 11 的 M1 價格變動預測相關係數僅 +0.05。']
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    print(f'\n報告已寫入 {path}')


def _register(model_type: str, metrics: dict):
    """
    把這次訓練登記到模型登錄表的 candidate 上（Iteration 21）。

    只影響 candidate——已凍結的長期服役版本存在 `_versions/` 底下的快照，
    訓練腳本碰不到。登錄失敗只印訊息，不影響訓練本身。
    """
    try:
        import model_registry as registry
        v = registry.register_training(model_type, train_metrics=metrics)
        if v:
            print(f'已登錄為 {model_type} v{v["version"]}（candidate）')
    except Exception as e:
        print(f'（模型登錄略過：{e}）')


if __name__ == '__main__':
    main()
