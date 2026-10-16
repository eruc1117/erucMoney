# Iteration 75 — 交易模擬頁可選「測試資料（合成）」：資料來源抽成物件（真實／合成），合成行情在後端記憶體現場產生、不讀不寫任何資料庫，結果上標明是假行情

**日期：** 2026-10-16
**依據：** 使用者：「交易模擬 可以選測試的資料」（接 Iteration 74 的方案 A；當時說不做的方案 C「灌測試庫給儀表板操作」改成不灌庫的做法）
**規則：** 合成資料走記憶體，不寫 `Stock`、不寫 `Stock_crawler_test`；預設仍是真實行情（沒給 `source` 就是 `real`，tests 直接驗這點）；不跑回測、`portfolio_runs` N 不動（審查後查表：96 列、最大 id 96，與 Iteration 73 相同）；兩個模擬器的成交、費率、指標算法沒改（`git diff -U0` 兩檔只有 import、`source` 參數、`src` 三處資料呼叫、`empty_reason`、結果多 `source`、caveat 前綴，共 23 行加 18 行減）。

## 一、做了什麼

1. **`Crawler/synthetic_market.py`**（新增）：資料來源物件，兩個模擬器只透過它的三個方法拿資料。
   - `DbSource`：真實行情，三個方法在呼叫時才取 `portfolio_paper.market_days`、`trading_sim.load_prices_any`、`trading_replay.load_bench`（所以 Iteration 74 的 `fake_market.patch` 仍然有效，`test_trading_fuzz` 15 項照過）。
   - `SyntheticSource(seed)`：每檔獨立的幾何隨機漫步（日報酬 N(0.03%, 2%) 夾 ±10%，一字鎖 0.3% 機率貼漲跌停），**每檔的亂數種子 = `f'{seed}:{stock_id}'`、序列固定從 `EPOCH` 2010-01-01 產生到期末那年年底**，所以同一代號同一種子不管期間、不管同批還有哪些代號，數字都一樣；`lru_cache` 快取每檔序列。任何 4～6 碼代號都有行情，0050 也是合成的（當對手）。
   - `get_source(name, seed)`：`real`／`synthetic`，名字不對或 seed 不在 0～1,000,000,000 丟 `ValueError`（API 轉 400）。
2. **`trading_sim.simulate`／`run_text`、`trading_strategy.simulate_rules`** 多一個 `source=None` 參數（None = `DbSource()`）；三處資料呼叫改經 `src`；結果多 `source`（`{kind, label[, seed]}`）；合成資料時 `caveat` 前面接 `SYNTHETIC_CAVEAT`（「這是合成測試資料……沒有任何投資意義」）；期間太早的訊息改用 `src.empty_reason`（合成：「合成行情從 2010-01 起」）。`trading_strategy` 原本 `from trading_sim import load_prices_any` 拿掉（改經 `src`）。
3. **`Crawler/api.py`**：`SimRequest`、`RulesRequest` 多 `source: str = 'real'`、`seed: int = 0`；`_sim_source(body)` 轉 `ValueError` → 400。
4. **`Server/routes/sim.js`**：`sourceFields(body)`——`source`／`seed` **有給才轉**給 FastAPI（沒給就不帶，所以既有的 body 等值測試不用改），`source` 不在白名單或 `seed` 不是 0～1e9 整數 → 400。mock 多回 `source`。
5. **前端 `Screen/`**：`TradingSim.jsx` 工具列多「資料」下拉（真實行情／測試資料（合成））與種子輸入（選合成時才出現），`form` 多 `source`／`seed`，原本 `{...form}` 展開進 payload 的寫法讓自訂指令與 `RuleBuilder` 兩條路都自動帶到；說明文字依來源切換；新元件 `components/SourceBanner.jsx` 在兩種結果區最上面顯示橘色警示（真實行情不顯示）。`DEFAULT_FORM` 與 localStorage 合併，舊使用者預設仍是真實行情。
6. **tests**：`Crawler/tests/test_synthetic_market.py`（5 項）——同代號同種子跨期間跨同批一致、2020 年 262 個平日、OHLC 包住、`get_source` 驗證、兩個模擬器用合成來源跑完且 `get_conn` 被攔下（不連庫）、同種子重跑結果一字不差、`DbSource` 確實呼叫原本三個函式且預設來源是真實、API 的 `source`／`seed` 回傳與 400、**不給 `source` 時會走到 `get_conn`**（證明預設沒有悄悄變成合成）。`Server/tests/http/sim.test.js` +5（有給才轉、沒給不帶、四種 400）。

## 二、結果

| 檢查（`AI/progress/checks.json`） | 結果 | 說明 |
|---|---|---|
| `pytest-75` | 261 過 | Iteration 74 的 256 ＋ `test_synthetic_market` 5；`test_trading_fuzz`／`test_trading_sim`／`test_trading_strategy` 沒改照過 |
| `jest-75` | 190 過（17 套） | Server 完整 `npm test`（對 `Stock_test`）；`sim.test.js` +5 |
| `vite-build-75` | 過 | `Screen` 建置；只有既有的 chunk 大小警告 |

合成行情本身的數字沒有意義，這一輪沒有結果檔；`portfolio_runs` 不動。

## 三、讀法

- 「測試資料」是**功能試用用的假行情**，不是歷史重播、不是壓力情境：隨機漫步沒有動能、沒有產業、0050 和個股彼此獨立。用它能驗的是流程（指令解析、順延、一字鎖、費稅、規則觸發、畫面），不是任何策略好壞。畫面上的橘色警示與 `caveat` 都寫明這點。
- 預設行為沒變：Node 沒給 `source` 就不帶、FastAPI 預設 `real`、前端舊的 localStorage 表單合併進 `source: 'real'`；`test_api_source_and_seed` 最後一段直接驗「不給 source 會走到 `get_conn`」。
- 不碰庫的保證在 `SyntheticSource` 三個方法都不 import 任何 db 模組，tests 用 Iteration 74 的 `_no_db` 攔下 `get_conn` 跑完整條路（含 FastAPI `TestClient`）。
- 合成序列從 2010 固定產生、每檔獨立種子，是為了「同一個代號在不同期間、不同組合裡看到同一條線」——使用者改期間或多加一檔規則，原本那幾檔的行情不會跟著變。代價是每檔第一次要算到期末那年年底（2010～2025 共 4,174 點，`timeit` 量到 11.3 ms），之後 `lru_cache` 命中（4,096 檔）。
- 沒做：合成資料的參數（波動、漂移、一字鎖機率）開放給前端調；真實與合成的結果並排；歷史回放分頁（`/sim/replay` 是候選清單對實際行情，沒有合成版）。
- Node 的 `/sim/replay` 沒改。

## 變更檔案

修改：`Crawler/trading_sim.py`（`simulate`／`run_text` 多 `source`、結果多 `source`、caveat）、`Crawler/trading_strategy.py`（`simulate_rules` 多 `source`、拿掉 `from trading_sim import load_prices_any`）、`Crawler/api.py`（`SimRequest`／`RulesRequest` 多 `source`／`seed`、`_sim_source`）、`Server/routes/sim.js`（`sourceFields`）、`Server/tests/helpers/fastapi-mock.js`（sim 兩個 handler 回 `source`）、`Server/tests/http/sim.test.js`（+5）、`Screen/src/pages/TradingSim.jsx`（資料下拉、種子、說明、警示）、`Screen/src/components/RuleBuilder.jsx`（警示）、`AI/Doc/README.md`、`progress.md`
統一前端：`../meeting_front_end/src/stock/{pages/TradingSim.jsx, components/RuleBuilder.jsx, components/SourceBanner.jsx}` 同一份已複製、`checks.json` `mfe-build-75` 過；該 repo 的 commit／push 由使用者執行（auto mode 擋下）
新增：`Crawler/synthetic_market.py`、`Crawler/tests/test_synthetic_market.py`（5 項）、`Screen/src/components/SourceBanner.jsx`、`AI/Doc/Iterations/Iteration-75.md`
資料表：無
審查：evidence-reviewer 第一輪 40／0／3 PASS（unresolved 三條：N 未查表、模擬器 diff、「微秒級」——已補查表、diff 與計時，見規則與讀法）
驗證：`checks.json` `pytest-75`（261 過）、`jest-75`（190 過）、`vite-build-75`（過）
重啟：**MoneyCrawlerApi**（`api.py`、`trading_sim.py`、`trading_strategy.py` 改了）與 **MoneyApi**（`Server/routes/sim.js` 改了）；前端 push 後 GitHub Pages 約 3 分鐘
