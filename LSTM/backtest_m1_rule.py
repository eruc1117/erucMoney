"""
M1 投票規則回測（Iteration 11 後續）
─────────────────────────────────────
背景：`voting_engine._get_m1_signal` 讀取 `p.get('predicted')`，
但 LSTM API 回傳的欄位是 `predicted_close`，取不到值就回退成現價，
於是變動恆為 0.0%、M1 自實作以來永遠輸出 Hold。

修好欄名之前必須先回答：**這條規則本身準不準？**
（Iteration 9 的教訓：不要把沒有 edge 的訊號放進以固定 ±0.33 計分的投票。）

規則：以 LSTM 滾動預測未來 7 日，取均價與現價比較，
      >= +2% → Buy，<= -2% → Sell，其餘 Hold。

評估：訊號發出後，實際未來 7 個交易日的均價方向是否一致。
      只在測試期（各股票時序最後 15%）取樣，不碰訓練資料。

用法：python backtest_m1_rule.py [--samples 40] [--model m02_stacked]
產出：results/m1_rule_backtest.md
"""

import argparse
import os
import warnings
from datetime import datetime

warnings.filterwarnings("ignore")
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"

import numpy as np

from config import LOOKBACK, TRAIN_RATIO, VAL_RATIO, SAVED_DIR, RESULTS_DIR
from data_loader import load_prices, get_all_stocks

CROSS_SAVED = SAVED_DIR / "cross_stock"
REPORT_PATH = RESULTS_DIR / "m1_rule_backtest.md"

HORIZON = 7          # 與 voting_engine 一致
THRESHOLD = 2.0      # ±2%


def load_model(model_key: str):
    import tensorflow as tf
    path = CROSS_SAVED / f"{model_key}.keras"
    if not path.exists():
        return None
    custom = {}
    try:
        from models.m04_attention import BahdanauAttention
        custom["BahdanauAttention"] = BahdanauAttention
    except Exception:
        pass
    return tf.keras.models.load_model(str(path), custom_objects=custom)


def roll_predict(model, window: np.ndarray, days: int) -> list:
    """複製 serve.py 的滾動預測邏輯。"""
    buf = list(window.astype(float))
    preds = []
    while len(preds) < days:
        w = np.array(buf[-LOOKBACK:])
        mean, std = w.mean(), w.std() + 1e-8
        x = ((w - mean) / std).reshape(1, LOOKBACK, 1).astype("float32")
        out = model.predict(x, verbose=0)
        steps = out[0, :, 0] if out.ndim == 3 else np.atleast_1d(out[0]).ravel()[:1]
        for v in steps:
            if len(preds) >= days:
                break
            p = float(v) * std + mean
            preds.append(p)
            buf.append(p)
    return preds


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", type=int, default=40,
                    help="每檔股票在測試期取樣幾個日期")
    ap.add_argument("--model", default="m02_stacked")
    args = ap.parse_args()

    model = load_model(args.model)
    if model is None:
        print(f"模型 {args.model} 不存在")
        return

    records = []
    for sid in get_all_stocks():
        df = load_prices(sid)
        if df is None or len(df) < LOOKBACK + HORIZON + 30:
            continue
        close = df["close_price"].values.astype(float)

        n = len(close)
        test_start = int(n * (TRAIN_RATIO + VAL_RATIO))
        # 需留 HORIZON 天觀察實際結果
        valid = range(max(test_start, LOOKBACK), n - HORIZON)
        if len(valid) == 0:
            continue
        idxs = np.linspace(valid[0], valid[-1], min(args.samples, len(valid))).astype(int)

        for i in idxs:
            window = close[i - LOOKBACK: i]
            cur = close[i - 1]
            preds = roll_predict(model, window, HORIZON)
            pred_avg = float(np.mean(preds))
            chg = (pred_avg - cur) / cur * 100

            actual_avg = float(np.mean(close[i: i + HORIZON]))
            actual_chg = (actual_avg - cur) / cur * 100

            signal = "Buy" if chg >= THRESHOLD else ("Sell" if chg <= -THRESHOLD else "Hold")
            records.append({"stock_id": sid, "pred_chg": chg,
                            "actual_chg": actual_chg, "signal": signal})
        print(f"  {sid} 完成（{len(idxs)} 個取樣點）", flush=True)

    if not records:
        print("無樣本")
        return

    pred_chg = np.array([r["pred_chg"] for r in records])
    act_chg = np.array([r["actual_chg"] for r in records])
    sigs = np.array([r["signal"] for r in records])

    fired = sigs != "Hold"
    n_fired = int(fired.sum())
    if n_fired:
        long_ = sigs[fired] == "Buy"
        a = act_chg[fired]
        ok = np.where(long_, a > 0, a < 0)
        da = float(ok.mean() * 100)
        signed = np.where(long_, a, -a)
        avg_ret = float(signed.mean())
        buy_n, sell_n = int(long_.sum()), int((~long_).sum())
        buy_da = float(ok[long_].mean() * 100) if buy_n else float("nan")
        sell_da = float(ok[~long_].mean() * 100) if sell_n else float("nan")
        buy_ret = float(a[long_].mean()) if buy_n else float("nan")
        sell_ret = float(-a[~long_].mean()) if sell_n else float("nan")
    else:
        da = avg_ret = buy_da = sell_da = buy_ret = sell_ret = float("nan")
        buy_n = sell_n = 0

    corr = float(np.corrcoef(pred_chg, act_chg)[0, 1])

    print(f"\n樣本 {len(records)}　觸發 {n_fired}（{n_fired/len(records):.0%}）")
    print(f"方向準確率 {da:.2f}%　單次平均報酬 {avg_ret:+.2f}%")
    print(f"買進 {buy_n} 次 {buy_da:.1f}% 報酬 {buy_ret:+.2f}%　"
          f"賣出 {sell_n} 次 {sell_da:.1f}% 報酬 {sell_ret:+.2f}%")
    print(f"預測變動 vs 實際變動 相關係數 = {corr:+.4f}")

    lines = [
        "# M1 投票規則回測（Iteration 11 後續）",
        "",
        f"**執行時間：** {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"**模型：** {args.model}　**規則：** 7 日滾動預測均價 vs 現價，±{THRESHOLD}% 轉訊號",
        f"**樣本：** {len(records)} 個（測試期取樣，未碰訓練資料）",
        "",
        "| 指標 | 數值 |",
        "|------|------|",
        f"| 觸發率 | {n_fired/len(records):.0%}（{n_fired} 次） |",
        f"| 方向準確率 | **{da:.2f}%** |",
        f"| 單次平均報酬 | {avg_ret:+.2f}% |",
        f"| 買進 | {buy_n} 次，準確率 {buy_da:.1f}%，平均 {buy_ret:+.2f}% |",
        f"| 賣出 | {sell_n} 次，準確率 {sell_da:.1f}%，平均 {sell_ret:+.2f}% |",
        f"| 預測變動 vs 實際變動 相關係數 | **{corr:+.4f}** |",
        "",
        "## 解讀",
        "",
        "- **方向的隨機基準是 50%**。",
        "- **相關係數**是更嚴格的檢驗：若滾動預測帶有真實資訊，",
        "  預測變動幅度應與實際變動幅度正相關；接近 0 代表預測值只是累積的漂移。",
    ]
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"\n報告已寫入 {REPORT_PATH}")


if __name__ == "__main__":
    main()
