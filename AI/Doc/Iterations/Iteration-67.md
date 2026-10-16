# Iteration 67 — 三年期市場狀態閘門在 2018–2024 一次都沒觸發：結果與候選完全相同，市場狀態閘門家族關閉

**日期：** 2026-10-15
**依據：** 使用者：「……整理後以論文基礎優化各類模型，或是投資計畫，不斷自我迭代，每一代都要記錄。」（第二代）
**規則：** 事前登記（`AI/experiments/iter67_hypothesis.md`，寫在跑之前）；只在開發期跑一次；開發期沒超過候選就不跑驗證期、不試其他 lookback；保留期未開；候選不換。N 80 → 81。

## 一、做了什麼

1. **假設 H4**（Papers.md P6 Cooper–Gutierrez–Hameed 2004、P7 Du–Huang–Liao 2009 的第二次抽樣）：市場狀態改用文獻原本的三年（756 個交易日）而不是一年。一年期（#75，Iteration 66）反效果；預期三年期較不敏感、DOWN 月更少、結果介於 #75 與 #30 之間。事前判準：開發期沒超過 #30 就關閉這個家族，不再試其他 lookback。
2. **實作**：`portfolio_signal.py` 加 `STATE_GATES = {'~up3': 756, '~up': 252}`、`load_bench_history`（0050 還原收盤從 `stock_daily_prices` 另載 4 年）、`needs_bench_history`；`market_state_up` 有 `mkt.bench_hist` 時用它算；`portfolio_backtest.run` 在訊號含 `~up3` 時掛上 `bench_hist`。**不用 `warmup_days`**：全市場日線只從 2018-01-02 起（`market_data.PRICE_START`），暖機只會多載 0050；`estimate_tsmc_weight` 要 250 × 0.8 = 200 列全市場資料才估得出來，所以有沒有暖機，第一次估得出台積電權重都是 2018-10-26（全市場第 201 個交易日；結果檔第四節實跑兩種載法）。差別在暖機讓動能從 2018-01 就有值、那些月份會調倉並用 fallback 0.35 下單，而候選 #30 不暖機、2018-11-12 才第一次調倉（Iteration 64），到時估計已可用——載入範圍與 2018 年的調倉都會和 #30 不同。測試 `test_three_year_gate_uses_bench_history`（+1；本輪後 25 項，Iteration 68 再加 1 成 26）。
3. **實驗**：`AI/experiments/iter67_grid.json`（1 組 dev）。結果檔 `UnifiedModel/results/portfolio_iter67_gate3y.md`（`iter67_results.py`：指標表來自 `portfolio_runs.metrics`，閘門狀態對每個訊號日用 0050 長歷史實算一年與三年報酬）。

## 二、結果（`portfolio_runs.metrics`；結果檔 `portfolio_iter67_gate3y.md`）

| N | 設定 | 段 | 年化主動 | IR | 追蹤誤差 | 相對最大落後 | 換手 | 調倉次數 |
|---|---|---|---|---|---|---|---|---|
| 30 | win3+mom-t3-tsmcest（候選） | dev | +8.64% | 0.67 | 12.9% | −14.7% | 3.6 | 35 |
| 75 | win3+mom~up-t3-tsmcest（一年期閘門，Iteration 66） | dev | +5.17% | 0.413 | 12.5% | −15.2% | 3.66 | 36 |
| 81 | win3+mom~up3-t3-tsmcest（三年期閘門） | dev | +8.64% | 0.67 | 12.9% | −14.7% | 3.6 | 35 |

閘門狀態（結果檔第二節，0050 長歷史）：

| 段 | 訊號日 | 一年期 DOWN | 三年期 DOWN | 三年期報酬最低的訊號日 |
|---|---|---|---|---|
| dev 2018-01～2021-12 | 48 | 8（2018-10-11～2019-03-11、2019-08-12、2019-09-11） | **0** | 2020-04-13：+22.6% |
| valid 2022-01～2024-09 | 33 | 13（2022-05-11～2023-05-11） | **0** | 2024-03-11：+22.9% |

## 三、讀法

- **三年期閘門在開發期與驗證期一次都沒觸發。** 0050 在 2018–2024 的 81 個訊號日往回看三年的報酬最低也是 +22.6%（2020-04-13，COVID 低點後）；逐日看（結果檔第三節，2018-01-02～2024-09-30 共 1,643 個交易日）最低也是 +4.5%（2020-03-19）、沒有一天為負——台股這七年沒有「三年報酬為負」的交易日（一年期則有 411 天為負，最低 −26.3%，2022-10-25）。#81 因此和候選 #30 逐月一樣（主動 +8.64%、IR 0.67、35 次調倉），不是「過門檻」而是「沒有資訊」。驗證期不跑：事前判準是「沒超過 #30 就關閉」，而且閘門在驗證期也是 0 次 DOWN，跑了等於再複製一次 #38。
- **市場狀態閘門家族（一年、三年）關閉。** 一年期（#75）有觸發但反效果；三年期不觸發。Cooper–Gutierrez–Hameed 的狀態依賴在美股 1929–1995 有 DOWN 樣本可測，台股 2018–2024 用 0050 看沒有；Du–Huang–Liao 說台股 DOWN 更常出現，那是他們的樣本期間（見 P7），不是 2018 之後。要在這個資料上測「DOWN 之後動能更負」只能用更短的狀態窗口，而一年期已經失敗——再縮短就是搜參數，不做。
- **一年期 DOWN 月份的數字和 Iteration 66 不同（開發期仍是 8，驗證期 9 → 13）**：Iteration 66 用載入範圍內的 0050（2022-01 起只多載 130 天），2022-01～08 歷史不足算不出；這次用長歷史，2022-05～08 也判成 DOWN。#75 跑的是前者，數字沒錯，但代表「一年期閘門」若用長歷史會觸發得更多——不重跑（同家族、已失敗）。
- **N = 81，候選不換、保留期未開。** 這一代的代價是 1 次試驗，換到的是把一個家族關掉。審查指出這次試驗跑之前就能算出「開發期三年期 0 次觸發」（只依賴 0050），以後閘門類假設的事前登記要附預期觸發次數，省下 N。另外修了一個會影響之後網格的問題：`bench_hist` 掛在被快取共用的 `Market` 上，`run` 現在不需要時明確清掉。
- **下一代**從 Papers.md 第六節剩下的假設挑：以營收為條件的動能（P11）不需要新資料；法人籌碼（P18）要先補表。

## 變更檔案

修改：`Crawler/portfolio_signal.py`（`market_state_up` 用 `bench_hist`、`load_bench_history`、`STATE_GATES`、`needs_bench_history`、`_gated_parts`）、`Crawler/portfolio_backtest.py`（`run` 掛 `bench_hist`，不需要時清掉）、`Crawler/tests/test_portfolio.py`（+1 `test_three_year_gate_uses_bench_history`）、`AI/experiments/iter66_results.py`（標題依 N 範圍）、`AI/Doc/Papers.md`（P6／P7 狀態、第五節第二代、第六節）、`AI/Doc/README.md`、`progress.md`
新增：`AI/experiments/iter67_hypothesis.md`、`iter67_grid.json`、`iter67_results.py`、`iter67_dev.log`、`UnifiedModel/results/portfolio_iter67_gate3y.md`
資料表：`portfolio_runs` #81
驗證：`checks.json` `pytest-portfolio`、`pytest` 最新一筆是 26 過、229 過（本輪後是 25／228，Iteration 68 又加了 `test_momrev_keeps_only_positive_sue`，同名紀錄被覆寫）；沒跑 jest 與 vite build（Node 與前端沒改）
