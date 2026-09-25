"""
模型評估指標與視覺化
"""
import os
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.font_manager import FontProperties

from config import RESULTS_DIR

# ── 中文字型設定（Windows：微軟正黑體）──────────────────────────────────────
def _setup_chinese_font():
    """設定 matplotlib 支援中文，依序嘗試常見 Windows 字型"""
    candidates = [
        "Microsoft JhengHei",   # 微軟正黑體（繁體）
        "Microsoft YaHei",      # 微雅黑（簡體）
        "SimHei",               # 黑體
        "DFKai-SB",             # 標楷體
    ]
    available = {f.name for f in matplotlib.font_manager.fontManager.ttflist}
    for name in candidates:
        if name in available:
            matplotlib.rcParams["font.family"] = name
            break
    else:
        # 找不到已知字型時，嘗試直接指定字型檔
        font_path = r"C:\Windows\Fonts\msjh.ttc"
        if os.path.exists(font_path):
            matplotlib.font_manager.fontManager.addfont(font_path)
            prop = FontProperties(fname=font_path)
            matplotlib.rcParams["font.family"] = prop.get_name()

    matplotlib.rcParams["axes.unicode_minus"] = False  # 負號正常顯示

_setup_chinese_font()


def inverse_transform_1d(arr: np.ndarray, scaler) -> np.ndarray:
    """對一維陣列做 inverse_transform（MinMaxScaler 1 特徵）"""
    return scaler.inverse_transform(arr.reshape(-1, 1)).flatten()


def compute_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict:
    """
    計算回歸評估指標
    y_true, y_pred: 原始價格（非標準化），1D array
    """
    mae  = float(np.mean(np.abs(y_true - y_pred)))
    rmse = float(np.sqrt(np.mean((y_true - y_pred) ** 2)))
    mape = float(np.mean(np.abs((y_true - y_pred) / (y_true + 1e-9))) * 100)

    # 方向準確率（MODEL-004 修正）：
    # 舊算法比較 diff(y_true) 與 diff(y_pred)，等於問「預測序列自己的走勢
    # 跟實際序列自己的走勢是否同向」——一個永遠照抄昨日收盤的模型
    # 在這個定義下會拿到接近 100%。正確的問題是「相對昨日實際收盤，
    # 模型說漲還是跌，答對了嗎」，所以預測方向要以 y_true[t-1] 為基準。
    # 本函式假設輸入是**單一股票的連續時序**；跨股票串接的陣列在邊界處
    # 會多出一筆錯的比較，逐股呼叫才正確（train_cross 的整體 DA 仍不可信）。
    if len(y_true) < 2:
        da = 0.0
    else:
        prev = y_true[:-1]
        actual_dir = np.sign(y_true[1:] - prev)
        pred_dir   = np.sign(y_pred[1:] - prev)
        da = float(np.mean(actual_dir == pred_dir) * 100)

    return {"MAE": mae, "RMSE": rmse, "MAPE": mape, "DA": da}


def plot_predictions(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    stock_id: str,
    model_key: str,
    model_name: str,
    dates=None,
    y_std: np.ndarray = None,
    save: bool = True,
) -> str:
    """
    繪製預測 vs 實際圖，回傳儲存路徑
    """
    out_dir = RESULTS_DIR / model_key / stock_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = str(out_dir / "prediction.png")

    fig, ax = plt.subplots(figsize=(12, 5))

    x = dates if dates is not None else np.arange(len(y_true))

    ax.plot(x, y_true, label="實際價格", color="#2196F3", linewidth=1.5)
    ax.plot(x, y_pred, label="預測價格", color="#FF5722", linewidth=1.5,
            linestyle="--")

    if y_std is not None:
        ax.fill_between(x, y_pred - 2 * y_std, y_pred + 2 * y_std,
                        alpha=0.25, color="#FF5722", label="±2σ 信賴區間")

    if dates is not None:
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
        fig.autofmt_xdate()

    metrics = compute_metrics(y_true, y_pred)
    subtitle = (f"MAE={metrics['MAE']:.2f}  RMSE={metrics['RMSE']:.2f}  "
                f"MAPE={metrics['MAPE']:.2f}%  DA={metrics['DA']:.1f}%")

    ax.set_title(f"{stock_id}  {model_name}\n{subtitle}", fontsize=11)
    ax.set_ylabel("價格 (TWD)")
    ax.legend()
    ax.grid(alpha=0.3)
    plt.tight_layout()

    if save:
        fig.savefig(out_path, dpi=120)
    plt.close(fig)
    return out_path


def plot_loss(history, stock_id: str, model_key: str, model_name: str) -> str:
    """繪製 train/val loss 曲線"""
    out_dir = RESULTS_DIR / model_key / stock_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = str(out_dir / "loss.png")

    fig, ax = plt.subplots(figsize=(8, 4))
    ax.plot(history.history["loss"],     label="Train Loss", color="#2196F3")
    ax.plot(history.history["val_loss"], label="Val Loss",   color="#FF5722")
    ax.set_title(f"{stock_id}  {model_name} — Loss Curve")
    ax.set_xlabel("Epoch")
    ax.set_ylabel("MSE Loss")
    ax.legend()
    ax.grid(alpha=0.3)
    plt.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)
    return out_path
