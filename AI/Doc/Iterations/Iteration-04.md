# Iteration 4 — 排程自動化（request.md 第六節）

**日期：** 2026-08-06

## 問題

`request.md` 第六節「資料更新頻率」定義了三個排程，但舊 `scheduler.py`：

1. 只有每日 18:00 股價任務，且仍使用**已被 FinMind 取代的 TWSEScraper**（專案早已遷移）
2. 股票清單寫死 `["2330","2317","2454","2308","3008"]`——5 檔中 4 檔根本不在追蹤清單
3. 缺「每小時新聞爬蟲 + 特徵計算」與「每日 20:00 投票」兩個排程

## 修正內容

### `Crawler/scheduler.py` 重寫

| 排程 | 時間 | 動作 | 寫入表 |
|------|------|------|--------|
| `job_stock` | 每日 18:00 | FinMind 抓追蹤股票近 7 天行情+籌碼（涵蓋補班日，upsert 冪等） | `stock_daily_prices`、`stock_chip_analysis` |
| `job_news` | 每小時 :05 | Yahoo TW + CNN 首頁新聞 → `user_news`；再對每檔追蹤股票計算情緒特徵 | `user_news`、`news_features` |
| `job_vote` | 每日 20:00 | `voting_engine.run_vote_batch()` 全追蹤股票投票 | `voting_results` |

- 股票清單改為動態查詢 `stock_info WHERE is_tracking = TRUE`（22 檔）
- `config.py` `SCHEDULE` 新增 `news_cron`（每小時 :05）、`vote_cron`（20:00）
- 啟動方式不變：`python main.py --mode schedule`

## 驗證結果

`job_news` 實跑一次：

```
[news] 即時合計: 50 則（yahoo-tw 25 + cnn 25）
[news] 新增 50 則（跳過重複）→ user_news 71 → 121 筆
[排程/news] 情緒特徵計算完成（22 檔，news_features 當日 upsert）
```

- `_tracked_stock_ids()` 回傳 22 檔 ✅
- `news_features` 當日全部更新（sentiment=0.1533、article_count=50）✅
- `job_stock` 未實跑（FinMind 匿名額度 30 次/h，22 檔 × 行情+籌碼 = 44 次會超限），邏輯與 `main.py --mode stock` 相同已在既有流程驗證過

## 觀察與建議（供後續迭代）

1. **M2 信號無個股區分度**：模型二情緒以「全部新聞」計算（sector sentiment 設計），本次 22 檔全部得到相同 Buy(0.95)。`stock_articles`（個股相關文章數）已在特徵中但評分規則未使用——未來可提高個股相關新聞權重
2. **news_volume_gap 冷啟動失真**：過去 3 天無新聞時基準量=1，今日 50 則 → gap=49，直接觸發爆量加分。排程每小時穩定運行後此問題自然消失
3. **每日 job_stock 額度**：22 檔 × 2 類資料 = 44 次呼叫，超過匿名 30 次/h——建議申請 FinMind token（600 次/h）填入 `config.py`
