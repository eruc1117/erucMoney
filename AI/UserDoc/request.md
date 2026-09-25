# 三模型加權投票決策系統 — 規格文件

**建立日期：** 2026-03-22
**目標股票：** 20 檔電子股（價格區間 20~40 元）
**決策輸出：** Buy / Sell / Hold

---

## 一、系統概觀

整合三個異質模型的輸出，透過**加權多數決（Weighted Voting）**產生最終投資建議。
每個模型負責不同維度的分析，彼此互補，避免單一訊號過度擬合。

```
stock_daily_prices  ──► 模型一（LSTM）        ──┐
user_news           ──► 模型二（新聞特派員）    ──┼──► 投票引擎 ──► voting_results
stock_chip_analysis ──► 模型三（籌碼觀測員）    ──┘
```

---

## 二、模型定義

### 模型一：時序專家（LSTM — 數值驅動）

| 項目 | 內容 |
|------|------|
| 演算法 | LSTM（現有 serve.py） |
| 資料來源 | `stock_daily_prices`（近 30 天 K 線、MA、RSI） |
| 決策邏輯 | 判斷目前股價是否處於超賣區或上升趨勢中 |

**輸出規則**
- `Buy`：價格回測支撐點或啟動帶量攻擊
- `Sell`：破位跌穿月線或乖離率過高
- `Hold`：狹幅震盪

---

### 模型二：新聞特派員（FinBERT + XGBoost — 訊息驅動）

> **架構升級：** 從單純「情緒分析」升級為**時序滯後影響模型（Time-Lagged Influence Model）**，使模型能學習「過去新聞如何影響未來股價」。

#### 模型規格

| 項目 | 內容 |
|------|------|
| 演算法 | FinBERT（情緒提取）+ XGBoost（非線性回歸預測） |
| 學習目標 | 新聞特徵與「T+N 股價超額變動」的相關性 |
| 輸入窗口 | 過去 72 小時的新聞文本 + 過去 5 日的價量特徵 |
| 決策輸出 | 預測新聞帶來的「股價變動機率值」（0~100%） |

#### 雙階段學習架構

現有邏輯偏向「當下情緒 = 當下買賣」，但新聞影響通常有**發酵期**，改為：

- **階段 A（特徵工程）：** 使用 FinBERT 將新聞轉化為 `Sentiment_Score`（-1 到 +1）與 `Embedding_Vector`
- **階段 B（時序學習）：** 使用 XGBoost 學習「T+0 的新聞」對「T+1 到 T+5 股價」的貢獻度

#### 核心特徵表（XGBoost 輸入矩陣）

| 特徵類別 | 欄位名稱 | 說明 |
|----------|----------|------|
| 情緒特徵 | `Avg_Sentiment_24h` | 過去 24 小時新聞情緒的移動平均 |
| 熱度特徵 | `News_Volume_Gap` | 今日新聞量與過去 7 日平均的差值（爆量通常代表轉折） |
| 關鍵詞特徵 | `Keyword_Recovery_Hit` | 布林值：是否出現 "Inventory Depletion" 等強效關鍵詞 |
| 股價滯後 | `Price_Return_T_Minus_1` | 昨日漲跌幅（判斷新聞是否已被市場反應） |
| 產業連動 | `Sector_Sentiment` | 同產業（20 檔電子股）的整體情緒平均值 |

#### 標籤（Label）定義：超額報酬（Alpha）

- **修正前：** 預測明天會不會漲
- **修正後：** 預測「新聞發布後 3 天內，該股是否跑贏大盤（TAIEX）」

> 過濾掉大盤集體上漲的噪音，精準抓出新聞帶來的帶動力。

#### 時間衰減權重（Time Decay）

新聞影響力會隨時間消失，XGBoost 加入衰減機制：

| 時間點 | 影響權重 |
|--------|----------|
| T+1 天 | 100% |
| T+2 天 | 60% |
| T+3 天 | 30% |
| T+4 天以後 | 忽略 |

> 避免模型將一週前的新聞與今天的股價強行連結。

#### 針對電子工業（20~40 元）的客製化邏輯

此類股票（如：聯電、宏碁、仁寶）對**外資報告**與**營收公告**極度敏感：

- 標題含「**營收（Revenue）**」、「**法說會（Conference）**」的新聞，給予更高加權係數
- 關鍵詞庫擴充：除 "Demand Recovery" 外，加入：
  - `Capacity Utilization`（產能利用率）
  - `Gross Margin`（毛利率）

**輸出規則**
- `Buy`：負面情緒轉向正面，或利多消息頻發
- `Sell`：突發重大利空（禁令、財報雷）
- `Hold`：消息面平淡

---

### 模型三：籌碼觀測員（Random Forest — 結構驅動）

| 項目 | 內容 |
|------|------|
| 演算法 | Random Forest |
| 資料來源 | `stock_chip_analysis`（三大法人買賣超、融資融券） |
| 決策邏輯 | 判斷錢是誰在買；外資持續吸貨 → 多頭訊號 |

**輸出規則**
- `Buy`：法人連續 3 日大買且散戶退場
- `Sell`：法人由買轉賣且高檔融資暴增
- `Hold`：法人與散戶對做，方向不明

---

## 三、投票機制

### 加權多數決公式

```
vote_score = w1 × score(M1) + w2 × score(M2) + w3 × score(M3)

score 對照：Buy = +1  /  Hold = 0  /  Sell = -1

最終決策：
  score ≥  0.3  → Buy
  score ≤ -0.3  → Sell
  其餘           → Hold
```

### 情境範例

| 情境 | 模型一 | 模型二 | 模型三 | 最終決策 |
|------|--------|--------|--------|----------|
| 強勢買入 | Buy（向上突破） | Buy（利多頻傳） | Buy（法人大買） | **強力買入 (3:0)** |
| 謹慎買入 | Buy（超跌） | Hold（無消息） | Buy（法人卡位） | **買入 (2:0:1)** |
| 虛假繁榮 | Buy（價格漲） | Sell（利空隱憂） | Sell（法人出貨） | **觀望/賣出 (1:2)** |
| 無感盤整 | Hold | Hold | Hold | **持有 (0:0:3)** |

---

## 四、權重策略

預設各模型權重均等（各 1/3），依股票特性微調：

| 股票類型 | 調整方向 | 範例 | 原因 |
|----------|----------|------|------|
| 權值股 | 籌碼模型 ↑ | 2303 聯電 | 外資動向決定走勢 |
| 話題股 | 新聞模型 ↑ | 2388 威盛 | 消息面驅動極大 |
| 均衡型 | 維持預設 | — | 無特殊性質 |

```python
WEIGHTS_DEFAULT = {"m1": 0.34, "m2": 0.33, "m3": 0.33}

WEIGHTS_BY_STOCK = {
    "2303": {"m1": 0.25, "m2": 0.25, "m3": 0.50},  # 權值股 → 籌碼加重
    "2388": {"m1": 0.25, "m2": 0.50, "m3": 0.25},  # 話題股 → 新聞加重
}
```

---

## 五、資料庫設計

### 新增資料表

#### `news_features`（新聞情緒特徵，每小時更新）

```sql
CREATE TABLE news_features (
    id            SERIAL PRIMARY KEY,
    stock_id      VARCHAR(10)  NOT NULL,
    feature_date  DATE         NOT NULL,
    sentiment     FLOAT,                  -- -1.0 ~ +1.0
    keyword_hits  JSONB,                  -- {"Demand Recovery": 2, ...}
    article_count INT DEFAULT 0,
    updated_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (stock_id, feature_date)
);
```

#### `voting_results`（投票結果，每日 20:00 寫入）

```sql
CREATE TABLE voting_results (
    id            SERIAL PRIMARY KEY,
    stock_id      VARCHAR(10)  NOT NULL,
    vote_date     DATE         NOT NULL,
    m1_signal     VARCHAR(4),             -- Buy / Sell / Hold
    m2_signal     VARCHAR(4),
    m3_signal     VARCHAR(4),
    final_signal  VARCHAR(4),
    score         FLOAT,
    weights       JSONB,                  -- {"m1": 0.4, "m2": 0.3, "m3": 0.3}
    m1_reason     TEXT,
    m2_reason     TEXT,
    m3_reason     TEXT,
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (stock_id, vote_date)
);
```

---

## 六、資料更新頻率

| 時間 | 動作 | 對應資料表 |
|------|------|-----------|
| 每日收盤後 | 更新股價與籌碼資料 | `stock_daily_prices`, `stock_chip_analysis` |
| 每小時 | 執行新聞爬蟲，計算情緒特徵 | `news_features` |
| 每日 20:00 | 三模型投票，寫入結果 | `voting_results` |

---

## 七、實作方案

### 7.1 模型輸出標準介面

所有模型統一回傳以下格式：

```python
{
    "stock_id":   "2303",
    "signal":     "Buy",      # Buy | Sell | Hold
    "confidence": 0.82,       # 0.0 ~ 1.0
    "reason":     "法人連續 3 日買超，外資持股比 +1.2%"
}
```

### 7.2 實作檔案對照

| 檔案 | 說明 |
|------|------|
| `Crawler/model2_news.py` | 查詢 `user_news`，計算情緒加總，輸出信號 |
| `Crawler/model3_chip.py` | 查詢 `stock_chip_analysis` 近 3 日，判斷法人方向 |
| `LSTM/model1_lstm.py` | 呼叫現有 serve.py，將預測價格轉換為信號 |
| `Crawler/voting_engine.py` | 合併三模型輸出，執行加權投票，寫入 `voting_results` |

### 7.3 Node.js API 端點（新增）

| 方法 | 路徑 | 說明 |
|------|------|------|
| `GET` | `/voting` | 取得所有股票最新投票結果 |
| `GET` | `/voting/:stock_id` | 取得單一股票歷史投票記錄 |
| `POST` | `/voting/run` | 手動觸發投票（proxy → FastAPI） |

### 7.4 前端頁面（新增 VotingDashboard）

- 列表顯示 20 檔股票目前投票狀態
- 每列：股票代碼 ｜ M1 ｜ M2 ｜ M3 ｜ **最終建議** ｜ 分數條
- 點擊展開：查看三模型各自的 reason + confidence
- 可手動調整單一股票模型權重並即時重新計算

---

## 八、開發優先順序

| 順序 | 項目 | 難度 | 說明 |
|------|------|------|------|
| 1 | `model3_chip.py`（籌碼模型） | ★☆☆ | DB 已有資料，純規則判斷 |
| 2 | `model2_news.py`（新聞模型） | ★☆☆ | 移植現有 analyzeSentiment 邏輯 |
| 3 | `voting_engine.py`（投票引擎） | ★☆☆ | 純數學計算，無外部依賴 |
| 4 | DB 建表 + Node.js API | ★★☆ | 新增兩張表與三個路由 |
| 5 | 前端 VotingDashboard | ★★☆ | 新頁面，參考現有 Prediction 頁 |
| 6 | `model1_lstm.py`（LSTM 接入） | ★★★ | 需先完成模型訓練 |
| 7 | 排程自動觸發（每日 20:00） | ★★★ | 需爬蟲與模型穩定後加入 |
