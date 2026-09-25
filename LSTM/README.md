# LSTM 股票預測模型

使用 10 種 LSTM 架構對台股 `stock_daily_prices` 中的歷史資料進行訓練與評估。

---

## 目錄結構

```
LSTM/
├── config.py              # 全域設定（DB、超參數、路徑）
├── data_loader.py         # PostgreSQL 資料載入 + 序列建立
├── features.py            # 技術指標特徵工程
├── evaluate.py            # 評估指標 + 視覺化
├── report_generator.py    # HTML / Markdown 報告產生
├── train_all.py           # 主訓練腳本
├── models/
│   ├── m01_vanilla.py     # M01：Vanilla LSTM
│   ├── m02_stacked.py     # M02：Stacked LSTM（3 層）
│   ├── m03_bidirectional.py # M03：Bidirectional LSTM
│   ├── m04_attention.py   # M04：LSTM + Bahdanau Attention
│   ├── m05_cnn_lstm.py    # M05：CNN-LSTM
│   ├── m06_multifeature.py # M06：Multi-feature LSTM（OHLCV + 籌碼）
│   ├── m07_seq2seq.py     # M07：Seq2Seq LSTM（預測未來 5 天）
│   ├── m08_mc_dropout.py  # M08：MC Dropout LSTM（不確定性量化）
│   ├── m09_technical.py   # M09：LSTM + 技術指標（20 特徵）
│   └── m10_ensemble.py    # M10：Ensemble（M01+M02+M03 加權集成）
├── results/               # 訓練結果（metrics.json、predictions.json、圖表）
├── saved_models/          # 儲存的 Keras 模型（.keras）
└── report/                # 最終報告（report.html、report.md、summary.csv）
```

---

## 10 種模型說明

| # | 模型名稱 | 特徵 | 特點 |
|---|----------|------|------|
| M01 | Vanilla LSTM | close only | 基準模型，單層 64 units |
| M02 | Stacked LSTM | close only | 3 層堆疊（128→64→32），學習高階時序 |
| M03 | Bidirectional LSTM | close only | 雙向同時學習前後時序依賴 |
| M04 | LSTM + Attention | close + volume | Bahdanau 注意力機制，聚焦關鍵時間步 |
| M05 | CNN-LSTM | OHLCV（5） | Conv1D 提取局部模式 + LSTM 長期依賴 |
| M06 | Multi-feature LSTM | OHLCV + 籌碼（10） | 量價 + 法人籌碼融合 |
| M07 | Seq2Seq LSTM | close only | 一次預測未來 5 個交易日 |
| M08 | MC Dropout LSTM | close only | 貝葉斯不確定性估計（±2σ 信賴區間） |
| M09 | LSTM + Technical | OHLCV + 技術指標（20） | MA/RSI/MACD/Bollinger 全技術面 |
| M10 | Ensemble | — | M01+M02+M03 加權平均（0.25/0.45/0.30） |

---

## 安裝

```bash
pip install -r requirements.txt
```

> 需已安裝 PostgreSQL 並啟動 Node.js Server（資料來源：`Stock` 資料庫）

---

## 執行

### 訓練所有股票、所有模型
```bash
cd LSTM
python train_all.py
```

### 僅訓練指定股票
```bash
python train_all.py --stocks 2330 2317 0050
```

### 僅執行指定模型
```bash
python train_all.py --models m01_vanilla m02_stacked m10_ensemble
```

### 訓練完不產生報告
```bash
python train_all.py --skip-report
```

### 重新產生報告（已有結果）
```bash
python report_generator.py
```

---

## 評估指標

| 指標 | 說明 | 越好 |
|------|------|------|
| MAE | 平均絕對誤差（TWD） | 越低越好 |
| RMSE | 均方根誤差（TWD） | 越低越好 |
| MAPE | 平均絕對百分比誤差（%） | 越低越好 |
| DA | 方向準確率（漲跌預測準確率，%） | 越高越好 |

---

## 輸出說明

### results/{model_key}/{stock_id}/
- `metrics.json` — 測試集評估指標
- `predictions.json` — 實際值 vs 預測值（含 M08 的 y_std）
- `prediction.png` — 預測圖表
- `loss.png` — 訓練/驗證 Loss 曲線

### saved_models/{model_key}/{stock_id}.keras
- Keras 格式模型，可直接 `tf.keras.models.load_model()` 載入

### report/
- `summary.csv` — 所有股票 × 模型的指標摘要
- `report.html` — 完整視覺化報告（在瀏覽器開啟）
- `report.md` — Markdown 格式摘要

---

## 設定調整

編輯 `config.py`：

```python
LOOKBACK    = 20     # 輸入序列長度（天數）
FORECAST_STEPS = 5   # M07 Seq2Seq 預測天數
EPOCHS      = 100    # 最大訓練輪次
BATCH_SIZE  = 32
PATIENCE    = 15     # Early Stopping patience
```

---

## 資料需求

- PostgreSQL `Stock` 資料庫（localhost:5432）
- `stock_daily_prices`：至少 60 筆以上資料（建議 90 天以上）
- `stock_chip_analysis`：M06 使用，無資料時自動補 0
