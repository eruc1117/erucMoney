# Iteration 41 — 多使用者階段 1：users 表、JWT、持股按人隔離（本機）

**日期：** 2026-09-25

## 起點

使用者要「持股部分加上區分不同使用者功能，並且將前端獨立出來可以單獨部署到 GitHub Pages，透過 RESTful API 連本機後端」。
架構提案在 `AI/Doc/Architecture-MultiUser.diagram.html`（五個階段）。本迭代是階段 1：先在本機把帳號、登入、
持股隔離做出來，前端獨立部署（階段 2～4）之後再做。

## 做了什麼

### 後端（Server/）

| 檔案 | 內容 |
|------|------|
| `migrations/017_users.sql` | `users`（username、bcrypt 雜湊、role admin/user、is_active、last_login_at）；`user_holdings`／`user_trades` 加 `user_id NOT NULL DEFAULT 1`、`user_news` 加可空 `user_id`；`user_holdings` 唯一鍵 `(stock_id)` → `(user_id, stock_id)`；既有資料全部歸 admin（id 1） |
| `lib/auth.js` | `signToken`（JWT 7 天，sub = user id）、`requireAuth`（Bearer → `req.user`，401）、`requireRole('admin')`（403）。密鑰：環境變數 `JWT_SECRET`，沒有就產生 `Server/.jwt_secret`（已 gitignore），重啟不會登出所有人 |
| `routes/auth.js` | `POST /auth/login`（每分鐘 10 次）、`GET /auth/me`、`POST /auth/change-password`；admin：`GET/POST /auth/users`、`PUT /auth/users/:id`（角色、顯示名、停用、重設密碼）、`DELETE /auth/users/:id`（持股與交易 CASCADE）。不開放自助註冊 |
| `index.js` | `/health` 與 `/auth` 公開，其餘全部 `requireAuth`；`/crawler`、`/models`、`/data` 要 admin；CORS 白名單 `ALLOWED_ORIGINS`（沒設就全開）；啟動時 `ensureAdmin()` 用 `ADMIN_PASSWORD`（預設 admin123，會警告）補 admin 雜湊 |
| `routes/holdings.js` | 16 處 SQL 全部加 `user_id = req.user.id`：持股、台帳、建議 vs 實際、新增／修改／刪除 |
| `lib/tradeLedger.js` | `rebuild(db, stockId, userId)`：回放只看該使用者的交易、只寫該使用者的持股列 |
| `routes/cash.js` | 把 `user_id` 傳給 FastAPI `/cash/plan`（排除已持有時只看登入者） |
| `routes/news.js` | 手動貼的新聞記 `user_id` |
| 新依賴 | `jsonwebtoken`、`bcryptjs`、`express-rate-limit` |

### Crawler/（FastAPI）

`roles.load_holdings(user_id=1)`、`cash_allocator.allocate(..., user_id)`、`api.py /cash/plan?user_id=`。
**排程投票（20:00）沒有登入者，「持倉管家」角色用 admin 的持股**——voting_results 是全站共用的一份，
之後若要每人一份要改成請求時算，這是階段 1 明確留下的限制。

### 前端（Screen/）

| 檔案 | 內容 |
|------|------|
| `services/auth.js` | token 與使用者存 localStorage；登入／登出廣播給 App |
| `services/api.js` | 每次請求自動帶 `Authorization: Bearer`；401 自動登出；API 位址 `getApiBase()/setApiBase()`：localStorage → `VITE_API_URL` → localhost（階段 2 前端獨立部署要用） |
| `pages/Login.jsx` | 登入頁；可展開改後端位址並測試 `/health` |
| `pages/Account.jsx` | 改密碼；admin 的使用者管理（建帳號、改角色、停用、重設密碼、刪除） |
| `App.jsx`、`Sidebar`、`Topbar` | 沒登入只顯示登入頁；側欄「帳號」；頂欄顯示使用者、點了到帳號頁 |

## 驗證（2026-09-25 02:32，本機）

```
GET  /health                         → 200
GET  /holdings（無 token）           → 401
POST /auth/login admin/admin123      → token
GET  /holdings（admin）              → 3 檔、9 筆交易（既有資料）
POST /auth/users test2               → 201
GET  /holdings（test2）              → 0 檔
POST /holdings/trades（test2 買 2330 1000 股） → 回放後 test2 1 檔；admin 仍 3 檔 9 筆
GET  /auth/users、/models（test2）   → 403
DELETE /auth/users/2                 → test2 的持股與交易一起消失
```

前端 `vite build` 通過。

## 使用方式

1. 啟動 Node（`cd Server && npm run dev`）：migration 017 自動套用、admin 密碼為 `admin123`（或設環境變數 `ADMIN_PASSWORD`）。
2. 前端登入 admin → 側欄「帳號」→ 改密碼 → 建其他帳號。
3. 每個帳號登入後看到的持股、交易台帳、建議 vs 實際、閒置資金排除持股，都是自己的。

## 留給階段 2～5

- 前端：`base: '/money/'`、HashRouter（目前是 state 切頁，沒有 router，不受影響）、GitHub Actions 部署。
- 隧道：cloudflared、`ALLOWED_ORIGINS` 設成 github.io 網域、`JWT_SECRET` 與 `ADMIN_PASSWORD` 放 `Server/.env`（已 gitignore，index.js 目前沒有讀 .env，要加 dotenv 或在服務啟動腳本設環境變數）。
- 投票的持倉角色改成按請求者算；`weekly_plan`、`ledger_audit` 若要按人跑要加 `user_id` 參數。
