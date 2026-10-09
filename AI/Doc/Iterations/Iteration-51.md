# Iteration 51 — 打敗大盤：成功紀錄標記與前端「月調倉」頁

**日期：** 2026-10-09
**依據：** 使用者：「先把成功的紀錄，然後整理到前端畫面上顯示」。
**前提：** Iteration 50 的 44 次實驗只存了指標與持股，沒有淨值曲線；前端要畫圖得補。

## 一、做了什麼

### 成功紀錄：migration 022，`--attach-series`、`--tag`

- `portfolio_runs.tag`：`candidate` 標在 #30（開發期）、#38（驗證期）、#44（全期間）三列——同一組參數 `win3+mom --tranches 3 --tsmc-weight est`。
- `portfolio_run_series(run_id, trade_date, nav, bench)`：日淨值，組合與 0050 同起點 1。新的 run 自動存；舊的用
  `portfolio_backtest.py --attach-series <id>` 以日誌裡的參數重算補上——**不算新實驗，N 不動**。三列重算的年化主動報酬與日誌一字不差（drift 0.0），回測可重現。
- `metrics.yearly_active`：逐年主動報酬進 JSONB（新 run 自動有，舊的由 attach 補）。

### API：`Crawler/portfolio_api.py` → FastAPI `/portfolio/*` → Node `Server/routes/portfolio.js`

| 端點 | 內容 |
|---|---|
| `GET /portfolio/candidate` | 候選三列（開發期、驗證期、全期間）、全期間曲線（每 5 日一點，328 點）、最後一次持股（21 檔含台積電）、門檻、保留期是否開過 |
| `GET /portfolio/runs` | 實驗日誌全部（失敗的也在） |
| `GET /portfolio/runs/:id?step=` | 單一 run：指標、參數、曲線、最後持股 |

Node 代理照第 47 次迭代的模式（`proxyToFastAPI`、FastAPI 不在線回 503）；一般使用者可讀。`tests/http/portfolio.test.js` 5 項、`fastapi-mock.js` 三條假回應、`migrations.test.js` 改 22。

### 頁面：`Screen/src/pages/PortfolioLab.jsx`（側欄「月調倉」，meeting_front_end 同步到「預測」群組）

由上到下：候選三列對門檻（年化主動報酬、IR、DSR、月勝率、追蹤誤差、相對最大落後、換手、成本、組合對 0050）→ 淨值曲線（ApexCharts，組合實線、0050 虛線）
與逐年主動報酬 → 回測期末的最後持股（台積電標「固定」）→ 實驗日誌（預設收起，★ 候選）→ 怎麼讀。
**DSR 放在和主動報酬一樣大的位置**，頁首直接寫「保留期未開」：這一頁要說的是「超越了」和「不是運氣」是兩件事。
`smoke.mjs` 加 `PortfolioLab`，jsdom 掛載通過。

## 二、要注意

- Node（:3001）與 FastAPI（:8000）**都要重啟**才有新路由（兩個常駐程序是 Deploy/run_logged.js 起的）。migration 022 已用 runner 套到正式庫。
- 頁上的「最後一次持股」是 2024-09-11 回測期末的清單，不是今天的；每月自動清單要等階段 4 的 `job_portfolio_monthly`。

## 變更檔案

新增：`Server/migrations/022_portfolio_series.sql`、`Crawler/portfolio_api.py`、`Server/routes/portfolio.js`、`Server/tests/http/portfolio.test.js`、`Screen/src/pages/PortfolioLab.jsx`（meeting_front_end 同）。
修改：`Crawler/portfolio_backtest.py`、`Crawler/api.py`、`Server/app.js`、`Server/tests/helpers/fastapi-mock.js`、`Server/tests/db/migrations.test.js`、`Crawler/tests/helpers/db_setup.py`、
`Screen/src/{App.jsx,components/Sidebar.jsx,services/api.js}`、`Screen/smoke.mjs`、`meeting_front_end/src/stock/{nav.js,services/api.js}`。
