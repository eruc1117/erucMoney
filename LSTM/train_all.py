"""
主訓練腳本：對所有股票執行 10 種 LSTM 模型訓練，並輸出結果

用法：
    python train_all.py                     # 訓練所有股票、所有模型
    python train_all.py --stocks 2330 2317  # 僅訓練指定股票
    python train_all.py --models m01 m02    # 僅訓練指定模型
    python train_all.py --skip-report       # 不產生 HTML 報告
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

import tensorflow as tf
from config import (EPOCHS, BATCH_SIZE, PATIENCE, LOOKBACK, FORECAST_STEPS,
                    RESULTS_DIR, SAVED_DIR, MODEL_NAMES, MC_SAMPLES)
from data_loader import (get_all_stocks, prepare_single_feature,
                         prepare_multi_feature, load_prices, load_full,
                         prepare_single_logreturn, prepare_logreturn_enhanced)
from features import build_technical_features, TECHNICAL_COLS
from evaluate import (compute_metrics, plot_predictions, plot_loss,
                      inverse_transform_1d)
from models import MODEL_BUILDERS
from models.m08_mc_dropout import mc_predict
from models.m09_technical   import build as build_m09
from models.m10_ensemble    import ensemble_predict, dynamic_ensemble_predict
from sklearn.preprocessing import MinMaxScaler


# ── 工具函式 ────────────────────────────────────────────────────────────────
def callbacks():
    return [
        EarlyStopping(monitor="val_loss", patience=PATIENCE,
                      restore_best_weights=True, verbose=0),
        ReduceLROnPlateau(monitor="val_loss", factor=0.5,
                          patience=7, min_lr=1e-6, verbose=0),
    ]


# ── IMP-005：方向準確率 EarlyStopping ─────────────────────────────────────────

class DirectionalAccuracyCallback(tf.keras.callbacks.Callback):
    """
    IMP-005：在每個 Epoch 結束後計算驗證集方向準確率（Directional Accuracy, DA），
    當 DA 不再改善時提前停止，使訓練目標與交易實用性一致。

    適用於 log_return 預測（z-score 或 MinMax 正規化均可）：
    - z-score：sign(y_norm) 直接對應漲跌方向
    - MinMax：以 midpoint（0 映射後的位置）比較

    Parameters
    ----------
    X_val      : 驗證集輸入
    y_val      : 驗證集目標（正規化後）
    patience   : DA 未改善的容忍 epoch 數
    midpoint   : MinMax 模式下 log_return=0 對應的正規化值（預設 None → z-score 模式）
    """
    def __init__(self, X_val: np.ndarray, y_val: np.ndarray,
                 patience: int = 10, midpoint: float = None):
        super().__init__()
        self.X_val    = X_val
        self.y_val    = y_val.flatten()
        self.patience = patience
        self.midpoint = midpoint   # None = z-score 模式
        self.best_da  = -np.inf
        self.wait     = 0
        self.best_weights = None

    def on_epoch_end(self, epoch, logs=None):
        y_pred = self.model.predict(self.X_val, verbose=0).flatten()

        if self.midpoint is None:
            # z-score 模式：sign 直接比較
            da = float(np.mean(np.sign(y_pred) == np.sign(self.y_val)))
        else:
            # MinMax 模式：以 midpoint 為閾值
            da = float(np.mean(
                (y_pred > self.midpoint) == (self.y_val > self.midpoint)
            ))

        logs = logs or {}
        logs["val_dir_acc"] = da

        if da > self.best_da:
            self.best_da = da
            self.wait    = 0
            self.best_weights = self.model.get_weights()
        else:
            self.wait += 1
            if self.wait >= self.patience:
                self.model.stop_training = True
                if self.best_weights is not None:
                    self.model.set_weights(self.best_weights)


def callbacks_improved(X_val: np.ndarray, y_val: np.ndarray,
                        midpoint: float = None):
    """
    IMP-005：以方向準確率為主要 EarlyStopping 監控指標，
    搭配 ReduceLROnPlateau（val_loss）動態調降學習率。
    """
    return [
        DirectionalAccuracyCallback(X_val, y_val,
                                    patience=PATIENCE, midpoint=midpoint),
        ReduceLROnPlateau(monitor="val_loss", factor=0.5,
                          patience=7, min_lr=1e-6, verbose=0),
    ]


# ── IMP-001+002+003+005：M01 改進版訓練 ────────────────────────────────────────

def logreturn_to_price(y_norm: np.ndarray, meta, last_close: np.ndarray,
                        use_zscore: bool, target_col_idx: int = 0) -> np.ndarray:
    """
    將正規化的 log_return 預測值反轉換為絕對收盤價。

    use_zscore=True  : meta 為 norm_params_te (N, F, 2)
    use_zscore=False : meta 為 scalers dict，取 scalers["log_return"]
    """
    y_flat = y_norm.flatten()
    if use_zscore:
        lr_mean = meta[:, target_col_idx, 0]
        lr_std  = meta[:, target_col_idx, 1]
        log_ret = y_flat * lr_std + lr_mean
    else:
        sc      = meta["log_return"]
        log_ret = sc.inverse_transform(y_flat.reshape(-1, 1)).flatten()
    return last_close * np.exp(log_ret)


def train_m01_improved(stock_id: str, use_zscore: bool = True):
    """
    IMP-001+002+003+005 組合：
    - Log return 預測目標（IMP-001）
    - 10 特徵輸入（IMP-002）
    - Rolling Z-score 正規化（IMP-003，use_zscore=True）
    - 方向準確率 EarlyStopping（IMP-005）

    Returns: {"metrics": {...}, "y_true": array, "y_pred": array}
    """
    model_key = "m01_vanilla"

    result = prepare_logreturn_enhanced(stock_id, lookback=LOOKBACK,
                                         use_zscore=use_zscore)
    if result is None:
        return None

    splits, meta, last_close_te, cols = result
    X_tr, y_tr, X_val, y_val, X_te, y_te = splits

    if len(X_tr) < 10:
        return None

    input_shape = (X_tr.shape[1], X_tr.shape[2])   # (lookback, n_features)
    model = MODEL_BUILDERS[model_key](input_shape)

    # IMP-005：以方向準確率為 EarlyStopping 指標
    midpoint = None if use_zscore else 0.5
    cbs = callbacks_improved(X_val, y_val, midpoint=midpoint)

    model.fit(
        X_tr, y_tr,
        validation_data=(X_val, y_val),
        epochs=EPOCHS, batch_size=BATCH_SIZE,
        callbacks=cbs, verbose=0,
    )

    y_pred_norm = model.predict(X_te, verbose=0)
    target_col  = cols.index("log_return") if "log_return" in cols else 0

    y_true = logreturn_to_price(y_te,         meta, last_close_te, use_zscore, target_col)
    y_pred = logreturn_to_price(y_pred_norm,  meta, last_close_te, use_zscore, target_col)

    metrics = compute_metrics(y_true, y_pred)

    # 儲存模型（與原 m01 分開，避免覆蓋）
    save_dir = SAVED_DIR / model_key
    save_dir.mkdir(parents=True, exist_ok=True)
    suffix = "improved_zscore" if use_zscore else "improved_minmax"
    model.save(str(save_dir / f"{stock_id}_{suffix}.keras"))

    # 儲存結果
    res_dir = RESULTS_DIR / f"{model_key}_improved" / stock_id
    res_dir.mkdir(parents=True, exist_ok=True)
    with open(res_dir / "metrics.json", "w", encoding="utf-8") as f:
        import json
        json.dump({**metrics, "imp_flags": "IMP001+002+003+005",
                   "use_zscore": use_zscore, "n_features": len(cols)}, f, indent=2)

    plot_predictions(y_true, y_pred, stock_id,
                     f"{model_key}_improved", f"M01 Improved ({suffix})")

    return {"metrics": metrics, "y_true": y_true, "y_pred": y_pred}


def save_metrics(metrics: dict, stock_id: str, model_key: str):
    out_dir = RESULTS_DIR / model_key / stock_id
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "metrics.json", "w", encoding="utf-8") as f:
        json.dump(metrics, f, ensure_ascii=False, indent=2)


def save_preds(y_true, y_pred, stock_id, model_key, y_std=None):
    out_dir = RESULTS_DIR / model_key / stock_id
    out_dir.mkdir(parents=True, exist_ok=True)
    d = {"y_true": y_true.tolist(), "y_pred": y_pred.tolist()}
    if y_std is not None:
        d["y_std"] = y_std.tolist()
    with open(out_dir / "predictions.json", "w") as f:
        json.dump(d, f)


# ── 單特徵訓練（M01~M03）────────────────────────────────────────────────────
def train_single_feature(stock_id: str, model_key: str):
    result = prepare_single_feature(stock_id, lookback=LOOKBACK)
    if result is None:
        return None

    splits, scaler = result
    X_tr, y_tr, X_val, y_val, X_te, y_te = splits

    if len(X_tr) < 10:
        return None

    input_shape = (X_tr.shape[1], X_tr.shape[2])
    model = MODEL_BUILDERS[model_key](input_shape)

    history = model.fit(
        X_tr, y_tr, validation_data=(X_val, y_val),
        epochs=EPOCHS, batch_size=BATCH_SIZE,
        callbacks=callbacks(), verbose=0,
    )

    y_pred_s = model.predict(X_te, verbose=0).flatten()
    y_true   = inverse_transform_1d(y_te, scaler)
    y_pred   = inverse_transform_1d(y_pred_s.reshape(-1, 1), scaler)

    metrics = compute_metrics(y_true, y_pred)
    save_metrics(metrics, stock_id, model_key)
    save_preds(y_true, y_pred, stock_id, model_key)
    plot_predictions(y_true, y_pred, stock_id, model_key,
                     MODEL_NAMES[model_key])
    plot_loss(history, stock_id, model_key, MODEL_NAMES[model_key])

    # 儲存模型
    (SAVED_DIR / model_key).mkdir(parents=True, exist_ok=True)
    model.save(str(SAVED_DIR / model_key / f"{stock_id}.keras"))

    return {"metrics": metrics, "y_true": y_true, "y_pred": y_pred}


# ── M04 Attention：close + volume ─────────────────────────────────────────
def train_m04(stock_id: str):
    model_key = "m04_attention"
    res = prepare_multi_feature(
        stock_id, ["close_price", "volume"], lookback=LOOKBACK)
    if res is None:
        return None

    splits, scalers = res
    X_tr, y_tr, X_val, y_val, X_te, y_te = splits
    if len(X_tr) < 10:
        return None

    model   = MODEL_BUILDERS[model_key]((X_tr.shape[1], X_tr.shape[2]))
    history = model.fit(X_tr, y_tr, validation_data=(X_val, y_val),
                        epochs=EPOCHS, batch_size=BATCH_SIZE,
                        callbacks=callbacks(), verbose=0)

    y_pred_s = model.predict(X_te, verbose=0).flatten()
    sc_close = scalers["close_price"]
    y_true   = inverse_transform_1d(y_te, sc_close)
    y_pred   = inverse_transform_1d(y_pred_s.reshape(-1, 1), sc_close)

    metrics = compute_metrics(y_true, y_pred)
    save_metrics(metrics, stock_id, model_key)
    save_preds(y_true, y_pred, stock_id, model_key)
    plot_predictions(y_true, y_pred, stock_id, model_key, MODEL_NAMES[model_key])
    plot_loss(history, stock_id, model_key, MODEL_NAMES[model_key])
    (SAVED_DIR / model_key).mkdir(parents=True, exist_ok=True)
    model.save(str(SAVED_DIR / model_key / f"{stock_id}.keras"))
    return {"metrics": metrics, "y_true": y_true, "y_pred": y_pred}


# ── M05 CNN-LSTM：OHLCV ────────────────────────────────────────────────────
def train_m05(stock_id: str):
    model_key = "m05_cnn_lstm"
    cols = ["close_price", "open_price", "high_price", "low_price", "volume"]
    res  = prepare_multi_feature(stock_id, cols, lookback=LOOKBACK)
    if res is None:
        return None

    splits, scalers = res
    X_tr, y_tr, X_val, y_val, X_te, y_te = splits
    if len(X_tr) < 10:
        return None

    model   = MODEL_BUILDERS[model_key]((X_tr.shape[1], X_tr.shape[2]))
    history = model.fit(X_tr, y_tr, validation_data=(X_val, y_val),
                        epochs=EPOCHS, batch_size=BATCH_SIZE,
                        callbacks=callbacks(), verbose=0)

    sc_close = scalers["close_price"]
    y_pred_s = model.predict(X_te, verbose=0).flatten()
    y_true   = inverse_transform_1d(y_te, sc_close)
    y_pred   = inverse_transform_1d(y_pred_s.reshape(-1, 1), sc_close)

    metrics = compute_metrics(y_true, y_pred)
    save_metrics(metrics, stock_id, model_key)
    save_preds(y_true, y_pred, stock_id, model_key)
    plot_predictions(y_true, y_pred, stock_id, model_key, MODEL_NAMES[model_key])
    plot_loss(history, stock_id, model_key, MODEL_NAMES[model_key])
    (SAVED_DIR / model_key).mkdir(parents=True, exist_ok=True)
    model.save(str(SAVED_DIR / model_key / f"{stock_id}.keras"))
    return {"metrics": metrics, "y_true": y_true, "y_pred": y_pred}


# ── M06 Multi-feature：OHLCV + 籌碼 ───────────────────────────────────────
def train_m06(stock_id: str):
    model_key = "m06_multifeature"
    from models.m06_multifeature import FEATURE_COLS
    res = prepare_multi_feature(stock_id, FEATURE_COLS,
                                lookback=LOOKBACK, use_chips=True)
    if res is None:
        return None

    splits, scalers = res
    X_tr, y_tr, X_val, y_val, X_te, y_te = splits
    if len(X_tr) < 10:
        return None

    model   = MODEL_BUILDERS[model_key]((X_tr.shape[1], X_tr.shape[2]))
    history = model.fit(X_tr, y_tr, validation_data=(X_val, y_val),
                        epochs=EPOCHS, batch_size=BATCH_SIZE,
                        callbacks=callbacks(), verbose=0)

    sc_close = scalers["close_price"]
    y_pred_s = model.predict(X_te, verbose=0).flatten()
    y_true   = inverse_transform_1d(y_te, sc_close)
    y_pred   = inverse_transform_1d(y_pred_s.reshape(-1, 1), sc_close)

    metrics = compute_metrics(y_true, y_pred)
    save_metrics(metrics, stock_id, model_key)
    save_preds(y_true, y_pred, stock_id, model_key)
    plot_predictions(y_true, y_pred, stock_id, model_key, MODEL_NAMES[model_key])
    plot_loss(history, stock_id, model_key, MODEL_NAMES[model_key])
    (SAVED_DIR / model_key).mkdir(parents=True, exist_ok=True)
    model.save(str(SAVED_DIR / model_key / f"{stock_id}.keras"))
    return {"metrics": metrics, "y_true": y_true, "y_pred": y_pred}


# ── M07 Seq2Seq ────────────────────────────────────────────────────────────
def train_m07(stock_id: str):
    model_key = "m07_seq2seq"
    from data_loader import prepare_multi_feature as pmf, split_sequences
    from data_loader import load_prices, make_sequences

    df = load_prices(stock_id)
    if df is None or len(df) < LOOKBACK + FORECAST_STEPS + 10:
        return None

    close  = df["close_price"].values.reshape(-1, 1)
    scaler = MinMaxScaler()
    scaled = scaler.fit_transform(close)

    X, y = make_sequences(scaled, lookback=LOOKBACK, forecast=FORECAST_STEPS)
    # y: (N, FORECAST_STEPS, 1) needed for seq2seq
    y = y.reshape(y.shape[0], FORECAST_STEPS, 1)

    from data_loader import split_sequences
    splits = split_sequences(X, y)
    X_tr, y_tr, X_val, y_val, X_te, y_te = splits

    if len(X_tr) < 10:
        return None

    model = MODEL_BUILDERS[model_key]((X_tr.shape[1], X_tr.shape[2]),
                                      forecast_steps=FORECAST_STEPS)
    history = model.fit(X_tr, y_tr, validation_data=(X_val, y_val),
                        epochs=EPOCHS, batch_size=BATCH_SIZE,
                        callbacks=callbacks(), verbose=0)

    y_pred_s = model.predict(X_te, verbose=0)  # (N, steps, 1)
    # 取第一步預測作為指標計算（與其他模型對齊）
    y_pred_1 = y_pred_s[:, 0, 0]
    y_te_1   = y_te[:, 0, 0]
    y_true   = inverse_transform_1d(y_te_1.reshape(-1, 1), scaler)
    y_pred   = inverse_transform_1d(y_pred_1.reshape(-1, 1), scaler)

    metrics = compute_metrics(y_true, y_pred)
    save_metrics(metrics, stock_id, model_key)
    save_preds(y_true, y_pred, stock_id, model_key)
    plot_predictions(y_true, y_pred, stock_id, model_key, MODEL_NAMES[model_key])
    plot_loss(history, stock_id, model_key, MODEL_NAMES[model_key])
    (SAVED_DIR / model_key).mkdir(parents=True, exist_ok=True)
    model.save(str(SAVED_DIR / model_key / f"{stock_id}.keras"))
    return {"metrics": metrics, "y_true": y_true, "y_pred": y_pred}


# ── M08 MC Dropout ─────────────────────────────────────────────────────────
def train_m08(stock_id: str):
    model_key = "m08_mc_dropout"
    res = prepare_single_feature(stock_id, lookback=LOOKBACK)
    if res is None:
        return None

    splits, scaler = res
    X_tr, y_tr, X_val, y_val, X_te, y_te = splits
    if len(X_tr) < 10:
        return None

    model   = MODEL_BUILDERS[model_key]((X_tr.shape[1], X_tr.shape[2]))
    history = model.fit(X_tr, y_tr, validation_data=(X_val, y_val),
                        epochs=EPOCHS, batch_size=BATCH_SIZE,
                        callbacks=callbacks(), verbose=0)

    mean_s, std_s = mc_predict(model, X_te, n_samples=MC_SAMPLES)
    y_true  = inverse_transform_1d(y_te, scaler)
    y_pred  = inverse_transform_1d(mean_s.reshape(-1, 1), scaler)
    y_std   = (scaler.data_max_[0] - scaler.data_min_[0]) * std_s

    metrics = compute_metrics(y_true, y_pred)
    save_metrics(metrics, stock_id, model_key)
    save_preds(y_true, y_pred, stock_id, model_key, y_std=y_std)
    plot_predictions(y_true, y_pred, stock_id, model_key,
                     MODEL_NAMES[model_key], y_std=y_std)
    plot_loss(history, stock_id, model_key, MODEL_NAMES[model_key])
    (SAVED_DIR / model_key).mkdir(parents=True, exist_ok=True)
    model.save(str(SAVED_DIR / model_key / f"{stock_id}.keras"))
    return {"metrics": metrics, "y_true": y_true, "y_pred": y_pred}


# ── M09 Technical Indicators ───────────────────────────────────────────────
def train_m09(stock_id: str):
    model_key = "m09_technical"
    from data_loader import load_prices, make_sequences, split_sequences

    df = load_prices(stock_id)
    if df is None or len(df) < 60:
        return None

    df_feat = build_technical_features(df)
    cols_ok = [c for c in TECHNICAL_COLS if c in df_feat.columns]
    df_feat = df_feat[cols_ok].fillna(0)

    scalers, parts = {}, []
    for col in cols_ok:
        sc = MinMaxScaler()
        parts.append(sc.fit_transform(df_feat[[col]]))
        scalers[col] = sc

    scaled = np.hstack(parts)
    X, y   = make_sequences(scaled, lookback=LOOKBACK, forecast=1)
    y      = y.reshape(-1, 1)
    splits = split_sequences(X, y)
    X_tr, y_tr, X_val, y_val, X_te, y_te = splits

    if len(X_tr) < 10:
        return None

    model   = build_m09((X_tr.shape[1], X_tr.shape[2]))
    history = model.fit(X_tr, y_tr, validation_data=(X_val, y_val),
                        epochs=EPOCHS, batch_size=BATCH_SIZE,
                        callbacks=callbacks(), verbose=0)

    sc_close = scalers["close_price"]
    y_pred_s = model.predict(X_te, verbose=0).flatten()
    y_true   = inverse_transform_1d(y_te, sc_close)
    y_pred   = inverse_transform_1d(y_pred_s.reshape(-1, 1), sc_close)

    metrics = compute_metrics(y_true, y_pred)
    save_metrics(metrics, stock_id, model_key)
    save_preds(y_true, y_pred, stock_id, model_key)
    plot_predictions(y_true, y_pred, stock_id, model_key, MODEL_NAMES[model_key])
    plot_loss(history, stock_id, model_key, MODEL_NAMES[model_key])
    (SAVED_DIR / model_key).mkdir(parents=True, exist_ok=True)
    model.save(str(SAVED_DIR / model_key / f"{stock_id}.keras"))
    return {"metrics": metrics, "y_true": y_true, "y_pred": y_pred}


# ── M10 Ensemble ───────────────────────────────────────────────────────────
def run_m10(stock_id: str, base_results: dict):
    model_key = "m10_ensemble"
    preds = {}
    for k in ["m01_vanilla", "m02_stacked", "m03_bidirectional"]:
        if base_results.get(k) and base_results[k].get("y_pred") is not None:
            preds[k] = base_results[k]["y_pred"]

    if len(preds) < 2:
        return None

    # y_true 取 base models 共同測試集（長度取最小）
    y_trues = [base_results[k]["y_true"] for k in preds]
    min_len = min(len(t) for t in y_trues)
    for k in preds:
        preds[k] = np.array(preds[k])[:min_len]
    y_true = np.array(y_trues[0])[:min_len]

    y_pred  = ensemble_predict(preds)
    metrics = compute_metrics(y_true, y_pred)
    save_metrics(metrics, stock_id, model_key)
    save_preds(y_true, y_pred, stock_id, model_key)
    plot_predictions(y_true, y_pred, stock_id, model_key, MODEL_NAMES[model_key])
    return {"metrics": metrics, "y_true": y_true, "y_pred": y_pred}


# ── 模型訓練分派 ────────────────────────────────────────────────────────────
def train_model(stock_id: str, model_key: str, base_results: dict = None):
    if model_key in ("m01_vanilla", "m02_stacked", "m03_bidirectional"):
        return train_single_feature(stock_id, model_key)
    elif model_key == "m04_attention":
        return train_m04(stock_id)
    elif model_key == "m05_cnn_lstm":
        return train_m05(stock_id)
    elif model_key == "m06_multifeature":
        return train_m06(stock_id)
    elif model_key == "m07_seq2seq":
        return train_m07(stock_id)
    elif model_key == "m08_mc_dropout":
        return train_m08(stock_id)
    elif model_key == "m09_technical":
        return train_m09(stock_id)
    elif model_key == "m10_ensemble":
        return run_m10(stock_id, base_results or {})
    return None


# ── 主流程 ─────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="LSTM 模型訓練")
    parser.add_argument("--stocks",      nargs="*", default=None)
    parser.add_argument("--models",      nargs="*", default=None)
    parser.add_argument("--skip-report", action="store_true")
    args = parser.parse_args()

    all_stocks = get_all_stocks()
    stocks = args.stocks if args.stocks else all_stocks
    stocks = [s for s in stocks if s in all_stocks]

    all_model_keys = list(MODEL_NAMES.keys())
    models = args.models if args.models else all_model_keys
    # 確保 m10 最後執行（依賴 m01~m03）
    base_keys = [k for k in models if k != "m10_ensemble"]
    run_keys  = base_keys + (["m10_ensemble"] if "m10_ensemble" in models else [])

    print(f"\n{'='*60}")
    print(f"  LSTM 訓練任務")
    print(f"  股票數：{len(stocks)}  模型數：{len(run_keys)}")
    print(f"  股票：{', '.join(stocks)}")
    print(f"{'='*60}\n")

    all_results = {}   # { stock_id: { model_key: result } }
    summary = []

    for stock_id in stocks:
        print(f"▶ [{stock_id}] 開始訓練...")
        stock_res = {}

        for model_key in run_keys:
            try:
                print(f"  [{stock_id}] {MODEL_NAMES[model_key]} ...", end=" ", flush=True)
                res = train_model(stock_id, model_key,
                                  base_results=stock_res)
                if res:
                    stock_res[model_key] = res
                    m = res["metrics"]
                    print(f"MAE={m['MAE']:.2f}  RMSE={m['RMSE']:.2f}"
                          f"  MAPE={m['MAPE']:.2f}%  DA={m['DA']:.1f}%")
                    summary.append({
                        "stock_id":   stock_id,
                        "model_key":  model_key,
                        "model_name": MODEL_NAMES[model_key],
                        **m,
                    })
                else:
                    print("跳過（資料不足）")
            except Exception:
                print("失敗")
                traceback.print_exc()

        all_results[stock_id] = stock_res

    # ── 產生摘要 CSV ──────────────────────────────────────────────────────
    if summary:
        REPORT_DIR = RESULTS_DIR.parent / "report"
        REPORT_DIR.mkdir(exist_ok=True)
        df_sum = pd.DataFrame(summary)
        df_sum.to_csv(REPORT_DIR / "summary.csv", index=False, encoding="utf-8-sig")
        print(f"\nOK 摘要已儲存：{REPORT_DIR / 'summary.csv'}")

    # ── 產生 HTML 報告 ────────────────────────────────────────────────────
    if not args.skip_report and summary:
        try:
            from report_generator import generate_report
            path = generate_report(summary)
            print(f"OK HTML 報告：{path}")
        except Exception:
            traceback.print_exc()

    print("\nOK 全部訓練完成")


if __name__ == "__main__":
    main()
