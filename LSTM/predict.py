"""
跨股票推論腳本
──────────────
使用跨股票訓練的模型，對任意股票預測未來收盤價（包含未訓練過的股票）。

用法：
    python predict.py --stock 2330
    python predict.py --stock 2330 --model m02_stacked
    python predict.py --stock 2330 --days 5     # 滾動預測未來 5 天
    python predict.py --stock 2330 --from-db    # 從 DB 取最新資料（預設）
    python predict.py --stock 2330 --prices 580 575 578 ...  # 手動輸入價格
"""
import argparse
import os
import warnings
warnings.filterwarnings("ignore")
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"

import numpy as np
import tensorflow as tf

from config import LOOKBACK, SAVED_DIR, MODEL_NAMES
from data_loader import load_prices

CROSS_SAVED_DIR = SAVED_DIR / "cross_stock"


def load_cross_model(model_key: str):
    """載入跨股票訓練模型"""
    path = CROSS_SAVED_DIR / f"{model_key}.keras"
    if not path.exists():
        raise FileNotFoundError(
            f"找不到跨股票模型：{path}\n"
            f"請先執行：python train_cross.py --models {model_key}")
    return tf.keras.models.load_model(str(path))


def normalize_window(window: np.ndarray, eps: float = 1e-8):
    """Window-level Z-score 正規化，回傳 (正規化序列, mean, std)"""
    mean = window.mean()
    std  = window.std() + eps
    return (window - mean) / std, mean, std


def predict_next(model, prices: np.ndarray) -> float:
    """
    給定最近 LOOKBACK 天的收盤價，預測下一個交易日收盤價。

    prices : 1D array，長度至少 LOOKBACK
    Returns: 預測收盤價（TWD）
    """
    if len(prices) < LOOKBACK:
        raise ValueError(f"至少需要 {LOOKBACK} 筆價格，目前只有 {len(prices)} 筆")

    window = prices[-LOOKBACK:].astype(float)
    x_norm, mean, std = normalize_window(window)

    x_input = x_norm.reshape(1, LOOKBACK, 1).astype(np.float32)
    y_norm  = model.predict(x_input, verbose=0)[0, 0]

    return float(y_norm * std + mean)


def predict_multi_days(model, prices: np.ndarray, days: int = 5) -> list[float]:
    """
    滾動預測未來 N 天（每次用前一天預測值接入序列）。

    prices : 至少 LOOKBACK 筆歷史收盤價
    days   : 要預測幾天
    """
    buf = list(prices[-LOOKBACK:].astype(float))
    preds = []
    for _ in range(days):
        p = predict_next(model, np.array(buf))
        preds.append(p)
        buf.append(p)
        buf = buf[-LOOKBACK:]   # 維持滑動窗口
    return preds


def get_available_models() -> list[str]:
    if not CROSS_SAVED_DIR.exists():
        return []
    return [f.stem for f in CROSS_SAVED_DIR.glob("*.keras")]


def main():
    parser = argparse.ArgumentParser(description="跨股票 LSTM 推論")
    parser.add_argument("--stock",    required=True, help="股票代碼（例如 2330）")
    parser.add_argument("--model",    default=None,  help="模型 key（預設自動選最佳）")
    parser.add_argument("--days",     type=int, default=1, help="預測天數（預設 1）")
    parser.add_argument("--prices",   nargs="+", type=float, default=None,
                        help="手動輸入最近收盤價（不填則從 DB 讀取）")
    args = parser.parse_args()

    # ── 決定使用哪個模型 ──────────────────────────────────────────────────────
    available = get_available_models()
    if not available:
        print(f"找不到任何跨股票模型，請先執行 python train_cross.py")
        return

    model_key = args.model
    if model_key is None:
        # 預設優先選 m02_stacked（通常表現最好），否則取第一個
        model_key = "m02_stacked" if "m02_stacked" in available else available[0]

    if model_key not in available:
        print(f"找不到模型 {model_key}，可用模型：{available}")
        return

    print(f"\n模型：{MODEL_NAMES.get(model_key, model_key)}（跨股票）")
    print(f"股票：{args.stock}")

    # ── 取得價格資料 ──────────────────────────────────────────────────────────
    if args.prices:
        prices = np.array(args.prices)
        print(f"使用手動輸入價格：{prices}")
    else:
        try:
            df = load_prices(args.stock)
            prices = df["close_price"].values
            print(f"從 DB 載入 {len(prices)} 筆資料（最新：{prices[-1]:.2f}）")
        except Exception as e:
            print(f"無法從 DB 載入 {args.stock}：{e}")
            return

    if len(prices) < LOOKBACK:
        print(f"資料不足（需要 {LOOKBACK} 筆，目前 {len(prices)} 筆）")
        return

    # ── 載入模型並預測 ────────────────────────────────────────────────────────
    model  = load_cross_model(model_key)
    last   = prices[-1]

    if args.days == 1:
        pred = predict_next(model, prices)
        change    = pred - last
        change_pct = change / last * 100
        print(f"\n{'─'*40}")
        print(f"  最後收盤：{last:.2f} TWD")
        print(f"  預測明日：{pred:.2f} TWD")
        print(f"  預測漲跌：{change:+.2f} ({change_pct:+.2f}%)")
        print(f"{'─'*40}")
    else:
        preds = predict_multi_days(model, prices, days=args.days)
        print(f"\n{'─'*40}")
        print(f"  最後收盤：{last:.2f} TWD")
        print(f"  未來 {args.days} 天預測：")
        cur = last
        for i, p in enumerate(preds, 1):
            chg = p - cur
            pct = chg / cur * 100
            print(f"    Day+{i}：{p:.2f} ({chg:+.2f} / {pct:+.2f}%)")
            cur = p
        print(f"{'─'*40}")


if __name__ == "__main__":
    main()
