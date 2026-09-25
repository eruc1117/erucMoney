# LSTM 模型訓練環境設定與啟動指南

---

## 一、首次安裝（只需做一次）

```bash
cd C:\Users\Eric\Desktop\coding\money\LSTM

# 建立虛擬環境
python -m venv venv

# 啟動虛擬環境
venv\Scripts\activate

# 安裝依賴套件
pip install -r requirements.txt
```

> 提示符前出現 `(venv)` 代表虛擬環境已啟動

---

## 二、每次訓練前（必須先啟動虛擬環境）

```bash
cd C:\Users\Eric\Desktop\coding\money\LSTM
venv\Scripts\activate
```

---

## 三、執行訓練

```bash
# 訓練所有股票（全部 10 種模型）
python train_all.py

# 僅訓練指定股票
python train_all.py --stocks 2330 2317 0050

# 僅執行指定模型
python train_all.py --models m01_vanilla m02_stacked m10_ensemble

# 訓練完不產生 HTML 報告
python train_all.py --skip-report

# 已有結果，只重新產生報告
python report_generator.py
```

---

## 四、查看報告

訓練完成後開啟：

```
LSTM/report/report.html   ← 完整 HTML 視覺化報告
LSTM/report/report.md     ← Markdown 摘要
LSTM/report/summary.csv   ← 所有指標數據表
```

---

## 五、常見訊息說明

### ModuleNotFoundError: No module named 'numpy'
**原因：** 沒有啟動虛擬環境就直接執行。
**解法：** 先執行 `venv\Scripts\activate`。

### WARNING: oneDNN custom operations are on
```
I0000 ... oneDNN custom operations are on. You may see slightly different
numerical results due to floating-point round-off errors...
```
**原因：** TensorFlow 啟用了 Intel oneDNN（深度學習加速函式庫），會對浮點運算重新排序以加速 CPU 計算。
**影響：** 無害。預測結果可能有極微小的數值差異（1e-7 以下），不影響實際準確度。
**如需關閉（結果完全可復現）：**
```bash
set TF_ENABLE_ONEDNN_OPTS=0   # Windows（單次）
python train_all.py
```
或寫進 `config.py` 開頭：
```python
import os
os.environ["TF_ENABLE_ONEDNN_OPTS"] = "0"
```

### WARNING: All log messages before absl::InitializeLog()...
**原因：** TensorFlow 使用的 abseil 日誌函式庫在初始化前的訊息導向 stderr，屬正常啟動流程。完全無害，可忽略。

---

## 六、前端整合（完整啟動流程）

系統分為三個服務，需全部啟動：

| 服務 | 指令 | Port | 說明 |
|------|------|------|------|
| Node.js Server | `cd Server && node index.js` | 3001 | 前端資料服務 |
| Crawler FastAPI | `cd Crawler && python main.py --mode server` | 8000 | 爬蟲觸發 |
| LSTM 預測伺服器 | `cd LSTM && venv\Scripts\activate && python serve.py` | 8001 | 模型預測 |

### 首次使用（只需一次）

```bash
# 1. 訓練跨股票模型
cd C:\Users\Eric\Desktop\coding\money\LSTM
venv\Scripts\activate
python train_cross.py         # 全部 8 種模型 × 所有股票

# 2. 啟動預測伺服器
python serve.py               # 保持此視窗開著
```

### 每次啟動

```bash
# 視窗 1：Node.js Server
cd C:\Users\Eric\Desktop\coding\money\Server
node index.js

# 視窗 2：Crawler
cd C:\Users\Eric\Desktop\coding\money\Crawler
python main.py --mode server

# 視窗 3：LSTM 預測伺服器
cd C:\Users\Eric\Desktop\coding\money\LSTM
venv\Scripts\activate
python serve.py
```

### 前端使用

開啟預測頁面 → 輸入股票代碼 → 選擇預測天數 → 點擊「執行預測（全部）」

| 前端模型名稱 | 實際模型 | 特點 |
|---|---|---|
| LSTM | M02 Stacked LSTM | 3 層堆疊，精確度高 |
| Prophet | M09 技術指標 LSTM | RSI/MACD/Bollinger 20 特徵 |
| GRU | M03 Bidirectional LSTM | 雙向學習趨勢 |

---

## 七、跨股票模型（Cross-Stock）

跨股票模型使用 **Window-level Z-score 正規化**，讓同一個模型可以預測任意股票，
包含訓練時未見過的股票。

### 訓練跨股票模型

```bash
# 訓練全部模型（使用所有股票資料）
python train_cross.py

# 限定模型
python train_cross.py --models m01_vanilla m02_stacked

# 限定訓練用股票（但模型可推論任意股票）
python train_cross.py --stocks 2330 2317 0050
```

模型儲存於：`saved_models/cross_stock/{model_key}.keras`

### 推論（預測任意股票）

```bash
# 預測明日收盤（從 DB 取最新資料）
python predict.py --stock 2330

# 指定模型
python predict.py --stock 2330 --model m02_stacked

# 滾動預測未來 5 天
python predict.py --stock 2330 --days 5

# 手動輸入最近 20 天收盤價（不需 DB）
python predict.py --stock 9999 --prices 100 102 98 105 ...
```

### 個股 vs 跨股票的差異

| | 個股模型（train_all.py） | 跨股票模型（train_cross.py） |
|--|------------------------|---------------------------|
| 訓練資料 | 單一股票 | 所有股票合併 |
| 正規化 | MinMaxScaler（全域） | Z-score（每窗口自適應） |
| 推論對象 | 只能預測訓練過的股票 | 任意股票（含未訓練過的） |
| 準確度 | 個股較高 | 泛化性較好 |

---

## 七、目錄結構快速參考

```
LSTM/
├── venv/                  ← 虛擬環境（不要手動修改）
├── train_all.py           ← 個股訓練腳本
├── train_cross.py         ← 跨股票訓練腳本
├── predict.py             ← 跨股票推論腳本
├── config.py              ← 超參數設定
├── models/                ← 10 種 LSTM 模型
├── results/               ← 訓練輸出（指標 + 圖表）
│   └── cross_stock/       ← 跨股票訓練結果
├── saved_models/
│   └── cross_stock/       ← 跨股票模型檔 (.keras)
└── report/                ← 最終報告
```
