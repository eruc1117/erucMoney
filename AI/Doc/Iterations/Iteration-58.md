# Iteration 58 — 程式交易引擎：選股、進出場、停損、下單規則寫成程式每天跑；券商先紙上、凱基接口留好；頁面給預測與觀察

**日期：** 2026-10-09
**依據：** 使用者：「程式交易（Program Trading）是把選股、進出場、停損及下單規則寫成程式，由電腦自動完成整個交易流程，用來取代人工盯盤與情緒化決策。是提供預測交易結果及觀察，預計接凱基的」。
Iteration 57 的頁面只做到「清單 → 指令由人下」，這一輪把中間那層補成引擎。
**規則：** 紙上模式的成交寫進同一本模擬帳戶（`portfolio_paper_*`），淨值曲線不分家；引擎只在 `trading_engine_state.enabled` 為真時接手排程，否則紙上交易照 Iteration 54 的方式跑；
live 模式沒設好券商就停下來記錯誤，不送任何單；本輪不開引擎（開不開由使用者決定——開了之後紙上交易的規則就從「次日開盤照單全收」變成「限價單＋停損」，和回測的對照會變）。

## 一、做了什麼

### 引擎：`Crawler/trading_engine.py`

| 規則 | 實作 |
|---|---|
| 選股 | 候選策略（`run_id`，預設 #44）每月 11 日起第一個交易日收盤算清單——沿用 `portfolio_paper.signal_date_for_month`／`make_list` |
| 進出場 | 清單出來當天收盤後 `gen_rebalance_orders`：退出的全賣、超過目標的賣超過部分、不足的買；股數以當天收盤估、買單留手續費並以「現金＋賣出淨額」按比例縮；每份清單只產生一次（沒有任何單也留一筆 0 股痕跡） |
| 停損 | 每天收盤 `gen_stop_loss_orders`：持股收盤 ≤ 平均成本 × (1 − `stop_loss_pct` 15%) → 隔天全賣（`stop_loss`）；已有待成交賣單的不重複 |
| 守門 | `relative_drawdown_breached`：帳戶對 0050 的相對回撤 ≤ −`rel_dd_guard` 10% → 該份清單的買單全部不產生（賣單照送），記 `guard` 事件 |
| 下單 | 零股限價：買 = 收盤 × (1 + `limit_slip` 0.5%)、賣 = 收盤 × (1 − 0.5%)；未成交隔天用新收盤重掛，`max_attempts` 3 次後取消 |
| 每日 | `run_daily(today)`：送待成交單（每張在 order_date 之後第一個有行情的日子）→ 紙上結算 → 訊號日算清單 → 所有還沒委託的清單產生委託 → 停損檢查；每一步以日期判斷，可補跑 |

規則存 `trading_engine_state.rules`（JSONB，缺的用 `RULES_DEFAULT`）；`configure()` 檢查鍵與值，`mode=live` 一定配 `broker=kgi`、`paper` 配 `paper`。

### 委託單與事件：migration 026

`trading_engine_state`（一列）、`trading_orders`（pending → filled／unfilled 重掛／cancelled／rejected；限價、原因、嘗試次數、成交價量、券商單號）、`trading_events`（signal／orders／fill／unfilled／cancelled／rejected／stop_loss／guard／error／config／no_quote）。

### 券商介面：`Crawler/brokers/`

- `base.py`：`Broker.execute(orders, exec_date) → [Fill]`、`positions()`、`cash()`、`configured()`；`BrokerNotConfigured`。
- `paper.py`：用隔天實際行情模擬零股限價單——買：開盤 ≤ 限價才成交（成交價 = 開盤）；賣：開盤 ≥ 限價；一字鎖死、沒行情 → 未成交；賣超過持股：沒持股拒絕、有持股就縮到持股數；買超過現金縮到放得下（不夠買 1 股拒絕）；成交寫 `portfolio_paper_trades`、更新現金。
- `kgi.py`：凱基官方 Python 套件 `kgiapp`（.NET Framework 4.5，要先向凱基申請）；`configured()` 檢查 `KGI_ID`／`KGI_PASSWORD`／`KGI_BRANCH`／`KGI_ACCOUNT` 與套件，接上前永遠回「未就緒」，`execute` 丟 `BrokerNotConfigured`。檔頭寫了接上時要做的四件事。

### 排程與 API

- `scheduler.job_portfolio_paper`（18:40）：引擎開著就跑 `trading_engine.run_daily`，否則照舊 `portfolio_paper.run_daily`。
- FastAPI：`GET /trading/engine/status|orders|events|forecast`、`POST /trading/engine/config|run`。Node `routes/trading.js` 代理：GET 登入即可，POST 限 admin，`mode` 亂給 400。
- `forecast()`：候選回測的年化主動報酬 0.0705 與追蹤誤差 0.1249 → 1／3／6／12 個月的期望、95% 區間、贏 0050 的機率（Φ(μ/σ)，假設月主動報酬近似常態且獨立）；開戶後給 12 個月的預期淨值帶，和模擬帳戶的實際相對淨值疊圖，算 z 值看有沒有出帶。回應裡附 caveat（DSR 0.13）。

### 頁面：`Screen/src/pages/AlgoTrading.jsx`（meeting_front_end 同一份），四個分頁

- **引擎**：開關、模式、券商就緒、下一個訊號日、委託統計、最後執行與錯誤、模擬帳戶；四條規則的文字；admin 可啟動／關閉、手動跑今天、切紙上／實單、改四個參數。
- **預測**：依據 run、回測指標、實際 vs 預期（z 值、在不在帶內）、四個期間的表、預期帶對實際的圖、caveat。
- **觀察**：模擬帳戶對 0050、淨值、待成交、最接近停損的那檔；停損監看表（成本、最後收盤、停損價、距停損，3% 內標紅）；引擎事件時間軸；委託單表（狀態篩選）。
- **手動指令**：Iteration 57 的內容原樣搬進來。

## 二、結果

| 檢查 | 結果 | 來源 |
|---|---|---|
| `Crawler/tests/test_trading_engine.py` 5 項 | 設定驗證與 live 未設定停下；清單 → 三張限價買單（限價 = 收盤 × 1.005、股數留手續費）→ 隔天開盤全成交、模擬帳戶有三筆、第二天不重複；開盤連續跳過限價 → 重掛兩次第三次取消、沒持股；停損觸發 → 賣單、限價賣不掉就重掛、不重複開單；相對回撤守門擋掉買單；預測的 12 個月 p_beat = Φ(0.0705/0.125) ≈ 0.714、1 個月 sd = 0.125/√12 | `checks.json` name=pytest |
| Crawler pytest 全套 | 205 項通過 | 同上（2026-10-09） |
| Server jest | 177 項、16 套通過（`trading.test.js` 8 項，含引擎代理 2 項；`migrations.test.js` 26 個） | `checks.json` name=jest |
| Screen vite build | 通過 | `checks.json` name=vite-build |
| meeting_front_end `npm run build` | Compiled with warnings（既有警告） | 本 session 輸出（不在 repo） |
| 常駐工作 | 重啟 MoneyApi（migration 026）、MoneyCrawlerApi（引擎端點）、MoneyScheduler（切換）；`GET :8000/trading/engine/status` 回 `enabled=false`、`broker_ready=true`，`/forecast` 回 run #44 的四個期間 | 本 session curl 輸出 |
| 頁面 | 本機 Vite ＋ 不帶登入的預覽（:3004）看過引擎／預測／觀察三個分頁：預測表 1 個月 +0.57%（56%）、3 個月 +1.72%（61%）、6 個月 +3.46%（65%）、12 個月 +7.05%（71%） | `events.jsonl` 的 navigate／screenshot 事件；數字可由 `/trading/engine/forecast` 重算 |

## 三、讀法

1. 「程式交易」四件事的對應：選股 = 候選清單（已有）、進出場 = 11 日調倉（已有）、停損 = 這一輪新加、下單規則 = 限價＋重掛（新加）。引擎的價值不在規則多巧，在**每一步都留痕**（委託、事件），人只看預測和觀察。
2. 預測表要這樣讀：12 個月 +7.05% 是「如果回測成立」的期望，95% 區間 −17% ～ +32% 很寬，贏 0050 的機率 71%；DSR 0.13 說候選本身還不能排除運氣。觀察頁的 z 值是把實際放回這個分布看有沒有出帶——出帶就是回測不成立的訊號。
3. 停損對月調倉策略是雙面刃：回測沒有停損（候選的 +7.05% 是無停損算出來的）。引擎開著之後，紙上交易就不再是回測的乾淨對照。要兩者都要，得開第二本模擬帳戶（沒做）。
4. 凱基：`kgiapp` 是 .NET 架構、Windows 限定、要申請；這台機器是 Windows 可以跑。接上去的四步在 `brokers/kgi.py` 檔頭。
5. 沒做的：第二本模擬帳戶（無停損對照）、live 模式的成交回報對帳、盤中即時價（現在用收盤算限價、隔天開盤成交）、假日表。

## 變更檔案

新增：`Crawler/trading_engine.py`、`Crawler/brokers/{__init__,base,paper,kgi}.py`、`Crawler/tests/test_trading_engine.py`、`Server/migrations/026_trading_engine.sql`。
修改：`Crawler/api.py`（六個端點）、`Crawler/scheduler.py`（引擎接手）、`Crawler/tests/helpers/db_setup.py`（三張表）、`Server/routes/trading.js`（引擎代理）、`Server/tests/helpers/fastapi-mock.js`、`Server/tests/http/trading.test.js`、`Server/tests/db/migrations.test.js`（26）、
`Screen/src/pages/AlgoTrading.jsx`（四分頁）、`Screen/src/services/api.js`、`Screen/src/App.jsx`（標題）、`meeting_front_end/src/stock/{pages/AlgoTrading.jsx,services/api.js,nav.js}`、`AI/Doc/README.md`、`Server/README.md`、`progress.md`、`AI/Doc/Iterations/Iteration-57.md`（審查後改測試項數）。
