# Iteration 70 — 第五代：Amihud 非流動性是第一條有效實作在開發期超過候選的文獻假設，驗證期過門檻但低於候選；隔夜短期持續不成立

**日期：** 2026-10-15
**依據：** 使用者：「使用者要『搜論文、記錄、以論文為基礎優化、不斷迭代、每代記錄』 至少找 10 篇以上論文」（同 Iteration 69，第五代）
**規則：** 第四代結果看過之後才登記本代（`AI/experiments/iter70_hypothesis.md`）；兩條假設都不是第四代的變體、不和第四代的新成分組合；只在開發期跑、一條一跑、不調參；valid 只給「過門檻且年化主動或 IR 超過 #30、tests 已過」的、一次；保留期未開；候選不換。

## 一、做了什麼

1. **H9 隔夜報酬的短期持續**（P28 Zhang, Tsai, Weng & Tsai 2023，台灣；P27 Aboody 等 2018）：新成分 `ovn1m` ＝ 最近 21 個交易日隔夜異常報酬（總異常報酬減日內）的累積，`win3+mom+ovn1m`。候選的 `mom` 跳過最近一個月，文獻說最近一個月的隔夜那一半會持續。
2. **H10 Amihud 非流動性**（P35 Amihud 2002）：新成分 `illiq` ＝ 過去 252 個交易日 |日報酬| ÷ 成交金額 的平均取 log，`win3+mom+illiq`。
3. `Market` 多 `ar_over`；`portfolio_signal.py` 多 `signal_ovn1m`、`signal_illiq`；tests +2（跑網格前先跑 `pytest -q tests/test_portfolio.py` 31 過；`checks.json` 裡的 `pytest-portfolio` 是 21:22 審查後補 `illiq` 邊界斷言再跑的那次、也是 31 過，跑網格前那次已被覆蓋）。dev 跑 #86、#87；#87 過門檻且兩項都超過 #30，依規則 valid 一次 → #88。
4. 結果檔 `UnifiedModel/results/portfolio_iter70_illiq.md`（`iter70_results.py`：指標表來自 `portfolio_runs.metrics`，加 Iteration 53 的 `rev_accel+mom` #53／#62 當對照；第三、四節對 dev 與 valid 每個訊號日實算 `illiq` 和流動性名次、`mom` 的等級相關，以及兩個組合前 20 名的流動性名次中位數；第五節從 `portfolio_positions` 算四個 run 實際成交持股的全市場流動性名次分佈；第六節每年池內大型股對小型股的等權報酬。第四～六節是描述性的，不得用來設計下一條假設）。

## 二、結果（`portfolio_runs.metrics`；結果檔 `portfolio_iter70_illiq.md`）

| N | 設定 | 段 | 年化主動 | IR | 追蹤誤差 | 相對最大落後 | 月勝率 | 換手 | 調倉次數 |
|---|---|---|---|---|---|---|---|---|---|
| 30 | win3+mom-t3-tsmcest（候選） | dev | +8.64% | 0.67 | 12.9% | −14.7% | 55% | 3.6 | 35 |
| 38 | win3+mom-t3-tsmcest（候選） | valid | +15.71% | 1.085 | 14.5% | −16.7% | 66% | 3.27 | 25 |
| 53 | rev_accel+mom-t3-tsmcest（Iteration 53） | dev | +11.10% | 0.857 | 13.0% | −12.8% | 62% | 4.11 | 38 |
| 62 | rev_accel+mom-t3-tsmcest（Iteration 53） | valid | +8.52% | 0.608 | 14.0% | −16.6% | 53% | 3.5 | 25 |
| **86** | **win3+mom+ovn1m-t3-tsmcest**（H9） | dev | +6.31% | 0.493 | 12.8% | −14.0% | 55% | 3.58 | 35 |
| **87** | **win3+mom+illiq-t3-tsmcest**（H10） | dev | **+11.09%** | **0.847** | 13.1% | −13.5% | 55% | 3.59 | 35 |
| **88** | **win3+mom+illiq-t3-tsmcest**（H10） | valid | **+14.14%** | **0.98** | 14.4% | −16.1% | 69% | 3.46 | 25 |

逐年主動報酬（結果檔第二節）：

| N | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024（～09） |
|---|---|---|---|---|---|---|---|
| 30／38 候選 | +11.7% | +6.4% | +18.1% | +1.6% | +15.2% | +18.8% | +3.2% |
| 86 | +14.1% | +2.3% | +11.1% | +0.6% | | | |
| 87／88 | +13.1% | +4.8% | +19.7% | **+9.2%** | +13.7% | +15.1% | +3.9% |

`illiq` 的診斷（結果檔第三節；流動性名次 1 = 池內 60 日成交金額最大）：

| 段 | 訊號日 | ρ(illiq, 流動性名次) 中位數 | ρ(illiq, mom) 中位數 | 前 20 流動性名次中位數 win3+mom | 同 win3+mom+illiq | 前 20 重疊中位數 |
|---|---|---|---|---|---|---|
| dev | 35 | 0.56 | 0.34 | 80 | 152 | 12 |
| valid | 25 | 0.57 | 0.40 | 80 | 143 | 14 |

## 三、讀法

- **H9 不成立。** `win3+mom+ovn1m` +6.31%／IR 0.493，低於候選、IR 沒過門檻，valid 不跑。一個月的隔夜持續（P28）在月調倉、前 300 的框架下沒有增量；加上 Iteration 69 的 `imom`（拿掉隔夜那一半也變差），隔夜／日內拆解家族關閉：兩個方向都試過、都低於把兩者加在一起的 `mom`。
- **H10 是 19 次文獻試驗（N 70～88）裡第一條有效實作在開發期超過候選的**（錯版 `win3+resmom` #72 dev +10.30%／0.849 也超過，但它是帶截距 OLS 的一個月反轉、tag=void，不計）：+11.09%／0.847 對 +8.64%／0.67，相對最大落後也較小（−13.5% 對 −14.7%）。驗證期 +14.14%／0.98 **過門檻**。19 次裡跨段過門檻的有三個家族：`win3+resmom`（#79／#80，驗證期被錯版先看過、不乾淨）、`win3+mom+rev_yoy3`（#74／#77）與本輪的 `win3+mom+illiq`（#87／#88）；候選以外還有 Iteration 53 的 `rev_accel+mom`（#53／#62），不在這 19 次內。但 #88 **低於候選的驗證期 #38**（+15.71%／1.085）：2022、2023 各少 1.5、3.7 pp，2024 多 0.7 pp。開發期的優勢幾乎全在 2021 年（+9.2% 對 +1.6%）。
- **`illiq` 在這個池子裡就是「往小的那端偏」：** 和流動性名次的等級相關中位數 0.56，前 20 名持股的池內流動性名次中位數從 80 變成 152（池子 270 檔）；實際成交持股的**全市場**名次（結果檔第五節，`portfolio_positions.filled`）中位數 #87 174 對 #30 100、#88 160 對 #38 102。所以 #87／#88 的讀法是「流動性前 300 裡偏向後半段的動能股」。**但開發期的優勢不是單純的 size 效應**：結果檔第六節用池內「名次 101～300 等權減 1～100 等權」描述每年小型股相對大型股的報酬，2021 年只有 +3.3%，2018 年 +15.6%、2019 年 −20.6%、2020 年 −10.5%；#87 對候選的逐年差是 +1.4／−1.6／+1.6／+7.6 pp，和這條線對不上。2021 那 7.6 pp 從哪裡來，本輪沒有再拆（拆下去就是事後分析）。驗證期也過門檻是它比 `rev_accel+mom`（驗證期掉到 +8.52%）強的地方。
- **成本的 caveat（結果檔第五節量了，沒重跑）：** 回測對全市場流動性名次 ≤ 200 的股票滑價 0.15%、> 200 才 0.30%（`portfolio_backtest.COSTS`）。#87 的成交持股有 59% 名次 > 150、40% > 200（候選 #30：35%、22%）；#88 為 54%、37%（#38：33%、20%）。所以 #87／#88 比候選多了約一倍的持股付 0.30% 滑價（成本/年 1.57% 對 1.49% 已含），而名次 150～200 那一段付的是和候選一樣的 0.15%、成交金額卻較小——實際滑價可能更高，沒有做敏感度（那是新的 N，由使用者決定）。
- **事前登記的兩個瑕疵（方法審查抓到）：** 登記檔 `iter70_hypothesis.md` 的檔案時間 21:07:54 早於 dev 日誌 21:08:46（`ls --time-style=full-iso`），跑後沒改過；但 H10 段寫「門檻是兩者都要」而規則段寫「年化主動**或** IR 超過 #30」，本輪 #87 兩項都超過所以無影響，下一代統一成「兩項都要超過」。
- **候選不換（規則：換候選是使用者的決定）。** 要換成 `win3+mom+illiq` 的理由：開發期兩項都超過候選、驗證期過門檻、相對最大落後較小；不換的理由：驗證期低於候選、優勢集中在 2021、成本未量化、DSR 用 N=88 只有 0.488。不建議再做「`win3+mom+illiq` 加別的成分」的事後組合。
- **N = 88，保留期未開。** 文獻驅動的研究五代（Iteration 66～70）共 19 次試驗：有效實作裡 1 次在開發期超過候選（#87），3 個家族跨段過門檻（resmom、rev_yoy3、illiq）；驗證期數字超過候選 #38 的只有 `win3+resmom` #80（+16.30%／1.177），但它的驗證期已被錯版 #76 先看過、不算乾淨確認；乾淨的一次性確認裡沒有一個超過候選。

## 變更檔案

修改：`Crawler/portfolio_signal.py`（`Market.ar_over`、`signal_ovn1m`、`signal_illiq`、`_single`、`SINGLE_SIGNALS`）、`Crawler/tests/test_portfolio.py`（+2，31 項）、`AI/Doc/Papers.md`（P27／P28／P35 狀態、第五節第五代、第六節）、`AI/Doc/README.md`、`progress.md`
新增：`AI/experiments/iter70_hypothesis.md`、`iter70_grid.json`、`iter70_results.py`、`iter70_dev.log`、`iter70_valid.log`、`UnifiedModel/results/portfolio_iter70_illiq.md`
資料表：`portfolio_runs` #86～#88
審查：strategy-critic PASS（九條意見全部處理）；evidence-reviewer 三輪 43／3／2 → 42／2／2 → 33／1／1 仍 FAIL：第三輪唯一 incorrect 是「65～70 未提交」應為 66～70，第三輪後已改；unresolved 一條（跑網格前那次 31 過被同名覆蓋）附在完成報告
驗證：`checks.json` `iter70-dev`、`iter70-valid`（exit 0）、`pytest`（234 過，21:10，在補 `illiq` 邊界斷言之前）、`pytest-portfolio`（31 過，21:22，補斷言之後；跑網格前那次 31 過已被同名覆蓋）、`iter70-prereg-mtime`（登記檔 mtime 21:07:54 早於 dev 日誌 21:08:46 的 `ls` 輸出）、`iter69-70-git-hunks`（對 dec7174 的 `git diff --stat`）；沒跑 jest 與 vite build（Node 與前端沒改）。本輪改的 Python 檔只有 `portfolio_signal.py` 與 `tests/test_portfolio.py`；`git status` 另有 `Crawler/portfolio_backtest.py` M，那是 Iteration 67 的 `run` 掛 `bench_hist`（66～70 都未提交，dec7174 就是 Iteration 65 的 commit，git status 分不出輪次）。`git diff dec7174 -- Crawler/portfolio_signal.py` 只有三個 hunk（`Market.__init__` 139 行附近、`signal_rev_streak` 之後新增的訊號函式、`_single`），`signal_mom`／`signal_win3` 不在任何 hunk 裡，所以正式策略 `win3+mom` 沒改、MoneyCrawlerApi 不重啟也不影響它；但常駐 API 載的是舊版模組，`ovn1m`／`illiq` 在重啟前不會出現在 API 內，目前沒有端點需要它們
