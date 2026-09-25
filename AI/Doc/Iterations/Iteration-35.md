# Iteration 35 — 法人持股頁、外資真實持股進排程、修正全站日期少一天

**日期：** 2026-09-19

## 起點

使用者要一個新分頁：「顯示三大法人對單一股票持股變化」。

做第一版時發現兩件事：

1. `stock_chip_analysis` 只有每日買賣超，**沒有任何一方的絕對持股**；`foreign_holding_ratio`
   欄位從 2012 年第一筆到現在全是 NULL——爬蟲一直寫 `None`，註解寫著「需另呼叫
   taiwan_stock_shareholding」，沒人接。
2. 後端把 PostgreSQL 的 `DATE` 用 `toISOString().slice(0, 10)` 轉字串。node-postgres 把
   DATE 解析成**本地時區的午夜**，轉 UTC 就退回前一天——台北 +8 之下**每個日期都少一天**。
   實測 `/stocks/2330/prices` 把 9/11 的收盤 2410 標成 9/10；市場總覽的「資料日期」也是錯的。
   這個 bug 從 stocks.js 誕生就在，一路活到現在。

使用者決定：開下一個 Iteration 把外資真實持股接進來，並同時修這個 bug。

## 一、「持股變化」要拆成兩種資料講

| | 買賣超累計 | 外資真實持股 |
|---|---|---|
| 來源 | `stock_chip_analysis`（FinMind InstitutionalInvestorsBuySell） | `stock_foreign_holding`（FinMind TaiwanStockShareholding，Iteration 35 新增） |
| 意義 | 從期間第一天起算的淨買賣，**換起點數字就變** | 今天手上有幾股、佔已發行股數幾 %，**絕對值** |
| 涵蓋 | 外資、投信、自營商 | **只有外資**（證交所只揭露外資及陸資持股） |

投信、自營商沒有每日持股揭露，這不是資料沒抓，是市場上沒有這份資料；頁面底部寫明。

### 分表，不擴欄

持股統計沒有塞進 `stock_chip_analysis`。那張表是 M3 籌碼模型與 UnifiedModel 的特徵來源，
而持股統計的日期集合與買賣超不完全一致（停牌日、揭露時差）。塞同一張表會多出一批買賣超
全 NULL 的列，模型端分不出「沒交易」與「沒抓到」。新表 `stock_foreign_holding`
（stock_id, trade_date, foreign_shares, foreign_ratio, foreign_upper_limit_ratio, shares_issued），
`upsert_foreign_holding()` 在表不存在時自動建立。

### 單位

FinMind 兩份資料的單位都是**股**（台積電單日外資買賣超可達 ±1,600 萬股；DB.md 原本寫「張」
是錯的，已改）。資料庫照原樣存，前端 ÷1000 換算成張顯示。

## 二、進排程與回補

| 路徑 | 改動 |
|------|------|
| `FinMindScraper.fetch_foreign_holding()` | 新增；欄位對照 ForeignInvestmentShares / SharesRatio / UpperLimitRatio / NumberOfSharesIssued |
| `scheduler.job_stock`（每日 18:00） | 行情 + 籌碼之後多抓持股；失敗只記 warning，不擋前兩者 |
| `data_freshness.backfill()` | 補行情時一併補持股 |
| `backfill_prices.py --holding / --holding-only` | 歷史回補 |

回補結果（26 檔追蹤股票，2012-05-02 起）：

| | 數字 |
|---|---|
| 寫入筆數 | 91,544 |
| 涵蓋 | 26 檔 × 3,520~3,521 個交易日 |
| 日期範圍 | 2012-05-02 ～ 2026-09-18 |
| 失敗 | 0 |

每檔一次呼叫，26 次約 1 分鐘完成，沒有觸到限流。

回補時順帶看到：**行情與買賣超停在 9/11**，而持股統計已到 9/18。start-dev.bat 在
Iteration 33 之前從未啟動排程器，之後也只在有人開機時才跑；今天 21:01 才啟動服務，
18:00 那一輪自然沒跑。本次以 `scheduler.job_stock()` 手動補跑一次，之後由排程接手。

## 三、日期 bug 的修法：在連線層解決，不是逐個路由修

    Server/db.js
    types.setTypeParser(1082, v => v)   // DATE 原樣回傳 'YYYY-MM-DD'

四處 `toISOString().slice(0, 10)` 全部刪掉（stocks.js 三處；predictions.js 那一處是對
自建的 UTC Date 呼叫，本來就對，保留）。holdings.js 早就知道這個坑、在部分 SQL 用了
`::text`，但 `price_date` 那欄沒有——現在也一併正確了。

為什麼不逐個路由加 `::text`：這個 bug 已經證明「每個人都要記得」的做法會漏。
在連線層改，之後任何路由拿到 DATE 都是字串。

驗證：修前 `/stocks?tracked=true` 資料日期 2026-09-10，修後 2026-09-11（與 DB 一致）。

**預測比對沒有受影響。** Iteration 33 的「以真實交易日對齊」在 SQL 端用 `trade_date::text`
與 `>= $2::date` 比較，從未經過 JS Date，所以那邊的日期一直是對的，修正前後不變。

## 四、前端：`Screen/src/pages/InstitutionalHoldings.jsx`（側欄「法人持股」）

由上而下：

1. 股票代碼（附追蹤清單 datalist）＋ 期間（20／60／120 日、1／3 年，日曆天）
2. 七格總結：三法人各自累計買賣超、合計、**外資持股比例（真實）**、**外資持股張數變化（真實）**、同期股價
3. 累計買賣超折線（三法人＋合計，收盤價虛線疊右軸）
4. 外資真實持股折線（比例左軸、張數右軸）
5. 每日買賣超柱狀
6. 近 30 個交易日明細，含外資持股與比例兩欄

後端 `GET /stocks/:id/institutional?days=N`：一次 SQL 用視窗函數算累計，LEFT JOIN 行情與持股。

### 踩到的 ApexCharts 4 行為

多 y 軸時，ApexCharts 4 預設把同一軸的系列在圖例裡**分組直排**（`legend.clusterGroupedSeries`），
五個名字疊成一柱。這不是 CSS 問題，用 DOM 檢查才確認是內建行為；設 `clusterGroupedSeries: false`。
另外 4.x 的 `yaxis[].seriesName` 可以給陣列，一個軸綁多條線，比舊寫法（五個軸物件、四個 `show:false`）乾淨。

## 改動檔案

| 檔案 | 改動 |
|------|------|
| `Crawler/models/stock.py` | 新增 `StockForeignHolding` |
| `Crawler/scrapers/finmind_scraper.py` | 新增 `fetch_foreign_holding()` |
| `Crawler/db/repository.py`、`db/schema.sql` | 新表 `stock_foreign_holding` 與 `upsert_foreign_holding()` |
| `Crawler/scheduler.py`、`data_freshness.py`、`backfill_prices.py` | 持股進每日排程、補齊與回補 |
| `Server/db.js` | DATE 型別原樣回傳字串（修日期少一天） |
| `Server/routes/stocks.js` | 新端點 `/:id/institutional`；外資持股比例改讀新表；移除三處 `toISOString()` |
| `Screen/src/pages/InstitutionalHoldings.jsx` | 新頁 |
| `Screen/src/App.jsx`、`components/Sidebar.jsx`、`services/api.js` | 掛頁與 API helper |
| `AI/Doc/DB.md`、`Architecture.md`、`UserDoc/Spec.md` | 新表、新端點、單位更正 |

## 誠實評估

- ✅ 外資真實持股是證交所揭露的絕對值，不是推估；26 檔 14 年全部補齊、零失敗。
- ✅ 日期 bug 在連線層修，是根本解；驗證過修前後的資料日期。
- ⚠️ 這一頁是**籌碼流向的參考，不是買賣訊號**。Iteration 9 已證明籌碼模型的賣出訊號沒有 edge；
  這裡只是把資料攤開給人看，沒有任何預測意涵。
- ⚠️ 「三大法人持股變化」名稱下，真正的持股只有外資一方。投信、自營商的「變化」是買賣超累計，
  頁面有寫明，但使用者若跳過註記仍可能誤讀。

## 遺留問題

1. **外資持股比例現在有真實資料了，但沒有進任何模型。** `UnifiedModel/features.py` 的註解
   把 `holding_chg_5d` 排除是因為那欄全 NULL；現在資料在新表裡，要不要當特徵是下一個
   走查的事——照 Iteration 30 的規矩，得用巢狀走查驗，不是加了就上。
2. **market 總覽與個股分析的「外資持股%」現在會顯示了**（改讀新表），但那兩頁的文案沒改，
   仍只顯示比例，不顯示日期；持股統計偶爾比行情晚一天揭露，兩頁的比例可能對應前一個交易日。
3. **排程器仍依賴 start-dev.bat 被人打開。** 今天 18:00 沒跑就是這個原因；這是部署問題，不是程式問題。
