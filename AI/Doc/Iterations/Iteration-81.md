# Iteration 81 — 籌碼結構面資料路線：全市場融資融券／借券賣出與外資持股／發行股數兩張表（交易所官方檔）建好、回補中；文獻第四批 12 篇

**日期：** 2026-10-18
**依據：** 使用者：「繼續上網找論文或是任何資料，實作交易策略或是月調倉方案，找更多種方案」（2026-10-17；同一則訊息先要求重啟 MoneyScheduler、commit 78／80、候選不換並全部列出——已做；重啟的證據 `checks.json` `sched-proc-81`：程序 `pythonw main.py --mode schedule` 2026-10-17 23:45:58 啟動）
**規則：** 資料工作，不算 N（N 仍 102）；沒跑任何回測；兩張新表走 `Server/migrations/030`、`031`，用 `Server/lib/migrate.js`（MoneyApi 啟動時跑的同一支）套用，沒有直接對正式庫下 ALTER；訊號假設等回補完、`--check` 覆蓋率看過（只看列數）之後另外登記再跑；保留期未開；候選不換。

## 一、做了什麼

1. **文獻第四批**（`AI/Doc/Papers.md` 第十節，P65～P76，12 篇，全部只讀到摘要或二手整理）：動能、價值兩個家族都已關閉，這批找的是**籌碼與結構面**——放空與融資（Lin, Ho & Ko 2023 PBFJ：放空流量預測台股報酬；Hu, Huang & Liao 2009 QREF：被放空最重的股票一個月負報酬；TEJ SIR 兩篇：法人借券賣出餘額市值 ÷ 市值，中大型股負向、排除 SIR > 0 再取 52 週高動能年化 21.69%／Sharpe 1.832；券資比碩士論文）、外資持股水準（Huang & Shiu 2009 FM：高外資持股股票報酬高）、週轉率（Lee & Swaminathan 的台灣版：低週轉率贏家較好）、規模（證據前後不一，不登記）、除權息／庫藏股（事件型或要 MOPS）、低價股（價值家族已關閉）都未登記。狀態「待資料」7 列（P65～P68、P70～P72），對應下一代要登記的四條假設：放空一條（借券 SIR，P67／P68）、散戶融資一條（P62）、外資持股水準一條（P70）、低週轉率動能一條（P72）。
2. **交易所端點探測**（`checks.json` `margin-holding-smoke-81` 之前的 curl，未記）：證交所 `marginTrading/MI_MARGN`（融資融券彙總，張，16 欄）、`marginTrading/TWT93U`（信用額度總量管制餘額表：融券＋借券賣出，股，15 欄）、`fund/MI_QFIIS`（外資及陸資投資持股統計：發行股數、持有股數、比率）；櫃買 `margin/balance`（20 欄，2018 與 2024 相同）、`margin/sbl`（15 欄，同 TWT93U 版面）、`insti/qfii`（持股比例排行表，10 欄，2018 與 2024 相同）。2018-01-02 起都有 JSON。櫃買 OpenAPI 的路徑清單（`/tpex_margin_sbl`、`/tpex_3insti_qfii` 等）只給當日，歷史仍走上述查詢端點。
3. **解析**（`Crawler/scrapers/exchange_daily.py`）：`parse_twse_margin`（16 欄按位置，欄名重複；張 × 1,000 存股）、`parse_twse_sbl`（15 欄按位置；回融券今日餘額當對位檢查、借券當日賣出與餘額）、`parse_tpex_margin`（按名稱）、`parse_tpex_sbl`（15 欄按位置）、`merge_margin_sbl`（兩張表共有的「融券餘額」逐列對位，不等的列 > 1% 就 `ExchangeFormatError`；借券表沒列的股票借券欄留 NULL）、`parse_twse_holding`／`parse_tpex_holding`（按名稱；持股比率與持有 ÷ 發行差 > 0.5 個百分點就擋下，`foreign_ratio` 一律存自己算的）。
4. **表與模組**：`market_margin_daily`（migration 030：融資買／賣／餘額、融券買／賣／餘額、借券當日賣出／餘額，股）、`market_foreign_holding_daily`（migration 031：發行股數、外資持有股數、比率）；`Crawler/margin_data.py`（一天四次呼叫）、`Crawler/holding_data.py`（兩次），和 `institutional_data.py` 同構（回補跳過已有的日子、失敗記下繼續、`--status`、`--check`）；排程 `job_margin_daily` 18:39、`job_holding_daily` 18:41（`scheduler.py`，啟動訊息同步）；`tests/test_margin_holding.py` 4 項、`test_scheduler.py` 加兩個工作、`migrations.test.js` 29 → 31。
5. **真實檔煙霧測試**（`margin-holding-smoke-81`，2018-01-03、2019-07-01、2021-06-01、2024-01-02、2026-10-16 ＋ 休市 2024-01-01）：融資融券上市 1,001～1,301 列、上櫃 635～918 列，借券欄 100% 有值、兩市對位檢查都過；外資持股上市 1,033～1,364 列、上櫃 746～894 列；休市四張表都回 0。台積電 2018-01-03：融資餘額 9,434,000 股、融券 2,321,000、借券賣出餘額 12,659,000；發行 25,930,380,458 股、外資 78.95%。
6. **回補**：2026-10-18 01:13 兩條同時起跑（`iter81_margin_backfill.log`、`iter81_holding_backfill.log`，delay 1.5 秒；融資融券約 6.5 秒／交易日、外資持股約 3.7 秒／交易日，2,141 天），外資持股 03:21 跑完：2,136 天成功、2 天失敗（2019-12-13、2026-10-15，見 7），修正後 03:24 補回；`holding-check-81`：2,090 檔、3,816,161 列、2,138 個交易日、2018-01-02～2026-10-16，有日線沒本表的交易日 0、有日線沒本表列的股票日 7,354／3,768,564（0.20%）、比率異常或持股 > 發行的列 0。融資融券**本紀錄寫時仍在跑**（寫時到 2022-12），完成數字與 `--check` 結果見 `progress.md`。
7. **轉上市當天兩市都有列**：外資持股回補失敗的兩天都是上櫃轉上市日（1795 美時 2019-12-13、8908 幸福 2026-10-15）——證交所檔那列是首日佔位（持有 59,000 股／0 股）、櫃買檔那列才是實際持股（68.93%／0.31%），同一批 upsert 撞 `(stock_id, trade_date)`。法人表與融資融券表那天都只在櫃買有列（查過 `market_institutional_daily`、`market_margin_daily` 的 1795），所以加 `drop_transfer_duplicates`（`exchange_daily.py`）：兩邊都有的代號丟證交所列、留櫃買列，`holding_data.py` 與 `margin_data.py` 的 `update_day` 都用；測試 +1（`pytest-margin-holding-81b` 18 過：test_margin_holding 5、test_scheduler 13）。正在跑的融資融券回補程序是舊碼，之後若撞到同類日子會記失敗、回補完再補跑。
8. **發行股數的點時性**（`holding-pit-81`，只看列）：9,147 次切換散在 2,024 個交易日、1,571 檔，最多一天 49 檔（2025-05-19），按月以 5 月 1,821 次最多（股東會後員工認股與可轉債轉換）；台積電每年 3 月與 5～6 月各動一次（幾十萬股）、長榮 2022-09-20 減資當天從 5,291,050,204 切到 2,116,420,082 股；五檔樣本（2330、2317、2454、2603、6488）的外資持股比率 2,137 天裡 1,886～2,068 天有變動。是逐檔在生效日切換的點時資料，不是像櫃買殖利率那樣回溯改寫。

## 二、結果（沒有回測；資料表與檢查）

| 項目 | 值 | 來源 |
|---|---|---|
| 新表 | `market_margin_daily`、`market_foreign_holding_daily`（migration 030、031 已套用） | `checks.json` `migrate-030-031` |
| 解析測試 | `pytest-margin-holding-81` 24 過（test_margin_holding 4、test_scheduler 13、test_valuation 3、test_institutional 4） | `checks.json` |
| 全套 | `pytest-81` 277 過；`jest-migrations-81` 4 過（31 個 migration 對新庫） | `checks.json` |
| 煙霧 | 五個日期＋休市，見一、5 | `margin-holding-smoke-81` |
| 回補 | 外資持股完成（03:24；2,138 個交易日、3,816,161 列、2,090 檔）；融資融券進行中（01:13 起） | `holding-check-81`、兩個 log |
| 點時性 | 發行股數 9,147 次切換散在 2,024 個交易日、最多一天 49 檔；見一、8 | `holding-pit-81` |
| 去重修正後測試 | `pytest-margin-holding-81b` 18 過 | `checks.json` |
| N | 102（不變） | `checks.json` `runs-count-81`（`SELECT max(experiment_n), count(*)`） |

## 三、讀法

- **這兩張表打開的是三個沒試過的家族：** （a）放空——法人借券賣出餘額（SIR，P67／P68；中大型股負向、候選池正是中大型）、融券餘額（P66）、放空流量（P65，借券當日賣出的 21 日累計 ÷ 成交量）；（b）散戶融資——融資餘額變動（P62，反向）；（c）外資持股水準與週轉率——`fhold`（P70）、`mom` × 低週轉率（P72；發行股數讓 P32 擱置的理由消失）。下一代（Iteration 82）登記四條、各一跑，不做組合搜尋：（a）放空一條、（b）散戶融資一條、（c）外資持股水準一條與低週轉率動能一條。
- **點時性要先查再用**（Iteration 80 的教訓）：融資融券與借券是當日盤後統計，應是點時；外資持股比率是當日結算後的持股；「發行股數」的切換日分布已查（一、8）：逐檔在生效日切換、散在全年，是點時資料。第十代登記檔（`AI/experiments/iter82_hypothesis.md`）引用這兩個檢查。
- **單位與覆蓋的坑：** 證交所融資融券以張、借券表以股——統一存股；沒有信用交易資格的股票不在融資融券表裡（同日融資融券列／外資持股列：上市 1,001～1,301／1,033～1,364、上櫃 635～918／746～894），`--check` 的「有日線沒本表列」會比法人表高，那不是缺資料；`universe` 過濾後每天會略過一到三百列（ETF 等非股票代號，近年較多：外資持股 2019-12-13 略過 160、2026-10-16 略過 280；是哪些代號沒查）。
- **TEJ 的 21.69%／1.832 不能直接當預期：** 廠商回測、未同儕審查、母體是全市場（含小型股）、等權 50 檔、月初再平衡；本專案的池是流動性前 300、前 20 等權、11 日訊號，照 P67 的「中大型股才負向」，方向應該有、幅度未知。
- **N = 102，保留期未開，候選不換。** 使用者 2026-10-17 決定：#94／#96、#90／#92、#87／#88、#99 都不升格，全部列在 `progress.md` 未解當跨段候補。

## 變更檔案

修改：`Crawler/scrapers/exchange_daily.py`（`TWSE_MI_MARGN`、`TWSE_TWT93U`、`TPEX_MARGIN`、`TPEX_SBL`、`LOT`、`MARGIN_MISMATCH_TOLERANCE`、`fetch_twse_margin`、`fetch_twse_sbl`、`fetch_tpex_margin`、`fetch_tpex_sbl`、`_lots`、`parse_twse_margin`、`parse_twse_sbl`、`parse_tpex_margin`、`parse_tpex_sbl`、`merge_margin_sbl`、`TWSE_MI_QFIIS`、`TPEX_QFII`、`HOLDING_RATIO_TOLERANCE`、`fetch_twse_holding`、`fetch_tpex_holding`、`_holding_row`、`parse_twse_holding`、`parse_tpex_holding`、`drop_transfer_duplicates`）、`Crawler/scheduler.py`（`job_margin_daily` 18:39、`job_holding_daily` 18:41、啟動訊息）、`Crawler/tests/test_scheduler.py`、`Server/tests/db/migrations.test.js`（29 → 31）、`AI/Doc/Papers.md`（第十節 P65～P76）、`AI/Doc/DataSources.md`（兩列）、`AI/Doc/README.md`、`progress.md`
新增：`Crawler/margin_data.py`、`Crawler/holding_data.py`、`Crawler/tests/test_margin_holding.py`（5 項）、`Server/migrations/030_market_margin.sql`、`031_market_foreign_holding.sql`、`AI/experiments/iter81_runs_count.py`、`AI/Doc/Iterations/Iteration-81.md`；回補日誌 `AI/experiments/iter81_margin_backfill.log`、`iter81_holding_backfill.log`（*.log 不進 git）
資料表：`market_margin_daily`、`market_foreign_holding_daily`（回補中）；`portfolio_runs` 不動
驗證：`checks.json` `pytest-margin-holding-81`（24 過）、`migrate-030-031`、`margin-holding-smoke-81`、`jest-migrations-81`（4 過）、`pytest-81`（277 過）、`runs-count-81`（max 102／102 列、最後一筆 2026-10-17 22:56；第十代第一批之後是 104）、`holding-check-81`、`holding-pit-81`、`pytest-margin-holding-81b`（18 過，去重修正後）、`sched-proc-81`（排程器程序 23:45:58、`scheduler.py` mtime 23:55:18、兩個回補程序 01:12:54 起）；審查紀錄 `evidence-reviewer-81`（輪後記入）；沒跑全套 jest 與 vite build（Node 路由與前端沒改）
重啟：**MoneyScheduler**（18:39／18:41 兩個排程還沒掛上：現行程序 2026-10-17 23:45:58 啟動，早於本輪的 `scheduler.py` 修改；`sched-proc-81` 同時印了 `scheduler.py` 的 mtime）；MoneyApi 不用（migration 030／031 已由 `lib/migrate.js` 套用）；MoneyCrawlerApi 不用（`api.py` 沒改）
