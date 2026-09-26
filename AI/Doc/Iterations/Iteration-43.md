# Iteration 43 — 併入行事曆平台：股票分頁、唯讀代理、單一登入

**日期：** 2026-09-26

## 起點

使用者的另一個專案「行事曆協作平台」（`E:\Desktop\coding\project`；Node.js 版程式在 GitHub 的
`meeting_front_end`、`meeting_API_Server`、`meeting_chat_server`，`project/` 目錄裡是後來的 .NET 重寫版）。
要求：**維持 Node.js 版本**；以行事曆前端為主，把股票的入口加成新分頁；後端用相同方式處理；合併後的前端推到
`meeting_front_end`；**登入系統用同一套**。

兩個 Node repo 已 clone 到 `E:\Desktop\coding\meeting_front_end`、`E:\Desktop\coding\meeting_API_Server`。

## 設計

```
行事曆前端 (React CRA :3000)                      行事曆後端 (Express :5000)              erucMoney (Express :3001)
  /stock 分頁 ──GET /api/stock/*（Bearer 自己的 JWT）──▶ StockService 白名單轉發 ──Bearer 原樣──▶ requireAuth：
  「開啟完整儀表板」→ erucmoney.com/#token=<JWT>                                              同一把密鑰驗證
                                                                                              payload {id, username}
                                                                                              → users.external_id 對應
                                                                                                （第一次自動建立）
```

- **單一身份來源是行事曆**：`meeting_API_Server` 的 JWT payload 加上 `username`（原本只有 `id`）。
- **股票 API 用同一把密鑰**：`JWT_SECRET` = 行事曆的 `SECRET`。`lib/auth.js` 接受兩種 token：本地的 `{sub, role, name}`
  與行事曆的 `{id, username}`；後者以 `users.external_id`（migration 018）對應到本系統使用者，沒有就建立
  （`password_hash` 空＝不能用本地密碼登入），持股／交易照 user_id 隔離。
- **erucMoney 的 `/auth/login` 先問行事曆**：`AUTH_API_URL` 有設就把帳密送去 `POST /api/auth/login`，成功回它簽的 token
  （`sso: 'calendar'`）；行事曆說帳號不存在或密碼錯才退回本地帳號（admin）。所以 erucmoney.com 的登入頁也用行事曆帳號。
- **免二次登入的交接**：行事曆前端開啟儀表板時把自己的 JWT 放在網址片段 `#token=…`；erucMoney 前端載入時
  `takeTokenFromHash()` 取出、清掉網址、存成 session，再用 `/auth/me` 驗證。片段不會送到伺服器。
- **行事曆後端的代理只轉 GET 白名單**：行情、產業、週預測、目錄、健康檢查、使用者自己的持股／台帳／`auth/me`。
  帳號管理、爬蟲、模型管理不轉（那些在 erucMoney 用 admin）。

## 檔案

| Repo | 檔案 | 內容 |
|------|------|------|
| meeting_front_end | `src/pages/Stock`、`components/Stock`、`contexts/StockContext.js`、`content/StockContent.json` | 股票分頁：追蹤股票表（收盤、漲跌、外資持股）、週預測表、狀態燈、重新整理、另開／內嵌完整儀表板（帶 token） |
| meeting_front_end | `router/config.ts`、`router/index.tsx`、`components/Header` | `/stock` 受保護路由、導覽列「Stock」 |
| meeting_front_end | `README.md`、`.env`（本機） | 功能說明、`REACT_APP_STOCK_URL` |
| meeting_API_Server | `services/StockService.js`、`controllers/StockController.js`、`routes/stock/stock.js`、`routes/index.js` | `/api/stock/*` 唯讀代理（轉送使用者 token） |
| meeting_API_Server | `services/AuthService.js` | JWT payload 加 `username` |
| meeting_API_Server | `tests/services/StockService.test.js` | 32 項：白名單、無 token、轉送 Bearer、401／5xx 對應 |
| meeting_API_Server | `README.md`、`docs/API.md` | 端點、環境變數、錯誤碼、SSO 說明 |
| money | `Server/migrations/018_users_external.sql` | `users.external_id` |
| money | `Server/lib/auth.js` | 接受行事曆 token、自動建立對應使用者 |
| money | `Server/routes/auth.js` | 登入先問行事曆（`AUTH_API_URL`） |
| money | `Screen/src/services/auth.js`、`App.jsx` | `#token=` 交接 |
| money | `.env.example` | `JWT_SECRET` 要等於行事曆 `SECRET`、`AUTH_API_URL` |

## 驗證（本機，2026-09-26 00:24）

本機 PostgreSQL 有既有的 `Schedule` 資料庫，行事曆後端以 `.env`（DB、SECRET、`STOCK_API_URL=http://localhost:3001`）在 :5000 啟動；
erucMoney 的 `.env` 把 `JWT_SECRET` 改成同一把、加 `AUTH_API_URL=http://localhost:5000`，重啟 MoneyApi 套用 migration 018。

| 步驟 | 結果 |
|------|------|
| 行事曆註冊新帳號 | token payload `{id: 410, username: "ssotest…"}` |
| 行事曆 token → `/api/stock/stocks?tracked=true` | 200，26 檔 |
| 行事曆 token → `/api/stock/holdings` | 200，0 檔（erucMoney 自動建立 users id 6、external_id 410） |
| 行事曆 token 直接打 erucMoney `/auth/me` | 200，回對應使用者 |
| erucMoney `/auth/login` 用行事曆帳密 | 200，`sso: 'calendar'` |
| `/api/stock/auth/users` | 403（白名單外） |
| Jest `StockService` | 32/32；其餘套件 97 過、5 個既有失敗與本次無關（ScheduleService、validator、ipWhitelist） |
| `vite build`（erucMoney）、`react-scripts build`（行事曆） | 通過 |

測試帳號已從兩邊資料庫刪除。

## 網域改道（2026-09-26 00:10～）

使用者決定 `erucmoney.com` 改為統一前端（meeting_front_end），股票儀表板搬到 `stock.erucmoney.com`：

| 做了 | 狀態 |
|------|------|
| erucMoney `Screen/public/CNAME` → `stock.erucmoney.com`，push → Pages 重佈成功（自訂網域由 CNAME 檔切換） | 完成 |
| meeting_front_end：`public/CNAME` = `erucmoney.com`、`.github/workflows/pages.yml`（CRA build、`404.html` fallback、正式 API 位址）、鎖定檔同步 | 完成、已推 |
| 隧道 ingress 加 `calendar-api.erucmoney.com → :5000`、`route dns`、服務重啟 | 完成，公開 401（未登入）正確 |
| 行事曆 API 常駐 `MoneyCalendarApi`（`Deploy/install_calendar_api_task.ps1`；stdout 導到 `logs/task.out`，因為 pino 自己佔用 `logs/api.log`） | Running |
| `meeting_API_Server/.env`：`ALLOWED_ORIGINS` 加 `https://erucmoney.com`、`NODE_ENV=production`；money `.env`：`AUTH_API_URL=https://calendar-api.erucmoney.com`，MoneyApi 重啟 | 完成 |
| meeting_API_Server 的兩個 commit 推上 GitHub | 完成 |

## 部署要做的

1. `meeting_API_Server` 正式環境的 `.env`：`STOCK_API_URL=https://api.erucmoney.com`；`SECRET` 與 erucMoney `.env` 的 `JWT_SECRET` 相同。
   本機兩邊已經設成同一把（`E:\Desktop\coding\money\.env`、`E:\Desktop\coding\meeting_API_Server\.env`）。
2. erucMoney `.env` 的 `AUTH_API_URL` 指到行事曆後端的公開位址（目前是 `http://localhost:5000`，行事曆後端還沒對外）。
3. erucMoney 前端 push 後 GitHub Pages 自動重佈（交接功能要新版前端）。
4. `meeting_front_end` 的正式 `REACT_APP_BASEURL` 指到行事曆後端、`REACT_APP_STOCK_URL=https://erucmoney.com`。

## 限制

- 行事曆 token 只有 1 小時；交接到 erucMoney 後一小時要重新從行事曆開啟（或在 erucmoney.com 用行事曆帳密登入）。
- erucMoney 本地 admin 仍是本地帳號；行事曆帳號在 erucMoney 一律 `user` 角色，要給 admin 到 erucMoney「帳號」頁改角色。
- 行事曆後端在 `project/` 目錄裡是 .NET 版；本迭代改的是 GitHub 上的 Node.js 版（`meeting_API_Server`），沒有推送，只在本機 commit。

## 登入「伺服器錯誤，請稍後再試」（2026-09-26 修）

症狀：erucmoney.com 登入一律失敗；curl 打 `calendar-api.erucmoney.com/api/auth/login` 正常（含 CORS 標頭），但頁面內任何 `fetch` 都丟 `TypeError: Failed to fetch`。
原因：`meeting_front_end/public/index.html` 的 CSP `connect-src` 只放行 `localhost:5000/4000`，瀏覽器在網路層之前就擋掉跨網域請求，前端把它當成伺服器錯誤。
修法（meeting_front_end commit `91b48ec`）：`connect-src` 加 `%REACT_APP_BASEURL%`（CRA 建置時代換）與 `calendar-api`／`chat` 網域；`frame-src` 加 `%REACT_APP_STOCK_URL%`（股票分頁內嵌儀表板要用）。
驗證：本機以正式環境變數建置後，頁面內 `fetch` 登入 200、表單登入導向 `/schedule`；push 後 Pages 一分鐘內重佈，`erucmoney.com` 已送出新的 CSP。

待辦：`stock.erucmoney.com` 的 DNS CNAME 已加，但 GitHub 回 404 且憑證未簽——用 GitHub Actions 部署時 `public/CNAME` **不會**自動綁網域，
要到 `eruc1117/erucMoney` → Settings → Pages → Custom domain 填 `stock.erucmoney.com`，等 DNS check 過再勾 Enforce HTTPS。
