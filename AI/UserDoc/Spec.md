# 需求規格 (Spec)

> 最後更新：2026-08-06

---

## 主要需求

| # | 需求描述 | 狀態 | 實作位置 |
|---|----------|------|----------|
| 1 | 輸入金額後，比對資料庫抓取可購買範圍的股票 | ✅ 已完成 | `BudgetSearch.jsx` → `GET /stocks?max_price=` |
| 2 | 模型分析未來走向，產出圖表 | ✅ UI 完成，後端 Stub | `Prediction.jsx`（LSTM / Prophet / GRU 三模型介面，含整合視圖） |
| 3 | 畫面輸入需要撈取的股票資料 | ✅ 已完成 | `StockAnalysis.jsx` → `GET /stocks/:id` |
| 4 | 由使用者畫面貼上新聞資料 | ✅ 已完成 | `NewsInput.jsx` → `POST /news` |
| 5 | 紀錄查詢過的資料 | ✅ 已完成 | `QueryHistory.jsx` → `localStorage` |
| 6 | 輸入的股票不在資料庫中，才執行爬蟲 | ✅ 已完成 | `StockAnalysis.jsx` — 404 → 觸發爬蟲確認 |
| 7 | 新聞輸入頁面 | ✅ 已完成 | `NewsInput.jsx` — 寫入 `user_news` 表（PostgreSQL） |
| 8 | 清除假資料，資料由 Crawler 寫入的資料庫為主 | ✅ 已完成 | 所有頁面改為從 PostgreSQL 讀取，mockData 全部移除 |
| 9 | 獨立 Node.js Server，處理資料庫與前端資料 | ✅ 已完成 | `Server/index.js`，監聽 port 3001 |
| 10 | 執行爬蟲時，前端進度條 + 完成通知 | ✅ 已完成 | `StockAnalysis.jsx` — 模擬進度條 + Toast 倒數 |
| 11 | 個股分析加上時間範圍（預設1週，上限1個月，必填） | ✅ 已完成 | `StockAnalysis.jsx` — 1/2/3/4 週按鈕組 |
| 12 | 爬蟲能撈出過去資料並寫入資料庫 | ✅ 已完成 | 個股分析頁「歷史資料補充」卡片，自訂日期範圍，上限 365 天 |
| 13 | 點選追蹤股票時，顯示歷史資料及統計圖表 | ✅ 已完成 | `StockAnalysis.jsx` — K線、收盤走勢、日漲跌幅、每日明細、三大法人 |
| 14 | 新聞管理：PostgreSQL 儲存、查詢、修改、刪除、Modal 查看 | ✅ 已完成 | `NewsInput.jsx` — 搜尋列 + Modal + `PUT/DELETE /news/:id` |
| 15 | 自動爬取網路新聞（Yahoo Finance TW + CNN Business） | ✅ 已完成 | `NewsSentiment.jsx` → `POST /crawler/news` → `NewsScraper` |
| 16 | 三模型加權投票決策系統（規格見 `request.md`） | ✅ 管線已跑通 | `voting_engine.py` + `VotingDashboard.jsx`；排程自動投票待實作 |

---

## 需求細節

### 需求 1 — 預算查詢
- 輸入金額（元），系統換算「每張 1,000 股」所需單價上限
- 從 DB 篩選 `close_price <= max_price` 的股票，顯示可買張數、所需金額
- 結果可點「詳細分析」跳轉個股分析頁

### 需求 3 / 6 — 個股分析 + 爬蟲 Fallback
- 輸入股票代碼 → 查詢 DB → 若不存在（404）→ 詢問是否執行爬蟲
- 若存在但資料量不足（交易日 < 週數 × 3）→ 自動觸發爬蟲補充
- 爬蟲完成後 Toast 通知，5 秒倒數自動重新查詢

### 需求 10 — 爬蟲進度保護機制（四層）
1. 前端 `autoCrawledRef`：每次手動搜尋只允許自動觸發一次
2. 前端 `localStorage` 冷卻：同一股票 30 分鐘內不重複自動觸發
3. 後端 30 分鐘冷卻：`_crawl_done_at` 字典，近期模式受限
4. 後端並發鎖：`_running_tasks`，同股票不能同時執行兩個爬蟲

### 需求 11 — 時間範圍
- 選項：1 週 / 2 週 / 3 週 / 4 週（必選，預設 1 週）
- 切換週數 → 自動重新查詢 DB 行情（不需重新點擊查詢）
- 爬蟲固定抓取最近 90 天；前端查詢依 `weeks × 7` 日篩選

### 需求 12 — 歷史資料補充
- 位置：個股分析頁 → 向下捲動 → 「歷史資料補充」卡片
- 操作：選擇起始日、結束日 → 點「補充歷史資料」
- 規格：自訂日期範圍，單次上限 365 天，歷史補充模式跳過 30 分鐘冷卻
- API：`POST /crawler/run` Body 加上 `start_date` / `end_date`（YYYY-MM-DD）

### 需求 13 — 統計圖表（個股分析頁內容，由上而下）

頁面依序呈現以下圖表與元件：

#### 1. 最新行情指標卡（4 張）
- 收盤價（NTD）、成交量（張）、三大法人合計買賣超（張）、產業別

#### 2. K 線圖 (Candlestick Chart)
- **圖表類型：** K 線（Candlestick）+ 成交量柱狀圖（Bar，副圖）
- **X 軸：** 日期（Date），格式 YYYY/MM/DD
- **Y 軸（主圖）：** 股價，單位 NTD，動態範圍
- **Y 軸（副圖）：** 成交量，單位：張（股數 / 1,000）

#### 3. 期間統計指標卡（4 張）
- 區間最高、最低、均收（NTD）、總成交量（張）

#### 4. 收盤走勢圖 (Closing Price Trend)
- **圖表類型：** 折線圖（Line Chart）
- **X 軸：** 日期（Date）
- **Y 軸：** 收盤價（NTD）
- **附加線條：** MA5（週線）、MA20（月線），各以不同顏色呈現

#### 5. 日漲跌幅圖 (Daily Change Rate)
- **圖表類型：** 柱狀圖（Bar Chart）
- **X 軸：** 日期（Date）
- **Y 軸：** 漲跌幅（%），範圍 -10% ～ +10%（台股漲跌幅限制）
- **視覺規則：** 正值（漲）顯示綠色，負值（跌）顯示紅色，Y = 0 處有基準線

#### 6. 每日行情明細表格
- 欄位：日期、開盤、最高、最低、收盤（NTD）、成交量（張）、漲跌（NTD）、漲跌幅（%）

#### 7. 三大法人籌碼圖（近 20 日）
- **圖表類型：** 柱狀圖（Bar Chart），外資 / 投信 / 自營商分組
- **Y 軸：** 買賣超張數（正值買超，負值賣超）

#### 8. 歷史資料補充卡片
- 日期選擇器（起始日 / 結束日）+ 進度條 + 補充按鈕

### 需求 14 — 新聞管理（NewsInput 頁）
- **PostgreSQL 儲存：** 所有新聞（使用者提交 + 爬取）存入 `user_news` 表
- **查詢：** 搜尋列即時過濾（標題、內文、平台、股票代碼）
- **查看全文：** 點擊新聞卡片 → Modal 顯示完整內文
- **修改：** Modal 內「編輯」→ 修改平台、標題、代碼、內文 → 送 `PUT /news/:id`
- **刪除：** Modal 內「刪除」→ 二次確認 → 送 `DELETE /news/:id`

### 需求 15 — 自動爬取網路新聞
- **來源：** Yahoo Finance 台灣（`tw.news.yahoo.com/finance/`）& CNN Business
- **觸發：** 新聞情緒頁 → 「立即爬取首頁新聞」按鈕 → `POST /crawler/news`
- **流程：**
  1. Node.js `/crawler/news` → Proxy → FastAPI `/crawler/news`
  2. FastAPI 啟動背景執行緒，呼叫 `NewsScraper().scrape_all()`
  3. `insert_news_articles()` 寫入 `user_news`（相同 platform+title 略過）
  4. 前端每 2.5 秒輪詢 `GET /crawler/news/status`，完成後重新整理列表
- **抓取量：** 每來源最多 25 則標題（含自動偵測台股代碼）
- **去重：** 相同 `(platform, title)` 不重複寫入

---

## 資料來源

### 網路新聞
| 平台 | 語言 | URL |
|------|------|-----|
| Yahoo Finance 台灣 | 中文 | https://tw.news.yahoo.com/finance/ |
| CNN Business | 英文 | https://edition.cnn.com/business |

### 股市資料
- **主要來源：** FinMind API（`pip install FinMind`）
  - 免費匿名：30 次/小時；Token 認證：600 次/小時
  - 設定：`Crawler/config.py` → `FINMIND["token"]`
- **參考文件：** `AI/Doc/DataSources.md`

---

## 模型（待實作）
- 訓練 3 個不同風格模型（LSTM、GRU、Prophet）
- 個別或整合進行未來一週股票預測
- 前端 `Prediction.jsx` 已有 Stub，等待模型模組接入

---

## 服務架構

```
React (Vite) :5173
    ↓ HTTP
Node.js Server :3001  ──→  PostgreSQL :5432/Stock
    ↓ Proxy /crawler/*
FastAPI (Python) :8000  ──→  FinMind API
                        ──→  Yahoo Finance TW（新聞爬蟲）
                        ──→  CNN Business（新聞爬蟲）
```

### API 端點（Node.js Server :3001）

| 端點 | 說明 | 狀態 |
|------|------|------|
| `GET /stocks/:id` | 個股基本資訊 + 最新行情 + 最新籌碼 | ✅ |
| `GET /stocks?max_price=N` | 依預算篩選可買股票 | ✅ |
| `GET /stocks?tracked=true` | 追蹤中股票（Overview 頁使用） | ✅ |
| `GET /stocks/:id/prices?days=N` | 最近 N 天行情（預設 90，上限 365） | ✅ |
| `GET /stocks/:id/prices?start_date=&end_date=` | 指定日期區間行情（無上限） | ✅ |
| `GET /stocks/:id/prices` | 資料庫全部歷史行情 | ✅ |
| `GET /stocks/:id/chips?days=N` | 三大法人籌碼（預設 20，上限 365） | ✅ |
| `GET /stocks/:id/institutional?days=N` | 三大法人持股變化（買賣超累計 + 外資真實持股；「法人持股」頁） | ✅ |
| `POST /crawler/run` | 觸發股票爬蟲，Proxy → FastAPI :8000 | ✅ |
| `GET /crawler/status/:id` | 查詢股票爬蟲狀態，Proxy → FastAPI :8000 | ✅ |
| `POST /crawler/news` | 觸發新聞爬蟲（Yahoo + CNN），Proxy → FastAPI | ✅ |
| `GET /crawler/news/status` | 查詢新聞爬蟲狀態，Proxy → FastAPI | ✅ |
| `GET /news` | 使用者提交 + 爬取新聞列表（PostgreSQL `user_news`） | ✅ |
| `POST /news` | 儲存使用者提交的新聞 | ✅ |
| `PUT /news/:id` | 修改新聞（標題、平台、內文、代碼） | ✅ |
| `DELETE /news/:id` | 刪除新聞 | ✅ |
| `GET /model/predict` | 模型預測 → LSTM 伺服器 :8001（`serve.py`，10 種模型） | ✅ |
| `POST /model/retrain` | 模型重訓（Stub，待實作） | ⏳ |
| `GET /voting` | 全部股票最新投票結果（`voting_results`） | ✅ |
| `GET /voting/:stock_id` | 單一股票歷史投票記錄 | ✅ |
| `POST /voting/run` | 手動觸發三模型投票，Proxy → FastAPI :8000 | ✅ |
| `GET /voting/status` | 查詢投票執行狀態，Proxy → FastAPI :8000 | ✅ |
| `GET /forecast/weekly` | 每週自動預測（全模型 × 全股票，下一週與下下週）最新結果 | ✅ |
| `POST /forecast/weekly/run` | 手動補跑每週預測 | ✅ |

### 啟動指令
```bash
# 一鍵啟動（開發模式）
start-dev.bat

# 或個別啟動：
# 1. Crawler FastAPI
cd Crawler && python main.py --mode server

# 2. Node.js Server
cd Server && npm run dev

# 3. React 前端
cd Screen && npm run dev
```

### 安裝新聞爬蟲依賴
```bash
cd Crawler
pip install beautifulsoup4
# 或
pip install -r requirements.txt
```

---

## 已知問題 / Bug 紀錄

詳見 `AI/Doc/Bugs/bugs.md`

| ID | 問題 | 狀態 |
|----|------|------|
| BUG-001 | 預算查詢 pg 回傳 NUMERIC 為字串，`.toFixed()` crash | ✅ 已修復 |
| BUG-002 | 每日行情「漲跌」欄位 server SQL 未含 `change_value` | ✅ 已修復 |
| BUG-003 | 切換時間範圍後圖表不更新 | ✅ 已修復 |
| BUG-004 | 資料不足時未自動補充爬蟲 | ✅ 已修復 |
| BUG-005 | 自動爬蟲可能無限迴圈 / 頻率過高 | ✅ 已修復（四層保護） |
| FEAT-001 | 新增歷史資料補充功能（需求 12） | ✅ 已實作 |
| FEAT-002 | 新聞 PostgreSQL 儲存 + 查詢/修改/刪除/Modal（需求 14） | ✅ 已實作 |
| FEAT-003 | 網路新聞爬蟲 Yahoo Finance TW + CNN Business（需求 15） | ✅ 已實作 |
