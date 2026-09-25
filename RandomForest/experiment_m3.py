"""
M3 籌碼模型改進實驗台（Iteration 9）

目的：現行 M3（RandomForest/train_m3.py）測試集方向準確率僅 50.83%，等同擲硬幣。
本腳本以「走查驗證（walk-forward）」比較數個假設，找出真正有效的設定後才部署。

診斷假設：
  H1 原始報酬標籤被大盤 beta 主導 → 改用「相對同儕的超額報酬（alpha）」較可學
  H2 特徵全為個股時序、缺橫斷面情境 → 加入當日 22 檔之間的百分位排名特徵
  H3 單一 80/20 切分只看一個市場情境 → 改用多折走查取平均，降低估計變異

實驗變體：
  V0  原始報酬 ±2% 標籤 + 基礎特徵        （= 現行production 設定，基準線）
  V1  alpha 標籤（訓練集分位數門檻）+ 基礎特徵
  V2  alpha 標籤 + 基礎特徵 + 橫斷面排名特徵
  V3  V2 + 調參

共同評估口徑（確保可比）：
  **方向準確率一律對「原始未來 3 日報酬」計算**，不因標籤定義改變而失真。
  同時report alpha 方向準確率與出手率（coverage）供參考。

用法：
    python experiment_m3.py                # 跑全部變體
    python experiment_m3.py --folds 5      # 指定走查折數
產出：
    results/m3_experiment.md               # 完整比較報告
"""

import argparse
import os
import sys
from datetime import datetime

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier

CRAWLER_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'Crawler')
sys.path.insert(0, CRAWLER_DIR)

from db.connection import get_conn                      # noqa: E402
from m3_features import build_features, FEATURE_COLS    # noqa: E402

BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
REPORT_PATH = os.path.join(BASE_DIR, 'results', 'm3_experiment.md')

LABEL_HORIZON = 3      # 未來 N 個交易日報酬（預設；--horizons 可覆寫）
BUY_TH, SELL_TH = 0.02, -0.02

# 橫斷面排名特徵（當日 22 檔之間的百分位，0~1）
CS_FEATURE_COLS = [
    'cs_foreign_5d', 'cs_total_5d', 'cs_trust_5d',
    'cs_ret_5d', 'cs_ret_20d', 'cs_vol_ratio',
    'mkt_breadth',      # 當日買超家數比例（大盤籌碼氛圍）
    'mkt_ret_5d',       # 當日 22 檔 ret_5d 平均（大盤動能）
]


# --------------------------------------------------------------------------- #
# 資料
# --------------------------------------------------------------------------- #
def load_dataset() -> pd.DataFrame:
    sql = """
        SELECT c.stock_id, c.trade_date,
               c.foreign_investor_buy AS foreign_net,
               c.investment_trust_buy AS trust_net,
               c.dealer_buy           AS dealer_net,
               c.total_net_buy        AS total_net,
               p.volume, p.close_price AS close
        FROM stock_chip_analysis c
        JOIN stock_daily_prices p USING (stock_id, trade_date)
        ORDER BY c.stock_id, c.trade_date
    """
    with get_conn() as conn:
        return pd.read_sql(sql, conn)


def build_panel(raw: pd.DataFrame, horizon: int = LABEL_HORIZON) -> pd.DataFrame:
    """個股特徵 → 併成面板 → 加未來報酬、alpha、橫斷面特徵。"""
    frames = []
    for sid, g in raw.groupby('stock_id'):
        feat = build_features(g)
        feat['fwd_ret'] = feat['close'].shift(-horizon) / feat['close'] - 1
        feat['stock_id'] = sid
        frames.append(feat)
    data = pd.concat(frames, ignore_index=True).dropna(subset=['fwd_ret'])
    data = data.sort_values(['trade_date', 'stock_id']).reset_index(drop=True)

    # alpha = 個股未來報酬 - 當日全體平均未來報酬（剝離大盤 beta）
    data['mkt_fwd_ret'] = data.groupby('trade_date')['fwd_ret'].transform('mean')
    data['alpha'] = data['fwd_ret'] - data['mkt_fwd_ret']

    # 橫斷面排名特徵（僅用當日同儕資訊，無未來洩漏）
    for src, dst in [('foreign_5d', 'cs_foreign_5d'), ('total_5d', 'cs_total_5d'),
                     ('trust_5d', 'cs_trust_5d'), ('ret_5d', 'cs_ret_5d'),
                     ('ret_20d', 'cs_ret_20d'), ('vol_ratio', 'cs_vol_ratio')]:
        data[dst] = data.groupby('trade_date')[src].rank(pct=True)
    data['mkt_breadth'] = data.groupby('trade_date')['total_1d'].transform(lambda s: (s > 0).mean())
    data['mkt_ret_5d']  = data.groupby('trade_date')['ret_5d'].transform('mean')

    return data


# --------------------------------------------------------------------------- #
# 標籤
# --------------------------------------------------------------------------- #
def label_raw(data: pd.DataFrame, train_mask: pd.Series) -> np.ndarray:
    """原始報酬固定門檻 ±2%（現行 production 定義）。"""
    return np.select([data['fwd_ret'] > BUY_TH, data['fwd_ret'] < SELL_TH], [2, 0], default=1)


def label_alpha(data: pd.DataFrame, train_mask: pd.Series) -> np.ndarray:
    """alpha 分位數門檻；分位點**只由訓練集計算**，避免未來資訊洩漏。"""
    tr = data.loc[train_mask, 'alpha']
    lo, hi = tr.quantile(1 / 3), tr.quantile(2 / 3)
    return np.select([data['alpha'] > hi, data['alpha'] < lo], [2, 0], default=1)


# --------------------------------------------------------------------------- #
# 評估
# --------------------------------------------------------------------------- #
def fold_metrics(pred: np.ndarray, fwd_ret: np.ndarray, alpha: np.ndarray) -> dict:
    """一律以原始報酬方向為主指標，alpha 方向為輔。"""
    act = pred != 1                       # 出手（非 Hold）
    n = int(act.sum())
    if n == 0:
        return {'n_calls': 0, 'coverage': 0.0, 'dir_acc': np.nan,
                'alpha_dir_acc': np.nan, 'avg_ret': np.nan}

    long_ = pred[act] == 2
    r  = fwd_ret[act]
    a  = alpha[act]
    dir_ok       = np.where(long_, r > 0, r < 0)
    alpha_dir_ok = np.where(long_, a > 0, a < 0)
    # 依訊號方向取得的平均報酬（做多吃 +r，做空吃 -r）
    signed_ret = np.where(long_, r, -r)

    # 多空分開看：多頭市場中「方向準確率高」與「賺錢」可能背離
    lm, sm = long_, ~long_
    return {
        'n_calls': n,
        'coverage': float(act.mean()),
        'dir_acc': float(dir_ok.mean()),
        'alpha_dir_acc': float(alpha_dir_ok.mean()),
        'avg_ret': float(signed_ret.mean()),
        'n_long': int(lm.sum()),
        'long_dir_acc': float(dir_ok[lm].mean()) if lm.sum() else np.nan,
        'long_avg_ret': float(r[lm].mean()) if lm.sum() else np.nan,
        'n_short': int(sm.sum()),
        'short_dir_acc': float(dir_ok[sm].mean()) if sm.sum() else np.nan,
        'short_avg_ret': float(-r[sm].mean()) if sm.sum() else np.nan,
    }


def walk_forward(data: pd.DataFrame, feature_cols: list, label_fn, rf_params: dict,
                 n_folds: int, horizon: int = LABEL_HORIZON, gate: float = 0.0,
                 verbose: bool = True, collect_proba: bool = False):
    """
    擴張視窗走查：每折用切分點之前全部資料訓練，測該折區間。

    gate：最高類別機率低於此值即改判 Hold（模擬 production 的信心門檻）。
    collect_proba=True 時額外回傳各折的 (proba, fwd_ret, alpha) 以供門檻掃描。
    """
    dates = np.sort(data['trade_date'].unique())
    # 前 50% 一律作為初始訓練，其餘等分成 n_folds 折
    start = int(len(dates) * 0.5)
    bounds = np.linspace(start, len(dates), n_folds + 1).astype(int)

    results, raw_out = [], []
    for i in range(n_folds):
        te_lo, te_hi = dates[bounds[i]], dates[bounds[i + 1] - 1]
        train_mask = data['trade_date'] < te_lo
        test_mask  = (data['trade_date'] >= te_lo) & (data['trade_date'] <= te_hi)

        # 封存：訓練集尾端 horizon 個交易日的標籤會跨進測試期
        embargo_from = dates[bounds[i] - horizon] if bounds[i] >= horizon else dates[0]
        train_mask &= data['trade_date'] < embargo_from

        y_all = label_fn(data, train_mask)
        X = data[feature_cols].values
        model = RandomForestClassifier(random_state=42, n_jobs=-1, **rf_params)
        model.fit(X[train_mask.values], y_all[train_mask.values])
        proba = model.predict_proba(X[test_mask.values])
        pred = apply_gate(proba, gate)

        fwd = data.loc[test_mask, 'fwd_ret'].values
        alp = data.loc[test_mask, 'alpha'].values
        if collect_proba:
            raw_out.append((proba, fwd, alp))

        m = fold_metrics(pred, fwd, alp)
        m.update({'fold': i + 1, 'test_from': str(te_lo)[:10], 'test_to': str(te_hi)[:10],
                  'n_train': int(train_mask.sum()), 'n_test': int(test_mask.sum())})
        results.append(m)
        if verbose:
            print(f"    fold {i+1} [{m['test_from']}~{m['test_to']}] "
                  f"方向 {m['dir_acc']:.2%} / alpha方向 {m['alpha_dir_acc']:.2%} "
                  f"/ 出手 {m['coverage']:.0%}")
    return (results, raw_out) if collect_proba else results


def apply_gate(proba: np.ndarray, gate: float) -> np.ndarray:
    """最高類別機率 < gate 一律改判 Hold（1）。"""
    pred = proba.argmax(axis=1)
    if gate > 0:
        pred = np.where(proba.max(axis=1) < gate, 1, pred)
    return pred


def aggregate(folds: list) -> dict:
    """以出手次數加權平均（避免小折被過度放大）。"""
    df = pd.DataFrame(folds).dropna(subset=['dir_acc'])
    keys = ['dir_acc', 'alpha_dir_acc', 'coverage', 'avg_ret', 'dir_acc_std', 'n_calls',
            'long_dir_acc', 'long_avg_ret', 'n_long',
            'short_dir_acc', 'short_avg_ret', 'n_short']
    if df.empty:
        return {k: (0 if k.startswith('n_') else np.nan) for k in keys}
    w = df['n_calls']

    def wavg(col, weights):
        sub = df[[col]].join(weights.rename('w')).dropna()
        return float(np.average(sub[col], weights=sub['w'])) if len(sub) and sub['w'].sum() else np.nan

    return {
        'dir_acc': wavg('dir_acc', w),
        'alpha_dir_acc': wavg('alpha_dir_acc', w),
        'coverage': wavg('coverage', df['n_test']),
        'avg_ret': wavg('avg_ret', w),
        'dir_acc_std': float(df['dir_acc'].std()),
        'n_calls': int(w.sum()),
        'long_dir_acc':  wavg('long_dir_acc', df['n_long']),
        'long_avg_ret':  wavg('long_avg_ret', df['n_long']),
        'n_long': int(df['n_long'].sum()),
        'short_dir_acc': wavg('short_dir_acc', df['n_short']),
        'short_avg_ret': wavg('short_avg_ret', df['n_short']),
        'n_short': int(df['n_short'].sum()),
    }


# --------------------------------------------------------------------------- #
# 變體定義
# --------------------------------------------------------------------------- #
BASE_RF = dict(n_estimators=300, max_depth=8, min_samples_leaf=50,
               class_weight='balanced_subsample')
TUNED_RF = dict(n_estimators=500, max_depth=6, min_samples_leaf=120,
                max_features=0.5, class_weight='balanced_subsample')

VARIANTS = [
    ('V0 基準（原始報酬±2% + 基礎特徵）', FEATURE_COLS, label_raw, BASE_RF),
    ('V1 alpha 標籤 + 基礎特徵', FEATURE_COLS, label_alpha, BASE_RF),
    ('V2 alpha 標籤 + 橫斷面特徵', FEATURE_COLS + CS_FEATURE_COLS, label_alpha, BASE_RF),
    ('V3 V2 + 調參（更淺更正則）', FEATURE_COLS + CS_FEATURE_COLS, label_alpha, TUNED_RF),
]


V3_COLS = FEATURE_COLS + CS_FEATURE_COLS


def run_variants(raw: pd.DataFrame, n_folds: int):
    data = build_panel(raw)
    print(f'面板 {len(data)} 筆 / {data["stock_id"].nunique()} 檔 / '
          f'{data["trade_date"].nunique()} 個交易日\n')
    all_results = []
    for name, cols, label_fn, params in VARIANTS:
        print(f'▶ {name}')
        folds = walk_forward(data, cols, label_fn, params, n_folds)
        agg = aggregate(folds)
        agg.update({'name': name, 'n_features': len(cols)})
        all_results.append((agg, folds))
        print(f"  → 加權方向準確率 {agg['dir_acc']:.2%} "
              f"(折間標準差 {agg['dir_acc_std']:.2%}) / 出手率 {agg['coverage']:.0%}\n")
    write_report(all_results, data, n_folds)


def run_horizon_sweep(raw: pd.DataFrame, n_folds: int, horizons: list):
    """天期掃描：籌碼效應可能需要數日以上才發酵，3 日或許過短。"""
    rows = []
    for h in horizons:
        print(f'▶ 天期 {h} 日')
        data = build_panel(raw, horizon=h)
        folds = walk_forward(data, V3_COLS, label_alpha, TUNED_RF, n_folds, horizon=h)
        agg = aggregate(folds)
        agg['horizon'] = h
        rows.append(agg)
        print(f"  → 方向準確率 {agg['dir_acc']:.2%} "
              f"(折間標準差 {agg['dir_acc_std']:.2%}) / 單次平均報酬 {agg['avg_ret']:+.3%}\n")
    return rows


def run_gate_sweep(raw: pd.DataFrame, n_folds: int, horizon: int, gates: list):
    """信心門檻掃描：少出手但更準，對投票系統而言通常更有價值。"""
    data = build_panel(raw, horizon=horizon)
    print(f'▶ 天期 {horizon} 日，計算各折機率…')
    _, raw_out = walk_forward(data, V3_COLS, label_alpha, TUNED_RF, n_folds,
                              horizon=horizon, verbose=False, collect_proba=True)
    rows = []
    for g in gates:
        folds = []
        for i, (proba, fwd, alp) in enumerate(raw_out):
            m = fold_metrics(apply_gate(proba, g), fwd, alp)
            m.update({'fold': i + 1, 'n_test': len(fwd)})
            folds.append(m)
        agg = aggregate(folds)
        agg['gate'] = g
        rows.append(agg)
        print(f"  門檻 {g:.2f} → 方向 {agg['dir_acc']:.2%} / 出手率 {agg['coverage']:.0%} "
              f"({agg['n_calls']} 次) | 多 {agg['n_long']} 次 {agg['long_dir_acc']:.2%} "
              f"報酬 {agg['long_avg_ret']:+.3%} | 空 {agg['n_short']} 次 "
              f"{agg['short_dir_acc']:.2%} 報酬 {agg['short_avg_ret']:+.3%}")
    return rows


def write_sweep_report(hz_rows: list, gate_rows: list, gate_horizon: int, n_folds: int):
    path = os.path.join(BASE_DIR, 'results', 'm3_sweep.md')
    lines = [
        '# M3 天期與信心門檻掃描（Iteration 9）',
        '',
        f'**執行時間：** {datetime.now().strftime("%Y-%m-%d %H:%M")}',
        f'**設定：** V3（alpha 標籤 + 橫斷面特徵 + 調參），{n_folds} 折擴張視窗走查',
        '',
        '## 預測天期掃描',
        '',
        '> 假設：籌碼流向需要時間發酵，3 個交易日可能過短、雜訊佔比過高。',
        '',
        '| 未來天期 | 方向準確率 | 折間標準差 | alpha 方向 | 出手率 | 單次平均報酬 |',
        '|---------|-----------|-----------|-----------|--------|-------------|',
    ]
    for r in hz_rows:
        lines.append(f"| {r['horizon']} 日 | **{r['dir_acc']:.2%}** | {r['dir_acc_std']:.2%} | "
                     f"{r['alpha_dir_acc']:.2%} | {r['coverage']:.0%} | {r['avg_ret']:+.3%} |")

    lines += [
        '',
        f'## 信心門檻掃描（天期 {gate_horizon} 日）',
        '',
        '> 最高類別機率低於門檻即改判 Hold。投票系統寧可少出手、出手要準。',
        '',
        '| 門檻 | 方向準確率 | 出手率 | 出手次數 | 單次平均報酬 |',
        '|------|-----------|--------|---------|-------------|',
    ]
    for r in gate_rows:
        lines.append(f"| {r['gate']:.2f} | **{r['dir_acc']:.2%}** | {r['coverage']:.0%} | "
                     f"{r['n_calls']} | {r['avg_ret']:+.3%} |")

    lines += [
        '',
        '### 多空拆解',
        '',
        '> 台股 2023-2026 為多頭格局，「方向準確率高」與「賺錢」可能背離：',
        '> 做空即使方向常對，遇到反彈時虧損幅度大，平均報酬仍可能為負。',
        '',
        '| 門檻 | 買進次數 | 買進方向準確率 | 買進平均報酬 | 賣出次數 | 賣出方向準確率 | 賣出平均報酬 |',
        '|------|---------|---------------|-------------|---------|---------------|-------------|',
    ]
    for r in gate_rows:
        if not r['n_calls']:
            continue
        lines.append(
            f"| {r['gate']:.2f} | {r['n_long']} | {r['long_dir_acc']:.2%} | "
            f"{r['long_avg_ret']:+.3%} | {r['n_short']} | {r['short_dir_acc']:.2%} | "
            f"{r['short_avg_ret']:+.3%} |"
        )

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    print(f'\n報告已寫入 {path}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--folds', type=int, default=5)
    ap.add_argument('--mode', choices=['variants', 'sweep'], default='variants')
    ap.add_argument('--horizons', type=int, nargs='+', default=[3, 5, 10, 20])
    ap.add_argument('--gate-horizon', type=int, default=10)
    args = ap.parse_args()

    print('載入資料…')
    raw = load_dataset()

    if args.mode == 'variants':
        run_variants(raw, args.folds)
    else:
        hz = run_horizon_sweep(raw, args.folds, args.horizons)
        best = max(hz, key=lambda r: r['dir_acc'])
        gh = args.gate_horizon if args.gate_horizon in args.horizons else best['horizon']
        print(f'\n最佳天期 {best["horizon"]} 日（{best["dir_acc"]:.2%}）；'
              f'門檻掃描使用天期 {gh} 日\n')
        gates = run_gate_sweep(raw, args.folds, gh, [0.0, 0.40, 0.45, 0.50, 0.55, 0.60])
        write_sweep_report(hz, gates, gh, args.folds)


def write_report(all_results: list, data: pd.DataFrame, n_folds: int):
    base = all_results[0][0]
    lines = [
        '# M3 籌碼模型改進實驗報告（Iteration 9）',
        '',
        f'**執行時間：** {datetime.now().strftime("%Y-%m-%d %H:%M")}',
        f'**資料：** {len(data)} 筆面板 / {data["stock_id"].nunique()} 檔 / '
        f'{data["trade_date"].nunique()} 個交易日 '
        f'（{str(data["trade_date"].min())[:10]} ~ {str(data["trade_date"].max())[:10]}）',
        f'**驗證：** {n_folds} 折擴張視窗走查，訓練集尾端封存 {EMBARGO_DAYS} 個交易日',
        '',
        '> 方向準確率一律以**原始未來 3 日報酬**計算，不因各變體標籤定義不同而失真。',
        '',
        '## 變體比較（依出手次數加權平均）',
        '',
        '| 變體 | 特徵數 | 方向準確率 | 折間標準差 | alpha 方向準確率 | 出手率 | 單次平均報酬 |',
        '|------|--------|-----------|-----------|-----------------|--------|-------------|',
    ]
    for agg, _ in all_results:
        delta = agg['dir_acc'] - base['dir_acc']
        mark = '' if agg is base else f"（{delta:+.2%}）"
        lines.append(
            f"| {agg['name']} | {agg['n_features']} | **{agg['dir_acc']:.2%}**{mark} | "
            f"{agg['dir_acc_std']:.2%} | {agg['alpha_dir_acc']:.2%} | "
            f"{agg['coverage']:.0%} | {agg['avg_ret']:+.3%} |"
        )

    lines += ['', '## 各折明細', '']
    for agg, folds in all_results:
        lines += [f'### {agg["name"]}', '',
                  '| 折 | 測試期間 | 訓練筆數 | 測試筆數 | 方向準確率 | alpha 方向 | 出手率 |',
                  '|----|---------|---------|---------|-----------|-----------|--------|']
        for f in folds:
            lines.append(
                f"| {f['fold']} | {f['test_from']} ~ {f['test_to']} | {f['n_train']} | "
                f"{f['n_test']} | {f['dir_acc']:.2%} | {f['alpha_dir_acc']:.2%} | "
                f"{f['coverage']:.0%} |"
            )
        lines.append('')

    os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)
    with open(REPORT_PATH, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    print(f'報告已寫入 {REPORT_PATH}')


if __name__ == '__main__':
    main()
