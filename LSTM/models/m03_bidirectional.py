"""
M03 Bidirectional LSTM
───────────────────────
架構：Bidirectional(LSTM(64)) → Dropout(0.2) → Dense(32) → Dense(1)
特徵：close_price（單特徵）
預測：下一個交易日收盤價
優勢：同時學習前向/後向時序依賴（適合股價趨勢）
"""
from tensorflow.keras.models import Sequential
from tensorflow.keras.layers import Bidirectional, LSTM, Dense, Dropout


def build(input_shape: tuple) -> Sequential:
    model = Sequential([
        Bidirectional(LSTM(64, return_sequences=False), input_shape=input_shape),
        Dropout(0.2),
        Dense(32, activation="relu"),
        Dense(1),
    ], name="m03_bidirectional")
    model.compile(optimizer="adam", loss="mse")
    return model
