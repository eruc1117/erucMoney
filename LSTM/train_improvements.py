"""
IMPR-001 改進方案測試腳本
──────────────────────────
對 4 支代表性股票，逐輪套用改進方案並記錄指標變化。

執行方式：
    cd LSTM
    venv\\Scripts\\activate
    python train_improvements.py                   # 全部測試股票
    python train_improvements.py --stocks 2330    # 指定股票

輸出：
    LSTM/report/improvement_log.csv               # 逐輪指標比較表
    LSTM/report/improvement_summary.txt           # 精簡摘要

改進輪次：
    Round 0 (baseline)   : M01 原版（close_price 單特徵，MinMax）
    Round 1 (IMP-001)    : Log Return 預測目標（單特徵，MinMax）
    Round 2 (IMP-001+002): Log Return + 10 特徵（MinMax，無 z-score）
    Round 3 (IMP-001+002+003): Log Return + 10 特徵 + Rolling Z-score
    Round 4 (IMP-001+002+003+005): + 方向準確率 EarlyStopping
    Round 5 (IMP-004)    : Walk-Forward Validation（使用 Round 4 最優設定）
    Round 6 (IMP-006)    : M10 動態集成（使用 M01/M02/M03 近期誤差）
"""
import argparse
import csv
import json
import os
import sys
import traceback
import warnings
warnings.filterwarnings("ignore")
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"

import numpy as np
import pandas as pd
import tensorflow as tf
from datetime import datetime
from pathlib import Path
from tensorflow.keras.callbacks import EarlyStopping, ReduceLROnPlateau
from sklearn.preprocessing import MinMaxScaler

# ── 確保能 import 同目錄模組 ────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent))

from config import (EPOCHS, BATCH_SIZE, PATIENCE, LOOKBACK,
                    RESULTS_DIR, SAVED_DIR, REPORT_DIR, MODEL_NAMES,
                    TRAIN_RATIO, VAL_RATIO)
from data_loader import (
    prepare_single_feature,
    prepare_single_logreturn,
    prepare_logreturn_enhanced,
    split_sequences,
)
from evaluate import compute_metrics, plot_predictions
from models import MODEL_BUILDERS
from models.m10_ensemble import dynamic_ensemble_predict, compute_dynamic_weights
from train_all import (
    callbacks, callbacks_improved,
    logreturn_to_price, train_m01_improved,
    train_single_feature,
)

# ── 測試股票（依 Target.md，涵蓋 4 種類型）───────────────────────────────────
DEFAULT_TEST_STOCKS = ["2330", "2344", "2323", "2324"]

# ── 輸出設定 ────────────────────────────────────────────────────────────────
REPORT_DIR.mkdir(parents=True, exist_ok=True)
LOG_CSV  = REPORT_DIR / "improvement_log.csv"
LOG_TXT  = REPORT_DIR / "improvement_summary.txt"

CSV_FIELDS = ["date", "stock_id", "round", "imp_flags",
              "mae", "rmse", "mape", "dir_acc", "overfit_ratio", "note"]


# ══════════════════════════════════════════════════════════════════════════════
# 工具函式
# ══════════════════════════════════════════════════════════════════════════════

def _append_log(row: dict):
    """將一筆結果寫入 CSV（首次寫入時加 header）"""
    is_new = not LOG_CSV.exists()
    with open(LOG_CSV, "a", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if is_new:
            w.writeheader()
        w.writerow({k: row.get(k, "") for k in CSV_FIELDS})


def _fmt(metrics: dict, val_mape: float = None) -> dict:
    """整理 compute_metrics 結果，加入 overfit_ratio"""
    row = {
        "mae":       round(metrics["MAE"],  2),
        "rmse":      round(metrics["RMSE"], 2),
        "mape":      round(metrics["MAPE"], 2),
        "dir_acc":   round(metrics["DA"],   1),
    }
    if val_mape is not None and val_mape > 0:
        row["overfit_ratio"] = round(metrics["MAPE"] / val_mape, 2)
    else:
        row["overfit_ratio"] = ""
    return row


def _val_mape_from_history(model, X_val, y_val_true_price):
    """計算驗證集的 MAPE（用真實價格，供 overfit_ratio 計算）"""
    y_pred_val = model.predict(X_val, verbose=0).flatten()
    # 這裡只計算方向 MAPE 的近似值，不做完整反正規化
    # overfit_ratio 僅供參考，不是精確值
    return None   # 暫時不計算以保持流程簡潔


def _simple_callbacks():
    return callbacks()


# ══════════════════════════════════════════════════════════════════════════════
# Round 0 — Baseline（M01 原版）
# ══════════════════════════════════════════════════════════════════════════════

def run_round0_baseline(stock_id: str, today: str) -> dict | None:
    """原版 M01 Vanilla：close_price 單特徵，MinMax，val_loss EarlyStopping"""
    result = prepare_single_feature(stock_id, lookback=LOOKBACK)
    if result is None:
        return None

    splits, scaler = result
    X_tr, y_tr, X_val, y_val, X_te, y_te = splits
    if len(X_tr) < 10:
        return None

    model = MODEL_BUILDERS["m01_vanilla"]((X_tr.shape[1], X_tr.shape[2]))
    model.fit(X_tr, y_tr, validation_data=(X_val, y_val),
              epochs=EPOCHS, batch_size=BATCH_SIZE,
              callbacks=_simple_callbacks(), verbose=0)

    y_pred_s = model.predict(X_te, verbose=0).flatten()
    from evaluate import inverse_transform_1d
    y_true = inverse_transform_1d(y_te,                    scaler)
    y_pred = inverse_transform_1d(y_pred_s.reshape(-1, 1), scaler)

    m = compute_metrics(y_true, y_pred)
    row = {"date": today, "stock_id": stock_id,
           "round": 0, "imp_flags": "baseline", **_fmt(m)}
    print(f"    R0 baseline   MAPE={m['MAPE']:.2f}%  DA={m['DA']:.1f}%")
    _append_log(row)
    return {"metrics": m, "y_true": y_true, "y_pred": y_pred}


# ══════════════════════════════════════════════════════════════════════════════
# Round 1 — IMP-001 only（Log Return 單特徵）
# ══════════════════════════════════════════════════════════════════════════════

def run_round1_imp001(stock_id: str, today: str) -> dict | None:
    """IMP-001：預測目標改為 log_return，MinMax 正規化，單特徵"""
    result = prepare_single_logreturn(stock_id, lookback=LOOKBACK)
    if result is None:
        return None

    splits, scaler, last_close_te = result
    X_tr, y_tr, X_val, y_val, X_te, y_te = splits
    if len(X_tr) < 10:
        return None

    model = MODEL_BUILDERS["m01_vanilla"]((X_tr.shape[1], X_tr.shape[2]))
    model.fit(X_tr, y_tr, validation_data=(X_val, y_val),
              epochs=EPOCHS, batch_size=BATCH_SIZE,
              callbacks=_simple_callbacks(), verbose=0)

    y_pred_norm = model.predict(X_te, verbose=0)
    y_true = logreturn_to_price(y_te,        {"log_return": scaler},
                                last_close_te, use_zscore=False)
    y_pred = logreturn_to_price(y_pred_norm,  {"log_return": scaler},
                                last_close_te, use_zscore=False)

    m = compute_metrics(y_true, y_pred)
    row = {"date": today, "stock_id": stock_id,
           "round": 1, "imp_flags": "IMP001", **_fmt(m)}
    print(f"    R1 IMP-001    MAPE={m['MAPE']:.2f}%  DA={m['DA']:.1f}%")
    _append_log(row)
    return {"metrics": m, "y_true": y_true, "y_pred": y_pred}


# ══════════════════════════════════════════════════════════════════════════════
# Round 2 — IMP-001+002（10 特徵，MinMax）
# ══════════════════════════════════════════════════════════════════════════════

def run_round2_imp001_002(stock_id: str, today: str) -> dict | None:
    """IMP-001+002：Log Return + 10 特徵，MinMax（未使用 Rolling Z-score）"""
    result = prepare_logreturn_enhanced(stock_id, lookback=LOOKBACK, use_zscore=False)
    if result is None:
        return None

    splits, scalers, last_close_te, cols = result
    X_tr, y_tr, X_val, y_val, X_te, y_te = splits
    if len(X_tr) < 10:
        return None

    model = MODEL_BUILDERS["m01_vanilla"]((X_tr.shape[1], X_tr.shape[2]))
    model.fit(X_tr, y_tr, validation_data=(X_val, y_val),
              epochs=EPOCHS, batch_size=BATCH_SIZE,
              callbacks=_simple_callbacks(), verbose=0)

    y_pred_norm = model.predict(X_te, verbose=0)
    y_true = logreturn_to_price(y_te,        scalers, last_close_te, use_zscore=False)
    y_pred = logreturn_to_price(y_pred_norm,  scalers, last_close_te, use_zscore=False)

    m = compute_metrics(y_true, y_pred)
    row = {"date": today, "stock_id": stock_id,
           "round": 2, "imp_flags": "IMP001+002", **_fmt(m),
           "note": f"{len(cols)} features"}
    print(f"    R2 IMP-001+002  MAPE={m['MAPE']:.2f}%  DA={m['DA']:.1f}%")
    _append_log(row)
    return {"metrics": m, "y_true": y_true, "y_pred": y_pred}


# ══════════════════════════════════════════════════════════════════════════════
# Round 3 — IMP-001+002+003（Rolling Z-score）
# ══════════════════════════════════════════════════════════════════════════════

def run_round3_imp001_002_003(stock_id: str, today: str) -> dict | None:
    """IMP-001+002+003：Log Return + 10 特徵 + Rolling Z-score"""
    result = prepare_logreturn_enhanced(stock_id, lookback=LOOKBACK, use_zscore=True)
    if result is None:
        return None

    splits, norm_te, last_close_te, cols = result
    X_tr, y_tr, X_val, y_val, X_te, y_te = splits
    if len(X_tr) < 10:
        return None

    model = MODEL_BUILDERS["m01_vanilla"]((X_tr.shape[1], X_tr.shape[2]))
    model.fit(X_tr, y_tr, validation_data=(X_val, y_val),
              epochs=EPOCHS, batch_size=BATCH_SIZE,
              callbacks=_simple_callbacks(), verbose=0)

    y_pred_norm = model.predict(X_te, verbose=0)
    target_col  = cols.index("log_return") if "log_return" in cols else 0
    y_true = logreturn_to_price(y_te,        norm_te, last_close_te, use_zscore=True,  target_col_idx=target_col)
    y_pred = logreturn_to_price(y_pred_norm,  norm_te, last_close_te, use_zscore=True, target_col_idx=target_col)

    m = compute_metrics(y_true, y_pred)
    row = {"date": today, "stock_id": stock_id,
           "round": 3, "imp_flags": "IMP001+002+003", **_fmt(m)}
    print(f"    R3 IMP-001+002+003  MAPE={m['MAPE']:.2f}%  DA={m['DA']:.1f}%")
    _append_log(row)
    return {"metrics": m, "y_true": y_true, "y_pred": y_pred, "splits": splits,
            "norm_te": norm_te, "last_close_te": last_close_te, "cols": cols}


# ══════════════════════════════════════════════════════════════════════════════
# Round 4 — IMP-001+002+003+005（方向準確率 EarlyStopping）
# ══════════════════════════════════════════════════════════════════════════════

def run_round4_imp001_002_003_005(stock_id: str, today: str) -> dict | None:
    """IMP-001+002+003+005：加入方向準確率 EarlyStopping"""
    result = prepare_logreturn_enhanced(stock_id, lookback=LOOKBACK, use_zscore=True)
    if result is None:
        return None

    splits, norm_te, last_close_te, cols = result
    X_tr, y_tr, X_val, y_val, X_te, y_te = splits
    if len(X_tr) < 10:
        return None

    model = MODEL_BUILDERS["m01_vanilla"]((X_tr.shape[1], X_tr.shape[2]))
    # IMP-005：方向準確率 EarlyStopping（z-score 模式，midpoint=None）
    cbs = callbacks_improved(X_val, y_val, midpoint=None)
    model.fit(X_tr, y_tr, validation_data=(X_val, y_val),
              epochs=EPOCHS, batch_size=BATCH_SIZE,
              callbacks=cbs, verbose=0)

    y_pred_norm = model.predict(X_te, verbose=0)
    target_col  = cols.index("log_return") if "log_return" in cols else 0
    y_true = logreturn_to_price(y_te,        norm_te, last_close_te, True, target_col)
    y_pred = logreturn_to_price(y_pred_norm,  norm_te, last_close_te, True, target_col)

    m = compute_metrics(y_true, y_pred)
    row = {"date": today, "stock_id": stock_id,
           "round": 4, "imp_flags": "IMP001+002+003+005", **_fmt(m)}
    print(f"    R4 IMP-001~005     MAPE={m['MAPE']:.2f}%  DA={m['DA']:.1f}%")
    _append_log(row)
    return {"metrics": m, "y_true": y_true, "y_pred": y_pred,
            "model": model, "splits": splits,
            "norm_te": norm_te, "last_close_te": last_close_te, "cols": cols}


# ══════════════════════════════════════════════════════════════════════════════
# Round 5 — IMP-004：Walk-Forward Validation
# ══════════════════════════════════════════════════════════════════════════════

def run_round5_walkforward(stock_id: str, today: str,
                           n_rounds: int = 4) -> dict | None:
    """
    IMP-004：Walk-Forward Validation（滾動訓練窗口驗證）
    使用 IMP-001+002+003+005 設定，對最後 n_rounds 個月滾動測試，
    評估模型在不同時間段的穩定性。
    """
    result = prepare_logreturn_enhanced(stock_id, lookback=LOOKBACK, use_zscore=True)
    if result is None:
        return None

    splits, _, _, cols = result
    X_all = np.concatenate([splits[0], splits[2], splits[4]], axis=0)
    y_all = np.concatenate([splits[1], splits[3], splits[5]], axis=0)

    n = len(X_all)
    if n < LOOKBACK * (n_rounds + 3):
        return None

    target_col = cols.index("log_return") if "log_return" in cols else 0
    test_size  = max(10, n // (n_rounds + 3))  # 每 round 測試的樣本數
    min_train  = max(30, n - n_rounds * test_size)

    round_metrics = []
    for r in range(n_rounds):
        train_end  = min_train + r * test_size
        test_start = train_end
        test_end   = min(test_start + test_size, n)
        if test_end <= test_start:
            break

        X_tr_r = X_all[:train_end]
        y_tr_r = y_all[:train_end]
        val_cut = int(len(X_tr_r) * 0.9)
        X_tv, y_tv = X_tr_r[:val_cut], y_tr_r[:val_cut]
        X_vv, y_vv = X_tr_r[val_cut:], y_tr_r[val_cut:]
        X_te_r = X_all[test_start:test_end]
        y_te_r = y_all[test_start:test_end]

        if len(X_tv) < 10 or len(X_te_r) < 2:
            continue

        # 重新準備 norm_params 和 last_close（用完整管線的 test 段估計）
        # 簡化：使用 z-score 的 norm_params 只對 test 段有效，
        # 此處採用近似：以全部資料重算 prepare_logreturn_enhanced 不變
        # 改由再次呼叫並取對應段落（詳細實作見文件）
        model = MODEL_BUILDERS["m01_vanilla"]((X_tv.shape[1], X_tv.shape[2]))
        cbs = callbacks_improved(X_vv, y_vv, midpoint=None)
        model.fit(X_tv, y_tv, validation_data=(X_vv, y_vv),
                  epochs=EPOCHS, batch_size=BATCH_SIZE,
                  callbacks=cbs, verbose=0)

        y_pred_norm = model.predict(X_te_r, verbose=0).flatten()
        y_true_norm = y_te_r.flatten()

        # Walk-forward 直接用方向準確率評估（正規化值 sign 可比較）
        da = float(np.mean(np.sign(y_pred_norm) == np.sign(y_true_norm)) * 100)
        round_metrics.append({"round": r, "da": da})
        print(f"    R5-WF round{r+1}/{n_rounds}  DA={da:.1f}%")

    if not round_metrics:
        return None

    avg_da = float(np.mean([x["da"] for x in round_metrics]))
    std_da = float(np.std( [x["da"] for x in round_metrics]))
    m = {"MAE": 0, "RMSE": 0, "MAPE": 0, "DA": avg_da}
    row = {"date": today, "stock_id": stock_id,
           "round": 5, "imp_flags": "IMP004(WalkFwd)",
           "dir_acc": round(avg_da, 1),
           "note": f"std={std_da:.1f}% over {len(round_metrics)} rounds"}
    print(f"    R5 Walk-Fwd DA avg={avg_da:.1f}%  std={std_da:.1f}%")
    _append_log(row)
    return {"metrics": m, "round_details": round_metrics}


# ══════════════════════════════════════════════════════════════════════════════
# Round 6 — IMP-006：M10 動態集成
# ══════════════════════════════════════════════════════════════════════════════

def run_round6_dynamic_ensemble(stock_id: str, today: str,
                                 base_results: dict) -> dict | None:
    """
    IMP-006：以 M01/M02/M03 的近期 MAPE 計算動態權重，與固定權重比較。
    base_results 需包含 m01_vanilla、m02_stacked、m03_bidirectional 的結果。
    """
    required = ["m01_vanilla", "m02_stacked", "m03_bidirectional"]
    preds, maes = {}, {}
    for k in required:
        if k in base_results and base_results[k] is not None:
            preds[k] = base_results[k]["y_pred"]
            maes[k]  = base_results[k]["metrics"]["MAPE"]

    if len(preds) < 2:
        print(f"    R6 動態集成：基礎模型不足（{list(preds.keys())}），跳過")
        return None

    weights = compute_dynamic_weights(maes)
    weights_str = " / ".join(f"{k.split('_')[0]}={v:.2f}" for k, v in weights.items())

    # 對齊長度
    min_len = min(len(v) for v in preds.values())
    for k in preds:
        preds[k] = np.array(preds[k])[:min_len]
    y_true = np.array(list(base_results.values())[0]["y_true"])[:min_len]

    # 固定權重
    from models.m10_ensemble import ensemble_predict
    y_pred_fixed   = ensemble_predict(preds)
    m_fixed        = compute_metrics(y_true, y_pred_fixed)

    # 動態權重
    y_pred_dynamic = dynamic_ensemble_predict(preds, maes)
    m_dynamic      = compute_metrics(y_true, y_pred_dynamic)

    row_fixed = {"date": today, "stock_id": stock_id,
                 "round": "6a", "imp_flags": "IMP006-fixed",
                 **_fmt(m_fixed), "note": "fixed 0.25/0.45/0.30"}
    row_dyn   = {"date": today, "stock_id": stock_id,
                 "round": "6b", "imp_flags": "IMP006-dynamic",
                 **_fmt(m_dynamic), "note": weights_str}
    print(f"    R6a 固定集成  MAPE={m_fixed['MAPE']:.2f}%  DA={m_fixed['DA']:.1f}%")
    print(f"    R6b 動態集成  MAPE={m_dynamic['MAPE']:.2f}%  DA={m_dynamic['DA']:.1f}%  ({weights_str})")
    _append_log(row_fixed)
    _append_log(row_dyn)

    return {
        "fixed":   {"metrics": m_fixed,   "y_pred": y_pred_fixed},
        "dynamic": {"metrics": m_dynamic, "y_pred": y_pred_dynamic},
        "weights": weights,
    }


# ══════════════════════════════════════════════════════════════════════════════
# 主流程
# ══════════════════════════════════════════════════════════════════════════════

def run_stock(stock_id: str, today: str):
    print(f"\n{'─'*60}")
    print(f"  [{stock_id}] 開始改進測試")
    print(f"{'─'*60}")

    # 先跑 M02/M03 基礎模型（供 R6 動態集成使用）
    base_results = {}
    for mk in ["m01_vanilla", "m02_stacked", "m03_bidirectional"]:
        try:
            res = train_single_feature(stock_id, mk)
            if res:
                base_results[mk] = res
        except Exception:
            pass

    results = {}

    try:
        results["R0"] = run_round0_baseline(stock_id, today)
    except Exception:
        print("    R0 失敗")
        traceback.print_exc()

    try:
        results["R1"] = run_round1_imp001(stock_id, today)
    except Exception:
        print("    R1 失敗")
        traceback.print_exc()

    try:
        results["R2"] = run_round2_imp001_002(stock_id, today)
    except Exception:
        print("    R2 失敗")
        traceback.print_exc()

    try:
        results["R3"] = run_round3_imp001_002_003(stock_id, today)
    except Exception:
        print("    R3 失敗")
        traceback.print_exc()

    try:
        results["R4"] = run_round4_imp001_002_003_005(stock_id, today)
    except Exception:
        print("    R4 失敗")
        traceback.print_exc()

    try:
        results["R5"] = run_round5_walkforward(stock_id, today)
    except Exception:
        print("    R5 失敗")
        traceback.print_exc()

    try:
        results["R6"] = run_round6_dynamic_ensemble(stock_id, today, base_results)
    except Exception:
        print("    R6 失敗")
        traceback.print_exc()

    # ── 印出這支股票的改進摘要 ────────────────────────────────────────────
    print(f"\n  [{stock_id}] 改進摘要：")
    labels = {
        "R0": "Baseline      ",
        "R1": "IMP-001      ",
        "R2": "IMP-001+002  ",
        "R3": "+003 (Z-score)",
        "R4": "+005 (DA-ES)  ",
    }
    r0_mape = results.get("R0", {}) and results["R0"] and results["R0"]["metrics"]["MAPE"] or None
    for rk, label in labels.items():
        r = results.get(rk)
        if r and r.get("metrics"):
            m = r["metrics"]
            delta = ""
            if r0_mape and rk != "R0":
                diff = m["MAPE"] - r0_mape
                delta = f"  ({'+' if diff > 0 else ''}{diff:.2f}% vs baseline)"
            print(f"    {label}  MAPE={m['MAPE']:.2f}%  DA={m['DA']:.1f}%{delta}")


def main():
    parser = argparse.ArgumentParser(description="IMPR-001 改進測試")
    parser.add_argument("--stocks", nargs="*", default=None,
                        help="指定測試股票（預設：2330 2344 2323 2324）")
    args = parser.parse_args()

    stocks = args.stocks if args.stocks else DEFAULT_TEST_STOCKS
    today  = datetime.now().strftime("%Y-%m-%d")

    print(f"\n{'='*60}")
    print(f"  IMPR-001 LSTM 改進方案測試")
    print(f"  日期：{today}")
    print(f"  測試股票：{', '.join(stocks)}")
    print(f"  輸出：{LOG_CSV}")
    print(f"{'='*60}")

    for stock_id in stocks:
        try:
            run_stock(stock_id, today)
        except Exception:
            print(f"\n[{stock_id}] 整體失敗")
            traceback.print_exc()

    # ── 最終摘要 ─────────────────────────────────────────────────────────
    if LOG_CSV.exists():
        df = pd.read_csv(LOG_CSV)
        df_today = df[df["date"] == today]
        if not df_today.empty:
            print(f"\n{'='*60}")
            print("  今日測試結果（MAPE，越低越好）")
            print(f"{'='*60}")
            pivot = df_today.pivot_table(
                index="stock_id", columns="imp_flags",
                values="mape", aggfunc="mean"
            )
            print(pivot.to_string())

            # 寫入 txt 摘要
            with open(LOG_TXT, "a", encoding="utf-8") as f:
                f.write(f"\n\n{'='*60}\n")
                f.write(f"日期：{today}\n")
                f.write(pivot.to_string())
                f.write("\n")

            print(f"\nOK 結果已儲存：{LOG_CSV}")

    print("\nOK 全部改進測試完成")


if __name__ == "__main__":
    main()
