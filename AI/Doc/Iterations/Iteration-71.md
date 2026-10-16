# Iteration 71 — 全市場三大法人買賣超：交易所官方檔路線，2018 起 2,137 個交易日回補完成、候選池覆蓋 99.9%

**日期：** 2026-10-15
**依據：** 使用者：「先補」（接 Iteration 70 完成報告的下一步：補 FinMind 三大法人買賣超全市場表）
**規則：** 資料工作，不跑回測、N 不動（仍是 88）；不直接對正式庫建表（migration 由 MoneyApi 重啟套用）；保留期未開。

## 一、做了什麼

1. **不走 FinMind，走交易所官方檔**（和 `market_daily_prices` 同一條路線）：證交所 `fund/T86`（selectType=ALLBUT0999）與櫃買 `insti/dailyTrade`（type=Daily、sect=EW），一天兩次呼叫拿全市場、不吃額度。改走交易所而不是 FinMind（`DataSources.md` 記申請 token 每小時 600 次），是因為 2018 起約 2,100 個交易日，逐日呼叫 FinMind 要 3.5 小時以上且需 token；交易所檔沒有額度限制。
2. **版面**（記在 `exchange_daily.py` 兩個 parse 的 docstring；`DataSources.md` 只記來源、單位與合計驗證）：證交所 19 欄（2017-12-18 起固定，外陸資不含外資自營商＋外資自營商分列）；櫃買兩種——2018 年 16 欄（有欄名）、之後 24 欄（欄名只剩「買進／賣出／買賣超」重複七組，只能按位置）。解析器 `parse_twse_institutional`／`parse_tpex_institutional`（`Crawler/scrapers/exchange_daily.py`）：外資 ＝ 外陸資＋外資自營商、自營商 ＝ 自行＋避險，**逐列驗證「三大法人合計 ＝ 外資＋投信＋自營」**，不等的列超過 1% 就 `ExchangeFormatError`（版面變了會擋下、不會寫錯欄），櫃買欄數不是 16／24 也擋。
3. **表**：`Server/migrations/028_market_institutional.sql` → `market_institutional_daily`（stock_id、trade_date、三個法人各買／賣／淨、total_net、source；單位股；PK (stock_id, trade_date)）。`Server/tests/db/migrations.test.js` 的數量 27 → 28。
4. **程式**：`Crawler/institutional_data.py`（`--backfill`：按交易日抓、已有 ≥ 800 列的日子跳過、可中斷續跑；`--update --date`；`--status`；`--check`：對 `market_daily_prices` 的覆蓋率與合計驗證）。只留 `market_universe` 裡的代號（ETF、債券 ETF 略過）。
5. **排程**：`scheduler.py` 新增 `job_institutional_daily`，每日 18:35（全市場日線 18:30 之後）。
6. **測試**：`Crawler/tests/test_institutional.py`（+4：證交所 19 欄含外資自營商與自營商兩腿相加、休市與格式守門、櫃買 16 欄、櫃買 24 欄按位置與休市）。

## 二、結果

| 檢查（`checks.json`） | 結果 |
|---|---|
| `pytest-institutional-71`（test_institutional + test_market_data） | 32 過 |
| `insti-parse-smoke-71`（不寫庫：2018-01-03、2019-07-01、2021-06-01、2024-01-02、2026-10-14 真實檔解析；2024-01-01 休市） | 上市 907／1,027／1,095／1,178／1,347 列、上櫃 487／591／726／790／901 列，五天合計驗證都沒擋下；休市回 0／0 |
| `jest-migrations-71`（`npx jest tests/db --runInBand`，臨時庫 Stock_migtest 套 28 個 migration） | 4 過（之前一次因測試裡寫死 27 失敗，同名覆蓋、未留在 checks.json） |

**回補完成**（2026-10-15 22:06 起、2026-10-16 01:31 結束，實跑約 3.4 小時、約 5.7 秒／日；`AI/experiments/iter71_backfill.log`：2,137 個交易日、3,321,740 列、休市 3、失敗 0；`checks.json` `insti-check-71`：合計 ≠ 三法人相加的列 0；「日線有而法人表沒有的交易日」列出 2018-12-22，但那天回補本來就抓到了（週六補班日，上市 437、上櫃 145 共 582 列，低於 `--check` 的 800 列門檻才被列為缺日；`insti-fill-20181222` 重跑該日 upsert 同一批 582 列，主鍵相同、總列數不變——`checks.json` `insti-status-after-fill`）；缺列的股票日 11.87%，集中在成交金額名次 1,000 以外，前 300 名只缺 0.06%——見 `UnifiedModel/results/portfolio_iter73_insti.md` 第三節；MoneyApi 原本仍是 03:32 的程序、日誌只套到 027，由本 session 用 Stop／Start-ScheduledTask 重啟後 `[Migration] Applied: 028_market_institutional.sql`）。指令： `cd Crawler && python institutional_data.py --backfill`（2018-01-01 起2,137 個交易日 × 2 次呼叫、每次間隔 2 秒；可中斷續跑），再 `--check`。

## 三、讀法

- 這一輪只是把資料路線打通；法人籌碼訊號（P18：外資連續買超、委託不平衡）要等回補完、`--check` 覆蓋率看過之後才登記假設，那時才算 N。
- 煙霧測試裡 2019-07-01 與 2026-10-14 證交所三大法人買賣超絕對值最大的（兩天都是淨賣超）是 00677U、00406A（ETF），這些代號不在 `market_universe`，寫庫時會被略過——法人表的股票池和日線一致。
- 外資自營商在證交所表裡單獨列（煙霧測試沒單獨印這一欄、全表比例沒統計），併入外資；若之後要「外資不含自營商」，解析器的 `f_n` 欄已分開讀，加一欄就好。

## 變更檔案

修改：`Crawler/scrapers/exchange_daily.py`（`TWSE_T86`、`TPEX_INSTI`、`ExchangeFormatError`、兩個 fetch、兩個 parse、`_check_identity`）、`Crawler/scheduler.py`（`job_institutional_daily`、18:35 排程、啟動訊息）、`Server/tests/db/migrations.test.js`（27 → 28）、`AI/Doc/DataSources.md`、`AI/Doc/Papers.md`（P18 狀態）、`AI/Doc/README.md`、`progress.md`
新增：`Server/migrations/028_market_institutional.sql`、`Crawler/institutional_data.py`、`Crawler/tests/test_institutional.py`
資料表：`market_institutional_daily`（migration 028；正式庫已於 2026-10-15 22:06 套用，`Server/logs/api.log`）
審查：evidence-reviewer 三輪 29／8／4 → 36／1／3 → 12／0／1 PASS（第一輪抓到 2018-12-22 不是缺日、結束時間 01:31 等八條，已改）
驗證：`checks.json` `pytest-institutional-71`（32 過）、`insti-parse-smoke-71`（exit 0）、`jest-migrations-71`（4 過）；沒跑全套 jest 與 vite build（只動 migration 與測試計數、前端沒改）
重啟：MoneyApi 已由本 session 重啟（套 migration 028）；**MoneyScheduler**（新排程 18:35）還沒重啟；MoneyCrawlerApi 不用
