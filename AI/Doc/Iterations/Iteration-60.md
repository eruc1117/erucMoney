# Iteration 60 — 交易模擬開放給未登入者：自訂交易指令跑實際日線給收益，歷史回放也不用登入

**日期：** 2026-10-09
**依據：** 使用者：「程式交易 1. 開啟模擬功能，給未登入者使用 2. 當使用者給出交易指令後，可以設定區間，模擬跑完後得收益」。
**規則：** 公開的東西只讀資料庫、不寫任何帳戶或表；輸入有上限（指令 4000 字／200 筆、期間 8 年）、靠全域 rate-limit 擋濫用；價格、費率、對 0050 的指標算法和回放（Iteration 59）同一份。

## 一、做了什麼

### 自訂交易指令：`Crawler/trading_sim.py`

- `parse_instructions(text)`：一行一筆「日期 買/賣 代號 數量」。日期收 `2024-01-15`／`2024/01/15`／`20240115`；買賣收中英文；數量收 `10股`、`2張`（= 2000 股）、`50000元`（執行那天開盤換算）、賣出的 `全部`／`all`；`#` 之後是註解。壞行收進 `errors`（行號、原文、原因），其餘照跑。
- `simulate(instructions, start, end, capital)`：指令日當天有行情就當天開盤市價成交，否則順延到下一個有行情的日子（沒行情、一字鎖死都順延，股數型與金額型都最多 5 次，之後略過並寫原因）；賣超過持股縮到持股（標「部分」）、沒持股可賣或金額不夠一股就略過並寫原因；期末持股以最後收盤估值。
  成交用 `trading_rules.fill_orders`、價格用 `trading_replay.load_prices`（還原價）、指標用 `trading_replay._metrics`——三份模擬（引擎、回放、指令）同一套數學。
- 回：指標（總報酬、0050、主動、年化、追蹤誤差、IR、月勝率、回撤）、淨值序列、成交（指令日 → 實際成交日、價、費、損益）、略過的指令、期末持股、已實現損益、費用、caveat、看不懂的行。

### 公開 API

- FastAPI `POST /trading/sim` `{text, start, end, capital}`（驗日期、長度、資金）。
- Node `Server/routes/sim.js`，掛在 `/sim`，**沒有登入中介層**（只有全域 rate-limit）：`GET /sim/replay`（轉 `/trading/engine/replay`，白名單八個鍵）、`POST /sim/run`（驗 text／start／end／capital 後轉 `/trading/sim`）。`/trading/*` 仍要登入。

### 頁面

- `Screen/src/components/ReplayPanel.jsx`：Iteration 59 的回放分頁抽成元件，`fetchReplay` 由頁面給（程式交易頁用登入的 `/trading/engine/replay`，公開頁用 `/sim/replay`）。
- `Screen/src/pages/TradingSim.jsx`（側欄「交易模擬」）：分頁**自訂指令**（指令文字框附範例、起迄、資金 → 五格、淨值對 0050 的圖、成交表、期末持股、略過的指令、看不懂的行）與**歷史回放**（ReplayPanel）。
- 統一前端 `meeting_front_end`：同一份元件與頁面；`nav.js` 的「預測」群組加 `simulate`（沒有 `personal`，**匿名可用**，不會顯示 🔒）。儀表板 `Screen` 本身整站要登入，所以「給未登入者」是指 erucmoney.com 這邊。

### 補：簡易模式（同日稍後，使用者：「交易指令 給簡易版模板化」）

`TradingSim.jsx` 的自訂指令分頁改成兩種模式：**簡易（表單／模板）**——日期、買／賣、股票（追蹤股下拉可選）、數量＋單位（股／張／元／全部）一筆一筆加，或套模板「買進持有」（起始日一筆金額）、「定期定額」（每月固定日期固定金額，到期末）、「進出一次」（起始日買、結束日全賣），清單每列顯示自動產生的指令文字，可刪；**進階（文字）**——原本的文字框。切到進階時把簡易產生的文字帶過去。後端不變（同一個 `POST /sim/run`）。
本機預覽：定期定額 0050 每月 5 日 10 萬、2024-01-02～09-30 → 九筆指令、總報酬 +15.99%（0050 +40.25%）。

## 二、結果

| 檢查 | 結果 | 來源 |
|---|---|---|
| `Crawler/tests/test_trading_sim.py` 3 項 | 解析（六種寫法、四種壞行）；當天開盤成交、金額換股、順延到 10/13、全部賣出、賣超縮到持股、沒行情的代號略過、指標與淨值序列；守門（空指令、日期不在期間、全看不懂、沒行情、超過 8 年、期末估值） | `checks.json` name=pytest |
| Crawler pytest 全套 | 215 項通過（含 0050 只在 stock_daily_prices 的補查：ETF 不在全市場日線，模擬改成找不到就到追蹤股表找） | 同上 |
| `Server/tests/http/sim.test.js` 6 項 | 匿名 GET /sim/replay 200 且只轉白名單；匿名 POST /sim/run 200、body 原樣轉、capital 預設 100 萬；四種 400 | `checks.json` name=jest（183 項、17 套） |
| Screen vite build、meeting_front_end build | 通過 | `checks.json` name=vite-build、mfe-build |
| 正式 API 匿名呼叫 | 重啟 MoneyApi／MoneyCrawlerApi 後，不帶 token `POST :3001/sim/run`（三行指令、2024-01-02～09-30、30 萬）回 `available: true`；`GET /sim/replay` 200 | `checks.json` name=sim-anon |

## 三、讀法

1. 「給使用者指令、設區間、跑完給收益」是最直接的模擬：沒有策略、沒有規則，就是「照你說的做會怎樣」。它和回放、引擎共用成交與指標的程式，所以三邊的數字可以互相對照。
2. 公開就代表不能寫：這兩個端點只讀（日線、0050、回放的清單取自 `portfolio_positions`／`portfolio_runs`），不寫 `portfolio_*`、`trading_*`、`user_*` 任何一張表。rate-limit 是 `.env` 的 `RATE_LIMIT_PER_MIN`（範例 300／分）。
3. 沒做的：匯入 CSV、盤後零股集合競價模型、分享連結（把指令與結果存起來給別人看）、多次模擬的比較。
4. evidence-reviewer 審過一輪：46 條主張 43 verified、2 incorrect（金額型指令沒行情時無限順延——程式已改成也計次 5 次；「不碰 portfolio_*」改成「只讀不寫」）、1 unresolved（meeting_front_end build 輸出，已用 record_check 記成 mfe-build）。

## 變更檔案

新增：`Crawler/trading_sim.py`、`Crawler/tests/test_trading_sim.py`、`Crawler/sim_anon_evidence.py`（只讀，印匿名呼叫的證據）、`Server/routes/sim.js`、`Server/tests/http/sim.test.js`、`Screen/src/components/ReplayPanel.jsx`、`Screen/src/pages/TradingSim.jsx`、`meeting_front_end/src/stock/{components/ReplayPanel.jsx,pages/TradingSim.jsx}`。
修改：`Crawler/api.py`（`POST /trading/sim`）、`Server/app.js`（掛 `/sim`）、`Server/tests/helpers/fastapi-mock.js`、`Screen/src/pages/AlgoTrading.jsx`（改用 ReplayPanel）、`Screen/src/services/api.js`、`Screen/src/App.jsx`、`Screen/src/components/Sidebar.jsx`、`meeting_front_end/src/stock/{pages/AlgoTrading.jsx,services/api.js,nav.js}`、`AI/Doc/README.md`、`Server/README.md`、`progress.md`。
