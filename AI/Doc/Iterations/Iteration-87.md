# Iteration 87 — 交易模擬加匯入／匯出：匯入指令 CSV、規則 JSON 或之前匯出的結果 JSON，跑完一鍵下載 zip（結果 JSON＋成交／淨值／指標 CSV）；格式先寫範本給使用者確認、zip 自己寫不加套件、純前端不用重啟

**日期：** 2026-10-19
**依據：** 使用者：「交易模擬 提供一個輸入輸出功能，先提供模板確認輸入輸出的檔案格式及內容」→ 模板五問的回答：設定用表單不放 CSV（可以）、四個檔打包 zip、CSV 用 UTF-8 帶 BOM（OK）、檔名不帶股票或模式、成交的 side 用 buy／sell
**規則：** 純前端（兩個前端各一份、逐 byte 相同），後端 FastAPI／Node 一行未動、不用重啟；不寫任何資料表、`portfolio_runs` N 不動；匯入只進頁面狀態（和手動輸入一樣走原本的 `/sim/run`／`/sim/rules`），沒有新的上傳端點；zip 只存不壓（STORE）、不加 npm 套件。

（這個檔 2026-10-19 23:07 曾被並行的另一個 session 用 Write 蓋成它的紀錄，它的那份已改名 `Iteration-88.md`；本檔從主 session 的上下文重寫，內容與審查第二輪讀到的版本相同，再加第二輪的兩處修正。）

## 一、做了什麼

1. **格式規格與範本**（先給使用者確認，再實作）：`AI/UserDoc/TradingSimIO.md` ＋ `AI/UserDoc/sim_templates/` 六個檔（`sim_instructions.csv`、`sim_rules.json`、`sim_result.json`、`sim_trades.csv`、`sim_series.csv`、`sim_metrics.csv`）。tests 直接讀三個匯入範本（`sim_instructions.csv`、`sim_rules.json`、`sim_result.json`）當輸入；四個匯出範本（含 `sim_result.json`）由 `AI/experiments/iter87_templates.mjs` 用程式對共用樣本 `Screen/tests/fixtures/sim_sample.mjs` 實際產生（`templates-gen-87`），所以匯出範本就是程式輸出（第一版是手寫、小數有補零，審查後改成程式產生）。
2. **`Screen/src/lib/simIO.js`**（新，純函式；只有 `downloadBytes` 用到 `document`，`exportSim` 傳 `download: false` 就不碰——`node --test` 可跑；`meeting_front_end/src/stock/lib/simIO.js` 同一份）：
   - 匯入：`parseInstructionsCsv`（BOM、`#` 註解列、有無標題列、引號欄位、買／賣與 buy／sell、股／張／元／全部；壞列各自記原因，好列照收、依日期排序）；`parseRulesJson`（`{format, settings?, rules}` 或純陣列；`settings` 只留合法欄）；`parseImport(name, text)` 依副檔名分流，結果檔（`format = erucmoney-sim-result/1`）還原 `settings` 與 `input`（指令列或規則）。
   - 匯出：`buildResultJson`（規格第二節：`format`、`generated_at`、`mode`、`settings`、`source`、`input` 原樣、`metrics`、`trades` 多 `seq` 與 `ref`「第 N 列」／「規則 #N」、指令模式 `skipped`／規則模式 `triggers`、`final`、`series`、`caveat`）；`buildExportFiles`（四個檔，CSV 帶 BOM、CRLF、欄位照規格，`sim_metrics` 一列一項）；`zipStore`（STORE、CRC-32、檔名 UTF-8 flag）；`exportSim` 組起來下載 `sim_<YYYYMMDD-HHMM>.zip`。
3. **頁面**：`TradingSim.jsx` 工具列多「匯入」（隱藏的 `<input type=file accept=.csv,.json>`）與跑完後的「匯出（zip）」；匯入指令 CSV 或指令結果檔 → 切到「日期指令（表單）」並放進清單（註解 `note` 保留；匯出時用後端回的 `line` 對回表單列——表單先用 `rowOk` 濾掉不完整的列再對，和 `rowsToText` 的編號一致；審查抓到第一版沒濾，有空列時會錯位）；匯入規則 JSON 或規則結果檔 → 切到「條件規則」並交給 `RuleBuilder`（新 prop `imported`）；檔內有 `settings` 就覆蓋期間／資金／資料來源／種子並存 localStorage；匯入訊息列出幾筆、略過哪幾列與原因。`RuleBuilder.jsx` 跑完多「匯出（zip）」（結果檔 `input.rules` 就是那組規則）。
4. **tests** `Screen/tests/simio.test.mjs`（8 項，`node --test`，不用瀏覽器、不用伺服器）：六列範本全讀；壞列七種原因各自對、無標題列照位置讀、引號欄位、日期排序、`normDate` 三種寫法；規則 JSON 物件／陣列／三種壞法；`parseImport` 分流與結果檔（程式產生的範本）還原；指令模式結果 JSON（`ref`、`signal_date` 用指令日、`input` 從 `parsed` 還原帶 `note`、`skipped` 有／`triggers` null）並匯回去一字不差；規則模式（`ref`「規則 #N」、`triggers` 有／`skipped` null、`input.rules` 原樣）；四個檔的檔名、BOM、CRLF、欄位、metrics 列、四點序列不補零；zip 四個條目名稱／大小／CRC 對得上、CRC-32 標準向量 `0xCBF43926`、中文檔名；同一個 zip 寫到暫存區給 PowerShell `Expand-Archive` 解（`simio-zip-87`）。

## 二、結果

| 檢查（`AI/progress/checks.json`） | 結果 | 說明 |
|---|---|---|
| `simio-test-87` | 8 過 | `node --test tests/simio.test.mjs`（審查後重跑） |
| `simio-zip-87` | 過 | PowerShell `Expand-Archive` 解出 4 個檔（result 2,961 B、trades 226 B、series 147 B、metrics 485 B；tests 的 zip 不帶 `note`，所以 result 比範本的 3,006 B 小）、trades CSV 前三個 byte 是 BOM、結果 JSON `format` 對 |
| `templates-gen-87` | 過 | 程式產生四個匯出範本（3,006／226／147／485 B） |
| `fe-sync-87` | 過 | `TradingSim.jsx`、`RuleBuilder.jsx`、`lib/simIO.js` 兩個前端逐 byte 相同（node 比對：26,523／25,228／16,656 bytes） |
| `vite-build-87` | 過 | `Screen` 建置（審查後重跑） |
| `mfe-build-87` | 過 | `meeting_front_end` CRA 建置（審查後重跑） |
| `mfe-eslint-87` | 過 | `RuleBuilder.jsx`、`TradingSim.jsx`、`lib/simIO.js` `--max-warnings 0`（審查後重跑） |
| `smoke-tradingsim-87` | 過 | `node smoke.mjs TradingSim`：jsdom 掛載成功（DOM 8,242 字元；`doExport` 改一行後沒重跑） |
| `browser-import-87` | 過（手動） | 下面瀏覽器實測的紀錄；repo 沒有截圖，只有這條 summary |

瀏覽器實測（2026-10-19，`meeting_front_end` 開發伺服器以 `PORT=3005 npm start` 啟動——PORT 是當場給的環境變數，repo 裡沒有設定；頁面 `/stock/analysis/simulate` 是 `StockApp.jsx` 的 `/stock/<mode>/<key>` 路徑規則套上 `nav.js` 分析模式（`analysis`）「預測」群組的 `simulate` 項；Chrome；**無截圖、只記在 `checks.json` `browser-import-87`**）：頁面載入無 console 錯誤、工具列有「匯入」；上傳 `sim_instructions.csv` → 自動切到「日期指令（表單）」、清單 6 筆（2024-01-15 買 2330 10 股…2024-07-01 賣 0050 全部）、訊息「已匯入 6 筆指令」；上傳 `sim_rules.json` → 切到「條件規則」、三條規則齊（2330 向上穿過 20 日均線買 100000 元／跌破 或 比成本低 10% 賣全部／0050 每月 5 日買 20000 元）、訊息「已匯入 3 條規則，期間／資金／資料來源已依檔案設定」。按「跑模擬」回 `Failed to fetch`：本機沒有行事曆後端（shim 指向 `localhost:5000` 的 meeting_API_Server），與本輪無關；「匯出（zip）」按鈕只在有結果時出現，所以**匯出與跑完後的畫面沒在瀏覽器驗到**，以單元測試（結果 JSON、四個檔、zip 解壓）與 Screen 的 jsdom 冒煙為準；push 上線後可在 erucmoney.com 再驗。

pytest／jest 沒跑：後端與 Node 沒改（本輪的 `git status` 只有前端兩個 repo 的檔案與文件）。`checks.json` 裡的 `pytest-87`、`live-list-87` 是並行的另一個 session（紙上交易清單缺陷，它的紀錄是 `Iteration-88.md`）記的，不是本輪；號碼協調見 `progress.md` 任務段。

## 三、讀法

- 匯入不是新的資料入口：檔案只變成頁面上的列或規則，按「跑模擬」仍走原本的端點與上限（200 筆、50 條、8 年）；所以後端不用改、也沒有上傳風險。
- 結果 JSON 是「可重跑的存檔」：匯回去會還原輸入與設定（期間、資金、來源、種子），再按一次跑模擬就得到同一份結果（真實行情資料若更新會不同）。三個 CSV 是給 Excel 的，數字和 JSON 同一份。
- zip 用 STORE 不壓縮：四個檔加起來幾 KB 到幾十 KB（series 最多 400 點、trades 最多 200 筆、triggers 最多 400 筆），壓縮沒意義；省掉在兩個前端各加一個套件。
- 沒做：拖放匯入、匯出前選檔、歷史回放分頁的匯出、把 zip 存到伺服器。

## 變更檔案

修改：`Screen/src/pages/TradingSim.jsx`、`Screen/src/components/RuleBuilder.jsx`、`AI/Doc/README.md`、`progress.md`
統一前端：`../meeting_front_end/src/stock/{pages/TradingSim.jsx, components/RuleBuilder.jsx}`（逐 byte 相同）、`lib/simIO.js`（新，同一份）
新增：`Screen/src/lib/simIO.js`、`Screen/tests/simio.test.mjs`（8 項）、`Screen/tests/fixtures/sim_sample.mjs`、`AI/experiments/iter87_templates.mjs`、`AI/UserDoc/TradingSimIO.md`、`AI/UserDoc/sim_templates/`（6 檔）、`AI/Doc/Iterations/Iteration-87.md`
資料表：無
審查：evidence-reviewer 第一輪 55／8／7 FAIL（incorrect：範本「六個都被 tests 讀」與匯出範本手寫補零、「不碰 DOM」、note 對回在表單有空列時錯位、「四個 CSV」、規格文件四處與實作不符——匯出範本改程式產生、`doExport` 先 `rowOk` 過濾、規格與措辭都改；unresolved：兩前端 diff 與瀏覽器實測沒證據——補 `fe-sync-87`、`browser-import-87`，統一前端部署見 `../meeting_front_end/.github/workflows/pages.yml` 與 `public/CNAME`）；第二輪 36／2／4 FAIL（incorrect：`simulate` 在 `nav.js` 的「預測」群組不是「分析」群組、`progress.md` 產出與已完成清單沒跟上——已改；unresolved：使用者原話、瀏覽器實測與 `PORT=3005` 只有本 session 的 summary、統一前端部署耗時沒量過——repo 內補不了，附在報告交回使用者）
驗證：`checks.json` `simio-test-87`、`simio-zip-87`、`templates-gen-87`、`fe-sync-87`、`vite-build-87`、`mfe-build-87`、`mfe-eslint-87`、`smoke-tradingsim-87`、`browser-import-87`（都過）；pytest／jest 沒跑（後端未動）
重啟：不用（純前端）；`Screen` push 後 GitHub Pages 約 3 分鐘（CLAUDE.md）；`meeting_front_end` 的 workflow（`.github/workflows/pages.yml`，push `main` → `npm ci` → `test:unit` → build → deploy-pages，`public/CNAME` = erucmoney.com）耗時沒量過
