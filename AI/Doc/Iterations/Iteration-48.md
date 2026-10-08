# Iteration 48 — 打敗大盤計畫階段 1：全市場股票池、日線、含息大盤

**日期：** 2026-10-07
**依據：** Claude Docs「台股量化交易研究」文件的分頁「實作計畫：打敗大盤」（月營收公告日反應排名、每月調倉、對手是 0050 含息）。
使用者的三個決定：用零股、FinMind 先用免費配額、資料從 2018 起。
**前提：** Iteration 39 已證明 SUE 漂移不顯著（Q5−Q1 CAR[1,20] +0.96%，t 1.3），公告日反應 AR₀ 才有訊號（係數 +0.41，t 4.0）。
本迭代**不碰訊號與回測**，只做計畫的階段 1：把資料範圍從 26 檔追蹤股＋159 檔研究股擴到上市櫃全市場（含下市股），補含息大盤，
把公司行動與還原價接上，每日更新進排程。

## 一、做了什麼

### 資料表：migration 020（`market_universe`、`market_daily_prices`）

另開兩張表、不塞進 `stock_info` / `stock_daily_prices`：那兩張被 LSTM、`rebuild_adj_close`、`sync_stock_info`、新鮮度檢查當成
「追蹤股清單」在用（DB.md 2.8 的教訓）。月調倉選股只讀新表，舊鏈完全不動。`market_daily_prices` 欄位與 `stock_daily_prices` 對齊，
多 `adj_close`（還原除權息與減資，事件表沿用 `stock_dividend_result` / `stock_capital_reduction`）與 `source`（finmind / twse / tpex）。

### 股票池：`Crawler/market_universe.py`

FinMind `TaiwanStockInfo` ＋ `TaiwanStockDelisting` 各一次呼叫。收錄：上市櫃（興櫃不收）、代號 4 碼且不以 0 開頭（排除 ETF、特別股、TDR、權證）、
產業別非 ETF／ETN／受益證券／存託憑證／指數；**下市表裡符合規則的也收**（存活者偏差就是少了它們）。

| 結果（2026-10-07） | 數字 |
|---|---|
| 股票池 | 2,621 檔（在市 1,978；上市 1,215、上櫃 928） |
| 2018 以後下市 | 112 檔（回測期內會消失的股票） |

**踩到的坑**：`TaiwanStockInfo` 的 `date` 欄不是上市日——1,749 檔都是同步當天。第一版拿它當 `listing_date`，待補清單只剩 284 檔（其餘被當成「還沒上市」跳過）。
改成留空，由 `market_data.derive_listing_dates()` 用第一筆價格日推回（只有 2018 之後才上市的股票填得出來，起點就有價的留空＝更早上市）。

### 日線：`Crawler/market_data.py`，兩條路線寫同一張表

| 路線 | 怎麼拿 | 額度 | 用途 |
|---|---|---|---|
| `--source finmind` | `TaiwanStockPrice` 逐檔，一次拿 2018 起全部 | 匿名約 30 次/小時、免費 token 600 次/小時；**免費等級不能查「某日全市場」**（實測 `status 400 Your level is free`） | 使用者選的回補路線；可中斷續跑，補到底的檔跳過 |
| `--source exchange` | 證交所 `MI_INDEX`（ALLBUT0999）＋櫃買 `afterTrading/otc`，一天兩次呼叫拿全市場 | 不吃額度，禮貌延遲 3 秒 | 每日排程；回補也可以（2018 起約 2,100 個交易日） |

解析在 `Crawler/scrapers/exchange_daily.py`（純函式，fixtures 是 2024-11-05 的真實回應裁短）。FinMind 的 `TaiwanStockPrice` 本來就是從這些檔來的，欄位一一對應，
`--check` 的 `tracked_consistency` 會拿追蹤股表（FinMind）對同日收盤驗證兩個來源可混用。

實測：3 檔樣本 5,581 列 5 秒；匿名額度第一小時放了 294 檔，之後每個小時窗只放約 5 檔就回 HTTP 402——**免費路線全市場要好幾天**。依使用者「不夠再改官方行情檔」的決定，第 299 檔時停掉 FinMind、改跑 `--source exchange`（2018 起約 2,130 個交易日、一天兩次呼叫、禮貌延遲 3 秒，約 4 小時），兩條路線寫同一張表、逐日略過已補滿（≥ 1,000 列）的日子。日誌 `logs/market_backfill_exchange.log`；跑完由 `logs/post_backfill.sh` 自動 `--rebuild-adj` 與 `--check`，結果在 `logs/market_post_backfill.log`。2018 起的除權息 13,462 筆、減資 216 筆（1,927 檔）已回補完成。

**回補結果（2026-10-08 03:00）**：2,132 個交易日、2,088 檔、3,758,828 列，0 個交易日失敗，約 2 小時 50 分；還原價 3,759,757 列一次重建完成（1,925 檔有公司行動）。
收盤 0.00 的列（上櫃檔對沒成交的證券印 0.00，共 3,748 列）第一版當成價格存進去、adj_close 算不出來，解析改成 `close <= 0` 一律略過並刪掉既有列。
「還沒補完 21 檔」都是下市股：下市前的停止買賣期比 45 天長，或 2018 一開年就下市（如 1729），不是資料缺口。

| `--check` | 結果 |
|---|---|
| survivorship | ✔ 110/112（2018 後下市的股票有價格） |
| day_coverage | ✔ 2132/2134（差的兩天交易所回休市） |
| adj_close_null | ✔ 0 |
| tracked_consistency | ✔ 47,123 列與追蹤股表（FinMind）同日收盤 0 列不一致——兩個來源可以混用 |
| limit_lock_share | 0.24%（一字漲跌停 8,986 列） |
| revenue_coverage | 1,271/1,978 檔有月營收；**公告日精確只有 7,652/28,332**（none 17,175、estimated 2,478） |
| benchmark_index | ✔ TAIEX_TR 2,132 日涵蓋 2018-01-02 ~ 2026-10-07 |

### 公司行動與還原價

除權息從交易所參考價表來：證交所 `TWT49U`、櫃買 `exDailyQ`（按月、全市場）；減資從證交所 `TWTAUU`（按年）。寫進既有事件表，
只收 `ex_date ≤ 今天`（未來事件會把整段歷史提前縮放）。`rebuild_adj()`：沒有事件的股票一句 SQL `adj = close`；有事件的逐檔算累積係數後
`UPDATE … FROM (VALUES …)` 批次更新（`rebuild_adj_close.py` 是逐列 UPDATE，26 檔沒問題，兩千檔會跑不完）。演算法同一套（回溯還原，最新一段 = 原始收盤）。
2018 起的事件回補已跑完（見 `logs/market_events_backfill.log`）。

### 含息大盤

`index_daily_prices.symbol = 'TAIEX_TR'`（發行量加權股價報酬指數）：FinMind `TaiwanStockTotalReturnIndex` 一次回補 2018 起 2,132 日；
每日從 `MI_INDEX` 的「報酬指數」表更新（同一次呼叫），價格指數 `TAIEX` 一併存。0050 本身已是追蹤股，還原價完整。

### 排程：`job_market_daily` 每日 18:30

交易所檔更新全市場日線與指數 → 近兩週公司行動 → **只重建有新事件股票的 adj_close**（其餘當天那列 adj = close，係數必為 1）。
啟動補跑：18:30 已過、`market_daily_prices` 最後日早於今天就補。與 `job_stock` 無關，只是錯開對外請求。

### 檢查：`python market_data.py --check`

| 檢查 | 判定 |
|---|---|
| `survivorship` | 2018 以後下市的股票要有價格（≥ 50%） |
| `day_coverage` | 交易日曆的開市日 ≥ 99% 有資料 |
| `adj_close_null` | 必須 0 |
| `tracked_consistency` | 與追蹤股表同日收盤差 > 0.01 的列必須 0 |
| `limit_lock_share` | 一字漲跌停比例（只報數字；回測視為未成交） |
| `revenue_coverage` | 股票池裡有月營收的檔數、公告日精確的月份比例（只報數字） |
| `benchmark_index` | TAIEX_TR 涵蓋整段回測期 |

### 月營收全市場回補：`Crawler/backfill_revenue_mops.py`（2026-10-08 補做）

FinMind 逐檔不可行（同上），改抓公開資訊觀測站的**營業收入彙總表**：一個市場一個月一頁就是全部公司
（`mopsov.twse.com.tw/nas/t21/{sii|otc}/t21sc03_{民國年}_{月}_{0|1}.html`，_1 是 KY 公司，單位千元）。
2016-10 ~ 2026-09 共 120 個月 × 4 頁 = 480 次請求、20 分鐘、0 頁失敗，寫入 218,349 列。
頁面是巢狀表格，解析只取「直接子 td ≥ 10 且第一格是 4 碼代號」的列（`tests/test_revenue_mops.py` 7 項）。

**月份對應核對過**：表裡 `revenue_month` 沿用 FinMind 慣例＝公布月（8 月營收 → 2026-09-01），台積電 514,805,337 千元對上。
只寫 `revenue`，既有公告日與來源原封不動。

| 月營收覆蓋 | 之前 | 之後 |
|---|---|---|
| 股票池有月營收的檔數 | 1,271 / 1,978 | **1,990 / 1,978（含下市股）** |
| 2018-01 那一期有營收的公司 | — | 1,684 |
| 公告日精確的月份 | 7,652 / 28,332 | 7,652 / 220,156（**沒變**：彙總表沒有各公司公告日） |

所以 SUE（只要營收數字）全市場、全期間都算得出；AR₀（要反應日）仍只有 2024-03 以後、約 200 家大型股有。

### 測試

`Crawler/tests/test_market_data.py` 28 項（解析 fixtures、股票池規則、寫入冪等、還原價、待補清單、檢查報表）；`test_scheduler.py` +2（18:30 註冊、補跑）；
Server `migrations.test.js` 改 20 個。全部通過。

## 二、對計畫階段 1 的回應

| 計畫項目 | 狀態 |
|---|---|
| stock_info 擴到全市場、加 delisted_date | 改為另開 `market_universe`（理由見上）；2,621 檔、112 檔 2018 後下市 ✔ |
| 全市場日線 2018 起、含 adj_close | ✔ 交易所檔回補完成：2,088 檔、376 萬列、還原價齊全、與追蹤股表一致 |
| research_daily_prices 併入後廢止 | **未做**：NewsModels/build_dataset.py 還在讀它，等全量回補完再切 |
| 全市場月營收與公告日、MOPS 全量公告日 | **未做**（見三） |
| 加權報酬指數、0050 adj_close 完整 | TAIEX_TR 2,132 日 ✔；0050 2003 起有還原價 ✔ |
| 0050 月持股權重表 | **未做** |
| FinMind token、job_stock 擴到全市場 | 不擴 job_stock：另開 `job_market_daily` 走交易所檔，不吃額度 ✔ |
| 四項偏差檢查寫成 pytest | 檢查函式有測試 ✔；對真實資料的判定要等回補完 |

## 三、沒做的與下一步

1. ~~價格回補完成~~ 已完成（交易所檔路線）。之後每天由 `job_market_daily` 18:30 接著補。
2. ~~月營收全市場回補~~ 已完成（MOPS 彙總表）。**公告日精確度**仍未解：FinMind `create_time` 2026-03 前全空、鉅亨速報只收強勢月、
   MOPS 彙總表沒有各公司公告日。AR₀ 訊號要的是「反應日」，所以階段 2 另加「公告窗口反應」訊號當近似，AR₀ 本身只能從 2024-03 測起。
3. 0050 月持股權重（台積電固定權重用）。
4. `research_daily_prices` 退場。

## 變更檔案

新增：`Server/migrations/020_market_universe.sql`、`Crawler/market_universe.py`、`Crawler/market_data.py`、`Crawler/scrapers/exchange_daily.py`、
`Crawler/tests/test_market_data.py`、`Crawler/tests/fixtures/{twse_mi_index,twse_mi_index_holiday,tpex_otc_daily,tpex_otc_daily_holiday,twse_twt49u,tpex_exdailyq,twse_twtauu}.json`。
修改：`Crawler/scheduler.py`、`Crawler/tests/test_scheduler.py`、`Crawler/tests/helpers/db_setup.py`、`Server/tests/db/migrations.test.js`、`AI/Doc/DB.md`、`AI/Doc/README.md`。
