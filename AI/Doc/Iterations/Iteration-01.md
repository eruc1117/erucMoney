# Iteration 1 — stock_info 資料完整性修正

**日期：** 2026-08-06

## 問題

| 現象 | 影響 |
|------|------|
| `stock_info` 僅 4 筆，但 `stock_daily_prices` 有 22 檔股票的行情 | 18 檔股票（含 Target.md 的多數測試股）查無基本資料，前端個股分析頁無名稱/產業別 |
| `3330` 列只有代碼，無名稱/市場別/產業別，且無任何行情資料 | 殘留垃圾資料，出現在追蹤清單（Overview 頁）卻完全不可用 |

根本原因：`api.py` 爬蟲流程在 `fetch_stock_info()` 失敗時以 `upsert_stock_info(stock_id, stock_id)` 寫入代碼充當名稱（fallback），而歷史批次抓取（`fetch_all_history.py`）只寫行情、未寫基本資料。

## 修正內容

新增 **`Crawler/sync_stock_info.py`**（可重複執行的同步工具）：

1. 以 `stock_daily_prices` 實際存在的股票清單為準
2. 呼叫 FinMind `taiwan_stock_info()`（單次 API 呼叫）補齊名稱 / 市場別 / 產業別
3. **去重邏輯**：FinMind 同一檔股票會回傳多筆（泛用「電子工業」+ 具體產業別），優先保留具體產業別
4. 清除「無名稱且無行情資料」的殘留列
5. 支援 `--dry-run` 預覽模式

## 執行結果

```
FinMind 取得 42 筆原始資料，去重後 22 檔
已 upsert 22 筆 stock_info
已刪除殘留列：3330
```

- `stock_info` 22 筆全部有名稱、市場別、具體產業別（例：2303 聯電/半導體業、3037 欣興/電子零組件業）
- `GET /stocks?tracked=true` 驗證回傳 22 檔完整資料 ✅

## 遺留觀察（供後續迭代）

- `2883 凱基金`（原開發中華開發金控更名）僅 1 天行情（2026-03-11），不在 Target.md 20 檔清單內，判斷為測試殘留；行情資料保留不動
- 部分股票最新行情的 `volume` / `change_rate` 為 null（如 5483、6239 的 2026-03-17），來源資料品質問題，與本迭代無關
- 行情最新日期 2026-03-23，距今約 4.5 個月（資料更新屬另一議題，見 Iteration 0 盤點）
