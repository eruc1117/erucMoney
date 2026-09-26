# Server — 股票 API（Node.js :3001）

`app.js` 是 Express 應用程式本體（路由、中介層、`init()` 跑 migration 與建表），`index.js` 只負責 `init()` 後 `listen(3001)`。
設定從 repo 根目錄的 `.env` 讀（見 `.env.example`）。

## 測試

| 層 | 目錄 | 需要 |
|----|------|------|
| 單元 | `tests/unit/` | 不碰資料庫（台帳回放、兩種 token 與角色同步） |
| http | `tests/http/` | 測試資料庫 `Stock_test`；FastAPI 用假伺服器（`tests/helpers/fastapi-mock.js`）、行事曆登入也用假伺服器 |
| migration | `tests/db/` | 會建又刪一個臨時庫 `Stock_migtest`（DB_USER 要有 CREATEDB；沒有就自動跳過） |

### 第一次

```powershell
# 1. 建測試資料庫（連線資訊用根目錄 .env 的 DB_*）
psql -U postgres -c 'CREATE DATABASE "Stock_test";'
#    或：cd Server && node -e "require('dotenv').config({path:'../.env'});const {Client}=require('pg');const e=process.env;new Client({host:e.DB_HOST,port:+e.DB_PORT,database:'postgres',user:e.DB_USER,password:e.DB_PASSWORD}).connect().then(async c=>{await c.query('CREATE DATABASE \"Stock_test\"');await c.end()})"

# 2. 裝相依（jest、supertest 已在 devDependencies）
cd Server && npm install
```

`Server/.env.test` 是測試專用設定（`DB_NAME=Stock_test`、測試密鑰、`ADMIN_PASSWORD`、`ALLOWED_ORIGINS`、`RATE_LIMIT_PER_MIN`）。
`tests/setup-env.js` 先讀根目錄 `.env`（拿 `DB_PASSWORD`），再用 `.env.test` 覆寫；**`DB_NAME` 不是 `_test` 結尾會直接拒跑**，所以永遠碰不到正式庫 `Stock`。
測試第一次跑會自己建基底表（`tests/helpers/bootstrap.sql`，對應 Crawler 建的四張表與 `app.init()` 建的三張）、跑 18 個 migration、seed 4 檔 30 個交易日的行情。

### 執行

```bash
npm test                # 全部（--runInBand：http 測試共用 Stock_test，不能平行）
npm run test:unit       # 只跑 tests/unit（秒級、不碰資料庫）
npm run test:coverage   # 加覆蓋率（只算 lib/、routes/、app.js）
```

### 功能對應

| 功能 | 檔案 |
|------|------|
| 台帳回放、費率 | `tests/unit/tradeLedger.test.js` |
| 本地／行事曆 token、角色同步、requireRole | `tests/unit/auth.test.js` |
| 登入、SSO、/me、改密碼、admin 使用者 CRUD | `tests/http/auth.test.js` |
| 持股、交易、試算、建議 vs 實際 | `tests/http/holdings.test.js` |
| 新聞輸入 CRUD | `tests/http/news.test.js` |
| 行情、產業、籌碼、法人 | `tests/http/stocks.test.js` |
| 爬蟲與資料回填的 admin 代理 | `tests/http/admin-proxy.test.js` |
| 美股報價代理 | `tests/http/us.test.js` |
| helmet、CORS、限流、公開端點 | `tests/http/security.test.js` |
| 18 個 SQL migration | `tests/db/migrations.test.js` |

CI：`.github/workflows/test.yml`（Postgres 16 service，`Server/` 有變動就跑）。

### 測試時可用的環境變數

- `FASTAPI_HOST` / `FASTAPI_PORT`：把 `lib/proxy.js` 的目標改到假 FastAPI（沒設就是 `localhost` 與各路由指定的埠，正式行為不變）。
- `AUTH_API_URL`：指到假的行事曆登入服務。
