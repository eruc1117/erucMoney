"""
LSTM 誠實評估工具（Iteration 11）
─────────────────────────────────
現有 `evaluate.compute_metrics` 的方向準確率（DA）算法有兩個問題：

  1. 它比較「連續兩個樣本之差」的正負號：
         sign(diff(y_true)) vs sign(diff(y_pred))
     但跨股票測試集是把 22 檔股票的樣本**串接**而成，
     `np.diff` 會跨越股票邊界，產生無意義的比較。
  2. 即使在單一股票內，正確的問題也應該是
     「相對最後一個已知收盤價，模型預測漲還是跌？」
         sign(y_pred - last_close) vs sign(y_true - last_close)
     而不是相鄰兩次預測之間的差。

本模組提供正確的 DA，並加入**天真基準線（persistence，明日=今日）**。
金融時序中天真基準線常常打敗深度模型；不與它比較，
MAPE 2% 這種數字會給人模型很準的錯覺。

用法：
    python evaluate_honest.py                # 評估全部已訓練模型 + 基準線
    python evaluate_honest.py --models m01_vanilla m02_stacked
產出：
    results/honest_eval.md
"""

import argparse
import json
import os
import warnings
from datetime import datetime

warnings.filterwarnings("ignore")
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"

import numpy as np

from config import LOOKBACK, RESULTS_DIR, SAVED_DIR, MODEL_NAMES
from data_loader import prepare_cross_stock_data

CROSS_SAVED = SAVED_DIR / "cross_stock"
REPORT_PATH = RESULTS_DIR / "honest_eval.md"


def denorm(values: np.ndarray, norm_params: np.ndarray) -> np.ndarray:
    """正規化值 → 原始價格。"""
    return values.flatten() * norm_params[:, 1] + norm_params[:, 0]


def last_close_from_window(X: np.ndarray, norm_params: np.ndarray) -> np.ndarray:
    """
    取每個樣本輸入視窗的最後一個收盤價（原始價格）。
    這是「今日收盤」，也是天真基準線的預測值與方向判斷的基準點。
    """
    return X[:, -1, 0] * norm_params[:, 1] + norm_params[:, 0]


def honest_metrics(y_true: np.ndarray, y_pred: np.ndarray,
                   last_close: np.ndarray) -> dict:
    """
    以「相對今日收盤」為基準計算方向準確率，逐樣本獨立，不跨股票比較。
    另回報只在模型確實表態（預測變動幅度 > 0.1%）時的方向準確率——
    模型若總是預測「幾乎不變」，DA 會被大量接近零的雜訊稀釋。
    """
    err = y_true - y_pred
    mae = float(np.mean(np.abs(err)))
    rmse = float(np.sqrt(np.mean(err ** 2)))
    mape = float(np.mean(np.abs(err / (y_true + 1e-9))) * 100)

    true_dir = np.sign(y_true - last_close)
    pred_dir = np.sign(y_pred - last_close)
    da = float(np.mean(true_dir == pred_dir) * 100)

    # 模型明確表態的樣本（預測漲跌幅 > 0.1%）
    move = np.abs(y_pred - last_close) / (last_close + 1e-9)
    strong = move > 0.001
    da_strong = float(np.mean(true_dir[strong] == pred_dir[strong]) * 100) if strong.any() else float('nan')

    # 預測的平均變動幅度：接近 0 代表模型幾乎照抄今日價格
    avg_move = float(np.mean(move) * 100)

    return {'MAE': mae, 'RMSE': rmse, 'MAPE': mape, 'DA': da,
            'DA_strong': da_strong, 'n_strong': int(strong.sum()),
            'avg_pred_move_pct': avg_move, 'n': len(y_true)}


def naive_baseline(last_close: np.ndarray) -> np.ndarray:
    """天真基準線：明日收盤 = 今日收盤。"""
    return last_close.copy()


def load_model(model_key: str):
    import tensorflow as tf
    path = CROSS_SAVED / f'{model_key}.keras'
    if not path.exists():
        return None
    custom = {}
    try:
        from models.m04_attention import BahdanauAttention
        custom['BahdanauAttention'] = BahdanauAttention
    except Exception:
        pass
    try:
        return tf.keras.models.load_model(str(path), custom_objects=custom)
    except Exception as e:
        print(f'  {model_key} 載入失敗：{e}')
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--models', nargs='*', default=None)
    args = ap.parse_args()

    print('載入跨股票測試集…')
    splits, np_te, stock_labels = prepare_cross_stock_data(lookback=LOOKBACK)
    X_tr, y_tr, X_val, y_val, X_te, y_te = splits
    print(f'測試樣本 {len(X_te)}（{len(set(stock_labels))} 檔股票）\n')

    y_true = denorm(y_te, np_te)
    last_close = last_close_from_window(X_te, np_te)

    rows = []

    # ── 天真基準線 ──────────────────────────────────────────────────────────
    m = honest_metrics(y_true, naive_baseline(last_close), last_close)
    m['name'] = '天真基準線（明日=今日）'
    rows.append(m)
    print(f"天真基準線        MAE={m['MAE']:.2f} MAPE={m['MAPE']:.2f}% "
          f"DA={m['DA']:.1f}%")

    # ── 各模型 ─────────────────────────────────────────────────────────────
    keys = args.models or [k for k in MODEL_NAMES
                           if (CROSS_SAVED / f'{k}.keras').exists()]
    preds_cache = {}
    for key in keys:
        model = load_model(key)
        if model is None:
            continue
        raw = model.predict(X_te, verbose=0)
        if raw.ndim == 3:          # Seq2Seq：(N, steps, 1) → 只取第 1 步比較
            raw = raw[:, 0, :]
        y_pred = denorm(raw, np_te)
        preds_cache[key] = y_pred

        m = honest_metrics(y_true, y_pred, last_close)
        m['name'] = MODEL_NAMES.get(key, key)
        m['key'] = key
        rows.append(m)
        print(f"{key:18} MAE={m['MAE']:.2f} MAPE={m['MAPE']:.2f}% "
              f"DA={m['DA']:.1f}% 平均預測變動={m['avg_pred_move_pct']:.2f}%")

    # ── M10 集成（無 .keras 檔，由基礎模型加權組合）──────────────────────
    ens_cfg = CROSS_SAVED / 'm10_ensemble.json'
    if ens_cfg.exists():
        with open(ens_cfg, encoding='utf-8') as f:
            cfg = json.load(f)
        usable = {k: w for k, w in cfg['weights'].items() if k in preds_cache}
        if usable:
            tw = sum(usable.values())
            blended = sum(preds_cache[k] * w for k, w in usable.items()) / tw
            m = honest_metrics(y_true, blended, last_close)
            m['name'] = MODEL_NAMES['m10_ensemble']
            m['key'] = 'm10_ensemble'
            rows.append(m)
            print(f"{'m10_ensemble':18} MAE={m['MAE']:.2f} MAPE={m['MAPE']:.2f}% "
                  f"DA={m['DA']:.1f}%（{len(usable)} 個基礎模型）")

    write_report(rows, len(X_te), len(set(stock_labels)))
    np.save(RESULTS_DIR / 'honest_eval_preds.npy',
            {'y_true': y_true, 'last_close': last_close,
             'preds': preds_cache, 'labels': np.array(stock_labels)},
            allow_pickle=True)


def write_report(rows: list, n_test: int, n_stocks: int):
    base = rows[0]
    lines = [
        '# LSTM 誠實評估報告（Iteration 11）',
        '',
        f'**執行時間：** {datetime.now().strftime("%Y-%m-%d %H:%M")}',
        f'**測試集：** {n_test} 樣本 / {n_stocks} 檔股票（各股票時序最後 15%）',
        '',
        '> 方向準確率（DA）以「相對今日收盤價」計算，逐樣本獨立。',
        '> 舊的 `evaluate.compute_metrics` 用相鄰樣本相減，會跨越股票邊界，數值不可信。',
        '',
        '## 與天真基準線的比較',
        '',
        '| 模型 | MAE | RMSE | MAPE | 方向準確率 | 明確表態時的 DA | 平均預測變動 |',
        '|------|-----|------|------|-----------|----------------|-------------|',
    ]
    for r in rows:
        is_naive = r.get('key') is None and '基準線' in r['name']
        # 天真基準線預測「零變動」，本來就沒有方向意見，列數字會誤導
        da_col = '不適用（無方向意見）' if is_naive else f"**{r['DA']:.1f}%**"
        das = '—' if is_naive or not r['n_strong'] else f"{r['DA_strong']:.1f}%（{r['n_strong']}）"
        lines.append(
            f"| {r['name']} | {r['MAE']:.2f} | {r['RMSE']:.2f} | {r['MAPE']:.2f}% | "
            f"{da_col} | {das} | {r['avg_pred_move_pct']:.2f}% |"
        )

    lines += [
        '',
        '## 怎麼讀這張表',
        '',
        f'- **天真基準線的 MAE={base["MAE"]:.2f}、MAPE={base["MAPE"]:.2f}%**。',
        '  模型若沒有明顯優於它，代表只學會「把今日價格照抄」，看似精準其實沒有預測力。',
        '- 天真基準線的方向準確率標為「不適用」：它預測零變動，本來就沒有方向意見，',
        '  硬算會得到 3% 這種只反映「收盤價完全沒變」的數字。**方向的隨機基準是 50%**。',
        '- **平均預測變動**接近 0 是照抄的直接證據：模型輸出幾乎等於輸入視窗的最後一天。',
        '',
        '## 為何價格模型必然退化成照抄',
        '',
        '訓練目標是「下一日收盤價」，而收盤價序列近似隨機漫步——',
        '在 MSE 損失下，最佳解就是「等於今日收盤」。模型收斂到這個解是數學上的必然，',
        '不是訓練不足。要得到有預測力的模型，必須改以**報酬率**為預測目標',
        '（見 train_returns.py），讓「照抄」不再是低損失解。',
    ]
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(REPORT_PATH, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    print(f'\n報告已寫入 {REPORT_PATH}')


if __name__ == '__main__':
    main()
