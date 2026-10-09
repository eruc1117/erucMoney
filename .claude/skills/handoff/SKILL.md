---
name: handoff
description: 把目前的工作狀態寫進 progress.md（任務／產出／已完成／決策／未解／下一步／階段），並確認 checks.json 與工作區一致。session 要結束、context 快滿、或使用者說「先記下來」「交接」時用。
---

補充說明：$ARGUMENTS

1. 看 `git status --short` 與 `git diff --stat`：工作區每個改動都要對應到筆記裡「產出」或「未解」的一項。
2. 看 `AI/progress/checks.json`：每項檢查的時間要晚於相關檔案的最後修改；過期的重跑（`record_check.js`）或在「未解」寫「X 測試未重跑」。
3. 更新 `progress.md`（格式見 `.claude/rules/iterations.md`）：
   - **任務**一句話；**產出**列路徑；**已完成**只列有證據的（檔案在、測試過）；
   - **決策**附日期與理由；**未解**寫缺什麼證據或被什麼擋住；
   - **下一步**只寫一個可以直接動手的步驟；**階段**用 `- [x]`／`- [~]`／`- [ ]`。
4. 回報：筆記路徑、未解的數量、下一步那一句。
