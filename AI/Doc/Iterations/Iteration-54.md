# Iteration 54 — 階段 4 紙上交易：模擬帳戶、每日排程、月調倉頁的檢討區

**日期：** 2026-10-09
**依據：** 計畫分頁的階段 4；使用者：「開始做階段 4 紙上交易」。候選 #44（`win3+mom --tranches 3 --tsmc-weight est`）。
**前提：** 保留期（2024-10 起）仍未開；紙上交易是「新資料」的第一段，與保留期一起做最後判定。

## 一、做了什麼

### 模擬帳戶：`Crawler/portfolio_paper.py`，migration 025

| 表 | 內容 |
|---|---|
| `portfolio_paper_state` | 一列：起始日 2026-10-09、起始資金 1,000,000、現金、候選 run_id 44 |
| `portfolio_paper_trades` | 每筆模擬成交：訊號日、成交日、股數（零股）、開盤價、手續費 0.0855%、賣出稅 0.3%；一字鎖死記 `filled=false` |
| `portfolio_paper_nav` | 每個交易日的淨值、現金、0050 還原收盤 |
| `portfolio_live_list` | 改成留歷史（同一訊號日覆蓋，各月各留；unique (rebalance_date, stock_id)） |

**和計畫原本寫法不同**：計畫寫「user_trades 加 account 欄位」，但那張表綁使用者、用移動平均成本重放、給「我的持股」頁用；模擬帳戶要的是「照清單機械式成交、每天結算對 0050」，
混進去兩邊都難對帳，所以另開三張表。

`run_daily(today)` 三步、每步以日期判斷、可補跑：
1. **成交**：每一份算出來但還沒成交的清單，在它之後第一個有行情的日子開盤成交。先賣（不在清單的全賣、超過目標的賣超過部分）後買，
   買單按比例縮以留手續費，股數取整；一字鎖死（高 = 低且相對前收 ≥ 9.5%）不成交、現金留著。清單與持股相同時留一筆 0 股的痕跡，免得一直被當成待成交。
2. **結算**：起始日起每個有全市場行情（≥ 500 檔）、還沒結算的日子，用**該日為準**的持股與現金（補跑過去的日子不能用之後的成交——第一版就踩到這個，測試抓到）。
3. **訊號日**：本月（與上月，補跑用）11 日起第一個有行情的交易日，還沒有清單就用候選參數算（`portfolio_backtest.current_list`，點時，從 2018 算到該日只取名單）。

### 排程：`job_portfolio_paper` 每日 18:40

全市場日線 18:30 進來之後跑；啟動補跑：18:40 已過且結算最後日早於今天就補。`test_scheduler.py` +2。模擬帳戶沒開就略過。

### API 與頁面

`GET /portfolio/paper`（FastAPI → Node 代理 → 匿名可讀）：狀態、檢討（起始日起總報酬、0050、主動報酬、逐月主動報酬對回測預期的月均）、成交紀錄、持股、待成交清單。
月調倉頁加「紙上交易」卡（Screen 與 meeting_front_end）：六個數字磁磚、模擬帳戶對 0050 的曲線、逐月表、成交表。

### 測試

`tests/test_portfolio_paper.py` 4 項（訊號日＝11 日起第一個有行情日；開戶只能一次；開盤成交的股數與現金對到小數；結算與檢討；鎖死不成交、換名單賣舊買新、賣出有稅；沒帳戶／沒行情的略過）。
全部：爬蟲 pytest、Server jest `portfolio.test.js` +1、`migrations.test.js` 25 個。

## 二、時程

- 2026-10-09 開戶，全現金。10 月 11 日是週六 → **10 月 13 日收盤算第一份清單、14 日開盤成交**。
- 之後每月同樣規則。三個月（2027-01）後對照回測預期（候選月主動報酬均值約 +0.57%、月勝率 57%），再決定要不要開保留期與小額實單。

## 三、沒做的

- 與回測預期的差距只做了「月均主動報酬、月勝率」的對照；追蹤誤差帶（±1.96 × 月追蹤誤差）之後再加。
- 0050 真實持股權重仍用估計值；每月清單的台積電權重會隨估計值變，記在 `portfolio_live_list.target_weight`。
- 小額實單（階段 5）未動。

## 變更檔案

新增：`Crawler/portfolio_paper.py`、`Crawler/tests/test_portfolio_paper.py`、`Server/migrations/025_portfolio_paper.sql`。
修改：`Crawler/portfolio_backtest.py`（清單留歷史）、`Crawler/portfolio_api.py`、`Crawler/api.py`、`Crawler/scheduler.py`、`Crawler/tests/test_scheduler.py`、`Crawler/tests/helpers/db_setup.py`、
`Server/routes/portfolio.js`、`Server/tests/helpers/fastapi-mock.js`、`Server/tests/http/portfolio.test.js`、`Server/tests/db/migrations.test.js`、
`Screen/src/pages/PortfolioLab.jsx`、`Screen/src/services/api.js`、`meeting_front_end/src/stock/{pages/PortfolioLab.jsx,services/api.js}`。
