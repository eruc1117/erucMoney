# Iteration 2 — 三模型投票管線修復與跑通

**日期：** 2026-08-06

## 問題（對照 `AI/UserDoc/request.md` 規格）

| 現象 | 根本原因 |
|------|----------|
| `news_features` 表 0 筆（規格要求每小時更新） | `model2_news.py` 只即時計算特徵回傳給投票引擎，**從未寫入** `news_features` 表 |
| `voting_results` 僅 2 筆（2026-03-22 的 2330、2323） | 投票引擎只被手動跑過一次 2 檔；未對 Target.md 的 20 檔測試股執行過 |
| 模型一（LSTM）依賴 :8001 預測伺服器 | 伺服器未啟動時 m1 固定回 Hold（優雅降級，但等於兩模型投票） |

## 修正內容

### 1. `Crawler/model2_news.py` — 新增 `news_features` 落地

`get_signal()` 計算完特徵後呼叫新增的 `_persist_features()`：
- 以 `(stock_id, CURRENT_DATE)` upsert 至 `news_features`
- `sentiment` ← 時間衰減加權情緒均值（`avg_sentiment_72h`）
- `keyword_hits`（JSONB）← 強效關鍵字命中 + 新聞量差 + 產業情緒
- `article_count` ← 近 72h 文章總數
- 寫入失敗僅記 warning，不中斷投票流程

### 2. 啟動完整服務鏈並執行 22 檔投票

- 啟動 LSTM 預測伺服器（`LSTM/serve.py` :8001，載入 `cross_stock/m02_stacked.keras`）
- 重啟 Crawler FastAPI（:8000）載入新 model2
- `POST /voting/run` 執行全部 22 檔股票

## 驗證結果

| 檢查項 | 結果 |
|--------|------|
| `voting_results`（2026-08-06） | 22 筆：1 Buy（2388 威盛）/ 4 Sell / 17 Hold ✅ |
| `news_features` | 0 筆 → 22 筆 ✅ |
| LSTM 呼叫 | 21 檔預測成功；2883 因僅 1 日行情回「LSTM 無預測資料」→ 優雅降級 Hold ✅ |
| `GET /voting`（Node :3001） | 回傳 22 筆完整結果（含 m1~m3 reason、m2_features、weights）✅ |

投票結果解讀範例：
- **2388 威盛 → Buy**：M3 籌碼模型偵測「法人連續 5 日買超，外資 +5,398,879 張」
- **2303 聯電 → Sell**：M3 偵測「法人連續 3 日賣超，外資 -14,176,472 張」
- M2 全部 Hold 是正確行為：`user_news` 最新新聞為 2026-03，近 72h 無新聞可分析

## 遺留觀察（供後續迭代）

1. **M1 幾乎全 Hold**：行情資料停在 2026-03-23，LSTM 以舊資料預測，變動趨近 0%。資料更新後應重跑投票
2. **M2 需要新聞**：規格的「每小時新聞爬蟲 + 特徵計算」排程尚未建立（`scheduler.py` 只排了股價爬蟲）
3. **每日 20:00 自動投票排程**（request.md 第六節）尚未實作，目前僅手動觸發
