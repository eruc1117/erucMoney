"""
美股隔夜 → 台股大盤（Iteration 14）
────────────────────────────────────
`test_us_value.py` 顯示美股特徵對「個股 alpha」毫無幫助。事後想通原因：

    美股隔夜走勢影響的是**全體台股**，而 alpha ＝ 個股報酬 − 當日全體平均，
    市場共同成分在計算 alpha 時就被減掉了。
    美股資訊天生無法解釋橫斷面差異，只能解釋大盤水準。

本腳本改測正確的目標：**台股大盤（24 檔等權平均）次日的方向與波動**。
這是美股資訊該有作用的地方。

樣本單位改為「一個交易日一列」，數量遠少於個股面板（約 6,000 列），
故同時報告二項檢定標準誤，避免小樣本上的過度解讀。

用法：python test_us_market.py [--horizons 1 3 5]
產出：results/us_market.md
"""

import argparse
import os
import sys
from datetime import datetime

import numpy as np
import pandas as pd

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(BASE_DIR, '..', 'Crawler'))

from features import build_panel, LOAD_SQL   # noqa: E402
from us_features import load_and_attach, US_FEATURES   # noqa: E402

RESULTS_DIR = os.path.join(BASE_DIR, 'results')
N_FOLDS = 5


def build_market_series() -> pd.DataFrame:
    """把個股面板壓成「一個交易日一列」的大盤序列，並接上美股特徵。"""
    from db.connection import get_conn
    with get_conn() as conn:
        raw = pd.read_sql(LOAD_SQL, conn)

    panel = build_panel(raw)
    panel['ret_1d_calc'] = panel.groupby('stock_id')['close'].transform(
        lambda s: s.pct_change())

    mkt = (panel.groupby('trade_date')
           .agg(mkt_ret=('ret_1d_calc', 'mean'),
                mkt_breadth=('ret_1d_calc', lambda s: (s > 0).mean()),
                n_stocks=('stock_id', 'nunique'),
                mkt_vol_ratio=('vol_ratio', 'mean'),
                mkt_rsi=('rsi_14', 'mean'))
           .reset_index())
    mkt = mkt[mkt['n_stocks'] >= 5].reset_index(drop=True)

    # 大盤自身的歷史特徵（只用過去資料）
    for n in (1, 3, 5, 10, 20):
        mkt[f'mkt_ret_{n}d'] = mkt['mkt_ret'].rolling(n).sum().shift(0)
    for n in (5, 20):
        mkt[f'mkt_vol_{n}d'] = mkt['mkt_ret'].rolling(n).std()
    mkt['mkt_breadth_5d'] = mkt['mkt_breadth'].rolling(5).mean()

    return load_and_attach(mkt)


TW_SELF_FEATURES = ['mkt_ret_1d', 'mkt_ret_3d', 'mkt_ret_5d', 'mkt_ret_10d',
                    'mkt_ret_20d', 'mkt_vol_5d', 'mkt_vol_20d',
                    'mkt_breadth', 'mkt_breadth_5d', 'mkt_vol_ratio', 'mkt_rsi']


def folds_1d(n_rows: int, horizon: int):
    """時序走查（樣本已是逐日，直接依列切分）。"""
    start = int(n_rows * 0.5)
    bounds = np.linspace(start, n_rows, N_FOLDS + 1).astype(int)
    for i in range(N_FOLDS):
        tr = np.zeros(n_rows, dtype=bool)
        tr[:max(bounds[i] - horizon, 0)] = True          # 標籤期封存
        te = np.zeros(n_rows, dtype=bool)
        te[bounds[i]:bounds[i + 1]] = True
        if tr.sum() > 300 and te.sum() > 30:
            yield tr, te


def run(data, cols, horizon):
    from sklearn.ensemble import HistGradientBoostingClassifier
    X = data[cols].values
    y = (data['fwd_mkt_ret'] > 0).astype(int).values
    preds, trues = [], []
    for tr, te in folds_1d(len(data), horizon):
        clf = HistGradientBoostingClassifier(
            max_iter=200, max_depth=3, learning_rate=0.05, min_samples_leaf=40,
            l2_regularization=1.0, early_stopping=True,
            validation_fraction=0.2, random_state=42)
        clf.fit(X[tr], y[tr])
        preds.append(clf.predict(X[te]))
        trues.append(y[te])
    if not preds:
        return None
    p, t = np.concatenate(preds), np.concatenate(trues)
    acc = float((p == t).mean())
    base = float(max(t.mean(), 1 - t.mean()))
    n_eff = max(len(t) // max(horizon, 1), 1)
    se = float(np.sqrt(acc * (1 - acc) / n_eff))
    return {'acc': acc, 'base': base, 'edge': acc - base,
            'n': len(t), 'n_eff': n_eff, 'se': se, 'lower95': acc - 1.96 * se}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--horizons', type=int, nargs='+', default=[1, 3, 5])
    args = ap.parse_args()

    print('建立大盤序列…')
    mkt = build_market_series()
    print(f'大盤序列 {len(mkt)} 個交易日'
          f'（{str(mkt["trade_date"].min())[:10]} ~ {str(mkt["trade_date"].max())[:10]}）\n')

    us_cols = [c for c in US_FEATURES if c in mkt.columns]
    tw_cols = [c for c in TW_SELF_FEATURES if c in mkt.columns]
    variants = {
        '僅台股自身': tw_cols,
        '僅美股隔夜': us_cols,
        '台股＋美股': tw_cols + us_cols,
    }

    rows = []
    for h in args.horizons:
        m = mkt.copy()
        m['fwd_mkt_ret'] = m['mkt_ret'].shift(-1).rolling(h).sum().shift(-(h - 1))
        need = sorted(set(tw_cols + us_cols)) + ['fwd_mkt_ret']
        d = m[m[need].notna().all(axis=1)].reset_index(drop=True)
        print(f'=== 天期 {h} 日（{len(d)} 個交易日）===')
        for name, cols in variants.items():
            r = run(d, cols, h)
            if r is None:
                continue
            r.update({'horizon': h, 'variant': name})
            rows.append(r)
            print(f"  {name:10} 準確率 {r['acc']:.2%}　基準 {r['base']:.2%}"
                  f"　超越 {r['edge']:+.2%}　95%下界 {r['lower95']:.2%}"
                  f"（n={r['n']}，有效 {r['n_eff']}）")
        print()

    write_report(rows, len(mkt), len(us_cols), len(tw_cols))


def write_report(rows, n_days, n_us, n_tw):
    os.makedirs(RESULTS_DIR, exist_ok=True)
    path = os.path.join(RESULTS_DIR, 'us_market.md')
    lines = [
        '# 美股隔夜 → 台股大盤方向（Iteration 14）',
        '',
        f'**執行時間：** {datetime.now().strftime("%Y-%m-%d %H:%M")}',
        f'**樣本：** {n_days} 個交易日　'
        f'**特徵：** 台股自身 {n_tw} 個、美股隔夜 {n_us} 個',
        '',
        '> 為何改測大盤：美股隔夜影響全體台股，而個股 alpha ＝ 個股報酬 − 當日全體平均，',
        '> 市場共同成分已被減掉，美股資訊天生無法解釋橫斷面差異。',
        '',
        '| 天期 | 特徵組 | 準確率 | 基準 | 超越基準 | 95% 下界 | 有效樣本 |',
        '|------|-------|-------|------|---------|---------|---------|',
    ]
    for r in rows:
        lines.append(f"| {r['horizon']} | {r['variant']} | **{r['acc']:.2%}** | "
                     f"{r['base']:.2%} | {r['edge']:+.2%} | {r['lower95']:.2%} | "
                     f"{r['n_eff']} |")
    lines += ['', '## 注意', '',
              '大盤序列每個交易日只有一列，樣本量遠小於個股面板，',
              '且長天期有視窗重疊問題（有效樣本 ≈ n/天期）。',
              '準確率須與 95% 下界一起看，單看點估計容易過度解讀。']
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    print(f'報告已寫入 {path}')


if __name__ == '__main__':
    main()
