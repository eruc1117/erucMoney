# Iteration 0 — Git Baseline 建立

**日期：** 2026-08-06
**Commit：** `d89c652`

## 目的

依使用者指示開始「依照 AI/ 文件內容進行修正的自我迭代流程」，每次迭代皆需 git 版控與說明文件。本迭代為基礎建設：將既有專案納入版本控制，作為後續所有修正的比較基準。

## 執行內容

1. `git init`（專案先前無版控）
2. 建立 `.gitignore`：排除 `node_modules/`、`venv/`、`__pycache__/`、LSTM/XGBoost 模型產出物（`saved_models/`、`results/`、`report/`）、除錯暫存檔（`crawl_debug.log`、`yahoo_raw.html`）
3. Baseline commit：102 個檔案，18,118 行
4. 建立本迭代文件目錄 `AI/Doc/Iterations/`

## 現況盤點（後續迭代依據）

對照 `AI/` 文件與實際程式碼、資料庫（PostgreSQL :5432/Stock）狀態：

| 項目 | 文件記載 | 實際狀態 | 落差 |
|------|----------|----------|------|
| 投票系統程式 | request.md 規格 | `model2_news.py`、`model3_chip.py`、`voting_engine.py`、`Server/routes/voting.js`、`VotingDashboard.jsx` 皆已存在 | 程式在但 `news_features` 0 筆、`voting_results` 僅 2 筆 → 管線疑似沒跑通 |
| stock_info | Target.md 定義 20 檔測試股 | 僅 4 筆，其中 `3330` 無名稱/市場/產業（不完整資料） | 缺 18 檔基本資料 |
| stock_daily_prices | — | 22 檔、25,736 筆，2021-03-02 ～ 2026-03-23 | 最新資料距今約 4.5 個月 |
| AI/Doc/README.md 索引 | 只列 3 份文件 | 實際有 8 份文件 | 索引過時 |
| IMPR-001（LSTM 準確率改進） | bugs.md 標記「待實作」 | `train_improvements.py` 存在，需確認 | 待驗證 |

## 迭代規劃

- **Iteration 1：** 修正 `stock_info` 資料完整性（補齊 20 檔、清 3330）
- **Iteration 2：** 跑通三模型投票管線（news_features / voting_results）
- **Iteration 3：** 文件同步（README 索引、Spec 狀態）
