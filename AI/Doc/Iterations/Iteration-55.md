# Iteration 55 — Claude Code harness 七層就位，儀表板多一頁「工作進度」把交接、驗證、活動攤開來看

**日期：** 2026-10-09
**依據：** 使用者：「依照這文章進一步優化，並要一個相對完整可視的工作進度的圖形介面」——兩篇文章：@beamnxw《Make Opus 5.5 Finish Long Tasks: A Reusable Harness Engineering Setup》（七層）、@eng_khairallah1《How to Build Your First Team of AI Agents Using Claude Opus 5.5》（orchestrator／specialist／critic、最小權限、審查上限、不提早結束回合）。
**規則：** 真相來源留在 repo（`progress.md`、`checks.json`、`events.jsonl`），儀表板只讀不寫；證據檔由腳本產生、deny 掉手改；不碰正式庫、不 commit。

## 一、做了什麼

### Harness（`AI/harness/README.md` 有對照表）

| 層 | 檔案 | 內容 |
|---|---|---|
| 1 事實 | `CLAUDE.md`、`.claude/rules/{migrations,portfolio,iterations}.md` | 跨任務事實（子系統、輸出位置、慣例、完成的定義、effort、無人看管時不提早結束）；路徑規則只在碰到 migration／月調倉／迭代紀錄時載入 |
| 2 流程 | `.claude/skills/iterate`、`experiment`、`handoff` | 每一步要有看得到的產出；`/experiment` 要求事前寫假設、不重搜、驗證期只跑一次 |
| 3 來源 | 既有 `AI/Doc/README.md`、`AI/UserDoc/` | 沒接 MCP，來源都在 repo |
| 4 規則 | `.claude/settings.json` | deny：`.env`、`.env.*`（用 `!` 例外留 `.env.example`、`Server/.env.test`，實測可讀）、`Server/.jwt_secret`、實驗結果檔與 `checks.json`／`events.jsonl` 的 Edit／Write；env：`PYTHONUTF8=1`、子代理深度 1、同時 4 個；hooks：SessionStart／UserPromptSubmit／PostToolUse／PostToolUseFailure／PermissionDenied／SubagentStop／Stop 都呼叫 `hook_log.js` |
| 5 審查 | `.claude/agents/evidence-reviewer`（高）、`strategy-critic`（高）、`test-runner`（低） | 只讀不改；回「主張／判定／來源／修正」表或 PASS／FAIL 清單；最多三輪 |
| 6 effort | agent frontmatter `effort:` | 主 session 預設，審查 high，跑測試 low |
| 7 完成 | `progress.md` ＋ `AI/progress/checks.json` | 完成 = 產出路徑存在 ＋ checks.json 有結果 ＋ progress.md 更新 |

兩支腳本：`AI/harness/hook_log.js`（hook JSON → `events.jsonl` 一行，永遠 exit 0、5 MB 輪替）、`AI/harness/record_check.js`（跑指令或記判定 → `checks.json`，同名覆蓋）。
`AI/progress/events.jsonl`、`checks.json` 進 `.gitignore`（機器上的執行紀錄）；`progress.md` 進版控。

### 工作進度頁

- `Server/routes/progress.js`：`GET /progress`（admin）。解析 `progress.md` 七段（`## 任務／產出／已完成／決策／未解／下一步／階段`，階段 `- [x]`／`- [~]`／`- [ ]`）、讀 `checks.json`、`events.jsonl`（壞行略過、最後 120 筆、連續日期窗每日筆數、10 分鐘內有事件 = 正在工作）、`AI/Doc/Iterations/*.md` 的標題與日期、`git log -15` 與 `git status --porcelain`、七層是否就位。
  `PROGRESS_ROOT` 可指到別的目錄（測試用暫存目錄）。
- `Screen/src/pages/WorkProgress.jsx`：頂列六格（階段、最近迭代、驗證、未解、工作區、本次重讀）、階段路線圖、交接筆記（下一步置頂）、驗證結果（點開看最後 30 行）、Harness 七層、活動（每日柱狀圖＋事件列，失敗的標紅）、迭代紀錄、最近提交。每 30 秒重讀。
- 兩個小坑：`git status --porcelain` 的輸出不能 `.trim()`（第一行的狀態欄會被吃掉一個字）；只有一天有事件時單根柱子會填滿整張圖，所以每日筆數補成連續日期窗（起點 = min(最早事件日, 13 天前)，最多 30 天）。

## 二、結果

| 檢查 | 結果 | 來源 |
|---|---|---|
| `Server` jest | 161 項通過（14 套，含新的 `progress.test.js` 9 項） | `AI/progress/checks.json`（name=jest） |
| `Crawler` pytest | 199 項通過 | `checks.json`（name=pytest） |
| `Screen` vite build | 通過 | `checks.json`（name=vite-build） |
| hooks 實際生效 | 本 session 寫入 `events.jsonl` 的 PostToolUse／UserPromptSubmit／Stop／PostToolUseFailure／SubagentStop 事件在頁面活動列看得到 | `AI/progress/events.jsonl` |
| 頁面 | 本機 Vite ＋ 不帶登入的 `/progress` 預覽（:3003，只掛路由、不跑 `init()`）看過全頁 | `events.jsonl` 2026-10-09T05:30～05:33 的 navigate／screenshot 事件 |

## 三、讀法

1. 文章的七層在這個專案裡原本一層都沒有（沒有 CLAUDE.md、skills、agents、hooks），但「迭代紀錄」和「實驗日誌 N 只增不減」其實已經在做第 7 層的事；這一輪是把它們接上明確的完成條件與審查。
2. 最有用的不是文件，是兩個機制：**證據只能由腳本產生**（deny 掉 Edit／Write）、**完成條件看檔案不看對話**（頁面只讀 repo）。
3. 另一個 session 同時在做 Iteration 54，commit `21e1ea2` 把這一輪前半段的檔案一起收進去了——同一工作區同時兩個 session 要先分工到不同目錄，記在 `progress.md` 未解。
4. 還沒驗的：`PermissionDenied` 的實際欄位（`PostToolUseFailure` 已記到 `reason`；`SubagentStop` 已記到，但 `summary` 只有 agent id、沒有名稱）；`/goal` 流程沒有真的跑過一輪（`AI/harness/README.md` 有範本）。
5. 這份紀錄交 evidence-reviewer 審過一輪：39 條主張 33 verified、1 incorrect（就是上一點，已修）、5 unresolved（4 條是它看不到 git 或 repo 外來源，主 session 用 `git show --stat 21e1ea2` 確認過；1 條是 deny 清單裡 `!` 例外是否生效——主 session 實測 Read `.env.example` 可讀，`.env` 被擋）。

## 變更檔案

新增：`CLAUDE.md`、`progress.md`、`.claude/settings.json`、`.claude/rules/{migrations,portfolio,iterations}.md`、`.claude/skills/{iterate,experiment,handoff}/SKILL.md`、`.claude/agents/{evidence-reviewer,strategy-critic,test-runner}.md`、`AI/harness/README.md`、`Screen/src/pages/WorkProgress.jsx`。
修改（相對 21e1ea2）：`AI/harness/hook_log.js`、`Server/routes/progress.js`、`Server/tests/http/progress.test.js`、`Screen/src/App.jsx`、`Screen/src/components/Sidebar.jsx`、`Screen/src/services/api.js`、`AI/Doc/README.md`、`Server/README.md`。
（`AI/harness/record_check.js`、`Server/app.js` 的 `/progress` 掛載、`.gitignore` 已在 21e1ea2 裡。）
