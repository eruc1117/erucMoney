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
| [Bugs/bugs.md](./Bugs/bugs.md) | Bug 紀錄與功能追加履歷 |

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
