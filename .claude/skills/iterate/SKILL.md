---
name: iterate
description: 跑一輪完整的「Iteration」：從 progress.md 接手、實作、用 record_check 跑測試、交給 evidence-reviewer 查證、寫 Iteration-NN.md 與 README 索引、更新 progress.md、回報輸出路徑與驗證結果。使用者說「下一輪」「繼續迭代」「做 Iteration」或交付一個會改程式碼的功能時用。
---

要做的題目：$ARGUMENTS

每一步都要留下**看得到的產出**；沒有產出的步驟等於沒做。

1. **接手**：讀 `progress.md` 與它列出的產出檔；看 `git status --short` 知道工作區有什麼沒提交。
   若題目和筆記的「下一步」不同，先把筆記的任務收尾或在筆記的「未解」記下來，再開始新題目。
2. **定完成條件**：用一句話寫出這一輪結束時要存在的檔案與要通過的檢查（放進回報的開頭）。
   題目若涉及回測實驗，改用 `/experiment`，不要在這裡跑。
3. **實作**：改程式碼。schema 改動走 `Server/migrations/`（見 rules）。前端改完 `cd Screen && npm run build`。
4. **驗證**（結果會進 `AI/progress/checks.json`，儀表板看得到）：
   - `node AI/harness/record_check.js --name jest --cwd Server -- npm test`（只動 Crawler 可改跑 `--name jest-unit -- npm run test:unit`）
   - `node AI/harness/record_check.js --name pytest --cwd Crawler -- python -m pytest -q`
   - 前端：`node AI/harness/record_check.js --name vite-build --cwd Screen -- npm run build`
   測試輸出很長時交給 `test-runner` subagent 跑並回報失敗清單。
5. **寫迭代紀錄**：`AI/Doc/Iterations/Iteration-NN.md`（格式見 `.claude/rules/iterations.md`），`AI/Doc/README.md` 迭代表最上面加一列。
6. **審查**：請 `evidence-reviewer` 讀迭代紀錄，給它：紀錄路徑、本輪變更檔案清單、結果檔或資料表位置。
   它回「主張／判定／來源／修正」表。`incorrect` 的改紀錄或改程式碼；`unresolved` 的在紀錄裡標「待確認」。
   審查結果用 `node AI/harness/record_check.js --name evidence-reviewer --status pass|fail --summary "…"` 記下。最多三輪。
7. **交接**：更新 `progress.md`（任務／產出／已完成／決策／未解／下一步／階段）。
8. **回報**：輸出路徑、`checks.json` 裡每項檢查的結果、審查表裡 incorrect／unresolved 的數量、要使用者做的事（重啟常駐工作、commit）。

不要以「接下來我會…」結束回合；做到第 8 步才算完。
