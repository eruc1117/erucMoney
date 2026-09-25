# 資料庫設計文件 (Database Design)

---

## 1. 原始新聞表 (Raw News - MongoDB) ⏳ 計畫中，尚未實作

> **注意：** 此表為第二階段（新聞爬蟲）規劃設計，目前尚未建立。
> 現階段使用者新聞由前端直接提交，儲存於 PostgreSQL `user_news` 表（見 2.4 節）。

用於存放爬蟲的第一手資料，不做過多處理，確保資料追溯性。

```json
{
  "source_id": "unique_hash_of_url",
  "platform": "Yahoo Finance",
  "url": "https://finance.yahoo.com/news/...",
  "language": "en",
  "raw_title": "Market Trends in 2026",
  "raw_content": "Full text content from the scraper...",
  "author": "John Doe",
  "publish_at": "2026-03-11T12:00:00Z",
  "scraped_at": "2026-03-11T14:30:00Z",
  "metadata": {
    "tags": ["Tech", "AI"],
    "stock_tickers": ["NVDA", "TSMC"]
  }
}
```

---

## 2. 台股資料表 (Taiwan Stock - PostgreSQL)

針對台灣股票的資料特性，分為「個股基本資訊」、「每日行情（日K）」及「三大法人籌碼面」三張主要表。

### 2.1 個股基本資訊表 `stock_info`

儲存股票代碼、名稱、產業類別等靜態或半靜態資料。

```sql
CREATE TABLE stock_info (
    stock_id        VARCHAR(10) PRIMARY KEY,            -- 股票代碼 (如: '2330')
    stock_name      VARCHAR(50) NOT NULL,               -- 股票名稱 (如: '台積電')
    market_type     VARCHAR(10),                        -- 市場類型 ('上市', '上櫃')
    industry_type   VARCHAR(50),                        -- 產業類別 (如: '半導體業')
    listing_date    DATE,                               -- 上市日期
    is_tracking     BOOLEAN DEFAULT TRUE,               -- 是否持續追蹤抓取
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Migration 001: 產業類別索引（加速按產業篩選查詢）
CREATE INDEX IF NOT EXISTS idx_stock_info_industry_type
  ON stock_info (industry_type);
```

> **产业類型資料來源：** FinMind SDK `fetch_stock_info()` 回傳的 `industry_type` 欄位，
> 與台灣證交所分類一致（如：半導體業、金融業、電子零組件業等）。

---

## 2.1.1 Migration 管理

Node.js Server 啟動時，`Server/lib/migrate.js` 會自動執行 `Server/migrations/` 目錄下的 `.sql` 檔案（依檔名排序）。已執行的 Migration 記錄於 `_migrations` 表，不會重複執行。

```sql
-- Migration 追蹤表（Server 自動建立）
CREATE TABLE IF NOT EXISTS _migrations (
    id         SERIAL PRIMARY KEY,
    filename   VARCHAR(200) UNIQUE NOT NULL,
    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

| 檔案 | 說明 |
|------|------|
| `001_add_industry_index.sql` | 為 `stock_info.industry_type` 新增索引 |

---

### 2.2 每日行情表 `stock_daily_prices`

資料量最大的表，建議針對 `trade_date` 進行 Table Partitioning（分區）以提升查詢效能。

```sql
CREATE TABLE stock_daily_prices (
    stock_id            VARCHAR(10) NOT NULL,
    trade_date          DATE        NOT NULL,
    open_price          NUMERIC(10, 2),     -- 開盤價
    high_price          NUMERIC(10, 2),     -- 最高價
    low_price           NUMERIC(10, 2),     -- 最低價
    close_price         NUMERIC(10, 2),     -- 收盤價
    volume              BIGINT,             -- 成交張數/股數
    turnover_value      NUMERIC(18, 2),     -- 成交金額
    transaction_count   INT,                -- 成交筆數
    change_value        NUMERIC(10, 2),     -- 漲跌價位
    change_rate         NUMERIC(6, 3),      -- 漲跌幅 (%)
    PRIMARY KEY (stock_id, trade_date)
);

-- 建立日期索引，優化時間序列分析
CREATE INDEX idx_price_date ON stock_daily_prices (trade_date DESC);
```

### 2.3 三大法人籌碼表 `stock_chip_analysis`

法人動向是趨勢預測的重要特徵，建議優先建立此表。

```sql
CREATE TABLE stock_chip_analysis (
    stock_id                VARCHAR(10) NOT NULL,
    trade_date              DATE        NOT NULL,
    foreign_investor_buy    BIGINT,             -- 外資買超張數
    investment_trust_buy    BIGINT,             -- 投信買超張數
    dealer_buy              BIGINT,             -- 自營商買超張數
    total_net_buy           BIGINT,             -- 合計買超張數
    foreign_holding_ratio   NUMERIC(5, 2),      -- 外資持股比例 (%)：從未寫入，一律 NULL（見 2.5）
    PRIMARY KEY (stock_id, trade_date)
);
```

> 單位註記：FinMind `TaiwanStockInstitutionalInvestorsBuySell` 回傳的是**股**，不是張。
> 表內數值照原樣存（台積電單日外資可達 ±1,600 萬股），前端顯示時 ÷1000 換算成張。

### 2.5 外資持股統計表 `stock_foreign_holding`（Iteration 35）

外資的**絕對持股**（今天手上有幾股、佔已發行股數幾 %），來源 FinMind `TaiwanStockShareholding`
（證交所「外資及陸資投資持股統計」）。與 2.3 的差別：那邊是「今天買賣了多少」，這邊是「今天有多少」。

刻意與 `stock_chip_analysis` 分表：那張表是 M3 與 UnifiedModel 的特徵來源，而持股統計的日期集合
與買賣超不完全一致；塞同一張表會多出買賣超全 NULL 的列，模型端分不出「沒交易」與「沒抓到」。
2.3 的 `foreign_holding_ratio` 欄位因此**不再使用**，Server 端的外資持股比例一律改讀本表。

三大法人裡只有外資有這份每日揭露；投信、自營商沒有，只能用買賣超累計推估。

```sql
CREATE TABLE IF NOT EXISTS stock_foreign_holding (
    stock_id                  VARCHAR(10)   NOT NULL,
    trade_date                DATE          NOT NULL,
    foreign_shares            BIGINT,          -- 外資持有股數（股）
    foreign_ratio             NUMERIC(6, 2),   -- 外資持股比例 (%)
    foreign_upper_limit_ratio NUMERIC(6, 2),   -- 外資投資上限 (%)
    shares_issued             BIGINT,          -- 已發行股數（股）
    PRIMARY KEY (stock_id, trade_date)
);
CREATE INDEX IF NOT EXISTS idx_foreign_holding_date ON stock_foreign_holding (trade_date DESC);
```

寫入路徑：`FinMindScraper.fetch_foreign_holding()` → `upsert_foreign_holding()`（表不存在時自動建立）。
每日 18:00 排程與 `data_freshness.backfill()` 都會寫；歷史用 `backfill_prices.py --holding-only` 回補。

### 2.4 使用者提交新聞表 `user_news`

由前端「新聞輸入」頁面提交，Server 啟動時自動建立（`CREATE TABLE IF NOT EXISTS`）。

```sql
CREATE TABLE IF NOT EXISTS user_news (
    id           SERIAL PRIMARY KEY,
    platform     VARCHAR(100),               -- 來源平台名稱（如：Yahoo Finance）
    title        VARCHAR(500),               -- 新聞標題（預設：'(無標題)'）
    content      TEXT,                       -- 新聞內文
    tickers      TEXT[],                     -- 關聯股票代碼陣列（如：{2330,2317}）
    submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

> 此表由 `Server/index.js` 啟動時自動建立，無需手動執行 DDL。

**Iteration 38 起**：`user_news` 是新聞主表——爬蟲（`rss_news_scraper`）、三年回填（`backfill_news.py`、
`backfill_mops.py`）與使用者貼上的新聞都在這裡，`submitted_at` 存的是**發布時間**（爬蟲來源）。
`keywords TEXT[]` 由 Server migration 加入。`news_schema.py` 再加：
`source_url / published_at_utc / language / scope（GLOBAL/US/TW）/ source_tier（1~3）/ content_kind（api/body/summary/filing/user）/
dedup_group_id / is_canonical`。寫入判重：有發布時間時「標題 + 發布日」，否則只看標題。

### 2.6 新聞結構化表（Iteration 38，`Crawler/news_schema.py`）

| 表 | 主鍵 | 用途 | 寫入者 |
|----|------|------|--------|
| `news_crawl_raw` | id；`source_url` 唯一 | 爬蟲原始中介表（含非財金） | `insert_raw_news_batch` |
| `instrument_alias` | (alias, ticker) | 標的別名：台積／TSMC／台灣50 → 代碼 | `news_alias.py --seed` |
| `trading_calendar` | (market, trade_date) | TW/US 交易日與收盤時間 | `news_align.py --calendar` |
| `news_price_link` | (news_id, ticker, market) | 新聞 → 標的 → `effective_date`（13:30 前歸當日） | `news_align.py --link` |
| `news_daily_features` | (stock_id, effective_date) | 每檔每日本股／全市場字典情緒（歷史可回算） | `news_align.py --features`、排程每小時增量 |
| `news_llm_feature` | (news_id, model) | LLM 結構化抽取：event_type / direction / magnitude / is_expected / scope | `news_pilot/scripts/05_load_db.py` |
| `news_features` | (stock_id, feature_date) | 舊：M2 當天推論時寫的 72h 聚合值 | `model2_news._persist_features` |

來源 tier / scope 的對照在 `Crawler/news_sources.py`（未建表）。

### 2.7 月營收表 `stock_revenue_announce`（Iteration 20 建、39 改）

| 欄位 | 說明 |
|------|------|
| `stock_id`, `revenue_month` | 主鍵；`revenue_month` 是營收所屬月份（月初），不是公布月 |
| `revenue` | 合併營收（元），FinMind；2013 年起，`backfill_revenue.py` |
| `announce_date` | 公布日（可為 NULL，migration 016 拿掉 NOT NULL） |
| `announce_ts` | 公布時間（秒），只有 MOPS 公告／鉅亨營收速報／媒體標題來源有 |
| `announce_source` | `mops_item` / `cnyes_item` / `news_item` / `finmind` / `cnyes_list` / `estimated`，優先序由高到低，`backfill_revenue_dates.py` |

事件研究（`Crawler/revenue_event_study.py` → `AI/Doc/RevenueEventStudy.md`）只用 `estimated` 以外的事件做主結論。
鉅亨來源會寫入非追蹤股（每月約 200 家大型股），擴大股票池時只需補 `revenue`。

### 2.8 研究股價格表 `research_daily_prices`（Iteration 39，`Crawler/research_universe.py`）

欄位同 `stock_daily_prices`（沒有 `adj_close`，未還原權息），存「鉅亨營收速報有 ≥ 12 個月精確公布時間」的非追蹤股
（2026-09：159 檔，2023-01 起）。**另開一張表的原因**：`stock_daily_prices` 被 LSTM `data_loader`、`rebuild_adj_close`、
`sync_stock_info`、新鮮度檢查當成追蹤股清單在用，研究股塞進去會讓 LSTM 多訓練一百多檔、新鮮度檢查天天報落後。
只有 `revenue_event_study.py --research` 讀它。

### 2.9 `news_llm_feature` 的規則模型 `rule_mops_v1`（Iteration 39，`Crawler/mops_event_study.py`）

MOPS 重大訊息 6,137 則的主旨用正則分 22 類（營收、財報-季報、財報-自結、股利、法說會、股東會、庫藏股、員工股權、
澄清媒體、注意交易、訴訟裁罰、捐贈、人事異動、併購投資、減資增資、可轉債、背書保證、有價證券交易、資本支出、更正、
董事會決議、其他），寫進同一張表：`model = 'rule_mops_v1'`、`event_type` = 類別、`is_expected` = 是否例行、
`direction = 'neutral'`、`magnitude = 1`。M2 要過濾例行公告時用 `is_expected`。

---

## 3. 模型訓練整合視圖 (View)

將「新聞情緒得分」與「股價變動」結合，方便預測模型直接讀取。

```sql
CREATE VIEW v_model_training_data AS
SELECT
    p.stock_id,
    p.trade_date,
    p.close_price,
    p.change_rate,
    n.sentiment_score,  -- 關聯新聞模組
    c.total_net_buy     -- 關聯籌碼模組
FROM stock_daily_prices p
LEFT JOIN stock_chip_analysis c
    ON p.stock_id = c.stock_id AND p.trade_date = c.trade_date
LEFT JOIN news_features n
    ON p.trade_date = n.publish_at::DATE
WHERE p.stock_id = '2330';
```

## weekly_forecast_runs / weekly_forecasts（Iteration 37）

每週日 08:00 排程的全模型預測結果。`runs` 一列一次執行（基準日、下一週與下下週的日期區間、
股票數、模型數、失敗清單）；`forecasts` 一列一個（執行, 市場, 股票, 模型），`payload` 依模型而異：
LSTM 存 10 日路徑與兩週末的收盤／區間／變動，閘門模型存各自的欄位並帶 `covers`
（`next_day` / `week1` / `both` / `3d`）標明視野。不併入 `model_predictions`：那張表是單一目標值的台帳。
