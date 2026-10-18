# Iteration 84：資料更新後已登記 run 的原樣重算（不寫 portfolio_runs）

**產生：** 2026-10-18 14:39　**腳本：** `AI/experiments/iter84_recompute.py`　**事前登記：** `AI/experiments/iter84_hypothesis.md`

每列用 `portfolio_runs.params` 原樣重算（`portfolio_backtest.run(save=False)`），與日誌 `metrics` 與 `portfolio_positions` 比。「持股差」＝（訊號日, 股票）對稱差的筆數／日誌筆數。
DSR 不列：重算時的 N 是下一號、與日誌不可比。

| run | 名稱 | 段 | 指標 | 日誌 | 重算 | 差 |
|---|---|---|---|---|---|---|
| #30 | win3+mom-t3-tsmcest-dev | dev | ann_active | +8.64% | +8.64% | 相同 |
|  |  |  | info_ratio | 0.67 | 0.67 | 相同 |
|  |  |  | tracking_error | +12.89% | +12.89% | 相同 |
|  |  |  | rel_mdd | -14.69% | -14.69% | 相同 |
|  |  |  | cagr_port | +29.78% | +29.78% | 相同 |
|  |  |  | cagr_bench | +19.46% | +19.46% | 相同 |
|  |  |  | turnover_annual | 3.6 | 3.6 | 相同 |
|  |  |  | n_rebalances | 35 | 35 | 相同 |
| | | | 持股差 | 735 筆 | 735 筆 | 0 筆（相同） |
| #38 | win3+mom-t3-tsmcest-valid | valid | ann_active | +15.71% | +15.71% | 相同 |
|  |  |  | info_ratio | 1.085 | 1.085 | 相同 |
|  |  |  | tracking_error | +14.48% | +14.48% | 相同 |
|  |  |  | rel_mdd | -16.65% | -16.64% | +0.01 pp |
|  |  |  | cagr_port | +30.27% | +30.27% | 相同 |
|  |  |  | cagr_bench | +12.58% | +12.58% | 相同 |
|  |  |  | turnover_annual | 3.27 | 3.27 | 相同 |
|  |  |  | n_rebalances | 25 | 25 | 相同 |
| | | | 持股差 | 525 筆 | 525 筆 | 0 筆（相同） |
| #44 | win3+mom-t3-tsmcest-dev+valid | dev | ann_active | +7.05% | +7.05% | 相同 |
|  |  |  | info_ratio | 0.564 | 0.564 | 相同 |
|  |  |  | tracking_error | +12.49% | +12.49% | 相同 |
|  |  |  | rel_mdd | -14.69% | -14.69% | 相同 |
|  |  |  | cagr_port | +25.29% | +25.29% | 相同 |
|  |  |  | cagr_bench | +17.04% | +17.04% | 相同 |
|  |  |  | turnover_annual | 3.81 | 3.81 | 相同 |
|  |  |  | n_rebalances | 68 | 68 | 相同 |
| | | | 持股差 | 1428 筆 | 1428 筆 | 0 筆（相同） |
| #87 | win3+mom+illiq-t3-tsmcest-dev | dev | ann_active | +11.09% | +11.09% | 相同 |
|  |  |  | info_ratio | 0.847 | 0.847 | 相同 |
|  |  |  | tracking_error | +13.10% | +13.10% | 相同 |
|  |  |  | rel_mdd | -13.47% | -13.47% | 相同 |
|  |  |  | cagr_port | +32.71% | +32.71% | 相同 |
|  |  |  | cagr_bench | +19.46% | +19.46% | 相同 |
|  |  |  | turnover_annual | 3.59 | 3.59 | 相同 |
|  |  |  | n_rebalances | 35 | 35 | 相同 |
| | | | 持股差 | 735 筆 | 735 筆 | 0 筆（相同） |
| #88 | win3+mom+illiq-t3-tsmcest-valid | valid | ann_active | +14.14% | +14.14% | 相同 |
|  |  |  | info_ratio | 0.98 | 0.98 | 相同 |
|  |  |  | tracking_error | +14.43% | +14.43% | 相同 |
|  |  |  | rel_mdd | -16.12% | -16.12% | 相同 |
|  |  |  | cagr_port | +28.49% | +28.49% | 相同 |
|  |  |  | cagr_bench | +12.58% | +12.58% | 相同 |
|  |  |  | turnover_annual | 3.46 | 3.46 | 相同 |
|  |  |  | n_rebalances | 25 | 25 | 相同 |
| | | | 持股差 | 525 筆 | 525 筆 | 0 筆（相同） |
| #90 | win3+relmom-t3-tsmcest-dev | dev | ann_active | +10.12% | +10.12% | 相同 |
|  |  |  | info_ratio | 0.785 | 0.785 | 相同 |
|  |  |  | tracking_error | +12.89% | +12.89% | 相同 |
|  |  |  | rel_mdd | -14.06% | -14.06% | 相同 |
|  |  |  | cagr_port | +31.54% | +31.54% | 相同 |
|  |  |  | cagr_bench | +19.46% | +19.46% | 相同 |
|  |  |  | turnover_annual | 3.6 | 3.6 | 相同 |
|  |  |  | n_rebalances | 35 | 35 | 相同 |
| | | | 持股差 | 735 筆 | 735 筆 | 0 筆（相同） |
| #92 | win3+relmom-t3-tsmcest-valid | valid | ann_active | +15.19% | +15.19% | 相同 |
|  |  |  | info_ratio | 1.07 | 1.07 | 相同 |
|  |  |  | tracking_error | +14.20% | +14.20% | 相同 |
|  |  |  | rel_mdd | -15.82% | -15.82% | 相同 |
|  |  |  | cagr_port | +29.68% | +29.68% | 相同 |
|  |  |  | cagr_bench | +12.58% | +12.58% | 相同 |
|  |  |  | turnover_annual | 3.31 | 3.31 | 相同 |
|  |  |  | n_rebalances | 25 | 25 | 相同 |
| | | | 持股差 | 525 筆 | 525 筆 | 0 筆（相同） |
| #94 | win3+mom+fflow-t3-tsmcest-dev | dev | ann_active | +10.33% | +10.33% | 相同 |
|  |  |  | info_ratio | 0.875 | 0.875 | 相同 |
|  |  |  | tracking_error | +11.81% | +11.81% | 相同 |
|  |  |  | rel_mdd | -11.49% | -11.49% | 相同 |
|  |  |  | cagr_port | +31.80% | +31.80% | 相同 |
|  |  |  | cagr_bench | +19.46% | +19.46% | 相同 |
|  |  |  | turnover_annual | 3.61 | 3.61 | 相同 |
|  |  |  | n_rebalances | 35 | 35 | 相同 |
| | | | 持股差 | 735 筆 | 735 筆 | 0 筆（相同） |
| #96 | win3+mom+fflow-t3-tsmcest-valid | valid | ann_active | +14.34% | +14.34% | 相同 |
|  |  |  | info_ratio | 1.054 | 1.054 | 相同 |
|  |  |  | tracking_error | +13.61% | +13.61% | 相同 |
|  |  |  | rel_mdd | -15.39% | -15.39% | 相同 |
|  |  |  | cagr_port | +28.72% | +28.72% | 相同 |
|  |  |  | cagr_bench | +12.58% | +12.58% | 相同 |
|  |  |  | turnover_annual | 3.44 | 3.44 | 相同 |
|  |  |  | n_rebalances | 25 | 25 | 相同 |
| | | | 持股差 | 525 筆 | 525 筆 | 0 筆（相同） |
| #106 | win3+mom+nsir-t3-tsmcest-dev | dev | ann_active | +9.77% | +9.77% | 相同 |
|  |  |  | info_ratio | 0.852 | 0.852 | 相同 |
|  |  |  | tracking_error | +11.47% | +11.47% | 相同 |
|  |  |  | rel_mdd | -11.49% | -11.49% | 相同 |
|  |  |  | cagr_port | +31.13% | +31.13% | 相同 |
|  |  |  | cagr_bench | +19.46% | +19.46% | 相同 |
|  |  |  | turnover_annual | 3.41 | 3.41 | 相同 |
|  |  |  | n_rebalances | 35 | 35 | 相同 |
| | | | 持股差 | 735 筆 | 735 筆 | 0 筆（相同） |
| #108 | win3+mom+nsir-valid-top20-t3-tsmcest | valid | ann_active | +13.97% | +13.97% | 相同 |
|  |  |  | info_ratio | 1.062 | 1.062 | 相同 |
|  |  |  | tracking_error | +13.15% | +13.15% | 相同 |
|  |  |  | rel_mdd | -13.01% | -13.01% | 相同 |
|  |  |  | cagr_port | +28.31% | +28.31% | 相同 |
|  |  |  | cagr_bench | +12.58% | +12.58% | 相同 |
|  |  |  | turnover_annual | 3.43 | 3.43 | 相同 |
|  |  |  | n_rebalances | 25 | 25 | 相同 |
| | | | 持股差 | 525 筆 | 525 筆 | 0 筆（相同） |
| #54 | rev_accel-t3-tsmcest-valid | valid | ann_active | +4.25% | +4.25% | 相同 |
|  |  |  | info_ratio | 0.459 | 0.459 | 相同 |
|  |  |  | tracking_error | +9.25% | +9.25% | 相同 |
|  |  |  | rel_mdd | -9.54% | -9.54% | 相同 |
|  |  |  | cagr_port | +17.36% | +17.36% | 相同 |
|  |  |  | cagr_bench | +12.58% | +12.58% | 相同 |
|  |  |  | turnover_annual | 4.35 | 4.35 | 相同 |
|  |  |  | n_rebalances | 33 | 33 | 相同 |
| | | | 持股差 | 693 筆 | 693 筆 | 0 筆（相同） |
| #58 | rev1m-t3-tsmcest-valid | valid | ann_active | -6.05% | -6.05% | 相同 |
|  |  |  | info_ratio | -0.503 | -0.503 | 相同 |
|  |  |  | tracking_error | +12.04% | +12.04% | 相同 |
|  |  |  | rel_mdd | -19.85% | -19.85% | 相同 |
|  |  |  | cagr_port | +5.77% | +5.77% | 相同 |
|  |  |  | cagr_bench | +12.58% | +12.58% | 相同 |
|  |  |  | turnover_annual | 4.4 | 4.4 | 相同 |
|  |  |  | n_rebalances | 33 | 33 | 相同 |
| | | | 持股差 | 693 筆 | 693 筆 | 0 筆（相同） |
| #62 | rev_accel+mom-t3-tsmcest-valid | valid | ann_active | +8.52% | +8.52% | 相同 |
|  |  |  | info_ratio | 0.608 | 0.608 | 相同 |
|  |  |  | tracking_error | +14.01% | +14.01% | 相同 |
|  |  |  | rel_mdd | -16.62% | -16.62% | 相同 |
|  |  |  | cagr_port | +22.17% | +22.17% | 相同 |
|  |  |  | cagr_bench | +12.58% | +12.58% | 相同 |
|  |  |  | turnover_annual | 3.5 | 3.5 | 相同 |
|  |  |  | n_rebalances | 25 | 25 | 相同 |
| | | | 持股差 | 525 筆 | 525 筆 | 0 筆（相同） |

## 摘要

| run | 名稱 | 段 | tag | 年化主動 日誌 → 重算 | 差 | 持股差 | 基準相同 |
|---|---|---|---|---|---|---|---|
| #30 | win3+mom-t3-tsmcest-dev | dev | candidate | +8.64% → +8.64% | +0.00 pp | 0/735 | 是 |
| #38 | win3+mom-t3-tsmcest-valid | valid | candidate | +15.71% → +15.71% | +0.00 pp | 0/525 | 是 |
| #44 | win3+mom-t3-tsmcest-dev+valid | dev | candidate | +7.05% → +7.05% | +0.00 pp | 0/1428 | 是 |
| #87 | win3+mom+illiq-t3-tsmcest-dev | dev |  | +11.09% → +11.09% | +0.00 pp | 0/735 | 是 |
| #88 | win3+mom+illiq-t3-tsmcest-valid | valid |  | +14.14% → +14.14% | +0.00 pp | 0/525 | 是 |
| #90 | win3+relmom-t3-tsmcest-dev | dev |  | +10.12% → +10.12% | +0.00 pp | 0/735 | 是 |
| #92 | win3+relmom-t3-tsmcest-valid | valid |  | +15.19% → +15.19% | +0.00 pp | 0/525 | 是 |
| #94 | win3+mom+fflow-t3-tsmcest-dev | dev |  | +10.33% → +10.33% | +0.00 pp | 0/735 | 是 |
| #96 | win3+mom+fflow-t3-tsmcest-valid | valid |  | +14.34% → +14.34% | +0.00 pp | 0/525 | 是 |
| #106 | win3+mom+nsir-t3-tsmcest-dev | dev |  | +9.77% → +9.77% | +0.00 pp | 0/735 | 是 |
| #108 | win3+mom+nsir-valid-top20-t3-tsmcest | valid |  | +13.97% → +13.97% | +0.00 pp | 0/525 | 是 |
| #54 | rev_accel-t3-tsmcest-valid | valid |  | +4.25% → +4.25% | +0.00 pp | 0/693 | 是 |
| #58 | rev1m-t3-tsmcest-valid | valid |  | -6.05% → -6.05% | +0.00 pp | 0/693 | 是 |
| #62 | rev_accel+mom-t3-tsmcest-valid | valid |  | +8.52% → +8.52% | +0.00 pp | 0/525 | 是 |

portfolio_runs：重算前 N 108／108 列，重算後 N 108／108 列（沒有新增）。
耗時 3.0 分。保留期未開。
