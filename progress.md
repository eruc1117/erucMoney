# 交接筆記

**更新：** 2026-10-09
（格式見 `.claude/rules/iterations.md`；儀表板「工作進度」頁讀這個檔。只寫有證據的事。）

## 任務
Iteration 61：交易模擬的條件規則（條件 → 觸發買賣）——未提交。引擎已啟動（紙上、停損 0、限價 ±2%），等今晚 18:40 排程第一次真的跑、10/13 第一份清單

## 產出
- Crawler/trading_strategy.py、tests/test_trading_strategy.py（3 項）、rules_anon_evidence.py；api.py `POST /trading/sim/rules`；Server/routes/sim.js `/sim/rules`、sim.test.js（7 項）
- Screen/src/components/RuleBuilder.jsx、TradingSim.jsx（條件規則／日期指令／進階三種模式）、api.js runRules；meeting_front_end 同步
- AI/Doc/Iterations/Iteration-61.md、AI/Doc/README.md、Server/README.md
（以下為 60，已提交）
- Crawler/trading_sim.py、Crawler/tests/test_trading_sim.py（3 項）、Crawler/sim_anon_evidence.py；Crawler/api.py `POST /trading/sim`
- Server/routes/sim.js（公開，掛 /sim）、Server/tests/http/sim.test.js（6 項）、Server/app.js、fastapi-mock
- Screen/src/components/ReplayPanel.jsx（從 AlgoTrading 抽出）、Screen/src/pages/TradingSim.jsx（側欄「交易模擬」）、api.js、App.jsx、Sidebar.jsx；meeting_front_end 同一份＋ nav.js「預測」群組 simulate（匿名）
- AI/Doc/Iterations/Iteration-60.md、AI/Doc/README.md、Server/README.md
（以下為 58／59，已提交）
- Crawler/trading_engine.py、Crawler/brokers/{__init__,base,paper,kgi}.py、Crawler/tests/test_trading_engine.py（5 項）、Server/migrations/026_trading_engine.sql
- Crawler/api.py（/trading/engine/*）、Crawler/scheduler.py（引擎開著就接手 18:40）、Crawler/tests/helpers/db_setup.py
- Server/routes/trading.js（引擎代理）、Server/tests/http/trading.test.js（8 項）、Server/tests/helpers/fastapi-mock.js、Server/tests/db/migrations.test.js（26）
- Screen/src/pages/AlgoTrading.jsx（四分頁）、Screen/src/services/api.js、Screen/src/App.jsx；../meeting_front_end/src/stock/{pages/AlgoTrading.jsx, services/api.js, nav.js}
- Crawler/trading_rules.py（純函式，引擎與回放共用）、Crawler/trading_replay.py、tests/test_trading_rules.py（5）、tests/test_trading_replay.py（2）；api.py `/trading/engine/replay`、Node 代理、頁面「歷史模擬」分頁
- AI/Doc/Iterations/Iteration-58.md、Iteration-59.md、AI/Doc/README.md、Server/README.md；Iteration-57.md 審查後改測試項數

## 已完成
- 階段 1～3（48～53）：候選 #44，N = 66
- 階段 4 紙上交易（54）：2026-10-09 開戶 100 萬；第一份清單 10/13 算、10/14 成交
- harness 與工作進度頁（55）、買多少股分頁（56）、程式交易手動指令（57，a4eac0f／meeting_front_end d4566c3）
- 程式交易引擎（58）與回放（59）已提交 7e5ad6f；交易模擬（60）：pytest 215、jest 183（17 套）、vite build、meeting_front_end build 都通過；MoneyApi／MoneyCrawlerApi 已重啟，匿名 `POST /sim/run` 與 `GET /sim/replay` 實測可用（checks.json sim-anon）
- 回放結論（候選期間 2018-11～2024-09，還原價）：照單全收 +346%（0050 +189%、年化主動 +7.89%，與回測 +7.05% 接近）；停損 15% 的引擎 +228%（185 次停損）、25% +256%、35% +277%、不停損但限價 ±0.5% +304%、±2% +334%；七組都在 checks.json（replay-*）

## 決策
- 2026-10-09：候選不換；不再搜參數；新資料（紙上交易、保留期）才是下一步
- 2026-10-09：程式交易分兩層——引擎（規則、委託、事件）與券商（紙上先跑，凱基 `kgiapp` 接口留好）；live 沒設好券商就停下來記錯誤，不送單
- 2026-10-09：引擎**不自動開**。開了之後紙上交易的規則從「次日開盤照單全收」變成「限價＋停損」，和回測（無停損）的對照會變——開不開、要不要第二本模擬帳戶，由使用者決定
- 2026-10-09：預測用候選回測的年化主動報酬與追蹤誤差推常態區間；caveat 寫在回應裡（DSR 0.13）
- 2026-10-09：回放只在候選期間（清單來自 portfolio_positions run 44），保留期不開；回放結果不寫 portfolio_runs（不是新實驗，不算 N）
- 2026-10-09：使用者決定**啟動引擎（紙上）**，規則改成停損 0（關閉）、限價 ±2%——依回放結果；RULES_DEFAULT 程式預設仍是 15%／0.5%，實際生效的是 trading_engine_state.rules

## 未解
- Iteration 61 未提交（本 repo 與 meeting_front_end）；pytest 218、jest 184、兩個 build、匿名 rules-anon 都過
- 條件規則沒做：AND／OR 組合、對 0050 的相對強弱、成交量條件、部位比例動作、規則送進引擎實際執行
- 引擎第一次 run_daily（2026-10-09 15:42）因當天日線未進而略過；要看 18:40 之後 trading_events 有沒有 signal／orders（10/13 訊號日才會有清單）
- 開了引擎之後，紙上交易的成交方式從「照單全收」變成「限價 ±2%」，和回測的對照會差約 0.5%／年（回放估）
- 公開模擬沒做：匯入 CSV、盤後零股集合競價模型、分享連結、多次模擬比較
- 凱基：`kgiapp` 要先申請、填 KGI_* 環境變數、實作 `brokers/kgi.py execute` 與成交回報對帳
- 沒做：第二本模擬帳戶（無停損對照）、live 成交回報、盤中即時價、假日表
- 月營收公告日精確度、0050 真實持股權重表、保留期未開（只能開一次）
- 同一工作區兩個 session 會互相 commit 到對方檔案、覆寫 progress.md——同時開要先分工目錄

## 下一步
10/13 收盤後（18:40 排程）看「程式交易 → 觀察」：應有 signal 事件、約 21 張調倉委託；10/14 開盤成交後看 fill 事件與模擬帳戶持股

## 階段
- [x] 階段 1 全市場股票池與日線、含息大盤
- [x] 階段 2 月調倉回測引擎與實驗日誌（DSR）
- [x] 階段 3 訊號搜尋與候選（N = 66，候選 #44）
- [~] 階段 4 紙上交易：模擬帳戶已開（2026-10-09），每日 18:40 結算，等每月清單累積
- [~] 階段 5 程式交易：引擎已啟動（紙上，停損 0、限價 ±2%），等 10/13 第一份清單；凱基未接
- [ ] 階段 6 保留期一次判定（使用者決定何時開）
