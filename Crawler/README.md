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
