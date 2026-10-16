# Iteration 74 — 交易模擬的大量假資料改走記憶體：合成行情 + 攔下三個資料函式與 get_conn，8 年 × 61 檔上 50 條隨機規則／200 筆隨機指令的帳務不變量全過，整個過程不連任何資料庫

**日期：** 2026-10-16
**依據：** 使用者：「找方案在交易模擬建立大量假資料進行測試」→ 給三個方案後：「方案 A，測試資料不要汙染到真實股票資料」
**規則：** 不碰正式庫 `Stock`、也不碰測試庫 `Stock_crawler_test`——新測試沒有 `db` marker，且 `get_conn` 在測試期間被換成直接丟例外；不改模擬器本體（`trading_sim.py`、`trading_strategy.py`、`trading_rules.py`、`trading_replay.py` 一行未動）；不跑回測、`portfolio_runs` 的 N 不動。

## 一、做了什麼

1. **方案選擇**（2026-10-15 先量過才選；量測數字待確認——腳本在暫存區、repo 沒有來源）：兩個模擬器只透過三個函式碰資料——`portfolio_paper.market_days`、`trading_replay.load_prices`、`trading_replay.load_bench`——其餘是純計算（`trading_strategy.py`、`trading_sim.py`、`trading_rules.py` 裡沒有 `get_conn`）。
   另一條路「灌測試庫」因為 `market_days` 要每天 ≥ 500 列才算交易日，8 年要 1,085,760 列、寫入 22.4 秒（1 年 135,720 列、2.5 秒；**待確認**：量測腳本在暫存區，沒留進 repo），且使用者要求假資料不得汙染真實股票資料，所以採記憶體方案。
2. **`Crawler/tests/helpers/fake_market.py`**（新增）：
   - `make_market(ids, start, end, seed, lock_prob, warmup_days=450, vol, drift, lock_ids)`：每檔幾何隨機漫步（日報酬 N(0.03%, 2%) 夾在 ±10%），開盤在前收附近、高低包住開收，`prev_close` 是每檔自己的上一筆；從 `start − warmup_days` 起（規則模擬的指標要 420 天暖機）。一字鎖照 `trading_rules.is_locked` 的定義做：高＝低且離前收 ≥ `LIMIT_LOCK`（0.095），所以鎖的那天貼在前收 × 1.1 或 × 0.9（過程敘述、repo 無舊版：第一版只做「開高低收同價」沒貼漲跌停，測試抓到會成交，改掉）。
   - `patch(monkeypatch, market)`：換掉三個資料函式；路由照正式庫——`0050` 只在 `table='stock_daily_prices'` 找得到、其他股票只在 `market_daily_prices`，所以 `trading_sim.load_prices_any` 的回退路徑也會被走到。另外把 `db.connection.get_conn`、`portfolio_paper.get_conn`、`trading_replay.get_conn` 都換成丟 `RuntimeError('fake_market：這個測試不得連資料庫…')`。
   - `random_rules(ids, rng, n, market, capital)`：14 種條件都可能抽到（均勻 `rng.choice`，沒有斷言 50 條裡全出現）、三成包成 and／or 群組、`max_times` 與 `cooldown` 隨機；`random_instructions(ids, days, rng, n, market, capital)`：含週末日期測順延。買進數量按資金 1%～30% 與該檔第一個收盤縮放（過程敘述、repo 無舊版：第一版用固定 100 元估股價，種子 0 一筆就把資金買光、只剩 4 筆成交，改掉）。
   - `check_invariants(r, capital)`：兩個模擬器共用的結果結構——現金不為負、持股為正、成交價量為正、費稅不為負（買單稅是 0）、`gross = shares × price`、淨值序列日期遞增且 nav／bench 為正；**帳要對**：期末現金 = 資金 − Σ買(成交額＋手續費) ＋ Σ賣(成交額 − 手續費 − 稅)（容差 0.01 × (筆數 + 1)）、每檔期末股數 = Σ買股 − Σ賣股、賣不超過持股、`final.value = cash + Σ持股市值`、`metrics.final_nav = final.value`。
3. **`Crawler/tests/test_trading_fuzz.py`**（新增，15 項，沒有 `db` marker）：產生器可重現與 OHLC 合理；`patch` 後三個 `get_conn` 都丟例外、路由正確；規則模擬 5 個種子 × 50 條（`MAX_RULES`）；指令模擬 5 個種子 × 200 筆（`MAX_INSTRUCTIONS`），每筆最後不是成交就是略過（`trades + skipped == 200`）、成交日不早於指令日、只落在平日；`0050` 規則走回退表、每月 1 日買 8 年 = 96 次；一字鎖股票天天鎖 → 指令全略過（`一字鎖死`／`期間內沒輪到執行`）、規則觸發 12 次 `unfilled` 一字鎖死、現金不變；8 年上限仍擋住。
4. **統計腳本** `AI/experiments/iter74_fuzz_stats.py` → `UnifiedModel/results/trading_fuzz_iter74.md`（同一個合成市場、同一組種子）。

## 二、結果

合成市場：61 檔 × 2,408 日（含暖機；期間 2018-01-01～2025-12-31 內 2,088 日）、一字鎖 397 個股票日、產生 0.39 秒（結果檔第一行）。

| 種子 | 規則 | 成交 | 觸發紀錄（截尾 400） | 期末持股檔數 | 秒 |
|---|---|---|---|---|---|
| 0 | 50 | 19 | 400 | 11 | 1.02 |
| 1 | 50 | 34 | 140 | 8 | 0.92 |
| 2 | 50 | 382 | 400 | 10 | 0.99 |
| 3 | 50 | 176 | 400 | 12 | 0.98 |
| 4 | 50 | 367 | 400 | 10 | 1.11 |

| 種子 | 指令 | 成交 | 略過 | 略過原因 | 秒 |
|---|---|---|---|---|---|
| 0 | 200 | 46 | 154 | 現金不夠 93、沒有持股可賣 61 | 0.06 |
| 1 | 200 | 37 | 163 | 現金不夠 99、沒有持股可賣 64 | 0.06 |
| 2 | 200 | 53 | 147 | 現金不夠 82、沒有持股可賣 65 | 0.06 |
| 3 | 200 | 26 | 174 | 現金不夠 112、沒有持股可賣 62 | 0.06 |
| 4 | 200 | 38 | 162 | 現金不夠 90、沒有持股可賣 72 | 0.06 |

（來源：`UnifiedModel/results/trading_fuzz_iter74.md`；總報酬欄在結果檔裡，是假行情上的數字、沒有意義，不抄進來。）

驗證（`AI/progress/checks.json`；summary 只記 exit 0，測試數來自 pytest 輸出）：`pytest-74` 256 過（原 241 ＋ 15；2026-10-16 10:27 UTC）、`jest-unit-74` 44 過（Node 沒改，順帶確認）。沒跑 `vite build`（前端沒改）、沒跑 Server 的完整 `npm test`（只動 Crawler 的 tests）。新測試單獨跑 6.28 秒（`checks.json` `pytest-fuzz-74`，15 過）。

## 三、讀法

- 這一輪的「結果」是**不變量成立**，不是任何報酬數字：合成行情沒有資訊，總報酬只反映隨機規則碰巧做了什麼。
- 10 趟隨機模擬（共 1,178 筆成交：規則 978、指令 200）帳都對、沒有例外，表示現有兩個模擬器在長期間、多規則、含一字鎖與順延的情況下現金／持股／費稅的會計是一致的；這是回歸保護網，不是對策略的任何判斷。
- 隨機指令略過率 73%～87%——原因全是「現金不夠」與「沒有持股可賣」，是隨機買賣的自然結果（賣單不看有沒有持股），不是模擬器問題；順延最多 5 次後每筆都落在成交或略過其中一邊（`trades + skipped == 200` 五個種子都成立）。
- 「不汙染真實資料」靠兩層：新測試不用 `db` marker、不碰 `clean_db`；`patch` 把 `get_conn` 攔下——任何沒被三個替身接住的資料庫存取會立刻 `RuntimeError`，`test_patch_blocks_every_db_path` 直接驗這件事。`db.connection` 之外有自己 `import get_conn` 的模組（`portfolio_paper`、`trading_replay`）也一併換掉；其他模組若日後也在模組層匯入 `get_conn` 且被模擬器用到，要加進 `patch` 的清單——沒加的話 pytest 下會連到 `CRAWLER_TEST_DB`（`config.py` 第 50 行：設了就取代 `Stock`），不會碰正式庫，但就不再是「不連庫」。
- 要在儀表板上手動操作大量假資料（原方案 C）這輪沒做：那要灌測試庫並把 FastAPI 指到它，使用者沒要。
- 沒改模擬器本體、沒改 API、沒改 schema——不用重啟常駐工作。

## 變更檔案

修改：`AI/Doc/README.md`（迭代表加一列）、`progress.md`
新增：`Crawler/tests/helpers/fake_market.py`、`Crawler/tests/test_trading_fuzz.py`（15 項）、`AI/experiments/iter74_fuzz_stats.py`、`UnifiedModel/results/trading_fuzz_iter74.md`、`AI/Doc/Iterations/Iteration-74.md`
資料表：無（`portfolio_runs` N 不動；本輪新增的測試與腳本都不寫 `Stock`／`Stock_crawler_test`。整套 `pytest-74` 裡既有的 `db` 測試照常對測試庫 truncate／seed，與本輪無關；2026-10-15 量測灌庫耗時那次寫過測試庫、當場 `truncate_all` 清掉，無紀錄、待確認）
審查：evidence-reviewer 第一輪 43／4／7 FAIL（秒數、措辭已改；待確認見各處）→ 第二輪 17／0／8 PASS（`checks.json` `evidence-reviewer-74`；unresolved 皆為已標待確認的暫存區量測與過程敘述）
驗證：`checks.json` `pytest-74`（256 過）、`pytest-fuzz-74`（新檔單跑 15 過）、`jest-unit-74`（44 過）；沒跑 `vite-build`、沒跑 Server 完整 `npm test`
重啟：不需要
