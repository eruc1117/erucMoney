# Iteration 61 — 交易模擬的模組化輸入：條件 → 觸發買賣（均線、RSI、N 日報酬、停損停利、每月固定日），逐日用實際行情判斷

**日期：** 2026-10-09
**依據：** 使用者：「交易指令 給簡易版模板化」→「模塊化輸入是要可以設定條件，去觸發買跟賣」。先做的日期表單（同日稍早）留著當「日期指令」，主要入口改成條件規則。
**規則：** 公開、只讀（和 Iteration 60 一樣走 `/sim/*`）；條件在**收盤**判斷、動作在**下一個交易日開盤**市價成交（與引擎一致），日期類條件當天開盤；成交、價格（還原價）、指標算法與其他模擬同一份。

## 一、做了什麼

### 後端：`Crawler/trading_strategy.py`

規則 = `{stock_id, when:{type,…}, then:{side, qty, unit}, max_times, only_if_flat, cooldown}`。條件 14 種：

| 類型 | 意思 | 參數 |
|---|---|---|
| `price_below`／`price_above` | 收盤低於／高於某價 | x |
| `cross_above_ma`／`cross_below_ma` | 收盤由下往上穿過／由上往下跌破 n 日均線（前一日在另一邊） | n |
| `above_ma`／`below_ma` | 收盤在 n 日均線之上／下（狀態） | n |
| `rsi_below`／`rsi_above` | RSI(n，Wilder 平滑) 低於／高於 x | n、x |
| `change_below`／`change_above` | n 日報酬 ≤／≥ x% | n、x |
| `loss_from_cost`／`gain_from_cost` | 比平均成本（含手續費）低／高 x%（停損／停利；要有持股） | x |
| `monthly_day` | 每月 d 日起第一個交易日（當天開盤） | d |
| `on_date` | 指定日期當天開盤 | date |

動作：買（元／股／張）或賣（全部／股／張）。`max_times` 預設 1（每月固定日不限）、`only_if_flat` 指標類條件的買單預設「沒持股才買」（避免狀態條件每天加碼；日期類 `monthly_day`／`on_date` 的買單預設不擋）、`cooldown` 觸發後幾個交易日內不再觸發。
`validate_rules` 回逐條錯誤；`simulate_rules` 逐日：開盤先執行前一日觸發與日期類的單 → 結算 → 收盤判斷指標類條件 → 明天開盤。指標只算用得到的，暖機多抓 420 天。回指標、淨值序列、成交（附規則編號與文字）、**觸發紀錄**（觸發／成交／未成交／拒絕／略過與原因）、每條規則觸發次數、期末持股、沒行情的代號。上限 50 條、8 年。

### API 與頁面

- FastAPI `POST /trading/sim/rules`（先 `validate_rules`，錯誤 400）；Node `POST /sim/rules`（公開，驗陣列、≤ 50 條、日期、資金）。
- `Screen/src/components/RuleBuilder.jsx`：每條規則一列——股票（追蹤股可選）、「當」（條件下拉，參數欄位跟著變）、「就」買／賣、數量＋單位、最多次數、沒持股才買、冷卻；列下顯示自動產生的規則文字。模板四個：均線進出、停損停利、逢低加碼、RSI 反轉（套在指定的那檔）。結果：五格（含每條規則觸發次數）、淨值對 0050、觸發紀錄、成交、期末持股。
- `TradingSim.jsx` 自訂指令分頁改三種模式：**條件規則**（預設）、日期指令（表單）、進階（文字）。meeting_front_end 同一份。

## 二、結果

| 檢查 | 結果 | 來源 |
|---|---|---|
| `Crawler/tests/test_trading_strategy.py` 3 項 | 驗證與規則文字；指定日期買、停損在收盤觸發隔天開盤賣、價格條件只買一次、停利；2 日均線穿越（每月固定日那條已先持有 1 股時要關「沒持股才買」）、每月固定日一次、RSI 與跌破在最後一天觸發沒機會執行 | `checks.json` name=pytest |
| Crawler pytest 全套 | 218 項通過 | 同上 |
| `Server/tests/http/sim.test.js` 7 項 | 加：匿名 POST /sim/rules 200、rules 原樣轉、空陣列與 51 條 400 | `checks.json` name=jest（184 項、17 套） |
| Screen vite build、meeting_front_end build | 通過 | `checks.json` name=vite-build、mfe-build |
| 正式 API 匿名呼叫 | 重啟後不帶 token `POST :3001/sim/rules`（均線進出 2330 ＋ 每月 5 日 0050 1 萬，2024-01-02～09-30，30 萬）：均線買 9 次賣 8 次、總報酬 +15.39%（0050 +40.25%）、43 筆觸發紀錄 | `checks.json` name=rules-anon |
| 頁面 | 本機預覽：模板「停損停利」套在 2330 → 1/2 買 10 萬、+20% 停利賣出，總報酬 +2.39% | 截圖不在 repo；同一組規則用正式 API 重跑記在 `checks.json` name=rules-anon-stop |

## 三、讀法

1. 這才是使用者要的「模組化」：條件是可組合的積木，而不是先把日期寫死。日期指令與文字模式留著給「我就是要那天買」的人。
2. 收盤判斷、隔天開盤成交是刻意的：避免用當天收盤價成交的前視偏誤，也和引擎（紙上／凱基）的執行方式一致，所以同一條規則在模擬和實際執行會是同一個意思。
3. 兩個預設值很重要：`only_if_flat`（狀態條件像「在均線之上」每天都成立，不擋會天天買）、`max_times`＝1（除了每月固定日）。模板裡針對每條規則各自設好。
4. 範例結果（均線進出 2330 九進八出 +15% 對 0050 +40%）不是結論，是工具在動的證據——規則好不好要使用者自己用不同期間試。
5. evidence-reviewer 審過一輪：41 條主張 39 verified、1 incorrect（only_if_flat 預設漏寫日期類例外，已改）、1 unresolved（頁面截圖，已補 rules-anon-stop 證據）。
6. 沒做的：多條件 AND／OR、相對強弱（對 0050）、成交量條件、部位比例（%）動作、把規則一鍵送進引擎實際執行（引擎目前只跑候選策略的月清單）。

## 變更檔案

新增：`Crawler/trading_strategy.py`、`Crawler/tests/test_trading_strategy.py`、`Crawler/rules_anon_evidence.py`、`Screen/src/components/RuleBuilder.jsx`、`meeting_front_end/src/stock/components/RuleBuilder.jsx`。
修改：`Crawler/api.py`（`POST /trading/sim/rules`）、`Server/routes/sim.js`、`Server/tests/helpers/fastapi-mock.js`、`Server/tests/http/sim.test.js`、`Screen/src/pages/TradingSim.jsx`（三種模式）、`Screen/src/services/api.js`、`meeting_front_end/src/stock/{pages/TradingSim.jsx,services/api.js}`、`AI/Doc/README.md`、`Server/README.md`、`progress.md`。
