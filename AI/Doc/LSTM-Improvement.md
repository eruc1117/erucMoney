# LSTM 預測準確率改進方案

> 建立日期：2026-03-23
> 背景：M01 Vanilla LSTM 及現有模型在 PredictionCompare 頁面的 MAPE 偏高、方向準確率不足 55%，需系統性改進。

---

## 一、根本原因分析

| # | 問題 | 影響 |
|---|------|------|
| P1 | 預測目標為**絕對股價**（非平穩序列） | 模型學到均值迴歸假設，長期預測偏移 |
| P2 | M01 只使用**單一特徵**（收盤價） | 遺漏量價關係、技術趨勢、籌碼訊號 |
| P3 | **全域 MinMax 正規化**（訓練+測試共用 Scaler） | 未來資料洩漏（Data Leakage），導致測試指標虛高 |
| P4 | **時間視窗固定 30 天**，未依股票波動率調整 | 慢漲慢跌股需更長記憶，短線急漲股需更短反應 |
| P5 | 評估只看 MAE / MAPE，**未監控方向準確率** | 訓練目標與交易實用性脫鉤 |
| P6 | 訓練集與驗證集**未嚴格時序分割**（Walk-Forward） | 驗證指標過於樂觀 |

---

## 二、改進方案

### IMP-001：預測目標改為對數報酬率（Log Return）

**問題對應：** P1

**原理：**
```
原做法：y = close_t          ← 非平穩，均值隨時間漂移
改進後：y = log(close_t / close_{t-1})  ← 接近平穩，去除長期趨勢偏移
```

**實作步驟：**
1. 前處理加入 `log_return = np.log(close / close.shift(1))`
2. 訓練目標 `y` 改為 `log_return_t+1`
3. 推論時將輸出反轉：`predicted_close = last_close × exp(predicted_log_return)`

**測試指標：**
- MAPE 相對改善 ≥ 10%
- 方向準確率（Directional Accuracy）≥ 55%

---

### IMP-002：M01 特徵擴充（最小改動，高效益）

**問題對應：** P2

**新增特徵（從 5 個增至 10 個）：**

| 新特徵 | 計算方式 | 理由 |
|--------|----------|------|
| `log_return` | `log(close_t / close_{t-1})` | 去趨勢化（配合 IMP-001） |
| `volume_ratio` | `volume / MA20_volume` | 爆量通常對應趨勢轉折 |
| `rsi_14` | RSI(14) | 超買超賣，0~100 已正規化 |
| `macd_hist` | MACD(12,26,9) 柱狀值 | 動能方向訊號 |
| `bb_position` | `(close - BB下界) / (BB上界 - BB下界)` | 相對布林帶位置，天然 [0,1] |

**測試指標：**
- 對照組：M01 原版（5 特徵）
- 實驗組：M01 擴充（10 特徵）
- 方向準確率提升 ≥ 3 個百分點

---

### IMP-003：正規化改為 Rolling Z-Score（每視窗自適應）

**問題對應：** P3

**原理：**
```
原做法：MinMax 用整段歷史的 min/max 正規化
         → 測試時模型「看過」未來最高/最低價
改進後：每個時間窗口獨立做 Z-score
         mean = mean(window)  /  std = std(window)
         → 只用窗口內資訊，無未來洩漏
```

**實作：**
```python
# 每個樣本窗口獨立正規化
for i in range(len(windows)):
    w = windows[i]
    mean, std = w.mean(axis=0), w.std(axis=0) + 1e-8
    X[i] = (w - mean) / std
    # 記錄 mean/std 供推論時反正規化
```

**適用場景：** 跨股票模型（`train_cross.py`）優先採用，已在 LSTM-Setup.md 七節標注

**測試指標：**
- Walk-Forward 測試集 MAPE 不高於訓練集 MAPE 的 1.5 倍（過擬合指標）

---

### IMP-004：Walk-Forward Validation 嚴格實施

**問題對應：** P6

**訓練 / 驗證 / 測試分割原則：**
```
完整資料（假設 3 年）：
  ├── 訓練集：前 70%（約 2 年）
  ├── 驗證集：中 15%（約 6 個月）  ← 僅 transform，不 fit Scaler
  └── 測試集：後 15%（約 6 個月）  ← 完全隔離，最後才評估
```

**Walk-Forward 滾動方式：**
```
Round 1：Train [2022-01 ~ 2024-06]  →  Test [2024-07]
Round 2：Train [2022-01 ~ 2024-07]  →  Test [2024-08]
...（每月向前滾一個月）
```

**測試指標：**
- 每個 Round 的方向準確率標準差 < 10%（模型穩定性）
- 平均方向準確率 ≥ 53%

---

### IMP-005：加入 Early Stopping 監控方向準確率

**問題對應：** P5

**現況：** `EarlyStopping(monitor='val_loss')`
**問題：** val_loss 最小不代表方向準確率最高（例如模型學會預測均值可讓 MSE 小但方向全錯）

**改進方式：**
```python
import tensorflow as tf

class DirectionalAccuracy(tf.keras.callbacks.Callback):
    """每個 epoch 結束後計算驗證集方向準確率，達標才允許提前停止"""
    def on_epoch_end(self, epoch, logs=None):
        y_pred = self.model.predict(X_val, verbose=0).flatten()
        y_true = y_val.flatten()
        # 比較相對前一天的漲跌方向
        dir_acc = np.mean(np.sign(y_pred) == np.sign(y_true))
        logs['val_dir_acc'] = dir_acc

callbacks = [
    EarlyStopping(monitor='val_dir_acc', mode='max', patience=10, restore_best_weights=True),
    ReduceLROnPlateau(monitor='val_loss', factor=0.5, patience=5),
]
```

**測試指標：**
- 最終模型的驗證集方向準確率 ≥ 55%

---

### IMP-006：M10 Ensemble 加入動態權重（依近期誤差調整）

**問題對應：** P1, P2（利用集成彌補單一模型偏差）

**原理：**
固定加權（M01+M02+M03 各 1/3）無法適應不同市場狀態，改為依各模型**最近 30 天 MAPE** 動態調整：

```python
def dynamic_weights(maes: dict) -> dict:
    """
    maes = {"m01": 0.032, "m02": 0.028, "m03": 0.041}
    誤差越小，權重越高
    """
    inv = {k: 1.0 / (v + 1e-8) for k, v in maes.items()}
    total = sum(inv.values())
    return {k: v / total for k, v in inv.items()}
```

**測試指標：**
- 動態 Ensemble MAPE ≤ 三個基礎模型中最小的 MAPE × 0.95

---

## 三、測試計劃

### 3.1 測試股票（依 Target.md 選擇代表性股票）

| 股票 | 類型 | 選擇理由 |
|------|------|----------|
| 2330 TSMC | 大型權值股 | 基準測試，流動性高 |
| 2344 華邦電 | 週期循環股 | 測試週期性預測能力 |
| 2323 中環 | 高波動股 | 測試短線波動訊號 |
| 2324 仁寶 | 低波動基準 | 測試穩定股的滯後問題 |

### 3.2 測試矩陣

每個改進方案對每支股票獨立測試，記錄以下指標：

| 指標 | 說明 | 目標值 |
|------|------|--------|
| MAPE | 平均絕對百分比誤差 | ≤ 3% |
| MAE | 平均絕對誤差（元） | — |
| Dir-Acc | 方向準確率 | ≥ 55% |
| Overfitting Ratio | test_MAPE / val_MAPE | ≤ 1.5 |
| CI Hit Rate | 實際值落在 95% 信賴區間內的比例 | ≥ 70% |

### 3.3 測試執行順序

```
基準測試（現有 M01 Vanilla）
    ↓
IMP-001：Log Return 預測目標   （獨立套用，對比基準）
    ↓
IMP-002：特徵擴充              （疊加 IMP-001）
    ↓
IMP-003：Rolling Z-Score       （疊加前兩項）
    ↓
IMP-004：Walk-Forward          （疊加前三項，重新訓練驗證）
    ↓
IMP-005：方向準確率 EarlyStopping（疊加全部）
    ↓
IMP-006：動態 Ensemble         （使用上述最優模型組合）
```

### 3.4 結果記錄格式

訓練完成後於 `LSTM/report/improvement_log.csv` 記錄：

```csv
date,stock_id,model,imp_flags,mape,mae,dir_acc,ci_hit_rate,overfit_ratio
2026-03-23,2330,m01_vanilla,none,0.042,25.3,0.51,0.65,1.8
2026-03-23,2330,m01_vanilla,IMP001,0.033,19.8,0.57,0.72,1.3
...
```

---

## 四、各模型改進優先級

| 模型 | 優先改進項 | 預期效益 |
|------|-----------|---------|
| M01 Vanilla | IMP-001、IMP-002 | 提升最明顯（現況最弱） |
| M02 Stacked | IMP-003、IMP-004 | 解決過擬合 |
| M06 Multi-feature | IMP-003、IMP-005 | 特徵多更容易洩漏 |
| M09 Technical | IMP-004、IMP-005 | 方向準確率優化 |
| M10 Ensemble | IMP-006 | 動態權重替換固定權重 |

---

## 五、已知不可改善的限制

以下問題屬於 LSTM 結構性限制，改進方案**無法根本解決**：

- **黑天鵝事件**：突發政策、戰爭、疫情無歷史樣本可學習
- **隔日跳空**：法說會、財報公告後的跳空由資訊不對稱決定，非時序可預測
- **低流動性股**：日成交量 < 500 張的股票樣本不足，模型無法收斂

這些情境建議配合**模型二（新聞情緒）** 與**模型三（籌碼）** 的投票系統作為第二層防護。
