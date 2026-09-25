"""
M06 Multi-feature LSTM
───────────────────────
架構：LSTM(128) → LSTM(64) → Dropout(0.3) → Dense(1)
特徵：OHLCV + 三大法人籌碼（最多 10 特徵）
預測：下一個交易日收盤價
優勢：融合量價與籌碼面資訊，提升預測準確度
"""
from tensorflow.keras.models import Sequential
from tensorflow.keras.layers import LSTM, Dense, Dropout


def build(input_shape: tuple) -> Sequential:
    model = Sequential([
        LSTM(128, input_shape=input_shape, return_sequences=True),
        LSTM(64,  return_sequences=False),
        Dropout(0.3),
        Dense(32, activation="relu"),
        Dense(1),
    ], name="m06_multifeature")
    model.compile(optimizer="adam", loss="mse")
    return model


FEATURE_COLS = [
    "close_price",
    "open_price", "high_price", "low_price", "volume",
    "foreign_investor_buy", "investment_trust_buy",
    "dealer_buy", "total_net_buy", "foreign_holding_ratio",
]
