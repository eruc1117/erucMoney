# Iteration 65 — 月調倉與正式策略的淨值曲線加上含息大盤：正式策略全期間贏 0050 也贏大盤，保留期兩個都輸

**日期：** 2026-10-12
**依據：** 使用者：「月調倉跟正式策略，曲線加上大盤指數」。
**規則：** 純顯示，不跑回測、不動 `portfolio_runs`（N 仍 69）、不碰保留期；大盤用已有的 `index_daily_prices` 的 `TAIEX_TR`（發行量加權股價報酬指數，含息），不另抓資料。

## 一、做了什麼

### `Crawler/portfolio_api.py`：`get_run` 的 series 每點多一個 `idx`

- `_index_series(cur, dates)`：把 `TAIEX_TR` 收盤對齊到淨值曲線的日期，第一天歸一到 1（nav／bench 在表裡本來就是起點 = 1，三條線才畫得在一起）；指數缺的交易日沿用前一日；起點那天沒有指數就整條不給（前端只畫兩條）。
- 三個端點一起受惠：`GET /portfolio/candidate`（月調倉頁的全期間曲線）、`GET /portfolio/official`（正式策略頁 live 列、保留期）、`GET /portfolio/runs/:id`。Node 只是代理，沒改。
- 單元測試 `test_index_series_aligns_ffills_and_rebases`（對齊、補值、歸一、三種空結果）。

### 前端 `NavRangeChart.jsx`（Screen 與 meeting_front_end 同一份）

- 第三條線「加權指數含息（大盤）」，橘色實線；舊 run 沒有 `idx` 就自動回到兩條。
- 區間重新歸一時，大盤的起點取區間內第一個有值的點；缺的點留 null，Apex 斷線不畫成 0。
- 圖上方的區間摘要加「大盤 ±x%」與年化「對大盤」；主動報酬仍是**對 0050**（策略的對手沒變）。
- 兩頁的卡片標題改「淨值曲線：組合 vs 0050 vs 大盤」。

## 二、結果

三條線都從起點 1 算（`portfolio_run_series` 的 nav／bench 與 `index_daily_prices` TAIEX_TR 對齊後的值；下表數字與 N 都由 `Crawler/nav_index_evidence.py` 印出，記在 `checks.json` name=nav-index-evidence 2026-10-12）：

| 列 | 期間 | 組合 | 0050 含息 | 大盤含息 | 來源 |
|---|---|---|---|---|---|
| live #68（全期間至今） | 2018-01-12 ～ 2026-10-12 | 10.38 | 7.22 | 6.11 | `get_run(68)` 末點 |
| 保留期 #69（凍結） | 2024-10-14 ～ 2026-10-08 | 2.206 | 2.491 | 2.272 | `get_run(69)` 末點 |
| live #68 的「保留期」快捷區間 | 2024-10-01 ～ 2026-10-12 | 2.365 | 2.605 | 2.308 | 區間內重新歸一 |

- live 列 2,126 個點對齊後都有值（其中 1 天 `index_daily_prices` 沒有該日的列，沿用前一日）；TAIEX_TR 本身 2018-01-02 ～ 2026-10-12 共 2,133 日。`portfolio_runs` 仍是 69 列、max N = 69。
- 全期間 0050 比大盤多一截（7.22 對 6.11）：台積電約佔 0050 一半（月調倉頁的滾動迴歸估：2018 約 0.38、近兩年 0.55，Iteration 50），這幾年它跑贏大盤。正式策略的對手是 0050，比對大盤更嚴。

| 檢查 | 結果 | 來源 |
|---|---|---|
| Crawler pytest | 225 passed（新增 1） | `checks.json` name=crawler-pytest 2026-10-12 |
| Screen `npm run build` | 通過 | `checks.json` name=screen-build |
| meeting_front_end `npm run build` | 通過 | `checks.json` name=meeting-front-end-build |
| Server jest | 沒跑（Node 沒改） | – |
| 數字證據 | 三條線末點、區間、涵蓋、N | `checks.json` name=nav-index-evidence |

## 三、讀法

- 正式策略在全期間贏 0050 也贏大盤；在保留期（2024-10 起）輸 0050、**也輸大盤**（2.206 對 2.272）——Iteration 64 的結論（保留期沒過門檻）不因為換對手而改變。
- 保留期內 0050 又贏大盤一截（2.491 對 2.272），所以「輸給 0050」有一部分是台積電效應，但策略本來就固定持台積電的 0050 估計權重（run 44 params `tsmc_weight = est`），這不是藉口。
- 大盤線只是參考，不進任何指標；門檻、IR、DSR 都仍對 0050。

## 變更檔案
修改：`Crawler/portfolio_api.py`、`Crawler/tests/test_portfolio.py`、`Screen/src/components/NavRangeChart.jsx`、`Screen/src/pages/OfficialStrategy.jsx`、`Screen/src/pages/PortfolioLab.jsx`、`../meeting_front_end/src/stock/{components/NavRangeChart.jsx, pages/OfficialStrategy.jsx, pages/PortfolioLab.jsx}`、`AI/Doc/README.md`、`progress.md`
新增：`AI/Doc/Iterations/Iteration-65.md`、`Crawler/nav_index_evidence.py`（證據腳本）
