# Iteration 79 — 十種交易策略範本搬到後端成單一來源、可一鍵比較：合成行情上每種都照定義動作；2018-01～2024-09 真實行情四檔上，「一直在場」的三種在三檔贏過 0050；純擇時的五種四檔全輸（期末現金 89%～100%），季線趨勢與定投在均線下只在 2603 贏

**日期：** 2026-10-17
**依據：** 使用者：「建立不同交易策略並進行測試」
**規則：** 這是交易模擬（條件規則）那條線，不是月調倉回測——不寫 `portfolio_runs`、N 不動、不登記 Papers.md、候選不變（同一時間另一個 session 在做 Iteration 78 第八代實驗，本輪不碰它的檔案）。真實行情只讀，期間 2018-01-02～2024-09-30、不進保留期（2024-10 起）。合成行情與 tests 不連任何資料庫。範本是「常見做法的定義」，不調參、不挑最好的那組。

## 一、做了什麼

1. **`Crawler/trading_presets.py`**（新，119 行）：十種策略範本的單一來源。原本 Iteration 61／62 寫死在 `RuleBuilder.jsx` 的六個模板（均線進出、停損停利、逢低加碼、RSI 反轉、定投在均線下、雙重確認）搬過來，另加四種：買進持有（對照組）、定期定額、季線趨勢（60 日均線）、動能突破（60 日漲 20% 且在 20 日均線上）。買進金額寫成**資金的比例**（`then.frac`），`build(key, stock_id, start, capital)` 換成元、把 `'@start'` 換成期間起始日；`list_presets()` 給前端；`compare()` 把十種套在同一檔、同一期間、同一筆資金各跑一次 `trading_strategy.simulate_rules`，回每種的成交筆數、觸發次數、報酬、回撤、期末現金。
   | key | 名稱 | 定義（買進金額 = 資金比例） |
   |---|---|---|
   | `buyhold` | 買進持有 | 起始日買 50%，不賣 |
   | `dca` | 定期定額 | 每月 5 日買 1.5% |
   | `ma20` | 均線進出 | 向上穿過 20 日均線買 10%，跌破賣光 |
   | `ma60` | 季線趨勢 | 向上穿過 60 日均線買 30%，跌破賣光 |
   | `stop` | 停損停利 | 起始日買 30%；比成本低 10% 或高 20% 賣光 |
   | `dip` | 逢低加碼 | 每月 5 日買 1%；5 日跌 5% 以上再加 2%（最多 10 次、冷卻 5 日） |
   | `rsi` | RSI 反轉 | RSI(14) < 30 買 10%，> 70 賣光（冷卻 5 日） |
   | `dcama` | 定投在均線下 | 每月 5 日 且 前一日收盤在 60 日均線下才買 2% |
   | `confirm` | 雙重確認 | 穿過 20 日均線 且 RSI(14) > 50 買 10%；跌破 或 比成本低 10% 賣光 |
   | `breakout` | 動能突破 | 60 日漲 20% 以上 且 在 20 日均線上買 10%；20 日跌 10% 以上 或 比成本低 15% 賣光 |
2. **API**：FastAPI `GET /trading/sim/presets?stock&start&capital`（範本清單，規則已套好股票與金額）、`POST /trading/sim/presets/compare {stock_id, start, end, capital, source, seed}`（比較表；`source`／`seed` 同 Iteration 75，合成行情也能比）。Node `GET /sim/presets`（只轉三個參數）、`POST /sim/compare`（代號 4～6 碼、日期、資金、來源驗證後轉給 FastAPI）；假伺服器與 `sim.test.js` +2。`meeting_API_Server` 的 `sim` 前綴本來就允許匿名 GET／POST，不用改。
3. **`Crawler/tests/test_trading_presets.py`**（新，5 項，無 `db` marker、`get_conn` 被攔下）：
   - 十種都通過 `validate_rules`、金額隨資金等比放大、`'@start'` 都換掉、`list_presets` 文字正確、不存在的 key 丟 `KeyError`。
   - **刻意造的 V 形行情**（跌 60 日每日 −0.5% → 急彈 5 日每日 +5% → 漲 115 日每日 +0.5% → 崩 40 日每日 −2% → 盤整 30 日；開盤 = 收盤、0050 不動）：十種都跑完、帳務不變量（Iteration 74 的 `check_invariants`）全過，且每種照定義動作——買進持有只買一次；定期定額 12 個月各一次；停損停利第一天買、跌 10% 賣光、停利 0 次；均線進出／季線趨勢在上漲段買、崩盤段賣、有賺；RSI 反轉在下跌段第 3 個交易日就買（Wilder RSI 沒有暖機，連跌第 2 天就是 0）、急彈段 RSI > 70 就賣、第一趟賠（斷言 `pnl < 0`）——策略本身的性質；動能突破在上漲段後半買、崩盤段賣；逢低加碼的加碼全落在崩盤段（1～10 次）；定投在均線下只在均線下的月份買。**雙重確認整段一筆都不買**：長跌後反彈第一天就穿過被拖低的 20 日均線，那天 RSI(14) 只有 41.7（測試用 `_indicators` 算出整段只有第 60 個交易日穿線、RSI 斷言 41.7），AND 不成立、之後再沒有穿線。
   - 第二條行情（盤整 60 日 ±0.05% 交錯 → 漲 100 日 → 崩 40 日 → 盤整 30 日）驗雙重確認會買會賣：盤整裡每隔一天穿線、RSI 剛過 50，來回被洗（每趟小賠 < 1,000 元）；上漲第一天穿線時 RSI 已在 50 以上 → 買一次，崩盤跌破 → 賣光、有賺。
   - 合成行情（種子 1）上的比較表：十列齊、欄位齊、買進持有 1 筆、定期定額 24 筆、兩次呼叫結果一字不差；期間倒置或早於 2010 回 `available: False`。
   - API：兩個端點 200 與各種 400；不給 `source` 會碰 `get_conn`（證明預設仍是真實行情）。
4. **前端**：`RuleBuilder.jsx` 的六個寫死模板拿掉（`git diff --numstat` 60 加 28 減，記在 `checks.json` `rulebuilder-numstat-79`），改用 `getPresets` 抓後端範本（「套在哪檔」、起始日、資金改了就重抓；第一次抓到且編輯器是空的才放第一個範本）；新按鈕「比較全部策略」→ `comparePresets`，結果用 `CompareTable` 列成一張表（依總報酬排序、橘色合成警示、每列「套用」把那組規則放進編輯器）。`TradingSim.jsx` 多傳兩個函式、`api.js` 多 `getSimPresets`／`compareSimPresets`。`meeting_front_end/src/stock/` 三檔同步（`RuleBuilder.jsx`／`TradingSim.jsx` 與 Screen 逐字相同；`api.js` 是那邊的 shim，只加同名兩個函式）。
5. **實驗腳本** `AI/experiments/iter79_presets.py`：真實行情四檔（2330、2317、2454、2603）＋合成種子 0 各跑一次 `compare()`，寫 `UnifiedModel/results/trading_presets_iter79.md`（腳本產生，不手改）。

## 二、結果

| 檢查（`AI/progress/checks.json`） | 結果 | 說明 |
|---|---|---|
| `pytest-79` | 272 過 | Crawler 整套（Iteration 76 的 263 ＋ 本輪 5 ＋ 另一個 session 工作區裡未提交的新測試） |
| `jest-79` | 193 過（17 套） | Server 完整 `npm test`；`sim.test.js` +2 |
| `presets-run-79` | 過 | 實驗腳本；真實行情每檔約 2.9 秒、合成 0.5 秒（結果檔各節標題） |
| `vite-build-79` | 過 | `Screen` 建置 |
| `mfe-build-79` | 過 | `meeting_front_end` CRA 建置 |
| `mfe-eslint-79` | 過 | 三個同步檔 `eslint --max-warnings 0` |

（改號前先以 `-78` 名稱記過一輪同樣的檢查——`jest-sim-78`、`presets-run-78`、`pytest-78`、`jest-78`、`vite-build-78`、`mfe-build-78`、`mfe-eslint-78`，也是本輪的；發現另一個 session 正在用 78 後改為 79 重跑重記。`pytest-portfolio-78`、`val-parse-smoke-78`、`jest-migrations-78` 不是本輪的。）

**真實行情**（`UnifiedModel/results/trading_presets_iter79.md`；2018-01-02～2024-09-30、資金 100 萬、0050 含息同期 +182.7%）：

| 檔 | 贏過 0050 的範本（總報酬） | 最差三種 |
|---|---|---|
| 2330 | 逢低加碼 +214.6%、定期定額 +199.3%、買進持有 +198.5% | 雙重確認 +6.9%、停損停利 +5.9%、RSI 反轉 +5.6% |
| 2317 | 沒有（最好是定期定額 +142.0%） | 雙重確認 +3.8%、均線進出 +1.6%、停損停利 −3.7% |
| 2454 | 逢低加碼 +257.3%、買進持有 +239.2%、定期定額 +236.8% | 均線進出 +11.6%、停損停利 +7.7%、RSI 反轉 +4.5% |
| 2603 | 逢低加碼 +879.5%、定期定額 +860.4%、買進持有 +615.6%、定投在均線下 +529.6%、季線趨勢 +292.7% | 雙重確認 +32.5%、RSI 反轉 +8.4%、停損停利 −3.0% |

四檔 × 十種 = 40 格裡 11 格贏過 0050：一直在場的三種（逢低加碼、定期定額、買進持有）在 2330、2454、2603 贏、2317 全輸；均線進出、雙重確認、動能突破、RSI 反轉、停損停利五種四檔都沒贏，期末現金占比 89%～100%；季線趨勢（現金 74%～92%）與定投在均線下（現金 7%～23%）只在 2603 贏。合成行情（種子 0）那節 0050 合成序列同期 −69.7%（結果檔該節有印），十種「主動報酬」全是正的——那是隨機漫步上的噪音，只證明比較表在合成來源上跑得通。

## 三、讀法

- **這一輪的產出是「策略庫 + 它們各自會做什麼的證據」，不是哪個策略好。** 十種範本是常見做法的定義，金額比例是定義的一部分；真實行情的比較表是事後結果，沒有驗證期、沒有多檔、沒有多期間，不能拿來選策略。它放在交易模擬頁，和月調倉研究（`portfolio_runs`、Papers.md）是兩條線。
- 純擇時的五種（均線進出、雙重確認、動能突破、RSI 反轉、停損停利）在 2018～2024 的多頭裡四檔全輸，主要是**在場資金少**：一次買 10%～30%、賣光後要等下一個訊號，期末現金 89%～100%；「一直在場」的三種（逢低加碼、定期定額、買進持有）資金幾乎全投，吃到整段多頭。季線趨勢一次買 30%、進出少，2603 那段大漲吃到了（+292.7%）；定投在均線下資金幾乎全投但只在均線下的月份買，四檔都低於定期定額。這不代表把比例調高就會贏（那是調參），也不代表在別的期間還是這個排序。
- 合成行情上的行為測試是這輪真正的「測試」：每種策略在已知形狀的行情上做了定義該做的事（含兩個反直覺的性質——RSI 反轉買太早賣太早、雙重確認在長跌後反彈永遠不買）。以後改 `trading_strategy` 的求值或成交，這 5 項會先抓到。
- 沒做：範本參數開放前端調整、多檔組合、比較表存檔、Screen 側 eslint（Screen 沒有 lint 腳本）、瀏覽器實測（兩個常駐工作要重啟後新端點才存在；FastAPI 與 Node 路徑由 pytest 的 `TestClient` 與 jest 的假伺服器覆蓋）。
- 另一個 session 同時在這個工作區做 Iteration 78（估值表、第八代實驗），`progress.md`／`AI/Doc/README.md` 兩邊都有未提交改動；本輪只在那些檔裡**加**自己的段落，沒動它的。它預告的下一輪請用 80 號。

## 變更檔案

修改：`Crawler/api.py`（兩個端點）、`Server/routes/sim.js`（兩條路由）、`Server/tests/helpers/fastapi-mock.js`、`Server/tests/http/sim.test.js`（+2）、`Screen/src/components/RuleBuilder.jsx`、`Screen/src/pages/TradingSim.jsx`、`Screen/src/services/api.js`、`AI/Doc/README.md`、`progress.md`
統一前端：`../meeting_front_end/src/stock/{components/RuleBuilder.jsx, pages/TradingSim.jsx, services/api.js}`
新增：`Crawler/trading_presets.py`、`Crawler/tests/test_trading_presets.py`（5 項）、`AI/experiments/iter79_presets.py`、`UnifiedModel/results/trading_presets_iter79.md`、`AI/Doc/Iterations/Iteration-79.md`
資料表：無（只讀 `market_daily_prices`／`stock_daily_prices`；`portfolio_runs` 不動）
審查：evidence-reviewer 第一輪 46／2／4 FAIL（incorrect：「擇時的七種全輸」與 2603 衝突、模板出處漏了 Iteration 62；unresolved：RSI「第 15 天」實跑是第 3 天、41.7 沒有斷言、−39 行、合成 0050 數字沒印——全部已改：測試加斷言、腳本印數字、四處措辭改掉）；第二輪 55／0／1 PASS（unresolved 只剩 RuleBuilder 行數——審查者沒有 Bash，已記 `checks.json` `rulebuilder-numstat-79`：60 加 28 減）
驗證：`checks.json` `pytest-79`（272 過）、`jest-79`（193 過）、`presets-run-79`（過）、`vite-build-79`（過）、`mfe-build-79`（過）、`mfe-eslint-79`（過）、`rulebuilder-numstat-79`、`evidence-reviewer-79`（pass）
重啟：**MoneyCrawlerApi**（`api.py` 與新模組）與 **MoneyApi**（`Server/routes/sim.js`）；兩個前端 push 後 GitHub Pages 約 3 分鐘
