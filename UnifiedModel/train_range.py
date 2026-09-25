"""
週振幅預測（Iteration 19）
──────────────────────────
需求：從預測資料中整理出「一週內高低點有顯著差異」的股票。

本質上這是**振幅預測**，而非方向預測——正好落在本專案唯一驗證出
有預測力的領域（Iteration 13：波動率相關 0.61；Iteration 12：方向超越基準 −0.09%）。

## 預測目標

    range_5d = (未來 5 日最高價 − 未來 5 日最低價) ÷ 今日收盤

亦即「接下來一週股價會在多寬的區間內擺盪」。用途：

  · 波段操作選股——振幅大才有價差可做
  · 風險預警——同樣的部位，振幅大的標的風險高得多
  · 與 M3 買進訊號搭配——訊號相同時，優先選振幅大的

## 「顯著差異」的定義（兩個維度都提供，避免單一標準誤導）

  相對自身：預測振幅 ÷ 該股歷史振幅中位數 —— 排除「這檔本來就波動大」
  相對同儕：當日全體股票的百分位排名 —— 排除「今天全市場都在震盪」

只有兩者**同時偏高**才是真正值得注意的標的。

## 必須勝過的基準

    歷史中位數  用該股過去 60 日的振幅中位數當預測值
    ATR 外推    以 ATR(14) × √5 估算
    EWMA        以 EWMA 波動率 × √5 × 2（常態分布下高低差約 2σ）

用法：python train_range.py
產出：saved_models/range_model.joblib、results/range_model.md
"""

import os
import sys
from datetime import datetime

import numpy as np
import pandas as pd

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(BASE_DIR, '..', 'Crawler'))

from features import build_panel, LOAD_SQL, PRICE_FEATURES, CS_FEATURES, \
    MARKET_FEATURES   # noqa: E402
from train_volatility import add_vol_features, ewma_vol, folds, \
    EXTRA_VOL_FEATURES   # noqa: E402

RESULTS_DIR = os.path.join(BASE_DIR, 'results')
MODEL_DIR = os.path.join(BASE_DIR, 'saved_models')
HORIZON = 5          # 一週＝5 個交易日
N_FOLDS = 5


def load_data(for_inference: bool = False) -> pd.DataFrame:
    """
    建立含未來 5 日振幅的面板。

    **高低價也必須還原公司行動**——Iteration 18 只處理了 close，
    但 high/low 同樣會在除權息與減資日出現機械性缺口。
    以 adj_close ÷ close 求出當日還原係數，再套用到 high/low。

    for_inference=True 時**不剔除目標值缺失的列**。
    目標 range_5d 需要未來 5 天資料，訓練時當然要剔除；
    但推論只需要特徵，若照樣剔除會讓預測基準日落後最新資料 5 個交易日
    （首版就是這個 bug——線上顯示的是一週前的預測）。
    """
    from db.connection import get_conn
    with get_conn() as conn:
        raw = pd.read_sql(LOAD_SQL, conn)

    panel = add_vol_features(build_panel(raw))
    panel = panel.sort_values(['stock_id', 'trade_date']).reset_index(drop=True)

    factor = panel['adj_close'] / panel['close'].replace(0, np.nan)
    panel['adj_high'] = panel['high'] * factor
    panel['adj_low'] = panel['low'] * factor

    g = panel.groupby('stock_id')
    daily = g['adj_close'].transform(lambda s: s.pct_change())
    panel['ewma_vol'] = daily.groupby(panel['stock_id']).transform(ewma_vol)

    # 未來 5 日的最高與最低（不含今日）
    fwd_high = g['adj_high'].transform(
        lambda s: s.shift(-HORIZON).rolling(HORIZON).max())
    fwd_low = g['adj_low'].transform(
        lambda s: s.shift(-HORIZON).rolling(HORIZON).min())
    panel['range_5d'] = (fwd_high - fwd_low) / panel['adj_close']

    # 基準線材料。
    # min_periods 必須放寬：最後 5 筆的 range_5d 為 NaN（缺未來資料），
    # 若沿用預設（視窗內須全部有值），推論當日的歷史中位數會算成 NaN，
    # 導致「相對自身」的顯著判定失效。
    panel['hist_range_median'] = g['range_5d'].transform(
        lambda s: s.shift(1).rolling(60, min_periods=30).median())
    panel['hist_range_std'] = g['range_5d'].transform(
        lambda s: s.shift(1).rolling(60, min_periods=30).std())


    # ── 外生特徵（Iteration 30 巢狀走查通過）─────────────────────────────
    # 訓練與推論共用這條路徑，確保兩邊的特徵集完全一致——
    # 只在訓練端加特徵，推論時 bundle 的 feature_cols 會找不到欄位而整個失效。
    from night_features import attach as attach_night
    from intl_features import attach as attach_intl
    panel = attach_intl(attach_night(panel, 'TX'))

    if for_inference:
        return panel.reset_index(drop=True)
    return panel.dropna(subset=['range_5d']).reset_index(drop=True)


def evaluate(y_true: np.ndarray, y_pred: np.ndarray) -> dict:
    err = y_true - y_pred
    ss_res = float(np.sum(err ** 2))
    ss_tot = float(np.sum((y_true - y_true.mean()) ** 2))
    # 排序能力：選股用途只需要排序對，故 Spearman 比 Pearson 更貼近實際需求
    rank_corr = float(pd.Series(y_pred).corr(pd.Series(y_true), method='spearman'))
    return {
        'corr': float(np.corrcoef(y_pred, y_true)[0, 1]) if y_pred.std() > 0 else 0.0,
        'rank_corr': rank_corr,
        'r2': 1 - ss_res / ss_tot if ss_tot > 0 else 0.0,
        'mae': float(np.mean(np.abs(err))),
        'n': int(len(y_true)),
    }


def top_decile_lift(y_true: np.ndarray, y_pred: np.ndarray) -> dict:
    """
    選股角度的實用指標：預測振幅最大的前 10%，實際振幅是全體平均的幾倍？
    lift = 1.0 代表毫無選股能力。
    """
    k = max(int(len(y_pred) * 0.1), 10)
    idx = np.argsort(-y_pred)[:k]
    return {
        'top10_actual': float(y_true[idx].mean()),
        'overall_actual': float(y_true.mean()),
        'lift': float(y_true[idx].mean() / y_true.mean()) if y_true.mean() > 0 else 1.0,
        'n_top': int(k),
    }


def run_variant(d: pd.DataFrame, cols: list, label: str):
    """跑一次走查，回傳 (預測值, 實際值, 指標)。"""
    from sklearn.ensemble import HistGradientBoostingRegressor
    X = d[cols].values
    y = d['range_5d'].values
    y_log = np.log(np.maximum(y, 1e-6))
    preds, trues = [], []
    for tr, te in folds(d, HORIZON):
        reg = HistGradientBoostingRegressor(
            max_iter=400, max_depth=5, learning_rate=0.05, min_samples_leaf=80,
            l2_regularization=1.0, early_stopping=True,
            validation_fraction=0.15, random_state=42)
        reg.fit(X[tr], y_log[tr])
        preds.append(np.exp(reg.predict(X[te])))
        trues.append(y[te])
    p, t = np.concatenate(preds), np.concatenate(trues)
    m = evaluate(t, p)
    m.update(top_decile_lift(t, p))
    m['name'] = label
    print(f"  {label:16} 排序相關={m['rank_corr']:.4f} R²={m['r2']:+.4f} "
          f"MAE={m['mae']:.4%} lift={m['lift']:.3f}")
    return p, t, m


def main():
    print('載入資料…')
    d = load_data()

    from event_features import add_event_features, EVENT_FEATURES
    d = add_event_features(d)

    # Iteration 30 巢狀走查通過：外樣本排序相關 0.6537 vs 現行 0.6393（+0.0144），
    # 勝出組合「現行+夜盤+韓日」在 2/3 折被選中。
    # 穩定性剛好落在門檻上（67%），而單層消融偏好「現行+夜盤」——
    # 韓日的邊際貢獻不穩定，這點記在報告裡，不假裝它很確定。
    from night_features import NIGHT_FEATURES
    from intl_features import INTL_FEATURES
    exog_cols = [c for c in NIGHT_FEATURES + INTL_FEATURES if c in d.columns]
    base_cols = [c for c in PRICE_FEATURES + CS_FEATURES + MARKET_FEATURES
                 + EXTRA_VOL_FEATURES if c in d.columns] + exog_cols
    ev_cols = [c for c in EVENT_FEATURES if c in d.columns]
    cols = base_cols + ev_cols
    need = cols + ['range_5d', 'hist_range_median', 'ewma_vol', 'atr_pct']
    d = d[d[need].notna().all(axis=1)].reset_index(drop=True)

    # ── 事件特徵消融 ────────────────────────────────────────────────────
    # 門檻不能只要求「有提升」——任何雜訊都可能讓數字往上一點點。
    # 實測事件特徵只帶來 +0.0011 排序相關，且原始效應量測顯示
    # 營收／除權息窗內外的振幅差異 t 值僅 −0.55 / −0.66（見 event_effect.md）。
    # 故要求至少 +0.005 的實質margin，避免把雜訊當成改進而讓模型無謂變複雜。
    MIN_GAIN = 0.005
    print(f'\n=== 事件特徵消融（{len(ev_cols)} 個事件特徵）===')
    _, _, m_base = run_variant(d, base_cols, '不含事件')
    _, _, m_ev = run_variant(d, cols, '含事件')
    gain = m_ev['rank_corr'] - m_base['rank_corr']
    use_events = gain >= MIN_GAIN
    print(f"  → 排序相關 {m_base['rank_corr']:.4f} → {m_ev['rank_corr']:.4f}"
          f"（{gain:+.4f}，門檻 {MIN_GAIN:+.4f}）"
          f"　lift {m_base['lift']:.3f} → {m_ev['lift']:.3f}")
    print(f"  → {'採用事件特徵' if use_events else '**不採用**（提升未達門檻，屬雜訊）'}")
    if not use_events:
        cols = base_cols

    print('\n=== 與基準線比較 ===')
    print(f'可用 {len(d)} 筆 / {d["stock_id"].nunique()} 檔 '
          f'（{str(d["trade_date"].min())[:10]} ~ {str(d["trade_date"].max())[:10]}）')
    print(f'特徵 {len(cols)} 個　目標：未來 {HORIZON} 日 (最高−最低) ÷ 今日收盤')
    print(f'實際振幅分布：中位數 {d["range_5d"].median():.2%}　'
          f'平均 {d["range_5d"].mean():.2%}　'
          f'9 成分位 {d["range_5d"].quantile(0.9):.2%}\n')

    from sklearn.ensemble import HistGradientBoostingRegressor

    X = d[cols].values
    y = d['range_5d'].values
    y_log = np.log(np.maximum(y, 1e-6))     # 振幅右偏，取 log 後再迴歸

    preds, trues, idxs = [], [], []
    for tr, te in folds(d, HORIZON):
        reg = HistGradientBoostingRegressor(
            max_iter=400, max_depth=5, learning_rate=0.05, min_samples_leaf=80,
            l2_regularization=1.0, early_stopping=True,
            validation_fraction=0.15, random_state=42)
        reg.fit(X[tr], y_log[tr])
        preds.append(np.exp(reg.predict(X[te])))
        trues.append(y[te])
        idxs.append(np.where(te)[0])

    p = np.concatenate(preds)
    t = np.concatenate(trues)
    idx = np.concatenate(idxs)
    sub = d.iloc[idx]

    results = {
        '歷史中位數': sub['hist_range_median'].values,
        'ATR 外推': (sub['atr_pct'] * np.sqrt(HORIZON) * 2).values,
        'EWMA 外推': (sub['ewma_vol'] * np.sqrt(HORIZON) * 2).values,
        '模型': p,
    }

    print(f"{'方法':14} {'相關係數':>9} {'排序相關':>9} {'R²':>9} {'MAE':>9} "
          f"{'前10%實際振幅':>13} {'lift':>7}")
    print('-' * 76)
    rows = []
    for name, pred in results.items():
        m = evaluate(t, pred)
        lift = top_decile_lift(t, pred)
        m.update(lift)
        m['name'] = name
        rows.append(m)
        print(f"{name:14} {m['corr']:9.4f} {m['rank_corr']:9.4f} {m['r2']:+9.4f} "
              f"{m['mae']:9.4%} {m['top10_actual']:12.2%} {m['lift']:7.3f}")

    model_r = next(r for r in rows if r['name'] == '模型')
    best_base = max(r['rank_corr'] for r in rows if r['name'] != '模型')
    deploy = model_r['rank_corr'] > best_base
    print(f"\n模型排序相關={model_r['rank_corr']:.4f}　最佳基準={best_base:.4f}　"
          f"→ {'部署' if deploy else '**不部署**'}")

    write_report(rows, d, cols, deploy)
    if deploy:
        save_model(d, cols, X, y_log)


def save_model(d, cols, X, y_log):
    import joblib
    from sklearn.ensemble import HistGradientBoostingRegressor
    reg = HistGradientBoostingRegressor(
        max_iter=400, max_depth=5, learning_rate=0.05, min_samples_leaf=80,
        l2_regularization=1.0, early_stopping=True,
        validation_fraction=0.15, random_state=42)
    reg.fit(X, y_log)
    os.makedirs(MODEL_DIR, exist_ok=True)
    path = os.path.join(MODEL_DIR, 'range_model.joblib')
    joblib.dump({
        'model': reg, 'feature_cols': cols, 'log_target': True,
        'horizon': HORIZON, 'trained_at': datetime.now().isoformat(),
        'range_quantiles': {str(q): float(d['range_5d'].quantile(q))
                            for q in (0.1, 0.25, 0.5, 0.75, 0.9)},
    }, path)
    print(f'模型已存 {path}')
    _register('range', {'rows': len(X), 'features': len(cols), 'horizon': HORIZON})


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


def write_report(rows, d, cols, deploy):
    os.makedirs(RESULTS_DIR, exist_ok=True)
    path = os.path.join(RESULTS_DIR, 'range_model.md')
    lines = [
        '# 週振幅預測模型（Iteration 19）',
        '',
        f'**執行時間：** {datetime.now().strftime("%Y-%m-%d %H:%M")}',
        f'**目標：** 未來 {HORIZON} 個交易日 (最高價 − 最低價) ÷ 今日收盤',
        f'**樣本：** {len(d)} 筆 / {d["stock_id"].nunique()} 檔　**特徵：** {len(cols)} 個',
        f'**驗證：** {N_FOLDS} 折擴張視窗走查 + 標籤期封存',
        '',
        f'實際振幅分布：中位數 {d["range_5d"].median():.2%}、'
        f'平均 {d["range_5d"].mean():.2%}、9 成分位 {d["range_5d"].quantile(0.9):.2%}',
        '',
        '| 方法 | 相關係數 | 排序相關 | R² | MAE | 前 10% 實際振幅 | lift |',
        '|------|---------|---------|-----|-----|---------------|------|',
    ]
    for r in rows:
        mark = '**' if r['name'] == '模型' else ''
        lines.append(f"| {mark}{r['name']}{mark} | {r['corr']:.4f} | "
                     f"{r['rank_corr']:.4f} | {r['r2']:+.4f} | {r['mae']:.4%} | "
                     f"{r['top10_actual']:.2%} | {r['lift']:.3f} |")
    lines += [
        '',
        '## 指標說明',
        '',
        '- **排序相關**（Spearman）：選股只需要排序對，這比 Pearson 更貼近實際用途。',
        '- **lift**：預測振幅最大的前 10%，其實際振幅是全體平均的幾倍。',
        '  1.0 代表毫無選股能力——這是判斷功能有沒有用的關鍵數字。',
        '- **高低價已還原公司行動**：以 `adj_close ÷ close` 求係數再套用到 high/low，',
        '  否則除權息與減資日的假缺口會被當成真實振幅（Iteration 18 的延伸）。',
        '',
        f'**部署判定：{"通過" if deploy else "未通過"}**',
    ]
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    print(f'報告已寫入 {path}')


if __name__ == '__main__':
    main()
