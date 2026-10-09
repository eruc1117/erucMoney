---
name: experiment
description: 跑一次「打敗大盤」月調倉回測實驗：先寫假設與理由、只在開發期跑、驗證期只確認一次、寫日誌 portfolio_runs、留結果檔、交 strategy-critic 檢查前視偏誤與選擇偏誤。使用者提出新訊號／新參數／「再試一種策略」時用；不要用它來重搜參數。
---

假設：$ARGUMENTS

這個流程的目的是讓每一次實驗**事前有理由、事後有證據**，而不是讓 N 變大。先讀 `.claude/rules/portfolio.md`。

1. **事前登記**（先寫再跑）：在回報裡寫下三行——假設是什麼、為什麼這個假設在台股可能成立（文獻或機制）、預期哪個指標會變好。
   想不出理由的實驗不跑；回報「沒有事前理由，不跑」就是完成。
2. **檢查是不是重搜**：`portfolio_runs` 裡已經有同家族的設定（查 `name`、`signal`、`params`）就不要再跑相鄰參數；相鄰設定差 ±5% 是雜訊（Iteration 50 量過）。
3. **開發期**：`cd Crawler && python portfolio_backtest.py --signal … --segment dev …`（或 `portfolio_search.py --round …`）。每一次都會寫日誌、產 `UnifiedModel/results/portfolio_NNN_*.md`。
4. **驗證期一次**：只對開發期過門檻的那一組跑 `--segment valid`，同一組參數、不調。
5. **對照候選**：把結果和 `candidate`（#30 dev／#38 valid／#44 全期間）放同一張表，附 `#experiment_n`。
6. **審查**：請 `strategy-critic` 讀結果檔與用到的訊號程式碼（`portfolio_signal.py` 相關函式），給它 `#experiment_n`、結果檔路徑、訊號定義位置。
   它會查前視偏誤、驗證期是否被拿來挑、N 是否記對、成本假設。FAIL 就修，最多三輪；記 `node AI/harness/record_check.js --name strategy-critic --status pass|fail --summary "…"`。
7. **結論寫進迭代紀錄**（`/iterate` 的格式）：沒成立的和成立的一樣要寫。候選不因為單次實驗換——「跨段一致且超過候選的家族」只在回報裡標出來，換不換由使用者決定。
8. **交接**：更新 `progress.md`，N 的新值寫進「已完成」。
9. **回報**：#experiment_n 範圍、開發期／驗證期指標對候選、審查結果、N 現在是多少、保留期仍未開。
