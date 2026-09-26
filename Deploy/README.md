# 部署：erucmoney.com（階段 2～4；Iteration 43 起改為統一前端）

網域配置（2026-09-26）：

| 網域 | 內容 | 來源 |
|------|------|------|
| `erucmoney.com` | **統一前端**：行事曆平台（含「股票」分頁），登入只有一套 | GitHub Pages，[meeting_front_end](https://github.com/eruc1117/meeting_front_end) |
| `stock.erucmoney.com` | 股票完整儀表板（從行事曆按「開啟完整儀表板」以 `#token=` 交接免登入） | GitHub Pages，本 repo `Screen/`；**Actions 部署不讀 `public/CNAME`，Custom domain 要在 repo Settings → Pages 手動填 `stock.erucmoney.com`** |
| `api.erucmoney.com` | 股票 API（本機 Node :3001） | Cloudflare Tunnel |
| `calendar-api.erucmoney.com` | 行事曆 API（本機 Node :5000，[meeting_API_Server](https://github.com/eruc1117/meeting_API_Server)） | Cloudflare Tunnel |

Cloudflare DNS 要有：apex 四筆 A + `www` CNAME（GitHub Pages，灰雲）、`stock` CNAME → `eruc1117.github.io`（灰雲）、
`api`／`calendar-api` CNAME → 隧道（橘雲，`cloudflared tunnel route dns` 自動加）。
PostgreSQL、FastAPI、LSTM、排程器全部留在本機，不對外。

```
瀏覽器 ──HTTPS──▶ GitHub Pages（Screen/dist）
   │
   └──HTTPS + Bearer──▶ api.erucmoney.com（Cloudflare）──隧道──▶ cloudflared 服務 ──▶ localhost:3001（Node）
                                                                                      ├─ pg → PostgreSQL :5432
                                                                                      ├─ proxy → FastAPI :8000
                                                                                      └─ proxy → LSTM :8001
```

## 已備好的檔案

| 檔案 | 用途 |
|------|------|
| `.github/workflows/pages.yml` | push 到 master／main 且 `Screen/` 有變動 → build → 部署 GitHub Pages |
| `Screen/public/CNAME` | `erucmoney.com`，GitHub Pages 讀它設自訂網域 |
| `Screen/src/services/api.js` | 在 `*.erucmoney.com` 下預設 API = `https://api.erucmoney.com`；登入頁可改 |
| `.env.example` | `ALLOWED_ORIGINS`、`JWT_SECRET`、`ADMIN_PASSWORD`、`RATE_LIMIT_PER_MIN` |
| `Server/index.js` | dotenv、helmet、trust proxy、全域 rate-limit、CORS 白名單 |
| `Deploy/cloudflared-config.yml` | 隧道 ingress：只有 `api.erucmoney.com → localhost:3001` |
| `Deploy/install_tunnel.ps1` | 裝 cloudflared → 登入 → 建隧道 → 寫設定 → DNS → 裝服務 |
| `Deploy/install_api_task.ps1` | Node API 登入即啟動（工作排程器 `MoneyApi`） |
| `Deploy/install_services_task.ps1` | FastAPI :8000（`MoneyCrawlerApi`）與 LSTM :8001（`MoneyLstm`）登入即啟動；只聽本機，不進隧道 |

## 你要做的步驟（依序）

### A. 本機後端（5 分鐘）

1. `copy .env.example .env`，填：
   - `JWT_SECRET`：`node -e "console.log(require('crypto').randomBytes(48).toString('hex'))"`
   - `ADMIN_PASSWORD`：只在 admin 還沒設密碼時生效；已經用 admin123 登入過就到前端「帳號」頁改
   - `ALLOWED_ORIGINS` 與 `RATE_LIMIT_PER_MIN` 用範例值
2. `powershell -ExecutionPolicy Bypass -File Deploy\install_api_task.ps1`
   → `http://localhost:3001/health` 回 `{"ok":true}`；`Server\logs\api.log` 應印出 `[cors] 白名單：…`

### B. 隧道（10 分鐘，會開兩次瀏覽器）

3. **系統管理員** PowerShell：`powershell -ExecutionPolicy Bypass -File Deploy\install_tunnel.ps1`
   - 第 2 步瀏覽器選 `erucmoney.com` 授權
   - 第 5 步會自動在 Cloudflare 加 `api` 的 CNAME
4. 驗證：`curl https://api.erucmoney.com/health` 回 `{"ok":true}`。
   不通：`Get-Service cloudflared`、事件檢視器 → Windows Logs → Application 找 cloudflared。

### C. 前端上 GitHub Pages（10 分鐘）

5. Cloudflare DNS 加 GitHub Pages 的紀錄（**Proxy 狀態選 DNS only，灰雲**，讓 GitHub 自己簽憑證）：

   | 類型 | 名稱 | 內容 |
   |------|------|------|
   | A | `@` | `185.199.108.153` |
   | A | `@` | `185.199.109.153` |
   | A | `@` | `185.199.110.153` |
   | A | `@` | `185.199.111.153` |
   | CNAME | `www` | `eruc1117.github.io` |

6. GitHub repo `eruc1117/erucMoney` → Settings → Pages：
   - Source：**GitHub Actions**
   - Custom domain：`erucmoney.com` → 等 DNS check 通過 → 勾 **Enforce HTTPS**
7. commit 並 push（工作流程只在 `Screen/` 有變動時觸發；第一次可到 Actions 頁手動 Run workflow）。
8. 開 `https://erucmoney.com` → 登入頁 → 「後端位址」應顯示 `https://api.erucmoney.com` → 測試連線 → 登入。

### D. 選配：Cloudflare Access（第二道門）

Zero Trust → Access → Applications → Self-hosted，網域 `api.erucmoney.com`，Policy：Emails 列你們的信箱、One-time PIN。
之後瀏覽器第一次打 API 會先跳 Cloudflare 的 Email 驗證。注意：Access 會擋沒帶 cookie 的 `fetch`，
要在 Application 設定「Allow CORS」並把 `https://erucmoney.com` 加進允許來源，否則前端會被 302 到登入頁。
先不開也可以，JWT 已經擋住未登入的請求。

## 常見問題

- **前端能開但登入失敗「連不到」**：先 `curl https://api.erucmoney.com/health`。隧道通但 401／CORS 錯，看 `Server\logs\api.log` 的 `[cors] 白名單` 有沒有 `https://erucmoney.com`。
- **GitHub Pages 顯示 404**：Settings → Pages 的 Source 沒選 GitHub Actions，或工作流程沒跑（Actions 頁看）。
- **www 開不了**：CNAME `www` 沒加，或 Pages 的 Custom domain 只填了 apex；GitHub 會自動把 www 導到 apex。
- **重啟電腦後 API 不通**：`Get-ScheduledTask MoneyApi`、`Get-Service cloudflared` 兩個都要在跑。
- **換密鑰**：改 `.env` 的 `JWT_SECRET` 並重啟 MoneyApi，所有人重新登入。
