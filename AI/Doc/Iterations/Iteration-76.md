# Iteration 76 — 月調倉頁最上面列出「贏過大盤」的每一次回測，點一列展開那次回測每個訊號日買了哪些股票（新端點 `/portfolio/runs/{id}/positions`，純讀取、N 不動）

**日期：** 2026-10-17
**依據：** 使用者：「打敗大盤：目前候選對門檻，有贏過大盤的，都列在頂端，點擊後再展開購買的股票細節」
**規則：** 只讀 `portfolio_runs`／`portfolio_positions`／`market_universe`，不跑回測、`portfolio_runs` N 不動（仍 96）；候選不換；實驗日誌那張表（N 只增不減）原樣保留，新清單只是另一種讀法。

## 一、做了什麼

1. **`Crawler/portfolio_api.py`**：新函式 `run_positions(run_id)`——某次回測**全部**調倉的持股，按訊號日分組（舊到新）、組內照排名（台積電固定持、沒排名的在後），名稱 `LEFT JOIN market_universe` 帶出（不在候選池的留 `None` 但仍列）；另回 `frequent`（整段回測出現次數最多的 15 檔）、`n_rebalances`、`n_stocks`。既有的 `get_run` 只回最後一次調倉，這裡回全部。
2. **`Crawler/api.py`**：`GET /portfolio/runs/{run_id}/positions`，不存在 → 404。
3. **`Server/routes/portfolio.js`**：`GET /portfolio/runs/:id/positions` 代理（非正整數 id → 400）；假伺服器 `fastapi-mock.js` 多一個 handler；`portfolio.test.js` +1。
4. **前端新元件 `Screen/src/components/BeatMarketList.jsx`**：從 `/portfolio/runs`（頁面本來就抓）挑出 **年化主動報酬 > 0 且 tag ≠ void** 的列、依主動報酬排序；每列標三項門檻（年化主動 ≥ 3%、IR ≥ 0.5、DSR ≥ 0.95）過了幾項、沒過哪項；段別篩選（按鈕依清單裡實際出現的段生成、標籤用 `segment_label`：目前是開發期／驗證期／實單，#68 正式 live 列年化主動 +4.36% 也在清單裡；保留期兩列 #67 作廢、#69 為負，所以沒有保留期按鈕）與「只看三項門檻都過的」；**點一列展開**：那次回測共幾次調倉、曾持有幾檔，訊號日下拉（預設最後一次），持股磚（排名／續抱／固定持台積電／未成交變淡），下方「最常買到」。持股點開才抓、抓過就留著。
5. **`Screen/src/pages/PortfolioLab.jsx`**：總覽分頁最上面加一張卡「贏過大盤的回測：點一列看買了哪些股票」，原本「目前候選對門檻」等卡片全部往下移、內容不變（`git diff --stat`：10 行加、0 行減，只有 import 與新卡）。`services/api.js` 多 `getPortfolioRunPositions`。
6. **統一前端 `meeting_front_end`**：`src/stock/pages/PortfolioLab.jsx`、`components/BeatMarketList.jsx` 同一份複製過去，`services/api.js` 加同一行。

## 二、結果

| 檢查（`AI/progress/checks.json`） | 結果 | 說明 |
|---|---|---|
| `pytest-76` | 263 過 | Iteration 75 的 261 ＋ `tests/test_portfolio_positions.py` 2（db 一項：分組、排序、名稱、未成交、次數、不存在 → None；API 一項：200 透傳、404） |
| `jest-76` | 191 過（17 套） | Server 完整 `npm test`；`portfolio.test.js` +1（轉送路徑、回應形狀、`x`／`0` → 400） |
| `vite-build-76` | 過 | `Screen` 建置；只有既有的 chunk 大小警告 |
| `mfe-build-76` | 過 | `meeting_front_end` CRA 建置 |
| `mfe-eslint-76` | 過 | 同步過去的三個檔 `eslint --max-warnings 0`，零警告 |
| `positions-evidence-76` | 過 | `AI/experiments/iter76_evidence.py` 對正式庫唯讀查詢，下面的資料表數字全部出自它的輸出（`checks.json` detail） |

正式庫實測（唯讀，`positions-evidence-76`，2026-10-17）：

| run | 調倉次數 | 曾持有 | `portfolio_positions` 列數 | 回應大小 | `run_positions` 耗時 |
|---|---|---|---|---|---|
| #44（候選全期間） | 68 | 306 檔 | 1,428 | 177 KB | 6.4 ms |
| #68（正式 live） | 93 | 381 檔 | 1,953 | 242 KB | 5.9 ms |

#44 最常買到：2330 台積電 ×68（固定持）、3661 世芯-KY ×21、1519 華城 ×17、3037 欣興 ×12、3017 奇鋐 ×12；最後一次訊號日 2024-09-11。#68 最後一次訊號日 2026-10-12。
清單規模：`portfolio_runs` 96 列（最大 id 96、N 96）裡年化主動 > 0 的 78 列，tag = void 的 4 列（#67 保留期舊版 +131.78%——0050 分割未還原那次、#71、#72、#76）都 > 0、不列，所以清單 **74 列**；其中年化主動 ≥ 3% 且 IR ≥ 0.5 的 40 列。tag 分布：candidate 3、official 1、official-live 1、void 4、無 87。

## 三、讀法

- 「贏過大盤」＝年化主動報酬 > 0，門檻是另一件事：清單裡每列都標了過幾項，大多數列 DSR 沒過（N 次嘗試後挑最好的，純運氣也挑得到）。頁面文字與門檻欄都寫明，別把「列在頂端」讀成「可以用」。
- 作廢的不列（#67、#71、#72、#76 共 4 列 tag = void）：那是資料錯或被取代的回測（#67 是 0050 一拆四沒還原），+131% 排第一會誤導；實驗日誌那張表仍是全部 96 列，N 沒有動。
- 同一組參數在開發期、驗證期各是一列（例如候選 #30 dev、#38 valid、#44 全期間），清單不合併，因為它們的持股本來就是不同期間。
- 展開看到的是**回測當時**每個訊號日的目標持股（`portfolio_positions`），不是今天該買什麼；「現在該買哪些」仍在下面那張候選卡。未成交（開盤一字鎖）的磚變淡並標「未成交」。
- 名稱來自 `market_universe`，目前 `portfolio_positions` 裡每一檔都找得到名稱（`positions-evidence-76`：缺名稱 0 列）；日後若候選池重建而少了某檔，前端只顯示代號。
- 沒做：持股隨時間的變化圖、兩次回測持股的交集比較、清單的匯出。

## 變更檔案

修改：`Crawler/portfolio_api.py`（`run_positions`）、`Crawler/api.py`（`GET /portfolio/runs/{run_id}/positions`）、`Server/routes/portfolio.js`、`Server/tests/helpers/fastapi-mock.js`、`Server/tests/http/portfolio.test.js`（+1）、`Screen/src/pages/PortfolioLab.jsx`（頂端新卡）、`Screen/src/services/api.js`（`getPortfolioRunPositions`）、`../meeting_front_end/src/stock/{pages/PortfolioLab.jsx, services/api.js}`、`AI/Doc/README.md`、`progress.md`
新增：`Screen/src/components/BeatMarketList.jsx`、`../meeting_front_end/src/stock/components/BeatMarketList.jsx`、`Crawler/tests/test_portfolio_positions.py`（2 項）、`AI/experiments/iter76_evidence.py`（證據查詢）、`AI/Doc/Iterations/Iteration-76.md`
資料表：無（只讀）
審查：evidence-reviewer 第一輪 32／1／9 FAIL（incorrect：段別篩選寫成「開發期／驗證期／保留期」，實際依清單出現的段生成，含實單 #68；unresolved 九條：資料表數字無檔案來源、PortfolioLab 是否只有插入、eslint 無紀錄——已補 `positions-evidence-76`、`mfe-eslint-76` 與 `git diff --stat` 關閉）
驗證：`checks.json` `pytest-76`（263 過）、`jest-76`（191 過）、`vite-build-76`（過）、`mfe-build-76`（過）、`mfe-eslint-76`（過）、`positions-evidence-76`（過）、`portfoliolab-diff-76`（`git diff --stat`：10 行加 0 行減）；evidence-reviewer 第二輪 19／0／1 PASS
重啟：**MoneyCrawlerApi**（`api.py`、`portfolio_api.py` 改了）與 **MoneyApi**（`Server/routes/portfolio.js` 改了）；兩個前端 push 後 GitHub Pages 約 3 分鐘
