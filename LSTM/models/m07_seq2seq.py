"""
M07 Seq2Seq LSTM（多步預測）
─────────────────────────────
架構：Encoder LSTM → RepeatVector → Decoder LSTM → TimeDistributed Dense
特徵：close_price（單特徵）
預測：未來 5 個交易日收盤價
優勢：一次輸出多步，適合週趨勢規劃
"""
from tensorflow.keras.models import Sequential
from tensorflow.keras.layers import (
    LSTM, Dense, Dropout, RepeatVector, TimeDistributed,
)
from config import FORECAST_STEPS


def build(input_shape: tuple, forecast_steps: int = FORECAST_STEPS) -> Sequential:
    """
    input_shape: (lookback, n_features)
    """
    model = Sequential([
        # Encoder
        LSTM(128, input_shape=input_shape, return_sequences=False),
        Dropout(0.2),
        # Bridge
        RepeatVector(forecast_steps),
        # Decoder
        LSTM(64, return_sequences=True),
        Dropout(0.2),
        TimeDistributed(Dense(32, activation="relu")),
        TimeDistributed(Dense(1)),
    ], name="m07_seq2seq")
    model.compile(optimizer="adam", loss="mse")
    return model
