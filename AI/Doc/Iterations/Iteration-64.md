# Iteration 64 — 候選 #44 升為正式策略：新頁「正式策略」、淨值每日 18:50 重算；保留期因 0050 分割未還原與回測無暖機重跑一次——結果輸給 0050

**日期：** 2026-10-11
**依據：** 使用者：「候選 #44 開，轉為正式策略，開新的分頁，並每天更新淨值」。
**規則：** 保留期只能開一次——`portfolio_official.promote` 跑一次 segment holdout、tag `official`、凍結；每日更新的曲線另開一列 `live`（同參數、2018-01-01 到最新行情，每天覆寫自己，不算新實驗）；兩者分開存，因為一個是證據、一個會一直變。

## 一、做了什麼

### `Crawler/portfolio_official.py`、migration 027 `portfolio_official`

- `promote(44, note)`：拒絕第二次（已有正式策略或日誌已有 holdout 列）；跑保留期（2024-10-01 → 今天）→ #67；跑 live（2018-01-01 → 今天）→ #68；寫 `portfolio_official`（候選、保留期、live 三個 run id、升格日、理由、最後更新）。
- `update_daily(today, force)`：live 列用同參數重算到最新行情，`update_run_in_place` 覆寫 metrics（保留 experiment_n／DSR 等實驗欄位）、period_end、positions、series；行情沒新的就略過；`--force` 給資料修正後用。
- `status()`：三段指標（開發／驗證／開發＋驗證／保留期／live）、live 淨值序列、逐年、本月清單、紙上帳戶摘要。
- 排程 `job_portfolio_official` 每日 18:50（日線 18:30、紙上 18:40 之後）；啟動補跑：正式策略淨值日期落後行情才補。
- FastAPI `GET /portfolio/official`、`POST /portfolio/official/update`；Node 代理（GET 匿名可讀、POST admin）。

### 頁面 `Screen/src/pages/OfficialStrategy.jsx`（側欄「正式策略」；統一前端放「預測」群組，匿名可讀）

四格（開發＋驗證、保留期、全期間至今、紙上帳戶）、每日更新的淨值曲線（可選區間，多一個「保留期」快捷鍵）、三段指標表、逐年主動報酬、本月清單；admin 有「立刻更新」。
`NavRangeChart` 從月調倉頁抽成共用元件（`components/NavRangeChart.jsx`，加 `extraPresets`／`storageKey`）。

### 抓到的資料問題與處理

1. **0050 在 2025-06-18 做 1 拆 4 的分割，還原價沒處理**：`stock_daily_prices` 的收盤價從 188.65（2025-06-10）掉到 47.57（2025-06-18），adj_close 沒有回溯乘 0.25，對手曲線從那天起少了四分之三，所以第一次保留期算出年化主動 +131.8%、IR 2.28——是假的。
   處理：`Crawler/fix_0050_split.py` 把分割當公司行動寫進 `stock_capital_reduction`（ex 2025-06-18、前收 188.65、參考價 47.1625，factor 0.25，和減資同一套回溯還原），`rebuild_adj_close.rebuild(['0050'])` 重建 5,727 列；修正後 2024-10-01 的 adj_close 44.06、最新 114.95（`checks.json` name=fix-0050-split）。
   live 列用 `--update --force` 重算：年化主動 +4.34%、IR 0.34（2018-01-12～2026-10-07）。保留期用修正後的對手**不存**地再算一次（`holdout_preview_evidence.py`，不是新實驗）：年化主動 +12.6%、IR 0.63、組合 +213% 對 0050 +149%、相對最大落後 −26.7%、月勝率 58%（`checks.json` name=holdout-corrected-preview）。
   **凍結的 #67 仍是錯的對手算出來的**；要不要用修正後的資料重跑一次保留期（算第二次開）由使用者決定，本輪沒動。
2. **保留期前 8 個月沒調倉（2024-10～2025-05 全現金）**：`skipped_months: 8`，第一次調倉是 2025-06-11。
   根因是**回測沒有暖機**：`portfolio_backtest.run` 從 `start` 才開始載行情，動能訊號要 252 個交易日歷史，所以任何期間開頭約 10 個月都因「訊號不足」不調倉（開發期 2018 年也是這樣，第一次調倉 2018-11-12）。
   處理：`run()` 加 `warmup_days`（行情與營收往前多載，調倉仍從 `start` 開始；NAV 從第一次成交日起算，暖機期不進曲線）。
   一度懷疑是公告日 bug（2024-04～2026-02 的 `stock_revenue_announce` 公告日 100% 與營收月同月）——查了 Iteration 49 才確認那是對的：`revenue_month` 的鍵是**公布月**（FinMind 慣例），同月才正確；而且候選訊號 `win3` 用的是每月 1～11 日的日曆窗口，根本不碰公告日。這條懷疑撤回。
3. **保留期重跑（使用者決定）**：`portfolio_official.rerun_holdout`——同參數、0050 修正後、暖機 420 天 → **#69**（24 次調倉、0 個空窗月）取代 #67（tag 改 `void`、notes 寫明，列留著當證據；N 變 69）。
   **#69：年化主動 −6.12%、IR −0.45**；組合 +120.6% 對 0050 +149.1%（2024-10-14～2026-10-08，年化 +51.0% 對 +60.8%）；追蹤誤差 13.8%、最大回撤 −34.4% 對 −27.5%；逐年主動 2024 +2.2%、2025 −1.7%、2026 −11.3%（`checks.json` name=official-holdout-rerun、official-evidence）。
   正式策略在保留期**沒有打敗 0050**：三個門檻（主動 ≥ +3%、IR ≥ 0.5、DSR ≥ 0.95）一個都沒過。
4. 0050 在 2025-06-11～17 沒有行情（原因未查，應是分割停牌）；市場日線那幾天有 5 個交易日（`checks.json` name=official-evidence）。

## 二、結果

| 檢查 | 結果 | 來源 |
|---|---|---|
| `test_portfolio_official.py` 3 項、`test_scheduler.py` +1（18:50 與補跑條件） | 升格只能一次、tag、每日更新原地覆寫（N 不動、series 覆寫）、同日略過、沒升格略過；重跑保留期：舊列 void、新列 official、`portfolio_official` 指到新列、暖機 420 | `checks.json` name=pytest |
| Crawler pytest 全套 | 224 項通過 | 同上 |
| Server jest | 185 項、17 套（`migrations.test.js` 27 個；`portfolio.test.js` +1：official 匿名 200、update 401／403／admin 200） | `checks.json` name=jest |
| Screen vite build、meeting_front_end build | 通過 | `checks.json` name=vite-build、mfe-build |
| 升格 | #67 holdout、#68 live、`portfolio_official` 一列 | `checks.json` name=official-promote |
| 保留期重跑 | #69 取代 #67（void）、`portfolio_official.holdout_run_id = 69`；N = 69 | `checks.json` name=official-holdout-rerun、official-evidence |
| 0050 分割修正、live 重算、保留期修正後預覽 | 見上 | `checks.json` name=fix-0050-split、official-update-forced、holdout-corrected-preview |
| 常駐工作 | MoneyApi（migration 027）、MoneyCrawlerApi、MoneyScheduler 已重啟 | — |
| 頁面 | 本機預覽看過：四格、淨值曲線（全期間 2018-01-12～2026-10-07 組合 +944% 對 0050 +630%）、三段表 | 截圖不在 repo；#68 的總報酬、#67 的調倉日、營收公告日同月統計、migration 027 已套用，都印在 `checks.json` name=official-evidence |

## 三、讀法

1. 保留期「只看一次」在這一輪開了兩次：第一次的對手壞掉、回測又沒暖機。同參數在修正後再算一次不是挑參數，使用者決定這樣做，兩列都留著、寫清楚。
2. **結論是壞消息**：修好資料、補上暖機後，候選策略在保留期年化主動 −6.1%，連續 24 個月正常調倉，2025、2026 都落後 0050。之前「+12.6%」的預覽是靠前 8 個月空手躲過落後期的假象。開發期 +8.6%、驗證期 +15.7% 的候選，出了樣本就不成立——這正是 DSR 0.13 一直在說的事（66 次嘗試後挑出來的最好，很可能是運氣）。
   正式策略的名分還在（頁面、每日淨值、紙上交易都照跑），但它現在是「正在被證偽的策略」，不是「打敗大盤的策略」。要不要繼續讓引擎照它下單、要不要回到研究階段，是使用者的決定。
3. 每日更新的 live 曲線是「策略的理論軌跡」，紙上帳戶是「引擎真的做了什麼」；兩者差距就是執行成本（限價沒成交、現金閒置、估計的台積電權重）。live 列（#68，從 2018-01 起算）沒有暖機，2018 年前 10 個月仍是空手；要不要也加暖機重算，和「開發期紀錄要不要動」是同一個問題，沒動。
4. 沒做：第二本無停損模擬帳戶、把保留期結果接回「月調倉」頁的候選表。
5. evidence-reviewer 審過一輪：36 條主張 29 verified、1 incorrect（把 2025-06-10 的收盤價寫成 adj_close，已改）、6 unresolved（DB 內容、截圖、重啟狀態、使用者原話——DB 的部分已用 `official_evidence.py` 補進 checks.json）。

## 變更檔案

新增：`Crawler/portfolio_official.py`（含 `rerun_holdout`）、`Crawler/tests/test_portfolio_official.py`、`Crawler/fix_0050_split.py`、`Crawler/holdout_preview_evidence.py`、`Crawler/official_evidence.py`、`Server/migrations/027_portfolio_official.sql`、`Screen/src/pages/OfficialStrategy.jsx`、`Screen/src/components/NavRangeChart.jsx`、`meeting_front_end/src/stock/{pages/OfficialStrategy.jsx,components/NavRangeChart.jsx}`。
修改：`Crawler/portfolio_backtest.py`（`warmup_days`）、`Crawler/scheduler.py`、`Crawler/api.py`、`Crawler/tests/test_scheduler.py`、`Crawler/tests/helpers/db_setup.py`、`Server/routes/portfolio.js`、`Server/tests/helpers/fastapi-mock.js`、`Server/tests/http/portfolio.test.js`、`Server/tests/db/migrations.test.js`（27）、`Screen/src/pages/PortfolioLab.jsx`、`Screen/src/App.jsx`、`Screen/src/components/Sidebar.jsx`、`Screen/src/services/api.js`、`meeting_front_end/src/stock/{pages/PortfolioLab.jsx,nav.js,services/api.js}`、`AI/Doc/README.md`、`Server/README.md`、`progress.md`。
