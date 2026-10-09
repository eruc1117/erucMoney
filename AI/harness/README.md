# Claude Code harness（2026-10-09）

依兩篇文章組起來的工作環境：@beamnxw「Make Opus 5.5 Finish Long Tasks: A Reusable Harness Engineering Setup」的七層，
加 @eng_khairallah1「How to Build Your First Team of AI Agents」的三個角色（orchestrator／specialist／critic）、最小權限、審查上限三輪、不提早結束回合。

| 層 | 檔案 | 做什麼 |
|---|---|---|
| 1 工作區事實 | `CLAUDE.md`、`.claude/rules/*.md` | 跨任務的事實；路徑規則只在碰到對應檔案時載入 |
| 2 重複流程 | `.claude/skills/iterate`、`experiment`、`handoff`、`progress` | `/iterate 題目`、`/experiment 假設`、`/handoff`、`/progress`（在 Claude 這一側看進度） |
| 3 來源存取 | `AI/Doc/README.md`、`AI/UserDoc/` | 本專案的來源都在 repo 裡，沒有接 MCP |
| 4 行動規則 | `.claude/settings.json` | deny：`.env`、`Server/.jwt_secret`、實驗結果檔、`checks.json`／`events.jsonl` 不手改；env：`PYTHONUTF8`、子代理深度 1、同時 4 個；hooks：七種事件都呼叫 `hook_log.js` |
| 5 審查者回證據 | `.claude/agents/evidence-reviewer.md`、`strategy-critic.md`、`test-runner.md` | 只讀不改；回表格或 PASS／FAIL 清單；effort high／high／low |
| 6 effort | agent frontmatter | 主 session 預設；審查 high；跑測試 low |
| 7 完成條件 | `progress.md`、`AI/progress/checks.json` | 完成 = 產出路徑存在 ＋ checks.json 有結果 ＋ progress.md 更新 |

## 兩支腳本

- `hook_log.js`：hook 事件 → `AI/progress/events.jsonl`（一行一事件，5 MB 輪替）。永遠 exit 0，不印 stdout。
- `record_check.js`：跑指令並把結果（exit code、最後 30 行）寫進 `AI/progress/checks.json`；或直接記一個判定（`--status pass|fail|skip --summary`）。
- `progress_report.js`：把 progress.md、checks.json、events.jsonl（24 小時內各 session 在做什麼）、迭代與 git 印成一頁文字；`/progress` skill 跑它，`--events N` 多印事件。網頁版是 `Server/routes/progress.js`。

```
node AI/harness/record_check.js --name jest --cwd Server -- npm test
node AI/harness/record_check.js --name pytest --cwd Crawler -- python -m pytest -q
node AI/harness/record_check.js --name vite-build --cwd Screen -- npm run build
node AI/harness/record_check.js --name evidence-reviewer --status pass --summary "12 條 verified"
```

## 看進度

儀表板側欄「工作進度」（admin）：`Server/routes/progress.js` 把 `progress.md`、`checks.json`、`events.jsonl`、`AI/Doc/Iterations/`、git log 整理成一個 JSON，
`Screen/src/pages/WorkProgress.jsx` 畫：階段路線圖、交接筆記、驗證結果、harness 七層、活動時間軸、迭代紀錄、最近提交。每 30 秒重讀。

`AI/progress/events.jsonl` 與 `checks.json` 在 `.gitignore`（機器上的執行紀錄）；`progress.md` 進版控（交接筆記）。

## 一次完整的跑法

1. `claude` 進 repo 根目錄；`/context` 看 CLAUDE.md 有沒有載入，`/agents` 看三個審查者在不在，`/permissions` 看 deny 規則。
2. `/goal 用 /iterate 做 <題目>。完成條件：Iteration-NN.md 與變更檔案存在、checks.json 裡 jest／pytest 通過、evidence-reviewer 沒有 incorrect、progress.md 已更新、回報列出輸出路徑與驗證結果。12 回合未達成就停下報告阻礙。`
3. 跑完開儀表板「工作進度」對照：驗證表、未解、下一步。
4. 新 session 貼「讀 progress.md 並從『下一步』繼續」——它應該接得上；接不上就是筆記缺了路徑或決策。
