# 交易模擬 匯入／匯出 檔案格式（2026-10-19 使用者已確認、Iteration 87 已實作）

**日期：** 2026-10-19
**狀態：** 2026-10-19 使用者確認五點（見第三節的答案），同日 Iteration 87 實作完成（`Screen/src/lib/simIO.js`、`TradingSim.jsx`、`RuleBuilder.jsx`；後端未動）。
**範本檔：** `AI/UserDoc/sim_templates/`——三個匯入範本手寫；四個匯出範本（`sim_result.json`、`sim_trades.csv`、`sim_series.csv`、`sim_metrics.csv`）由 `node AI/experiments/iter87_templates.mjs` 用程式對 tests 的共用樣本（`Screen/tests/fixtures/sim_sample.mjs`）實際產生，不手改

## 一、匯入（兩種檔，對應頁面上的兩種模式）

| 檔 | 給哪個模式 | 格式 | 範本 |
|---|---|---|---|
| 指令 CSV | 日期指令（表單） | UTF-8（可帶 BOM，Excel 直接存就行），逗號分隔，第一列標題 | `sim_instructions.csv` |
| 規則 JSON | 條件規則 | JSON，`rules` 結構與現在 `/sim/rules` 的 body 完全相同 | `sim_rules.json` |

### 指令 CSV 欄位

| 欄 | 必填 | 內容 |
|---|---|---|
| `date` | 是 | `YYYY-MM-DD`（也收 `2024/01/15`、`20240115`） |
| `side` | 是 | `買`／`賣`（也收 `buy`／`sell`、`b`／`s`） |
| `stock_id` | 是 | 4～6 碼代號 |
| `qty` | 看 unit | 數字；`unit=全部` 時留空 |
| `unit` | 是 | `股`／`張`／`元`／`全部`；賣出不能用 `元` |
| `note` | 否 | 自由文字，不影響模擬，原樣帶進結果檔 |

- `#` 開頭的列是註解，略過。
- 匯入後進「日期指令（表單）」的清單，按「跑模擬」才走現有解析與上限（200 筆、8 年）。壞列不擋整檔：好列照收，壞列與原因列在匯入訊息（最多列 5 列）。
- **期間、資金、資料來源、種子不在 CSV 裡**，用頁面上的表單（要放進檔裡的話用規則 JSON 那種 `settings`，見下）。

### 規則 JSON

```
{ "format": "erucmoney-sim-rules/1",
  "settings": { "start", "end", "capital", "source", "seed" },   // 可省略；有就覆蓋頁面表單
  "rules": [ …與 /sim/rules 相同… ] }
```

- 匯入「比較全部策略」或範本按鈕產生的規則也能存成這個檔再匯入。
- 沒有 `format` 欄或是純陣列 `[ {…}, {…} ]` 也收（當成只有 `rules`）。

## 二、匯出（跑完模擬後一鍵下載）

| 檔 | 內容 | 給誰 | 範本 |
|---|---|---|---|
| `sim_result_<日期時間>.json` | 完整結果：設定、資料來源、**輸入原樣**（指令或規則）、指標、成交、略過／觸發、期末持股、淨值序列、caveat | 存檔、重跑（匯入這個檔會還原輸入與設定）、程式讀 | `sim_result.json` |
| `sim_trades_<日期時間>.csv` | 成交明細，一列一筆 | Excel | `sim_trades.csv` |
| `sim_series_<日期時間>.csv` | 淨值序列（組合／0050 含息／現金），畫圖用 | Excel | `sim_series.csv` |
| `sim_metrics_<日期時間>.csv` | 指標 `key,label,value` 一列一項 | Excel | `sim_metrics.csv` |

### 成交 CSV 欄位

| 欄 | 內容 |
|---|---|
| `seq` | 成交序號 |
| `ref` | 來源：指令是「第 N 列」、規則是「規則 #N」 |
| `signal_date` | 指令日／觸發日 |
| `date` | 實際成交日（順延或隔天開盤） |
| `stock_id`、`side` | 代號、`buy`／`sell` |
| `shares`、`price`、`gross` | 股數、成交價（還原價）、成交額 |
| `fee`、`tax` | 手續費、證交稅（買單 0） |
| `pnl` | 賣出的已實現損益（買單空白） |
| `note` | 部分成交等備註 |

### 淨值 CSV 欄位

`date,nav,bench,cash`：`nav`／`bench` 起點 1、最多四位小數（不補零，`1` 就是 `1`）；`cash` 整數元。

### 結果 JSON 與現在 API 回傳的差別

- 多 `format`、`generated_at`、`mode`、`settings`、`input`；`metrics`、`final`、`caveat`、`source` 沿用現在 `/sim/run`／`/sim/rules` 的回傳；`series` 的 `d` 改名 `date`；`trades` 以 `seq`／`ref`／`signal_date` 取代 `line`／`asked`／`rule`，規則的 `text` 不帶；`skipped`／`triggers` 也改用 `ref`。
- `trades` 多 `seq` 與 `ref`（原本指令模式是 `line`、規則模式是 `rule`，統一成人看得懂的字串）。
- 指令模式 `triggers` 是 `null`、規則模式 `skipped` 是 `null`。
- 合成行情的結果照樣匯出，`source.kind = "synthetic"`、caveat 帶警示，檔名不另外標。

## 三、要你確認的點

1. 匯入 CSV 的設定（期間、資金、來源、種子）放表單不放檔裡——可以嗎？還是也要能從檔案帶？ → **可以**（規則 JSON 與結果 JSON 仍可帶 `settings`）
2. 匯出要四個檔各自下載，還是一個 zip？（zip 要多拉一個前端套件） → **打包 zip**（最後沒拉套件：自己寫只存不壓的 zip）
3. CSV 編碼：UTF-8 帶 BOM（Excel 開不會亂碼，但部分程式讀到 BOM 會當成第一欄名字的一部分）。 → **OK**
4. 檔名用 `sim_<類型>_<YYYYMMDD-HHMM>.csv`，還是要帶股票／模式？ → **不要**；zip 本身是 `sim_<YYYYMMDD-HHMM>.zip`
5. 匯出的成交 CSV 的 `side` 用 `buy`／`sell` 還是 `買`／`賣`？（匯入兩種都收） → **buy／sell**
