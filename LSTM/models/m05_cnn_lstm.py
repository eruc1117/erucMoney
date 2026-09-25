"""
M05 CNN-LSTM
─────────────
架構：Conv1D(64, k=3) → MaxPool → LSTM(64) → Dropout → Dense(1)
特徵：OHLCV（5 特徵）
預測：下一個交易日收盤價
優勢：CNN 提取局部時序模式，LSTM 捕捉長期依賴
"""
from tensorflow.keras.models import Sequential
from tensorflow.keras.layers import (
    Conv1D, MaxPooling1D, LSTM, Dense, Dropout,
)


def build(input_shape: tuple) -> Sequential:
    model = Sequential([
        Conv1D(filters=64, kernel_size=3, activation="relu",
               padding="same", input_shape=input_shape),
        MaxPooling1D(pool_size=2, padding="same"),
        LSTM(64, return_sequences=False),
        Dropout(0.2),
        Dense(32, activation="relu"),
        Dense(1),
    ], name="m05_cnn_lstm")
    model.compile(optimizer="adam", loss="mse")
    return model
