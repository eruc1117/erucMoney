"""
以「報酬率」為預測目標的訓練實驗（Iteration 11）
────────────────────────────────────────────────
動機（來自 evaluate_honest.py 的實測結果）：

  現有 8 個價格模型的 MAE 全部落在 5.17~5.25，而天真基準線（明日=今日）
  是 5.20；方向準確率 46.9~50.6%，平均預測變動僅 0.22~0.58%。
  **模型只是學會了照抄今日價格。**

  這不是訓練不足，是數學必然：收盤價序列近似隨機漫步，
  在 MSE 損失下「預測值 = 今日收盤」就是最佳解。
  只要訓練目標是價格水準，模型就會收斂到這個平凡解。

作法：改以「次日報酬率」為目標。照抄不再是低損失解，
      模型被迫去學真正的訊號（若存在的話）。

評估口徑與 evaluate_honest.py 一致：方向準確率相對今日收盤計算，
並與天真基準線比較 MAE。方向的隨機基準是 50%。

用法：
    python train_returns.py                    # 訓練全部變體
    python train_returns.py --variants gru     # 指定變體
產出：
    saved_models/cross_stock/r01_returns.keras（若優於基準線才部署）
    results/returns_experiment.md
"""

import argparse
import json
import os
import warnings
from datetime import datetime

warnings.filterwarnings("ignore")
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"

import numpy as np
from tensorflow.keras.callbacks import EarlyStopping, ReduceLROnPlateau
from tensorflow.keras.models import Sequential
from tensorflow.keras.layers import LSTM, GRU, Dense, Dropout, Conv1D, Input

from config import (LOOKBACK, EPOCHS, BATCH_SIZE, PATIENCE,
                    TRAIN_RATIO, VAL_RATIO, SAVED_DIR, RESULTS_DIR)
from data_loader import load_prices, get_all_stocks

CROSS_SAVED = SAVED_DIR / "cross_stock"
REPORT_PATH = RESULTS_DIR / "returns_experiment.md"
MODEL_PATH = CROSS_SAVED / "r01_returns.keras"


# ── 資料 ────────────────────────────────────────────────────────────────────
def make_return_sequences(close: np.ndarray, lookback: int = LOOKBACK,
                          eps: float = 1e-8):
    """
    X : (N, lookback, 1)  過去 lookback 日的日報酬（以視窗自身標準差正規化）
    y : (N,)              次日報酬（原始比例，未正規化）
    last_close : (N,)     視窗最後一日收盤價（供還原價格與方向判斷）
    """
    rets = np.diff(close) / (close[:-1] + eps)      # 長度 T-1
    X, y, last_close = [], [], []
    for i in range(len(rets) - lookback):
        window = rets[i: i + lookback]
        std = window.std() + eps
        X.append((window / std).reshape(-1, 1))
        y.append(rets[i + lookback])
        # rets[k] 是 close[k]→close[k+1]；視窗結束於 rets[i+lookback-1]，
        # 故「今日收盤」是 close[i+lookback]
        last_close.append(close[i + lookback])
    return (np.array(X, dtype=np.float32),
            np.array(y, dtype=np.float32),
            np.array(last_close, dtype=np.float32))


def prepare_return_data(stock_ids=None, lookback: int = LOOKBACK):
    if stock_ids is None:
        stock_ids = get_all_stocks()

    parts = {s: {"X": [], "y": [], "lc": []} for s in ("train", "val", "test")}
    labels_test = []

    for sid in stock_ids:
        df = load_prices(sid)
        if df is None or len(df) < lookback + 12:
            continue
        X, y, lc = make_return_sequences(df["close_price"].values, lookback)
        n = len(X)
        n_tr, n_val = int(n * TRAIN_RATIO), int(n * VAL_RATIO)

        for name, sl in (("train", slice(0, n_tr)),
                         ("val", slice(n_tr, n_tr + n_val)),
                         ("test", slice(n_tr + n_val, None))):
            parts[name]["X"].append(X[sl])
            parts[name]["y"].append(y[sl])
            parts[name]["lc"].append(lc[sl])
        labels_test.extend([sid] * len(X[n_tr + n_val:]))

    def cat(name, k):
        return np.concatenate(parts[name][k], axis=0)

    return ((cat("train", "X"), cat("train", "y"),
             cat("val", "X"), cat("val", "y"),
             cat("test", "X"), cat("test", "y")),
            cat("test", "lc"), labels_test)


# ── 模型變體 ────────────────────────────────────────────────────────────────
def build_lstm(shape):
    return Sequential([Input(shape=shape),
                       LSTM(64, return_sequences=True), Dropout(0.2),
                       LSTM(32), Dropout(0.2), Dense(16, activation="relu"),
                       Dense(1)], name="r_lstm")


def build_gru(shape):
    return Sequential([Input(shape=shape),
                       GRU(64, return_sequences=True), Dropout(0.2),
                       GRU(32), Dropout(0.2), Dense(1)], name="r_gru")


def build_cnn(shape):
    return Sequential([Input(shape=shape),
                       Conv1D(32, 3, activation="relu", padding="causal"),
                       LSTM(32), Dropout(0.2), Dense(1)], name="r_cnn")


def build_tiny(shape):
    """刻意很小的模型：資料訊噪比低時，容量小反而不易過擬合雜訊。"""
    return Sequential([Input(shape=shape), LSTM(16), Dense(1)], name="r_tiny")


VARIANTS = {"lstm": build_lstm, "gru": build_gru,
            "cnn": build_cnn, "tiny": build_tiny}


# ── 評估 ────────────────────────────────────────────────────────────────────
def evaluate(y_true_ret, y_pred_ret, last_close):
    """方向準確率直接看報酬率正負號；另換算價格空間 MAE 以便與價格模型比較。"""
    true_price = last_close * (1 + y_true_ret)
    pred_price = last_close * (1 + y_pred_ret)
    naive_mae = float(np.mean(np.abs(true_price - last_close)))

    da = float(np.mean(np.sign(y_true_ret) == np.sign(y_pred_ret)) * 100)
    strong = np.abs(y_pred_ret) > 0.001
    da_strong = (float(np.mean(np.sign(y_true_ret[strong]) ==
                               np.sign(y_pred_ret[strong])) * 100)
                 if strong.any() else float("nan"))

    return {
        "MAE": float(np.mean(np.abs(true_price - pred_price))),
        "naive_MAE": naive_mae,
        "DA": da,
        "DA_strong": da_strong,
        "n_strong": int(strong.sum()),
        "avg_pred_move_pct": float(np.mean(np.abs(y_pred_ret)) * 100),
        "pred_up_ratio": float(np.mean(y_pred_ret > 0) * 100),
        "n": int(len(y_true_ret)),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--variants", nargs="*", default=list(VARIANTS))
    args = ap.parse_args()

    print("載入報酬率資料集…")
    splits, last_close_te, labels = prepare_return_data()
    X_tr, y_tr, X_val, y_val, X_te, y_te = splits
    print(f"訓練={len(X_tr)} 驗證={len(X_val)} 測試={len(X_te)}"
          f"（{len(set(labels))} 檔）")

    # 目標標準化：日報酬約 ±0.02，與已正規化的輸入尺度差兩個數量級，
    # 直接以 MSE 訓練會讓梯度過小而發散（首版實測 cnn 平均預測變動達 89%，
    # 日報酬不可能有這種數值 —— 那是訓練失敗，不是模型觀點）。
    # 標準差只由訓練集計算，避免未來資訊洩漏。
    y_std = float(y_tr.std()) + 1e-8
    print(f"訓練集日報酬標準差 = {y_std:.5f}（用於目標標準化）\n")
    y_tr_s, y_val_s = y_tr / y_std, y_val / y_std

    cbs = [EarlyStopping(monitor="val_loss", patience=PATIENCE,
                         restore_best_weights=True, verbose=0),
           ReduceLROnPlateau(monitor="val_loss", factor=0.5, patience=7,
                             min_lr=1e-6, verbose=0)]

    # 天真基準線：預測報酬率恆為 0（等同「明日=今日」）
    rows = [{"name": "天真基準線（報酬率=0）",
             **evaluate(y_te, np.zeros_like(y_te), last_close_te)}]
    print(f"天真基準線  MAE={rows[0]['MAE']:.2f}  DA=不適用（無方向意見）")

    best, best_da = None, -1.0
    for vk in args.variants:
        if vk not in VARIANTS:
            continue
        print(f"\n▶ 變體 {vk}")
        model = VARIANTS[vk]((X_tr.shape[1], X_tr.shape[2]))
        model.compile(optimizer="adam", loss="mse")
        model.fit(X_tr, y_tr_s, validation_data=(X_val, y_val_s),
                  epochs=EPOCHS, batch_size=BATCH_SIZE, callbacks=cbs, verbose=0)

        # 還原成真實報酬率尺度後再評估
        pred = model.predict(X_te, verbose=0).flatten() * y_std
        m = evaluate(y_te, pred, last_close_te)
        m["name"] = f"報酬率模型（{vk}）"
        m["variant"] = vk
        rows.append(m)
        print(f"  MAE={m['MAE']:.2f}（基準線 {m['naive_MAE']:.2f}）"
              f"  方向準確率={m['DA']:.2f}%"
              f"  平均預測變動={m['avg_pred_move_pct']:.3f}%"
              f"  預測上漲比例={m['pred_up_ratio']:.1f}%")

        if m["DA"] > best_da:
            best, best_da = (vk, model, m), m["DA"]

    write_report(rows, len(X_tr), len(X_te), len(set(labels)), best)

    # 只有明顯優於隨機（>51%）才部署，沿用 Iteration 9 的原則：
    # 沒有證據就不要把東西推上線
    if best and best[2]["DA"] > 51.0:
        CROSS_SAVED.mkdir(parents=True, exist_ok=True)
        best[1].save(str(MODEL_PATH))
        print(f"\n最佳變體 {best[0]}（DA={best_da:.2f}%）已存至 {MODEL_PATH}")
    else:
        print(f"\n最佳變體 DA={best_da:.2f}%，未超過 51% 門檻 → **不部署**"
              f"（避免用沒有 edge 的模型取代現況）")


def write_report(rows, n_tr, n_te, n_stocks, best):
    base = rows[0]
    lines = [
        "# 報酬率預測實驗報告（Iteration 11）",
        "",
        f"**執行時間：** {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"**資料：** 訓練 {n_tr} / 測試 {n_te} 樣本，{n_stocks} 檔股票",
        "",
        "> 動機：價格模型在 MSE 損失下的最佳解就是「照抄今日收盤」，",
        "> 因此必然退化成天真基準線（見 `honest_eval.md`）。",
        "> 改以次日報酬率為目標後，照抄不再是低損失解。",
        "",
        "| 模型 | 價格空間 MAE | 方向準確率 | 明確表態時 DA | 平均預測變動 | 預測上漲比例 |",
        "|------|-------------|-----------|--------------|-------------|-------------|",
    ]
    for r in rows:
        is_base = "基準線" in r["name"]
        da = "不適用" if is_base else f"**{r['DA']:.2f}%**"
        das = "—" if is_base or not r["n_strong"] else \
            f"{r['DA_strong']:.2f}%（{r['n_strong']}）"
        up = "—" if is_base else f"{r['pred_up_ratio']:.1f}%"
        lines.append(f"| {r['name']} | {r['MAE']:.2f} | {da} | {das} | "
                     f"{r['avg_pred_move_pct']:.3f}% | {up} |")

    lines += [
        "",
        "## 結論",
        "",
        f"- 天真基準線價格空間 MAE = **{base['MAE']:.2f}**（即實際日波動幅度）。",
        "- **方向準確率的隨機基準是 50%**。這才是判斷模型有無預測力的指標；",
        "  價格空間 MAE 在報酬率模型上必然接近基準線，因為日報酬本來就很小。",
        "- 部署門檻設為 DA > 51%：低於此不部署，避免用沒有 edge 的模型取代現況",
        "  （沿用 Iteration 9 對 M3 賣出訊號與規則 fallback 的處理原則）。",
    ]
    if best:
        lines.append(f"- 本次最佳變體：**{best[0]}**，DA = {best[2]['DA']:.2f}%。")

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"\n報告已寫入 {REPORT_PATH}")


if __name__ == "__main__":
    main()
