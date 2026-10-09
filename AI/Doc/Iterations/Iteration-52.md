# Iteration 52 — 月調倉頁的「現在該買哪些」＋分析頁免登入

**日期：** 2026-10-09
**依據：** 使用者：「候選對門檻，是買那些股票」「除了和個人相關的頁面，其他預測不用登入也可以看到」。

## 一、做了什麼

### 現在該買哪些：`portfolio_live_list`（migration 023）、`portfolio_backtest.py --current-list 44`

頁上原本的「最後一次持股」是 2024-09 回測期末的名單。現在用候選（#44）的參數從 2018 一路算到最近一個訊號日，
只取最後一次調倉的目標持股寫進 `portfolio_live_list`（分批輪動有路徑依賴，所以要從頭算；**保留期的淨值與指標不算、不存、不印**）。
`/portfolio/candidate` 多回 `current_list`，頁首「現在該買哪些」用磁磚列出：訊號日 2026-09-11、成交日 2026-09-14、21 檔——
台積電固定 59.7%（0050 權重估計），20 檔各 2.0%；★ 是這個月新進場的一批；rank 空的是上幾批進場、本月未進排名但還沒到期的續抱。
階段 4 的每月排程之後也寫這張表。

### 分析頁免登入（三個 repo）

| 層 | 改法 |
|---|---|
| erucMoney `Server/lib/auth.js`、`app.js` | `optionalAuth` 掛最外層（有 token 就驗、壞的仍 401；沒有就匿名）。路由分三種：**公開讀取** `readPublic`（stocks、news、model、predictions、voting、gap、catalog、us、forecast、portfolio：GET 免登入，POST／PUT／DELETE 要登入）、**個人** `requireUser`（holdings、cash）、**管理** `requireUser + requireRole('admin')`（crawler、models、data） |
| meeting_API_Server | `/api/stock` 改掛 `optionalAuthMiddleware`；`StockService` 匿名只能 GET 非個人前綴（holdings、cash、auth、crawler、models、data 以外），否則 401；匿名轉發不帶 Authorization |
| meeting_front_end | `/stock` 離開 PROTECTED_ROUTES；StockApp 沒 token 不叫 `/auth/me`，資產群組（持股、閒置資金）標 🔒、點進去顯示「登入後才看得到」；`api.js` 匿名收到 401 不再清登入、不跳登入頁 |

測試：erucMoney `public-read.test.js` 新增（匿名可讀七個端點、匿名 POST 401、`/holdings` 401、壞 token 401、管理端點匿名 401／一般 403），
原本「沒 token → 401」的六處改成「不是 401」；全套 151 項（`npm test`，runInBand——平行跑會互相寫壞測試庫）。
meeting_API_Server 229 項（`stock-proxy` 與 `StockService` 的匿名案例改寫）。

## 二、要注意

- 新聞列表（`GET /news`）跟著公開：新聞本來就是共享的，只有 `user_id` 記錄誰貼的；修改／刪除仍要登入且只能動自己的。
- 「查詢紀錄」存在瀏覽器本機，匿名也看得到自己的。
- Node（:3001）、行事曆 API（:5000）要重啟；前端由 GitHub Pages 自動部署。

## 變更檔案

money：`Server/migrations/023_portfolio_live_list.sql`、`Server/lib/auth.js`、`Server/app.js`、`Server/tests/http/public-read.test.js`、六個 http 測試、`Crawler/portfolio_backtest.py`、`Crawler/portfolio_api.py`、
`Screen/src/pages/PortfolioLab.jsx`、`Crawler/tests/helpers/db_setup.py`、`Server/tests/db/migrations.test.js`。
meeting_API_Server：`middlewares/optionalAuthMiddleware.js`、`routes/index.js`、`services/StockService.js`、兩個測試。
meeting_front_end：`src/router/index.tsx`、`src/stock/{StockApp.jsx,nav.js,services/api.js,pages/PortfolioLab.jsx}`。
