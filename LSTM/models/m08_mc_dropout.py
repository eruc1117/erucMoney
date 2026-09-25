"""
M08 MC Dropout LSTM（貝葉斯近似不確定性量化）
─────────────────────────────────────────────
架構：LSTM(64) → Dropout(0.3) → LSTM(32) → Dropout(0.3) → Dense(1)
特徵：close_price（單特徵）
預測：下一個交易日收盤價 + ±2σ 信賴區間
優勢：Monte Carlo Dropout 估計預測不確定性（對風險管理有幫助）

推論時保持 Dropout 開啟（training=True），
執行 N 次取均值/標準差，作為不確定性估計。
"""
import numpy as np
from tensorflow.keras.models import Model
from tensorflow.keras.layers import LSTM, Dense, Dropout, Input


def build(input_shape: tuple) -> Model:
    inputs = Input(shape=input_shape)
    x = LSTM(64, return_sequences=True)(inputs)
    x = Dropout(0.3)(x, training=True)   # 推論時保持開啟
    x = LSTM(32, return_sequences=False)(x)
    x = Dropout(0.3)(x, training=True)
    out = Dense(1)(x)

    model = Model(inputs, out, name="m08_mc_dropout")
    model.compile(optimizer="adam", loss="mse")
    return model


def mc_predict(model: Model, X: np.ndarray, n_samples: int = 50):
    """
    MC Dropout 推論：執行 n_samples 次預測，回傳均值與標準差
    Returns: mean (N,), std (N,)
    """
    preds = np.stack([model(X, training=True).numpy().flatten()
                      for _ in range(n_samples)], axis=0)  # (n_samples, N)
    return preds.mean(axis=0), preds.std(axis=0)
