# Iteration 5 — FinMind volume 欄位對應 Bug 修復 + 行情全量回補

**日期：** 2026-08-06

## 問題（BUG 等級：資料層重大）

準備訓練 M3 籌碼模型時發現：**`stock_daily_prices` 25,736 筆中只有 1 筆有 `volume`**，
`turnover_value`、`transaction_count` 同樣全空。影響範圍：

- 前端 K 線圖成交量副圖（Spec 需求 13）一直無資料可畫
- 個股分析「成交量」指標卡、期間總成交量統計皆空
- 任何依賴量能的模型特徵（M3 標準化基準、LSTM 量價特徵）無法計算

## 根本原因

`Crawler/scrapers/finmind_scraper.py` `fetch_prices()` 以**空格版欄名**讀取 FinMind DataFrame：

```python
row.get("Trading Volume")    # ✗ FinMind 實際欄名是 Trading_Volume（底線）
row.get("Trading money")     # ✗ 實際為 Trading_money
row.get("Trading turnover")  # ✗ 實際為 Trading_turnover
```

`Series.get()` 查無欄位回傳 None → 靜默寫入 NULL，無任何錯誤訊息，因此長期未被發現。

## 修正內容

1. **`finmind_scraper.py`**：改用底線欄名（保留空格版為 fallback，向前相容）
2. **新增 `Crawler/backfill_prices.py`** 回補工具：
   - 善用 FinMind `taiwan_stock_daily` 單次呼叫可抓整段日期範圍的特性
   - 22 檔 × 1 次呼叫 = 22 次，匿名額度（30 次/h）內完成
   - 一次解決兩個問題：volume 回補 + 補齊 2026-03-23 之後的行情斷層
   - 支援 `--start`、`--chips`（籌碼同步回補）參數

## 執行結果

```
[22/22] 全部成功，行情共 29,044 筆 upsert
```

| 檢查項 | 修復前 | 修復後 |
|--------|--------|--------|
| 有 volume 的筆數 | 1 / 25,736 | **29,044 / 29,044** ✅ |
| 行情最新日期 | 2026-03-23 | **2026-08-05（昨日）** ✅ |
| turnover_value / transaction_count | 全空 | 全部填齊 ✅ |

抽查 2330 台積電 2026-08-05：收盤 2405、成交量 36,782,301 股、119,876 筆——數值合理。

## 遺留事項

- **籌碼（stock_chip_analysis）仍停在 2026-03-20**：回補需再 22 次 API 呼叫，
  本小時匿名額度已用 24 次。處理方式擇一：
  1. 一小時後執行 `python backfill_prices.py --start 2026-03-20 --chips`
  2. 申請 FinMind 免費 token（600 次/h）填入 `config.py` 後立即執行
- 每日 18:00 排程（Iteration 4）上線後不會再發生斷層
