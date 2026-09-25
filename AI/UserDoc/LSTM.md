# LSTM 股票預測模型技術文件

---

## 一、核心概念：為什麼 LSTM 適合股票預測？

股票資料屬於**時序資料 (Time Series)**，前後資料點之間存在強烈的依賴關係。傳統神經網路（MLP）每次只看單一輸入，無法記住「上週漲了三天」這種跨時間的規律。

LSTM（Long Short-Term Memory）的關鍵設計是**細胞狀態 (Cell State)**，透過三個「閘門 (Gate)」動態決定記住或遺忘資訊：

| 閘門 | 公式 | 作用 |
|------|------|------|
| 遺忘閘 (Forget Gate) | $f_t = \sigma(W_f \cdot [h_{t-1}, x_t] + b_f)$ | 決定丟掉哪些舊記憶 |
| 輸入閘 (Input Gate) | $i_t = \sigma(W_i \cdot [h_{t-1}, x_t] + b_i)$ | 決定記住哪些新資訊 |
| 輸出閘 (Output Gate) | $o_t = \sigma(W_o \cdot [h_{t-1}, x_t] + b_o)$ | 決定輸出哪些狀態 |

**對股票預測的意義：**
- **短線慣性**：記住前幾天的漲跌趨勢（Momentum）
- **長線支撐**：記住過去數週的價格區間（如：20 元附近的支撐位）
- **雜訊過濾**：遺忘閘自動淡化異常單日劇烈波動的干擾

---

## 二、資料前處理 (Data Pipeline)

資料前處理是模型成敗的關鍵，原始數據必須經過三個步驟才能被模型吸收。

### 2.1 特徵工程 (Feature Engineering)

| 類別 | 特徵 | 說明 |
|------|------|------|
| 基礎價量 | Open, High, Low, Close, Volume | OHLCV 原始欄位 |
| 技術指標 | $MA_5$, $MA_{20}$ | 週線、月線均值 |
| 技術指標 | $RSI_{14}$ | 超買超賣指標（0～100） |
| 技術指標 | $K$, $D$ | 隨機指標，KD 交叉訊號 |
| 自定義 | 昨日漲跌幅 | $(Close_t - Close_{t-1}) / Close_{t-1}$ |
| 自定義 | 價格偏離度 | $(Close - MA_{20}) / MA_{20}$ |

### 2.2 正規化 (Normalization)

使用 **Min-Max Normalization** 將所有數值縮放到 $[0, 1]$：

$$x' = \frac{x - x_{\min}}{x_{\max} - x_{\min}}$$

> **原因**：避免成交量（單位：萬張）的權重過大，壓過股價（單位：元）的影響，使梯度下降更穩定。

> **注意**：Scaler 必須只用訓練集 `fit`，驗證集 / 測試集只能 `transform`，避免資料洩漏（Data Leakage）。

### 2.3 滑動視窗 (Sliding Window)

將時序資料切成固定長度的「片段」：

```
時間軸：  D1  D2  D3 ... D30 | D31
          ←  X（輸入，30天）→   y（預測目標）

下一個視窗：
          D2  D3  D4 ... D31 | D32
```

- **視窗大小（Time Steps）**：預設 30 天（可調整為 20 或 60）
- **預測目標**：第 31 天收盤價（或漲跌幅）

**資料張量形狀 (Tensor Shape)：**

```
X.shape = [Batch_Size, Time_Steps, Features]
        = [32,         30,         10        ]

y.shape = [Batch_Size, 1]
```

---

## 三、模型架構設計 (Model Architecture)

```
Input Layer       →  (30, 10)           # 30天 × 10個特徵
       ↓
LSTM Layer 1      →  64 units           # 提取基礎時序特徵
       ↓
Dropout Layer     →  rate=0.2           # 防止 Overfitting
       ↓
LSTM Layer 2      →  32 units           # 深化複雜波動規律
       ↓
Dropout Layer     →  rate=0.2
       ↓
Dense Layer       →  1 unit             # 輸出預測價格
```

**各層設計說明：**

| 層 | 參數 | 用途 |
|----|------|------|
| LSTM Layer 1 | `units=64, return_sequences=True` | 保留每個時間步的輸出，傳給下一層 |
| LSTM Layer 2 | `units=32, return_sequences=False` | 只輸出最後時間步的結果 |
| Dropout | `rate=0.2` | 隨機丟棄 20% 神經元，避免死背歷史 |
| Dense | `units=1, activation='linear'` | 迴歸輸出，不加激活函數 |

**Keras 程式碼範例：**

```python
from tensorflow.keras.models import Sequential
from tensorflow.keras.layers import LSTM, Dense, Dropout

model = Sequential([
    LSTM(64, return_sequences=True, input_shape=(30, 10)),
    Dropout(0.2),
    LSTM(32, return_sequences=False),
    Dropout(0.2),
    Dense(1)
])

model.compile(
    optimizer='adam',
    loss='mse',
    metrics=['mae']
)
```

---

## 四、訓練與驗證策略

股票預測**不能**使用傳統的隨機抽樣（K-Fold Cross Validation），
必須嚴格遵守**時間順序**，否則等同於「用未來資料預測過去」。

### 4.1 Walk-Forward Validation（滾動驗證）

```
Round 1:  訓練 [2022-01 ~ 2023-12]  →  驗證 [2024-01]
Round 2:  訓練 [2022-01 ~ 2024-01]  →  驗證 [2024-02]
Round 3:  訓練 [2022-01 ~ 2024-02]  →  驗證 [2024-03]
...
```

每一輪加入最新的實際數據重新訓練，反映市場最新狀態。

### 4.2 損失函數與優化器

| 項目 | 選擇 | 說明 |
|------|------|------|
| Loss Function | MSE（均方誤差） | $\frac{1}{n}\sum(y_{pred} - y_{true})^2$，對大誤差懲罰更重 |
| Optimizer | Adam | 自動調整學習率，收斂穩定 |
| 學習率 | `lr=0.001` | 預設值，可搭配 ReduceLROnPlateau 動態調降 |
| Batch Size | 32 | 小批次有助於跳出局部最小值 |
| Epochs | 50～100 | 搭配 EarlyStopping 防止過擬合 |

### 4.3 Early Stopping

```python
from tensorflow.keras.callbacks import EarlyStopping, ReduceLROnPlateau

callbacks = [
    EarlyStopping(monitor='val_loss', patience=10, restore_best_weights=True),
    ReduceLROnPlateau(monitor='val_loss', factor=0.5, patience=5)
]
```

---

## 五、評估指標

| 指標 | 公式 | 說明 |
|------|------|------|
| MAE | $\frac{1}{n}\sum|y_{pred} - y_{true}|$ | 平均絕對誤差，直覺上的「平均差幾元」 |
| RMSE | $\sqrt{\frac{1}{n}\sum(y_{pred} - y_{true})^2}$ | 對大誤差更敏感 |
| MAPE | $\frac{1}{n}\sum\left|\frac{y_{pred} - y_{true}}{y_{true}}\right| \times 100\%$ | 百分比誤差，跨股票比較用 |
| 方向準確率 | 預測漲跌方向正確次數 / 總次數 | 實際交易中比價格更重要 |

---

## 六、已知限制

- **黑天鵝事件**：LSTM 無法預測未曾出現的突發事件（如疫情、地緣政治）
- **過擬合風險**：資料量不足時（< 2 年），模型容易死記歷史走勢
- **滯後性**：預測曲線往往比實際價格慢半拍（Lag），適合趨勢判斷而非精確點位
- **非平穩性**：股價本身非平穩序列，建議預測**漲跌幅**而非**絕對價格**

---

## 七、準確率改進方案

> 詳見 `AI/Doc/LSTM-Improvement.md`

| 方案 | 對應問題 | 優先級 |
|------|---------|--------|
| IMP-001：Log Return 預測目標 | 非平穩序列 | ⭐⭐⭐ 最優先 |
| IMP-002：M01 特徵擴充（5→10） | 單特徵不足 | ⭐⭐⭐ |
| IMP-003：Rolling Z-Score 正規化 | 資料洩漏 | ⭐⭐ |
| IMP-004：Walk-Forward Validation | 驗證不嚴謹 | ⭐⭐ |
| IMP-005：方向準確率 EarlyStopping | 訓練目標偏差 | ⭐⭐ |
| IMP-006：M10 動態 Ensemble 權重 | 集成效益不足 | ⭐ |

**目標指標：** MAPE ≤ 3%　／　方向準確率 ≥ 55%　／　CI 命中率 ≥ 70%
