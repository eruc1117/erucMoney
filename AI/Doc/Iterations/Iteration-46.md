# Iteration 46 — 修跳空模型線上時序、排程器常駐

**日期：** 2026-09-29
**起因：** 使用者問「現有模型可不可以用，還是要更多實測」。重跑 `model_lifecycle --report-only` 後發現兩件事擋住實測本身：
跳空模型的線上輸出仍是 9/20 報告指出的對齊錯誤（9/20 之後沒有任何模型相關 commit），
以及排程器從來沒有註冊成常駐工作（工作排程器只有 MoneyApi／MoneyCalendarApi／MoneyCrawlerApi／MoneyLstm 四個）。

## 一、今天的線上台帳（修正前）

| 模型 | 到期樣本 | 線上指標 | 判定 |
|------|---------|---------|------|
| range v2 | 204 | 排序相關 0.700 | 可凍結 |
| volatility v2 | 127 | 排序相關 0.731 | 可凍結 |
| volume v1 | 153 | 排序相關 0.417 | 可凍結 |
| gap v2 | 230 | 方向 49.5%，多數類別 51.96% | 對齊錯誤（下節） |
| m3_chip | 151 | 出手 6 次 | 無法判定 |
| us_gap v2 | 23 | 排序相關 0.511 | 樣本不足 |
| lstm:*（台股） | 0 | 9/22 才第一次進台帳（14 筆／模型），10/15 到期 | 無資料 |
| lstm_us:* | 5 | — | 樣本不足 |

台帳最後一筆預測停在 9/22；gap v2 從 8/7 到 9/22 七週只有 **9 個交易日**有寫預測（8/7、8/10、8/11、8/14、8/24、9/8、9/9、9/11、9/18）——
只有人手動跑 `start-dev.bat` 的日子才有。振幅／成交量的到期數字與 9/20 報告一模一樣，就是因為中間沒有新預測進來。

## 二、跳空模型：對齊錯誤複驗與修法

用今天的 230 筆重算（`predicted_value` 對行情表重算的真實跳空）：

| 對照對象 | 相關 |
|---------|------|
| 目標日（隔一個交易日）的跳空 | −0.032 |
| 預測當天**已經發生**的跳空 | **+0.76** |

與 9/20 報告一致（當時 −0.115／+0.727）。根因不變：`futures_daily` 的 after_market 列以「夜盤結束那天」為 trade_date
（9/23 after_market 在 9/23 position 之前就入庫、且領先 9/23 開盤），訓練面板每列的 `night_*` 因此是「該列當天早上收的夜盤」。
推論取最新收盤日 D 那列時，夜盤是 D 的，描述的是 D 已發生的開盤；要預測 D+1 得換成 D+1 的那一場，而它 D+1 05:00 才收。

修法（`Crawler/gap_model.py`）：

- `_fresh_night_row(latest_tw)`：取 `load_night_panel('TX')` 裡 trade_date > 最新收盤日的那一列。沒有 → 夜盤未收，回 None。
  有兩列以上 → 個股行情落後了，同樣回 None（硬配最新夜盤只是另一種對齊錯誤）。
- `_build_latest_features()` 多回傳 `night_date`，有夜盤才把 `NIGHT_FEATURES` 八欄換成那一場；快取鍵改為「收盤日|夜盤日」。
- `predict_gaps()`：`night_date` 為 None 時回 `available=False, night_pending=True`，**不輸出也不寫台帳**；
  有值時回應多 `night_date`，台帳 `target_date` 直接用它（不再用行事曆推估）。
- 呼叫端（投票 `_get_gap_info`、閒置資金 `_gap_map`、週預測 `_batch_tw`、`/gap/predict`）原本就處理 `available=False`，不必改；
  週預測拿掉 9/20 加的「線上時序待修」caveat，改帶 `night_date`。

實測（23:31）：`_fresh_night_row(2026-09-22)` → 9/23（night_ret +0.53%，對得上 2330 9/23 開高 +0.6%）；
`_fresh_night_row(2026-09-24)` → None；`predict_gaps()` → `night_pending`，理由寫明 06:10 之後才有。

## 三、排程：06:20 專跑跳空

`scheduler.job_gap_predict`，CronTrigger 06:20（06:10 外生資料把夜盤抓進來之後、09:00 開盤之前），misfire 寬限 1 小時。
啟動補跑加一段：**只在 06:20~09:00 之間**、且今天開盤（target_date = today）還沒有跳空紀錄時，先補 06:10 的外生更新再跑跳空；
開盤後不補——那時再寫就不是預測了。`_gap_catch_up_due()` 查不到資料庫一律不補。
`tests/test_scheduler.py` 對應加三個案例（開盤前補、開盤後不補、今天已寫過不補），登記時點斷言 06:20 晚於 06:10。

20:00 投票與閒置資金頁在夜盤收完前拿不到跳空，「盤前定價」角色缺席。這是正確的：那個時間點沒有人知道明天的夜盤。

## 四、台帳作廢欄與對齊自檢

- `Server/migrations/019_model_predictions_invalid.sql`：`model_predictions.invalid_reason TEXT`，並把 gap 在 2026-09-25 之前的
  所有紀錄（v1 24 筆＋v2 256 筆）標成 `night_alignment`。不刪——留著才對得出當時線上到底輸出了什麼。
- `model_lifecycle.FETCH_SQL` 與 `/models/registry` 的 `pred_resolved` 排除 `invalid_reason` 非 NULL 的列；registry 多回 `pred_invalid`。
- `ledger_audit._leak_check()`：跳空類版本的預測值對 predicted_on 當天已實現跳空（SQL `LAG` 算 open/prev_close−1）的相關，
  ≥ 30 筆且 > 0.5 就列進 problems，21:00 的 `job_model_review` 會印在排程日誌。這正是 9/20 報告建議、當時沒做的那道自檢。
- Jest `migrations.test.js` 的 18 → 19，在 Stock_migtest 全新資料庫跑過。

**正式資料庫的 migration 019 尚未套用**：本會話直接對 Stock 資料庫 `ALTER TABLE` 被 auto mode 擋下（與 9/22 同一種拒絕）。
MoneyApi（Node）重啟時 `lib/migrate.js` 會自動套用；在那之前 21:00 的模型評估與稽核會因欄位不存在而報錯。

## 五、MoneyScheduler 常駐

`Crawler/install_scheduler_task.ps1` 第一次執行失敗：檔案沒有 UTF-8 BOM，Windows PowerShell 5.1 把中文註解讀成 cp950，
`$trigger.Delay = 'PT1M'` 那行被拆壞（Iteration 42 對 Deploy 腳本做過同樣的修正，這支漏了）。存成 BOM 後註冊成功：

```
已註冊 MoneyScheduler：狀態 Running，上次啟動 09/29/2026 23:32:58
```

登入即啟動、失敗兩分鐘後重啟、pythonw 無視窗、日誌 `Crawler/logs/scheduler.log`。

第二個問題在第一次補跑就露出來：`補跑中斷：Cannot log to objects of type 'NoneType'`。pythonw 沒有主控台，`sys.stderr` 是 None，而 FinMind 套件在 import 時做 `loguru.logger.add(sys.stderr)`，於是任何要抓行情的工作都在 import 那一刻失敗——也就是說 Iteration 36 設計的 pythonw 常駐從來沒有真正跑過股價更新。修法：`scheduler._ensure_std_streams()` 在任何工作 import 之前把 None 的 stdout／stderr 換成 devnull（檔案日誌不受影響）。改完重啟 MoneyScheduler，啟動補跑接著把上週日漏掉的每週預測補了。啟動當下的補跑先補了新聞空洞（546 則），
接著依規則補股價／投票／模型評估。`start-dev.bat` 原本就會偵測 MoneyScheduler 在跑而不再開一份。

## 六、對「模型能不能用」的回答

- 振幅／波動率／成交量三個閘門模型：線上站得住，可以凍結服役；但樣本全在單邊上漲期，下一段震盪期要複驗。
- 跳空：模型有效、線上從今天起才開始正確累積，成績從零算，約 4 個交易日到 100 筆。
- M3 籌碼、M2 新聞、LSTM：維持 9/20 報告的結論，不建議再投測試資源；M3 要先改記機率才可能判定。

## 變更檔案

`Crawler/gap_model.py`、`Crawler/scheduler.py`、`Crawler/ledger_audit.py`、`Crawler/model_lifecycle.py`、`Crawler/weekly_forecast.py`、
`Crawler/install_scheduler_task.ps1`（BOM）、`Crawler/tests/test_scheduler.py`、`Crawler/README.md`、
`Server/migrations/019_model_predictions_invalid.sql`、`Server/routes/models.js`、`Server/tests/db/migrations.test.js`、`Server/README.md`、
`AI/Doc/ModelAccuracy.md`、`AI/Doc/README.md`
