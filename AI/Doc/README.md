# AI 模組文件索引

## 系統文件

| 文件 | 說明 |
|------|------|
| [Architecture.md](./Architecture.md) | 系統架構：爬蟲、NLP、預測模型、API 各子系統設計 |
| [Architecture.diagram.html](./Architecture.diagram.html) | 系統架構圖 v2（六層 + 排程器，2026-09-25；含 JWT 認證、持股按人隔離、排程型事件與 NewsModels 研究、尚未做的階段 2～5） |
| [Architecture-MultiUser.diagram.html](./Architecture-MultiUser.diagram.html) | 目標架構提案：持股按使用者隔離（users + user_id + JWT）、前端獨立部署 GitHub Pages、Cloudflare Tunnel 連回本機 API；資料隔離表、變更清單、階段順序（2026-09-25） |
| [DataFlow.diagram.html](./DataFlow.diagram.html) | 整體資料流程圖：來源 → 採集 → PostgreSQL → 對齊／特徵 → 模型與事件研究；新聞訊號研究線；排程表（Iteration 39） |
| [RevenueEventStudy.md](./RevenueEventStudy.md) / [_universe](./RevenueEventStudy_universe.md) / [MopsEventStudy.md](./MopsEventStudy.md) / [NewsEventStudy.md](./NewsEventStudy.md) | 事件研究報告：月營收（23 檔／181 檔）、MOPS 分類、媒體新聞 |
| [DB.md](./DB.md) | 資料庫設計：PostgreSQL 台股資料表、模型訓練視圖 |
| [DataSources.md](./DataSources.md) | 外部資料來源：新聞網站、FinMind API（台股行情）、欄位對照表 |
| [LSTM-Setup.md](./LSTM-Setup.md) | LSTM 訓練環境設定、啟動指南（train_all / train_cross / serve.py） |
| [LSTM-Improvement.md](./LSTM-Improvement.md) | LSTM 準確率改進方案（IMP-001 ~ IMP-006） |
| [../../UnifiedModel/results/news_models.md](../../UnifiedModel/results/news_models.md) | 新聞訊號三模型的走查與五道關卡（Iteration 47，`train_news_models.py` 產出） |
| [ModelAccuracy.md](./ModelAccuracy.md) | 模型預測準確度報告（線上台帳 vs 離線走查）與改進方向（2026-09-20） |
| [Papers.md](./Papers.md) | 論文紀錄（2026-10-14 起）：打敗大盤計畫的文獻基礎，每篇寫「對專案的意思」與狀態（已測 #n／已採用／待測／待資料／不測）；新實驗要能指回一條 |
| [Bugs/bugs.md](./Bugs/bugs.md) | Bug 紀錄與功能追加履歷 |
| [../harness/README.md](../harness/README.md) | Claude Code harness（2026-10-09）：CLAUDE.md、rules、skills、agents、hooks、`progress.md` 交接筆記、`record_check.js` 驗證紀錄；儀表板「工作進度」頁 |

## 迭代紀錄（Iterations/）

| 文件 | 說明 |
|------|------|
| [Iteration-00.md](./Iterations/Iteration-00.md) | Git baseline 建立 + 現況盤點（2026-08-06） |
| [Iteration-01.md](./Iterations/Iteration-01.md) | stock_info 資料完整性修正（4 → 22 筆） |
| [Iteration-02.md](./Iterations/Iteration-02.md) | 三模型投票管線修復（news_features 落地 + 22 檔投票） |
| [Iteration-03.md](./Iterations/Iteration-03.md) | 文件同步（本文件索引、Spec 狀態） |
| [Iteration-04.md](./Iterations/Iteration-04.md) | 排程自動化（每日股價 / 每小時新聞特徵 / 每日 20:00 投票） |
| [Iteration-05.md](./Iterations/Iteration-05.md) | FinMind volume 欄位 bug 修復 + 行情全量回補（補至 2026-08-05） |
| [Iteration-06.md](./Iterations/Iteration-06.md) | M3 籌碼模型（Random Forest）訓練與整合；發現籌碼歷史全 0 |
| [Iteration-07.md](./Iterations/Iteration-07.md) | 籌碼全史回補 + M3 重訓（籌碼特徵重要度恢復） |
| [Iteration-08.md](./Iterations/Iteration-08.md) | M2 新聞模型（XGBoost）訓練管線 + 資料充足性門檻 |
| [Iteration-09.md](./Iterations/Iteration-09.md) | M3 走查驗證重建；發現信心門檻致線上永不出手、賣出訊號與規則 fallback 均無 edge |
| [Iteration-10.md](./Iterations/Iteration-10.md) | 新聞爬蟲改用公開 RSS／鉅亨網 API（內文由全空到 0% 失敗）；修正 M2 結構性無法區分個股 |
| [Iteration-11.md](./Iterations/Iteration-11.md) | 補齊 M07 Seq2Seq 與 M10 Ensemble；建立誠實評估後發現 10 個 LSTM 全部等同天真基準線 |
| [Iteration-12.md](./Iterations/Iteration-12.md) | 資料擴充至 1994 年（46,341 筆）+ 54 特徵整合模型；70% 目標不可達，最佳 59.89%（出手率 5%） |
| [Iteration-13.md](./Iterations/Iteration-13.md) | 波動率風險模組：相關 0.606 全面優於 EWMA；部位規則使超限交易減少 43% |
| [Iteration-14.md](./Iterations/Iteration-14.md) | 美股資料接入（實測無助益）、台股回補至 1992（167,119 筆）、投組相關性調整、前端風險欄位 |
| [Iteration-15.md](./Iterations/Iteration-15.md) | **修正 Iteration 14 結論**：美股與台股開盤跳空相關 +0.66，資訊在開盤即被吸收 |
| [Iteration-16.md](./Iterations/Iteration-16.md) | 開盤跳空預測上線：方向準確率 67.3%、MAE 0.66%，勝過費半單因子基準（盤前參考資訊） |
| [Iteration-17.md](./Iterations/Iteration-17.md) | 除權息調整：汙染範圍實為 5.54%（滾動窗擴散 20 倍），波動率 R²(log) 0.473→0.483 |
| [Iteration-18.md](./Iterations/Iteration-18.md) | adj_close 根本解 + 減資：11 筆減資的影響大於 479 筆除權息（單日假漲幅 +123%） |
| [Iteration-19.md](./Iterations/Iteration-19.md) | 週振幅預測：挑出一週內高低點顯著偏大的股票，lift 1.989（前 10% 振幅為平均近兩倍） |
| [Iteration-20.md](./Iterations/Iteration-20.md) | 事件特徵：**誠實的負面結果**——營收／除權息對振幅無可測效應（t=−0.55/−0.66），不採用 |
| [Iteration-21.md](./Iterations/Iteration-21.md) | 模型版本與凍結：長期服役快照 + 影子評估 + 預測台帳；自動門檻以多數類別為基準 |
| [Iteration-22.md](./Iterations/Iteration-22.md) | 持股輸入、六角色決策、5 日週計畫；**週擇時策略迭代收斂後仍輸給買進持有，不部署** |
| [Iteration-23.md](./Iterations/Iteration-23.md) | 交易台帳：持倉改由交易回放推導（移動平均成本、含費稅），可算已實現損益 |
| [Iteration-24.md](./Iterations/Iteration-24.md) | 張／零股單位；「建議 vs 實際」對照：第一次把模型的話與人的動作放同一張表 |
| [Iteration-25.md](./Iterations/Iteration-25.md) | UI 改版：雙主題／三段字級、台股紅漲綠跌、投票頁拆持有中／未持有（Iteration 36 依 git log 補寫） |
| [Iteration-26.md](./Iterations/Iteration-26.md) | 預測比對頁重做（移除延遲載入、ErrorBoundary）、三層自動檢查（smoke／互動／Playwright 版面）、閒置資金一週配置 |
| [Iteration-27.md](./Iterations/Iteration-27.md) | 資料新鮮度自動補齊（市場基準日判準）、趨勢預測頁可自我診斷（404 detail、代號空白、全部儲存） |
| [Iteration-28.md](./Iterations/Iteration-28.md) | 台指期夜盤：跳空模型方向 69.92%→72.24% 通過部署；同一份資料對 LSTM 收盤預測**完全無用** |
| [Iteration-29.md](./Iterations/Iteration-29.md) | 韓股／日股：單獨有資訊（單因子方向 66.29%）但幾乎被夜盤涵蓋，**三個模型皆未通過門檻** |
| [Iteration-30.md](./Iterations/Iteration-30.md) | 巢狀走查取代單層自我迭代：振幅／波動率部署 v2，跳空與 M3 否決；**Iteration 29 的 +0.0188 提升被證實為選擇偏誤** |
| [Iteration-31.md](./Iterations/Iteration-31.md) | 統一資料層 + 模型目錄 + 每頁可選模型；新增成交量模型（排序相關 0.4823）；**相對強弱因 2012 前籌碼特徵是捏造的零而從「通過」翻成「不通過」** |
| [Iteration-32.md](./Iterations/Iteration-32.md) | 美股外生資料進排程（06:10／19:10／20:00）；**反向跳空模型**：台股＋韓日 → 美股開盤，方向 61.32% 對多數類別 55.33%；美股波動率因 QLIKE 輸 EWMA 否決 |
| [Iteration-33.md](./Iterations/Iteration-33.md) | 美股趨勢預測與預測比對：同一批 LSTM、同一套比對邏輯，價格表／台帳／模型類型依 `market` 分流；**不做新趨勢模型**（全日方向只贏多數類別 +1.68pp）；發現 start-dev.bat 從未啟動排程器 |
| [Iteration-34.md](./Iterations/Iteration-34.md) | 美股清單 12 → 23 檔：照「與台灣的連動機制」挑候選、巢狀走查驗；三折挑出同一份清單，ASX（0.479）超過 TSM；**AAPL/MSFT 過門檻留任，不事後抬門檻**；EWT 是套套邏輯、不撐平均 |
| [Iteration-35.md](./Iterations/Iteration-35.md) | 「法人持股」頁 + 外資真實持股進排程（`stock_foreign_holding`，26 檔回補 91,544 筆）；**修正全站日期少一天**：pg DATE → 本地午夜 → `toISOString()` 退回前一天，改在連線層以字串回傳 |
| [Iteration-36.md](./Iterations/Iteration-36.md) | 遺留待辦清理：外資真實持股進巢狀走查——**四模型 12 折只被選中 1 折、M3 −0.37pp，不進模型**；持股%標示資料日期；排程器常駐化（工作排程器 + 啟動補跑 + 檔案日誌）；IMPR-001 執行與結案、DA 算法修正；補寫 Iteration 25~27 |
| [Iteration-37.md](./Iterations/Iteration-37.md) | 每週自動預測：每週日 08:00 排程用全部模型對全部股票預測下一週與下下週，存表直接顯示（新頁「週預測」）；錯過自動補跑 |
| [Iteration-38.md](./Iterations/Iteration-38.md) | 新聞資料回填與結構化（進行中）：鉅亨網 API 三年回填（tw_stock / us_stock / headline）、排程器啟動補新聞空洞；後續：別名表、去重、日級對齊、歷史特徵、美股新聞、LLM 抽取 |
| [Iteration-85.md](./Iterations/Iteration-85.md) | **第十一代：放空流量（借券賣出 ÷ 成交金額）相加 `win3+mom+nsblf` #110 開發期 +11.57%／0.906 超過候選、#113 驗證期 +15.24%／1.048 低候選 0.5 pp（歷來最接近）；產業領先股相加 #112 +10.27%／0.834、#114 valid +14.78%／1.05 低 0.9 pp（與候選最不像：持股交集 9／20）；兩條單獨訊號都反向、關閉**（N 108 → 114）；文獻第五批 P77～P80 |
| [Iteration-84.md](./Iterations/Iteration-84.md) | 資料更新後月調倉重算：候選 #30／#38／#44、四個跨段候補八列、持有過被重算股票的 #54／#58／#62 共 14 列，用日誌參數原樣重算（不計 N）持股名單全同、指標 112 格有 111 格相同（一格 0.01 pp 捨入）；追蹤股擴大不進月調倉（股票池只讀全市場表；0050 基準除外，已驗差 0.0005%）——候選不換、N 108、保留期未開 |
| [Iteration-83.md](./Iterations/Iteration-83.md) | 追蹤股 26 → 68 檔（0050 成分股 42 家）：FinMind 回補行情／籌碼／外資持股 126 次呼叫未觸額度，事件改用交易所檔（FinMind 的「權」列參考價＝前收，會漏掉股票股利），新增 `tracked_sync.py` 每日 18:43 從全市場表補 FinMind 漏掉的列；兩個來源 2018 起逐列對照：收盤、法人、持股全同 |
| [Iteration-82.md](./Iterations/Iteration-82.md) | **第十代：籌碼結構面——動能 × 放空反向相加 `win3+mom+nsir` #106 開發期 +9.77%／0.852 超過候選、驗證期 #108 +13.97%／1.062 過門檻但低候選 1.7 pp（第四個這種相加家族，列候補）；外資持股水準 `fhold` #103 登記指標低於候選、共同窗口 2018-11 起 +10.86%／1.550 超過候選（待使用者決定是否登記新假設）；低週轉率動能 #104、排除被放空股 #105、散戶融資反向 #107 都沒超過候選、關閉**：事前登記 03:27、`momsx` 跑前依列改分位（附錄）、N 102 → 108；候選 #44 不換、保留期未開 |
| [Iteration-81.md](./Iterations/Iteration-81.md) | **籌碼結構面資料路線：全市場融資融券／借券賣出與外資持股／發行股數兩張表建好、回補中**（文獻第四批 P65～P76，12 篇：放空流量與借券 SIR、散戶融資反向、外資持股水準、低週轉率動能）：證交所 MI_MARGN＋TWT93U＋MI_QFIIS、櫃買 margin/balance＋margin/sbl＋insti/qfii，2018 起都有；migration 030／031、`margin_data.py`／`holding_data.py`、18:39／18:41 排程、tests +4、真實檔煙霧五天過（借券欄 100%、對位檢查過）；不算 N（102）；下一代從放空、融資、持股水準／週轉率各登記一條 |
| [Iteration-80.md](./Iterations/Iteration-80.md) | **第九代：價值——殖利率單獨過門檻靠 2018 年（共同窗口 2018-11-12 起仍過、2019 起未過）、開發期低於候選；益本比反向，相加都拉低動能，家族關閉**（估值表 Iteration 78）：`dy` 單獨 #99 +4.12%／0.542（共同窗口 2018-11-12 起 +3.63%／0.622、2019 起 +2.34%／0.392 未過門檻；上櫃持股平均 2.8／20 含殖利率前視），相對最大落後 −7.2% 開發期最小、追蹤誤差 7.6%、持股與候選交集中位數 0／20、ρ(mom, dy) −0.37；`win3+mom+dy` #101 +4.86%／0.431（追蹤誤差與落後降了但報酬少 3.8 pp）；`ep` 單獨 #100 −3.33%／−0.401、相加 #102 +0.29%；valid 都不跑；點時性檢查：上市殖利率與兩市本益比點時、櫃買殖利率年初就印當年才決議的股利（前視）；N 102、候選不換 |
| [Iteration-79.md](./Iterations/Iteration-79.md) | **十種交易策略範本搬到後端、可一鍵比較**：`trading_presets.py` 單一來源（六個舊模板＋買進持有／定期定額／季線趨勢／動能突破）、`GET /trading/sim/presets`、`POST /trading/sim/presets/compare`、Node `/sim/presets`／`/sim/compare`、前端「比較全部策略」表；tests 用 V 形合成行情驗每種照定義動作（雙重確認在長跌後反彈永遠不買）；真實行情四檔 2018-01～2024-09：一直在場的三種在三檔贏 0050、純擇時的五種四檔全輸（期末現金 89%～100%）、季線趨勢與定投在均線下只在 2603 贏；不寫 portfolio_runs、N 不動；pytest 272、jest 193 |
| [Iteration-78.md](./Iterations/Iteration-78.md) | **第八代：波動處理的動能開發期都低於候選，家族關閉；全市場估值表建好、回補完成**（文獻第三批 P51～P64，14 篇）：`win3+vmom`（動能 ÷ 同窗口波動）#97 +7.92%／0.627，與 `mom` ρ 0.98、持股交集 17／20，幾乎沒改變排名；`win3+momx`（去掉全市場波動最高十分位）#98 +6.94%／0.578，落後與追蹤誤差較小但 2020 年少 12.4 pp（當年贏家是高波動股）；兩條都過門檻但低於候選 #30（+8.64%／0.67），valid 不跑；資料前置：`market_valuation_daily`（證交所 BWIBBU_d＋櫃買 peQryDate，本益比／殖利率／淨值比，migration 029、`valuation_data.py`、18:37 排程、tests +4、真實檔煙霧五天過）2018 起回補完成（2,138 個交易日、380 萬列、失敗 0、日線有估值表沒有的股票日 0.24%），下一代登記價值訊號 `dy`／`ep`；N 98、候選不換 |
| [Iteration-77.md](./Iterations/Iteration-77.md) | **「贏過大盤」清單展開時加淨值折線圖**（組合／0050 含息／大盤）：用既有 `/portfolio/runs/{id}` 曲線與 `NavRangeChart`，`has_series` 才抓、沒曲線的 31 列顯示說明；純前端、不用重啟；vite／mfe build 過 |
| [Iteration-76.md](./Iterations/Iteration-76.md) | **月調倉頁最上面列「贏過大盤」的每一次回測，點一列展開每個訊號日買了哪些股票**：`portfolio_api.run_positions` ＋ `GET /portfolio/runs/{id}/positions`（全部調倉、名稱、最常買到）、Node 代理、前端 `BeatMarketList`（年化主動 > 0 且非作廢、門檻過幾項、段別篩選、點開才抓）；純讀取、N 不動（96）；pytest 263、jest 191、vite／mfe build |
| [Iteration-75.md](./Iterations/Iteration-75.md) | **交易模擬頁可選「測試資料（合成）」**：`synthetic_market.py` 資料來源物件（`DbSource` 真實／`SyntheticSource(seed)` 合成，每檔獨立種子、從 2010 固定產生，同代號同種子跨期間一致），兩個模擬器多 `source` 參數、結果多 `source` 與警示 caveat；API／Node `source`／`seed`（有給才轉、白名單、400）；前端資料下拉、種子、`SourceBanner` 橘色警示；預設仍真實行情、合成不讀不寫任何庫；pytest 261、jest 190、vite build |
| [Iteration-74.md](./Iterations/Iteration-74.md) | **交易模擬的大量假資料改走記憶體**：`tests/helpers/fake_market.py` 合成行情（幾何隨機漫步、一字鎖貼漲跌停、0050 走回退表）＋ `patch` 攔下三個資料函式與 `get_conn`，8 年 × 61 檔上 5 種子 × 50 條隨機規則、5 種子 × 200 筆隨機指令的帳務不變量（現金／股數／費稅／淨值）全過、不連任何資料庫；`test_trading_fuzz.py` 15 項；pytest 256、jest-unit 44；模擬器本體未動、N 不動 |
| [Iteration-73.md](./Iterations/Iteration-73.md) | **第七代：外資淨買超加進動能**（P18／P44）`win3+mom+fflow` 開發期 #94 +10.33%／0.875 兩項超過候選、驗證期 #96 +14.34%／1.054 低於候選 #38 1.4 pp、IR 亦低；`fflow` 與 `mom` ρ 0.06、持股交集 11／20，是獨立訊號；外資單獨 #93 −0.03%（追蹤誤差 7.3%，持股不是權值股、原因沒量到）、投信相加 #95 沒過門檻；N 96、候選不換 |
| [Iteration-72.md](./Iterations/Iteration-72.md) | **第六代：扣掉產業的個股動能**（Grundy & Martin 2001，P48）`win3+relmom` 開發期 #90 +10.12%／0.785 兩項超過候選，驗證期 #92 +15.19%／1.07 與候選 #38（+15.71%／1.085）持平、落後較小——但與 `mom` 等級相關 0.95（構造使然）、實際持股交集中位數 18／20，#92 是候選家族的第二次抽樣而非獨立確認；產業動能相加 #89 +7.89%／0.624 低於候選、同月季節性 #91 +0.37%（只有 1～3 個 lag）；N 92、候選不換（使用者決定） |
| [Iteration-71.md](./Iterations/Iteration-71.md) | **全市場三大法人買賣超資料路線**（P18 前置，不算 N）：改走交易所官方檔（證交所 T86、櫃買 insti/dailyTrade，一天兩次呼叫）而非 FinMind；解析器處理證交所 19 欄與櫃買 16／24 欄兩種版面、逐列驗證合計＝三法人相加；migration 028 `market_institutional_daily`、`institutional_data.py` 回補／每日 18:35 排程；pytest +4、真實檔煙霧測試五天過；回補完成（2,137 個交易日、332 萬列、失敗 0）、候選池覆蓋 99.9% |
| [Iteration-70.md](./Iterations/Iteration-70.md) | **第五代：Amihud 非流動性**（P35）`win3+mom+illiq` 是 19 次文獻試驗裡第一條有效實作在開發期超過候選的（錯版 #72 不計）（#87 +11.09%／0.847 對 +8.64%／0.67），驗證期 #88 +14.14%／0.98 過年化主動與 IR 門檻（DSR 未達）但低於候選 #38（+15.71%／1.085）；持股流動性名次中位數 80 → 152、開發期優勢集中在 2021；隔夜短期持續 `ovn1m` #86 沒過門檻、隔夜／日內家族關閉；N 88、候選不換（使用者決定）；pytest 234 |
| [Iteration-69.md](./Iterations/Iteration-69.md) | **文獻第二批（22 篇，P25～P46）與第四代**：資訊連續性 `win3+mom+cont` #83 +6.49%／0.515、日內動能 `win3+imom` #84 +7.00%／0.628（追蹤誤差與落後較小但報酬低於候選）、中期動能 12-7 `win3+mom127` #85 +3.07%／0.253——都低於候選、valid 不跑；valid 規則收緊為「過門檻且超過候選」；N 85 |
| [Iteration-68.md](./Iterations/Iteration-68.md) | **第三代：以營收驚喜為條件的動能**（Novy-Marx 2015，P11）：`win3+momrev` 開發期 +4.69%／IR 0.38 低於候選 +8.64%／0.67、沒過門檻，候選池中位數 266 → 116 檔；家族關閉；N 82、valid 不跑；順帶發現 `win3` 在農曆年落 2 月上旬時整季失效（2019-02～04 候選也沒調倉）、SUE 類訊號有 10.4% 股票月反應日晚於訊號日；pytest 229 |
| [Iteration-67.md](./Iterations/Iteration-67.md) | **第二代：三年期市場狀態閘門**（Cooper 2004 原定義，P6 第二次抽樣）在 2018–2024 一次都沒觸發（0050 三年報酬最低 +22.6%），#81 與候選 #30 完全相同；市場狀態閘門家族（一年反效果、三年不觸發）關閉；N 81、候選不換、valid 不跑；pytest 228 |
| [Iteration-66.md](./Iterations/Iteration-66.md) | **文獻驅動的第三批實驗**（[Papers.md](./Papers.md) 24 條）：殘差動能（Blitz 2011）、營收 YoY 動能（Hung 2025）、市場狀態閘門（Cooper 2004／Du 2009）三條假設各跑一次，**都沒超過候選**；`win3+resmom` 修正版兩段過門檻（dev +7.49%／valid +16.30%）但開發期低於候選、且驗證期已被錯版 #76 看過一次；`tests` 抓到第一版殘差動能等於一個月反轉（#71／#72／#76 作實作錯誤留檔）；N 69 → 80、候選不換、保留期未開；pytest 227 |
| [Iteration-65.md](./Iterations/Iteration-65.md) | 月調倉與正式策略的淨值曲線加**含息大盤**（`index_daily_prices` TAIEX_TR，`get_run` series 多 `idx`、第一天歸一、缺日沿用前一日）；正式策略全期間 10.38 對 0050 7.22 對大盤 6.11，**保留期 #69 輸 0050 也輸大盤**（2.206／2.491／2.272）；不跑回測、N 不動；pytest 225、兩個 build 過 |
| [Iteration-64.md](./Iterations/Iteration-64.md) | **候選 #44 升為正式策略**：保留期開一次（#67）、live 列每日 18:50 重算（#68，migration 027 `portfolio_official`）、新頁「正式策略」（匿名可讀）；**抓到 0050 2025-06-18 一拆四沒還原、回測沒暖機**（修 adj_close、`run` 加 `warmup_days`），保留期重跑 #69 取代 #67：**年化主動 −6.1%、IR −0.45，正式策略在保留期輸給 0050** |
| [Iteration-63.md](./Iterations/Iteration-63.md) | 月調倉頁淨值曲線可選區間（全期間／開發期／驗證期／最近 1、3 年／自訂起迄），區間內重新歸一並顯示組合／0050／主動報酬與年化 |
| [Iteration-62.md](./Iterations/Iteration-62.md) | **條件 AND／OR 組合**：`when` 可為 `{op: and|or, conds:[…]}`（巢狀兩層、每層 1～8），`_eval` 遞迴求值；含日期條件的規則當天開盤判斷、指標看前一日收盤；頁面每條規則「＋ 加條件」與「且／或」切換，模板加「定投在均線下」「雙重確認」 |
| [Iteration-61.md](./Iterations/Iteration-61.md) | **條件 → 觸發買賣**：`trading_strategy.py` 十四種條件（價格、均線穿越／狀態、RSI、N 日報酬、停損停利、每月固定日、指定日期），收盤判斷隔天開盤成交，`max_times`／`only_if_flat`／`cooldown`；公開 `POST /sim/rules`；頁面 `RuleBuilder`（條件下拉、四個模板、觸發紀錄），自訂指令分頁三種模式 |
| [Iteration-60.md](./Iterations/Iteration-60.md) | **交易模擬開放給未登入者**：`trading_sim.py` 自訂交易指令（一行一筆「日期 買/賣 代號 數量」，當天開盤市價、順延、金額換股、全部賣出）設期間與資金跑實際日線給收益對 0050；公開路由 `/sim/replay`、`/sim/run`（只讀、不登入）；頁面「交易模擬」（自訂指令／歷史回放），統一前端放「預測」群組匿名可用；回放分頁抽成 `ReplayPanel` |
| [Iteration-59.md](./Iterations/Iteration-59.md) | **程式交易回放**：規則抽成純函式 `trading_rules.py`（引擎與回放同一份），`trading_replay.py` 把限價／重掛／停損／守門套在候選期間（2018-11～2024-09，68 份清單）的實際日線上對照「照單全收」；**停損 15%／25%／35% 都輸、限價 ±0.5% 少賺 1.9%／年、±2% 只差 0.5%**；`/trading/engine/replay` 與頁面「歷史模擬」分頁 |
| [Iteration-58.md](./Iterations/Iteration-58.md) | **程式交易引擎**：規則（候選清單、11 日調倉、停損 15%、相對回撤守門 10%、零股限價 ±0.5% 重掛 3 次）寫成 `Crawler/trading_engine.py`，委託單生命週期與事件（migration 026），券商介面 `brokers/`（紙上成交寫同一本模擬帳戶；凱基 `kgiapp` 接口留好未接）；排程 18:40 引擎開著就接手；頁面四分頁：引擎／預測（1～12 個月主動報酬期望、95% 區間、贏 0050 機率、預期帶對實際）／觀察（停損監看、事件、委託）／手動指令 |
| [Iteration-57.md](./Iterations/Iteration-57.md) | **「程式交易」頁**：候選月清單 × 使用者持股與可投入現金 → 先賣後買的下單指令（`lib/tradingPlan.js` 純函式：策略範圍、最小下單、現金不夠縮單、偏離前後）、勾選登記進台帳（note `[程式交易] 清單 日期`）、按清單分批的執行紀錄；`GET /trading/plan`、`/trading/log`；meeting_front_end 同步 |
| [Iteration-56.md](./Iterations/Iteration-56.md) | 月調倉頁分頁「買多少股」：輸入金額依最近清單權重與最新收盤換算零股股數（先留手續費再取整、零股最低費、剩餘現金、張＋零股）；清單 API 多 `price`／`price_date`；pytest 200、vite-build、jest-unit 36 通過 |
| [Iteration-55.md](./Iterations/Iteration-55.md) | **Claude Code harness 七層就位**（CLAUDE.md、rules、skills `/iterate` `/experiment` `/handoff`、agents evidence-reviewer／strategy-critic／test-runner、deny 與 hooks、`progress.md` 交接筆記、`record_check.js` 驗證紀錄）；儀表板新頁「工作進度」（`/progress`：階段路線圖、交接、驗證、七層、hook 活動、迭代、提交） |
| [Iteration-54.md](./Iterations/Iteration-54.md) | **階段 4 紙上交易**：模擬帳戶三張表（migration 025，不混 user_trades）、2026-10-09 開戶 100 萬零股；每日 18:40 `job_portfolio_paper` 成交／結算／訊號日算清單（可補跑）；`/portfolio/paper` 與月調倉頁「紙上交易」卡（對 0050、逐月對回測預期）；第一份清單 10/13 算、10/14 成交 |
| [Iteration-53.md](./Iterations/Iteration-53.md) | 第二批策略家族（N 45~66）：營收加速、連續成長、低波動、52 週高點、反轉、異常成交量；**跨段一致的只有「動能＋營收類＋持台積電」**（rev_accel+mom 11.1%/8.5%、win3+mom+rev_streak 9.9%/15.2%），單獨基本面與反轉不行，52 週高點是期間效應；候選不換 |
| [Iteration-52.md](./Iterations/Iteration-52.md) | 月調倉頁頁首「現在該買哪些」（候選算到最近訊號日的 21 檔目標持股，migration 023，保留期績效不算不存）；**分析頁免登入**：erucMoney 路由分公開讀取／個人／管理三種（`optionalAuth`、`readPublic`、`requireUser`），行事曆代理匿名只轉非個人 GET，前端 /stock 離開受保護路由、持股與閒置資金標 🔒 |
| [Iteration-51.md](./Iterations/Iteration-51.md) | 打敗大盤：候選三列標記 `candidate`、淨值曲線補存（migration 022，`--attach-series` 重算與日誌一字不差）；FastAPI `/portfolio/*` → Node 代理 → 新頁「月調倉」（候選對門檻、淨值對 0050、逐年、最後持股、實驗日誌）；meeting_front_end 同步 |
| [Iteration-50.md](./Iterations/Iteration-50.md) | **打敗大盤：44 次實驗的網格搜尋**（分批輪動、緩衝、股票池、動能／組合訊號、成交金額權重、台積電權重滾動迴歸估計）；轉折是**固定持有台積電**（追蹤誤差 20%→12%）；候選 `win3+mom-t3-tsmcest` 開發期 +8.6%、驗證期 +15.7%（IR 1.09）、全期間 +7.1%／年七年六正，**但 DSR 0.13**——下一步是紙上交易與保留期，不是再搜 |
| [Iteration-49.md](./Iterations/Iteration-49.md) | **打敗大盤階段 2**：月調倉回測引擎（股票池、sue／ar0／win 三訊號、成本、未成交、DSR、實驗日誌 migration 021）；前四次實驗**都沒打敗 0050**（換手 13~20 倍、成本吃 5~8%）；**發現公告日早一個月的 bug**（鉅亨／MOPS 來源寫到所屬月列，配到上一期營收）已修並搬正 11,442 列，第 39／47 結論待重跑 |
| [Iteration-48.md](./Iterations/Iteration-48.md) | **打敗大盤計畫階段 1**：全市場股票池 `market_universe`（2,621 檔，含 112 檔 2018 後下市）、日線 `market_daily_prices`（migration 020；FinMind 逐檔或交易所檔兩條路線）、除權息／減資從交易所表、批次還原價、含息大盤 `TAIEX_TR`、`job_market_daily` 18:30、`--check` 七項檢查；月營收改抓 MOPS 彙總表 480 頁補齊全市場 2016-10 起（公告日精確度仍未解） |
| [Iteration-47.md](./Iterations/Iteration-47.md) | **新聞訊號模型**（依「新聞與股價關聯性」方案）：六個維度成為面板區塊 news／event、三個模型（事件波動通過、營收漂移與語調未通過）、五道關卡進訓練腳本與前端關卡表、20:10 台帳、新頁「新聞訊號」與週預測三欄 |
| [Iteration-46.md](./Iterations/Iteration-46.md) | **修跳空模型線上時序**：夜盤特徵改用次一交易日那一場、夜盤未收就不預測；06:20 排程專跑跳空；台帳 `invalid_reason`（migration 019）作廢 8/7~9/22 的 256 筆；稽核加對齊自檢；MoneyScheduler 註冊成常駐工作（之前從未常駐，七週只有 9 天有預測） |
| [Iteration-45.md](./Iterations/Iteration-45.md) | 固定自動測試腳本（非模型部分，第 1～4 期）：股票 API Jest 130 項、爬蟲 pytest 124 項、Stock_test／Stock_crawler_test 測試庫、CI |
| [Iteration-44.md](./Iterations/Iteration-44.md) | 股票功能全部併進行事曆平台（方案 9）；整套平台共用一種 admin |
| [Iteration-43.md](./Iterations/Iteration-43.md) | 併入行事曆平台（Node.js 版 meeting_front_end／meeting_API_Server）：股票分頁、`/api/stock/*` 唯讀代理、**單一登入**（共用 JWT 密鑰、`users.external_id` 自動對應、登入先問行事曆、`#token=` 交接） |
| [Iteration-42.md](./Iterations/Iteration-42.md) | 部署準備 erucmoney.com：GitHub Pages 工作流程與 CNAME、前端依網域選 API、Server dotenv／helmet／rate-limit／CORS 白名單、Cloudflare Tunnel 與 Node API 常駐腳本、`Deploy/README.md` 八步驟清單 |
| [Iteration-41.md](./Iterations/Iteration-41.md) | 多使用者階段 1：`users` 表 + JWT 登入 + 持股／交易／台帳按 `user_id` 隔離；所有 API 要登入、管理端點要 admin；前端登入頁與帳號管理頁；本機驗證通過 |
| [Iteration-40.md](./Iterations/Iteration-40.md) | 新聞 + 股價 → 走勢：28 個論文模型（Ding CNN、HAN、StockNet、Transformer、FinBERT 路線、AZFinText、樹融合、消融）× 4 標籤（y1/y3/y5/波動）季度走查；**隔日方向 AUC 全部 0.50～0.53、純價格 0.524、新聞內容單獨 0.50**；波動 AUC 0.65 來自價格叢聚。結果 `NewsModels*.md`，程式 `NewsModels/` |
| [Iteration-39.md](./Iterations/Iteration-39.md) | 新聞訊號研究方案階段 1 與 3：月營收事件研究（公布時點多來源合成、SUE 五分組 CAR、日曆時間 t、漲跌停、增量迴歸；23 檔不顯著 → 擴到 159 檔研究股 `research_daily_prices`）、MOPS 重大訊息 22 類規則分類事件研究（波動訊號、無漂移）；兩個修正：0050 不能當基準（改等權）、同股連續公告視窗重疊。結果見 `RevenueEventStudy*.md`、`MopsEventStudy.md` |

## 使用者文件（../UserDoc/）

| 文件 | 說明 |
|------|------|
| [Spec.md](../UserDoc/Spec.md) | 需求規格（15 項主需求 + API 端點對照） |
| [request.md](../UserDoc/request.md) | 三模型加權投票決策系統規格 |
| [Target.md](../UserDoc/Target.md) | 20 檔測試股票清單（電子股 20~40 元） |
| [LSTM.md](../UserDoc/LSTM.md) | LSTM 股票預測模型技術文件 |
