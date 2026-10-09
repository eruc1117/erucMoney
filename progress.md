# 交接筆記

**更新：** 2026-10-09
（格式見 `.claude/rules/iterations.md`；儀表板「工作進度」頁讀這個檔。只寫有證據的事。）

## 任務
Iteration 55：Claude Code harness（七層）與儀表板「工作進度」頁；Iteration 56（另一個 session）：月調倉頁分頁「買多少股」。紙上交易（Iteration 54）已提交（21e1ea2、8f5b223）

## 產出
- CLAUDE.md、.claude/settings.json（deny／env／hooks）、.claude/rules/{migrations,portfolio,iterations}.md
- .claude/skills/{iterate,experiment,handoff}/SKILL.md、.claude/agents/{evidence-reviewer,strategy-critic,test-runner}.md
- AI/harness/hook_log.js、AI/harness/record_check.js、AI/harness/README.md
- Server/routes/progress.js（`GET /progress`，admin）、Server/tests/http/progress.test.js（9 項）
- Screen/src/pages/WorkProgress.jsx（側欄「工作進度」）、Screen/src/services/api.js `getProgress`
- AI/Doc/Iterations/Iteration-55.md、AI/Doc/README.md 索引列、Server/README.md 測試對照列
- Iteration 56：Crawler/portfolio_api.py（清單帶 price／price_date）、Screen 與 meeting_front_end 的 PortfolioLab.jsx（分頁「總覽／買多少股」）、Crawler/tests/test_portfolio_paper.py +1、Crawler/live_list_evidence.py、AI/Doc/Iterations/Iteration-56.md、README 索引列

## 已完成
- 階段 1～3：全市場股票池與日線（Iteration 48）、回測引擎與實驗日誌（49）、網格搜尋與第二批家族（50、53），N = 66
- 候選 #44 `win3+mom-t3-tsmcest`：開發期 +8.6%、驗證期 +15.7%（IR 1.09）、DSR 0.13（Iteration 50 結果檔）
- 階段 4 紙上交易（Iteration 54，已提交）：模擬帳戶 migration 025、每日 18:40 `job_portfolio_paper`、`/portfolio/paper`、月調倉頁紙上交易卡；2026-10-09 開戶 100 萬
- harness：hooks 已在本 session 實際寫入 `AI/progress/events.jsonl`（PostToolUse／UserPromptSubmit 都有收到）；checks.json 有 jest 161 項、pytest 199 項、vite-build 三項通過（2026-10-09）
- 工作進度頁已在本機（Vite :5173 ＋ 不帶登入的預覽 :3003）看過：階段路線圖、交接筆記、驗證表、七層、活動圖與事件列、迭代與提交
- Iteration 56「買多少股」：輸入金額依最近清單權重與最新收盤算零股股數；checks.json 2026-10-09：pytest 200、vite-build、jest-unit 36、smoke-portfolio、live-list 通過；evidence-reviewer 第一輪 31 verified／1 incorrect（已改）／7 unresolved（已補證據），第二輪見 checks.json `evidence-reviewer-56`

## 決策
- 2026-10-07：零股、FinMind 免費配額（實測不夠，全市場改走交易所／MOPS 官方檔）、資料從 2018 起
- 2026-10-09：候選不換（Iteration 53 的跨段一致家族差距在雜訊內；換了就是用驗證期挑）
- 2026-10-09：不再在開發期搜參數；新資料（紙上交易、保留期）才是下一步
- 2026-10-09：工作進度頁只讀 `progress.md`／`checks.json`／`events.jsonl`，不提供編輯——真相來源留在 repo，儀表板不會和工作區各說各話
- 2026-10-09：`checks.json`、`events.jsonl`、`UnifiedModel/results/portfolio_*.md` 用 deny 規則擋住 Edit／Write，只能由腳本產生（證據不手改）

## 未解
- `/progress` 要等常駐工作 `MoneyApi` 重啟才會生效（migration 025 也是）；前端要 push 後 GitHub Pages 才有「工作進度」頁
- hooks 的 `PermissionDenied` 實際欄位還沒在真實 session 看到（PostToolUse、UserPromptSubmit、Stop、PostToolUseFailure、SubagentStop 都已記到；SubagentStop 只有 agent id 沒名稱）
- 月營收公告日精確度（Iteration 39／49）仍未解；0050 真實持股權重表未補
- 保留期（2024-10 起）未開，只能開一次
- 同一時間有兩個 Claude session 在同一工作區工作，commit 會把對方未完成的檔案一起收進去（21e1ea2 收進了 harness 前半段）——之後同時開兩個 session 時先分工到不同目錄
- Iteration 56 未 commit（與 55 共用工作區；App.jsx／Sidebar.jsx／api.js 的 M 是 55 的）；FastAPI `MoneyCrawlerApi` 要重啟清單才會帶價格；meeting_front_end 的 PortfolioLab.jsx 也還沒 commit／push
- 「買多少股」只算買進；換月的「賣多少」要知道實際持股才算得出，未做

## 下一步
使用者重啟 `MoneyApi`、`MoneyCrawlerApi`、`MoneyScheduler` 後，開儀表板「工作進度」確認 `/progress` 回 200，再把 Iteration 55 與 56 一起 commit（money 與 meeting_front_end 各一次）並 push

## 階段
- [x] 階段 1 全市場股票池與日線、含息大盤
- [x] 階段 2 月調倉回測引擎與實驗日誌（DSR）
- [x] 階段 3 訊號搜尋與候選（N = 66，候選 #44）
- [~] 階段 4 紙上交易：模擬帳戶已開（2026-10-09），每日 18:40 結算，等每月 11 日清單累積
- [ ] 階段 5 保留期一次判定（使用者決定何時開）
- [ ] 階段 6 實單（零股）
