# Iteration 56 — 月調倉頁的「買多少股」分頁：輸入金額就換算成零股股數

**日期：** 2026-10-09
**依據：** 使用者：「月調倉多一個次分頁，功能是提供金額後回饋各股票要買多少股」
**規則：** 次分頁做成月調倉頁內的分頁，資料只加在既有的 `/portfolio/candidate` 回應裡，本輪沒有改 App.jsx／Sidebar.jsx／api.js（工作區裡這三檔的 M 是 Iteration 55 那個 session 的，待確認：兩個 session 的 diff 歸屬只能由使用者分辨）；本輪不 commit，留給使用者與 Iteration 55 一起處理。

## 一、做了什麼

### 資料：清單每檔帶最新收盤價（`Crawler/portfolio_api.py` `live_list`）

`portfolio_live_list` 最新訊號日那份清單，`LEFT JOIN LATERAL` 取 `market_daily_prices` 每檔最後一筆 `close_price > 0` 的收盤與日期；沒價格的留 `None`。
回應多 `price_date`（各檔價格日期的最大值）與每檔 `price`、`price_date`。`/portfolio/candidate` 的 `current_list` 跟著有。

### 頁面：分頁「總覽／買多少股」（`Screen/src/pages/PortfolioLab.jsx`，meeting_front_end 同一份）

分頁狀態存 localStorage（`pf_tab`），金額也存（`pf_buy_amount`，預設 30 萬；10／30／50／100 萬快捷鍵）。
換算 `planShares`：可用金額 = 投入 ÷ (1 + 0.0855%)（先留手續費，與紙上交易 `portfolio_paper.fill` 的縮單規則等價；回測 `portfolio_backtest.simulate` 的 need 另含滑價 0.15%／小型股 0.3%，頁面不留滑價，因為實際下單用限價單、沒有滑價假設）；每檔股數 = floor(可用 × 目標權重 ÷ 收盤價)；
手續費 = max(NT$1, round(成本 × 0.0855%))（零股最低費）；報買進成本、手續費、剩餘現金、投入比例，每檔另列「張＋零股」與實際權重。
表格依排名，台積電標「固定」、續抱標「續抱」、新進場 ★；沒價格的那檔標出來、股數 0。頁尾說明換月要先賣再買、賣出才有證交稅、小金額時高價股會吃掉權重。

### 測試與檢查

`tests/test_portfolio_paper.py::test_live_list_carries_latest_close_for_share_calculator`：最新訊號日那份清單（不是舊的）、每檔最新收盤與日期、沒行情的留 None。
`AI/progress/checks.json`：pytest 200 項通過、vite-build 通過（只有 chunk 大小警告）、jest-unit 36 項通過、`smoke-portfolio`（`Screen/smoke.mjs PortfolioLab` 掛載）通過、`live-list`（清單訊號日、檔數、價格日期、台積電權重與收盤的查詢輸出）——都在 2026-10-09。

## 二、結果

| 項目 | 值 | 來源 |
|---|---|---|
| 目前清單 | 訊號日 2026-09-11、21 檔 | `checks.json` 的 `live-list` 檢查輸出（`portfolio_api.live_list()`） |
| 價格日期 | 2026-10-07 | 同上 |
| 例：投入 30 萬 | 台積電 59.7% → 約 69 股（收盤 2,585）、其餘 20 檔各 2.0% → 每檔約 6,000 元 | 權重與收盤見 `live-list` 檢查輸出；股數 = floor(300000 ÷ 1.000855 × 0.597 ÷ 2585) = 69 |

## 三、讀法

- 這一頁是「把目標權重換成股數」的工具，不是建議。金額小時高價股（台積電 2,585 元）一檔就吃掉六成，低價股零頭多；30 萬以下要看剩餘現金與實際權重。
- 清單每月只更新一次；換月時先賣不在新清單的、再買 ★ 的，賣出才有 0.3% 證交稅——頁面有寫，但換月的「賣多少」還沒做（要知道使用者實際持股才算得出）。
- 價格是最後一個收盤，不是即時價；成交日開盤會差一點，紙上交易用的也是開盤價。

## 變更檔案

修改：`Crawler/portfolio_api.py`、`Screen/src/pages/PortfolioLab.jsx`、`meeting_front_end/src/stock/pages/PortfolioLab.jsx`、`Crawler/tests/test_portfolio_paper.py`。
新增：`Crawler/live_list_evidence.py`（只讀，印清單事實給 record_check 當證據）。未 commit（與 Iteration 55 的工作區一起由使用者處理）。
