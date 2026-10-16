# 交接筆記

**更新：** 2026-10-16（Iteration 73）
（格式見 `.claude/rules/iterations.md`；儀表板「工作進度」頁讀這個檔。只寫有證據的事。）

## 任務
Iteration 73（未提交）：第七代——法人買賣超：`win3+mom+fflow`（外資 21 日淨買超占成交金額比例相加）#94 dev **+10.33%／0.875 兩項超過候選**、#96 valid +14.34%／1.054 低於候選 1.4 pp、IR 亦低；`fflow` 與 `mom` ρ 0.06、持股交集 11／20，是獨立訊號；外資單獨 #93 −0.03%（追蹤誤差 7.3%，持股名次中位數 153、不是權值股）、投信相加 #95 沒過門檻。N 96、候選不換。Iteration 71 回補完成（2,137 天、332 萬列、失敗 0、候選池覆蓋 99.9%）。
（以下為 72）
Iteration 72（未提交）：使用者「月調倉方案繼續找」→ 第六代（產業與季節性）：`win3+relmom`（扣掉產業的個股動能，P48）#90 dev **+10.12%／0.785 兩項超過候選**、#92 valid +15.19%／1.07 與候選持平（少 0.5 pp）、落後較小——目前最接近候選的一組，但與 `mom` ρ 0.95；產業動能相加 #89 低於候選；同月季節性 #91 沒過門檻（只有 1～3 個 lag）。N 92、候選不換。
（以下為 71）
Iteration 71（未提交，進行中）：使用者「先補」→ 全市場三大法人買賣超資料路線（P18 前置，不算 N）：交易所官方檔（證交所 T86＋櫃買 insti/dailyTrade）、解析器（證交所 19 欄、櫃買 16／24 欄，逐列驗合計）、migration 028 `market_institutional_daily`、`institutional_data.py`、排程 18:35、tests +4、真實檔煙霧五天過。**回補進行中**（22:06 起，約 6 秒／交易日，2,140 天；MoneyApi 由本 session 重啟後套上 028）。
（以下為 70）
Iteration 70（未提交）：第五代——隔夜短期持續 `win3+mom+ovn1m` #86 dev +6.31%／IR 0.493 沒過門檻（隔夜／日內家族關閉）；Amihud 非流動性 `win3+mom+illiq` #87 dev **+11.09%／0.847 超過候選**（19 次文獻試驗裡第一條有效實作；錯版 #72 不計），valid #88 +14.14%／0.98 過年化主動與 IR 門檻（DSR 0.488 未達 0.95）但低於候選 #38（+15.71%／1.085）；候選不換，換不換由使用者決定；N 88。
（以下為 69）
Iteration 69（未提交）：使用者再要「搜論文、記錄、以論文為基礎優化、不斷迭代、每代記錄，至少 10 篇」。文獻第二批 22 篇（Papers.md P25～P46、第八節）＋第四代三條：資訊連續性 #83 +6.49%／0.515、日內動能 #84 +7.00%／0.628、中期動能 12-7 #85 +3.07%／0.253，都低於候選、valid 不跑；valid 規則收緊為「過門檻且超過 #30」；N 85。
（以下為 68）
Iteration 68（未提交）：第三代——以營收驚喜為條件的動能 `win3+momrev`（Novy-Marx 2015，P11）#82 dev +4.69%／IR 0.38，低於候選、沒過門檻，家族關閉；N 82。順帶找到 `win3` 在農曆年落 2 月上旬時會整季失效（2019-02～04 候選也沒調倉）。
（以下為 67）
Iteration 67（未提交）：第二代——三年期市場狀態閘門（P6 第二次抽樣）#81 與候選 #30 完全相同（2018–2024 零次 DOWN），家族關閉；N 81。
（以下為 66，未提交）
Iteration 66（未提交）：使用者要「搜論文、記錄、以論文為基礎優化、不斷迭代、每代記錄」。第一代：`AI/Doc/Papers.md`（24 條，P1～P24）＋三條文獻假設各跑一次（殘差動能、營收 YoY 動能、市場狀態閘門），**都沒超過候選**；N 69 → 80；候選不換、保留期未開。
（以下為 65，已提交 dec7174）
Iteration 65：月調倉頁與正式策略頁的淨值曲線加含息大盤（TAIEX_TR）第三條線；純顯示，N 不動
（以下為 64，已提交 bb791d6）
Iteration 64：候選 #44 升為正式策略（新頁、live #68 每日 18:50 重算）；保留期重跑 #69——**年化主動 −6.1%、輸給 0050**。引擎已啟動（紙上、停損 0、限價 ±2%）

## 產出
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
- **SUE 類訊號的點時缺口**（Iteration 68 量到）：`signal_sue` 不檢查公告日，2024-04 起有精確公告日的月份有 10.4% 股票月反應日晚於訊號日（最高 2026-03 26.6%）；含營收成分的實驗都受影響（結果檔 portfolio_iter68_momrev.md 第五節印出 23 列）；不影響候選。修 `signal_sue` 要重跑 #53 系列算 N，由使用者決定
- **`win3` 的農曆年缺陷**：三個「1～11 日」窗口各要 ≥ 3 個交易日，農曆年落在 2 月 1～10 日時（2019 年）2、3、4 月三個訊號日全空、候選不調倉抱舊持股；查過 2018-01～2024-09 只有 2019 年發生（2024 年 2 月窗口 3 天剛好夠；結果檔 portfolio_iter68_momrev.md 第三節）。改 `win3`（例如 min_count 降到 1 或窗口順延）等於改候選，由使用者決定
- **正式策略在保留期沒打敗 0050**（#69）：引擎繼續照它下單還是停，由使用者決定；本輪三條假設都沒給出更好的候選
- **`win3+mom+fflow`（#94／#96）要不要取代候選**：開發期兩項贏（+10.33%／0.875）、驗證期少 1.4 pp／IR（風險調整後）少 0.03、獨立訊號（持股交集 11／20）、優勢集中在 2020；DSR 0.403。由使用者決定
- **`win3+relmom`（#90／#92）要不要取代候選**：開發期兩項贏（+10.12%／0.785 對 +8.64%／0.67）、驗證期持平（+15.19%／1.07 對 +15.71%／1.085）、相對最大落後兩段都較小、產業更分散；但與 `mom` 等級相關 0.95（構造使然）、實際持股交集 18／20、#92 是候選家族的第二次抽樣而非獨立確認、產業分類是 2026 快照、DSR 0.457。由使用者決定
- **`win3+mom+illiq`（#87／#88）要不要取代候選**：開發期 +11.09%／0.847 超過候選，驗證期 +14.14%／0.98 過門檻但低於候選 #38；優勢集中在 2021（+7.6 pp），但池內小型股對大型股 2021 只多 3.3%，不是單純 size 效應（結果檔第六節）；成交持股全市場流動性名次中位數 174 對候選 100、40% 持股名次 > 200 付 0.30% 滑價（候選 22%），150～200 那段付和候選一樣的滑價但成交金額較小（沒做敏感度）；DSR 用 N=88 只有 0.488。由使用者決定
- 候選以外跨段過門檻的家族有 `rev_accel+mom`、`win3+mom+rev_streak`（Iteration 53）、`win3+resmom`（#79／#80，驗證期不乾淨）、`win3+mom+rev_yoy3`（#74／#77）與 `win3+mom+illiq`（Iteration 70）——有效實作裡只有 `illiq` 在開發期超過候選；驗證期數字超過 #38 的只有不乾淨的 #80，乾淨確認裡沒有；「跨段家族等權組合」是事後組合，不列為候選假設
- 流程漏洞（strategy-critic 抓到）：錯版如果已經跑過 valid，修正版再跑 valid 就不乾淨——以後新訊號先只跑 dev、確認實作（tests）後才跑 valid
- 候選 DSR 用累積 N（現在 88）會再往下；每多一條假設都是成本
- Iteration 66～70 未提交（五輪；65 已提交 dec7174）；MoneyCrawlerApi 不用重啟（66～70 只改訊號模組與測試，`signal_win3`／`signal_mom` 沒動；65 的新欄位要重啟才會出現）
- 文獻第二批裡要先補資料的：P31 同月季節性（全市場日線只從 2018 起）、P32 動能 × 週轉率（要流通股數）；要現金腿的：P42／P43（同 P10／P12）
- 法人籌碼（Papers P18）全市場資料不在庫裡（`stock_foreign_holding` 只有 26 檔），要先補 FinMind 三大法人買賣超
- 波動管理（P10／P12，引擎沒有現金腿）、動能季節性（P5，月份定義要讀全文）都還沒跑
- live 列 #68 沒暖機、2018 年前 10 個月空手；大盤線只是參考，指標仍對 0050
- 條件規則沒做 NOT／跨股票／成交量；公開模擬沒做匯入 CSV；凱基未接；第二本模擬帳戶沒做
- 同一工作區兩個 session 會互相覆寫 progress.md——同時開要先分工目錄

## 下一步
使用者重啟 MoneyScheduler（18:35 法人排程）；使用者決定候選：`win3+mom+fflow`（#94／#96）、`win3+relmom`（#90／#92）、`win3+mom+illiq`（#87／#88）三個都是開發期贏、驗證期略輸，候選仍 #44。
沒有指示就做第八代的資料前置（不算 N）：外資持股比率全市場表（證交所 MI_QFIIS 每日、櫃買同類表）——P18 的「持股水準」面向，與流量不同；或 P50 Hou 2007 產業領先股（要先定義領先股，門檻是參數，先登記再跑）。
仍待：SUE 類訊號公告日過濾、`win3` 農曆年缺陷。

## 階段
- [x] 階段 1 全市場股票池與日線、含息大盤
- [x] 階段 2 月調倉回測引擎與實驗日誌（DSR）
- [x] 階段 3 訊號搜尋與候選（N = 66，候選 #44）
- [~] 階段 4 紙上交易：模擬帳戶已開（2026-10-09），每日 18:40 結算，等每月清單累積
- [~] 階段 5 程式交易：引擎已啟動（紙上，停損 0、限價 ±2%）；凱基未接
- [x] 階段 6 保留期：2026-10-11 開（#67 作廢、#69 重跑）：年化主動 −6.1%，**沒過門檻**
- [~] 階段 7 文獻驅動研究：第一代（Iteration 66，N 70～80）三條假設都沒超過候選；第二代（67，#81）三年期閘門不觸發；第三代（68，#82）營收條件動能沒過門檻；第四代（69，#83～85）資訊連續性、日內動能、中期動能都低於候選；第五代（70，#86～88）隔夜持續沒過門檻、**Amihud 非流動性開發期超過候選、驗證期過門檻但低於候選**；第六代（72）扣產業的個股動能、第七代（73）外資淨買超相加都是開發期超過候選、驗證期略輸；27 次試驗，有效實作 3 次開發期超過候選（#87、#90、#94）、乾淨的驗證期確認 0 次超過候選（#92 −0.5 pp、#96 −1.4 pp、#88 −1.6 pp）；論文 50 篇；法人買賣超全市場表（71）回補完成
