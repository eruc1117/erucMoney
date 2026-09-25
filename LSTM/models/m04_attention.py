"""
M04 LSTM + Attention
─────────────────────
架構：LSTM(64, return_sequences=True) → BahdanauAttention → Dense(1)
特徵：close_price + volume（雙特徵）
預測：下一個交易日收盤價
優勢：Attention 讓模型聚焦於關鍵時間步
"""
import tensorflow as tf
from tensorflow.keras.models import Model
from tensorflow.keras.layers import LSTM, Dense, Layer, Input
import numpy as np


class BahdanauAttention(Layer):
    """Bahdanau 加法注意力機制"""

    def __init__(self, units: int = 32, **kwargs):
        super().__init__(**kwargs)
        self.W = Dense(units)
        self.V = Dense(1)

    def call(self, hidden_states):
        # hidden_states: (batch, timesteps, units)
        score   = self.V(tf.nn.tanh(self.W(hidden_states)))  # (batch, T, 1)
        weights = tf.nn.softmax(score, axis=1)               # (batch, T, 1)
        context = tf.reduce_sum(weights * hidden_states, axis=1)  # (batch, units)
        return context

    def get_config(self):
        cfg = super().get_config()
        cfg.update({"units": self.W.units})
        return cfg


def build(input_shape: tuple) -> Model:
    inputs = Input(shape=input_shape)
    x      = LSTM(64, return_sequences=True)(inputs)
    x      = BahdanauAttention(32)(x)
    out    = Dense(1)(x)

    model  = Model(inputs, out, name="m04_attention")
    model.compile(optimizer="adam", loss="mse")
    return model
