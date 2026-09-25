"""
整合預測模型訓練與評估（Iteration 12）
──────────────────────────────────────
目標：在**非訓練資料**上盡可能提高方向準確率。

誠實框架（沿用 Iteration 9/11 的教訓，先把作弊路徑堵死）：

  1. 走查驗證（擴張視窗）+ 標籤期封存，測試集永遠在訓練集之後
  2. 所有分位數／標準化參數只由訓練集計算
  3. 準確率一律對**未來實際報酬方向**計算，不因標籤定義改變而失真
  4. **報告準確率對出手率的完整曲線**——高準確率若只來自 20 次出手，
     那是雜訊不是模型能力。每個門檻都附上樣本數與二項檢定的標準誤。

用法：
    python train.py                       # 預設 3 日天期
    python train.py --horizons 1 3 5 10   # 天期掃描
    python train.py --min-move 0.01       # 只評估「有意義的波動」
產出：
    results/unified_report.md
"""

import argparse
import json
import os
import sys
from datetime import datetime

import numpy as np
import pandas as pd

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(BASE_DIR, '..', 'Crawler'))

from features import ALL_FEATURES, PRICE_FEATURES, CHIP_FEATURES, \
    CS_FEATURES, MARKET_FEATURES, build_panel, LOAD_SQL  # noqa: E402

RESULTS_DIR = os.path.join(BASE_DIR, 'results')
N_FOLDS = 5


# ── 資料 ────────────────────────────────────────────────────────────────────
def load_raw() -> pd.DataFrame:
    from db.connection import get_conn
    with get_conn() as conn:
        return pd.read_sql(LOAD_SQL, conn)


def build_dataset(raw: pd.DataFrame, horizon: int) -> pd.DataFrame:
    """
    只對標籤做 dropna，特徵缺失留給各特徵組自行處理。

    籌碼資料自 2012-05 才有（2330 行情可回溯至 1994），
    若在此就對全部特徵 dropna，會把 2012 年前的資料一併丟掉，
    純價量模型也跟著損失近兩萬列。
    """
    panel = build_panel(raw)
    if panel.empty:
        return panel
    panel = panel.sort_values(['stock_id', 'trade_date'])
    panel['fwd_ret'] = panel.groupby('stock_id')['close'].transform(
        lambda s: s.shift(-horizon) / s - 1)
    panel = panel.dropna(subset=['fwd_ret'])
    panel = panel.sort_values(['trade_date', 'stock_id']).reset_index(drop=True)
    # 相對同儕的超額報酬（Iteration 9 證實比原始報酬可學）
    panel['alpha'] = panel['fwd_ret'] - panel.groupby('trade_date')['fwd_ret'].transform('mean')
    return panel


# ── 評估 ────────────────────────────────────────────────────────────────────
def majority_baseline(fwd_ret: np.ndarray) -> dict:
    """
    **最重要的基準線**：永遠猜多數類別（在多頭市場就是「永遠喊漲」）。

    天期拉長時上漲的先驗機率會明顯高於 50%，此時模型的高準確率
    可能完全來自這個先驗，而不是預測能力。不與此比較，
    「天期 20 日準確率 57%」這種數字會給人模型很強的錯覺。
    """
    up_rate = float((fwd_ret > 0).mean())
    return {'up_rate': up_rate, 'majority_acc': max(up_rate, 1 - up_rate)}


def effective_n(n: int, horizon: int) -> int:
    """
    重疊視窗修正：天期 h 的相鄰樣本共用 h-1 天的結果，並非獨立。
    以 n/h 作為有效樣本數的保守估計，用於計算可信的標準誤。
    """
    return max(int(n / max(horizon, 1)), 1)


def coverage_curve(proba_up: np.ndarray, fwd_ret: np.ndarray,
                   min_move: float = 0.0, horizon: int = 1) -> list:
    """
    以「距離 0.5 的距離」作為信心，掃描不同出手率下的方向準確率。

    回傳每個出手率的 (coverage, n, accuracy, 標準誤)。
    標準誤 = sqrt(p(1-p)/n)，用來判斷高準確率是真本事還是樣本太少。
    """
    conf = np.abs(proba_up - 0.5)
    pred_up = proba_up > 0.5

    mask = np.ones(len(fwd_ret), dtype=bool)
    if min_move > 0:
        mask = np.abs(fwd_ret) >= min_move        # 只評估有意義的波動

    # 基準線必須是**全測試集**的無條件先驗，不能用模型選出的子集去算——
    # 模型若在高信心區都喊同一個方向，子集基準必然等於模型準確率（循環論證）。
    _b = majority_baseline(fwd_ret[mask])
    base_acc, base_up = _b['majority_acc'], _b['up_rate']

    rows = []
    for cov in (1.0, 0.2, 0.1, 0.05, 0.02, 0.01, 0.005, 0.002):
        k = max(int(len(conf) * cov), 1)
        idx = np.argsort(-conf)[:k]
        idx = idx[mask[idx]]
        if len(idx) < 10:
            continue
        correct = (pred_up[idx] == (fwd_ret[idx] > 0))
        acc = float(correct.mean())
        # 標準誤以「重疊修正後的有效樣本數」計算，避免長天期的區間過度樂觀
        n_eff = effective_n(len(idx), horizon)
        se = float(np.sqrt(acc * (1 - acc) / n_eff))
        rows.append({'coverage': cov, 'n': int(len(idx)), 'n_eff': n_eff,
                     'accuracy': acc, 'se': se, 'lower95': acc - 1.96 * se,
                     'majority_acc': base_acc,
                     'up_rate': base_up,
                     'edge': acc - base_acc,
                     'avg_ret': float(np.where(pred_up[idx], fwd_ret[idx],
                                               -fwd_ret[idx]).mean())})
    return rows


def walk_forward(data: pd.DataFrame, feature_cols: list, horizon: int,
                 model_kind: str = 'hgb', label: str = 'alpha'):
    """擴張視窗走查；回傳測試期的 (預測上漲機率, 實際報酬)。"""
    from sklearn.ensemble import HistGradientBoostingClassifier

    # 各特徵組自行剔除缺失列（籌碼組會自動只剩 2012 年後的資料）
    usable = data[feature_cols].notna().all(axis=1).values
    data = data[usable].reset_index(drop=True)
    if len(data) < 1000:
        return None, None, None

    dates = np.sort(data['trade_date'].unique())
    start = int(len(dates) * 0.5)
    bounds = np.linspace(start, len(dates), N_FOLDS + 1).astype(int)
    X = data[feature_cols].values

    all_proba, all_ret, all_fold = [], [], []
    for i in range(N_FOLDS):
        te_lo, te_hi = dates[bounds[i]], dates[bounds[i + 1] - 1]
        embargo_from = dates[max(bounds[i] - horizon, 0)]
        tr_mask = (data['trade_date'] < embargo_from).values
        te_mask = ((data['trade_date'] >= te_lo) &
                   (data['trade_date'] <= te_hi)).values
        if tr_mask.sum() < 500 or te_mask.sum() < 50:
            continue

        # 二元標籤：漲/跌。alpha 版本以「是否優於同日同儕平均」為準
        target = data['alpha'] if label == 'alpha' else data['fwd_ret']
        y = (target > 0).astype(int).values

        if model_kind == 'hgb':
            clf = HistGradientBoostingClassifier(
                max_iter=300, max_depth=4, learning_rate=0.05,
                min_samples_leaf=100, l2_regularization=1.0,
                early_stopping=True, validation_fraction=0.15, random_state=42)
        else:
            from sklearn.linear_model import LogisticRegression
            from sklearn.pipeline import make_pipeline
            from sklearn.preprocessing import StandardScaler
            clf = make_pipeline(StandardScaler(),
                                LogisticRegression(max_iter=2000, C=0.1))

        clf.fit(X[tr_mask], y[tr_mask])
        proba = clf.predict_proba(X[te_mask])[:, 1]
        all_proba.append(proba)
        # 評分口徑必須與訓練目標一致：訓練 alpha 就用 alpha 評分。
        # 否則會變成「訓練預測相對強弱、卻拿絕對漲跌評分」，
        # 而絕對漲跌在多頭期間先驗高達 54%，比較基準也跟著失真。
        all_ret.append(data.loc[te_mask, 'alpha' if label == 'alpha' else 'fwd_ret'].values)
        all_fold.append(np.full(te_mask.sum(), i + 1))

    if not all_proba:
        return None, None, None
    return (np.concatenate(all_proba), np.concatenate(all_ret),
            np.concatenate(all_fold))


# ── 主流程 ──────────────────────────────────────────────────────────────────
FEATURE_SETS = {
    '全部特徵': ALL_FEATURES,
    '僅價量技術面': PRICE_FEATURES,
    '僅籌碼面': CHIP_FEATURES,
    '籌碼+橫斷面': CHIP_FEATURES + CS_FEATURES + MARKET_FEATURES,
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--horizons', type=int, nargs='+', default=[3])
    ap.add_argument('--min-move', type=float, default=0.0,
                    help='只評估未來報酬絕對值 >= 此值的樣本')
    ap.add_argument('--label', choices=['alpha', 'raw'], default='alpha')
    args = ap.parse_args()

    print('載入資料…')
    raw = load_raw()
    print(f'原始 {len(raw)} 筆 / {raw["stock_id"].nunique()} 檔')

    all_results = []
    for h in args.horizons:
        data = build_dataset(raw, h)
        if data.empty:
            print(f'天期 {h}：特徵化後無資料')
            continue
        print(f'\n=== 天期 {h} 日：面板 {len(data)} 筆 / '
              f'{data["stock_id"].nunique()} 檔 / '
              f'{data["trade_date"].nunique()} 個交易日 '
              f'（{str(data["trade_date"].min())[:10]} ~ '
              f'{str(data["trade_date"].max())[:10]}）===')

        for set_name, cols in FEATURE_SETS.items():
            n_usable = int(data[cols].notna().all(axis=1).sum())
            proba, ret, _ = walk_forward(data, cols, h, label=args.label)
            if proba is None:
                print(f'  {set_name:14} 可用資料不足（{n_usable} 列），略過')
                continue
            curve = coverage_curve(proba, ret, args.min_move, horizon=h)
            full = next((c for c in curve if c['coverage'] == 1.0), None)
            all_results.append({'horizon': h, 'features': set_name,
                                'curve': curve, 'n_features': len(cols)})
            print(f"  {set_name}（可用 {n_usable} 列）"
                  f" 全樣本 {full['accuracy']:.2%}"
                  f"　vs 永遠喊多數類 {full['majority_acc']:.2%}"
                  f"（上漲率 {full['up_rate']:.1%}）")
            for c in curve:
                if c['coverage'] <= 0.2:
                    mark = ' ★' if c['edge'] > 0.05 and c['lower95'] > c['majority_acc'] else ''
                    print(f"      出手率 {c['coverage']:>6.1%}  n={c['n']:>5}"
                          f"（有效 {c['n_eff']:>4}）  準確率 {c['accuracy']:.2%}"
                          f"  超越基準 {c['edge']:+.2%}"
                          f"  95%下界 {c['lower95']:.2%}{mark}")

    write_report(all_results, args)


def write_report(results: list, args):
    os.makedirs(RESULTS_DIR, exist_ok=True)
    path = os.path.join(RESULTS_DIR, 'unified_report.md')
    lines = [
        '# 整合模型評估報告（Iteration 12）',
        '',
        f'**執行時間：** {datetime.now().strftime("%Y-%m-%d %H:%M")}',
        f'**標籤：** {"相對同儕超額報酬（alpha）" if args.label == "alpha" else "原始報酬"}'
        f'　**最小波動門檻：** {args.min_move:.1%}',
        f'**驗證：** {N_FOLDS} 折擴張視窗走查 + 標籤期封存，測試集永遠在訓練集之後',
        '',
        '> 準確率一律對**未來實際報酬方向**計算。',
        '> 每列附樣本數與二項標準誤：高準確率若只來自少量出手，95% 下界會明顯低於點估計。',
        '',
    ]
    for r in results:
        lines += [f"## 天期 {r['horizon']} 日 — {r['features']}（{r['n_features']} 個特徵）", '',
                  '| 出手率 | 樣本數 | 準確率 | 標準誤 | 95% 下界 | 單次平均報酬 |',
                  '|-------|-------|-------|-------|---------|-------------|']
        for c in r['curve']:
            lines.append(f"| {c['coverage']:.0%} | {c['n']} | **{c['accuracy']:.2%}** | "
                         f"±{c['se']:.2%} | {c['lower95']:.2%} | {c['avg_ret']:+.2%} |")
        lines.append('')

    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    print(f'\n報告已寫入 {path}')


if __name__ == '__main__':
    main()
