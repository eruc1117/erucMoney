# Iteration 88 — 紙上交易從沒拿到 2026-10-12 的清單：訊號日傍晚算清單時成交日還沒行情，`current_list` 回上個月那份、引擎記成「新清單」；改成訊號日當天就算目標持股、成交日先估，10 月清單補上並產生 21 張買單

**日期：** 2026-10-19（本來編 87，另一個 session 同時在做 Iteration 87「交易模擬加匯入／匯出」，改編 88；`checks.json` 裡 `pytest-87`／`pytest-87-full`／`live-list-87`／`engine-run-87` 是同一批結果的舊名）
**依據：** 使用者問「現在 8 W 0050 跟 7 W 2330 如何調整」→ 查正式策略的本月清單時發現清單還停在 2026-09-11
**規則：** 只改 live 清單的產生路徑；回測引擎的迴圈、`portfolio_runs`、候選、保留期都沒動（N 114）；修完用真實資料驗證訊號日路徑與正常路徑逐檔相同

## 一、做了什麼

1. **現象**（`Crawler/logs/scheduler.log`、資料表）：模擬帳戶 2026-10-09 開戶 100 萬，到 10-19 仍是 100 萬現金、0 持股、`portfolio_paper_trades` 空；`portfolio_live_list` 只有 2026-09-11 那份；引擎 18:40 記「新清單 {'rebalance_date': '2026-10-12', 'n': 21, 'new': ['3006']}、調倉單 []」，10-15、10-16、10-17、10-19 四次一字不差（10-10、10-11 是「起始日到今天沒有行情」；10-12～10-14 18:40 沒有任何 `[排程/engine]` 紀錄）。
2. **原因**（`Crawler/portfolio_paper.py` `make_list` → `portfolio_backtest.current_list(run_id, as_of=訊號日)`）：`current_list` 跑 `simulate` 到 as_of，而 `rebalance_schedule` 要求**成交日在資料裡**（「成交日要在 end 之內」）；訊號日當天成交日還沒行情，10 月這次調倉不在排程裡，函式回「最後一次調倉」＝ 9 月那份。
   `make_list` 把它原樣回傳，`run_daily` 用自己手上的 `sd`（10-12）記成新清單、`list_exists(10-12)` 永遠 False、隔天再來一次；沒有清單就沒有調倉單。
   9 月那份清單能存在是因為它是 2026-10-09 用 `portfolio_backtest.py --current-list 44` 手動算的（Iteration 52，成交日 09-14 早已過去），不是排程算的——排程路徑從開戶起就沒有產生過任何一份清單（log 裡 `[paper] 訊號日 … 清單` 一次都沒出現）。
3. **修法**：
   - `portfolio_backtest.simulate` 回傳多 `units`／`holdings_order`／`tranche_queue`（期末狀態）。
   - 新 `_pending_targets()`：訊號日 s 當天的目標持股——和 `simulate` 迴圈裡調倉那一段同一套（`eligible` → `scores_on` → 台積電權重 est → 分批到期的那批 `release` → `build_targets`），只是不成交、不改狀態；分數不足回 None。
   - `current_list`：simulate 到 as_of 後，若 as_of 所在月的訊號日 s ≤ as_of、還沒處理、而且 `mkt.next_day(s)` 是 None（成交日沒行情）→ 用 `_pending_targets` 當這次的清單，`exec_date` 先估下一個平日（新 `next_weekday`；`trading_calendar` 沒有未來的假日，只避週末），回傳 `exec_estimated=True`。成交日行情到了再算會走正常路徑、覆蓋成真正的成交日（同訊號日覆蓋是原本的設計）。
   - `portfolio_paper.make_list(rebalance_date, run_id, today)`：as_of 改用 today，回傳多 `matched`（算出的清單日是不是要的那天）。
   - `portfolio_paper.run_daily`、`trading_engine.run_daily`：`matched` 才記新清單；不符就記 `pending` 並寫 warning／`trading_events` error，不再誤報。
   - 測試：`test_portfolio_paper` +1（`make_list` 回舊清單時不當新清單、as_of 是今天、`next_weekday` 跨週末）；`test_trading_engine` 三處假 `make_list` 改成新簽名。
4. **真實資料驗證**（`live-list-88`，`AI/experiments/iter88_livelist.py`）：`current_list(44, as_of=2026-10-12)` 走訊號日路徑（`exec_estimated=True`、估成交日 10-13）、`current_list(44, as_of=今天)` 走正常路徑（真成交日 10-13）：**21 檔代碼、名次、權重逐檔相同**；再對正式策略 live 列 #68 自己在 2026-10-12 的 `portfolio_positions`（`positions-check-88`）：21 檔、權重不同 0 筆。10 月清單 21 檔（台積電 60.5%、其餘 20 檔各約 2.0%），對 9 月沒有進出（`is_new` 0 檔；分批到期的那批被重新選回，到期那批的檔數沒另外印）。
5. **補跑引擎一次**（`engine-run-88`，`python trading_engine.py --daily`，紙上模式）：對 2026-10-12 的清單產生 21 張買單（`trading_orders` pending、合計 2,002 股（`positions-check-88`）、order_date 10-12、限價 ＝ 收盤 × 1.02），引擎下次跑會在 order_date 之後第一個有行情的日子（10-13）開盤成交——這是引擎原本的補跑規則；清單內容完全由 10-12 收盤前的資料決定（上一點已驗），補成交不含事後資訊，但帳面上會晚了一週才開始持有。

## 二、結果

| 驗證 | 結果 |
|---|---|
| `pytest-88` | 51 passed（`test_portfolio_paper` 6、`test_trading_engine` 5、`test_portfolio` 38、`test_portfolio_positions` 2；跑到全過之前有兩次失敗，都是測試本身的問題——假 `make_list` 簽名、`setdefault` 回傳值——輸出被同名紀錄覆蓋、沒另存） |
| `pytest-88-full` | 284 passed（全套，37.8 秒） |
| `live-list-88` | 訊號日路徑對正常路徑 21 檔逐檔相同；估成交日 10-13 ＝ 真成交日；`pending_lists(今天)` ＝ [2026-10-12] |
| `engine-run-88` | 21 張買單 pending；`new_list` None（清單已存在）、`guard` False |
| `positions-check-88` | 2026-10-12 清單對 #68 持股 21 檔、不同 0 筆；#68 9 月→10 月進出都是空、`is_new` 0；買單 21 張 2,002 股、order_date 10-12；`trading_events` 今晚 +1（orders） |
| `evidence-reviewer-88` | 三輪 37／5／5 FAIL → 17／1／1 FAIL → 3／0／1 PASS（incorrect：「每天」→ 四次、Iteration 64 → 52、#68 比對補 `positions-check-88`、test 檔數、`trading_events` 事件種類）；留一條 unresolved：中途兩次 pytest 失敗的輸出沒另存 |
| jest、vite build | **沒跑**——Node 與前端沒改 |

## 三、讀法

- 這不是回測或候選的問題：live 列 #68 每天 18:50 重算時成交日行情都已在，所以它的持股一直是對的；壞的只有「訊號日傍晚給紙上交易算清單」這條路，從開戶（10-09）起就沒成功過，之前沒人發現是因為 10-12 是開戶後第一個訊號日。
- 修法選「訊號日當天算目標、成交日先估」而不是「等成交日行情到了再算」：後者會讓清單晚一天出現、凱基實單（若接上）就不能在成交日開盤下單；前者和回測「11 日收盤算、次日開盤成交」同一個時點。代價是 `_pending_targets` 和 `simulate` 迴圈裡的調倉段是兩份相同邏輯（有註明），改一邊要改另一邊；真實資料驗證就是在抓這種不一致。
- 10 月清單對 9 月沒有進出是策略本身的結果（分批到期的那批被重新選回），不是修法造成；#68 自己的 `portfolio_positions` 同樣如此（`positions-check-88`）。
- **要重啟 `MoneyScheduler`**（`job_portfolio_paper` 走的 `trading_engine`／`portfolio_paper`／`portfolio_backtest` 都改了）與 **`MoneyCrawlerApi`**（`/portfolio/*` 載入 `portfolio_backtest`）；沒重啟前排程器記憶體裡仍是舊碼，但 10-12 的清單已存在、`list_exists` 為真，舊碼不會再誤報。
- 未解：訊號日估的成交日只避週末、不避假日（`trading_calendar` 沒有未來日期），實際成交日由紙上交易用「清單日之後第一個有行情的日子」決定，所以只影響頁面顯示的「成交日」字樣。

## 變更檔案

修改：`Crawler/portfolio_backtest.py`（`simulate` 回傳期末狀態、`next_weekday`、`_pending_targets`、`current_list`）、`Crawler/portfolio_paper.py`（`make_list`、`run_daily`）、`Crawler/trading_engine.py`（`run_daily`）、`Crawler/tests/test_portfolio_paper.py`（+1）、`Crawler/tests/test_trading_engine.py`（假 `make_list` 簽名）、`AI/Doc/README.md`、`progress.md`。
新增：`AI/experiments/iter88_livelist.py`、`AI/experiments/iter88_positions_check.py`、`AI/Doc/Iterations/Iteration-88.md`。
資料：`portfolio_live_list` +21 列（2026-10-12，run 44）、`trading_orders` +21（pending）、`trading_events` +1（orders；清單已存在所以沒有 signal 事件）；`portfolio_runs` 沒動。
