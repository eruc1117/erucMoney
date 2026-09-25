"""
M01 Vanilla LSTM
─────────────────
架構：LSTM(64) → Dropout(0.2) → Dense(1)
特徵：close_price（單特徵）
預測：下一個交易日收盤價
"""
from tensorflow.keras.models import Sequential
from tensorflow.keras.layers import LSTM, Dense, Dropout


def build(input_shape: tuple) -> Sequential:
    """
    input_shape: (lookback, n_features)
    """
    model = Sequential([
        LSTM(64, input_shape=input_shape, return_sequences=False),
        Dropout(0.2),
        Dense(1),
    ], name="m01_vanilla")
    model.compile(optimizer="adam", loss="mse")
    return model
