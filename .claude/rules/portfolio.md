---
paths:
  - "Crawler/portfolio_*.py"
  - "Crawler/dsr.py"
  - "Crawler/tests/test_portfolio*.py"
  - "UnifiedModel/results/portfolio_*.md"
---

# 打敗大盤（月調倉）規則

對手是 0050 含息；門檻：年化主動報酬 ≥ +3%、資訊比率 ≥ 0.5、DSR ≥ 0.95。
期間：開發期 2018-01～2021-12、驗證期 2022-01～2024-09、保留期 2024-10 起。

- **每一次回測都寫進 `portfolio_runs`**（`experiment_n` 全域遞增，失敗的也算）。沒寫日誌的回測等於沒做。
- 新想法要**先寫假設與理由**再跑（`/experiment` skill 會要求）；跑完不管好壞都留結果檔 `UnifiedModel/results/portfolio_NNN_*.md`，結果檔是證據，不手改。
- 只在開發期搜尋；驗證期每組參數只跑一次確認。**用驗證期挑參數，驗證期就不再是驗證期。**
- 候選維持 `tag = 'candidate'` 的那組（目前 #44 `win3+mom-t3-tsmcest`）；換候選是使用者的決定，不是回測結果的決定。
- 保留期只能開一次（`--holdout-once`），沒有使用者明確要求絕不開。
- 改了 `portfolio_api.py`／`api.py` 的 `/portfolio/*`，Node 端 `Server/routes/portfolio.js` 與假伺服器 `Server/tests/helpers/fastapi-mock.js` 要同步。
- 結果數字要能在 `portfolio_runs.metrics` 或結果檔找到；迭代紀錄引用時附 `#experiment_n`。
