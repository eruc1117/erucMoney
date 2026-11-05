# Iteration 89 — 每個頁簽都有使用說明模式：頂欄一顆「使用說明」開關，開著時每頁上方顯示那一頁的「做什麼／怎麼用／怎麼看／注意」，換頁簽跟著換；兩個前端 27 個頁簽共用一份內容，純前端不用重啟

**日期：** 2026-11-05
**依據：** 使用者：「每一個頁簽都加上該頁簽的使用說明模式」
**規則：** 純前端（Screen 與統一前端 `meeting_front_end/src/stock` 各一份，元件與內容逐 byte 相同）；後端 FastAPI／Node 一行未動、不用重啟；不寫任何資料表、`portfolio_runs` 的 N 不動、保留期未開；各頁面檔（`pages/*.jsx`）一行未動；說明以「畫面上看得到、按得到的東西」為準（第一輪審查抓到 8 條不符，已改，見「審查」）；不加 npm 套件。

## 一、做了什麼

1. **做成「模式」而不是每頁一個問號**：開關是一個全域狀態（`useHelpMode`，存 localStorage `ui.help`，`'1'` 開、其他關，預設關）。開著的時候每個頁簽的內容區最上方多一張「使用說明：<頁簽標題>」卡，換頁簽就換成那一頁的；按頂欄開關或卡片上的「關閉說明」關掉，重新整理後記得上次的狀態。
2. **`Screen/src/components/PageHelp.jsx`**（新，59 行；`meeting_front_end/src/stock/components/PageHelp.jsx` 同一份）：`useHelpMode()`、`HelpToggle`（頂欄開關，`aria-pressed`、`aria-label="使用說明模式"`）、`PageHelp`（面板：一句用途＋「怎麼用」編號清單＋「怎麼看」「注意」兩個清單；找不到那個 key 的說明時顯示「這個頁簽還沒有使用說明。」）。
3. **`Screen/src/lib/helpContent.js`**（新，578 行；`meeting_front_end/src/stock/lib/helpContent.js` 同一份）：`HELP` 依頁簽 key 放 27 份說明，共 285 條（步驟／怎麼看／注意），最長一條 113 字。27 ＝ Screen 側欄 22 個頁簽 ∪ 統一前端 `nav.js` 26 個頁簽（分析 19＋管理 7）；只在 Screen 的是 `account`，只在統一前端的是管理模式的 `crawler`、`data`、`users`、`local`、`health`。
4. **接線**
   - Screen：`App.jsx` 持有狀態，傳給 `Topbar`（開關放在字級切換左邊），並在 `<main className="content">` 的第一個位置渲染 `<PageHelp>`。
   - 統一前端：`StockApp.jsx` 的標題列（`.stock-page-head`）加開關、標題列下方渲染面板；`stock-overrides.css` 讓標題列的說明文字吃掉中間、靠右，開關才不會被 `space-between` 擠到中央。
5. **樣式**：`Screen/src/index.css` 加「使用說明模式」一段（面板左邊一條藍線、`auto-fit` 多欄），統一前端的 `stock.css` 用原本的 `scripts/prefix-stock-css.js` 從 `index.css` 重新產生（`git diff --numstat`：`stock.css` +14／−0、`stock-overrides.css` +3／−0，`mfe-css-diff-89`）。
6. **頂欄不能因此更擠**：第一次截圖發現標題最長的頁簽（正式策略、交易模擬）頂欄的按鈕文字被折成兩行。改三處：`.ui-toggle button` 加 `white-space: nowrap`；視窗 1900px 以下開關只顯示「？」；同樣 1900px 以下 `.topbar-right` 的間距由 1rem 收成 .6rem。門檻原本訂 1500px，第一輪審查指出測試裡「原本」的選擇器（`:first-of-type`）其實沒把開關藏起來；改成用開關的 `aria-label` 選、確認藏起後重量，量到 1600px 寬的交易模擬標題比原本多折一行，才把門檻調到 1900px。結果見第二節的頂欄表。
7. **說明內容怎麼來的**：22 個 Screen 頁面檔（共 9,476 行，不含 `Login.jsx`）由四個唯讀 subagent 整檔讀完、回報每頁的控制項原文、顯示、資料來源與警語（附行號；`AI/progress/events.jsonl` 2026-11-05 12:47 起有四筆 general-purpose 的 `SubagentHandback`／`SubagentStop`，回報全文只在 session 裡、沒有另存）；管理模式五頁（478 行）主 session 自己讀。主 session 據此寫 `helpContent.js`，引用的三段原文（趨勢預測的市場備註、預測比對的兩個說明框）另外直接讀檔核對過。**主 session 沒有自己逐頁重讀那 22 個頁面檔**——內容的正確性靠 subagent 的回報與本輪的審查（審查逐條對過約 260 條，錯 8 條；其餘沒抽到的 17 條主 session 補對過）。兩個前端共用的頁面與元件 30 檔（pages 21＋components 9）逐 byte 相同（`fe-sync-89`），所以一份說明兩邊都適用。

## 二、結果

驗證（`AI/progress/checks.json`，2026-11-05；審查後重跑過，以下是最後一次的結果）：

| 檢查 | 結果 | 內容 |
|---|---|---|
| `help-test-89` | 過 | `node --test tests/help.test.mjs` 4 項：Screen 側欄 22 個 key 與 `PAGE_TITLES` 一致且都有說明；統一前端 `nav.js` 26 個 key 都有說明；沒有對不到頁簽的孤兒說明；每份四段齊全（用途 ≥ 15 字、步驟 ≥ 2、怎麼看 ≥ 1、注意 ≥ 1、單條 ≤ 160 字、沒有多餘欄位） |
| `help-smoke-89` | 過 | `node tests/help-smoke.mjs` 14 項（jsdom 掛真正的 `App`、fetch 換成永不回應）：預設關；按開關出現面板、`ui.help='1'`、按鈕 `active`；逐一點側欄 22 個頁簽，22 個都顯示自己的用途句、第一個步驟、三段、標題，且面板是 `.content` 第一個子元素；「關閉說明」後消失、`ui.help='0'`、換頁簽不再出現；`ui.help='1'` 重新掛載直接開著；render 錯誤 0 |
| `help-ui-89` | 過 | `node tests/help-ui.mjs` 15 項（Playwright，chromium 156.0.8078.80，對 `npm run dev` 的 :5173，後端請求一律回 503）：深色、淺色各 22 個頁簽面板高度 303～527px、沒被裁、在內容區最上方、無橫向溢出、頁面錯誤 0；按頂欄開關後面板消失；1100px 寬排 2 欄、480px 寬排 1 欄；頂欄七種寬度見下表 |
| `fe-sync-89` | 過 | `node AI/experiments/iter89_fesync.mjs`：`PageHelp.jsx` 2,436 bytes、`helpContent.js` 41,417 bytes 兩邊逐 byte 相同；`stock.css` 與重新產生的那份相同（換行統一成 LF 後比）；兩個前端共用的頁面與元件 30 檔逐 byte 相同 |
| `vite-build-89` | 過 | `Screen` `npm run build` |
| `mfe-eslint-89` | 過 | 統一前端 `npx eslint --max-warnings 0` 四個檔（`StockApp.jsx`、`StockApp.test.jsx`、`PageHelp.jsx`、`helpContent.js`） |
| `mfe-test-89` | 過 | 統一前端 `StockApp.test.jsx` 8 項（原 7 項＋新 1 項：預設關、按開關出現市場總覽的說明、換到個股分析跟著換、關掉後 `ui.help='0'`） |
| `mfe-build-89` | 過 | 統一前端 `npm run build`（CRA） |
| `mfe-shot-89` | 過 | `node AI/experiments/iter89_mfe_shot.mjs`：把統一前端的 `build/` 開起來，標題列三塊由左到右是標題（244–330px）、說明文字（346–1466px）、開關（1482–1576px）；預設沒有面板；開啟後個股分析／交易模擬／我的持股／新聞訊號／查詢紀錄的面板高 456／531／406／357／331px、沒被裁、清單字級 13.76px、小標 12.48px、頁面錯誤 0 |
| `mfe-css-diff-89` | 過 | 統一前端 `git diff --numstat`：`stock.css` +14／−0、`stock-overrides.css` +3／−0 |

沒跑：Server 的 jest、Crawler 的 pytest（後端沒改）；`smoke.mjs` 全頁掛載（頁面檔沒改）；統一前端的其他測試檔與 e2e（只動了殼層與新檔）。

頂欄對照（`help-ui-89`，三頁依序是市場總覽／正式策略／交易模擬；「原本」＝同一頁把說明開關藏起來（測試確認已藏起）並還原本輪加的兩條頂欄樣式；登入者顯示名用「版面檢查」四個字）：

| 視窗寬 | 標題高（現在） | 標題高（原本） | 按鈕高（現在） | 按鈕高（原本） | 說明鈕 |
|---|---|---|---|---|---|
| 1920px | 34／34／34 | 34／34／34 | 22／22／22 | 22／22／22 | ？ 使用說明 |
| 1901px | 34／34／34 | 34／34／34 | 22／22／22 | 22／22／22 | ？ 使用說明 |
| 1900px | 34／34／34 | 34／34／34 | 22／22／22 | 22／22／22 | ？ |
| 1750px | 34／34／34 | 34／34／34 | 22／22／22 | 22／22／22 | ？ |
| 1600px | 34／68／34 | 34／68／34 | 22／22／22 | 22／35／22 | ？ |
| 1440px | 34／68／68 | 34／68／68 | 22／22／22 | 22／47／35 | ？ |
| 1366px | 34／68／68 | 34／68／68 | 22／22／22 | 22／47／47 | ？ |

（單位 px；標題一行 34、兩行 68；按鈕一行 22。）

截圖：兩個前端各看過（Screen 深色個股分析、淺色交易模擬；統一前端市場總覽），存在本 session 的暫存目錄，**沒有進 repo**（`Screen/.ui-shots/` 本來就在 `.gitignore`）。

## 三、讀法

- 「每一個頁簽」在這裡是 27 個：兩個前端導覽上的每一個 key。以後加頁簽忘了寫說明，`help-test-89` 那支測試會指名是哪一個 key；刪了頁簽沒刪說明也會擋。
- 說明是**手寫的靜態文字**，不是從頁面產生的：頁面改了按鈕名稱或行為，`helpContent.js` 不會自己跟著變，測試也驗不出內容對不對（只驗有沒有、格式）。檔頭註解寫了這條規矩。這一輪第一版就有 8 條寫錯（例：趨勢預測的圖其實只畫預測線，95% 上下界在表格；持股「建議對照」的徽章文字是後端給的「與建議一致／與建議相反／建議觀望」），是審查對頁面碼才抓到的。
- 頁面上寫死的舊數字照頁面原文寫進說明，並註明是寫死的（例：美股跳空頁的「走查方向準確率 61.32%」是 Iteration 32 的數字，不隨資料更新）。
- 頂欄：七種寬度下，三個頁簽的標題高度都和加開關之前相同，按鈕不再折行（原本 1600px 以下會折成 35～47px）。標題長的頁簽本來就會折兩行（正式策略在 1600px 以下；交易模擬在 1600px 還是一行，1440px 以下才折），這一輪沒有修這件事。代價是視窗 1900px 以下開關只剩一個「？」（滑鼠停留有提示），整顆「？ 使用說明」只在更寬的視窗出現。只量了這七種寬度、三個頁簽、一個四個字的顯示名；顯示名更長時沒量。
- 沒驗到的：統一前端管理模式五頁的面板只有單元測試涵蓋到 key 與內容存在（`help-test-89`），沒有在瀏覽器裡以 admin 身分實際點過；兩個正式網域（`stock.erucmoney.com`、`erucmoney.com`）要 push 之後才看得到。
- 面板在 1600px 寬時高 303～527px，開著會把頁面內容往下推半個畫面左右——這是「模式」的代價，看熟了關掉。

## 審查

evidence-reviewer 第一輪 52 verified／9 incorrect／4 unresolved，FAIL（`evidence-reviewer-89-r1`）。處理：

- incorrect（說明內容 7 列 8 條，都對照頁面碼確認後改）：`stock` 拖曳條只有五張圖有；`prediction` 的圖沒畫 95% 區間（`what` 與「怎麼看」第一條）；`compare` 的 FinMind 額度只適用台股補資料；`weekly`「立即補跑」的時機是 LSTM 服務沒開的橘色警示；`portfolio` 只有三欄標「通過／未過」、DSR 用顏色；`holdings` 一致性徽章的文字；`history` 結果徽章的顏色規則。
- incorrect（頂欄 2 列）：測試裡「原本」的選擇器沒選到開關 → 改選擇器、測試多驗「開關已藏起」、重量後發現 1600px 的退步、門檻 1500px → 1900px、表格與讀法依新數字重寫。
- unresolved：`stock.css` 的 diff 行數 → 補 `mfe-css-diff-89`；subagent 讀檔沒有紀錄 → 指到 `events.jsonl` 的四筆事件（回報全文仍沒有另存，**待確認**的只剩這一點）；21 個頁面檔逐 byte 相同沒有檢查 → 併進 `fe-sync-89`（30 檔）；六個頁簽沒抽到的 17 條 → 主 session 對 `NewsInput.jsx`、`NewsSignals.jsx`、`InstitutionalHoldings.jsx`、`IdleCash.jsx`、`NewsSentiment.jsx`、`WorkProgress.jsx`、`Shares.jsx` 逐條讀過，都成立。

第二輪 24 verified／2 incorrect／0 unresolved，FAIL（`evidence-reviewer-89-r2`）：第一輪的 13 條都確認處理掉，剩同一句措辭在本檔與 `progress.md` 各一處（「標題長的頁簽在 1600px 以下本來就折兩行」——交易模擬在 1600px 原本是一行），已照頂欄表改寫；另採納一條不擋的建議：`prediction`「怎麼看」第一條加上「個別模式」（95% 上下界兩欄只在個別模式的表格），`helpContent.js` 因此是 41,417 bytes，受影響的檢查重跑過。

第三輪 9 verified／0 incorrect／0 unresolved，PASS（`evidence-reviewer-89-r3`）。

## 變更檔案

修改：`Screen/src/App.jsx`、`Screen/src/components/Topbar.jsx`、`Screen/src/index.css`；`AI/Doc/README.md`、`progress.md`
新增：`Screen/src/components/PageHelp.jsx`、`Screen/src/lib/helpContent.js`、`Screen/tests/help.test.mjs`、`Screen/tests/help-smoke.mjs`、`Screen/tests/help-ui.mjs`、`AI/experiments/iter89_fesync.mjs`、`AI/experiments/iter89_mfe_shot.mjs`、`AI/Doc/Iterations/Iteration-89.md`
統一前端（另一個 repo `../meeting_front_end`，未提交）：修改 `src/stock/StockApp.jsx`、`src/stock/StockApp.test.jsx`、`src/stock/stock-overrides.css`、`src/stock/stock.css`（腳本產生）；新增 `src/stock/components/PageHelp.jsx`、`src/stock/lib/helpContent.js`

重啟：不用（純前端）。`Screen` push 後 GitHub Pages 約 3 分鐘自動部署（CLAUDE.md）；統一前端要另外在 `meeting_front_end` commit／push。
