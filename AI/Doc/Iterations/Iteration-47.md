# Iteration 47 — 新聞訊號模型：六個維度、三個模型、五道關卡

**日期：** 2026-09-29
**依據：** 使用者提供的「新聞與股價關聯性」研究方案（News Signal Research Plan）。要求：依方案、搭配現有架構新增多種模型進行預測，前端畫面對應修改。
**前提：** 方案的第 1、3、5 階段其實已在 Iteration 39／40 做過事件研究與 28 個新聞模型，結論是「新聞內容幾乎沒有方向資訊、
有無報導才是可用的部分」。本迭代不重做研究，而是把方案的六個維度與五道關卡**做成產品裡的模型與畫面**，讓每一個新聞訊號都有台帳、都要過關才能服役。

## 一、做了什麼

### 特徵層：`Crawler/news_signal_features.py`，統一面板多兩個區塊

| 區塊 | 欄位 | 方案維度 |
|------|------|---------|
| `news` | `ns_n_articles`、`ns_n_sources` | 報導強度 |
| | `ns_abn_attn`（log1p 當日則數 − log1p 前 60 交易日日均）、`ns_attn_3d` | 異常注意力（Da, Engelberg & Gao 2011） |
| | `ns_sent`、`ns_sent_3d`（1／0.6／0.3 衰減）、`ns_strong_kw` | 情緒（字典 L1，與 model2_news 同一份，無前視偏誤） |
| | `ns_novelty`（1 − 標題與前 5 個新聞日標題的最大字元二元組 Jaccard） | 新穎度（Tetlock 2011） |
| | `ns_uncertainty`（避險／條件用語每千字密度，33 個中文詞） | 不確定性（Loughran & McDonald 2011 的中文近似） |
| | `ns_has_news`、`ns_mops_nonroutine`、`ns_mops_attention` | 有無新聞；MOPS 非例行（波動訊號）；注意交易另列（內生） |
| `event` | `ev_sue`、`ev_yoy`、`ev_yoy_extreme`、`ev_days_since_rev`、`ev_rev_ar0`、`ev_in_window` | 意外程度 ★（SUE 定義與 revenue_event_study 相同）、極端 YoY 反轉、公布日 AR₀、漂移窗口 |

時序（N0）：新聞用 `news_price_link.effective_date` 的 13:30 規則，交易日 D 那列只用 effective_date ≤ D 的新聞——D 收盤後的新聞歸 D+1，
D 這列看不到，設計上不可能洩漏。營收 t=0 用同一條規則。**沒有新聞 ≠ 中性**：情緒／新穎度／不確定性在沒新聞的日子是 NaN，
則數與注意力是 0（「沒人報導」是可觀察的事實）。新穎度第一版用 `dedup_group_id` 恆為 1（幾乎每則一群），改成標題二元組 Jaccard 後重複稿是 0、正常是 0.88 ± 0.08。

`panel.build(blocks=[..., 'news', 'event'])` 可用，`since_date='2023-09-01'`（新聞只有三年，掛上就砍樣本——方案說的實質代價）。

### 模型：`UnifiedModel/train_news_models.py`，三個模型、同一套關卡

每個模型跑兩個變體 `price_only`（12 個價量控制特徵）與 `price_news`，同一批列、同一組 3 折擴張視窗走查（後半段測試、封存 = 視野）：

| 模型 | 目標 | 列 | price_only | price_news | N2 增量 | 其他關卡 | 部署 |
|------|------|----|-----------|-----------|--------|---------|------|
| `news_event_vol` 事件波動 | 次日振幅 (高−低)÷前收（range, h=1） | 17,710 | 排序相關 0.6378 | **0.6512** | +0.0134，最差折 +0.0120 | 贏天真基準（20 日中位數 0.6179） | **通過** |
| `news_drift` 營收漂移 | 公布後 20 日超額報酬方向（signal, h=20），只在窗口內 | 14,265 | 0.0053 | 0.0133 | +0.0080，最差折 −0.0567 | 出手 20% 方向 55.8% 對多數類別 59.5%；剔除鎖死 53.9%；扣成本 +0.21% | 未通過 |
| `news_tone` 新聞語調 | 有新聞日的 3 日超額報酬方向（signal, h=3） | 11,077 | 0.0040 | −0.0023 | −0.0062 | 方向 53.1% 對 54.0%；扣成本 −0.39% | 未通過 |

讀法：

- **只有事件波動有增量**，而且是方案預言的那一種：新聞與非例行公告是波動訊號，不是方向訊號（MopsEventStudy、NewsEventStudy 的 |AR₀| 放大）。
- 營收漂移的排序相關有一點增量（+0.008，但不穩），方向準確率卻輸給多數類別——這三年單邊上漲，「一律猜漲」有 59.5%，任何模型都很難打。
  與 Iteration 39 一致：SUE 本身沒有可交易漂移。
- 語調沒有增量，與 Iteration 40 的 28 個模型 AUC 0.50~0.53 一致。這回是控制價量後的關卡版，結論相同。
- 第一次跑時 `panel.align` 把所有新聞欄位都要求非空，樣本掉到 9,646 列（只剩有新聞的日子），事件波動只差 0.0011 沒過門檻；
  改成只對價量欄 dropna 後樣本回到 17,710 列，事件波動才學得到「沒人報導的日子比較不震」。這正是方案 §06 的重點。

三個都登錄進 `model_versions`（candidate v1），**只有通過的才服役**；沒過的 credibility=none、每天照樣寫台帳，累積 100 筆線上紀錄後由 `model_lifecycle` 再看一次。
關卡：N1 方向（出手列方向準確率高出多數類別 +3pp）、N2 增量（+0.01 且每折不輸）、N3 剔除鎖死（|報酬| ≥ 9.5%）、N4 扣來回 0.585%。

### 接線

- 登錄：`model_registry.MODEL_TYPES` 三筆（target_kind 沿用 `range`／`signal`，**回填端不必改**）；`model_catalog.CATALOG` 三筆、新頁面代號 `signals`；
  目錄的 credibility 與 metric 由 `results/news_models.json` 同步（`_sync_news_credibility`），不手寫。
- 推論：`Crawler/news_models.py`——共用面板（`panel_cache`）、每檔最新一列；`signals()` 回六個維度 + 三模型輸出，未服役的模型只帶 `*_shadow` 與關卡；
  `_log_all` 對每個可載入版本寫台帳（signal 類棄權寫 0、range 類基準寫 20 日中位數）。
- 排程：`job_news_models` 每日 20:10（投票後、評估前）；啟動補跑在投票補跑之後順手跑。
- 週預測：`_batch_tw` 多三個模型，`latest()` 多三個鍵。
- API：FastAPI `GET /news/signals?stock_ids=`、`GET /news/signals/gates`；Node `routes/news.js` 代理同名路徑（前綴 `news` 本來就在統一平台的白名單）。
- 前端（Screen 與 meeting_front_end 各一份）：新頁「新聞訊號」`NewsSignals.jsx`（側欄／nav.js「新聞」群組）：
  六維度 × 三模型的表（篩選：今天有新聞／漂移窗口內／明日振幅偏大 ★）、五道關卡表、怎麼讀；
  `WeeklyForecast.jsx` 多三欄、拿掉 Iteration 46 之前的跳空 ⚠ 說明；ModelBar 在 `signals`／`analysis` 頁自動列出三個模型；模型版本頁本來就是資料驅動。

### 測試

- `Crawler/tests/test_news_signal_features.py`（7 項）：新穎度（首則 1、重複 0、只回看 5 個新聞日、不跨股票）、不確定性密度（重疊詞不重複計）、
  每日表合成（媒體家數、MOPS 例行／非例行／注意交易分開）、面板掛載（沒新聞是 NaN 不是 0、異常注意力基準、3 日情緒不延用）、
  事件掛載（13:30 後公布 → t=0 是下一交易日、第 20 日在窗口第 21 日出窗、AR₀）、SUE 定義。
- `Crawler/tests/test_news_signals_api.py`（4 項）：讀取端點不寫台帳、未服役不給值、關卡端點、報告缺檔回空。
- `Crawler/tests/test_scheduler.py`：20:10 登記、補跑順序 vote → news_models → model_review。
- `Server/tests/http/news-signals.test.js`（5 項）：轉發 query、回應形狀、503。
- 全套：Crawler pytest 138 過、Server 該兩檔 15 過、Screen `vite build` 過、meeting_front_end StockApp／api 測試 19 過。

## 二、對方案的回應

| 方案 | 本迭代 |
|------|--------|
| §01 先排程型再媒體 | 事件區塊（營收）與媒體區塊分開；營收漂移是獨立模型 |
| §03 不要算 corr(情緒, 報酬)；要增量檢定 | 每個模型都是 price_only vs price_news 的消融，N2 是部署門檻 |
| §03 漲跌停截斷 | N3：方向模型另報剔除鎖死的成績 |
| §04 六個維度、surprise 比 sentiment 重要 | 六個維度都做了；事件波動裡 SUE／距公布天數是特徵，漂移模型以 SUE、AR₀、極端 YoY 為主 |
| §05 L3 的前視偏誤 | 只用字典 L1；不用 LLM 打分做歷史回測 |
| §06 沒新聞 ≠ 中性；設計 A → B → C | NaN 語意；事件波動是設計 A 的閘門（不投方向）、漂移與語調是設計 B 的獨立子模型（未過關就不合成）；沒做 C |
| §07 五道關卡 | 全部落在 `train_news_models.py`，數字進 `results/news_models.json`，前端關卡表直接讀 |
| §08 執行順序 | 階段 1、3、5 的研究已在 Iteration 39／40；本迭代是階段 6「整合」的產品化，階段 2（財報）與階段 4（自建詞典）未做 |

## 三、沒做的與下一步

- **階段 2 財報事件研究**、**階段 4 自建中文財經情緒詞典**：不在本次範圍。不確定性詞表是 33 個詞的近似，情緒仍是 model2_news 的關鍵字表。
- 事件波動模型雖過關，只走過三年單邊行情；線上台帳從今天 20:10 起累積，100 筆後看 `model_lifecycle` 的排序相關與基準。
- 營收漂移的 +0.008 排序相關增量值得在下一段震盪期複驗；若要提升，方案建議的方向是用 AR₀ 而非 SUE（universe 研究 t 4.0），目前模型已含 `ev_rev_ar0`。
- M2 規則引擎（權重 0.30、從未驗證）現在有了對照組：`news_tone` 用同一份字典、控制價量後沒有增量。建議把 M2 的權重降到與「未驗證」相稱的水準（Iteration 46 已建議）。
- 前端未做：投票頁的角色卡（roles.py 的固定角色清單）沒有新增「事件」角色；事件波動要進 `cash_allocator` 的部位調整得另開迭代。

## 變更檔案

新增：`Crawler/news_signal_features.py`、`Crawler/news_models.py`、`UnifiedModel/train_news_models.py`、`UnifiedModel/results/news_models.md`／`.json`、
`UnifiedModel/saved_models/news_{event_vol,drift,tone}.joblib`、`Screen/src/pages/NewsSignals.jsx`（meeting_front_end 同）、
`Crawler/tests/test_news_signal_features.py`、`Crawler/tests/test_news_signals_api.py`、`Server/tests/http/news-signals.test.js`。
修改：`UnifiedModel/panel.py`、`Crawler/model_registry.py`、`Crawler/model_catalog.py`、`Crawler/api.py`、`Crawler/scheduler.py`、`Crawler/weekly_forecast.py`、
`Server/routes/news.js`、`Server/tests/helpers/fastapi-mock.js`、`Screen/src/{App.jsx,components/Sidebar.jsx,services/api.js,pages/WeeklyForecast.jsx}`、`Screen/smoke.mjs`、
`meeting_front_end/src/stock/{nav.js,services/api.js,pages/WeeklyForecast.jsx}`。
