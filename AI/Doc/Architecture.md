# 系統架構文件 (Architecture)

> 最後更新：2026-03-17

---

## 0. 服務架構總覽

```
┌─────────────────────────────────────────────────────────────┐
│                        使用者瀏覽器                          │
│              React + Vite  (port 5173)                      │
└──────────────────────┬──────────────────────────────────────┘
                       │ HTTP / fetch
┌──────────────────────▼──────────────────────────────────────┐
│              Node.js / Express Server  (port 3001)          │
│  ・直連 PostgreSQL（查詢、寫入新聞）                         │
│  ・Proxy /crawler/* → FastAPI :8000                         │
└──────────┬───────────────────────────┬───────────────────────┘
           │ pg driver                 │ HTTP proxy
┌──────────▼──────────┐   ┌────────────▼────────────────────┐
│   PostgreSQL :5432  │   │  FastAPI (Python)  (port 8000)  │
│   Database: Stock   │   │  ・爬蟲觸發 / 狀態查詢           │
│   ・stock_info      │◄──│  ・FinMind SDK 抓取資料          │
│   ・stock_daily_    │   │  ・UPSERT 寫入 DB               │
│     prices          │   └────────────┬───────────────────┘
│   ・stock_chip_     │                │ FinMind SDK
│     analysis        │   ┌────────────▼───────────────────┐
│   ・user_news       │   │       FinMind API               │
└─────────────────────┘   │  (台股行情 / 三大法人 / 基本資訊)│
                          └────────────────────────────────┘
```

### 啟動指令

```bash
# 1. Crawler FastAPI（爬蟲服務）
cd Crawler && python main.py --mode server     # port 8000

# 2. Node.js Server（資料服務）
cd Server && npm run dev                       # port 3001

# 3. React 前端
cd Screen && npm run dev                       # port 5173

# 4. 排程器（Iteration 36 起建議常駐，不再靠 start-dev.bat 手動開）
powershell -ExecutionPolicy Bypass -File Crawler\install_scheduler_task.ps1
#    → 註冊 Windows 工作排程器「MoneyScheduler」：登入即啟動、失敗自動重啟、
#      日誌在 Crawler\logs\scheduler.log；啟動時會補跑當天錯過的每日任務
#    → 移除：Crawler\uninstall_scheduler_task.ps1
#    → start-dev.bat 偵測到 MoneyScheduler 在跑就不會再開第二份
```

---

## 1. 資料採集子系統 (Crawler)

**目標：** 透過 FinMind API 取得台股結構化資料，寫入 PostgreSQL。

### 技術規格

- **核心框架：** FinMind Python SDK（`pip install FinMind`）
  - 取代直接爬取 TWSE，使用結構化 API 取得乾淨資料
  - 支援 Token 認證（免費額度：30 次/小時；Token：600 次/小時）
  - 設定：`Crawler/config.py` → `FINMIND["token"]`
- **爬蟲入口：** `Crawler/scrapers/finmind_scraper.py`
  - `FinMindScraper.fetch_prices()` → `stock_daily_prices`
  - `FinMindScraper.fetch_chips()` → `stock_chip_analysis`
  - `FinMindScraper.fetch_stock_info()` → `stock_info`

### 觸發方式

| 觸發方式 | 說明 | 日期範圍 |
|----------|------|----------|
| 前端查詢（新股票） | `POST /crawler/run`，無日期參數 | 自動：最近 90 天 |
| 前端「資料量不足」 | `POST /crawler/run`，無日期參數，自動偵測 | 自動：最近 90 天 |
| 前端「歷史資料補充」 | `POST /crawler/run` + `start_date` / `end_date` | 自訂，上限 365 天 |
| CLI 手動執行 | `python main.py --mode stock --stocks 2330` | `--date` 往前 90 天 |
| 定時排程 | `python main.py --mode schedule`（或 `install_scheduler_task.ps1` 常駐） | 每日 18:00，最近 7 天；程序啟動時若當天已錯過則補跑一次 |
| 每週全模型預測 | 排程器每週日 08:00（`weekly_forecast.run`） | 所有股票 × 所有模型，下一週與下下週；上個週日沒跑則啟動時補跑 |

### 歷史補充 API 規格

```
POST /crawler/run
Body: {
  stock_id:   string,         // 股票代碼（必填）
  start_date: string | null,  // YYYY-MM-DD，歷史起始日（選填）
  end_date:   string | null,  // YYYY-MM-DD，歷史結束日（選填）
}

- 未提供日期 → 近期模式（最近 90 天），受 30 分鐘冷卻限制
- 提供日期   → 歷史補充模式，跳過冷卻，單次最長 365 天
- end_date 不可超過今日，超過自動修正

Response: { status, task_id, mode: "recent" | "historical" }
status 值: "started" | "already_running" | "rate_limited"
```

### 爬蟲保護機制（四層）

| 層 | 位置 | 保護內容 |
|----|------|---------|
| 1 | 前端 ref | `autoCrawledRef`：每次手動搜尋只允許自動觸發一次，防 auto-reload 迴圈 |
| 2 | 前端 localStorage | `crawl_ts_{id}`：30 分鐘冷卻，近期模式前端直接攔截 |
| 3 | 後端 dict | `_crawl_done_at`：30 分鐘冷卻，近期模式後端拒絕，回傳 `rate_limited` |
| 4 | 後端 set | `_running_tasks`：並發鎖，同一股票不能同時執行兩個爬蟲 |

> 歷史補充模式**跳過**第 2、3 層冷卻限制（不同日期範圍視為不同任務）

---

## 2. Node.js 資料服務 (Server)

**目標：** 前端的單一資料出口，直連 PostgreSQL，並 Proxy 爬蟲請求至 FastAPI。

### 技術規格

- **框架：** Express.js（port 3001）
- **資料庫驅動：** `pg`（node-postgres）連線池
- **檔案結構：**
  ```
  Server/
  ├── index.js          # 啟動入口（執行 Migration、掛載路由、初始化資料表）
  ├── db.js             # PostgreSQL 連線池
  ├── lib/
  │   ├── proxy.js      # FastAPI Proxy 工具函式
  │   └── migrate.js    # Migration runner（啟動時自動執行）
  ├── migrations/
  │   └── 001_add_industry_index.sql  # stock_info.industry_type 索引
  └── routes/
      ├── stocks.js     # /stocks 相關端點
      ├── crawler.js    # /crawler/* proxy
      ├── news.js       # /news 端點
      └── model.js      # /model/* stubs
  ```

### API 端點

| 端點 | 說明 |
|------|------|
| `GET /stocks/industries` | 產業類別清單（含各類股票數），依數量排序 |
| `GET /stocks/:id` | 個股基本資訊 + 最新行情 + 最新籌碼 |
| `GET /stocks?tracked=true[&industry=X]` | 追蹤中股票，可依產業篩選 |
| `GET /stocks?max_price=N[&industry=X]` | 依預算篩選可買股票，可依產業篩選 |
| `GET /stocks/:id/prices?days=N` | 最近 N 天行情（預設 90，上限 365） |
| `GET /stocks/:id/prices?start_date=&end_date=` | 指定日期區間行情（無上限） |
| `GET /stocks/:id/prices` | 資料庫全部歷史行情 |
| `GET /stocks/:id/chips?days=N` | 三大法人籌碼（預設 20，上限 365） |
| `GET /stocks/:id/institutional?days=N` | 三大法人持股變化：每日買賣超 + 期間累計 + 外資真實持股 + 收盤價（預設 60，上限 1825） |
| `GET /forecast/weekly` | 每週自動預測最新一次執行（每檔一列：LSTM 兩週摘要 + 各模型），Proxy → FastAPI :8000 |
| `GET /forecast/weekly/status` | 每週預測是否執行中、下次排程時間，Proxy → FastAPI :8000 |
| `POST /forecast/weekly/run` | 手動補跑每週預測（背景執行），Proxy → FastAPI :8000 |
| `POST /crawler/run` | 觸發爬蟲，Proxy → FastAPI :8000 |
| `GET /crawler/status/:id` | 查詢爬蟲狀態，Proxy → FastAPI :8000 |
| `GET /news` | 使用者提交新聞列表（最新 200 筆） |
| `POST /news` | 儲存使用者提交的新聞至 `user_news` 表 |
| `GET /model/predict` | 模型預測（Stub，待實作） |
| `POST /model/retrain` | 手動重訓（Stub，待實作） |

### prices 端點查詢優先順序

```
start_date + end_date 同時有值 → 指定日期區間（歷史查詢，無日數上限）
days 有值                      → 今天往前 N 天（上限 365）
無任何參數                     → 資料庫全部歷史資料
```

---

## 3. 前端 (Screen)

**目標：** 提供股票查詢、爬蟲觸發、圖表呈現的互動介面。

### 技術規格

- **框架：** React 18 + Vite（`Screen/`，port 5173）
- **圖表：** ApexCharts（`react-apexcharts`）
- **API 呼叫：** `src/services/api.js`（`BASE = http://localhost:3001`）

### 頁面清單

| 頁面 | 說明 |
|------|------|
| 市場總覽（Overview） | 追蹤股票清單，含產業分布 + 產業篩選 + 最新行情 |
| 預算查詢（BudgetSearch） | 輸入金額 + 產業篩選，篩選可買股票，可跳轉個股分析 |
| 週預測（WeeklyForecast） | 每週日 08:00 排程自動用全部模型預測所有股票的下一週與下下週，開頁即顯示最新一次（Iteration 37） |
| 個股分析（StockAnalysis） | 查詢 / 爬蟲 / 多種統計圖表 / 歷史補充 |
| 新聞輸入（NewsInput） | 貼上新聞，寫入 `user_news` 表 |
| 新聞情緒（NewsSentiment） | 顯示已提交新聞（NLP 圖表待部署） |
| 趨勢預測（Prediction） | LSTM / Prophet / GRU 三模型預測介面，含個別 + 整合視圖（後端 Stub 待實作） |
| 查詢紀錄（QueryHistory） | localStorage 記錄，可跳轉個股分析 |

### 個股分析頁圖表（由上而下）

1. 最新行情 4 張 Metric Card（收盤價 / 成交量 / 三大法人 / 產業）
2. 日 K 線（Candlestick）+ 成交量（Bar）
3. 期間統計 4 張 Metric Card（最高 / 最低 / 均收 / 總量）
4. 收盤價走勢折線圖
5. 日漲跌幅（%）長條圖（上漲綠，下跌紅）
6. 每日行情明細表格
7. 三大法人籌碼長條圖（近 20 日）
8. 歷史資料補充卡片（日期選擇器 + 進度條）

---

## 4. 資料庫 (PostgreSQL)

**資料庫名稱：** `Stock`（`localhost:5432`）

| 資料表 | 說明 |
|--------|------|
| `stock_info` | 個股基本資訊（代碼、名稱、產業、市場、is_tracking） |
| `stock_daily_prices` | 每日行情（開高低收、成交量、漲跌值、漲跌幅） |
| `stock_chip_analysis` | 三大法人每日買賣超（外資、投信、自營商；單位為股） |
| `stock_foreign_holding` | 外資真實持股（股數、佔比、已發行股數；Iteration 35） |
| `user_news` | 使用者提交的新聞（平台、標題、內容、代碼標籤） |

詳見 `AI/Doc/DB.md`

---

## 5. NLP 模組（待實作）

**目標：** 將原始文本轉化為模型可理解的結構化特徵。

- **清洗流程：** 去除 HTML 標籤、停用詞過濾、繁簡轉換（OpenCC）
- **NLP 引擎：** BERT-base-Chinese 情感三分類（利多 / 中立 / 利空）
- **特徵向量化：** TF-IDF 或 Word2Vec

---

## 6. 趨勢預測模型（待實作）

**目標：** 結合時間序列與情緒指標，產出產業走勢預測。

- **模型：** LSTM / GRU（短期）、Prophet（中長期）
- **輸入特徵：** 新聞情緒分數、關鍵字頻率、股價與市場指數
- **評估指標：** MAE、RMSE、混淆矩陣方向準確率

---

## 7. 開發進度 (Roadmap)

| 階段 | 重點任務 | 狀態 |
|------|----------|------|
| 第一階段 | 爬蟲 + DB + Node.js Server + 前端基礎頁面 | ✅ 完成 |
| 第一階段+ | 歷史資料補充、爬蟲保護機制、統計圖表 | ✅ 完成 |
| 第一階段++ | 產業類型分類、Migration 機制、產業篩選前端 | ✅ 完成 |
| 第二階段 | 新聞爬蟲 + NLP 情感分析 | ⏳ 待開始 |
| 第三階段 | LSTM / GRU / Prophet 預測模型訓練 | ⏳ 待開始 |
| 第四階段 | 模型串接前端預測頁面（`Prediction.jsx`） | ✅ 前端 UI 完成，後端 Stub 待實作 |
