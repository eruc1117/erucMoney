"""
M3 籌碼觀測員 — Random Forest 訓練腳本 v2（Iteration 9）

v1 → v2 的三項改動，皆由 experiment_m3.py 的走查驗證背書（見 results/m3_experiment.md）：

  1. 標籤改用 alpha（超額報酬）
     原始 3 日報酬由大盤 beta 主導，籌碼資料預測不了大盤，模型只是在擬合雜訊。
     改為「個股報酬 − 當日全體平均報酬」，門檻取訓練集三分位（僅用訓練集計算）。
  2. 加入橫斷面特徵
     同日 22 檔之間的百分位排名，讓模型判斷得出「只有這檔被買超」與「全體都被買超」。
  3. 走查驗證取代單一切分
     5 折擴張視窗 + 訓練集尾端封存 3 個交易日（標籤跨期洩漏防護）。

走查結果：方向準確率 51.71%（v1 設定）→ 52.73%（v2 設定）。

**部署政策（本檔寫入模型 bundle，推論端 model3_chip.py 直接讀取）：**
  gate = 0.35      v1 寫死 0.45，但模型最高機率僅約 0.45，實測 22 檔全被擋下、
                   線上等於永遠 Hold —— 這個失效直到 Iteration 9 才被發現。
                   0.35 由 simulate_deployment.py 決定：門檻愈高愈準也愈沉默，
                   0.40 雖有 66.8% 準確率卻曾連續 50 個交易日無訊號；
                   0.35 為 56.9% 準確率但 82% 的交易日有訊號，總體訊號價值約為兩倍。
  sell_policy      走查顯示賣出訊號方向準確率僅約 52%、平均報酬為負，
                   而投票引擎不參考 confidence（固定 ±0.33 計分），
                   放行等於注入雜訊 → 預設 'suppress'（Sell 改判 Hold）。
                   代價：M3 只會投 Buy 或 Hold，在投票中只能往多方推。

用法：
    python train_m3.py                 # 訓練 + 走查評估 + 存模型
    python train_m3.py --eval-only     # 只評估既有模型
    python train_m3.py --keep-sell     # 部署時放行 Sell（不建議，僅供比較）
產出：
    saved_models/m3_chip_rf.joblib
    results/m3_metrics.md
"""

import argparse
import os
import sys
from datetime import datetime

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier

CRAWLER_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'Crawler')
sys.path.insert(0, CRAWLER_DIR)

from db.connection import get_conn                                      # noqa: E402
from m3_features import build_panel, MODEL_FEATURE_COLS                 # noqa: E402

BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH  = os.path.join(BASE_DIR, 'saved_models', 'm3_chip_rf.joblib')
REPORT_PATH = os.path.join(BASE_DIR, 'results', 'm3_metrics.md')

LABEL_MAP     = {0: 'Sell', 1: 'Hold', 2: 'Buy'}
LABEL_HORIZON = 3       # 未來 3 個交易日（天期掃描證實 5/10/20 日更差）
EMBARGO_DAYS  = 3       # = LABEL_HORIZON，訓練集尾端封存
N_FOLDS       = 5
PROBA_GATE    = 0.35    # 部署門檻（見檔頭說明；simulate_deployment.py 決定此值）

RF_PARAMS = dict(n_estimators=500, max_depth=6, min_samples_leaf=120,
                 max_features=0.5, class_weight='balanced_subsample',
                 random_state=42, n_jobs=-1)


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


def build_training_frame(raw: pd.DataFrame) -> pd.DataFrame:
    """特徵面板 + 未來報酬 + alpha。"""
    panel = build_panel(raw)
    panel = panel.sort_values(['stock_id', 'trade_date'])
    panel['fwd_ret'] = panel.groupby('stock_id')['close'].transform(
        lambda s: s.shift(-LABEL_HORIZON) / s - 1)
    panel = panel.dropna(subset=['fwd_ret']).sort_values(['trade_date', 'stock_id'])
    panel['alpha'] = panel['fwd_ret'] - panel.groupby('trade_date')['fwd_ret'].transform('mean')
    return panel.reset_index(drop=True)


def alpha_labels(data: pd.DataFrame, train_mask: np.ndarray) -> np.ndarray:
    """alpha 三分位標籤；分位點只由訓練集計算，避免未來資訊洩漏。"""
    tr = data.loc[train_mask, 'alpha']
    lo, hi = tr.quantile(1 / 3), tr.quantile(2 / 3)
    return np.select([data['alpha'] > hi, data['alpha'] < lo], [2, 0], default=1)


# --------------------------------------------------------------------------- #
def gated_metrics(proba: np.ndarray, fwd_ret: np.ndarray, gate: float) -> dict:
    """套用信心門檻後的方向準確率與多空拆解（一律對原始報酬計算）。"""
    pred = proba.argmax(axis=1)
    pred = np.where(proba.max(axis=1) < gate, 1, pred)
    act = pred != 1
    if not act.any():
        return {'n_calls': 0, 'coverage': 0.0, 'dir_acc': np.nan,
                'n_long': 0, 'long_dir_acc': np.nan, 'long_avg_ret': np.nan,
                'n_short': 0, 'short_dir_acc': np.nan, 'short_avg_ret': np.nan}
    long_ = pred[act] == 2
    r = fwd_ret[act]
    ok = np.where(long_, r > 0, r < 0)
    lm, sm = long_, ~long_
    return {
        'n_calls': int(act.sum()),
        'coverage': float(act.mean()),
        'dir_acc': float(ok.mean()),
        'n_long': int(lm.sum()),
        'long_dir_acc': float(ok[lm].mean()) if lm.any() else np.nan,
        'long_avg_ret': float(r[lm].mean()) if lm.any() else np.nan,
        'n_short': int(sm.sum()),
        'short_dir_acc': float(ok[sm].mean()) if sm.any() else np.nan,
        'short_avg_ret': float(-r[sm].mean()) if sm.any() else np.nan,
    }


def walk_forward_eval(data: pd.DataFrame) -> tuple:
    """5 折擴張視窗走查，回傳 (各折指標, 加權彙總)。"""
    dates = np.sort(data['trade_date'].unique())
    start = int(len(dates) * 0.5)
    bounds = np.linspace(start, len(dates), N_FOLDS + 1).astype(int)
    X = data[MODEL_FEATURE_COLS].values

    folds = []
    for i in range(N_FOLDS):
        te_lo, te_hi = dates[bounds[i]], dates[bounds[i + 1] - 1]
        embargo_from = dates[max(bounds[i] - EMBARGO_DAYS, 0)]
        train_mask = (data['trade_date'] < embargo_from).values
        test_mask  = ((data['trade_date'] >= te_lo) & (data['trade_date'] <= te_hi)).values

        y = alpha_labels(data, train_mask)
        model = RandomForestClassifier(**RF_PARAMS)
        model.fit(X[train_mask], y[train_mask])
        proba = model.predict_proba(X[test_mask])

        m = gated_metrics(proba, data.loc[test_mask, 'fwd_ret'].values, PROBA_GATE)
        m0 = gated_metrics(proba, data.loc[test_mask, 'fwd_ret'].values, 0.0)
        m.update({'fold': i + 1, 'test_from': str(te_lo)[:10], 'test_to': str(te_hi)[:10],
                  'n_train': int(train_mask.sum()), 'n_test': int(test_mask.sum()),
                  'dir_acc_nogate': m0['dir_acc'], 'coverage_nogate': m0['coverage']})
        folds.append(m)
        print(f"  fold {i+1} [{m['test_from']}~{m['test_to']}] "
              f"門檻後方向 {m['dir_acc']:.2%}（出手 {m['n_calls']}）"
              f" / 無門檻 {m0['dir_acc']:.2%}")

    df = pd.DataFrame(folds)

    def wavg(col, wcol):
        sub = df[[col, wcol]].dropna()
        return float(np.average(sub[col], weights=sub[wcol])) if len(sub) and sub[wcol].sum() else np.nan

    agg = {
        'dir_acc': wavg('dir_acc', 'n_calls'),
        'dir_acc_std': float(df['dir_acc'].std()),
        'coverage': wavg('coverage', 'n_test'),
        'n_calls': int(df['n_calls'].sum()),
        'dir_acc_nogate': wavg('dir_acc_nogate', 'n_test'),
        'long_dir_acc': wavg('long_dir_acc', 'n_long'),
        'long_avg_ret': wavg('long_avg_ret', 'n_long'),
        'n_long': int(df['n_long'].sum()),
        'short_dir_acc': wavg('short_dir_acc', 'n_short'),
        'short_avg_ret': wavg('short_avg_ret', 'n_short'),
        'n_short': int(df['n_short'].sum()),
    }
    return folds, agg


# --------------------------------------------------------------------------- #
def write_report(agg: dict, folds: list, data: pd.DataFrame, importances: pd.Series,
                 sell_policy: str):
    lines = [
        '# M3 籌碼模型（Random Forest v2）評估報告',
        '',
        f'**訓練時間：** {datetime.now().strftime("%Y-%m-%d %H:%M")}',
        f'**資料：** {len(data)} 筆面板 / {data["stock_id"].nunique()} 檔 / '
        f'{data["trade_date"].nunique()} 個交易日 '
        f'（{str(data["trade_date"].min())[:10]} ~ {str(data["trade_date"].max())[:10]}）',
        f'**標籤：** 未來 {LABEL_HORIZON} 日 alpha（超額報酬）三分位，門檻僅由訓練集計算',
        f'**驗證：** {N_FOLDS} 折擴張視窗走查，訓練集尾端封存 {EMBARGO_DAYS} 個交易日',
        f'**部署門檻：** {PROBA_GATE}　**賣出政策：** {sell_policy}',
        '',
        '> 方向準確率一律以**原始未來報酬**計算（非 alpha），確保與 v1 的 50.83% 可比。',
        '',
        '## 走查彙總',
        '',
        '| 指標 | 數值 |',
        '|------|------|',
        f"| 方向準確率（門檻 {PROBA_GATE} 後） | **{agg['dir_acc']:.2%}** |",
        f"| 折間標準差 | {agg['dir_acc_std']:.2%} |",
        f"| 出手率 | {agg['coverage']:.1%}（{agg['n_calls']} 次） |",
        f"| 方向準確率（無門檻對照） | {agg['dir_acc_nogate']:.2%} |",
        '',
        '## 多空拆解（本迭代最關鍵的發現）',
        '',
        '| 方向 | 出手次數 | 方向準確率 | 平均 3 日報酬 |',
        '|------|---------|-----------|--------------|',
        f"| 買進 | {agg['n_long']} | **{agg['long_dir_acc']:.2%}** | **{agg['long_avg_ret']:+.2%}** |",
        f"| 賣出 | {agg['n_short']} | {agg['short_dir_acc']:.2%} | {agg['short_avg_ret']:+.2%} |",
        '',
        '買進訊號有明確edge；賣出訊號接近擲硬幣且平均報酬為負，故預設抑制。',
        '注意：本資料期間（2023–2026）台股為多頭格局，賣出側的弱勢可能部分源自市場情境，',
        '若日後進入空頭，應重跑 `experiment_m3.py` 重新檢驗此政策。',
        '',
        '## 各折明細',
        '',
        '| 折 | 測試期間 | 訓練筆數 | 測試筆數 | 門檻後方向 | 出手次數 | 無門檻方向 |',
        '|----|---------|---------|---------|-----------|---------|-----------|',
    ]
    for f in folds:
        lines.append(
            f"| {f['fold']} | {f['test_from']} ~ {f['test_to']} | {f['n_train']} | "
            f"{f['n_test']} | {f['dir_acc']:.2%} | {f['n_calls']} | {f['dir_acc_nogate']:.2%} |"
        )

    lines += ['', '## 特徵重要度（前 12）', '', '| 特徵 | 重要度 |', '|------|--------|']
    for name, val in importances.head(12).items():
        lines.append(f'| {name} | {val:.4f} |')

    os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)
    with open(REPORT_PATH, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    print(f'報告已寫入 {REPORT_PATH}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--eval-only', action='store_true')
    ap.add_argument('--keep-sell', action='store_true',
                    help='部署時放行 Sell 訊號（走查顯示無 edge，不建議）')
    args = ap.parse_args()
    sell_policy = 'allow' if args.keep_sell else 'suppress'

    print('載入資料…')
    raw = load_dataset()
    print(f'原始 {len(raw)} 筆（{raw["stock_id"].nunique()} 檔）')

    data = build_training_frame(raw)
    print(f'面板 {len(data)} 筆 / {data["trade_date"].nunique()} 個交易日')

    print(f'\n走查驗證（{N_FOLDS} 折）…')
    folds, agg = walk_forward_eval(data)
    print(f"\n彙總：門檻後方向準確率 {agg['dir_acc']:.2%}（出手率 {agg['coverage']:.1%}）")
    print(f"      買進 {agg['n_long']} 次 {agg['long_dir_acc']:.2%} 平均 {agg['long_avg_ret']:+.2%}")
    print(f"      賣出 {agg['n_short']} 次 {agg['short_dir_acc']:.2%} 平均 {agg['short_avg_ret']:+.2%}")

    if args.eval_only:
        bundle = joblib.load(MODEL_PATH)
        model = bundle['model']
    else:
        # 最終模型：以全部資料重訓（走查僅用於估計泛化表現）
        print('\n以全部資料重訓最終模型…')
        full_mask = np.ones(len(data), dtype=bool)
        y = alpha_labels(data, full_mask)
        model = RandomForestClassifier(**RF_PARAMS)
        model.fit(data[MODEL_FEATURE_COLS].values, y)

    importances = pd.Series(model.feature_importances_,
                            index=MODEL_FEATURE_COLS).sort_values(ascending=False)
    write_report(agg, folds, data, importances, sell_policy)

    if not args.eval_only:
        os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)
        joblib.dump({
            'model': model,
            'feature_cols': MODEL_FEATURE_COLS,
            'label_map': LABEL_MAP,
            'version': 2,
            'label_type': 'alpha_tercile',
            'horizon': LABEL_HORIZON,
            'proba_gate': PROBA_GATE,
            'sell_policy': sell_policy,
            'trained_at': datetime.now().isoformat(),
            'metrics_walk_forward': agg,
        }, MODEL_PATH)
        print(f'模型已存 {MODEL_PATH}（gate={PROBA_GATE}, sell_policy={sell_policy}）')
        _register('m3_chip', {'proba_gate': PROBA_GATE,
                              'sell_policy': sell_policy,
                              'label_horizon': LABEL_HORIZON})


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
