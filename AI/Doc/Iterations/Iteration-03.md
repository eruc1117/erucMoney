# Iteration 3 — 文件同步

**日期：** 2026-08-06

## 問題

程式碼演進速度超前文件，多處文件記載與實況不符：

| 文件 | 落差 |
|------|------|
| `AI/Doc/README.md` | 索引僅列 3 份文件，實際有 8 份 + 迭代紀錄 |
| `AI/UserDoc/Spec.md` | 缺投票系統（request.md 已實作大半）；`GET /model/predict` 標「Stub」但實際已 proxy 至 LSTM :8001；API 表缺 4 個 /voting 端點 |
| `AI/Doc/Bugs/bugs.md` | 缺 Iteration 1/2 修正的資料問題紀錄 |

## 修正內容

1. **README.md**：重寫索引，涵蓋系統文件 6 份、迭代紀錄 4 份、使用者文件 4 份
2. **Spec.md**：
   - 新增需求 16（三模型投票系統，指向 request.md，標註排程自動投票待實作）
   - `GET /model/predict` 狀態 Stub → ✅（proxy → LSTM serve.py :8001，已驗證於 Iteration 2）
   - API 表新增 `GET /voting`、`GET /voting/:stock_id`、`POST /voting/run`、`GET /voting/status`（與 `Server/routes/voting.js`、`model.js` 逐一核對）
   - 最後更新日期 2026-03-16 → 2026-08-06
3. **bugs.md**：新增 DATA-001（stock_info 不完整）、DATA-002（news_features 未落地）修復紀錄

## 尚未完成事項（誠實盤點，供未來迭代）

| 項目 | 出處 | 狀態 |
|------|------|------|
| 每日 20:00 自動投票排程 | request.md 第六節 | 未實作（僅手動觸發） |
| 每小時新聞爬蟲 + 特徵計算排程 | request.md 第六節 | 未實作（scheduler.py 只排股價爬蟲） |
| `POST /model/retrain` | Spec.md | Stub |
| IMPR-001 LSTM 準確率改進（IMP-001~006） | LSTM-Improvement.md | `train_improvements.py` 存在，成效未驗證 |
| 行情資料更新（最新 2026-03-23） | — | 需觸發爬蟲補近 4.5 個月資料，受 FinMind 匿名 30 次/h 限制 |
