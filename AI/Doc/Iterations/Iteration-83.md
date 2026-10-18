# Iteration 83 — 追蹤股 26 → 68 檔（0050 成分股 42 家）：FinMind 回補 126 次未觸額度；公司行動改以交易所檔為準（FinMind 的「權」列參考價＝前收，會漏掉股票股利）；追蹤股三張表每日從全市場表補 FinMind 漏掉的列

**日期：** 2026-10-18
**依據：** 使用者：「候選不換，都先列出。然後先補更多家的股票資料」
**規則：** 不碰回測：`portfolio_runs` 不寫、N 仍是 108、候選 #44 不換、保留期未開。只動追蹤股那條鏈（`stock_info.is_tracking` 與 `stock_daily_prices`／`stock_chip_analysis`／`stock_foreign_holding`）；全市場表（`market_*`）只讀。不直接對正式庫下 ALTER／DELETE（只有 `stock_info` 兩列的 `market_type` 用 UPDATE 改成交易所檔的值）。

## 一、做了什麼

「更多家的股票資料」讀成：追蹤股清單（`stock_info.is_tracking`，原本是 `AI/UserDoc/Target.md` 的 20 家＋2330／2327／2883＋0050／0052／0056 共 26 檔）擴大。
挑 0050 成分股——專案要打敗的就是它，成分股的個股頁、法人持股、新聞情緒、每週預測、投票都應該看得到。

1. **成分股清單**：MoneyDJ 的 0050 持股（持股日期 2026-09-30）50 檔；名稱對 `market_universe` 逐檔查代碼，兩檔網頁沒印代碼、對照後改正（川湖 2059、鴻勁 7769）。
   已追蹤 8 檔（2330、2303、3037、2327、2883、2344、3231、2449），新增 **42 檔**：
   2454 2308 2317 3711 2383 2881 1303 2891 3017 2882 2887 2345 2382 2360 2885 2884 2408 2059 3443 2357 6669 3653 2886 2890 3008 2301 2412 3665 2892 2880 4958 2368 6446 1216 2395 8046 7769 5880 2603 4904 3045 6505。
2. **FinMind 回補**（`backfill_prices.py --stocks … --start 2000-01-01 --chips --holding`，`finmind-backfill-83`）：42 檔 × 3 = 126 次呼叫，08:18～08:21 跑完，失敗 0、沒碰到額度；
   行情 233,107 列、籌碼 142,685 列、外資持股 208,953 列（`logs/backfill_prices_iter83.log`）。
3. **列進追蹤清單**（`sync_stock_info.py`，FinMind 1 次呼叫）：`stock_info` 26 → 68 檔，全部 `is_tracking`。FinMind 對轉過市場的股票會回舊市場別
   （7769 鴻勁回 `emerging`、6446 藥華藥回 `tpex`），改成 `market_universe`（交易所檔）的 `twse`。新聞別名 `news_alias.seed()` 新增 41 筆（公司名）。
4. **公司行動與 adj_close**：先照既有流程 `backfill_dividend.py`（FinMind，1990 起）914 筆＋`rebuild_adj_close.py`（FinMind 減資）重建 233,023 列。
   對照全市場表時發現 **FinMind 的「權」（股票股利）列 reference_price ＝ before_price**（`iter83-evidence`，`AI/experiments/iter83_evidence.py` 再打一次 FinMind 對事件表現值：
   2890 2026-10-07 權：FinMind 45.40／45.40，證交所 TWT49U 45.40／44.97；2313 2026-06-22 權：FinMind 259.50／259.50，交易所 259.50／257.64；
   「息」與「權息」列兩邊一樣：2313 2026-06-02 282.0／279.2、2890 2026-07-23 40.4／38.52），用它重建的 adj_close 漏掉股票股利——而且 `backfill_dividend` 把交易所寫的列蓋掉了
   （兩條路線共用 `stock_dividend_result`）；改前的 `job_stock` 每天也會這樣蓋 180 天窗口（commit 05d3cc0 的 `Crawler/scheduler.py` 第 99 行 `backfill_dividend.fetch_dividends(ids, start)`，`start` 是今天 − 180 天）。
   處理：`AI/experiments/iter83_restore_events.py` 用交易所檔重寫事件表（`events-restore-83`）：2018 起除權息 13,469 筆、減資 217 筆、1,929 檔、失敗 0 段；
   2000～2017 除權息 13,376 筆、減資 100 筆、1,679 檔（事件表裡最早的交易所除權息列是 2003-06-02；櫃買檔較晚——抽查 2003-07 回空、2010-06 有 23 列；TWTAUU 減資年檔 2014／2015／2016 三段失敗：
   同一檔同一天印兩列（2408 2014-09-09、2438 2014-11-21，兩列內容一樣——主 session 抓檔比對，沒另存輸出）→ `parse_twse_capital_reduction` 改成以 (股票, 日) 去重，
   重抓三年補上 79 筆（`iter83-evidence`：2014～2016 減資 79 筆）。事件表 2018 以前現有除權息 13,396 筆（最早 2003-06-02）、減資 179 筆（137 檔）（同上）。
   重建 68 檔 403,572 列（主 session 跑 `rebuild_adj_close.rebuild(追蹤股)` 的回傳值，沒另存日誌）。
   `scheduler._refresh_adj_close` 不再打 FinMind 抓事件（事件表由 `job_market_daily` 用交易所檔維護，Iteration 48 起）。
   另一個被對照抓出來的錯：`rebuild_adj_close.load_events` 的 factor 上限 5 會略過減資九成（2408 2014-09-09 停止買賣前 8.10、恢復買賣參考價 80.93；
   `rebuild_adj_iter83.log` 裡 FinMind 的列「8.1000→80.9300（9.991）」被略過，`iter83-evidence` 裡交易所重寫後的列同樣是 8.10／80.93「彌補虧損」），
   2014-09 以前的 adj_close 就少十倍；減資的上限改成 20（除權息仍 5）。追蹤股裡 factor ≥ 5 的減資只有這一筆（`iter83-evidence`）。
5. **追蹤股三張表從全市場表補齊**（新檔 `Crawler/tracked_sync.py`，排程 18:43 `job_tracked_sync`）：`job_stock` 每檔打 FinMind 3 次、68 檔一天 204 次；FinMind 文件寫匿名 30 次／小時，
   排程 2026-09-22～10-17 的 18 次 `job_stock`（當時 130 次／天）都成功，204 次撐不撐得住沒試過——這是保險，不是修已發生的錯
   （scheduler.log 裡的「Requests reach the upper limit」（2026-10-18 09:10 時 104 行，檔案會輪替）全是 pytest 的假 FinMind 寫進去的：`scheduler.py` import 時掛檔案 handler，`tests/test_freshness.py`、`tests/test_price_parsers.py` 的假錯誤字串就落在同一個檔，時刻和本輪 pytest 08:24／08:42／09:09 吻合）。
   三張全市場表 18:30／18:35／18:41 已由交易所檔更新，和 FinMind 同日同值（第二節），
   所以把缺的列 `INSERT … SELECT … ON CONFLICT DO NOTHING` 補進去；交易所檔漲跌是 NULL 的日子（檔裡印 X）用前一日收盤算回來；
   補到行情列的股票、加上窗口內有公司行動的追蹤股，重建 adj_close（18:00 重建時 18:30 才進表的事件補上）。
   一次性跑 `--since 2018-01-01`（`tracked-sync-fill-83`）：行情 +1,838 列（只有 2327 國巨：補列前 `stock_daily_prices` 的 2327 從 2025-08-08 起（主 session 補列前的查詢，沒另存），
   補完 2018-01-02 起 2,120 列（`iter83-evidence`））、
   籌碼 +17,938 列、外資持股 +9 列。
6. **MOPS 重大訊息**：`backfill_mops.py --stocks …` 42 檔、2023-09～2026-10，每次請求 3～6 秒，08:16 啟動（第一筆完成 08:19:02，`logs/backfill_mops_progress.json`）、142.2 分跑完（`mops-backfill-83`）：16,138 則、`news_crawl_raw` +16,138、`user_news` +15,681（去重後）、失敗 0（`logs/backfill_mops_iter83.log`）。
   月營收（`stock_revenue_announce`）本來就是全市場表，42 檔都已有 5,875 列（`iter83-evidence`）。新聞別名 41 筆也在 `iter83-evidence`（42 檔裡沒進別名表的是 2603：「長榮」在 `news_alias._GENERIC` 清單裡，太泛不當別名）。

## 二、結果（`tracked-sync-compare-83`，`AI/experiments/iter83_compare.py`；2018-01-02 起兩表共有的股票日）

| 對照 | 共有股票日 | 相同 |
|---|---|---|
| 日線：收盤 | 136,507 | 100.0% |
| 日線：開高低 | 136,507 | 100.0% |
| 日線：成交量 | 136,507 | 97.4%（不同的 3,607 列全是上櫃期間：5483 整段 2,131 列、6446 轉上市前 2018-01-02～2024-01-24 1,476 列、FinMind 平均多 3.00%（`iter83-evidence`）：櫃買檔成交量不含零股與盤後，FinMind 含；上市期間全同） |
| 日線：漲跌 | 136,507 | 有值的列 100% 相同；交易所檔 NULL 10,620 列（7.8%） |
| 日線：adj_close（差 ≤ 0.05%） | 136,507 | 事件表重寫前 90.4%（10 檔差 0.44～3.64%，都是「權」；第一次 compare 的輸出被同名紀錄覆蓋，數字是主 session 當時的輸出）→ 重寫後 **100.0%** |
| 三大法人：外資／投信／自營／合計 | 136,550 | 100.0% |
| 外資持股：持股股數、發行股數 | 136,676 | 100.0%（比率差 ≤ 0.01 100.0%） |

追蹤股 68 檔現況：行情 403,770 列（最早 1992-01-04：2303、2312、2313；新股 3711 2018-04-30、7769 2024-11-01）、籌碼 200,362 列、外資持股 300,947 列、最新交易日 2026-10-16；
`adj_close` NULL 198 列（0052 105 列 2010～2018、3653 72 列 2008～2009、其餘 18 檔各 1～2 列共 21 列）全是 close_price ≤ 0 或 NULL 的列（`iter83-evidence`：198／198，反向 0 列；重建本來就略過）。
新鮮度檢查（`freshness-83`，`iter83_freshness.py` 明確傳入 68 檔——`data_freshness.check()` 預設只看預測比對與持股用到的股票）：68 檔落後 0。

| 驗證 | 結果 |
|---|---|
| `finmind-backfill-83` | 126 次呼叫、失敗 0 |
| `tracked-sync-fill-83` | 行情 +1,838、籌碼 +17,938、外資持股 +9 |
| `tracked-sync-compare-83` | 上表 |
| `freshness-83` | 明確傳入 68 檔，落後 0 |
| `mops-backfill-83` | 42 檔 16,138 則、user_news +15,681、142.2 分、失敗 0 |
| `iter83-evidence` | 審查補證據：FinMind 對交易所除權息列、2018 以前事件筆數、2014～2016 減資 79 筆、adj NULL 198／198、2327、6446 3.00%、全市場 factor ≥ 5 三筆、月營收 5,875、別名 41、7769／6446 市場別 |
| `events-restore-83` | 2018 起除權息 13,469、減資 217、1,929 檔；2000～2017 除權息 13,376、減資 100＋79、1,679 檔 |
| `pytest-tracked-sync-83` | 23 passed（`test_tracked_sync` 1、`test_scheduler` 13、`test_upsert` 9，含減資九成那項） |
| `pytest-events-83` | 39 passed（`test_market_data` +1 去重、`test_upsert` +1 減資九成、`test_tracked_sync`） |
| `pytest-83` | 282 passed |
| `adj-rebuild-dry-83` | 只讀試算：全市場 2,621 檔重算會變動 3 檔、2,331 列（1529 217、2364 908、3043 1,206） |
| `adj-rebuild-83` | `market_data.rebuild_adj()` 更新 2,331 列（2,621 檔、2,144 檔有公司行動；14:23～14:24） |
| `adj-rebuild-evidence-83` | 三檔只在 #54／#58／#62 持股過（除權日之後）；8913 2018-06-04 208 → 19.90 被 factor 下限略過；N 108 |

## 三、讀法

- 對專案的意思：儀表板個股頁、法人持股、新聞個股標記、每週預測、三模型投票現在涵蓋 0050 全部成分股。月調倉研究不受影響——股票池與訊號只讀全市場表，只有 0050 基準從 `stock_daily_prices` 讀 adj_close（`portfolio_signal.py` 開頭說明），0050 是上市 ETF、本輪沒補到它的列。
- **公司行動以交易所檔為準**：FinMind 的「息」列和交易所一致，「權」列不給參考價。追蹤股的歷史現在 2003-06 起用交易所事件（上櫃較晚）；更早的只有 FinMind 事件，股票股利沒調。
- **減資上限放寬會動到全市場表**：`market_data.rebuild_adj` 共用 `load_events`，2018 起全市場有 3 筆減資 factor ≥ 5（1529 2018-12-22 ×9.09、2364 2021-10-08 ×7.90、3043 2022-12-19 ×5.00），
  這三檔的 `market_daily_prices.adj_close` 在 d1835fa 時還是舊值（少調一次）。**使用者 2026-10-18 決定重建**：先只讀試算（`adj-rebuild-dry-83`）——全市場 2,621 檔（有事件 2,144 檔）依現行事件表重算，
  會變動的只有這三檔、2,331 列（1529 217、2364 908、3043 1,206，都是除權日以前的列）；再跑 `market_data.rebuild_adj()` 全市場（`adj-rebuild-83`，14:23～14:24）更新 2,331 列，
  例：1529 2018-12-12 收 2.36 的 adj 1.3518 → 12.2864、2364 2021-09-29 收 3.04 的 adj 1.2635 → 9.9790（除權日當天起不變）。旁證（`adj-rebuild-evidence-83`）：三檔在 `portfolio_positions` 只出現在
  #54、#58、#62（rev_accel／rev1m 家族 valid，2022-12～2023-08，都在除權日之後；候選與 live 清單都沒有），這三列若重跑，2364 的動能回看會跨過 2021-10-08、排名可能略變，其餘 run 不受影響。
  同一次 `load_events` 另警告略過 8913 全銓租賃 2018-06-04 除權息 208 → 18.11（factor 0.087，低於除權息下限 0.2；市場收盤 208 → 19.90 是真的斷層；該股 `market_type` NULL、2020-01-20 下市），
  它 2018-06-04 以前的 adj_close 仍高十倍，留在「未解」。追蹤股裡只有 2408 一筆、已重建。
- FinMind 匿名額度比文件寫的 30 次／小時寬：126 次在 2 分 53 秒（08:18:48～08:21:41）沒被擋，`job_stock` 每天 130 次 2026-09-22～10-17 的 18 次都成功；
  scheduler.log 裡的 upper limit 全是 pytest 寫的，排程沒撞過額度。現在每天 204 次沒試過；真撞到的日子 18:43 從交易所表補——不會變成「某檔今天沒資料」。
- 排程負擔：`job_news` 每小時 Yahoo 個股 RSS 26 → 68 條；`job_vote` 68 檔；`job_weekly_forecast` 台股 68 檔 × 10 個 LSTM（`LSTM/serve.py` 只載 `saved_models/cross_stock/{模型}.keras`，是跨股模型、逐股的舊檔不再用；新股是否只要 LOOKBACK 筆行情就能推論，這輪沒驗）。
  2026-10-18 08:00 那次跑的還是 26 檔；要看第一個週日（2026-10-25）的執行時間。
- 成交量的差只在上櫃期間（櫃買檔不含零股與盤後）；收盤、開高低全同。補進去的上櫃列成交量會比 FinMind 的小約 3%；月調倉只從追蹤股表讀 0050 的 adj_close，其他模型的特徵沒逐一查成交量。
- 兩個來源的列並存在同一張表：補進去的列沒有標記來源（`stock_daily_prices` 沒有 `source` 欄）。要分辨得看 `market_daily_prices.fetched_at` 或日期段。

## 變更檔案

修改：`Crawler/scheduler.py`（`job_tracked_sync` 18:43；`_refresh_adj_close` 不再打 FinMind；啟動訊息）、`Crawler/scrapers/exchange_daily.py`（`parse_twse_capital_reduction` 去重）、
`Crawler/rebuild_adj_close.py`（減資 factor 上限 20）、`Crawler/tests/test_scheduler.py`、`tests/test_market_data.py`（+1）、`tests/test_upsert.py`（+1）、`Crawler/tests/helpers/db_setup.py`（`market_institutional_daily`／`market_foreign_holding_daily`／`market_valuation_daily`／`market_margin_daily` 四張進 truncate 清單）、
`AI/Doc/DataSources.md`（追蹤股清單、補齊路線）、`AI/Doc/DB.md`（§2.1 追蹤股清單與加股步驟）、`AI/Doc/README.md`、`progress.md`。
新增：`Crawler/tracked_sync.py`、`Crawler/tests/test_tracked_sync.py`、`AI/experiments/iter83_compare.py`、`AI/experiments/iter83_freshness.py`、`AI/experiments/iter83_restore_events.py`、`AI/experiments/iter83_evidence.py`、`AI/experiments/iter83_rebuild_adj.py`（`--dry`／`--run`）、`AI/experiments/iter83_rebuild_adj_evidence.py`、
`Crawler/logs/backfill_prices_iter83.log`、`backfill_dividend_iter83.log`、`rebuild_adj_iter83.log`、`restore_events_iter83.log`、`backfill_mops_iter83.log`（`*.log` 不進 git）。
資料：`market_daily_prices.adj_close` 2,331 列重算（1529、2364、3043 除權日以前）、`stock_info` +42 列（68 檔追蹤）、`stock_daily_prices` +234,945 列、`stock_chip_analysis` +160,623 列、`stock_foreign_holding` +208,962 列、`instrument_alias` +41、`stock_info` 7769／6446 的 `market_type` 由 FinMind 的 emerging／tpex 改成 twse（UPDATE 兩列，`iter83-evidence` 只驗現值）、
`stock_dividend_result`／`stock_capital_reduction` 2000 起改為交易所檔的值、`news_crawl_raw` +16,138、`user_news` +15,681（MOPS）。
