# Iteration 38 — 新聞資料回填與結構化：從「實際 30 天」到 3 年

**日期：** 2026-09-22（進行中，本文件隨進度更新）

## 起點

使用者在 Claude Docs 寫了《新聞資料蒐集與股價預測方案》（GDELT 主幹、11 張表、日級對齊、
LLM 結構化抽取、LightGBM），要求「和現在撈新聞資料的爬蟲混和，提出優化方案」，並「開始執行，
定期產出進度文件」。

## 現況診斷（執行前）

現有管線：`rss_news_scraper` 每小時抓 RSS 與鉅亨網 API → `user_news`；`model2_news` 用正負
關鍵字字典算 72 小時情緒。對照方案的四原則：

| 原則 | 現況 | 證據 |
|------|------|------|
| 可回填歷史 | **沒有**。只有排程器活著的時段有資料 | 最近 14 天只有 4 天有抓（9/9、9/13、9/19、9/20） |
| 時間戳精確 | 有發布時間，但 naive 本地時間、未對齊 13:30 收盤 | `user_news.submitted_at` 無時區；M2 衰減用日曆日 |
| 可對應標的 | 只比對 `stock_info` 公司名與「（2330）」格式 | 1,947 則只有 580 則有 ticker；「國巨*」帶星號永遠比不到 |
| 去重分層 | 只有完全相同標題與 source_url | 同事件多家改寫會重複計入，`news_volume_gap` 灌水 |

結構性問題：沒有美股／國際新聞（CNN 僅 2 則舊資料）；`news_features` 只寫 `CURRENT_DATE`，
歷史特徵永遠補不回來——這是 M2「無走查」、`train_m2.py` 沒有訓練集的根因；Common Crawl
歷史爬蟲每請求等 60~300 秒，實際不可用。

### 關鍵發現：鉅亨網 API 可以回填 3 年

方案文件寫「中文歷史回填是最大缺口，只能靠 MOPS」。但現有程式已在用的鉅亨網分類 API
支援 `startAt / endAt / page`，內文隨 API 附帶，2023-09 起實測都在：

| 分類 | 一週則數（2023-10 第一週） | 3 年推估 |
|------|------|------|
| `tw_stock` | 282 | 約 44,000 |
| `us_stock` | 167 | 約 26,000 |
| `headline` | 551 | 約 86,000（與前兩類重疊，newsId 去重） |
| `wd_stock` | 218 | 未納入第一輪 |

每頁 30 則、約 1.6 秒。三年三個分類約 5,300 頁、2~3 小時。**中文財經主幹改為鉅亨網 API，
MOPS 退為事件層補充。** 另外 API 的 `market` 欄位自帶個股標記、`keyword` 自帶關鍵字。

### 硬體評估

資料庫 119 MB（C 槽，剩 63 GB）；`user_news` 每則 2.2 KB 含索引。方案最大情境 15 萬則
約 600 MB，C 槽夠一千萬則以上。GDELT 原始 GKG 實測每 15 分鐘檔 6.6 MB（英文）、12.9 MB（翻譯版），
六年 4 TB，**不留原始檔**，只留篩選後 Parquet 於 E 槽（三年預算約 150~170 GB，E 槽剩 647 GB）。

## 執行計畫

| 階段 | 內容 | 狀態 |
|------|------|------|
| 1a | `backfill_news.py`：鉅亨網 API 分月回填 2023-09 ~ 今天（tw_stock / us_stock / headline），可續跑 | 完成（230 分鐘，抓 120,157 則，user_news +109,699） |
| 1b | 排程器啟動補新聞空洞（`_catch_up_news`：上次抓取 > 2 小時就用 API 補回，再跑即時抓取） | 完成 |
| 1c | `backfill_mops.py`：MOPS 重大訊息回填（舊版 mopsov 端點，依公司＋民國年月；26 檔 × 37 月） | 完成（80 分鐘，6,574 則；user_news 6,137 則） |
| 2a | `news_schema.py`：`user_news` 加 `source_url / published_at_utc / language / scope / source_tier / content_kind / dedup_group_id / is_canonical`，新表 `instrument_alias / trading_calendar / news_price_link / news_daily_features` | 腳本完成；**DDL 被自動模式權限攔下，留給使用者執行** |
| 2b | `news_alias.py`：別名表灌入（stock_info 名稱去星號 + 26 檔手工別名）；`tag_tickers` 已接上（表不存在自動略過） | 腳本完成，灌入待使用者執行 |
| 2c | `news_dedup.py`：標題 SimHash（64 位元、4 桶、Hamming ≤ 3、±3 天），同群保留 tier 最高者為 canonical | 完成；乾跑 5,651 則 → 38 則重複 |
| 2d | `news_align.py`：`trading_calendar` 由價格表交易日生成；`news_price_link` 依 13:30 規則 | 完成（單元測試通過；寫表待 DDL） |
| 2e | `news_align.compute_daily_features`：每檔每 effective_date 的本股／全市場字典情緒；排程 `job_news` 每小時增量重算近 7 天 | 完成（寫表待 DDL） |
| 3 | 美股／國際：`us_stock`／`headline` 回填（中文的美股與國際新聞）；BBC Business／World RSS 接進即時抓取（英文，scope GLOBAL）；`news_sources.py` 定義 platform → tier / scope / 語言並回填 user_news；Finnhub（需 API key）與「前一交易日美國新聞情緒」特徵待做 | 部分完成 |
| 4 | `news_pilot/`：system.md、schema.json、02_prepare（從 user_news 抽 300 則）、03_run_claude（`claude -p --json-schema`）、04_evaluate、05_load_db；`news_llm_feature` 表 | 297 則 Sonnet 全跑完（0 批失敗）、60 則 Opus 先標黃金標準草稿；兩模型一致率 event_type 88%、scope 93%、direction 75%；結果見下 |
| 5 | `news_event_study.py`：事件研究法（AR = 個股 − 0050，視窗 ±5，按來源／字典情緒／新聞量分組）→ `AI/Doc/NewsEventStudy.md`；`XGBoost/train_m2.py` 重寫成每季 walk-forward（純價格 vs 價格+新聞，對照多數類與昨日延續）| 完成，結果見下；**未部署**（加 `--deploy` 才存檔） |

## 進度紀錄

### 2026-09-22

- 寫 `Crawler/backfill_news.py`。乾跑 2024-08-05~09：`tw_stock` 357 則（97 則有個股）、`us_stock` 170 則，
  0.6 分鐘。個股標記用 API `market` 欄位優先，再補 `tag_tickers` 公司名比對。
- 補 `user_news(title)` 索引：`insert_news_articles` 逐筆用標題查重，6 萬筆沒索引會退化成 O(n²)。
- `scheduler._catch_up_news`：不受每日標記與週末限制；空洞 > 2 小時才補；補完照常跑 `job_news`。
- 啟動三年回填（背景）。執行前基線：`user_news` 1,947 則、`news_crawl_raw` 2,008 則。

- 階段 2 模組全部寫完並單元測試：`news_schema.py`、`news_alias.py`、`news_dedup.py`、`news_align.py`。
  對齊規則測試：13:29 → 當日、13:30 → 次日、週六 → 週一、日曆外的未來交易日收盤前 → 當日。
  別名比對測試：`台積`／`TSMC`／`台灣50` 命中，`via email`／`circumcision` 不命中（英文整字、大小寫不分）。
- **被權限攔下的步驟**（自動模式判定為共用資源變更）：建表與灌別名。回填結束後由使用者執行：

  ```
  cd Crawler
  python news_schema.py            # 建 4 張新表 + user_news 加欄位
  python news_alias.py --seed      # 灌別名
  python news_dedup.py             # 全量去重
  python news_align.py --all       # 日曆 → 對齊 → 歷史特徵
  ```

  之後排程器每小時 `job_news` 會自動做近 7 天的增量（`_refresh_news_history`），表不存在時只記一行略過。
- 回填進度（23:19）：tw_stock 2023-09 ~ 2023-11 完成，每月 1,100~1,400 則、約 2 分鐘；
  三個分類全部跑完預估 4 小時。
- **MOPS 可用**：新版 `mops.twse.com.tw` 對程式回「安全性考量」頁，舊版 `mopsov.twse.com.tw/mops/web/ajax_t05st01`
  可依公司＋民國年月查，回表格（代號、名稱、發言日期、時間、主旨）。台積電 2024-08 有 30 則。
  `backfill_mops.py` 只存主旨（事件分類夠用），platform「MOPS重大訊息」、tier 1、content_kind `filing`。
- **國際新聞來源實測**：BBC Business／World RSS 用現有 `fetch_article_content` 直接抓到 3,400 字內文；
  CNBC、MarketWatch 原文頁是樣板，抓不到（不採用）。BBC 接進 `scrape_news`，不套財金關鍵字過濾
  （地緣政治、天災本來就不含財金詞）。
- `news_sources.py`：platform → (tier, scope, language) 集中定義；`--fill` 回填 user_news 的
  scope / source_tier / language / content_kind / source_url（source_url 從 news_crawl_raw 以標題對回）。
- `news_pilot/` 五個腳本寫完。`03_run_claude.py` 用 `claude -p --bare --json-schema --tools ""`，
  每批 15 則，可續跑，usage_log.csv 記 token 與費用。
- 修正：`news_schema.py` 原本在 Python 字串列表外寫了 SQL 註解（`-- ...`），是語法錯誤；
  之前被權限攔下所以沒跑到，改成 Python 註解。

#### 回填完成後要執行的指令（依序）

```
cd Crawler
python news_schema.py            # 建 5 張新表 + user_news 加欄位
python news_alias.py --seed      # 灌別名
python news_sources.py --fill    # 回填 scope / tier / language / content_kind / source_url
python news_dedup.py             # 全量去重
python news_align.py --all       # 日曆 → 對齊 → 歷史特徵
cd ../news_pilot
python scripts/02_prepare.py     # 抽 300 則 + gold_60_template.csv
python scripts/03_run_claude.py --limit 15   # 煙霧測試一批
```

#### 事件研究初步結果（回填到 2024-04 時，媒體來源 2,296 個事件）

| 分組 | n | AR₀ | t | \|AR₀\| 相對無新聞日基準 |
|------|---|-----|---|-------|
| 全部 | 2,296 | −0.10% | −2.0 | ×0.92 |
| 字典情緒正面 | 1,493 | −0.08% | −1.3 | ×0.93 |
| 字典情緒負面 | 224 | −0.25% | −1.6 | ×0.90 |
| 當日 4–10 則 | 506 | −0.09% | −0.7 | ×1.08 |

**字典情緒在這段資料上沒有方向訊號**：正面組的 AR₀ 也是負的，|AR₀| 沒有高於無新聞日。
這正是方案文件要做 LLM 結構化抽取的理由——關鍵字字典分不出「營收創高（例行）」與「意外砍單」。
待回填完成（含 MOPS 重大訊息與 2024-08、2025-04 兩個高波動窗口）後重跑，再看 MOPS 組與新聞量組。

### 2026-09-23

- MOPS 回填完成：963 次請求、80 分鐘，三次 502 都在 90 秒後重試成功。6,574 則公告。
- **發現 `insert_news_articles` 只用標題判重**：同主旨公告（「本公司代子公司公告取得固定收益證券」）每月再發，
  不同日期被當重複，6,574 則只進 3,945 則。改成「有發布時間就用標題＋發布日判重」，
  從 news_crawl_raw 補回 2,192 則 → user_news 內 MOPS 6,137 則（剩 437 則是同日同主旨，視為重複）。
  這個修正對 RSS 來源無影響（同一則 RSS 的 pubDate 不變）。
- 事件研究重跑（台股媒體到 2025-07、美股到 2025-07、MOPS 全部；10,503 個事件）。**跟只有 2,300 個事件時結論相反，有訊號**：

  | 分組 | n | AR₀ | t | \|AR₀\| 相對基準 |
  |------|---|-----|---|-------|
  | 全部 | 10,503 | +0.01% | +0.4 | ×1.32 |
  | 字典情緒正面 | 6,267 | +0.17% | +4.5 | ×1.39 |
  | 字典情緒負面 | 817 | −0.38% | −4.2 | ×1.25 |
  | 只有 MOPS 公告 | 1,128 | −0.33% | −5.2 | ×1.06 |
  | 當日 4–10 則 | 2,014 | +0.30% | +3.7 | ×1.75 |
  | 當日 >10 則 | 794 | +0.07% | +1.1 | ×0.68 |

  三個讀法：(1) 方向有訊號但很小（±0.2~0.4%），波動訊號較強（有新聞日 |AR| 高三成，4–10 則那天高七成五），
  與方案文件「主目標為波動幅度」一致；(2) 只有 MOPS 公告的日子平均是負的——重大訊息多半是處分資產、
  背書保證、董事會決議這類，字典把它們判成中性，LLM 的 event_type / is_expected 才分得出來；
  (3) >10 則的日子 |AR| 反而低於基準，那是台積電（天天十幾則），新聞量對大型股不是訊號。
  **注意**：AR₀ 是同日報酬，13:30 前發布的新聞有一部分是在報導當天盤中走勢（同時性，不是預測），
  嚴格的預測力要看 CAR[0,1] 扣掉 AR₀ 或只取收盤後發布的事件——留給 M2 走查驗證。
  完整表：`AI/Doc/NewsEventStudy.md`。
- 鉅亨網回填完成：230 分鐘、0 次警告。抓 120,157 則 → news_crawl_raw +119,724、user_news +109,699。
  `user_news` 現況 117,891 則，2023-09-01 起 **1,119 天每天都有新聞**（之前實際只有約 30 天）：

  | platform | 則數 | 有個股標記 |
  |----------|------|-----------|
  | 鉅亨網（台股） | 53,292 | 15,451 |
  | 鉅亨網美股 | 32,745 | 3,334 |
  | 鉅亨網頭條 | 24,095 | 1,794 |
  | MOPS重大訊息 | 6,137 | 6,137 |
  | RSS 四來源（2026-08 起） | 1,475 | 372 |

  資料庫 119 MB → 726 MB（新聞兩表 616 MB，每則約 5 KB——鉅亨網 API 內文比 RSS 摘要長，
  比執行前估的 2.2 KB 高一倍，仍在 C 槽可承受範圍）。
- 事件研究最終版（全部三年，10,820 個事件）與上一輪一致：正面 +0.16%（t +4.2）、負面 −0.28%（t −3.2）、
  MOPS-only −0.35%（t −5.4）、有新聞日 |AR| ×1.34。`AI/Doc/NewsEventStudy.md` 已覆蓋。
- LLM 試跑：`02_prepare` 從 user_news 抽 297 則（TW / US / GLOBAL × 2024-08 股災 / 2025-04 關稅 / 2025-11 平靜，
  各 33），另出 `gold_60_template.csv`。`03_run_claude` 兩個坑：
  (1) `--json-schema` 與 `--system-prompt` 的多行字串在 Windows 命令列會被拆壞 → schema 壓單行、
  system prompt 改 `--system-prompt-file`；(2) **`--bare` 會略過登入憑證，回「Not logged in」**，拿掉即可。
  煙霧測試 15 則：42 秒、輸出 4,525 tokens、報價 $0.108（訂閱額度，非現金）。
  抽取品質看起來對：盤勢週報 → other / 例行 / magnitude 1；特斯拉暴跌 → negative / 非預期 / TSLA；
  意法半導體裁員 → supply_chain / negative / STM。推估 297 則約 14 分鐘、報價約 $2。
- `XGBoost/train_m2.py` 重寫：新聞歸屬日用 13:30 規則、只對追蹤股、每個交易日一列（26 檔 × 745 日 = 16,226 樣本）、
  每季 walk-forward 11 折（2024Q1 ~ 2026Q3），同一個 XGBoost 分別餵「純價格」與「價格+新聞」：

  | 模型 | Accuracy | Macro F1 | 出手率 | 出手方向正確率 | 出手平均 3 日報酬 |
  |------|---------|---------|-------|-------------|---------------|
  | 多數類 | 0.343 | 0.169 | 0% | – | – |
  | 昨日延續 | 0.369 | 0.335 | 45% | 0.478 | −0.08% |
  | 純價格 | 0.384 | 0.347 | 49% | 0.499 | +0.18% |
  | 價格+新聞 | **0.389** | **0.361** | 58% | **0.515** | **+0.26%** |

  新聞版在 6/11 折 F1 贏過純價格，2025Q3、Q4 輸。增益存在但小（方向正確率 +1.6pp、每筆 +0.08%），
  跟事件研究「方向訊號小、波動訊號大」一致。特徵重要度：`mkt_sent_72h`、`mkt_sent`、`mkt_n` 三個
  **全市場**新聞特徵排在所有個股新聞特徵之前——字典情緒對個股的解析力弱，這是 LLM 特徵要補的位置。
  門檻（F1 與出手報酬都贏純價格）技術上通過，但 6/11 折不算穩，**留給使用者決定是否 `--deploy`**；
  `model2_news` 已加 `_features_iter38`：模型檔 `version == 'iter38'` 時用同一套定義即時算 13 個特徵（實測 2330：本股當日 21 則、全市場 180 則），舊模型檔仍走原本 7 特徵路徑；所以 `--deploy` 之後不用再改推論端。
- LLM 試跑完成。Sonnet 297 則 20 批、Opus 60 則 4 批，**JSON 失敗率 0%**，
  報價合計 $2.62（訂閱額度）。Sonnet 每批約 5,000 輸出 tokens、50 秒；Opus 每批只有 1,800 tokens、15 秒（rationale 短很多）。

  Sonnet 輸出分布（297 則）：event_type other 91 / macro_rate 58 / earnings 43 / guidance 28 / regulation 25 / product 18 /
  supply_chain 12 / geopolitics 9 / m_and_a 7 / legal 6；direction 正 101 / 負 90 / 中性 63 / mixed 43；
  magnitude 1:81、2:122、3:71、4:19、5:4；is_expected true 167；有 ticker 128 則（台股 59）；平均信心 0.54。
  scope 與抽樣類別對得上（TW 類 91/99 判 TW、US 類 87/99 判 US、GLOBAL 類 82/99 判 GLOBAL）。

  兩模型一致率（60 則）：

  | 欄位 | Sonnet vs Opus | 方案門檻（對人工標註） |
  |------|---------------|------------------|
  | event_type | 88.3% | ≥ 85% |
  | direction | 75.0% | ≥ 85% |
  | is_expected | 85.0% | ≥ 80% |
  | scope | 93.3% | ≥ 95% |
  | magnitude MAE | 0.28 | ≤ 0.7 |

  direction 一致率偏低，主要是 neutral 與 mixed 的邊界（總經新聞對兩市各有正負）——人工核對時優先看這一欄。
  **黃金標準草稿**已由 Opus 產出：`news_pilot/data/gold_60_draft_opus.csv`，人工核對後另存 `gold_60.csv` 再跑
  `04_evaluate.py` 得到正式一致率。magnitude 對隔日 |報酬| 的訊號檢查：抽樣裡台股 ticker 只有 59 則、
  有價格 35 則，且三分之一落在 2024-08-05 股災週，樣本太小無法判讀（1–2 分 3.9%、4–5 分只有 1 則）；
  要等正式跑情境 B 才有足夠樣本。

## 現況與下一步

**已可用**：三年新聞（117,891 則、1,119 天無缺口）、MOPS 公告、排程補洞、BBC 國際來源、
事件研究（有訊號）、M2 走查（新聞版小幅勝出、未部署）、LLM 抽取管線（試跑通過格式與一致率）。

**需要使用者做的**（依序）：
1. ~~建表等收尾指令~~ 已於 09-23 執行完成。
2. 覆核 `gold_60.csv`（note 欄標「待人工覆核」的 25 則）→ 重跑 `python scripts/04_evaluate.py`。
3. 決定 M2 是否 `python XGBoost/train_m2.py --deploy`（6/11 折勝出，增益小；建議等 LLM 特徵進來再決定）。
4. 決定是否開 API 帳號跑情境 B（tier-1 + 有 ticker 的 canonical，估 2~3 萬則、Sonnet Batch 約 $30）。
   `news_llm_feature` 表與 `05_load_db.py` 已備好。

**尚未做**：Finnhub（需 API key）、GDELT（等 GLOBAL scope 證明有增益）、LLM 特徵進 M2（等情境 B）、
`Server`／`Screen` 端顯示 scope／tier（前端未改）。

**未 commit**：本迭代所有變更都在工作區，等使用者確認後提交。

### 2026-09-23（使用者要求執行收尾指令）

- 建表、別名、來源欄位、去重、對齊這次都沒被攔，全部跑完：
  `instrument_alias` 57 筆（stock_info 只有 26 檔，別名主要來自手工表）；`user_news` 來源欄位回填 117,910 列、
  source_url 對回 117,862 列；去重 551 群、1,658 則重複；`trading_calendar` 18,100 日；
  `news_price_link` 45,056 筆（27,642 則新聞）；`news_daily_features` 11,993 列。
- 新增 `news_retag.py`：回填時別名表還不存在，用別名表重標全部新聞——只有 1,282 則多出 1,406 個標記
  （鉅亨網 API 的 `market` 欄位已經標得很齊，別名表的增量主要在 RSS 來源）。重標後重跑 link / features。
- 黃金標準：以 Opus 草稿為底，25 則 Sonnet／Opus 不一致者逐則依 system.md 規則裁定（改了 14 個欄位，
  例：幣圈崩跌 → other 而非 macro_rate；Fed 官員談話 → 例行；盤勢綜述不填 ticker；美國內政 → scope US），
  存 `gold_60.csv`，note 欄標「待人工覆核」。**注意這份 gold 的底是 Opus 的輸出，Opus 的分數因此偏高**
  （magnitude MAE 0 是因為沒有裁定過 magnitude），真正的驗證要等人工覆核。

  | 欄位 | 門檻 | Sonnet | Opus（偏高） |
  |------|------|--------|-------------|
  | event_type | ≥ 85% | 93.3% | 95.0% |
  | direction | ≥ 85% | **80.0%** | 95.0% |
  | is_expected | ≥ 80% | 96.7% | 88.3% |
  | scope | ≥ 95% | **93.3%** | 100% |
  | magnitude MAE | ≤ 0.7 | 0.28 | 0.00 |
  | ticker 召回 / 精確 | ≥ 90% / ≥ 85% | 100% / 92.1% | 97.1% / 100% |

  Sonnet 兩項未達標：direction（neutral／mixed 邊界，TW 類只有 75%）與 scope（差 1 則）。
  對應方案文件的決策表：「event_type 穩、direction 不穩」→ 修訂 direction 定義重跑，
  具體是在 system.md 加「無明確標的或對兩市影響相反 → mixed；只是資訊性報導 → neutral」的例句，
  再跑一次 Sonnet；仍不到 85% 就改 Opus（單則報價約 Sonnet 的 5 倍，情境 B 約 $130）。
