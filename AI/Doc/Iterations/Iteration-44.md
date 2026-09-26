# Iteration 44 — 股票功能全部併進行事曆平台（方案 9：分析／管理雙模式）

**日期：** 2026-09-26

## 起點

Iteration 43 把股票「入口」加進行事曆平台，完整功能仍要另開 `stock.erucmoney.com`。使用者看過 10 套設計方案後
選了**方案 9**：股票儀表板的所有功能都在統一前端裡做，沒有任何外連；一般使用者只有「分析」模式，
股票系統的 admin 多一個「管理」模式（橘色系，提醒自己在動系統）。

## 設計

```
meeting_front_end /stock/:mode/:page                meeting_API_Server                    erucMoney Node API :3001
  分析：行情 / 預測 / 資產 / 新聞 / 其他   ──ANY /api/stock/<path>（Bearer 行事曆 JWT）──▶  代理：方法、query、body 原樣轉  ──▶  requireAuth / requireRole('admin')
  管理：資料 / 模型 / 帳號 / 服務（admin）                                                   權限不重複判斷                          SSO_ADMIN_USERNAMES → 升 admin
```

- **搬頁面不改頁面**：erucMoney `Screen/src/pages/*.jsx`、`components/*.jsx`、`theme.jsx`、`services/{history,holding}.js`
  原樣複製到 `meeting_front_end/src/stock/`。差別只在兩個 shim：
  - `services/api.js`：位址固定 `${REACT_APP_BASEURL}/api/stock`、token 是行事曆的登入 token、把代理的 `{ data }` /
    `{ message, upstream }` 拆回頁面熟悉的 `{ data, notFound, error }`。介面（函式名）完全相同。
  - `services/auth.js`：使用者 = 行事曆的 `user` + 股票系統 `/auth/me` 的 `{ id, role }`（存 `stock_user`）；401 清掉登入回 `/login`。
- **樣式隔離**：`scripts/prefix-stock-css.js` 把 erucMoney 的 `index.css` 每條規則加上 `.stock-app` 前綴
  （`:root`／`html[data-theme]`／`body` → `.stock-app`，`html[data-size]`、`html, body` 這類全頁規則丟掉）產生 `stock.css`；
  `stock-overrides.css` 換成平台色票（黑底、紫色主色；管理模式橘色）、還原平台的全域元素樣式（h1 56px、p 21px、input 100%）、殼層。
  `theme.jsx` 的 `cssColor()` 改從 `.stock-app` 讀 CSS 變數（ApexCharts 要實際色值）。
- **殼層 `StockApp.jsx`**：模式列（分析／管理；非 admin 停用管理鍵）、左側分組導覽（`nav.js`）、路由
  `/stock/:mode?/:page?`（`router/config.ts` 改成非 exact）、個股跳轉 `?stock=`；載入時打 `/auth/me` 取角色、`/health` 顯示在線。
- **管理模式的新頁**（erucMoney 原本散在各頁的 admin 動作集中）：`AdminCrawler`（個股／新聞爬蟲、週預測補跑、投票觸發＋狀態輪詢）、
  `AdminData`（每檔新鮮度、勾選回填、外生資料回填）、`AdminUsers`（原 Account 頁的使用者管理，標出行事曆來源、SSO 使用者不給重設密碼）、
  `AdminHealth`（Node／FastAPI／排程／新鮮度一覽）；`ModelVersions` 直接沿用。
- **代理放開**（meeting_API_Server）：`StockService.proxy({ method, path, query, token, body, timeoutMs })`，允許的第一段路徑
  `health stocks forecast catalog predictions voting holdings cash gap model models news crawler data us auth`，
  只擋 `/auth/login`、`/auth/change-password`；上游 4xx 原樣回狀態碼與 detail；長工作逾時 180 秒；`express.json` 上限 10kb → 256kb（新聞全文）。
- **整套平台只有一種 admin**（同日追加）：行事曆後端 `users` 表加 `role`／`is_active`（migration 1790500000000），
  JWT payload 改成 `{ id, username, role }`，新增 `/api/admin/users`（列出、改角色、停用、刪除；不能動自己）與 `adminMiddleware`；
  第一個 admin 由行事曆 `.env` 的 `ADMIN_ACCOUNTS` 在註冊／登入時升級。erucMoney `lib/auth.js` 改成信任行事曆 token 的 role，
  每次請求同步進自己的 `users.role`（升降級即時生效）；原本的 `SSO_ADMIN_USERNAMES` 移除。
  前端：`AuthContext` 存 role，管理模式多一頁「平台使用者」（`AdminPlatformUsers.jsx`，打 `/api/admin/users`），
  原「使用者」改名「股票本地帳號」。

## 檔案

| Repo | 檔案 |
|------|------|
| meeting_front_end | `src/stock/StockApp.jsx`、`nav.js`、`stock.css`（產生）、`stock-overrides.css`、`services/{api,auth}.js`、`pages/Admin{Crawler,Data,Users,Health}.jsx`、搬來的 15 頁與 4 個元件、`scripts/prefix-stock-css.js`、`pages/Stock/index.tsx`、`router/config.ts`、`router/index.tsx`、`public/index.html`（CSP 去掉 frame-src）、`.github/workflows/pages.yml`（去掉 `REACT_APP_STOCK_URL`）、`package.json`（+apexcharts、react-apexcharts）、README |
| meeting_front_end（刪） | `components/Stock/`、`contexts/StockContext.js`、`content/StockContent.json` |
| meeting_API_Server | `services/StockService.js`、`controllers/StockController.js`、`routes/stock/stock.js`、`app.js`、`tests/services/StockService.test.js`（53 項）、README、`docs/API.md` §4 |
| money | `Server/lib/auth.js`（信任行事曆 token 的 role 並同步）、`.env.example`、本文件、`Deploy/README.md` |
| meeting_API_Server（admin） | `migrations/1790500000000_add-users-role.js`、`models/User.js`、`services/AuthService.js`、`services/AdminService.js`、`controllers/AdminController.js`、`routes/admin/admin.js`、`middlewares/adminMiddleware.js`、`utils/httpStatusMapper.js`、tests（adminMiddleware 4、AdminService 10） |
| meeting_front_end（admin） | `contexts/AuthContext.js`、`stock/services/auth.js`、`stock/pages/AdminPlatformUsers.jsx`、`stock/nav.js` |

## 驗證（本機，2026-09-26）

以正式環境變數建置 meeting_front_end，`serve -s build` 在 :3000，行事曆 API 與股票 API 都是本機常駐工作（經公開網域打回來）。
註冊一個行事曆測試帳號登入後：

| 步驟 | 結果 |
|------|------|
| `/stock` | 市場總覽：26 檔、模式列「管理」停用（角色 user）、紫色主色 |
| `/stock/analysis/stock?stock=2330` | 個股分析：K 線、模型列、資料不足時自動觸發爬蟲（非 admin 會被上游 403，頁面靜默回 idle） |
| 加進 `SSO_ADMIN_USERNAMES` 重啟 MoneyApi 後重載 | 角色 admin、「管理」可用、橘色系；爬蟲與排程頁狀態輪詢正常（下次週預測 09-27 08:00） |
| 頁面內 `POST /api/stock/holdings/trades` → `GET` → `DELETE` | 200 → 台帳看得到自己那筆 → 200；持股只有自己的 |
| Jest `StockService` | 53/53 |
| `react-scripts build` | 通過（既有 ESLint 警告） |

測試帳號已從兩邊資料庫刪除。之後使用者要求「現有帳密清空」：兩邊 users 全刪（備份在 `E:\Desktop\coding\backups\accounts-wipe-2026-09-26\`）。

## 限制

- 行事曆 token 只有 1 小時；過期後股票頁的請求回 401，前端清掉登入回 `/login`。
- 「查詢紀錄」存在瀏覽器 localStorage，換裝置不同步（原本就是這樣）。
- 字級切換與淺色主題（erucMoney 頂欄的功能）沒有搬：統一前端只有深色，字級跟平台。
- `stock.erucmoney.com` 的獨立儀表板仍在（erucMoney repo），統一前端不再連過去；要收掉的話刪 Cloudflare 的 `stock` CNAME 與 GitHub Pages 設定即可。
