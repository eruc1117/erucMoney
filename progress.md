# 交接筆記

**更新：** 2026-10-18（Iteration 84 資料更新後重算 14 列持股全同、未提交；Iteration 83 已提交 d1835fa、80a00da；81、82 已提交 05d3cc0；三個常駐工作已於 2026-10-18 14:19 全部重啟——MoneyCrawlerApi 與 MoneyApi 在 12:44 被關掉（結束碼 0xC000013A，主控台視窗關閉），:8000／:3001 停了 95 分鐘；MoneyScheduler 19 個排程、18:43 追蹤股補齊掛上）
（格式見 `.claude/rules/iterations.md`；儀表板「工作進度」頁讀這個檔。只寫有證據的事。）

## 任務
Iteration 84（未提交）：使用者「以目前新的股票資料，重新分析月調倉」→ 先分清 83 的資料變動哪些進月調倉（追蹤股 68 檔**不進**，股票池與訊號只讀全市場表；進的只有全市場 adj_close 三檔 2,331 列與 0050 基準，0050 對 #44 存的 1,635 點最大差 0.0005%），再把 14 列已登記 run（候選 #30／#38／#44、跨段候補 #87／#88、#90／#92、#94／#96、#106／#108、持有過 1529／2364 的 #54／#58／#62）用日誌參數原樣重算、不寫 `portfolio_runs`（同 `--attach-series` 慣例）：八項指標 112 格 111 格相同（#38 rel_mdd 0.01 pp 捨入，`iter84-mdd38`）、持股名單 9,639 筆全同；只驗這 14 列。結論：資料更新對月調倉沒有影響，候選不換、N 108、保留期未開。事前登記 `AI/experiments/iter84_hypothesis.md`、結果檔 `UnifiedModel/results/portfolio_iter84_data_refresh.md`、紀錄 `AI/Doc/Iterations/Iteration-84.md`。審查見「已完成」。
（以下為 83）
Iteration 83（已提交 d1835fa）：使用者「候選不換，都先列出。然後先補更多家的股票資料」→ 追蹤股清單 `stock_info.is_tracking` 26 → 68 檔（0050 成分股 50 檔裡新增 42 家，MoneyDJ 持股 2026-09-30、代碼對 `market_universe` 逐檔查）：FinMind 回補行情 233,107／籌碼 142,685／外資持股 208,953 列（126 次呼叫、失敗 0、未觸額度）；對照全市場表發現 FinMind 的「權」列參考價＝前收（2890 2026-10-07 45.40／45.40，交易所 45.40／44.97）→ 事件表改用交易所檔重寫（2018 起 13,469＋217 筆；2000～2017 13,376＋179 筆）、`_refresh_adj_close` 不再打 FinMind；新檔 `tracked_sync.py` 每日 18:43 從三張全市場表補 FinMind 漏掉的列（兩來源 2018 起逐列對照：收盤、法人、持股 100% 相同、adj_close 100%）。不碰回測：N 108、候選不換、保留期未開。紀錄 `AI/Doc/Iterations/Iteration-83.md`。MOPS 重大訊息 42 檔 2023-09 起回補完成（08:16～10:39，16,138 則、user_news +15,681、失敗 0）。減資 factor 上限 5 → 20（2408 2014-09 減資九成是真的事件）。
（以下為 82）
Iteration 82（已提交 05d3cc0）：第十代籌碼結構面五條（`AI/experiments/iter82_hypothesis.md` 03:27 登記；`momsx` 跑前依列改分位，附錄 05:18）：`fhold` #103 dev +6.01%／0.644（登記指標低於候選、共同窗口 2018-11-12 起 +10.86%／1.550 高於候選）、`momlt` #104 +1.86%／0.196、`momsx` #105 +6.42%／0.544、`win3+mom+nsir` #106 **+9.77%／0.852** → valid #108 **+13.97%／1.062**（候選 #38 +15.71%／1.085）、`ndmargin` #107 −1.85%。N 102 → 108；候選不換；保留期未開。結果檔 `UnifiedModel/results/portfolio_iter82_chips.md`、紀錄 `AI/Doc/Iterations/Iteration-82.md`。審查見「已完成」。
（以下為 81）
Iteration 81（已提交 05d3cc0；MoneyScheduler 已於 2026-10-18 08:10 重啟，兩個排程已掛上）：使用者「繼續上網找論文或是任何資料，實作交易策略或是月調倉方案，找更多種方案」→ 文獻第四批 12 篇（Papers.md 第十節 P65～P76：放空流量／借券 SIR、散戶融資反向、外資持股水準、低週轉率動能）＋兩張籌碼結構面全市場表（不算 N）：`market_margin_daily`（證交所 MI_MARGN＋TWT93U、櫃買 margin/balance＋margin/sbl：融資融券＋借券賣出，統一存股、融券餘額兩表對位檢查）、`market_foreign_holding_daily`（證交所 MI_QFIIS、櫃買 insti/qfii：發行股數、外資持股、比率）；migration 030／031 已用 `lib/migrate.js` 套用、`margin_data.py`／`holding_data.py`、18:39／18:41 排程、tests +4、真實檔煙霧五天過。回補完成（2026-10-18 01:13 兩條同時起跑，外資持股 03:24、融資融券 05:16 完，各 2,138 個交易日、失敗 0；上櫃轉上市日的重複列改留櫃買列）。N 102、候選不換。審查見「已完成」。
（以下為 80）
Iteration 80（已提交 0ff11b4）：使用者「做」→ 第九代價值（估值表）：`dy` 單獨 #99 dev +4.12%／0.542（共同窗口 2018-11-12 起 +3.63%／0.622、2019 起 +2.34% 未過門檻；上櫃持股 2.8／20 含殖利率前視）、落後 −7.2% 開發期最小、追蹤誤差 7.6%、持股與候選交集中位數 0／20、ρ(mom, dy) −0.37，但年化主動只有候選一半；`win3+mom+dy` #101 +4.86%／0.431（風險降、報酬少 3.8 pp）；`ep` 單獨 #100 −3.33%／−0.401 反向、相加 #102 +0.29%。四條都沒兩項超過 #30，valid 不跑、價值家族關閉。點時性檢查（`val-pit-check-80`）：櫃買檔殖利率年初就印當年春天才決議的股利——`dy` 對上櫃股在 1～3 月為主、部分到 5 月有前視，#99／#101 是上界、關閉的結論不變；本益比兩市都點時。N 102、候選不換、保留期未開。審查見「已完成」。
（以下為前一個）
Iteration 79（已提交 49be73b、已 push；meeting_front_end 已提交 5065478、已 push；MoneyCrawlerApi 與 MoneyApi 已於 2026-10-17 重啟，端點實測 200；progress.md／README 本身因混有 78 的內容待 78 一起提交）：使用者「建立不同交易策略並進行測試」→ 十種交易策略範本搬到後端 `trading_presets.py` 成單一來源（六個舊模板＋買進持有／定期定額／季線趨勢／動能突破，金額是資金比例），`GET /trading/sim/presets`、`POST /trading/sim/presets/compare`、Node `/sim/presets`／`/sim/compare`，前端範本改從後端抓＋「比較全部策略」表；tests 5 項用 V 形合成行情驗每種照定義動作；真實行情四檔 2018-01～2024-09 的比較表在 `UnifiedModel/results/trading_presets_iter79.md`（一直在場的三種在三檔贏 0050、純擇時的五種四檔全輸、季線趨勢與定投在均線下只在 2603 贏）。交易模擬那條線、不寫 portfolio_runs、N 不動。**另一個 session 預告的估值訊號那輪請用 Iteration 80。**
（以下為 78）
Iteration 78（已提交 0ff11b4）：使用者「現在繼續找不同種月調倉（打敗大盤），多看論文或是網路文章整理資料」→ 文獻第三批 14 篇（Papers.md 第九節 P51～P64）＋第八代兩條（波動處理的動能）：`win3+vmom`（動能 ÷ 同窗口波動）#97 dev +7.92%／0.627、`win3+momx`（去掉全市場波動最高十分位）#98 dev +6.94%／0.578——都過門檻但開發期低於候選 #30（+8.64%／0.67），valid 不跑、家族關閉；`vmom` 與 `mom` ρ 0.98（持股交集 17／20）、`momx` 的落後與追蹤誤差較小但 2020 年少 12.4 pp。資料前置（不算 N）：全市場估值表 `market_valuation_daily`（證交所 BWIBBU_d＋櫃買 peQryDate：本益比／殖利率／淨值比；migration 029 已用 `lib/migrate.js` 套用、`valuation_data.py`、18:37 排程、tests +4、真實檔煙霧五天過），**2018 起回補完成**（20:26～22:26，2,138 個交易日、3,804,828 列、失敗 0；`--check`：缺交易日 0、缺股票日 0.24%、本益比有值 77.2%、殖利率 > 50 的列 517 待看；`val-check-78`）。N 98、候選不換、保留期未開。審查見「已完成」。
（以下為 77）
Iteration 77（已提交 63aae25、已 push；meeting_front_end 已提交 da8c14c、已 push）：使用者「點擊展開時，也要顯示折線圖顯式對比」→ `BeatMarketList` 展開時再抓 `/portfolio/runs/:id?step=3`，用 `NavRangeChart` 畫組合／0050／大盤三條線（有 `has_series` 才抓；74 列裡 43 列有曲線、31 列早期只存指標顯示說明）；純前端、不用重啟；vite-build-77／mfe-build-77／mfe-eslint-77 過。審查見「已完成」。
（以下為 76）
Iteration 76（已提交 bb9d59a，未 push；meeting_front_end 已提交 2ad71ce，未 push）：使用者「打敗大盤：目前候選對門檻，有贏過大盤的，都列在頂端，點擊後再展開購買的股票細節」→ 月調倉頁最上面新卡「贏過大盤的回測」（年化主動 > 0 且非作廢、依主動報酬排序、標三項門檻過幾項、段別篩選），點一列展開那次回測每個訊號日的持股（新端點 `GET /portfolio/runs/{id}/positions`：全部調倉＋名稱＋最常買到）。純讀取、N 不動（96）。pytest 263、jest 191、vite／mfe build 過。**要重啟 MoneyCrawlerApi 與 MoneyApi**；meeting_front_end 三檔已同步並提交 2ad71ce。審查見「已完成」。
（以下為 75）
Iteration 75（已提交 c8492fb、已 push；meeting_front_end 三檔已同步、mfe-build-75 過，該 repo 已提交 dfb7b48 並 push；MoneyCrawlerApi 與 MoneyApi 已於 2026-10-16 重啟）：使用者「交易模擬 可以選測試的資料」→ 資料來源抽成物件（`synthetic_market.DbSource`／`SyntheticSource(seed)`），兩個模擬器多 `source`，API／Node 多 `source`／`seed`，前端「資料」下拉＋種子＋橘色警示；合成行情在後端記憶體現場產生、不讀不寫任何庫；預設仍真實行情。pytest 261、jest 190、vite build 過。**要重啟 MoneyCrawlerApi 與 MoneyApi**。審查見「已完成」。
（以下為 74）
Iteration 74（已提交）：使用者「找方案在交易模擬建立大量假資料進行測試」→「方案 A，測試資料不要汙染到真實股票資料」：合成行情（幾何隨機漫步）＋ `monkeypatch` 攔下 `market_days`／`load_prices`／`load_bench` 與 `get_conn`，8 年 × 61 檔上 5 種子 × 50 條隨機規則、5 種子 × 200 筆隨機指令的帳務不變量全過、不連任何資料庫；`test_trading_fuzz.py` 15 項、pytest 256、jest-unit 44；模擬器本體未動、N 不動、不用重啟。審查見「已完成」。
（以下為 73）
Iteration 73（已提交 4b8c8a8）：第七代——法人買賣超：`win3+mom+fflow`（外資 21 日淨買超占成交金額比例相加）#94 dev **+10.33%／0.875 兩項超過候選**、#96 valid +14.34%／1.054 低於候選 1.4 pp、IR 亦低；`fflow` 與 `mom` ρ 0.06、持股交集 11／20，是獨立訊號；外資單獨 #93 −0.03%（追蹤誤差 7.3%，持股名次中位數 153、不是權值股）、投信相加 #95 沒過門檻。N 96、候選不換。Iteration 71 回補完成（2,137 天、332 萬列、失敗 0、候選池覆蓋 99.9%）。
（以下為 72）
Iteration 72（已提交 4b8c8a8）：使用者「月調倉方案繼續找」→ 第六代（產業與季節性）：`win3+relmom`（扣掉產業的個股動能，P48）#90 dev **+10.12%／0.785 兩項超過候選**、#92 valid +15.19%／1.07 與候選持平（少 0.5 pp）、落後較小——目前最接近候選的一組，但與 `mom` ρ 0.95；產業動能相加 #89 低於候選；同月季節性 #91 沒過門檻（只有 1～3 個 lag）。N 92、候選不換。
（以下為 71）
Iteration 71（已提交 4b8c8a8，回補完成）：使用者「先補」→ 全市場三大法人買賣超資料路線（P18 前置，不算 N）：交易所官方檔（證交所 T86＋櫃買 insti/dailyTrade）、解析器（證交所 19 欄、櫃買 16／24 欄，逐列驗合計）、migration 028 `market_institutional_daily`、`institutional_data.py`、排程 18:35、tests +4、真實檔煙霧五天過。**回補進行中**（22:06 起，約 6 秒／交易日，2,140 天；MoneyApi 由本 session 重啟後套上 028）。
（以下為 70）
Iteration 70（已提交 4b8c8a8）：第五代——隔夜短期持續 `win3+mom+ovn1m` #86 dev +6.31%／IR 0.493 沒過門檻（隔夜／日內家族關閉）；Amihud 非流動性 `win3+mom+illiq` #87 dev **+11.09%／0.847 超過候選**（19 次文獻試驗裡第一條有效實作；錯版 #72 不計），valid #88 +14.14%／0.98 過年化主動與 IR 門檻（DSR 0.488 未達 0.95）但低於候選 #38（+15.71%／1.085）；候選不換，換不換由使用者決定；N 88。
（以下為 69）
Iteration 69（已提交 4b8c8a8）：使用者再要「搜論文、記錄、以論文為基礎優化、不斷迭代、每代記錄，至少 10 篇」。文獻第二批 22 篇（Papers.md P25～P46、第八節）＋第四代三條：資訊連續性 #83 +6.49%／0.515、日內動能 #84 +7.00%／0.628、中期動能 12-7 #85 +3.07%／0.253，都低於候選、valid 不跑；valid 規則收緊為「過門檻且超過 #30」；N 85。
（以下為 68）
Iteration 68（已提交 4b8c8a8）：第三代——以營收驚喜為條件的動能 `win3+momrev`（Novy-Marx 2015，P11）#82 dev +4.69%／IR 0.38，低於候選、沒過門檻，家族關閉；N 82。順帶找到 `win3` 在農曆年落 2 月上旬時會整季失效（2019-02～04 候選也沒調倉）。
（以下為 67）
Iteration 67（已提交 4b8c8a8）：第二代——三年期市場狀態閘門（P6 第二次抽樣）#81 與候選 #30 完全相同（2018–2024 零次 DOWN），家族關閉；N 81。
（以下為 66，已提交 4b8c8a8）
Iteration 66（已提交 4b8c8a8）：使用者要「搜論文、記錄、以論文為基礎優化、不斷迭代、每代記錄」。第一代：`AI/Doc/Papers.md`（24 條，P1～P24）＋三條文獻假設各跑一次（殘差動能、營收 YoY 動能、市場狀態閘門），**都沒超過候選**；N 69 → 80；候選不換、保留期未開。
（以下為 65，已提交 dec7174）
Iteration 65：月調倉頁與正式策略頁的淨值曲線加含息大盤（TAIEX_TR）第三條線；純顯示，N 不動
（以下為 64，已提交 bb791d6）
Iteration 64：候選 #44 升為正式策略（新頁、live #68 每日 18:50 重算）；保留期重跑 #69——**年化主動 −6.1%、輸給 0050**。引擎已啟動（紙上、停損 0、限價 ±2%）

## 產出
- （84）AI/experiments/iter84_hypothesis.md（登記 14:38＋附錄）、iter84_inputs.py、iter84_recompute.py、iter84_mdd38.py、iter84_calendar.py；UnifiedModel/results/portfolio_iter84_data_refresh.md；Crawler/logs/iter84_recompute.log（不進 git）；AI/Doc/Iterations/Iteration-84.md、README
- （83）AI/experiments/iter83_rebuild_adj.py、iter83_rebuild_adj_evidence.py（adj_close 重建）；Crawler/tracked_sync.py、tests/test_tracked_sync.py（1 項，db）、scheduler.py（`job_tracked_sync` 18:43、`_refresh_adj_close` 只重建）、scrapers/exchange_daily.py（減資檔去重）、rebuild_adj_close.py（減資上限 20）、tests/test_scheduler.py、test_market_data.py（+1）、test_upsert.py（+1）、tests/helpers/db_setup.py；AI/experiments/iter83_compare.py、iter83_freshness.py、iter83_restore_events.py、iter83_evidence.py；Crawler/logs/backfill_prices_iter83.log、backfill_dividend_iter83.log、rebuild_adj_iter83.log、restore_events_iter83.log、backfill_mops_iter83.log；AI/Doc/DataSources.md、DB.md（§2.1）、README.md；AI/Doc/Iterations/Iteration-83.md
- （82）AI/experiments/iter82_hypothesis.md（登記 03:27＋附錄 05:18）、iter82_grid.json、iter82_results.py、iter82_sir_rows.py、iter82_signal_hunks.txt、iter82_dev.log、iter82_valid.log；UnifiedModel/results/portfolio_iter82_chips.md；portfolio_runs #103～#108；Crawler/portfolio_signal.py（`MOMSX_SIR_CUT`、`signal_momsx`）、tests/test_portfolio.py；AI/Doc/Iterations/Iteration-82.md、README、Papers.md（第五節第十代、第六節、P62／P65～P68／P70～P72）
- （81）Crawler/scrapers/exchange_daily.py（融資融券／借券／外資持股 fetch／parse、`merge_margin_sbl`、`drop_transfer_duplicates`）、margin_data.py（新）、holding_data.py（新）、scheduler.py（18:39、18:41）、tests/test_margin_holding.py（新，4 項）、tests/test_scheduler.py；Server/migrations/030_market_margin.sql、031_market_foreign_holding.sql、tests/db/migrations.test.js（31）；AI/Doc/Papers.md（第十節 P65～P76）、DataSources.md（兩列）、Iterations/Iteration-81.md、README；回補日誌 AI/experiments/iter81_margin_backfill.log、iter81_holding_backfill.log
- （80）AI/experiments/iter80_hypothesis.md、iter80_grid.json、iter80_results.py、iter80_dev.log、iter80_signal_hunks.txt、iter80_data_queries.py、iter80_pit_check.py；AI/Doc/DataSources.md（估值列）、Server/migrations/029_market_valuation.sql（檔頭註解）、Crawler/valuation_data.py（docstring）；UnifiedModel/results/portfolio_iter80_value.md；portfolio_runs #99～#102；Crawler/portfolio_signal.py（`needs_valuation`、`load_valuation`、`_val_on`、`signal_dy`、`signal_ep`、`DY_MAX`、`VAL_MAX_LAG`）、portfolio_backtest.py（`run` 掛 `mkt.val`）、tests/test_portfolio.py（+1，36 項）；AI/Doc/Papers.md（第五節第九代、第六節、P58～P60）、Iterations/Iteration-80.md、README
- （79）Crawler/trading_presets.py、tests/test_trading_presets.py（5 項）、api.py（兩個端點）；Server/routes/sim.js、tests/helpers/fastapi-mock.js、tests/http/sim.test.js（+2）；Screen/src/components/RuleBuilder.jsx、pages/TradingSim.jsx、services/api.js；meeting_front_end 同三檔；AI/experiments/iter79_presets.py → UnifiedModel/results/trading_presets_iter79.md；AI/Doc/Iterations/Iteration-79.md、README
- （78）AI/experiments/iter78_hypothesis.md、iter78_grid.json、iter78_results.py、iter78_dev.log、iter78_signal_hunks.txt、iter78_valuation_backfill.log；UnifiedModel/results/portfolio_iter78_volmom.md；portfolio_runs #97～#98；Crawler/portfolio_signal.py（`MOMX_VOL_CUT`、`_mom_and_vol`、`signal_vmom`、`signal_momx`）、scrapers/exchange_daily.py（估值 fetch／parse／`_check_valuation`）、valuation_data.py（新）、scheduler.py（`job_valuation_daily` 18:37）、tests/test_portfolio.py（+1，35 項）、tests/test_valuation.py（新，3 項）、tests/test_scheduler.py；Server/migrations/029_market_valuation.sql、tests/db/migrations.test.js（29）；AI/Doc/Papers.md（第九節 P51～P64、第五節第八代、第六節）、DataSources.md、Iterations/Iteration-78.md、README
- （77）Screen/src/components/BeatMarketList.jsx（Chart）、meeting_front_end 同檔；AI/experiments/iter77_evidence.py；AI/Doc/Iterations/Iteration-77.md、README
- （76）Crawler/portfolio_api.py（`run_positions`）、api.py（`/portfolio/runs/{id}/positions`）、tests/test_portfolio_positions.py（2 項）；Server/routes/portfolio.js、tests/helpers/fastapi-mock.js、tests/http/portfolio.test.js（+1）；Screen/src/components/BeatMarketList.jsx（新）、pages/PortfolioLab.jsx、services/api.js；meeting_front_end 同三檔；AI/experiments/iter76_evidence.py；AI/Doc/Iterations/Iteration-76.md、README
- （75）Crawler/synthetic_market.py、tests/test_synthetic_market.py（5 項）；trading_sim.py／trading_strategy.py（`source` 參數）、api.py（`source`／`seed`、`_sim_source`）；Server/routes/sim.js（`sourceFields`）、tests/http/sim.test.js（+5）、tests/helpers/fastapi-mock.js；Screen/src/pages/TradingSim.jsx、components/RuleBuilder.jsx、components/SourceBanner.jsx（新）；AI/Doc/Iterations/Iteration-75.md、README
- （74）Crawler/tests/helpers/fake_market.py（`make_market`、`patch`、`random_rules`、`random_instructions`、`check_invariants`）、tests/test_trading_fuzz.py（15 項，無 db marker）；AI/experiments/iter74_fuzz_stats.py → UnifiedModel/results/trading_fuzz_iter74.md；AI/Doc/Iterations/Iteration-74.md、README
- （73）AI/experiments/iter73_hypothesis.md、iter73_grid.json、iter73_results.py、iter73_dev.log、iter73_valid.log；UnifiedModel/results/portfolio_iter73_insti.md；portfolio_runs #93～#96；Crawler/portfolio_signal.py（`needs_institutional`、`load_institutional`、`_flow`、`signal_fflow`、`signal_tflow`）、portfolio_backtest.py（`run` 掛 `mkt.insti`）、tests/test_portfolio.py（+1，34 項）、tests/test_scheduler.py（加 18:35 工作）；AI/Doc/Iterations/Iteration-73.md、Iteration-71.md（回補完成）、README、Papers.md（P18／P44、第五節第七代、第六節）；market_institutional_daily 3,321,740 列
- （72）AI/experiments/iter72_hypothesis.md、iter72_grid.json、iter72_results.py、iter72_dev.log、iter72_valid.log；UnifiedModel/results/portfolio_iter72_industry.md；portfolio_runs #89～#92；Crawler/portfolio_signal.py（`load_universe_meta` 多 industry_type／market_type、`signal_indmom`、`signal_relmom`、`signal_seas`）、tests（+2，33 項）；AI/Doc/Iterations/Iteration-72.md、README、Papers.md（P47～P50、P31、第五節第六代）
- （71）Server/migrations/028_market_institutional.sql；Crawler/institutional_data.py、scrapers/exchange_daily.py（三大法人 fetch／parse／`ExchangeFormatError`）、scheduler.py（`job_institutional_daily` 18:35）、tests/test_institutional.py（+4）；Server/tests/db/migrations.test.js（28）；AI/Doc/DataSources.md、Papers.md（P18）、Iterations/Iteration-71.md、README
- （70）AI/experiments/iter70_hypothesis.md、iter70_grid.json、iter70_results.py、iter70_dev.log、iter70_valid.log；UnifiedModel/results/portfolio_iter70_illiq.md；portfolio_runs #86～#88；Crawler/portfolio_signal.py（`Market.ar_over`、`signal_ovn1m`、`signal_illiq`）、tests/test_portfolio.py（+2，31 項）；AI/Doc/Iterations/Iteration-70.md、README、Papers.md（P27／P28／P35 狀態、第五節第五代、第六節）
- （69）AI/experiments/iter69_hypothesis.md、iter69_grid.json、iter69_results.py、iter69_dev.log；UnifiedModel/results/portfolio_iter69_lit2.md；portfolio_runs #83～#85；Crawler/portfolio_signal.py（`Market.ar_intra`、`_mom_window`、`signal_cont`、`signal_imom`、`signal_mom127`）、tests（+3）；AI/Doc/Iterations/Iteration-69.md、README、Papers.md（第八節 P25～P46、第五節第四代）
（以下為 68）
- AI/experiments/iter68_hypothesis.md、iter68_grid.json、iter68_results.py、iter68_dev.log；UnifiedModel/results/portfolio_iter68_momrev.md；portfolio_runs #82
- Crawler/portfolio_signal.py（`signal_momrev`）、tests/test_portfolio.py（+1，26 項）；AI/Doc/Iterations/Iteration-68.md、README、Papers.md（P11、第五節第三代、第六節）
（以下為 67）
- AI/experiments/iter67_hypothesis.md（事前登記）、iter67_grid.json、iter67_results.py、iter67_dev.log；UnifiedModel/results/portfolio_iter67_gate3y.md；portfolio_runs #81
- Crawler/portfolio_signal.py（`STATE_GATES`、`load_bench_history`、`needs_bench_history`、`market_state_up` 用 `bench_hist`）、portfolio_backtest.py（`run` 掛 bench_hist）、tests/test_portfolio.py（+1，25 項）
- AI/Doc/Iterations/Iteration-67.md、AI/Doc/README.md、AI/Doc/Papers.md（P6／P7、第五節第二代、第六節）
（以下為 66）
- AI/Doc/Papers.md（論文紀錄：五節＋下一輪可登記的假設）、AI/Doc/README.md（Papers 列與 Iteration-66 列）
- Crawler/portfolio_signal.py（`signal_resmom` 過原點 β、`signal_rev_yoy3`、`market_state_up`、`STATE_GATE='~up'`、`_gated_parts`）、tests/test_portfolio.py（+2，24 項）
- AI/experiments/iter66_grid.json、iter66_valid.json、iter66_grid2.json、iter66_results.py、iter66_*.log
- UnifiedModel/results/portfolio_iter66_papers.md（腳本產生）；portfolio_runs #70～#80
- AI/Doc/Iterations/Iteration-66.md
（以下為 65，已提交 dec7174）
- Crawler/portfolio_api.py（`_index_series`、series 每點 `idx`）、tests/test_portfolio.py（+1）、nav_index_evidence.py
- Screen 與 meeting_front_end 的 components/NavRangeChart.jsx、pages/OfficialStrategy.jsx、pages/PortfolioLab.jsx；AI/Doc/Iterations/Iteration-65.md
（以下為 64，已提交）
- Crawler/portfolio_official.py、tests/test_portfolio_official.py、fix_0050_split.py、holdout_preview_evidence.py、migration 027、scheduler 18:50、api.py `/portfolio/official*`、Node 代理與測試
- Screen/src/pages/OfficialStrategy.jsx、components/NavRangeChart.jsx、App／Sidebar；meeting_front_end 同步
- AI/Doc/Iterations/Iteration-64.md、AI/Doc/README.md、Server/README.md

## 已完成
- 資料更新重算（84）：iter84-prereg-sha256／mtime（14:38:09，重算前）；iter84-inputs 過（0050 淨值 1,635 點最大相對差 0.0005%、全市場 2018 起 adj NULL 0／≤0 0、N 108）；iter84-recompute-smoke 過（#38 0.2 分）；iter84-recompute 過（14 列 3.0 分：指標 111／112 格相同、持股名單 9,639 筆全同、N 108 → 108）；iter84-mdd38 過（#38 rel_mdd 未捨入 −0.166451 對 −0.166448）。沒跑：pytest、jest、vite build（沒改程式）。
- 審查（84）：strategy-critic-84 PASS（無前視、成交時點同、驗證期未挑、save=False 沒寫表、不計 N 同意；兩條措辭已改）；evidence-reviewer-84 三輪 25/6/2 FAIL → 16/2/1 FAIL → 8/0/0 PASS（9,261→9,639、Iteration 71→48、「本來就不存在」改寫、rel_mdd 歸因 iter84-mdd38、12-31 查詢 iter84-calendar）。
- adj_close 重建（83，2026-10-18 14:23）：adj-rebuild-dry-83 過（只讀試算：全市場 2,621 檔、有事件 2,144 檔，會變動的只有 1529 217 列、2364 908 列、3043 1,206 列）；adj-rebuild-83 過（`market_data.rebuild_adj()` 更新 2,331 列；1529 2018-12-12 adj 1.3518 → 12.2864、2364 2021-09-29 1.2635 → 9.9790）；adj-rebuild-evidence-83 過（三檔只在 #54／#58／#62 持股過、都在除權日之後；8913 2018-06-04 208 → 18.11 被下限略過；N 108）
- 審查（83）：evidence-reviewer-83 三輪 46/5/21 FAIL → 72/3/10 FAIL → 75/0/10 PASS（第一輪：Target.md 20 家、scheduler.log 的 upper limit 全是 pytest 寫的、adj NULL 列數、新鮮度只查 5 檔→改傳 68 檔、2 分 53 秒；第二輪：2603 長榮在 _GENERIC、月調倉 0050 基準、23 passed；未解 10 條是沒另存輸出或網頁／git 來源，紀錄裡已標明）
- 追蹤股擴大（83）：mops-backfill-83 過（42 檔 16,138 則、user_news +15,681、142.2 分、失敗 0）；finmind-backfill-83 過（42 檔 126 次、08:18～08:21、失敗 0）；sync_stock_info 68 檔（7769、6446 市場別改成 `market_universe` 的 twse）；news_alias +41；backfill_dividend 914 筆、rebuild 233,023 列 → 發現 FinMind「權」列不給參考價 → iter83_restore_events 2018 起除權息 13,469／減資 217／1,929 檔，重建 68 檔 403,572 列；tracked-sync-fill-83 過（行情 +1,838 只有 2327、籌碼 +17,938、外資持股 +9）；tracked-sync-compare-83 過（2018 起 136,507 股票日：收盤／開高低 100%、成交量 97.4%（不同的 3,607 列全是上櫃期間：5483、6446 轉上市前，櫃買檔不含零股盤後）、adj_close 差 ≤ 0.05% 100%；法人 136,550 列 100%；持股 136,676 列 100%）；freshness-83 過（明確傳入 68 檔、落後 0）；iter83-evidence 過（審查補證據：FinMind「權」列 2890／2313 對交易所、2018 以前事件 13,396／179、2014～2016 減資 79、adj NULL 198／198 都是 close ≤ 0、6446 3.00%、全市場 factor ≥ 5 三筆）；events-restore-83 過（2000～2017 除權息 13,376／減資 100＋79；TWTAUU 三年檔同檔同日重複列 → parser 去重；2408 減資九成 factor 9.99 改採用、減資上限 5 → 20）；pytest-tracked-sync-83 23 過；pytest-events-83 39 過；pytest-83 282 過。沒跑：jest、vite build（Node 與前端沒改）。
- 審查（82）：strategy-critic-82 PASS（方法乾淨；七條措辭——momlt「大型股」無數字、相加對排除基底不同、fhold 後續假設標事後、ndmargin 補共同窗口、sir 中位 265、試驗次數 39、補 backtest.py hunk——都已改）；evidence-reviewer-82 第一輪 49/5/1 FAIL（秒數、節數、中位、次數、單檔名）→ 第二輪 64/2/1 FAIL（progress.md 八節、階段 7 回補中已過期）→ 第三輪 13/0/0 PASS（checks.json 同名覆蓋，記最終結果）。
- 第十代第二批與驗證期（82）：margin-check-81（1,959 檔、3,505,421 列、2,138 日、借券欄 100%、缺股票日 7.87%）；sir-rows-82（池內 SIR＝0 只 1.0%）→ `momsx` 跑前改分位（iter82-prereg-mtime-amended 05:18:52、-sha256-amended）；iter82-dev-margin：#105 `momsx` +6.42%／0.544、#106 `win3+mom+nsir` +9.77%／0.852／TE 11.5%／落後 −11.5%、#107 `ndmargin` −1.85%／−0.151；iter82-valid：#108 +13.97%／1.062／TE 13.2%／落後 −13.0%／月勝率 62%（#38 +15.71%／1.085／14.5%／−16.7%）；iter82-results（七節，含共同窗口：#103 2018-11-12 起 +10.86%／1.550、#106 +10.66%／1.333、#30 +9.27%／0.926）；iter82-git-hunks（三個 hunk 都在 697 行後）；runs-count-82（108／108）；pytest-portfolio-82b 37 過、pytest-82b 279 過。
- 第十代第一批（82）：#103 `fhold` dev +6.01%／0.644／TE 9.3%／落後 −15.1%／換手 1.6／46 次調倉（2018-03-12 起）；#104 `momlt` +1.86%／0.196／TE 9.4%／落後 −11.5%（候選 #30 +8.64%／0.67／12.9%；`mom` #70 +5.96%／0.44／13.6%）。#103 過兩項門檻但年化主動與 IR 都低於 #30（兩項都略高於 #70），依登記規則不跑 valid；#104 兩項都低於 #70。登記 `iter82-prereg-mtime`（03:27:30）／`iter82-prereg-sha256` 記在 `iter82-dev-holding`（03:27:31 起）之前；N 102 → 104（`iter82_dev.log`）。
- 外資持股回補完（81）：03:21 跑完 2,136 天 ＋ 2 天失敗（轉上市日 1795／8908 兩市重複列）→ 加 `drop_transfer_duplicates` 後 03:24 補回；holding-check-81：2,090 檔、3,816,161 列、2,138 個交易日、缺交易日 0、缺股票日 0.20%、比率異常 0；holding-pit-81：發行股數 9,147 次切換散在 2,024 個交易日、最多一天 49 檔、5 月最多，長榮 2022-09-20 減資當天切換——點時；pytest-margin-holding-81b 18 過。
- 審查（81）：evidence-reviewer-81 三輪 37/4/6 → 11/2/0 → 5/2/0 FAIL——第一輪四條字句（低價股理由、「待資料」列數、列數範圍、略過列數）、第二輪「四條假設」與三處一致、第三輪移動目標數字與 P62 狀態欄，都在輪後改掉；補記 sched-proc-81、runs-count-81（checks.json 2026-10-18）
- 籌碼結構面資料路線（81）：pytest-margin-holding-81 24 過、pytest-81 277 過、jest-migrations-81 4 過（31 個 migration）、migrate-030-031（`Applied: 030`、`031`）、margin-holding-smoke-81 五個日期（2018-01-03、2019-07-01、2021-06-01、2024-01-02、2026-10-16）融資融券上市 1,001～1,301／上櫃 635～918 列、借券欄 100%、外資持股上市 1,033～1,364／上櫃 746～894 列、休市回 0（checks.json 2026-10-18）；回補進行中；N 仍 102
- 審查（80）：strategy-critic-80 三輪 FAIL → FAIL → FAIL（第一輪措辭與「TE 歷來最小」、第二輪要上櫃本益比全市場檢查／上櫃曝險／共同窗口、第三輪「2018-01-02 零檔」是空清單——都在輪後補了 val-pit-check-80b／80c 與結果檔第七八節）；evidence-reviewer-80 三輪 37/2/6 → 25/5/7 → 19/7/2 FAIL（第三輪：共同窗口 2018-11-12 起仍過門檻、只有 2019 起未過，標題與各處已改）；兩者的決定（價值家族關閉、候選不換）不受影響（checks.json 2026-10-17）
- 第九代（80）：#99 `dy` +4.12%／0.542／TE 7.6%／落後 −7.2%／換手 2.63；#100 `ep` −3.33%／−0.401／−21.8%；#101 `win3+mom+dy` +4.86%／0.431／11.3%；#102 `win3+mom+ep` +0.29%／0.027（候選 #30 +8.64%／0.67、`mom` #70 +5.96%／0.44）；逐年 #99 2018（3 月起）+12.4%、2019 +5.1%、2020 +2.3%、2021 +0.6%；ρ(mom, dy) −0.37、ρ(mom, ep) −0.18；池內有 ep 的 252／270；前 20 重疊 7／8、持股交集單獨 0／20、相加 8／20；#99 持股名次中位數 191；估值表對前 300 缺列 0.03%、沒本益比 8.5%；valid 不跑；pytest-portfolio-80 39（test_portfolio 36 ＋ test_valuation 3）、pytest-80 273、iter80-dev、iter80-results、iter80-git-hunks 過（checks.json 2026-10-17）；N = 102
- 策略範本（79）：pytest-79 272 過、jest-79 193 過（17 套）、presets-run-79 過、vite-build-79、mfe-build-79、mfe-eslint-79 過（checks.json 2026-10-17）；真實行情 40 格裡 11 格贏過 0050（+182.7%），均線進出／雙重確認／動能突破／RSI 反轉／停損停利四檔都沒贏；evidence-reviewer-79 第一輪 46/2/4 FAIL → 修六處（測試加 RSI 第 3 天／pnl<0／穿線日 RSI 41.7 斷言、腳本印合成 0050、措辭）後第二輪 55/0/1 PASS
- 審查（78）：strategy-critic-78 PASS（七條意見全部處理：補結果檔 ρ(mom, vol) 與第六節、三處讀法改寫、標題加開發期、登記檔 sha256）；evidence-reviewer-78 三輪 56/4/5 → 26/1/2 → 20/1/5 仍 FAIL——第三輪唯一 incorrect（「前一列」措辭）已改，unresolved 是 checks.json 不記 session 所以 -78 名稱的 jest／vite／mfe 紀錄與 pytest-78 裡交易模擬測試的歸屬只能推斷、evidence-reviewer-78 在輪後才記、程序啟動時間已補記 sched-proc-78（checks.json 2026-10-17）
- 第八代（78）：#97 `win3+vmom` dev +7.92%／0.627／TE 12.6%／落後 −15.7%；#98 `win3+momx` +6.94%／0.578／TE 12.0%／−12.8%（候選 #30 +8.64%／0.67／12.9%／−14.7%；對照 #51 `win3+mom+lowvol` +2.47%）；逐年 #98 2020 +5.7% 對候選 +18.1%、2021 +9.1% 對 +1.6%；ρ(mom, vmom) 0.98、前 20 重疊 18／12、持股交集 17／20 與 13／20、池內被 momx 排除 15%；valid 不跑；pytest-portfolio-78 51 過、pytest-78 272 過、iter78-dev、iter78-results、iter78-git-hunks（checks.json 2026-10-17）；N = 98
- 估值資料路線（78）：migrate-029 套用（`[Migration] Applied: 029_market_valuation.sql`）；val-parse-smoke-78 五個日期（2018-01-02、2019-07-01、2021-01-04、2024-01-02、2026-10-16）上市 906～1,082 列、上櫃 742～885 列、本益比有值 69～82%、殖利率與淨值比 100%、休市回 0；jest-migrations-78 4 過（29 個 migration 對新庫）；回補進行中
- 清單折線圖（77）：vite-build-77、mfe-build-77、mfe-eslint-77 過（checks.json 2026-10-17）；pytest／jest 沒跑（後端未動）；evidence-reviewer-77 第一輪 34/2/1 FAIL → 修三處後第二輪 4/0/0 PASS
- 贏過大盤清單（76）：pytest-76 263 過、jest-76 191 過（17 套）、vite-build-76 過、mfe-build-76 過（checks.json 2026-10-17）；positions-evidence-76 過（#44 68 次調倉／306 檔／177 KB／6.4 ms、清單 74 列）、mfe-eslint-76 過；evidence-reviewer-76 第一輪 32/1/9 FAIL → 修段別篩選描述、補 positions-evidence-76／mfe-eslint-76／portfoliolab-diff-76 後第二輪 19/0/1 PASS
- 測試資料來源（75）：pytest-75 261 過、jest-75 190 過（17 套）、vite-build-75 過（checks.json 2026-10-16）；evidence-reviewer-75 一輪 40/0/3 PASS（三條 unresolved 主 session 補查表 96 列、git diff、計時 11.3 ms 後關閉）
- 假資料測試（74）：pytest-74 256 過、jest-unit-74 44 過（checks.json 2026-10-16）；合成市場 61 檔 × 2,408 日、一字鎖 397 股票日；規則模擬 5 種子成交 19／34／382／176／367、每趟約 1 秒；指令模擬 5 種子成交 46／37／53／26／38、略過全是「現金不夠」「沒有持股可賣」、`trades + skipped == 200`；evidence-reviewer-74 兩輪 43/4/7 → 17/0/8 PASS（unresolved 是暫存區量測數字與過程敘述，已標待確認）
- 審查（71／73）：strategy-critic-73 PASS（九條已處理）；evidence-reviewer-71 三輪 29/8/4 → 36/1/3 → 12/0/1 PASS；evidence-reviewer-73 三輪 34/2/6 → 60/5/6 → 25/0/1 PASS（checks.json 2026-10-16）
- 第七代（73）：#93 `fflow` −0.03%／−0.004／TE 7.3%；#94 `win3+mom+fflow` +10.33%／0.875／TE 11.8%／落後 −11.5%；#96 valid +14.34%／1.054／13.6%／−15.4%／月勝率 69%（候選 #38 +15.71%／1.085／14.5%／−16.7%／66%）；#95 `win3+mom+tflow` +4.23%／0.346；ρ(mom, fflow) 0.06、持股交集 11／20；回補 2,137 天失敗 0（22:06～01:31）、2018-12-22 是補班日 582 列低於 --check 門檻不是缺、前 300 名缺 0.06%；pytest-portfolio-73 34 過、pytest 241 過（2026-10-16）；N = 96
- 審查（72）：strategy-critic-72 PASS（八條已處理）；evidence-reviewer-72 三輪 51/3/3 → 58/1/5 → 32/2/2，第三輪兩條行號／措辭已改，unresolved 交使用者（checks.json 2026-10-15）
- 第六代（72）：#89 `win3+mom+indmom` dev +7.89%／0.624；#90 `win3+relmom` dev +10.12%／0.785／TE 12.9%／落後 −14.1%；#92 valid +15.19%／1.07／TE 14.2%／−15.8%（候選 #38 +15.71%／1.085／14.5%／−16.7%）；#91 `win3+mom+seas` +0.37%／0.03；ρ(mom, relmom) 0.95、前 20 重疊 18；持股最大產業占比最大值 dev 60% → 45%、valid 40% → 35%；pytest-portfolio-72 33 過（2026-10-15）；N = 92
- 法人資料路線（71）：pytest-institutional-71 32 過；insti-parse-smoke-71 五個日期（2018-01-03、2019-07-01、2021-06-01、2024-01-02、2026-10-14）上市 907～1,347 列、上櫃 487～901 列、合計驗證全過、休市回 0；jest-migrations-71 4 過（2026-10-15）。N 仍 88
- 審查（69／70）：strategy-critic-69、-70 PASS；evidence-reviewer-69 三輪 48/2/3 → 49/1/2 → 13/1/2、-70 三輪 43/3/2 → 42/2/2 → 33/1/1，第三輪各剩一條字句已在輪後改掉，unresolved（使用者原話、跑網格前的 pytest-portfolio 被同名覆蓋）交回使用者（checks.json 2026-10-15）
- 第五代（70）：#86 `win3+mom+ovn1m` dev +6.31%／0.493；#87 `win3+mom+illiq` dev +11.09%／0.847／TE 13.1%／相對落後 −13.5%；#88 valid +14.14%／0.98／TE 14.4%／−16.1%／月勝率 69%（候選 #30 +8.64%／0.67、#38 +15.71%／1.085）；逐年 #87 2021 +9.2% 對候選 +1.6%，#88 2022／2023／2024 +13.7／+15.1／+3.9 對 +15.2／+18.8／+3.2；`illiq` 與流動性名次 ρ 中位數 0.56，前 20 持股流動性名次中位數 80 → 152（dev）、80 → 143（valid）；pytest-portfolio 31、pytest 234 過（2026-10-15）；N = 88
- 第四代（69）：#83 `win3+mom+cont` +6.49%／0.515、#84 `win3+imom` +7.00%／0.628（TE 11.2%、相對落後 −11.5%、月勝率 57%）、#85 `win3+mom127` +3.07%／0.253；ρ(mom, imom) 中位數 0.33、前 20 重疊 10；valid 都不跑；跑網格前 pytest-portfolio 29 過（2026-10-15，checks.json 的同名紀錄已被 70 的 31 過覆蓋）
- 第三代（68）：#82 `win3+momrev` dev +4.69%／0.38 對候選 +8.64%／0.67；候選池中位數 266 → 116；valid 不跑；pytest-portfolio 26、pytest 229 過（2026-10-15）。Iteration 67 審查：strategy-critic PASS；evidence-reviewer 三輪（41/1/2 → 10/3/0 → 7/0/0）PASS。Iteration 68 審查：strategy-critic PASS（七條意見已改）；evidence-reviewer 三輪（62/3/3 → 26/5/1 → 6/2/1）第三輪仍 FAIL，三條清單字句在第三輪後已改、附報告交回使用者
- 第二代（67）：#81 `win3+mom~up3` dev +8.64%／IR 0.67 = #30；三年期閘門 dev／valid 零次 DOWN（0050 三年報酬最低 +22.6% 於 2020-04-13、+22.9% 於 2024-03-11）；valid 不跑；pytest-portfolio 25、pytest 228 過（2026-10-15）
- Iteration 66 審查：strategy-critic 第一輪 FAIL → 第二輪 PASS；evidence-reviewer 第一輪 38/3/4、第二輪 25/4/1 → 第三輪 7/0/0 PASS（checks.json 2026-10-14／15）
- 文獻第一代（66）：N = 80。H1 `resmom` 單獨 dev +4.08%（`mom` #70 +5.96%），TE 11.9% 對 13.6%；H1b `win3+resmom` dev +7.49%／IR 0.61、valid +16.30%／1.177（候選 #30 +8.64%／0.67、#38 +15.71%／1.085）——修正版兩段過門檻、開發期低於候選，但驗證期被錯版 #76 先看過一次，#80 不算乾淨確認；H2 `rev_yoy3` dev −2.77%，`win3+mom+rev_yoy3` dev +8.58%／valid +13.80%；H3 `win3+mom~up` dev +5.17%／0.413（valid 不跑）。#71／#72／#76 是帶截距 OLS 的錯版（等於一個月殘差反轉），tag=void、notes 註明，留檔不刪。checks.json：pytest-portfolio 24 過、pytest 227 過（2026-10-14）
- 大盤線（65）：pytest 225、兩個 build、nav-index-evidence 都過（2026-10-12）；保留期 #69 組合 2.206／0050 2.491／大盤 2.272
- 階段 1～3（48～53）：候選 #44；階段 4 紙上交易（54）：2026-10-09 開戶 100 萬；階段 5 引擎（58／59）已提交；交易模擬（60～62）、區間曲線（63）已提交
- 回放結論（59）：照單全收 +346%（0050 +189%）；停損 15／25／35% 都輸；限價 ±2% 只差 0.5%／年

## 決策
- 2026-10-18（84）：「重新分析」做成**原樣重算已登記的 run、不計 N**（同 `attach_series` 慣例：同一組參數沒有新的選擇自由度），不跑新訊號、不開保留期；若審查者認為該計 N，改記為新列、結論不變。追蹤股擴大不進月調倉，要讓新資料進研究得走全市場表路線（71／78／81 那樣）
- 2026-10-18（使用者）：**全市場表 adj_close 重建**——減資 factor 上限放寬後 1529、2364、3043 三筆減資 factor ≥ 5 的 `market_daily_prices.adj_close` 依現行事件表重算（先只讀試算確認只動這三檔 2,331 列，再跑 `market_data.rebuild_adj()` 全市場）
- 2026-10-18（使用者）：**候選不換、都先列出**——`fhold` 不另登記新假設、四個跨段候補（#106／#108、#94／#96、#90／#92、#87／#88）都不升格，留在「未解」；接著「先補更多家的股票資料」→ Iteration 83：追蹤股從 26 檔擴到 0050 成分股全部（新增 42 家）
- 2026-10-18（82）：`momsx` 在第二批跑之前依列（`sir-rows-82`）改成排除 SIR 全市場前四分之一（原登記「排除 SIR > 0」在池內只剩約 3 檔）；原 sha256 保留、附錄重記，沒看過第二批報酬。`fhold` #103 共同窗口超過候選但登記指標未過：不跑 valid、不改規則，列給使用者決定是否登記新假設。#106 兩項超過 #30 → 依登記跑一次 valid（#108）。
- 2026-10-18（81）：籌碼結構面兩張表走交易所檔（同 71／78 路線）；融資融券統一存股、借券表沒列的股票借券欄 NULL 不補 0；外資持股比率存自己算的值並與交易所印的對位；migration 030／031 用 `lib/migrate.js` 套用不等 MoneyApi 重啟（同 78 的理由：讓回補今晚就跑）；下一代（82）從放空（借券 SIR）、散戶融資、持股水準／週轉率三組各登記一條、各一跑，登記前先查點時性（發行股數切換日分布）
- 2026-10-17（使用者）：**候選不換**——`win3+mom+fflow`（#94／#96）、`win3+relmom`（#90／#92）、`win3+mom+illiq`（#87／#88）與 `dy` 單獨（#99）都不升格，**先全部列出**在「未解」當跨段候補；MoneyScheduler 已重啟（23:45，18:37 估值排程掛上）；Iteration 78、80 已提交
- 2026-10-17（80）：價值（交易所估值）家族關閉——`dy` 單獨過門檻但不會成為候選（規則是兩項都超過 #30），不試殖利率區間、B/M、`dy+ep` 合併；殖利率 > 30% 當一次性股利不給值（看列定的，不看報酬）；虧損股在 `ep` 裡沒有值就不進排名（定義的一部分）；估值表留著，之後若用「殖利率當過濾」要另登記
- 2026-10-17（79）：策略範本放後端當單一來源（前端六個寫死模板拿掉），金額寫成資金比例；範本只是常見做法的定義、不調參、不挑最好的；比較表是事後結果，放交易模擬頁，不進 portfolio_runs、不登記 Papers.md；與 Iteration 78 並行時只在 progress.md／README **加**自己的段落
- 2026-10-17（78）：波動處理的動能家族關閉（`vmom`、`momx` 都低於候選；`lowvol` 相加早已低於）、不試其他分位或窗口；動能缺口閘門不登記（台灣證據為負，Lin, Ko & Yang 2022）；價值訊號依 Hsu 等 2015 用殖利率與益本比、不用 B/M；估值表走交易所檔（和法人表同路線）、migration 029 用 `Server/lib/migrate.js` 套用而不等 MoneyApi 重啟（同一支程式、冪等；為了讓回補今晚就能跑）；下一個資料工作是融資融券餘額表（P62）
- 2026-10-17（77）：折線圖沿用候選卡的 `NavRangeChart` 與 `/portfolio/runs/{id}` 資料，不另開端點；沒存曲線的早期 31 列不補跑（補要重跑回測）、只顯示說明；區間 localStorage key 每 run 一個
- 2026-10-17（76）：「贏過大盤」清單用年化主動 > 0 當門檻、作廢（tag = void）的不列（#67 舊保留期 +131% 是 0050 分割沒還原的假數字）；門檻另外標在每列，不把「贏過」寫成「可用」；持股端點回全部調倉（#44 177 KB），點開才抓、抓過就留著，不做分頁
- 2026-10-16（75）：交易模擬的「測試資料」不灌任何庫，由後端 `SyntheticSource` 現場產生；每檔種子 = `seed:stock_id`、序列固定從 2010-01-01 起，為了同代號在不同期間／組合裡看到同一條線；`source`／`seed` 在 Node 有給才轉，預設一律真實行情；合成結果一定帶警示 caveat 與橘色橫幅
- 2026-10-16（74）：交易模擬的大量測試資料走記憶體 monkeypatch，不灌測試庫——`market_days` 要每天 ≥ 500 列才算交易日，8 年要 108 萬列、22 秒（待確認，量測腳本在暫存區），且使用者要求不汙染真實股票資料；`patch` 同時把 `get_conn` 換成丟例外，漏接的資料庫存取當場失敗。方案 C（灌測試庫給儀表板手動操作）不做
- 2026-10-16（73）：投信淨買超、外資淨買超單獨兩個家族關閉；`win3+mom+fflow` 候選不換、交使用者決定；三個「開發期贏、驗證期略輸」的方向（illiq、relmom、fflow）**不做事後組合**
- 2026-10-15（72）：valid 規則統一為「兩項都超過 #30」（Iteration 70 登記檔兩段不一致的修正）；產業動能相加、同月季節性（1～3 lag）家族關閉；`win3+relmom` 候選不換、交使用者決定；不做 relmom × illiq × rev_accel 的事後組合
- 2026-10-15（71）：三大法人全市場表走交易所官方檔不走 FinMind——2,100 個交易日逐日呼叫 FinMind 要 3.5 小時以上且要 token，交易所檔沒有額度；和 market_daily_prices 同一條路線。外資含外資自營商、自營商含避險；寫入前驗合計
- 2026-10-15（69）：valid 的規則收緊——只給「開發期過門檻且年化主動或 IR 超過 #30、tests 已過」的設定跑一次；過門檻但低於候選的不跑（它不會成為候選，跑了只耗 N；#77／#80 就是這樣用掉的）
- 2026-10-15（69／70）：關閉的家族——資訊連續性相加（#83）、隔夜／日內拆解（#84 拿掉隔夜、#86 加回一個月隔夜，兩個方向都低於 `mom`）、中期動能 12-7（#85）；不試相鄰窗口
- 2026-10-15（70）：`win3+mom+illiq` 開發期超過候選、驗證期過門檻但低於候選——**候選不換**，依規則交由使用者決定；不做它和別的成分的事後組合
- 2026-10-15：「以營收為條件的動能」家族關閉（#82 沒過門檻），不試其他 SUE 門檻；營收與動能**相加**（Iteration 53）仍是候選以外跨段過門檻的方向之一
- 2026-10-15：市場狀態閘門家族（一年、三年）關閉——一年期反效果、三年期在樣本內不觸發；不再試其他 lookback（那是搜參數）
- 2026-10-15：三年期閘門用 0050 長歷史另載（`bench_hist`）而不是 `warmup_days`，為了讓 `estimate_tsmc_weight` 的 fallback 期和候選一致
- 2026-10-14：使用者要求**回研究階段、以論文為基礎迭代**——每條假設先在 Papers.md 登記來源與預期，一次一跑、不調參，結構固定為候選結構；候選仍不因單次實驗換
- 2026-10-14：`resmom` 的 β 用過原點迴歸（同窗口帶截距會變成反轉訊號，tests 抓到）；錯版的三次實驗留在日誌算 N
- 2026-10-14：市場狀態閘門先用一年期（為了和候選同一載入範圍、不暖機；文獻三年）；三年期是同一家族第二次抽樣、N+1
- 2026-10-14：意外觀察「一個月殘差反轉」（#72 dev +10.3%）**不追**（審查後改為：dev／valid 都已看過，視同已測、不登記、不重跑）
- 2026-10-11：候選 #44 升為正式策略、開保留期；#69 取代 #67（void 留著當證據）
- 2026-10-09：引擎啟動（紙上）、停損 0、限價 ±2%；回放不寫 portfolio_runs；預測用候選回測推常態區間（caveat DSR）

## 未解
- **8913 全銓租賃 2018-06-04 除權息 208 → 18.11 被 `load_events` 略過（83）**：factor 0.087 低於除權息下限 0.2，但市場收盤 208 → 19.90 是真的斷層，它 2018-06-04 以前的 `market_daily_prices.adj_close` 高十倍（該股 `market_type` NULL、2020-01-20 下市，池內大概碰不到）；要不要把除權息下限放寬或改用交易所參考價判定由使用者決定
- 回測 #54、#58、#62（rev_accel／rev1m 家族 valid）持股過 1529 或 2364：adj_close 重建後若重跑，2364 的動能回看跨過 2021-10-08、排名可能略變；候選與 live 清單不受影響
- 追蹤股 68 檔後第一個週日（2026-10-25）`job_weekly_forecast` 的執行時間要看；`job_news` 每小時 Yahoo RSS 68 條
- **跨段候補第四個（82）**：`win3+mom+nsir` #106 dev +9.77%／0.852（候選 +8.64%／0.67）、#108 valid +13.97%／1.062（候選 +15.71%／1.085），兩段追蹤誤差與相對落後都比候選小；和 #94／#96、#90／#92、#87／#88 同型。候選不換（使用者 2026-10-17），列著。
- **`fhold` #103 的共同窗口**：2018-11-12 起 +10.86%／1.550／TE 7.0%、2019 起 +8.95%／1.278，都高於候選；登記指標（全開發期含候選未進場的 2018-03～10）+6.01%／0.644 未超過，依規則沒跑 valid。要不要登記「`fhold` 對齊候選起點」或「`win3+mom+fhold`」為新假設（會跑 valid、N +1～2），由使用者決定。
- 策略範本沒做：參數開放前端調（會變成調參）、多檔組合、比較表存檔；真實行情比較只有四檔一個期間，不能拿來選策略
- **SUE 類訊號的點時缺口**（Iteration 68 量到）：`signal_sue` 不檢查公告日，2024-04 起有精確公告日的月份有 10.4% 股票月反應日晚於訊號日（最高 2026-03 26.6%）；含營收成分的實驗都受影響（結果檔 portfolio_iter68_momrev.md 第五節印出 23 列）；不影響候選。修 `signal_sue` 要重跑 #53 系列算 N，由使用者決定
- **`win3` 的農曆年缺陷**：三個「1～11 日」窗口各要 ≥ 3 個交易日，農曆年落在 2 月 1～10 日時（2019 年）2、3、4 月三個訊號日全空、候選不調倉抱舊持股；查過 2018-01～2024-09 只有 2019 年發生（2024 年 2 月窗口 3 天剛好夠；結果檔 portfolio_iter68_momrev.md 第三節）。改 `win3`（例如 min_count 降到 1 或窗口順延）等於改候選，由使用者決定
- **正式策略在保留期沒打敗 0050**（#69）：引擎繼續照它下單還是停，由使用者決定；本輪三條假設都沒給出更好的候選
- **`win3+mom+fflow`（#94／#96）要不要取代候選**：開發期兩項贏（+10.33%／0.875）、驗證期少 1.4 pp／IR（風險調整後）少 0.03、獨立訊號（持股交集 11／20）、優勢集中在 2020；DSR 0.403。由使用者決定
- **`win3+relmom`（#90／#92）要不要取代候選**：開發期兩項贏（+10.12%／0.785 對 +8.64%／0.67）、驗證期持平（+15.19%／1.07 對 +15.71%／1.085）、相對最大落後兩段都較小、產業更分散；但與 `mom` 等級相關 0.95（構造使然）、實際持股交集 18／20、#92 是候選家族的第二次抽樣而非獨立確認、產業分類是 2026 快照、DSR 0.457。由使用者決定
- **`dy` 單獨（#99）是「另一種」組合**：過門檻、追蹤誤差 7.6%、與候選持股幾乎不重疊（交集中位數 0、最大 1）、年化主動 +4.12%——不是候選的替代（報酬一半），但若要「低追蹤誤差、低換手」的版本，過門檻靠 2018 年（共同窗口 2018-11-12 起 +3.63%／0.622 仍過、2019 起 +2.34%／0.392 未過）且含櫃買殖利率前視；只有開發期數字、從沒在 valid 跑過，要另外追蹤得先登記並在 valid 跑一次（N+1）；要不要花這個 N 由使用者決定
- **`win3+mom+illiq`（#87／#88）要不要取代候選**：開發期 +11.09%／0.847 超過候選，驗證期 +14.14%／0.98 過門檻但低於候選 #38；優勢集中在 2021（+7.6 pp），但池內小型股對大型股 2021 只多 3.3%，不是單純 size 效應（結果檔第六節）；成交持股全市場流動性名次中位數 174 對候選 100、40% 持股名次 > 200 付 0.30% 滑價（候選 22%），150～200 那段付和候選一樣的滑價但成交金額較小（沒做敏感度）；DSR 用 N=88 只有 0.488。由使用者決定
- 候選以外跨段過門檻的家族有 `rev_accel+mom`、`win3+mom+rev_streak`（Iteration 53）、`win3+resmom`（#79／#80，驗證期不乾淨）、`win3+mom+rev_yoy3`（#74／#77）與 `win3+mom+illiq`（Iteration 70）——有效實作裡只有 `illiq` 在開發期超過候選；驗證期數字超過 #38 的只有不乾淨的 #80，乾淨確認裡沒有；「跨段家族等權組合」是事後組合，不列為候選假設
- 流程漏洞（strategy-critic 抓到）：錯版如果已經跑過 valid，修正版再跑 valid 就不乾淨——以後新訊號先只跑 dev、確認實作（tests）後才跑 valid
- 候選 DSR 用累積 N（現在 88）會再往下；每多一條假設都是成本
- Iteration 66～73 已於 2026-10-16 一次提交 4b8c8a8（55 個檔；65 是 dec7174）；未 push；MoneyCrawlerApi 不用重啟（66～70 只改訊號模組與測試，`signal_win3`／`signal_mom` 沒動；65 的新欄位要重啟才會出現）
- 文獻第二批裡要先補資料的：P31 同月季節性（全市場日線只從 2018 起）、P32 動能 × 週轉率（要流通股數）；要現金腿的：P42／P43（同 P10／P12）
- **櫃買估值檔的殖利率不是點時**（Iteration 80 `val-pit-check-80`）：股利年度整年固定、1 月 2 日就是當年才決議的股利；上市檔逐股在董事會後切換。若價值家族重開，要先補股利公告日（MOPS）或只用上市股。本益比兩市都在季報日更新、點時
- 估值表 `market_valuation_daily`（Iteration 78）：殖利率 > 50 的 517 列已查過是 7 檔的一次性大額股利（Iteration 80 用 > 30% 排除）；18:37 排程已於 2026-10-17 23:45 重啟後掛上
- 波動管理（P10／P12，引擎沒有現金腿）、動能季節性（P5，月份定義要讀全文）都還沒跑
- live 列 #68 沒暖機、2018 年前 10 個月空手；大盤線只是參考，指標仍對 0050
- `fake_market.patch` 只攔 `db.connection`、`portfolio_paper`、`trading_replay` 三處的 `get_conn`；日後有新模組在模組層 `from db.connection import get_conn` 且被模擬器用到，要加進清單（沒加的話 pytest 下會連到 `CRAWLER_TEST_DB` 測試庫、不是正式庫 `Stock`，但就不再是「不連庫」）
- 贏過大盤清單沒做多列同圖疊比、持股隨時間的變化圖、兩次回測持股交集比較、匯出；早期 31 列沒淨值曲線
- 合成資料的參數（波動、漂移、一字鎖機率）沒開放前端調；歷史回放分頁沒有合成版
- 條件規則沒做 NOT／跨股票／成交量；公開模擬沒做匯入 CSV；凱基未接；第二本模擬帳戶沒做
- 同一工作區兩個 session 會互相覆寫 progress.md——同時開要先分工目錄

## 下一步
使用者決定：（a）`fhold` 要不要登記新假設（對齊候選起點或 `win3+mom+fhold`）；（b）四個跨段候補（#106／#108、#94／#96、#90／#92、#87／#88）要不要換候選——Iteration 84 重算後數字都沒變；（c）8913 除權息下限要不要放寬。沒有決定前，下一代從 Papers.md 第六節挑：放空流量（P65，`sbl_sell` 21 日累計，先只看列）。
使用者要做的：三個常駐工作已於 2026-10-18 14:19 全部重啟（MoneyCrawlerApi、MoneyApi 曾於 12:44 被關掉 95 分鐘；MoneyScheduler 19 個排程、含 18:43 追蹤股補齊）；Iteration 83 已提交 d1835fa（收尾 70e98c4）；未 push。
仍待：SUE 類訊號公告日過濾、`win3` 農曆年缺陷。

## 階段
- [x] 階段 1 全市場股票池與日線、含息大盤
- [x] 階段 2 月調倉回測引擎與實驗日誌（DSR）
- [x] 階段 3 訊號搜尋與候選（N = 66，候選 #44）
- [~] 階段 4 紙上交易：模擬帳戶已開（2026-10-09），每日 18:40 結算，等每月清單累積
- [~] 階段 5 程式交易：引擎已啟動（紙上，停損 0、限價 ±2%）；凱基未接
- [~] 階段 8 追蹤股擴大（83）：0050 成分股 68 檔追蹤，三張表從全市場表每日補齊、公司行動 2003 起用交易所檔；MOPS 42 檔回補完
- [x] 階段 6 保留期：2026-10-11 開（#67 作廢、#69 重跑）：年化主動 −6.1%，**沒過門檻**
- [~] 階段 7 文獻驅動研究：（84）資料更新後 14 列原樣重算持股名單全同、指標一格 0.01 pp 捨入、N 不動；第一代（Iteration 66，N 70～80）三條假設都沒超過候選；第二代（67，#81）三年期閘門不觸發；第三代（68，#82）營收條件動能沒過門檻；第四代（69，#83～85）資訊連續性、日內動能、中期動能都低於候選；第五代（70，#86～88）隔夜持續沒過門檻、**Amihud 非流動性開發期超過候選、驗證期過門檻但低於候選**；第六代（72）扣產業的個股動能、第七代（73）外資淨買超相加都是開發期超過候選、驗證期略輸；27 次試驗，有效實作 3 次開發期超過候選（#87、#90、#94）、乾淨的驗證期確認 0 次超過候選（#92 −0.5 pp、#96 −1.4 pp、#88 −1.6 pp）；第八代（78，#97～#98）波動處理的動能（除以波動、去極端波動）都低於候選、家族關閉；第九代（80，#99～#102）價值：殖利率單獨過門檻但低於候選、益本比反向、相加都拉低；第十代（82，#103～#108）籌碼結構面：放空反向相加 #106 開發期超過候選、驗證期 #108 過門檻低 1.7 pp（第四個），外資持股水準 #103 共同窗口超過候選、登記指標未過，其餘三條關閉；39 次試驗（N 70～108），有效實作 4 次開發期超過候選、乾淨驗證期 0 次；論文 76 篇；法人買賣超全市場表（71）、估值表（78）回補完成，融資融券／借券與外資持股／發行股數表（81）回補完成（2026-10-18 03:24／05:16）