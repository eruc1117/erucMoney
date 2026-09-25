"""
M09 LSTM + 技術指標
────────────────────
架構：LSTM(128, return_sequences=True) → LSTM(64) → Dropout(0.2) → Dense(1)
特徵：OHLCV + MA5/10/20 + RSI + MACD + Bollinger + Momentum（共 20 特徵）
預測：下一個交易日收盤價
優勢：技術分析特徵對量化策略具有實際意義
"""
from tensorflow.keras.models import Sequential
from tensorflow.keras.layers import LSTM, Dense, Dropout


def build(input_shape: tuple) -> Sequential:
    model = Sequential([
        LSTM(128, input_shape=input_shape, return_sequences=True),
        LSTM(64,  return_sequences=False),
        Dropout(0.2),
        Dense(32, activation="relu"),
        Dense(1),
    ], name="m09_technical")
    model.compile(optimizer="adam", loss="mse")
    return model
