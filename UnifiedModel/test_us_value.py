"""
美股特徵是否真的有用？（Iteration 14）
──────────────────────────────────────
消融實驗：在完全相同的走查驗證下，比較「有無美股特徵」對兩個任務的影響。

  任務 A 方向預測    —— 先前反覆證實無 edge，看美股資訊能否突破
  任務 B 波動率預測  —— 已知可預測（相關 0.606），看美股能否再提升

只有實測有提升才保留，沿用 Iteration 9 建立的原則。

用法：python test_us_value.py [--horizon 20]
產出：results/us_ablation.md
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

from features import build_panel, LOAD_SQL, PRICE_FEATURES, CS_FEATURES, \
    MARKET_FEATURES   # noqa: E402
from train_volatility import add_vol_features, ewma_vol, folds, \
    EXTRA_VOL_FEATURES, score   # noqa: E402
from us_features import load_and_attach, US_FEATURES   # noqa: E402

RESULTS_DIR = os.path.join(BASE_DIR, 'results')


def load_all(horizon: int, vol_horizon: int = 20) -> pd.DataFrame:
    """
    方向天期與波動率天期必須分開。
    波動率是「一段期間內報酬的標準差」，天期 1 時 rolling(1).std() 恆為 NaN，
    會把整份資料清空——首版就是這樣掛掉的。
    """
    from db.connection import get_conn
    with get_conn() as conn:
        raw = pd.read_sql(LOAD_SQL, conn)

    panel = add_vol_features(build_panel(raw))
    panel = load_and_attach(panel)

    g = panel.groupby('stock_id')
    daily = g['close'].transform(lambda s: s.pct_change())
    panel['fwd_vol'] = daily.groupby(panel['stock_id']).transform(
        lambda s: s.shift(-vol_horizon).rolling(vol_horizon).std())
    panel['ewma_vol'] = daily.groupby(panel['stock_id']).transform(ewma_vol)
    panel['fwd_ret'] = g['close'].transform(lambda s: s.shift(-horizon) / s - 1)
    panel = panel.sort_values(['trade_date', 'stock_id'])
    panel['alpha'] = panel['fwd_ret'] - panel.groupby('trade_date')['fwd_ret'].transform('mean')
    return panel.dropna(subset=['fwd_vol', 'fwd_ret', 'ewma_vol']).reset_index(drop=True)


def run_direction(data, cols, horizon):
    """回傳 (全樣本準確率, 無條件基準, 前 5% 信心的準確率, n)。"""
    from sklearn.ensemble import HistGradientBoostingClassifier
    X = data[cols].values
    y = (data['alpha'] > 0).astype(int).values
    probas, trues = [], []
    for tr, te in folds(data, horizon):
        clf = HistGradientBoostingClassifier(
            max_iter=300, max_depth=4, learning_rate=0.05, min_samples_leaf=100,
            l2_regularization=1.0, early_stopping=True,
            validation_fraction=0.15, random_state=42)
        clf.fit(X[tr], y[tr])
        probas.append(clf.predict_proba(X[te])[:, 1])
        trues.append(data['alpha'].values[te])
    p, a = np.concatenate(probas), np.concatenate(trues)

    pred_up = p > 0.5
    acc = float((pred_up == (a > 0)).mean())
    base = float(max((a > 0).mean(), 1 - (a > 0).mean()))

    conf = np.abs(p - 0.5)
    k = max(int(len(conf) * 0.05), 10)
    idx = np.argsort(-conf)[:k]
    acc5 = float((pred_up[idx] == (a[idx] > 0)).mean())
    return acc, base, acc5, len(a)


def run_volatility(data, cols, horizon):
    from sklearn.ensemble import HistGradientBoostingRegressor
    X = data[cols].values
    y_raw = data['fwd_vol'].values
    y = np.log(np.maximum(y_raw, 1e-8))
    preds, trues, ewmas = [], [], []
    for tr, te in folds(data, horizon):
        reg = HistGradientBoostingRegressor(
            max_iter=400, max_depth=5, learning_rate=0.05, min_samples_leaf=80,
            l2_regularization=1.0, early_stopping=True,
            validation_fraction=0.15, random_state=42)
        reg.fit(X[tr], y[tr])
        preds.append(np.exp(reg.predict(X[te])))
        trues.append(y_raw[te])
        ewmas.append(data['ewma_vol'].values[te])
    p, t, e = np.concatenate(preds), np.concatenate(trues), np.concatenate(ewmas)
    return score(t, 0.5 * p + 0.5 * e)      # 與部署設定一致（blend=avg）


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--horizon', type=int, default=20, help='方向預測天期')
    ap.add_argument('--vol-horizon', type=int, default=20, help='波動率預測天期')
    args = ap.parse_args()
    h = args.horizon

    print(f'載入資料（方向天期 {h} 日，波動率天期 {args.vol_horizon} 日）…')
    data = load_all(h, args.vol_horizon)

    base_cols = [c for c in PRICE_FEATURES + CS_FEATURES + MARKET_FEATURES
                 + EXTRA_VOL_FEATURES if c in data.columns]
    us_cols = [c for c in US_FEATURES if c in data.columns]
    need = base_cols + us_cols
    d = data[data[need].notna().all(axis=1)].reset_index(drop=True)
    print(f'可用 {len(d)} 筆 / {d["stock_id"].nunique()} 檔 '
          f'（{str(d["trade_date"].min())[:10]} ~ {str(d["trade_date"].max())[:10]}）')
    print(f'基礎特徵 {len(base_cols)} 個，美股特徵 {len(us_cols)} 個\n')

    variants = {'不含美股': base_cols, '含美股': base_cols + us_cols}
    rows = []

    print('── 任務 A：方向預測（alpha 標籤）──')
    for name, cols in variants.items():
        acc, base, acc5, n = run_direction(d, cols, h)
        rows.append({'task': '方向', 'variant': name, 'acc': acc, 'base': base,
                     'acc5': acc5, 'n': n})
        print(f'  {name:8} 全樣本 {acc:.2%}（基準 {base:.2%}，超越 {acc - base:+.2%}）'
              f'　前 5% 信心 {acc5:.2%}')

    print('\n── 任務 B：波動率預測 ──')
    for name, cols in variants.items():
        s = run_volatility(d, cols, h)
        rows.append({'task': '波動率', 'variant': name, **s})
        print(f"  {name:8} 相關={s['corr']:.4f}  R²(log)={s['r2_log']:+.4f}  "
              f"QLIKE={s['qlike']:.4f}")

    write_report(rows, h, len(d), len(base_cols), len(us_cols))


def write_report(rows, h, n, n_base, n_us):
    os.makedirs(RESULTS_DIR, exist_ok=True)
    path = os.path.join(RESULTS_DIR, 'us_ablation.md')
    dirs = [r for r in rows if r['task'] == '方向']
    vols = [r for r in rows if r['task'] == '波動率']
    lines = [
        '# 美股特徵消融實驗（Iteration 14）',
        '',
        f'**執行時間：** {datetime.now().strftime("%Y-%m-%d %H:%M")}',
        f'**天期：** {h} 日　**樣本：** {n} 筆　'
        f'**特徵：** 基礎 {n_base} 個 + 美股 {n_us} 個',
        '',
        '> 時序對齊：美股日期**嚴格小於**台股日期，只用台股開盤前已公布的美股收盤。',
        '',
        '## 任務 A：方向預測',
        '',
        '| 設定 | 全樣本準確率 | 無條件基準 | 超越基準 | 前 5% 信心 |',
        '|------|-------------|-----------|---------|-----------|',
    ]
    for r in dirs:
        lines.append(f"| {r['variant']} | {r['acc']:.2%} | {r['base']:.2%} | "
                     f"**{r['acc'] - r['base']:+.2%}** | {r['acc5']:.2%} |")
    lines += ['', '## 任務 B：波動率預測（與 EWMA 平均後）', '',
              '| 設定 | 相關係數 | R²(log) | QLIKE |',
              '|------|---------|---------|-------|']
    for r in vols:
        lines.append(f"| {r['variant']} | **{r['corr']:.4f}** | {r['r2_log']:+.4f} | "
                     f"{r['qlike']:.4f} |")
    if len(vols) == 2:
        d_corr = vols[1]['corr'] - vols[0]['corr']
        lines += ['', f"美股特徵對波動率預測的相關係數影響：**{d_corr:+.4f}**"]
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    print(f'\n報告已寫入 {path}')


if __name__ == '__main__':
    main()
