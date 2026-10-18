# Iteration 84 — 資料更新後月調倉重算：候選與四個跨段候補 14 列持股名單全同、指標 112 格有 111 格相同（一格 0.01 pp 捨入），N 不動

**日期：** 2026-10-18
**依據：** 使用者：「以目前新的股票資料，重新分析月調倉」
**規則：** 只用日誌裡的參數原樣重算、不改任何參數、不寫 `portfolio_runs`（N 108 不動）、驗證期不拿來挑、保留期未開；事前登記 `AI/experiments/iter84_hypothesis.md`（`iter84-prereg-sha256`／`iter84-prereg-mtime` 14:38:09；檔頭寫的 14:52 是筆誤，附錄已更正）

## 一、做了什麼

Iteration 83「補更多家的股票資料」動了三樣東西，先弄清楚哪些會進月調倉：

| 83 的資料變動 | 進月調倉嗎 | 這輪怎麼查 |
|---|---|---|
| 追蹤股清單 26 → 68 檔（`stock_info.is_tracking`、FinMind 三張表、MOPS） | **不進**——股票池與訊號只讀全市場表 `market_*`（Iteration 48 起；`portfolio_signal.py` 開頭說明），追蹤股表只供儀表板、LSTM、新聞、投票 | 不用查 |
| 公司行動事件表改以交易所檔重寫（2003 起）＋ 減資 factor 上限 5 → 20 ＋ 全市場 `adj_close` 重算 | **進**——報酬用 `market_daily_prices.adj_close` | `adj-rebuild-dry-83`：全市場 2,621 檔只有 1529、2364、3043 三檔 2,331 列（除權日以前）變了；`iter84-inputs`：2018 起 3,768,564 列 adj_close NULL 0、≤ 0 列 0 |
| 0050 基準（`stock_daily_prices` 的 adj_close）隨 68 檔重建 | **進**——每個 run 的對手 | `iter84-inputs`：#44 存的 1,635 點 0050 淨值（2018-01-12～2024-09-30）對今天重建，最大相對差 0.0005%（2019-02-12，捨入）、期末 2.776225 對 2.776229 |

然後把 14 列已登記的 run 用 `portfolio_runs.params` 原樣重算（`portfolio_backtest.run(save=False)`，與 `--attach-series` 同一條路、不寫 `portfolio_runs`），指標與持股逐項對照：
候選 #30／#38／#44；四個跨段候補 #87／#88、#90／#92、#94／#96、#106／#108；持股過 1529 或 2364 的 #54／#58／#62（`adj-rebuild-evidence-83`）。
腳本 `AI/experiments/iter84_recompute.py`，結果檔 `UnifiedModel/results/portfolio_iter84_data_refresh.md`（`iter84-recompute`，14 列 3.0 分；先用 #38 煙霧 `iter84-recompute-smoke` 0.2 分）。

**為什麼不記成新的 N**：沒有新的選擇自由度——同一組參數、同一段期間、重算一次看資料有沒有動，和 `attach_series` 的既有慣例一樣（「不是新的實驗，N 不動」）。
事前登記寫明：審查者若認為該計 N，改記為新列即可、結論不變。

## 二、結果（`UnifiedModel/results/portfolio_iter84_data_refresh.md`）

| run | 名稱 | 段 | 年化主動 日誌 → 重算 | IR | 持股（訊號日, 股票）差 | `cagr_bench` |
|---|---|---|---|---|---|---|
| #30 | win3+mom-t3-tsmcest-dev（候選） | dev | +8.64% → +8.64% | 0.67 → 0.67 | 0／735 | 相同 |
| #38 | win3+mom-t3-tsmcest-valid（候選） | valid | +15.71% → +15.71% | 1.085 → 1.085 | 0／525 | 相同 |
| #44 | win3+mom-t3-tsmcest-dev+valid（候選、正式） | 全期間 | +7.05% → +7.05% | 0.564 → 0.564 | 0／1,428 | 相同 |
| #87／#88 | win3+mom+illiq | dev／valid | +11.09%／+14.14% 不變 | 0.847／0.98 不變 | 0／735、0／525 | 相同 |
| #90／#92 | win3+relmom | dev／valid | +10.12%／+15.19% 不變 | 0.785／1.07 不變 | 0／735、0／525 | 相同 |
| #94／#96 | win3+mom+fflow | dev／valid | +10.33%／+14.34% 不變 | 0.875／1.054 不變 | 0／735、0／525 | 相同 |
| #106／#108 | win3+mom+nsir | dev／valid | +9.77%／+13.97% 不變 | 0.852／1.062 不變 | 0／735、0／525 | 相同 |
| #54／#58／#62 | rev_accel／rev1m／rev_accel+mom（持有過 1529、2364） | valid | +4.25%／−6.05%／+8.52% 不變 | 0.459／−0.503／0.608 不變 | 0／693、0／693、0／525 | 相同 |

八項指標（年化主動、IR、追蹤誤差、相對最大落後、組合與 0050 年化、換手、調倉次數）14 列 112 格裡 111 格完全相同，唯一不同是 #38 的相對最大落後 −16.65% → −16.64%：
未捨入值是存的曲線 −0.166451 對重算 −0.166448（`iter84-mdd38`），差 3e-6、剛好跨過小數第四位的捨入邊界；兩條組合淨值逐日比值最大差 2.59e-6、0050 淨值 3.41e-6，來源是 0050 adj_close 重建的捨入。
持股名單 14 列共 9,639 筆（訊號日, 股票）全部相同（735 × 5 ＋ 525 × 6 ＋ 1,428 ＋ 693 × 2；只比名單，沒比權重與成交旗標——八項指標全同已涵蓋）。`portfolio_runs` 重算前後都是 N 108、108 列。
重算的 `end` 用日誌的 `period_end`（最後淨值日，開發期列是 2021-12-30）而不是段末 12-31，與 `attach_series` 同；2021-12-31 在 `market_daily_prices` 沒有列、12-30 是最後交易日（`iter84-calendar`），所以無差。**只驗了這 14 列**，其他 94 列沒重算，不能推成全部 108 列不變。

## 三、讀法

- **資料更新對月調倉沒有影響**：候選 #44（正式策略）、候選的開發期 #30 與驗證期 #38、四個跨段候補八列、連持有過被重算股票的 #54／#58／#62 都原樣重現。
  事前登記預期「#54／#58／#62 可能略變」沒發生——2364 的減資在 2021-10-08，這三列持有它是 2022-12～2023-03，12-1 月動能回看最早到 2021-12、沒跨過除權日；1529 的減資（2018-12）更早。
- **「新的股票資料」大多不進月調倉**：這輪補的 42 家追蹤股行情、籌碼、外資持股、MOPS 重大訊息都只在追蹤股表，月調倉的股票池（流動性前 300）與訊號從 Iteration 48 起只讀全市場表。
  想讓新資料進研究，要走全市場表路線（像 71／78／81 那樣建 `market_*` 表），不是加追蹤股。
- **Iteration 83 修的兩個公司行動問題，落到全市場表上只剩一個**：FinMind「權」列參考價的問題在全市場 adj_close 上沒留下差異（全市場事件從 Iteration 48 起就用交易所參考價表，`market_data.py` 檔頭；事件表重寫後 `adj-rebuild-dry-83` 只有三檔變動）；
  減資上限的問題在全市場表**存在過**——1529 ×9.09、2364 ×7.90、3043 ×5.00 原本被上限 5 略過，除權日以前 2,331 列 adj_close 是錯的（`adj-rebuild-83` 已重算）。#54／#58／#62 持有過 2364、#62 也持有過 1529，但都在除權日之後，重算結果一字不變。
- **候選不換、N 108、保留期未開**：這輪沒有新假設、沒有新 run。四個跨段候補的數字維持 Iteration 82 的結論（開發期超過候選、驗證期低候選 0.5～1.7 pp），換不換仍是使用者的決定。
- **沒做**：沒重跑保留期（#69 之後保留期只能開一次，沒有使用者要求）；沒重算 live 清單（`portfolio_live_list` 每日 18:50 由排程重算；0050 沒變、全市場表只動了三檔 2022-12 以前的列，live 最後一次調倉的 252 日回看碰不到，`portfolio_live_list` 也從未持有這三檔，`adj-rebuild-evidence-83`）。
- 待確認：`attach_series` 慣例（原樣重算不計 N）是否也該適用在這種「資料更新檢查」——事前登記寫了替代做法（改計 N 結論不變），由審查者判定。

| 驗證 | 結果 |
|---|---|
| `iter84-prereg-sha256`／`iter84-prereg-mtime` | ca80bca7…1c5d、2026-10-18 14:38:09（跑任何重算之前）；附錄更正後另記 `iter84-prereg-sha256-amended` |
| `iter84-inputs` | 14 列參數與指標；0050 淨值 1,635 點最大相對差 0.0005%；全市場 2018 起 adj NULL 0／≤0 0／3,768,564 列；0050 除息 32 筆、最近 2026-07-21；N 108 |
| `iter84-recompute-smoke` | #38 一列 0.2 分：指標相同、持股 0／525 差 |
| `iter84-recompute` | 14 列 3.0 分：111／112 格相同（#38 rel_mdd 0.01 pp）、持股名單 9,639 筆全同、N 108 → 108 |
| `iter84-calendar` | `market_daily_prices` 2021-12-29／30 各 1,731 列、12-31 無、下一日 2022-01-03 |
| `iter84-mdd38` | #38 相對最大落後未捨入：存的曲線 −0.166451、重算 −0.166448；淨值逐日比值最大差 2.59e-6（組合）、3.41e-6（0050） |
| `strategy-critic-84` | PASS：無前視（14 列的訊號都只讀訊號日以前的列）、成交時點同、驗證期未挑、`save=False` 沒寫任何表、不計 N 同意、成本與基準同；必改兩條措辭（「本來就不存在」、README 加 0050 例外）已改 |
| `evidence-reviewer-84` | 第一輪 25／6／2 FAIL（9,261 → 9,639、Iteration 71 → 48、「本來就不存在」與「沒有一列 run 碰到」、「全市場表沒變」、標題與 README 的「全部相同」、rel_mdd 歸因、審查紀錄名）→ 第二輪 16／2／1 FAIL（驗證表漏改 9,261、progress.md 產出漏 `iter84_mdd38.py`、12-31 沒交易缺查詢，三處已補）→ 第三輪 8／0／0 PASS，沒有未解的反對意見 |
| pytest／jest／vite build | **沒跑**——沒改 `Crawler/`、`Server/`、`Screen/` 的程式，只新增 `AI/experiments/` 腳本與文件 |

## 變更檔案

修改：`AI/Doc/README.md`、`progress.md`。
新增：`AI/experiments/iter84_hypothesis.md`（事前登記＋附錄）、`AI/experiments/iter84_inputs.py`、`AI/experiments/iter84_recompute.py`（審查後把 `n_before` 移到迴圈外、去掉重複查詢，輸出不變）、`AI/experiments/iter84_mdd38.py`、`AI/experiments/iter84_calendar.py`、`UnifiedModel/results/portfolio_iter84_data_refresh.md`（腳本產生）、`Crawler/logs/iter84_recompute.log`（`*.log` 不進 git）。
資料：沒有——`portfolio_runs`／`portfolio_positions`／`portfolio_run_series` 都沒寫。
