"""
M02 Stacked LSTM
─────────────────
架構：LSTM(128) → LSTM(64) → LSTM(32) → Dropout(0.2) → Dense(1)
特徵：close_price（單特徵）
預測：下一個交易日收盤價
優勢：多層堆疊學習更高階時序特徵
"""
from tensorflow.keras.models import Sequential
from tensorflow.keras.layers import LSTM, Dense, Dropout


def build(input_shape: tuple) -> Sequential:
    model = Sequential([
        LSTM(128, input_shape=input_shape, return_sequences=True),
        LSTM(64,  return_sequences=True),
        LSTM(32,  return_sequences=False),
        Dropout(0.2),
        Dense(1),
    ], name="m02_stacked")
    model.compile(optimizer="adam", loss="mse")
    return model
