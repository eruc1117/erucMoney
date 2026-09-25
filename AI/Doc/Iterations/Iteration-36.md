# Iteration 36 — 遺留待辦清理：持股不進模型、排程器常駐、IMPR-001 結案

**日期：** 2026-09-20

## 起點

使用者要求把專案進度盤點出來的六項遺留待辦「依照順序做完」：

1. 外資真實持股（Iteration 35 補進的 `stock_foreign_holding`）要不要進模型
2. 市場總覽與個股分析的「外資持股%」沒標資料日期
3. 排程器仍依賴 start-dev.bat 被人打開
4. bugs.md 未關閉項目：DATA-005、MODEL-004、IMPR-001
5. Iteration 25~27 沒有獨立文件
6. 根目錄殘留檔

結論先講：**第 1 項的答案是「不進」**——這是本迭代最重要的一行，下面先講它。

## 一、外資真實持股：五個模型全部未通過

### 特徵設計（`Crawler/holding_features.py`，panel 區塊 `holding`）

買賣超（chip 區塊）是**流量**，持股是**存量**。兩者日變動高度相關但不相等
（2330 近期一天：買超 +603 萬股、持股 +335 萬股，差額是借券與非集中市場移轉），
而存量本身有流量沒有的資訊：水位、長期趨勢、離投資上限的距離。做了 7 個特徵：

| 特徵 | 意義 |
|------|------|
| `fh_ratio` | 持股比例（水位） |
| `fh_chg_1d / 5d / 20d / 60d` | 多天期變動；60 日是買賣超特徵沒有的視野 |
| `fh_z60` | 相對自身 60 日均值的 z 分數 |
| `fh_headroom` | 投資上限 − 持股 |

時序與 chip 區塊一致：D 日揭露的持股用於預測 D+1 起的事。逐檔 as-of 合併，
缺日退回前一日存量，面板裡沒有持股的股票（美股）留 NaN 不補零。

### 驗證：沿用 Iteration 30 的巢狀走查，一個字都沒改門檻

`UnifiedModel/optimise_all.py` 加入「現行+持股」變體，並把振幅／波動率的**現行基準對到
已部署的 v2**（Iteration 30 的腳本裡「現行」還是 v1，這次順手修正）；成交量模型新增為第四個
loader。M3 是分類器，另寫 `RandomForest/ablate_m3_holding.py` 在 2012 起的完整樣本上測
（與 exog 消融分開，因為那份被夜盤砍到 2018 起）。

**四個迴歸模型，12 個外層折，「現行+持股」只被內層選中 1 折**（成交量折 3）：

| 模型 | 三折內層各挑中 | 持股被選中 |
|------|--------------|-----------|
| gap | 自身+全部、自身+全部、自身+夜盤+韓日 | 0/3 |
| range | v1+夜盤、v2、v1+夜盤 | 0/3 |
| volatility | v2、v2、v2 | 0/3 |
| volume | 現行、現行、**現行+持股** | 1/3 |

M3（`results/m3_holding_ablation.md`，38,568 筆 / 5 折）：

| 特徵組合 | 買進方向 | 買進平均報酬 | 出手率 |
|---------|---------|------------|--------|
| 現行（籌碼+橫斷面） | **52.44%** | **+0.37%** | 82.7% |
| 現行 + 持股 | 52.07% | +0.32% | 81.1% |

方向 −0.37pp、報酬 −0.04pp，門檻是 +1pp——**不是沒過，是變差**。
與 Iteration 30 的 M3 外生消融同一個型態：多出來的維度讓樹找到假切分點。

### 為什麼會這樣

持股的日變動幾乎就是買賣超（相關極高），這部分 chip 區塊已經有了；
剩下的「存量水位」與「長期趨勢」是慢變數，對 1~20 日的預測目標而言接近常數，
樹模型拿它當分群鍵只會把樣本切碎。事後看說得通，但事前不測就是猜——
Iteration 35 遺留問題寫的正是「要用巢狀走查驗，不是加了就上」。

### 部署狀態

- `holding` 區塊保留在 `panel.py`（資料層完整，之後任何模型要試都是一行的事）
- 沒有任何模型的特徵清單納入 `fh_*`；`features.py` 的 CHIP_FEATURES 註解已更新說明原因
- **不動線上任何模型**

### 一個必須講的副產物：超參數重調過了門檻，但那與持股無關

同一份報告裡 range / volatility / volume 三個模型「判定：部署」——請看清楚勝出組合：
`v1+夜盤`、`v2（現行）`、`現行`，**沒有一個含持股**。分數差距（+0.0208 / +0.0106 / +0.0166）
來自內層挑到的超參數（一致偏向 `learning_rate 0.03、max_depth 4`）對上 `DEFAULT_PARAMS`。

這不能直接當部署依據，因為「現行設定」在腳本裡是用 `DEFAULT_PARAMS` 訓的，
不一定等於線上那顆模型的實際參數。它是一條線索，不是結論，記在遺留問題。
順帶：振幅模型三折有兩折挑「v1+夜盤」而非現行的 v2（+韓日）——Iteration 30 就標記
v2 穩定性只有 67%「應在下次走查時複驗」，這次複驗的結果是韓日對振幅的貢獻站不穩。

### 踩到的資料坑（DATA-008）

M3 消融在 2012 起的完整樣本上跑，`ret_5d` 出現 inf：`0052 / 2017-06-01` 的 open/close 為 0。
`features.LOAD_SQL` 有 `close_price > 0` 過濾，`experiment_m3.load_dataset` 沒有。
消融腳本把 inf 換成 NaN 後丟掉；資料列未動，記在 bugs.md。

## 二、外資持股%：標出資料日期

`GET /stocks/:id` 與 `GET /stocks?tracked=true` 一併回傳 `foreign_holding_date` 與行情 `trade_date`。
前端新增 `services/holding.js`：持股日期早於行情日期就標「（9/18）」或「（晚於行情）」，
滑鼠停留顯示完整日期；對齊時只在 tooltip 顯示日期，不加雜訊。

## 三、排程器常駐化

9/19 18:00 沒跑的原因是程序根本不在。三件事：

1. **檔案日誌**：`Crawler/logs/scheduler.log`（RotatingFileHandler，5MB × 5）；
   主控台 handler 只在有 stderr 時加——`pythonw` 沒有。
2. **啟動補跑 `_catch_up()`**：APScheduler 的 cron 任務在程序不在時不會補跑。
   啟動時若當天已過 18:00 且行情最後日早於今天 → 跑 `job_stock`；已過 20:00 且今日無投票 →
   `job_vote`；再 `job_model_review`。只在資料確實落後時跑（假日與重複登入不燒 FinMind 額度），
   `logs/catchup_YYYY-MM-DD` 標記一天最多一次。
3. **`install_scheduler_task.ps1`**：註冊 Windows 工作排程器「MoneyScheduler」——
   登入即啟動（Interactive，不存密碼）、延遲 1 分鐘等 PostgreSQL、失敗 2 分鐘後重啟最多 5 次、
   不限執行時間、不重複啟動。`start-dev.bat` 偵測到它在跑就不再開第二份排程器。

**註冊這一步沒有由程式執行**：自動權限判定把「登入即啟動的工作」歸為需要人確認的動作。
腳本已就位，執行方式在 Architecture.md 的啟動指令。

## 四、bugs.md 三個未關閉項目

| 項目 | 查證結果 | 處置 |
|------|---------|------|
| DATA-005 新聞發布時間全空 | `news_crawl_raw` 2,008 筆，1,958 筆有時間且格式合法；只剩最早 50 筆（同一批 `scraped_at`）為空 | Iteration 10 的管線已修；寫 `cleanup_news_raw.py`（備份後刪）供使用者執行，刪除列的動作被權限擋下 |
| MODEL-004 LSTM 等同基準、DA 算法錯 | 投票端在 Iteration 22 已把 M1 權重 0.34 → 0.15；DA 算法一直沒修 | `evaluate.compute_metrics` 改為相對前一日實際收盤；`voting_engine` docstring 同步 |
| IMPR-001 LSTM 改進計畫 | `train_improvements.py` 早就寫好、從未跑過 | 跑完四檔，見下節 |

### IMPR-001：跑完了，結案

`LSTM/train_improvements.py` 對 2330 / 2344 / 2323 / 2324 逐輪套用 IMP-001~006（M01 架構，
EPOCHS 100、PATIENCE 15），方向準確率用修正後的定義（相對前一日實際收盤）：

| 輪次 | 設定 | 2330 | 2344 | 2323 | 2324 | 四檔平均 DA |
|------|------|------|------|------|------|-----------|
| R0 | M01 原版（價格、MinMax） | 47.2% | 46.9% | 45.3% | 48.0% | 46.9% |
| R1 | IMP-001 log return | 49.9% | 48.2% | 46.0% | 45.3% | 47.4% |
| R2 | +IMP-002 十特徵 | 46.1% | 46.6% | 47.5% | 46.2% | 46.6% |
| R3 | +IMP-003 rolling z-score | 49.5% | 51.8% | 49.5% | 48.1% | **49.7%** |
| R4 | +IMP-005 DA early stopping | 49.5% | 51.6% | 50.2% | 44.4% | 48.9% |
| R6b | IMP-006 動態集成 | 46.3% | 47.1% | 46.1% | 50.3% | 47.5% |
| R5 | IMP-004 walk-forward（口徑不同，見下） | 56.5% | 55.0% | 57.3% | 57.2% | — |

MAPE 的走勢：R0 → R1 明顯下降（2330 1.75% → 1.43%），之後各輪幾乎不動；R6 集成反而變差。
最好的一輪（R3）四檔平均 49.7%，**沒有一輪過 Iteration 11 立的 51% 門檻**，四檔各自最佳也只有
2344 的 51.8%（單檔單次，樣本不足以當證據）。原始輸出：`LSTM/report/improvement_log.csv`。

各項改進與證據的對應：

| 項目 | 內容 | 結果 |
|------|------|------|
| IMP-001 Log return 目標 | R1 | MAPE 降（照抄不再是最佳解），但 DA 仍在 50% 附近；與 Iteration 11 四種架構 48~50% 一致 |
| IMP-002 特徵 5 → 10 | R2 | MAPE 反而升（樣本少、特徵多） |
| IMP-003 Rolling z-score | R3 | 把 IMP-002 的惡化拉回，DA 不動 |
| IMP-005 DA early stopping | R4 | 與 R3 幾乎相同 |
| IMP-004 Walk-forward | R5 | 數字**不可與其他輪比較**：它比的是「正規化目標的正負號」，即「明日報酬是否高於過去 20 日平均報酬」，不是漲跌；Iteration 12 已用正確口徑做過走查 |
| IMP-006 動態集成 | R6 | 對三個各自等同基準的模型做加權平均，結果仍等同基準（數學上必然） |

**目標指標 DA ≥ 55% 在這份資料上不可達**（Iteration 12 用 54 個特徵的梯度提升最佳也只有
59.89%、出手率 5%）。IMPR-001 的六項裡有四項在 Iteration 11/12 就已被更強的實驗涵蓋，
這次把剩下兩項跑完，結論不變：**LSTM 收盤預測不部署為方向訊號**，維持趨勢角色 0.15 權重
與可停用的現狀。

## 五、Iteration 25~27 補件

依 git log 補寫 `Iteration-25.md`（UI 改版、紅漲綠跌、投票頁拆兩區）、`Iteration-26.md`
（預測比對重做、三層自動檢查、閒置資金配置）、`Iteration-27.md`（資料新鮮度、趨勢預測頁自我診斷），
README 索引改為逐一連結。

## 六、殘留檔

`git rm Markdown.md`（0 bytes）、刪除 `crawl_debug.log` 與 `yahoo_raw.html`（3 月的除錯產物，未被追蹤）。

## 改動檔案

| 檔案 | 改動 |
|------|------|
| `Crawler/holding_features.py` | 新增：7 個持股特徵、逐檔 as-of 掛載 |
| `UnifiedModel/panel.py` | 註冊 `holding` 區塊 |
| `UnifiedModel/optimise_all.py` | 「現行+持股」變體；range/volatility 現行基準對到 v2；新增 volume loader；`--stocks`；報告另存 `optimise_all_holding.md` |
| `RandomForest/ablate_m3_holding.py` | 新增：M3 持股消融（2012 起完整樣本、inf 處理） |
| `UnifiedModel/features.py` | CHIP_FEATURES 註解：持股已測、不進 |
| `Server/routes/stocks.js` | 兩個端點回傳 `foreign_holding_date` |
| `Screen/src/services/holding.js`、`Overview.jsx`、`StockAnalysis.jsx` | 持股日期標示 |
| `Crawler/scheduler.py` | 檔案日誌、`_catch_up()` |
| `Crawler/install_scheduler_task.ps1`、`uninstall_scheduler_task.ps1` | 工作排程器註冊／移除 |
| `start-dev.bat` | 偵測 MoneyScheduler，避免雙開 |
| `Crawler/cleanup_news_raw.py` | DATA-005 收尾腳本（查證／備份／刪除） |
| `LSTM/evaluate.py` | DA 改為相對前一日實際收盤 |
| `Crawler/voting_engine.py` | docstring：M1 權重已定 |
| `AI/Doc/Iterations/Iteration-25/26/27.md` | 補寫 |
| `AI/Doc/Bugs/bugs.md` | DATA-005、MODEL-004、MODEL-005、IMPR-001 結案；新增 DATA-008 |
| `AI/Doc/Architecture.md`、`README.md`、`.gitignore` | 啟動指令、索引、`Crawler/logs/` |

## 誠實評估

- ✅ 持股的否決是在 Iteration 30 的門檻與流程下得出的，沒有為了「讓資料派上用場」放寬任何條件。
- ✅ IMPR-001 從「待實作」變成「跑過、有數字、結案」；不是關掉，是做完。
- ⚠️ 排程器常駐的**註冊**動作與新聞舊資料的**刪除**動作都停在使用者手上。程式與文件都備妥，
  但本迭代結束時 9/19 那種「沒人開就不跑」的狀態**尚未**真正解除。
- ⚠️ 超參數重調的「部署」判定是副產物，未部署也未否決，需要一次以線上模型實際參數為基準的複跑。

## 遺留問題

1. **執行 `install_scheduler_task.ps1`**，並在隔天確認 `logs/scheduler.log` 有 17:30／18:00／20:00 的紀錄。
2. **執行 `cleanup_news_raw.py --apply`** 清掉 50 筆無日期舊新聞。
3. **超參數重調複跑**：以 `train_range.py`／`train_volatility.py`／`train_volume.py` 實際使用的參數
   為「現行」重跑巢狀走查；若 +0.01 仍成立則重訓部署。同時複驗振幅 v2 的韓日特徵是否該拿掉。
4. **DATA-007／008 根治**：`stock_daily_prices` 加 `close_price > 0` 檢查約束，M3 載入 SQL 補過濾。
