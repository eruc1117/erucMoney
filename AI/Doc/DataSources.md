# 資料來源 (Data Sources)

---

## 1. 新聞來源（Iteration 38 更新）

即時（每小時 `job_news`，`Crawler/scrapers/rss_news_scraper.py`）：

| 平台 | tier | scope | 語言 | 介面 | 內文 |
|------|------|-------|------|------|------|
| 鉅亨網 | 2 | TW | 中 | JSON API `news.cnyes.com/api/v3/news/category/tw_stock_news` | API 附帶 |
| 中央社財經 | 1 | TW | 中 | RSS | 抓原文頁 |
| 經濟日報證券／產業 | 2 | TW | 中 | RSS | 抓原文頁 |
| 自由財經 | 2 | TW | 中 | RSS | 抓原文頁 |
| BBC Business／BBC World | 1 | GLOBAL | 英 | RSS | 抓原文頁（不套財金關鍵字過濾） |
| Yahoo 個股 | 3 | TW | 中 | RSS `tw.stock.yahoo.com/rss?s=CODE.TW`（追蹤股；Iteration 83 起 68 檔） | 抓原文頁 |

歷史回填（`Crawler/backfill_news.py`，鉅亨網分類 API 支援 `startAt / endAt / page`，2023-09 起可用）：

| 分類 | platform | scope | 每週約 |
|------|----------|-------|--------|
| `tw_stock` | 鉅亨網 | TW | 280 則 |
| `us_stock` | 鉅亨網美股 | US | 170 則 |
| `headline` | 鉅亨網頭條 | GLOBAL | 550 則（與前兩類重疊，newsId 去重） |
| `tw_revenue` | 鉅亨網營收 | TW | 50 則（2024-04 起；由 `backfill_revenue_dates.py` 使用，見下） |

tier / scope / 語言的對照定義在 `Crawler/news_sources.py`。

**月營收公布時點**（Iteration 39，`Crawler/backfill_revenue_dates.py` → `stock_revenue_announce`）：
FinMind `TaiwanStockMonthRevenue` 的 `create_time` 在 2026-03 之前全空，公布日改成多來源合成，優先序
MOPS 重大訊息「公告 X 月營收」（秒）＞鉅亨網 `tw_revenue` 個股快訊「營收速報 - 公司(代號)X月營收…」（秒；每月約 200 家大型股）
＞其他媒體標題最早一則（秒）＞FinMind create_time（日）＞鉅亨網每日「營收一覽」內文「本次公布…前 3 名」（日；每天最多 6 家）
＞該股習慣公布日估計（`estimated`，事件研究不進主結論）。一覽清單的 `otherProduct` 混有累計排行、日期不對，不能拿。
MOPS 本身的 `t05st10_ifrs` 只有營收數字沒有公布時間。

失效或棄用：CNN Business 首頁與 Yahoo Finance 台灣首頁（舊法，內文恆空，Iteration 10 棄用）；
工商時報、鉅亨網 RSS（404）；Google News RSS（連結為 JS 轉址，取不到內文）；
Common Crawl 歷史爬蟲（每請求等 60~300 秒，實際不可用，鉅亨網 API 取代）；
CNBC／MarketWatch RSS（原文頁為樣板，內文抓不到）。

---

## 2. 股市資料來源

| 平台 | 說明 | URL |
|------|------|-----|
| FinMind | 台股結構化 API（個股行情、三大法人、基本資訊） | https://finmindtrade.com/ |
| 台灣證券交易所 (TWSE) | 原始資料來源（FinMind 底層抓取自此） | https://www.twse.com.tw/ |

---

## 3. FinMind API 說明

| 資料集 | FinMind 方法 | 對應 DB 表 |
|--------|-------------|-----------|
| 個股每日行情 | `taiwan_stock_daily()` | `stock_daily_prices` |
| 三大法人買賣超（追蹤股） | `taiwan_stock_institutional_investors()` | `stock_chip_analysis` |
| 三大法人買賣超（**全市場**，Iteration 71） | 不走 FinMind：證交所 `fund/T86`（selectType=ALLBUT0999）＋櫃買 `insti/dailyTrade`（type=Daily、sect=EW），一天兩次呼叫；`Crawler/institutional_data.py` | `market_institutional_daily`（2018-01 起；單位股；外資含外資自營商；寫入前驗證合計 = 三法人相加） |
| 個股估值：本益比、殖利率、股價淨值比（**全市場**，Iteration 78） | 不走 FinMind：證交所 `afterTrading/BWIBBU_d`（selectType=ALL）＋櫃買 `afterTrading/peQryDate`，一天兩次呼叫；`Crawler/valuation_data.py`；每日 18:37 排程 | `market_valuation_daily`（2018-01 起；上市殖利率與兩市本益比是點時（Iteration 80 `val-pit-check-80`）；**櫃買殖利率不是點時**（整年固定、年初就印當年才決議的股利）；本益比虧損印「-」／N/A → NULL；上市有收盤價與財報年/季、上櫃有每股股利） |
| 融資融券與借券賣出（**全市場**，Iteration 81） | 不走 FinMind：證交所 `marginTrading/MI_MARGN`（融資融券彙總，張）＋`marginTrading/TWT93U`（信用額度總量管制餘額表：融券＋借券賣出，股）；櫃買 `margin/balance`（張）＋`margin/sbl`（股），一天四次呼叫；`Crawler/margin_data.py`；每日 18:39 排程 | `market_margin_daily`（2018-01 起；一律存股；兩表共有的融券餘額逐列對位檢查；沒有信用交易資格的股票不在表裡；借券表沒列的借券欄 NULL） |
| 外資持股與發行股數（**全市場**，Iteration 81） | 不走 FinMind：證交所 `fund/MI_QFIIS`（外資及陸資投資持股統計）＋櫃買 `insti/qfii`（持股比例排行表），一天兩次呼叫；`Crawler/holding_data.py`；每日 18:41 排程 | `market_foreign_holding_daily`（2018-01 起；發行股數、外資持有股數、持股比率（自己算）；發行股數可算週轉率與市值） |
| 個股基本資訊 | `taiwan_stock_info()` | `stock_info`（`is_tracking` 就是追蹤股清單：原 `AI/UserDoc/Target.md` 的 20 家＋2330／2327／2883＋三檔 ETF；Iteration 83 加 0050 成分股 42 家成 68 檔；FinMind 對轉市場的股票會回舊市場別，以 `market_universe` 為準） |
| 追蹤股三張表補齊（Iteration 83） | 不走 FinMind：`Crawler/tracked_sync.py` 每日 18:43 把 `stock_daily_prices`／`stock_chip_analysis`／`stock_foreign_holding` 缺的列從 `market_daily_prices`／`market_institutional_daily`／`market_foreign_holding_daily` 補進去（已寫的列不覆蓋、補到行情的股票重建 adj_close） | 同左三張追蹤股表（兩個來源逐列對照見 Iteration 83：收盤、法人、持股全同；上櫃成交量交易所檔不含零股與盤後） |

### 欄位對照（taiwan_stock_daily → stock_daily_prices）

| FinMind 欄位 | 本系統欄位 | 說明 |
|-------------|-----------|------|
| `date` | `trade_date` | 交易日期 |
| `open` | `open_price` | 開盤價 |
| `max` | `high_price` | 最高價 |
| `min` | `low_price` | 最低價 |
| `close` | `close_price` | 收盤價 |
| `spread` | `change_value` | 漲跌 |
| 計算得出 | `change_rate` | 漲跌幅（%）= spread / (close - spread) × 100 |
| `Trading Volume` | `volume` | 成交股數 |
| `Trading money` | `turnover_value` | 成交金額 |
| `Trading turnover` | `transaction_count` | 成交筆數 |

### Token 設定

- 免費匿名：每小時 30 次 API 呼叫
- 申請 Token：每小時 600 次（建議正式環境使用）
- 設定位置：`Crawler/config.py` → `FINMIND["token"]`

### 資料補充範圍

| 觸發模式 | 日期範圍 | 冷卻限制 |
|----------|----------|----------|
| 近期模式（自動） | 最近 90 天 | 每股 30 分鐘 |
| 歷史補充模式 | 自訂 start_date ~ end_date | 無冷卻，單次上限 365 天 |

> FinMind 免費方案每小時 30 次；抓取大量歷史資料建議申請 Token。
