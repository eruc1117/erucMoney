# Iteration 57 — 「程式交易」頁：候選策略的月清單 × 你的持股與現金 → 下單指令、登記、對帳

**日期：** 2026-10-09
**依據：** 使用者：「再新增一個頁面是給程式交易的」。接在 Iteration 54（紙上交易）與 56（買多少股分頁）之後：56 把目標權重換成股數但不知道使用者實際持股，所以換月的「賣多少」算不出來；這一頁補上。
**規則：** 沒有券商 API，這一頁只「算」不「做」——指令由人到券商 App 下，執行後登記進既有的交易台帳（`POST /holdings/trades`），台帳仍是唯一的事實來源。程式只動「策略範圍」內的股票，使用者自己買的持股一律不動。

## 一、做了什麼

### 純函式：`Server/lib/tradingPlan.js`（`buildPlan`、`nextSignalDate`）

| 規則 | 內容 |
|---|---|
| 策略範圍 | 清單裡的股票 ∪ 台帳 note 以 `[程式交易]` 開頭的股票；範圍外的持股另列 `untouched`、不算總資產 |
| 目標股數 | 總資產 = 可投入現金 ＋ 範圍內持股市值；目標 = floor(總資產 × 目標權重 ÷ 參考價)；參考價 = 清單帶的最新收盤，沒有就用持股表最後收盤，都沒有就略過並警告 |
| 最小下單 | 調整金額 < `minTrade`（預設 NT$1,000）不下單；退出清單（目標 0）例外，全賣 |
| 先賣後買 | 賣出淨額（扣手續費 0.1425%、證交稅 0.3%）加進可用現金；買進總成本（含手續費）超過可用現金就從金額最大的買單縮股數到放得下（寧可少買不透支） |
| 費用 | 零股最低 1 元、整股最低 20 元（整股與 `tradeLedger` 一致） |
| 偏離 | Σ\|現在權重 − 目標權重\| ÷ 2，執行前／後各算一次 |
| 下一個訊號日 | 每月 11 日起第一個平日（候選規則，`portfolio_paper.signal_date_for_month`）；只避週末不知假日，頁面寫「約」 |

### 路由：`Server/routes/trading.js`（`requireUser`）

- `GET /trading/plan?cash=&min_trade=`：清單從 FastAPI `/portfolio/candidate` 的 `current_list`（新的 `lib/proxy.js fetchFastAPI`，拿回 JSON 在 Node 端算，不是轉給前端）；持股從 `user_holdings` 加最後收盤；範圍從 `user_trades.note`。回清單資訊、下一個訊號日、`orders`／`positions`／`untouched`／`warnings`／`summary`、登記用的 `note`（`[程式交易] 清單 YYYY-MM-DD`）。
- `GET /trading/log`：台帳裡 note 以 `[程式交易]` 開頭的交易，另按清單日期分批（筆數、買、賣、費用、日期範圍）。
- 沒有清單 404、FastAPI 連不上 503、參數不是數字 400。

### 頁面：`Screen/src/pages/AlgoTrading.jsx`（側欄「程式交易」）、`meeting_front_end/src/stock/pages/AlgoTrading.jsx`（資產群組，需登入）

可投入現金（10／30／50／100 萬快捷鍵，存 localStorage）與最小下單金額 → 產生指令。六格：總資產、賣／買筆數、執行後現金、權重偏離前後、紙上帳戶對 0050、策略範圍檔數。
指令表先賣後買：勾選「已執行」、成交價可改、成交日可改 →「登記已執行的 N 筆」逐筆呼叫 `addTrade`（note 帶清單日期）；「複製指令文字」給券商 App 用。
再來是策略範圍內的部位表（持有／目標／權重／本次動作）、不動的其他持股、執行紀錄（按清單分批的磁磚 ＋ 明細），頁尾寫清楚規則與費率。

## 二、結果

| 檢查 | 結果 | 來源 |
|---|---|---|
| `tests/unit/tradingPlan.test.js` 7 項 | 費用門檻、空手買齊（權重合計 100% 時手續費放不下 → 台積電 20 股縮成 19 並警告）、只調差額且 200 元的調整不下單、範圍外不動／退出全賣、現金不夠縮單後現金 ≥ 0、沒參考價略過、先賣後買、下一個訊號日（10/11 週日 → 10/12；當天算；跨年） | `checks.json` name=jest |
| `tests/http/trading.test.js` 7 項 | 匿名 401、cash 非數字 400、空手 10 萬三檔買單與 note、自己買的 0050 不動不算總資產、登記 2303 後進 managed／總資產／log 分批、另一個使用者看不到 | 同上 |
| Server jest 全套 | 175 項、16 套通過 | `checks.json` name=jest（2026-10-09） |
| Screen vite build | 通過 | `checks.json` name=vite-build |
| meeting_front_end `npm run build`（react-scripts） | 通過 | 本 session 執行輸出（不在 checks.json） |
| 頁面 | 本機 Vite ＋ 不帶登入的預覽（:3004，`req.user` 固定 admin、`POST /holdings/trades` 回 403 不登記）看過：以正式庫的清單（訊號日 2026-09-11、21 檔、參考價至 2026-10-07）與 30 萬現金算出 21 筆買單、偏離 50% → 0.6%、執行後現金 3,622 | `events.jsonl` 的 navigate／screenshot 事件 |

## 三、讀法

1. 這一頁和 56 的「買多少股」差在**知道你現在有什麼**：有持股才有賣單、才有「只調差額」，換月時退出清單的會自動出現賣單。
2. 範圍的判斷靠台帳 note 前綴，所以**一定要從這一頁登記**（或自己在 note 寫 `[程式交易]`），否則下個月程式不知道那檔是它買的、不會替你賣。
3. 30 萬以下台積電一檔吃六成、其餘每檔約 6,000 元，零股股數小（1～5 股的有好幾檔），手續費比例高；這是候選策略「台積電固定持 0050 權重」的結構，不是頁面的問題。
4. 沒做的：券商 API 下單、成交回報自動對帳（現在是人填成交價）、假日表（下一個訊號日只避週末）、限價單的價格建議（現在是參考價 = 最新收盤）。

## 變更檔案

新增：`Server/lib/tradingPlan.js`、`Server/routes/trading.js`、`Server/tests/unit/tradingPlan.test.js`、`Server/tests/http/trading.test.js`、`Screen/src/pages/AlgoTrading.jsx`、`meeting_front_end/src/stock/pages/AlgoTrading.jsx`。
修改：`Server/lib/proxy.js`（`fetchFastAPI`）、`Server/app.js`（掛 `/trading`）、`Server/tests/helpers/fastapi-mock.js`（候選回應補 `current_list`）、`Screen/src/services/api.js`、`Screen/src/App.jsx`、`Screen/src/components/Sidebar.jsx`、`Screen/src/pages/WorkProgress.jsx`（空狀態內距）、`meeting_front_end/src/stock/{nav.js,services/api.js}`、`AI/Doc/README.md`、`Server/README.md`、`progress.md`。
