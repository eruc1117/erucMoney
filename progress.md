# 交接筆記

**更新：** 2026-10-09
（格式見 `.claude/rules/iterations.md`；儀表板「工作進度」頁讀這個檔。只寫有證據的事。）

## 任務
Iteration 57：「程式交易」頁——候選月清單 × 使用者持股與現金 → 下單指令、登記、對帳（未提交）

## 產出
- Server/lib/tradingPlan.js、Server/routes/trading.js、Server/lib/proxy.js（fetchFastAPI）、Server/app.js（掛 /trading）
- Server/tests/unit/tradingPlan.test.js（7 項）、Server/tests/http/trading.test.js（7 項）、Server/tests/helpers/fastapi-mock.js（current_list）
- Screen/src/pages/AlgoTrading.jsx、Screen/src/services/api.js（getTradingPlan／getTradingLog）、App.jsx、Sidebar.jsx（🎯 程式交易）
- ../meeting_front_end/src/stock/{pages/AlgoTrading.jsx, nav.js, services/api.js}（另一個 repo，也未提交）
- AI/Doc/Iterations/Iteration-57.md、AI/Doc/README.md、Server/README.md

## 已完成
- 階段 1～3：股票池與日線（48）、回測引擎與日誌（49）、搜尋與家族（50、53），N = 66，候選 #44
- 階段 4 紙上交易（54，已提交 21e1ea2／8f5b223）：2026-10-09 開戶 100 萬；每日 18:40 結算；第一份清單 10/13 算、10/14 成交
- harness 七層與工作進度頁（55）、月調倉「買多少股」分頁（56）：已提交 14e3ef4
- 程式交易頁（57）：jest 175 項（16 套）、vite build、meeting_front_end `npm run build` 都通過；本機預覽以正式庫清單（2026-09-11、21 檔）與 30 萬現金算出 21 筆買單、偏離 50% → 0.6%

## 決策
- 2026-10-07：零股、FinMind 免費配額不夠改走交易所／MOPS 官方檔、資料從 2018 起
- 2026-10-09：候選不換；不再搜參數；新資料（紙上交易、保留期）才是下一步
- 2026-10-09：程式交易「只算不做」——沒有券商 API，指令由人下、執行後登記進台帳；程式只動策略範圍（清單 ∪ 台帳 note 以 `[程式交易]` 開頭的股票），使用者自己買的持股不動
- 2026-10-09：現金不夠買齊時從金額最大的買單縮股數，不透支；調整 < NT$1,000 不下單，退出清單例外

## 未解
- Iteration 57 未提交（本 repo 與 meeting_front_end 各一份）；`/trading` 要等 `MoneyApi` 重啟
- 程式交易沒做的：券商 API、成交回報自動對帳（人填成交價）、假日表（下一個訊號日只避週末）、限價單價格建議
- hooks 的 `PermissionDenied` 實際欄位仍未在真實 session 看到
- 月營收公告日精確度、0050 真實持股權重表、保留期未開（只能開一次）
- 同一工作區同時兩個 session 會把對方未完成的檔案一起 commit，也會互相覆寫 progress.md（21e1ea2、14e3ef4 都發生過）——同時開兩個 session 要先分工目錄

## 下一步
使用者重啟 `MoneyApi` 後登入開「程式交易」頁，用真實可投入金額產生指令、到券商下單、回來登記第一批（清單 2026-09-11 或等 10/13 的新清單）

## 階段
- [x] 階段 1 全市場股票池與日線、含息大盤
- [x] 階段 2 月調倉回測引擎與實驗日誌（DSR）
- [x] 階段 3 訊號搜尋與候選（N = 66，候選 #44）
- [~] 階段 4 紙上交易：模擬帳戶已開（2026-10-09），每日 18:40 結算，等每月清單累積
- [~] 階段 5 小額實單：程式交易頁（指令、登記、對帳）已做，等第一批真實下單
- [ ] 階段 6 保留期一次判定（使用者決定何時開）
