---
name: progress
description: 在 Claude Code 這一側看目前 Claude 在這個 repo 的工作與進度：任務、下一步、階段、24 小時內各 session 在做什麼、驗證結果、最近迭代與提交、未解。使用者說「進度」「現在在做什麼」「/progress」時用；不改任何檔案。
---

補充（例如 `--events 20` 要多看幾筆 hook 事件）：$ARGUMENTS

1. 跑 `node AI/harness/progress_report.js $ARGUMENTS`（只讀 progress.md、AI/progress/checks.json、AI/progress/events.jsonl、迭代紀錄與 git）。
2. 把輸出**原樣**放進一個程式碼區塊給使用者，不要改寫、不要省略段落。
3. 區塊下面最多三句話：哪個 session 是現在這個、有沒有過期的檢查（檢查時間早於相關檔案）、未解裡最該先處理的一條。
4. 使用者要「另外的畫面」時：`node AI/harness/progress_ui.js` 開獨立視窗（http://localhost:3010，每 5 秒更新，顯示各 session 與正在跑的子代理）；本 session 自己的背景 subagent 用內建 `/tasks`；網頁版在管理模式「工程 → 工作進度」（需 admin）。
