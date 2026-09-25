"""
技術指標特徵工程
"""
import numpy as np
import pandas as pd


def add_ma(df: pd.DataFrame, windows=(5, 10, 20)) -> pd.DataFrame:
    """移動平均線"""
    for w in windows:
        df[f"ma{w}"] = df["close_price"].rolling(w).mean()
    return df


def add_rsi(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """RSI（相對強弱指數）"""
    delta = df["close_price"].diff()
    gain  = delta.clip(lower=0).rolling(period).mean()
    loss  = (-delta.clip(upper=0)).rolling(period).mean()
    rs    = gain / (loss + 1e-9)
    df["rsi"] = 100 - (100 / (1 + rs))
    return df


def add_macd(df: pd.DataFrame,
             fast=12, slow=26, signal=9) -> pd.DataFrame:
    """MACD + Signal + Histogram"""
    ema_fast = df["close_price"].ewm(span=fast, adjust=False).mean()
    ema_slow = df["close_price"].ewm(span=slow, adjust=False).mean()
    df["macd"]        = ema_fast - ema_slow
    df["macd_signal"] = df["macd"].ewm(span=signal, adjust=False).mean()
    df["macd_hist"]   = df["macd"] - df["macd_signal"]
    return df


def add_bollinger(df: pd.DataFrame, period=20, std_mult=2.0) -> pd.DataFrame:
    """布林通道（上軌、中軌、下軌、%B）"""
    mid = df["close_price"].rolling(period).mean()
    std = df["close_price"].rolling(period).std()
    upper = mid + std_mult * std
    lower = mid - std_mult * std
    df["bb_upper"] = upper
    df["bb_mid"]   = mid
    df["bb_lower"] = lower
    df["bb_pct"]   = (df["close_price"] - lower) / (upper - lower + 1e-9)
    return df


def add_momentum(df: pd.DataFrame, periods=(1, 5)) -> pd.DataFrame:
    """價格動量（報酬率）"""
    for p in periods:
        df[f"ret{p}"] = df["close_price"].pct_change(p)
    return df


def add_volume_features(df: pd.DataFrame) -> pd.DataFrame:
    """成交量相關特徵"""
    df["vol_ma5"]  = df["volume"].rolling(5).mean()
    df["vol_ratio"] = df["volume"] / (df["vol_ma5"] + 1e-9)
    return df


def build_technical_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    一次性加入所有技術指標
    輸入 df 需含 close_price, high_price, low_price, volume 欄位
    """
    df = df.copy()
    df = add_ma(df, windows=(5, 10, 20))
    df = add_rsi(df, period=14)
    df = add_macd(df)
    df = add_bollinger(df)
    df = add_momentum(df, periods=(1, 5))
    df = add_volume_features(df)
    df = df.dropna()
    return df


TECHNICAL_COLS = [
    "close_price",
    "open_price", "high_price", "low_price", "volume",
    "ma5", "ma10", "ma20",
    "rsi",
    "macd", "macd_signal", "macd_hist",
    "bb_upper", "bb_mid", "bb_lower", "bb_pct",
    "ret1", "ret5",
    "vol_ma5", "vol_ratio",
]


# ── IMP-001 / IMP-002：對數報酬率特徵 ─────────────────────────────────────────

def add_log_return(df: pd.DataFrame) -> pd.DataFrame:
    """
    IMP-001：對數報酬率 log(close_t / close_{t-1})
    去除股價的長期趨勢漂移，使預測目標接近平穩序列。
    第一筆為 NaN，呼叫後需 dropna()。
    """
    df["log_return"] = np.log(df["close_price"] / df["close_price"].shift(1))
    return df


def build_enhanced_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    IMP-002：一次性加入所有技術指標 + log_return
    輸入 df 需含 close_price, high_price, low_price, volume
    """
    df = df.copy()
    df = add_ma(df, windows=(5, 10, 20))
    df = add_rsi(df, period=14)
    df = add_macd(df)
    df = add_bollinger(df)
    df = add_momentum(df, periods=(1, 5))
    df = add_volume_features(df)
    df = add_log_return(df)
    df = df.dropna()
    return df


# M01 改進版特徵清單（10 個）— IMP-002
# 第 0 欄必須是 log_return（預測目標）
M01_ENHANCED_COLS = [
    "log_return",    # IMP-001：預測目標（對數報酬率）
    "vol_ratio",     # 成交量比（volume / MA5_volume）
    "rsi",           # RSI(14)
    "macd_hist",     # MACD 柱狀值（動能方向）
    "bb_pct",        # 布林帶相對位置 %B
    "ret1",          # 昨日報酬率
    "ret5",          # 5 日報酬率
    "ma5",           # 5 日均線（原始值，配合 z-score 自動標準化）
    "ma20",          # 20 日均線
    "close_price",   # 收盤價（保留原始脈絡）
]
