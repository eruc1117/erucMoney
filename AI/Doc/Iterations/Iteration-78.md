# Iteration 78 — 第八代：波動處理的動能（除以波動、去極端波動）開發期都低於候選，家族關閉；全市場估值表（本益比／殖利率／淨值比）建好、回補完成

**日期：** 2026-10-17
**依據：** 使用者：「現在繼續找不同種月調倉（打敗大盤），多看論文或是網路文章整理資料」
**規則：** 事前登記 `AI/experiments/iter78_hypothesis.md` 寫於 2026-10-17 20:20（mtime 20:20:22，`checks.json` `iter78-prereg-mtime`；檔頭原寫 20:40 是估的時間，對 mtime 改正後 mtime 20:23:57，`iter78-prereg-mtime-after`），跑網格（20:26）之前、沒看過任何這兩個訊號的統計；只在開發期跑、各一次、不調參；valid 只給「過門檻且年化主動與 IR 都超過 #30」的——兩條都沒有，所以沒跑；保留期未開；候選不換；新表走 `Server/migrations/029`，用 `Server/lib/migrate.js`（MoneyApi 啟動時跑的同一支）套用，沒有直接對正式庫下 ALTER。

## 一、做了什麼

1. **文獻第三批**（`AI/Doc/Papers.md` 第九節，P51～P64，14 篇，全部只讀到摘要或二手整理）：找的是和動能排名**不同種**的訊號——台股的波動處理動能（Huang, Pan & Wang 2026 JRFM；Lin, Xia, Yang & Yang 2020 PBFJ；Yang & Zhang 2019 JFM；TEJ 特質波動與 VAM 兩篇網路文章）、價值（Asness, Moskowitz & Pedersen 2013；Hsu, Lee, Chang & Fung 2015 說台股用 E/P、D/P 比 B/M 好；Liang 2020；Novy-Marx 2013 要財報）、散戶融資（Ting, Lu & Chou 2018）、MAX 效應的台灣證據（主要在小型股）、動能缺口（Huang 2022；台灣證據為負 Lin, Ko & Yang 2022）。登記兩條假設（H16、H17）、一項資料前置（H18）；不登記五篇，理由寫在表裡。
2. **訊號**（`Crawler/portfolio_signal.py`）：`_mom_and_vol` 用 `mom` 同一個 12-1 窗口（`_mom_window`）算累積異常報酬與每日異常報酬標準差（都要 ≥ 80% 交易日有值）；`vmom` ＝ `mom` ÷ 標準差（標準差 0 或缺不給值，所以 0050 自己沒有值）；`momx` ＝ `mom` 但標準差在全市場（有 `mom` 值的股票）最高十分位不給值（`MOMX_VOL_CUT = 0.9`，文獻分組慣例，不調）。`signal_mom`／`signal_win3` 沒動（`iter78-git-hunks`：`AI/experiments/iter78_signal_hunks.txt`，對 4b8c8a8 的三個 hunk 舊行 599、642、724，現行檔 235～256 行不在其中）。
3. **兩跑 dev**：#97 `win3+vmom-t3-tsmcest`（H16，`vmom` 取代候選的 `mom`）、#98 `win3+momx-t3-tsmcest`（H17）。網格 `iter78_grid.json`，日誌 `iter78_dev.log`（14 秒），`checks.json` `iter78-dev`。
4. **結果檔** `UnifiedModel/results/portfolio_iter78_volmom.md`（`iter78_results.py`：指標表含對照 #30 與 #51、逐年、`vmom`／`momx` 對 `mom` 的等級相關與 ρ(mom, vol)、池內被 `momx` 排除的比例、前 20 重疊、`portfolio_positions` 實際持股流動性名次與交集、第六節「候選前 20 裡被 `momx` 排除的股票之後一個月的異常報酬」——第三節的 ρ(mom, vol) 與第六節是 strategy-critic 審查後補的，結果檔重新產生）。
5. **資料前置（不算 N）**：全市場個股估值表 `market_valuation_daily`——證交所 `afterTrading/BWIBBU_d`（收盤、殖利率、股利年度、本益比、股價淨值比、財報年/季，8 欄）＋櫃買 `afterTrading/peQryDate`（本益比、每股股利、股利年度、殖利率、股價淨值比，7 欄；2018 與 2024 欄名相同），按欄位名解析，虧損的「-」／N/A → NULL，「股價淨值比為正的列 < 50%」當欄位對錯擋下（`VALUATION_MIN_PB_SHARE`）。`Crawler/valuation_data.py`（回補／單日／狀態／檢查，和 `institutional_data.py` 同構）、migration 029、排程 `job_valuation_daily` 每日 18:37、`tests/test_valuation.py` 3 項、真實檔煙霧測試五天＋一個休市日過（`val-parse-smoke-78`：2018-01-02 上市 906／上櫃 742 列、2026-10-16 1,082／885 列，本益比有值 69～82%、殖利率與淨值比 100%）。回補 2018-01-02 起，20:26 開始、22:26 完成（`iter78_valuation_backfill.log`：2,138 個交易日、3,804,828 列、休市 3、失敗 0；約 3.4 秒／交易日）。`--check`（`checks.json` `val-check-78`）：2,085 檔、2018-01-02～2026-10-16；日線有而估值表沒有的交易日 0；兩表都有的日子裡有日線沒估值列的股票日 9,042／3,768,564（0.24%）；本益比有值 77.2%、殖利率與淨值比 100%；pb ≤ 0 的列 1、殖利率 > 50 的列 517（下一代定義 `dy` 前要看這 517 列是什麼，例如一次性大額股利，決定截尾或排除——只看列、不看報酬）。

## 二、結果（`portfolio_runs.metrics`；結果檔 `portfolio_iter78_volmom.md`）

| N | 設定 | 段 | 年化主動 | IR | 追蹤誤差 | 相對最大落後 | 月勝率 | 換手 | 調倉次數 |
|---|---|---|---|---|---|---|---|---|---|
| 30 | win3+mom-t3-tsmcest（候選） | dev | +8.64% | 0.67 | 12.9% | −14.7% | 55% | 3.6 | 35 |
| 51 | win3+mom+lowvol（Iteration 53，低波動**相加**） | dev | +2.47% | 0.241 | 10.3% | −11.5% | 53% | 3.24 | 35 |
| **97** | **win3+vmom**（H16） | dev | +7.92% | 0.627 | 12.6% | −15.7% | 55% | 3.56 | 35 |
| **98** | **win3+momx**（H17） | dev | +6.94% | 0.578 | 12.0% | −12.8% | 51% | 3.5 | 35 |

逐年主動報酬（結果檔第二節）：

| N | 2018 | 2019 | 2020 | 2021 |
|---|---|---|---|---|
| 30 候選 | +11.7% | +6.4% | +18.1% | +1.6% |
| 97 | +7.8% | +3.5% | +21.3% | +2.9% |
| 98 | +10.2% | +5.2% | **+5.7%** | **+9.1%** |

訊號與持股（結果檔第三～五節，dev 35 個訊號日）：

| 比較 | ρ(mom, ·) 中位數 | 前 20 重疊（對 win3+mom）中位數 | 實際持股交集中位數（對 #30） | 池內被排除的比例（中位數） | 持股流動性名次中位數 |
|---|---|---|---|---|---|
| vmom（#97） | 0.98 | 18 | 17／20 | — | 106（候選 100） |
| momx（#98） | —（同值） | 12 | 13／20 | 15%（最小 7%、最大 23%） | 108 |

## 三、讀法

- **H16 不成立（開發期）：** `vmom` 與 `mom` 的等級相關 0.98、持股交集 17／20——除以同窗口的波動幾乎不改變排名。候選池內 `mom` 與波動本身的等級相關中位數是 0.58（結果檔第三節 ρ(mom, vol)），所以除以波動壓低了高波動贏家的分數，但次序大致不變（排名平均只看名次）。年化主動 +7.92% 對 +8.64%、IR 0.627 對 0.67、相對最大落後反而更深（−15.7%）；「風險調整後改善」的預期沒有出現。P51（Huang, Pan & Wang 2026）只讀到摘要，無法確認它的「波動縮放」是個股排名層級還是組合部位層級；本輪只測了「個股 `mom` ÷ 同窗口波動」的排名版，結果不等於對 P51 的否定。
- **H17 不成立（開發期），但波動那一面和文獻一致：** 去掉高波動股後相對最大落後 −12.8%（候選 −14.7%）、追蹤誤差 12.0%（12.9%）——Yang & Zhang 2019（P53）說的「組合波動降」有出現（Lin 等 2020 的摘要只說拿掉後動能顯著、沒有崩盤）；但年化主動少 1.7 pp，差距集中在 **2020 年**（+5.7% 對 +18.1%）。結果檔第六節量了這件事：候選前 20 裡每個訊號日平均有 7.5 檔被 `momx` 排除（2020 年 8.2 檔），2020 年被排除者下一個月的異常報酬平均 +2.39%、留下者 +0.57%（差 +1.82%／月，12 個訊號日）——當年被拿掉的正是之後漲較多的股票；2021 年反過來（−1.79% 對 +1.76%，差 −3.55%），對應 #98 2021 +9.1% 對候選 +1.6%。全期差 −0.09%／月，排除沒有系統性的方向。池內實際被排除 15%（排除線在全市場算，池內股票波動偏高：中位數 2.36% 對 1.96%）。
- **「相加」對「除以／排除」：** 低波動相加（#51，+2.47%）比兩者都差，方向和 TEJ 特質波動研究「當過濾比當 alpha 訊號好」一致（排除版 #98 比相加版 #51 多 4.5 pp）；但 #51 的波動是 60 日 log 報酬標準差、#98 是 12-1 窗口異常報酬標準差，定義和用法兩件事都不同，4.5 pp 不能單獨歸給「過濾對相加」。過濾版仍低於不處理的候選。
- **家族關閉**（登記的規則）：波動處理的動能（`vmom`、`momx`、`lowvol` 相加）不再登記；不試其他分位或窗口。動能缺口閘門（P54）因台灣證據為負（P55）也不登記。
- **資料前置的讀法：** 估值表是交易所每天用「最近公告股利／財報」算的，本益比虧損印「-」（上市有值 78～82%、上櫃 69～76%），殖利率與淨值比全有。下一代登記的價值訊號 `dy`（殖利率）、`ep`（1 ÷ 本益比）依 Hsu 等 2015 的台灣證據，不用 B/M；和候選的動能是負相關的另一種訊號（Asness 等 2013）。**回補完、`--check` 覆蓋率看過之後才登記；覆蓋率只看列數，不看報酬。**
- **N = 98，保留期未開，候選不換。** 文獻驅動八代（Iteration 66～70、72、73、78）共 29 次試驗：有效實作裡 3 次開發期超過候選（#87、#90、#94），乾淨的驗證期確認裡 0 次超過候選。

## 變更檔案

修改：`Crawler/portfolio_signal.py`（`MOMX_VOL_CUT`、`_mom_and_vol`、`signal_vmom`、`signal_momx`、`_single`、`SINGLE_SIGNALS`）、`Crawler/scrapers/exchange_daily.py`（`TWSE_BWIBBU`、`TPEX_PE`、`VALUATION_MIN_PB_SHARE`、`fetch_twse_valuation`、`fetch_tpex_valuation`、`_val_row`、`_check_valuation`、`parse_twse_valuation`、`parse_tpex_valuation`）、`Crawler/scheduler.py`（`job_valuation_daily`、18:37 排程、啟動訊息）、`Crawler/tests/test_portfolio.py`（+1，35 項）、`Crawler/tests/test_scheduler.py`（加 `job_valuation_daily` 18:37 斷言）、`Server/tests/db/migrations.test.js`（28 → 29）、`AI/Doc/Papers.md`（第九節 P51～P64、第五節第八代、第六節）、`AI/Doc/DataSources.md`（估值表一列）、`AI/Doc/README.md`、`progress.md`
新增：`Crawler/valuation_data.py`、`Crawler/tests/test_valuation.py`（3 項）、`Server/migrations/029_market_valuation.sql`、`AI/experiments/iter78_hypothesis.md`、`iter78_grid.json`、`iter78_results.py`、`iter78_dev.log`、`iter78_signal_hunks.txt`、`iter78_valuation_backfill.log`、`UnifiedModel/results/portfolio_iter78_volmom.md`
資料表：`portfolio_runs` #97～#98；`market_valuation_daily`（migration 029 已套用；3,804,828 列、2,138 個交易日，`val-check-78`）
驗證：`checks.json` `iter78-prereg-mtime`、`iter78-prereg-mtime-after`、`pytest-portfolio-78`（51 過：test_valuation 3、test_portfolio 35、test_scheduler）、`migrate-029`、`val-parse-smoke-78`、`iter78-dev`、`pytest-78`（272 過，含另一個 session 的交易模擬測試）、`iter78-results`、`jest-migrations-78`（4 過，含 29 個 migration 對新庫）、`iter78-git-hunks`（hunk 標頭 3 列，檔頭寫 base 4b8c8a8）、`iter78-prereg-sha256`（登記檔的 sha256，審查後才補記，改正檔頭之後的內容）；審查紀錄 `strategy-critic-78`（PASS）、`evidence-reviewer-78`。本輪**沒跑**全套 jest 與 vite build（Node 路由與前端本輪沒改）；`checks.json` 裡名字帶 78 的 `jest-78`（193 過、17 套，20:29）、`vite-build-78`、`mfe-build-78`、`mfe-eslint-78`（20:30）是同一工作區另一個 session 對交易模擬前端檔（RuleBuilder、TradingSim、api.js，其 Iteration 79）跑的，不是本輪的驗證（歸屬依時間與對象推斷，checks.json 不記 session，待確認）
重啟：**MoneyScheduler**（18:37 估值排程還沒掛上：`Crawler/logs/scheduler.log` 24189 行 2026-10-16 20:00:54 的「排程器啟動」列是最後一次對正式庫 `Stock` 的啟動，列出的排程沒有「估值 18:37」；程序 `pythonw main.py --mode schedule` 的啟動時間 2026-10-16 20:00:53 是用 Get-CimInstance 查的，輸出記在 `checks.json` `sched-proc-78`。2026-10-17 20:25～20:32 的五次「排程器啟動」之前最近一條「連線池已建立」列（26117、26145、26201、26370、26539 行）都是 `localhost:5432/Stock_crawler_test`，其間沒有對 `Stock` 的連線池列——是 pytest 跑 `test_scheduler` 印的，不是常駐工作）；MoneyApi 不用重啟（migration 029 已由 `lib/migrate.js` 套用，重啟時只會印 Already applied）；MoneyCrawlerApi 不用重啟（`signal_win3`／`signal_mom` 沒動）
