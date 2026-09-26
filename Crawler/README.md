# Crawler 模組說明文件

台灣證券交易所（TWSE）股票資料爬蟲，同時提供 FastAPI HTTP 伺服器供前端（Screen）呼叫。

---

## 目錄結構

```
Crawler/
├── main.py               # 程式入口點（支援 server / stock / schedule 三種模式）
├── api.py                # FastAPI 伺服器（HTTP API，port 8000）
├── scheduler.py          # APScheduler 排程器（每日 18:00）
├── config.py             # 全域設定（含 DB 連線）
├── requirements.txt
├── db/
│   ├── connection.py     # psycopg2 連線池
│   ├── repository.py     # UPSERT 寫入函式
│   └── schema.sql        # 建表 DDL（初始化用）
├── models/
│   └── stock.py          # StockDailyPrice / StockChipAnalysis dataclass
├── scrapers/
│   ├── base_scraper.py   # 基底類別（反爬機制、重試、Session）
│   └── twse_scraper.py   # TWSE 官方 API 爬蟲
└── utils/
    └── user_agents.py    # User-Agent 池
```

---

## 安裝

```bash
pip install -r requirements.txt
```

---

## 初次使用：建立資料表

```bash
psql -U postgres -d money -f db/schema.sql
```

> 若資料庫尚未建立：`createdb -U postgres money`

---

## 設定 DB 連線

編輯 `config.py` 的 `DB` 區塊：

```python
DB = {
    "host": "localhost",
    "port": 5432,
    "dbname": "money",
    "user": "postgres",
    "password": "postgres",
}
```

---

## 使用方式

```bash
# ★ 啟動 HTTP 伺服器（供前端呼叫，固定在 port 8000）
python main.py --mode server

# 立即爬取今日資料並寫入 DB
python main.py --mode stock

# 指定股票代碼
python main.py --mode stock --stocks 2330 2317 2454

# 指定日期
python main.py --mode stock --date 20260310

# 啟動排程器（每日 18:00 自動執行，Ctrl+C 停止）
python main.py --mode schedule
```

---

## API 端點（server 模式）

伺服器啟動後監聽 `http://localhost:8000`，提供以下 REST API：

| 方法 | 路徑 | 說明 |
|------|------|------|
| GET | `/stocks/{stock_id}` | 個股基本資訊 + 最新行情 + 籌碼 |
| GET | `/stocks?max_price={price}` | 依預算篩選可買股票 |
| GET | `/stocks/{stock_id}/prices?days=90` | K 線行情（最近 N 天） |
| GET | `/stocks/{stock_id}/chips?days=20` | 三大法人籌碼（最近 N 天） |
| POST | `/crawler/run` | 觸發指定股票爬蟲（背景執行） |
| POST | `/news` | 新聞輸入（Stub，待 NLP 模組實作） |
| GET | `/model/predict` | 模型預測（Stub，待預測模組實作） |
| POST | `/model/retrain` | 手動重訓（Stub，待預測模組實作） |

API 文件（開發時可用）：`http://localhost:8000/docs`

---

## 資料流

```
TWSE API
  ├─ STOCK_DAY  →  TWSEScraper.fetch_daily_price()
  │                    → StockDailyPrice
  │                        → upsert_daily_prices()
  │                            → stock_daily_prices (PostgreSQL)
  │
  └─ T86        →  TWSEScraper.fetch_chip_analysis()
                       → StockChipAnalysis
                           → upsert_chip_analysis()
                               → stock_chip_analysis (PostgreSQL)
```

---

## 模組說明

### `db/connection.py`

`psycopg2.SimpleConnectionPool`，最小 1 條、最大 5 條連線。

```python
with get_conn() as conn:
    with conn.cursor() as cur:
        cur.execute("SELECT ...")
    conn.commit()
```

### `db/repository.py`

| 函式 | 寫入表 | 說明 |
|------|--------|------|
| `upsert_daily_prices(prices)` | `stock_daily_prices` | 批次 UPSERT 每日行情 |
| `upsert_chip_analysis(chips)` | `stock_chip_analysis` | 批次 UPSERT 三大法人籌碼 |
| `upsert_stock_info(...)` | `stock_info` | 新增/更新個股基本資訊 |

所有寫入使用 `ON CONFLICT DO UPDATE`，重複執行安全，資料自動覆蓋為最新值。

### `config.py`

| 設定項 | 預設值 | 說明 |
|--------|--------|------|
| `DELAY_MIN / MAX` | 1.5 / 4.0 秒 | 每次請求前的隨機延遲 |
| `REQUEST_TIMEOUT` | 15 秒 | 單一請求逾時 |
| `MAX_RETRIES` | 3 | 5xx 錯誤自動重試次數 |
| `DB` | localhost:5432/money | PostgreSQL 連線設定 |
| `SCHEDULE.stock_cron` | 18:00 | 排程執行時間 |

## 自動測試（tests/）

只測「抓得對、存得對、排得對」；特徵工程與模型不在這裡。全部不上網：`responses` 攔 `requests`，FinMind 的 `DataLoader` 用假物件，`time.sleep` 一律 no-op。

```
pip install -r requirements-test.txt
python -m pytest -q               # 全部（db 標記的測試用 CRAWLER_TEST_DB，預設 Stock_crawler_test）
python -m pytest -q -m "not db"   # 只跑不碰資料庫的（秒級）
```

| 檔案 | 對應 | 內容 |
|------|------|------|
| `test_config.py` | `config.py` | `.env` 手寫解析（引號、空白、註解、不覆蓋既有環境變數）、`validate()` 缺密碼明講、`FINMIND_TOKEN` 空字串＝匿名 |
| `test_price_parsers.py` | `scrapers/twse_scraper.py`、`scrapers/finmind_scraper.py`、`backfill_revenue.py` | 千分位、全形、停牌列、欄位型別、空回應、新舊欄名、NaN→None、除權息／減資列、額度耗盡 |
| `test_chip_parsers.py` | 同上（籌碼、外資持股） | 買賣超正負號、自營商合計／子項、外資持股比與上限、持股日期晚於行情 |
| `test_mops_parsers.py` | `backfill_mops.py`、`backfill_revenue.py`、`backfill_revenue_dates.py` | 民國日期＋發言時間→`announce_ts`、`source_url` 去重鍵、被擋重試、營收月份對應、鉅亨網快訊 vs 一覽、來源優先序 |
| `test_news_pipeline.py` | `scrapers/rss_news_scraper.py`、`news_scraper.py`、`news_alias.py`、`news_dedup.py`、`news_align.py`、`news_sources.py`、`backfill_news.py` | RSS／鉅亨網 API／原文頁解析、標題清理、時區、內文驗證、個股標記與別名、SimHash 去重與 3 天窗口、日級對齊、429 重試 |
| `test_freshness.py` `db` | `data_freshness.py` | 落後用「市場有的交易日」算（週末假日不算）、預測與持股才顧、一次最多 N 檔、額度用完提早停、外生資料三張表、來源互不影響 |
| `test_scheduler.py` | `scheduler.py`、`weekly_forecast.py` | 每個工作的 cron 時點與 `max_instances=1`、啟動補跑（凍結時間：只補已過時點且資料落後的、一天一次、週末略過、失敗不中斷）、每週預測到期 |
| `test_api_ops.py` | `api.py` | `/crawler/run` 冷卻／並發／歷史模式、`/crawler/status`、`/crawler/news` 關鍵字過濾與狀態、`/data/freshness`、`/data/backfill`、`/forecast/weekly/*`；`db`：`/stocks/*` |
| `test_upsert.py` `db` | `db/repository.py`、`rebuild_adj_close.py`、`sync_stock_info.py`、`news_alias.py`、`news_align.py` | 同鍵重跑不重複、新聞兩層去重（source_url；標題＋發布日）、adj_close 回溯還原、殘留列、別名表、交易日曆與對齊 |

測試資料庫：`tests/helpers/db_setup.py` 依正式順序建 schema（`db/schema.sql` → Node 啟動時建的四張表 → `Server/migrations/*.sql` → `news_schema.py`），只在名字以 `_test` 結尾的資料庫上動作；連不上就整批 skip。CI 在 `.github/workflows/test.yml` 的 `crawler` job。
