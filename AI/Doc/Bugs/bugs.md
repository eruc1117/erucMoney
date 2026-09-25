# Bug 紀錄 & 功能追加

## DATA-001 — stock_info 資料不完整（3330 殘留 + 18 檔缺基本資料）
- **狀態**：已修復（Iteration 1）
- **發現日期**：2026-08-06
- **根本原因**：`api.py` 在 `fetch_stock_info()` 失敗時以代碼充當名稱寫入 fallback 列；
  歷史批次抓取只寫行情不寫基本資料，導致 22 檔有行情的股票僅 4 檔有基本資料。
- **修復方式**：新增 `Crawler/sync_stock_info.py`（FinMind 補齊 + 去重 + 清殘留），
  詳見 `AI/Doc/Iterations/Iteration-01.md`。

---

## DATA-003 — 籌碼歷史資料三大法人數值全為 0
- **狀態**：修復中（Iteration 6 發現，回補背景執行）
- **發現日期**：2026-08-06
- **根本原因**：舊版 `fetch_all_history` 批次爬取時期的 fetch_chips 寫入 bug，
  18 檔股票 × 1,227 天的 foreign/trust/dealer/total 全為 0。現行 fetch_chips 已正確
  （2303 等近期資料有真實值可證）。
- **影響**：M3 籌碼特徵完全失效（RF 特徵重要度全 0）、前端三大法人歷史圖全 0。
- **修復方式**：`backfill_prices.py --chips-only`（含額度自動重試）重抓全史；完成後重訓 M3。

---

## DATA-004 — stock_daily_prices volume/turnover/transaction_count 全為 NULL
- **狀態**：已修復（Iteration 5）
- **發現日期**：2026-08-06
- **根本原因**：`finmind_scraper.py` 以空格版欄名（Trading Volume）讀取 FinMind DataFrame，
  實際欄名為底線版（Trading_Volume），`Series.get()` 靜默回 None。
- **修復方式**：改用底線欄名 + `backfill_prices.py` 全量回補 29,044 筆，
  行情同步由 2026-03-23 補至 2026-08-05。詳見 `AI/Doc/Iterations/Iteration-05.md`。

---

## DATA-002 — news_features 表從未寫入
- **狀態**：已修復（Iteration 2）
- **發現日期**：2026-08-06
- **根本原因**：`model2_news.py` 只即時計算特徵回傳，未依 request.md 規格落地 `news_features`。
- **修復方式**：`get_signal()` 新增 `_persist_features()`，以 (stock_id, 日期) upsert。
  詳見 `AI/Doc/Iterations/Iteration-02.md`。

---

## FEAT-001 — 歷史資料補充功能
- **狀態**：已實作
- **日期**：2026-03-12
- **問題**：爬蟲固定只抓「今天往前 90 天」，無法補充更早的歷史資料
- **解決方案**：
  - `CrawlerRequest` 新增 `start_date` / `end_date`（選填，YYYY-MM-DD）
  - 有指定日期 → 歷史補充模式，跳過 30 分鐘冷卻，單次上限 365 天
  - 未指定日期 → 近期模式（維持原邏輯，受冷卻限制）
  - 前端「個股分析」頁底部新增「歷史資料補充」卡片：日期選擇器 + 進度條

---



## BUG-001 — 預算查詢畫面 Crash（TypeError: toFixed is not a function）
- **狀態**：已修復
- **發現日期**：2026-03-12
- **頁面**：BudgetSearch
- **根本原因**：`pg` 套件將 PostgreSQL `NUMERIC` 欄位回傳為 **字串**（string），
  而 `s.close_price.toFixed(2)` 直接對字串呼叫 `.toFixed()` → TypeError，畫面崩潰。
- **影響欄位**：`close_price`、`change_rate`、`volume`（全部 NUMERIC/BIGINT 欄位）
- **修復方式**：BudgetSearch.jsx 所有數值欄位改用 `Number()` 包裝後再做運算與格式化。

---

## BUG-002 — 每日行情明細「漲跌」欄位顯示全為「－」
- **狀態**：已修復
- **發現日期**：2026-03-12
- **頁面**：StockAnalysis → 每日行情明細表格
- **根本原因**：Node.js Server `/stocks/:id/prices` SQL 未 SELECT `change_value` 欄位，
  前端 `p.change_value` 為 `undefined`，Number(undefined) = NaN → 顯示「－」。
- **修復方式**：Server `index.js` prices SQL 加入 `change_value`。

---

## BUG-004 — 資料量不足時未自動補充（不觸發爬蟲）
- **狀態**：已修復
- **發現日期**：2026-03-12
- **頁面**：StockAnalysis
- **根本原因**：股票存在於 DB 但 price 筆數少於所選週數應有量（每週至少 3 個交易日），
  系統只顯示現有少量資料，不提示也不補充，導致統計圖表無法產生。
- **修復方式**：`loadStock` 取回 prices 後判斷 `prices.length < weeks * 3`，
  若不足則自動呼叫 `triggerCrawler` 並顯示進度條橫幅；爬蟲完成後 Toast 倒數自動重新查詢。

---

## BUG-005 — 資料不足自動爬蟲可能形成無限迴圈 / 頻率過高
- **狀態**：已修復
- **發現日期**：2026-03-12
- **頁面**：StockAnalysis + Crawler FastAPI
- **根本原因**：自動爬蟲完成 → auto-reload → 資料仍不足 → 再次觸發 → 無限迴圈；
  且無任何頻率限制，理論上可無限對 FinMind API 發請求。
- **修復方式（四層保護）**：
  1. **前端單次限制**：`autoCrawledRef`，每次手動搜尋只允許自動爬蟲觸發一次，
     auto-reload 後若資料仍不足不再重觸發。
  2. **前端 localStorage 冷卻**：`crawl_ts_{stock_id}` 記錄上次觸發時間，
     30 分鐘內前端不重新觸發（即使手動重搜）。
  3. **後端冷卻鎖**：`_crawl_done_at` 字典記錄每支股票完成時間，
     30 分鐘內回傳 `{ status: "rate_limited", retry_after: N }`。
  4. **後端並發鎖**（既有）：`_running_tasks` 防止同一股票同時執行多個爬蟲。

---

## BUG-006 — StockAnalysis.jsx 使用未定義的 `logger` 物件
- **狀態**：已修復
- **發現日期**：2026-03-13
- **頁面**：StockAnalysis
- **根本原因**：`loadStock()` 冷卻判斷分支呼叫 `logger.info?.(...)`, 但 `logger` 從未 import 或定義，
  觸發時拋出 `ReferenceError: logger is not defined`，整個查詢流程中斷。
- **修復方式**：將 `logger.info?.(`[auto-crawl] ...`)` 改為 `console.log(`[auto-crawl] ...`)`。

---

## BUG-007 — 趨勢走勢圖缺少 MA5 / MA20 均線
- **狀態**：已修復
- **發現日期**：2026-03-13
- **頁面**：StockAnalysis → 收盤走勢圖
- **根本原因**：Spec 第 13 點規定需顯示 MA5 / MA20，但 `trendSeries` 只有一條「收盤價」series，
  均線計算邏輯不存在。
- **修復方式**：新增 `validPrices`、`ma5Data`、`ma20Data` useMemo；`trendSeries` 擴充為三條；
  `trendOptions` 加入 `stroke.width`、`colors`、`legend` 對應三條線。

---

## BUG-008 — 個股分析頁面區塊順序錯誤
- **狀態**：已修復
- **發現日期**：2026-03-13
- **頁面**：StockAnalysis
- **根本原因**：JSX 渲染順序為「歷史資料補充 → 三大法人籌碼」，與 Spec / Architecture 定義的
  「三大法人籌碼 → 歷史資料補充」相反。
- **修復方式**：交換兩個 JSX 區塊的位置，使籌碼圖先於歷史補充卡片渲染。

---

## BUG-009 — Server 500 錯誤無法診斷 + date 算術型別錯誤
- **狀態**：已修復
- **發現日期**：2026-03-14
- **頁面**：所有使用 `/stocks/:id/prices`、`/stocks/:id/chips` 的頁面
- **根本原因1**：`routes/stocks.js` 所有 catch 區塊只送 `res.status(500).json()`，
  未呼叫 `console.error`，Server 端無任何錯誤記錄，無法從終端機診斷 500 原因。
- **根本原因2**：`CURRENT_DATE - $2` 未明確轉型；`pg` 以 text 傳遞數值參數時，
  PostgreSQL 無法執行 `date - text` 算術，拋出 `operator does not exist: date - text`。
- **修復方式**：
  1. 新增 `log500(endpoint, id, err)` helper，所有 catch 區塊統一呼叫後再回傳 500。
  2. `days` 參數改為 `($2::int)`，日期區間改為 `$2::date AND $3::date` 明確型別轉換。

---

## BUG-010 — PredictionCompare 展開比對卡片頁面崩潰（toFixed is not a function）
- **狀態**：已修復
- **發現日期**：2026-03-23
- **頁面**：PredictionCompare
- **根本原因**：`node-postgres` 將 PostgreSQL `NUMERIC` 欄位（`close_price`）回傳為**字串**，
  `predictions.js` compare 路由建立 `actualMap` 時未轉型，導致前端 `r.actual_close.toFixed(2)` 對字串呼叫失敗，
  比對卡片展開時頁面整體崩潰（白畫面）。
  同時影響後端誤差計算（`actual - predicted` 字串相減）。
- **修復方式**：`Server/routes/predictions.js` actualMap 建立時加入 `parseFloat(r.close_price)`。

---

## IMPR-001 — LSTM 預測準確率改進計劃
- **狀態**：已執行並結案（Iteration 36；各項對應證據見 Iteration-36.md「IMPR-001」節）
- **建立日期**：2026-03-23
- **文件**：`AI/Doc/LSTM-Improvement.md`
- **背景**：M01 Vanilla 及現有模型在 PredictionCompare 頁的 MAPE 偏高、方向準確率 < 55%
- **根本原因摘要**：
  1. 預測目標為絕對股價（非平穩序列）
  2. M01 單特徵（只有收盤價），無量價/技術指標
  3. 全域 MinMax 正規化有未來資料洩漏風險
  4. 未嚴格實施 Walk-Forward 時序分割
  5. EarlyStopping 監控 val_loss 而非方向準確率
- **改進方案（6 項，詳見文件）**：
  - IMP-001：Log Return 作為預測目標
  - IMP-002：M01 特徵擴充 5 → 10 個
  - IMP-003：Rolling Z-Score 取代全域 MinMax
  - IMP-004：嚴格 Walk-Forward Validation
  - IMP-005：EarlyStopping 監控方向準確率
  - IMP-006：M10 Ensemble 動態權重
- **目標指標**：MAPE ≤ 3%、方向準確率 ≥ 55%、CI 命中率 ≥ 70%

---

## BUG-003 — 切換時間範圍後圖表 / 統計不更新
- **狀態**：已修復
- **發現日期**：2026-03-12
- **頁面**：StockAnalysis
- **根本原因**：`weeks` 狀態改變後沒有自動重新呼叫 `loadStock()`，
  使用者必須重新點擊「查詢」才能讓新週數生效；使用者預期切換週數即時更新。
- **修復方式**：新增 `useEffect([weeks])` 監聽，當 `loadState === 'found'` 時
  自動以新 `weeks` 重新查詢行情（chipData 固定查 20 日不受影響）。

---

## MODEL-001 — M3 信心門檻寫死 0.45，線上永遠不出手
- **狀態**：已修復（Iteration 9）
- **發現日期**：2026-08-06
- **根本原因**：`model3_chip.py` 的 `_PROBA_GATE` 寫死 0.45，但 RF 三分類在
  `class_weight='balanced_subsample'` 下最高類別機率僅約 0.45（實測 22 檔
  min=0.352 / median=0.398 / max=0.448），門檻永遠擋下所有預測。
- **影響**：M3 自 Iteration 6 上線以來每天對每檔都回「信心不足、觀望」，
  對投票零貢獻。歷史模擬顯示此門檻曾連續 191 個交易日無訊號。
- **修復方式**：門檻改由模型 bundle 的 `proba_gate` 攜帶（推論端不再寫死），
  依 `simulate_deployment.py` 的準確率／出手頻率取捨定為 0.35。
  診斷工具 `RandomForest/diagnose_production.py` 可隨時複驗。

---

## MODEL-002 — M3 賣出訊號與規則 fallback 均無 edge 卻以全權重投票
- **狀態**：已修復（Iteration 9）
- **發現日期**：2026-08-06
- **根本原因**：`voting_engine.py` 以固定 ±0.33 計分且**不參考 confidence**，
  因此任何訊號一旦送出就是全權重。而走查顯示 M3 賣出側方向準確率僅約 52%、
  平均報酬為負；規則 fallback 更只有 48.31%（28,886 筆，低於隨機約 6 個標準誤）
  且從不輸出 Hold。
- **影響**：兩條負 edge 路徑持續污染投票結果。
- **修復方式**：bundle 新增 `sell_policy='suppress'`（賣出改判 Hold）；
  RF 不可用時改為棄權而非規則 fallback（`M3_RULE_FALLBACK=allow` 可還原）。
  代價：M3 只會投 Buy 或 Hold。驗證腳本 `evaluate_rule_fallback.py`。

---

## DATA-005 — news_crawl_raw 的 published_at 全為空字串
- **狀態**：已修復（Iteration 10 的新管線）；50 筆舊資料待清（Iteration 36 收尾）
- **Iteration 36 查證**：`news_crawl_raw` 現有 2,008 筆，其中 1,958 筆有發布時間、格式全部
  合法；只剩最早那 50 筆（Yahoo 25 + CNN 25，同一個 `scraped_at` 批次）為空字串，
  正是舊首頁爬法留下的。它們不在模型資料路徑上（見下方補充）。
  清理腳本 `Crawler/cleanup_news_raw.py`（不加 `--apply` 只查證；加了會先備份到
  `AI/Doc/Bugs/` 再刪）。刪除資料庫列這一步保留給使用者執行。
- **發現日期**：2026-08-06
- **現象**：`news_crawl_raw` 僅 50 筆，且 `published_at` 全部為空字串
  （`SELECT count(*) ... WHERE published_at <> ''` 回 0），日期查詢直接報
  `invalid input syntax for type date`。`news_features` 僅 22 筆。
- **影響**：M2 的時序滯後特徵（24h/72h 衰減情緒）無法計算，XGBoost 訓練
  永遠達不到 300 樣本門檻。Iteration 8 記錄的 121 則新聞已不在庫中。
- **待辦**：查明新聞爬蟲的發布時間解析與寫入路徑，並確認 Common Crawl 回補是否中斷。

---

## DATA-006 — 新聞爬蟲內文恆為空、個股標記恆為空、無發布時間
- **狀態**：已修復（Iteration 10）
- **發現日期**：2026-08-06
- **根本原因**：`_parse_yahoo_soup` / `_parse_cnn_soup` 只解析首頁的連結文字，
  產生的 dict 寫死 `'content': ''`；`_auto_tickers` 用裸數字比對，在純標題上
  幾乎不命中；`insert_news_articles` 未寫 `submitted_at`，一律用 CURRENT_TIMESTAMP。
- **影響**：M2 從上線起只能對標題做情緒分析；`stock_articles` 特徵恆為 0；
  時間衰減權重把三個月前的舊聞當成今日新聞。實測最近 50 筆內文長度全為 0。
- **修復方式**：改用公開 RSS 與鉅亨網 JSON API（`rss_news_scraper.py`），
  加入內文品質驗證與「內文須與 RSS 摘要相符」的交叉檢查。
  實測 130 則內文為空 0%、有發布時間 100%、52 則帶個股標記涵蓋 17/22 檔。

---

## MODEL-003 — M2 在結構上無法區分個股（22 檔恆同訊號）
- **狀態**：已修復（Iteration 10）
- **發現日期**：2026-08-06
- **根本原因**：`_features_to_signal` 的五項評分輸入有四項是全市場聚合值
  （`avg_sentiment_72h` / `news_volume_gap` / `keyword_recovery_hit` /
  `sector_sentiment`），唯一的個股特徵 `stock_articles` 雖有計算卻從未被使用。
  規則引擎在結構上就不可能產生個股差異。
- **影響**：22 檔股票恆得相同訊號與相同 confidence；Iteration 7~9 觀察到的
  「全 Buy」現象一直被歸因於新聞爆量冷啟動，實為此結構性缺陷。
- **修復方式**：新增 `stock_sentiment_72h` / `stock_keyword_hit`（只用提及本股
  的新聞計算），評分主體改為本股情緒，大盤情緒降為背景修正；無本股新聞時棄權。
  修正後 M2 為 Hold 12 / Buy 8 / Sell 2、6 種不同 confidence。
- **注意**：規則權重仍未經回測驗證（新聞歷史僅數日）。本次是結構性修正而非調參。

---

## DATA-005 補充 — news_crawl_raw 不在模型資料路徑上
- **狀態**：已釐清（Iteration 10）
- Iteration 9 推測 `news_crawl_raw.published_at` 全空會癱瘓 M2 的時序特徵，
  但查證後確認 **M2 讀的是 `user_news`**（`model2_news._fetch_news`），
  `news_crawl_raw` 僅為爬取中介記錄，不影響任何模型。
  該欄位現已改寫入 ISO 字串。記錄於此以免日後重複追查。

---

## DATA-006 後續 — 清除 user_news 的 100 筆空內文舊資料
- **狀態**：已完成（2026-08-06，Iteration 10 後續）
- **背景**：舊爬蟲留下的 100 筆資料（Yahoo Finance 台灣 50 筆、CNN Business 50 筆）
  內文為空、tickers 為空、submitted_at 為批次寫入的相同時間戳，
  會稀釋 M2 的 `news_volume_gap` 特徵並污染情緒均值。
- **刪除前查證**：
  · 目標 100 筆全部同時符合「內文為空 + 平台為 Yahoo/CNN」
  · 空內文出現在其他平台的筆數為 **0** → 無誤刪使用者手動提交新聞的風險
  · 同平台但**有內文**的 21 筆不在刪除條件內，已保留
- **備份**：`AI/Doc/Bugs/user_news_deleted_20260806.csv`（含全部欄位，可用
  `\copy user_news FROM ... WITH (FORMAT csv, HEADER true)` 還原）
- **結果**：user_news 由 251 → 151 筆，**剩餘資料內文為空者 0 筆**。
  72 小時窗內新聞由 153 → 103 則；重跑投票後 22 檔為 Hold 12 / Buy 8 / Sell 2。

---

## BUG-007 — Node proxy 丟棄上游狀態碼，前端把錯誤物件當陣列而崩潰
- **狀態**：已修復（2026-08-06）
- **發現日期**：2026-08-06（使用者回報前端 console 錯誤）
- **現象**：`Prediction.jsx:129 Uncaught TypeError: data.map is not a function`，
  整個 `<Prediction>` 元件崩潰。
- **根本原因（兩層）**：
  1. `Server/lib/proxy.js` 的 `proxyRes.on('end')` 一律 `res.json(...)` 送出 **200**，
     完全不理會上游狀態碼。LSTM 回 `503 {"detail":"模型尚未訓練"}` 時，
     前端看到的是「200 + 一個物件」。**此缺陷影響所有代理路由，不只預測。**
  2. `Prediction.jsx` 只檢查 `!data`，而物件同樣是真值 → 直接 `.map()` 崩潰。
- **修復方式**：
  · `proxy.js` 沿用 `proxyRes.statusCode`；上游回非 JSON（如 FastAPI 未攔截例外的
    純文字 Internal Server Error）時保留其狀態碼並包成 `{detail, upstream_status}`
  · `api.js` 在 `!res.ok` 時讀取 `{detail}` 併入錯誤訊息，不再只顯示 `HTTP 503`
  · `Prediction.jsx` 改用 `Array.isArray(data)` 驗證，並顯示後端的 detail
- **驗證**：m04→200 陣列、m07(未訓練)→503、bogus→400、無資料股票→404，
  且錯誤訊息內容完整傳到前端。

---

## BUG-008 — LSTM m04_attention 自訂層無法反序列化（health 謊報可用）
- **狀態**：已修復（2026-08-06）
- **根本原因**：`m04_attention` 使用自訂層 `BahdanauAttention`，
  `serve.py` 的 `tf.keras.models.load_model()` 未傳 `custom_objects`，
  拋 `Could not locate class 'BahdanauAttention'` → HTTP 500。
- **加重問題**：`/health` 只檢查 `.keras` 檔是否存在，因此把 m04 列為可用，
  錯誤直到前端實際呼叫才浮現。
- **修復方式**：`_get_model()` 傳入 `custom_objects` 並攔截載入例外記錄原因；
  `/health` 新增 `?verify=true` 實際載入驗證，並回報 `failed_models` 與 `missing_models`。
- **驗證**：8 個已訓練模型全部載入成功且預測正常；m07/m10 正確回報未訓練。

---

## DATA-007 — stock_daily_prices 有兩列 OHLC 與成交量全為 0
- **狀態**：已在載入層緩解，DB 資料仍在（Iteration 11 發現）
- **發現日期**：2026-08-06
- **資料**：2449 / 2024-04-26、3037 / 2022-02-22，open/high/low/close 與 volume 全為 0。
  前後日分別是 95.50→98.90、237.50→240.50，顯然是爬蟲寫入的佔位列。
- **影響**：殺傷力遠超過「少一天資料」——
  · 報酬率 `diff/前收` 除以 0 會爆成 98 億，實測整體日報酬標準差被推到 1.8 億
  · 含 0 的視窗其 z-score 標準差暴增，正規化後的輸入完全失真
  · **所有 LSTM 模型的訓練都受影響**
- **緩解**：`LSTM/data_loader.load_prices` 過濾 `close_price <= 0` 並記錄警告。
  修正後日報酬標準差回到 0.02358（合理值）。
- **未完成**：DB 中兩列仍在（刪除指令被權限規則擋下），前端 K 線圖會顯示掉到 0 的假跳空。
  另需查明爬蟲為何寫入佔位列，否則未來還會出現。

---

## MODEL-004 — 10 個 LSTM 模型全部等同天真基準線，且 DA 指標算法有誤
- **狀態**：已結案（Iteration 36 整理）
  - 投票端：Iteration 22 的 `roles.py` 已把趨勢分析師權重 0.34 → 0.15，Iteration 31 起
    使用者可逐頁停用趨勢角色。「待決定」的事已經決定了，只是這裡沒更新。
  - DA 算法：`LSTM/evaluate.compute_metrics` 已於 Iteration 36 改為「相對前一日實際收盤」
    （舊算法比較兩條序列各自的 diff，照抄模型會拿到接近 100%）。`train_cross.py` 跨股票
    串接後的**整體** DA 仍不可信（邊界處多一筆），逐股 DA 正確。
- **發現日期**：2026-08-06
- **量測結果**：天真基準線（明日=今日）MAE=5.20；10 個模型 MAE 5.17~5.25、
  方向準確率 46.9~50.6%、平均預測變動僅 0.22~0.58%。**無一勝過基準線。**
- **根本原因**：訓練目標是價格水準，而收盤價近似隨機漫步，
  MSE 損失下「預測 = 今日收盤」即最佳解 → 模型必然收斂到照抄。
  改以報酬率為目標實驗（`train_returns.py`）四種架構仍為 48~50%，
  依門檻（DA>51%）判定不部署。
- **指標算法錯誤**：`evaluate.compute_metrics` 的 DA 比較相鄰樣本之差，
  而跨股票測試集是串接而成，`np.diff` 會跨越股票邊界。
  已新增 `evaluate_honest.py` 提供正確定義（相對今日收盤，逐樣本獨立）。
  舊演算法仍被 `train_cross.py` 使用，其 DA 欄位與 summary_cross_stock.csv 不可信。
- **對投票的影響**：M1 取 7 日均預測與現價比 ±2%，實測 22 檔中 12 檔觸發
  （10 個是 Sell）。但單步平均預測變動僅 0.58%，7 天的 2~8% 是自迴歸滾動
  累積偏差的產物，而非訊號。M1 目前以全權重注入雜訊，
  性質同 Iteration 9 已處理的 M3 賣出訊號與規則 fallback。

---

## MODEL-005 — M1 因欄名錯誤自實作以來永遠輸出 Hold
- **狀態**：已修復（Iteration 11 後續）
- **發現日期**：2026-08-06
- **根本原因**：`voting_engine._get_m1_signal` 讀 `p.get('predicted', current_price)`，
  但 LSTM API 回傳的欄位是 `predicted_close`。取不到值即回退成現價，
  `change_pct` 恆為 0.0，永遠落在 ±2% 之內 → 恆為 Hold。
  與 DATA-004（FinMind volume 空格版欄名）完全同類。
- **影響**：三模型投票實際上只有 M2／M3 在作用，M1 從未貢獻過任何訊號。
  症狀隱蔽——理由欄顯示「LSTM 預測價格與現價接近（變動 +0.0%）」看起來像正常結論。
- **修復方式**：改讀 `predicted_close`（保留 `predicted` 作為相容 fallback），
  並在欄位缺失時明確回報格式錯誤而非靜默 Hold。
- **修復前先回測**（`LSTM/backtest_m1_rule.py`，660 樣本）：
  觸發率 36%、方向準確率 52.12%、平均報酬 +1.02%，
  但同期無條件 7 日平均報酬為 +1.03% → **零超額報酬**；
  預測變動與實際變動相關係數僅 +0.05。
  結論記錄於 `_get_m1_signal` docstring；M1 權重已於 Iteration 22 降為 0.15（`roles.py`）。

---

## BUG-009 — numpy 2.x 的 repr 讓 psycopg2 產生 `schema "np" does not exist`
- **狀態**：已修復（Iteration 14）
- **發現日期**：2026-08-06
- **現象**：投組相關性調整靜默失效，日誌只有
  `[voting/batch] 投組相關性調整失敗（保留單筆建議）: schema "np" does not exist`，
  完全看不出真正原因。單獨測試 UPDATE 與 read_sql 都正常。
- **根本原因**：numpy 2.x 的 `repr(np.float64(5.1))` 是 `'np.float64(5.1)'`
  （1.x 時代是 `'5.1'`）。psycopg2 遇到無法適配的型別會退回用 repr 做字串插入，
  於是 SQL 變成 `SET position_pct = np.float64(5.1)`，
  PostgreSQL 將 `np` 解讀為 schema 名稱。
  `portfolio_risk.adjust_positions` 的 `scale` 來自 `w.sum()`（numpy.float64），
  乘出來的部位值因此全是 numpy 型別。
- **修復方式**：所有寫入 DB 的計算結果強制 `float()` 轉型。
- **注意**：本專案已全面升級 numpy 2.x，**凡是把 numpy 計算結果直接寫入 DB
  的地方都要檢查**。錯誤訊息不會提到 numpy，極難從訊息追查。

---

## DATA-008 — 0052 於 2017-06-01 的行情列 open/close 為 0
- **狀態**：已記錄，未修改資料（Iteration 36 發現）
- **發現方式**：M3 持股消融在 2012 起的完整樣本上跑，`ret_5d` 出現 inf——
  `experiment_m3.load_dataset` 沒有 `close_price > 0` 的過濾（`features.LOAD_SQL` 有）。
- **資料**：`0052 / 2017-06-01`：open 0、close 0、volume 75；前後日正常（46.33 / 47.05）。
  性質同 DATA-007（2449、3037 的全零列）。
- **處理**：消融腳本把 inf 換成 NaN 後一併丟掉；資料列本身未動。
  若要根治，應與 DATA-007 一起在 `stock_daily_prices` 補上 `close_price > 0` 的檢查約束，
  並讓 M3 的載入 SQL 加上同樣的過濾。
