# Iteration 77 — 「贏過大盤」清單展開時加淨值折線圖：組合對 0050 含息對大盤（用既有 `/portfolio/runs/{id}` 的曲線與 `NavRangeChart`，純前端、不用重啟）

**日期：** 2026-10-17
**依據：** 使用者：「點擊展開時，也要顯示折線圖顯式對比」（接 Iteration 76 的贏過大盤清單）
**規則：** 只改前端一個元件；後端、資料表、N（96）都不動；沒存曲線的回測不補跑、不造假，只顯示說明。

## 一、做了什麼

1. **`Screen/src/components/BeatMarketList.jsx`**：展開一列時，除了原本的 `/portfolio/runs/:id/positions`（持股），若該列 `has_series`（`list_runs` 依 `portfolio_run_series` 標的）再抓 `/portfolio/runs/:id?step=3`（Iteration 51 就有的端點：`series` 每點 `nav`／`bench`／`idx`，每 3 日一點），在持股上方用月調倉頁共用的 `NavRangeChart` 畫三條線（組合／0050 含息／大盤 TAIEX_TR），可選區間重新歸一；圖上方一行寫全期間年化與最大回撤（`run.metrics`）。區間選擇的 localStorage key 每個 run 各自一個（`pf_beat_nav_<id>`），免得開發期的區間套到驗證期的列上變成空圖。
2. 沒存曲線的列（`has_series = false`）不抓、顯示「這次回測沒有存淨值曲線（早期只存指標）」，下面仍有持股。
3. 曲線點開才抓、抓過就留著（與持股相同）。說明文字改為「點一列展開：淨值折線圖（組合／0050／大盤）與每個訊號日買了什麼」。
4. 統一前端 `meeting_front_end/src/stock/components/BeatMarketList.jsx` 同一份複製（那邊的 `NavRangeChart.jsx` Iteration 65 已同步）。

## 二、結果

| 檢查（`AI/progress/checks.json`） | 結果 | 說明 |
|---|---|---|
| `vite-build-77` | 過 | `Screen` 建置 |
| `mfe-build-77` | 過 | `meeting_front_end` CRA 建置 |
| `mfe-eslint-77` | 過 | 同步過去的元件 `eslint --max-warnings 0` |
| `series-evidence-77` | 過 | `AI/experiments/iter77_evidence.py` 對正式庫唯讀查詢，下面的曲線覆蓋數字出自它 |

pytest／jest 沒跑：後端與 Node 沒有任何改動（`git status` 的程式碼改動只有 `Screen/src/components/BeatMarketList.jsx`，其餘是文件 `AI/Doc/README.md`、`progress.md` 與兩個新檔）。

曲線覆蓋（`checks.json` `series-evidence-77`，腳本 `AI/experiments/iter77_evidence.py` 對正式庫唯讀查詢，2026-10-17）：55 個 run 有曲線（id 30～96，共 48,587 點）；清單 74 列裡 43 列有曲線、31 列沒有（id 2～43 之間的早期回測，Iteration 49／50 只存指標）、顯示說明。#44 曲線 1,635 點，step 3 後約 545 點；#68 2,130 點。

## 三、讀法

- 折線圖是「這次回測的淨值對 0050 含息對大盤」，三條都從起點（或選的區間起點）歸一到 1；贏不贏看組合線有沒有在 0050 線上方，`NavRangeChart` 上方會算這段的組合／0050／大盤／主動報酬。
- 和候選卡的淨值曲線是同一個元件、同一張表 `portfolio_run_series`，但取樣密度不同：候選卡經 `/portfolio/candidate`（內部 `get_run(step=5)`，每 5 日一點），清單經 `/portfolio/runs/{id}?step=3`（每 3 日一點）。候選卡畫的是 tag = candidate 三列（#30 開發期、#38 驗證期、#44 全期間 2018-01-01～2024-09-30）裡結束日最晚、起點最早的 #44，所以清單裡 #44 那列展開看到的，和下面「淨值曲線：組合 vs 0050 vs 大盤」是同一條曲線、點比較密。
- 早期 31 列（id 2～43 之間）沒曲線是資料本來就沒存（Iteration 49／50 只存指標），要看圖得 `portfolio_backtest.py --attach-series` 重算補上；本輪沒補，因為那是重跑回測。
- 沒做：多列同圖疊比、持股變化圖。

## 變更檔案

修改：`Screen/src/components/BeatMarketList.jsx`、`../meeting_front_end/src/stock/components/BeatMarketList.jsx`、`AI/Doc/README.md`、`progress.md`
新增：`AI/Doc/Iterations/Iteration-77.md`、`AI/experiments/iter77_evidence.py`（證據查詢）
資料表：無
審查：evidence-reviewer 第一輪 34／2／1 FAIL（incorrect：「git diff 只有一個 .jsx」漏了文件、候選卡資料來源寫成 `/portfolio/runs/{id}`；unresolved：全期間候選列是否為 #44——已查 `portfolio_runs` tag = candidate 為 #30／#38／#44，三處都已改）；第二輪 4／0／0 PASS
驗證：`checks.json` `vite-build-77`（過）、`mfe-build-77`（過）、`mfe-eslint-77`（過）、`series-evidence-77`（過）；pytest／jest 沒跑（後端未動）
重啟：不用（只有前端）；兩個 repo push 後 GitHub Pages 約 3 分鐘
