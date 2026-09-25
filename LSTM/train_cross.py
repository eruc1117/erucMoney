"""
跨股票 LSTM 模型訓練
────────────────────
原理：以 Window-level Z-score 正規化消除不同股票的價格尺度差異，
      讓單一模型可以泛化至任意股票（含未訓練過的）。

輸入：收盤價過去 20 天（各窗口自行標準化）
輸出：下一個交易日收盤價（正規化值，推論時反正規化還原真實價格）

用法：
    python train_cross.py                 # 訓練所有模型
    python train_cross.py --models m01 m02
    python train_cross.py --stocks 2330 2317  # 限定股票
"""
import argparse
import json
import os
import sys
import traceback
import warnings
warnings.filterwarnings("ignore")
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"

import numpy as np
import pandas as pd
from tensorflow.keras.callbacks import EarlyStopping, ReduceLROnPlateau

from config import (EPOCHS, BATCH_SIZE, PATIENCE, LOOKBACK,
                    SAVED_DIR, RESULTS_DIR, REPORT_DIR, MODEL_NAMES)
from data_loader import prepare_cross_stock_data, get_all_stocks
from evaluate import compute_metrics, plot_predictions, plot_loss
from models import MODEL_BUILDERS

CROSS_SAVED_DIR = SAVED_DIR / "cross_stock"
CROSS_RESULTS_DIR = RESULTS_DIR / "cross_stock"


def callbacks():
    return [
        EarlyStopping(monitor="val_loss", patience=PATIENCE,
                      restore_best_weights=True, verbose=0),
        ReduceLROnPlateau(monitor="val_loss", factor=0.5,
                          patience=7, min_lr=1e-6, verbose=0),
    ]


def train_cross_model(model_key: str, stock_ids: list[str] | None = None):
    """
    使用合併資料集訓練單一跨股票模型，
    評估時對每支股票分別計算指標。
    """
    print(f"\n  [{MODEL_NAMES[model_key]}] 載入跨股票資料...", end=" ", flush=True)

    splits, norm_params_test, stock_labels = prepare_cross_stock_data(
        stock_ids=stock_ids, lookback=LOOKBACK)

    X_tr, y_tr, X_val, y_val, X_te, y_te = splits
    if len(X_tr) < 20:
        print("資料不足，跳過")
        return None

    print(f"訓練樣本={len(X_tr)}  驗證={len(X_val)}  測試={len(X_te)}")

    input_shape = (X_tr.shape[1], X_tr.shape[2])  # (lookback, 1)
    model       = MODEL_BUILDERS[model_key](input_shape)

    history = model.fit(
        X_tr, y_tr,
        validation_data=(X_val, y_val),
        epochs=EPOCHS, batch_size=BATCH_SIZE,
        callbacks=callbacks(), verbose=0,
    )

    # ── 儲存模型 ────────────────────────────────────────────────────────────
    CROSS_SAVED_DIR.mkdir(parents=True, exist_ok=True)
    model_path = CROSS_SAVED_DIR / f"{model_key}.keras"
    model.save(str(model_path))

    # ── 反正規化 ─────────────────────────────────────────────────────────────
    y_pred_norm = model.predict(X_te, verbose=0).flatten()  # 正規化預測值
    means = norm_params_test[:, 0]
    stds  = norm_params_test[:, 1]

    y_true_price = y_te.flatten() * stds + means   # 反正規化真實價
    y_pred_price = y_pred_norm    * stds + means   # 反正規化預測價

    # ── 整體指標 ─────────────────────────────────────────────────────────────
    overall = compute_metrics(y_true_price, y_pred_price)
    print(f"    整體 MAE={overall['MAE']:.2f}  RMSE={overall['RMSE']:.2f}"
          f"  MAPE={overall['MAPE']:.2f}%  DA={overall['DA']:.1f}%")

    # ── 各股票指標 ───────────────────────────────────────────────────────────
    labels = np.array(stock_labels)
    per_stock = []
    unique_stocks = sorted(set(stock_labels))

    for sid in unique_stocks:
        mask = labels == sid
        if mask.sum() < 2:
            continue
        m = compute_metrics(y_true_price[mask], y_pred_price[mask])
        per_stock.append({"stock_id": sid, **m})

        # 個股圖表
        out_dir = CROSS_RESULTS_DIR / model_key / sid
        out_dir.mkdir(parents=True, exist_ok=True)
        plot_predictions(
            y_true_price[mask], y_pred_price[mask],
            stock_id=sid,
            model_key=f"cross_stock/{model_key}",
            model_name=f"{MODEL_NAMES[model_key]}（跨股票）",
        )

    # Loss 曲線
    CROSS_RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    plot_loss(history, stock_id="all",
              model_key=f"cross_stock/{model_key}",
              model_name=MODEL_NAMES[model_key])

    # ── 儲存結果 ─────────────────────────────────────────────────────────────
    result = {
        "model_key":  model_key,
        "model_name": MODEL_NAMES[model_key],
        "overall":    overall,
        "per_stock":  per_stock,
        "model_path": str(model_path),
    }
    out_dir = CROSS_RESULTS_DIR / model_key
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "metrics.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    return result


def train_seq2seq(stock_ids: list[str] | None = None):
    """
    M07 Seq2Seq（Iteration 11 新增支援）。

    舊版把 m07 列入跳過清單，原因是跨股票管線只產生單步標籤 y=(N,)，
    而 Seq2Seq 需要 (N, forecast_steps, 1)。現以
    `prepare_cross_stock_seq2seq` 提供多步標籤。

    評估時取「第 1 步」與其他單步模型比較（口徑一致），
    另外回報各步的 MAPE，觀察誤差如何隨預測天期擴大。
    """
    from config import FORECAST_STEPS
    from data_loader import prepare_cross_stock_seq2seq

    key = "m07_seq2seq"
    print(f"\n  [{MODEL_NAMES[key]}] 載入多步資料...", end=" ", flush=True)
    splits, np_te, stock_labels = prepare_cross_stock_seq2seq(
        stock_ids=stock_ids, lookback=LOOKBACK, forecast_steps=FORECAST_STEPS)
    X_tr, y_tr, X_val, y_val, X_te, y_te = splits
    if len(X_tr) < 20:
        print("資料不足，跳過")
        return None
    print(f"訓練={len(X_tr)} 驗證={len(X_val)} 測試={len(X_te)}"
          f"（每筆預測 {FORECAST_STEPS} 步）")

    model = MODEL_BUILDERS[key]((X_tr.shape[1], X_tr.shape[2]))
    history = model.fit(X_tr, y_tr, validation_data=(X_val, y_val),
                        epochs=EPOCHS, batch_size=BATCH_SIZE,
                        callbacks=callbacks(), verbose=0)

    CROSS_SAVED_DIR.mkdir(parents=True, exist_ok=True)
    model_path = CROSS_SAVED_DIR / f"{key}.keras"
    model.save(str(model_path))

    pred = model.predict(X_te, verbose=0)          # (N, steps, 1)
    means, stds = np_te[:, 0:1], np_te[:, 1:2]
    y_true_price = y_te[:, :, 0] * stds + means    # (N, steps)
    y_pred_price = pred[:, :, 0] * stds + means

    # 逐步 MAPE：觀察誤差隨天期擴大的情形
    per_step = []
    for s in range(y_true_price.shape[1]):
        m = compute_metrics(y_true_price[:, s], y_pred_price[:, s])
        per_step.append({"step": s + 1, **m})
        print(f"    第 {s+1} 步  MAE={m['MAE']:.2f}  MAPE={m['MAPE']:.2f}%")

    overall = compute_metrics(y_true_price[:, 0], y_pred_price[:, 0])
    print(f"    第 1 步整體 MAE={overall['MAE']:.2f} MAPE={overall['MAPE']:.2f}%")

    labels = np.array(stock_labels)
    per_stock = []
    for sid in sorted(set(stock_labels)):
        mask = labels == sid
        if mask.sum() < 2:
            continue
        per_stock.append({"stock_id": sid,
                          **compute_metrics(y_true_price[mask, 0],
                                            y_pred_price[mask, 0])})

    result = {"model_key": key, "model_name": MODEL_NAMES[key],
              "overall": overall, "per_step": per_step,
              "per_stock": per_stock, "forecast_steps": FORECAST_STEPS,
              "model_path": str(model_path)}
    out_dir = CROSS_RESULTS_DIR / key
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "metrics.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    return result


def build_ensemble(base_keys: list[str] | None = None):
    """
    M10 Ensemble（Iteration 11 新增支援）。

    M10 **不是可訓練的神經網路**，而是對其他模型預測做加權平均的方法——
    這才是舊版把它列入跳過清單的真正原因（沒有東西可以存成 .keras）。

    這裡改為產生一份權重設定檔，推論時由 serve.py 即時組合基礎模型。
    權重取各基礎模型測試集 MAE 的反比（誤差小者權重高），
    與 `models/m10_ensemble.compute_dynamic_weights` 一致。
    """
    from models.m10_ensemble import compute_dynamic_weights

    base_keys = base_keys or ["m01_vanilla", "m02_stacked", "m03_bidirectional"]
    maes = {}
    for k in base_keys:
        path = CROSS_RESULTS_DIR / k / "metrics.json"
        if not path.exists():
            print(f"    略過 {k}：找不到 metrics.json（請先訓練）")
            continue
        with open(path, encoding="utf-8") as f:
            maes[k] = float(json.load(f)["overall"]["MAE"])

    if not maes:
        print("    無可用的基礎模型，M10 無法建立")
        return None

    weights = compute_dynamic_weights(maes)
    cfg = {"model_key": "m10_ensemble", "model_name": MODEL_NAMES["m10_ensemble"],
           "base_models": list(weights.keys()), "weights": weights,
           "source_mae": maes,
           "note": "推論時由 serve.py 即時加權組合，無 .keras 模型檔"}

    CROSS_SAVED_DIR.mkdir(parents=True, exist_ok=True)
    with open(CROSS_SAVED_DIR / "m10_ensemble.json", "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    out_dir = CROSS_RESULTS_DIR / "m10_ensemble"
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "metrics.json", "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)

    print("    權重：" + "  ".join(f"{k}={v:.3f}" for k, v in weights.items()))
    return cfg


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--models", nargs="*", default=None,
                        help="指定模型 key，例如 m01_vanilla m02_stacked")
    parser.add_argument("--stocks", nargs="*", default=None,
                        help="限定訓練用的股票代碼")
    args = parser.parse_args()

    # m07 與 m10 需要各自的流程（見上方兩個函式），不走一般單步管線
    special = {"m07_seq2seq", "m10_ensemble"}
    all_keys = list(MODEL_NAMES)
    run_keys = args.models if args.models else all_keys
    run_keys = [k for k in run_keys if k in MODEL_NAMES]

    stock_ids = args.stocks if args.stocks else None

    print(f"\n{'='*60}")
    print(f"  跨股票 LSTM 訓練")
    print(f"  模型：{', '.join(run_keys)}")
    print(f"{'='*60}")

    summary = []
    # m10 必須最後跑：它的權重取自其他模型的 metrics.json
    for key in sorted(run_keys, key=lambda k: k == "m10_ensemble"):
        try:
            if key == "m07_seq2seq":
                result = train_seq2seq(stock_ids=stock_ids)
            elif key == "m10_ensemble":
                print(f"\n  [{MODEL_NAMES[key]}] 建立集成權重...")
                result = build_ensemble()
                if result:
                    summary.append({"model_key": key,
                                    "model_name": result["model_name"],
                                    "MAE": float("nan"), "RMSE": float("nan"),
                                    "MAPE": float("nan"), "DA": float("nan")})
                continue
            else:
                result = train_cross_model(key, stock_ids=stock_ids)

            if result:
                summary.append({
                    "model_key":  key,
                    "model_name": result["model_name"],
                    **result["overall"],
                })
        except Exception:
            traceback.print_exc()

    if summary:
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        df = pd.DataFrame(summary)
        csv_path = REPORT_DIR / "summary_cross_stock.csv"
        df.to_csv(csv_path, index=False, encoding="utf-8-sig")
        print(f"\nOK 摘要：{csv_path}")
        print(df.to_string(index=False))

    print("\nOK 跨股票訓練完成")
    print(f"  模型儲存於：{CROSS_SAVED_DIR}")


if __name__ == "__main__":
    main()
