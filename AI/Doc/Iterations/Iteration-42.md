# Iteration 42 — 部署準備：erucmoney.com（階段 2～4 的檔案與流程）

**日期：** 2026-09-25

## 起點

使用者買了 `erucmoney.com`（Cloudflare Registrar），要「先準備部署」。架構決定（Architecture-MultiUser.diagram.html）：
前端靜態放 GitHub Pages、API 用 Cloudflare Tunnel 從 `api.erucmoney.com` 接回本機 Node :3001，其他服務不對外。

## 做了什麼（程式與腳本，全部可重跑）

| 檔案 | 內容 |
|------|------|
| `.github/workflows/pages.yml` | push 到 master／main 且 `Screen/` 有變動 → `npm ci && npm run build` → `deploy-pages`。建置不寫死 API 位址 |
| `Screen/public/CNAME` | `erucmoney.com`；Vite 會原樣複製到 dist，GitHub Pages 讀它設自訂網域 |
| `Screen/src/services/api.js` | `defaultApiBase()`：在 `*.erucmoney.com` 下預設 `https://api.erucmoney.com`，其餘 `VITE_API_URL` → localhost；登入頁仍可改 |
| `.env.example` | `ALLOWED_ORIGINS`、`JWT_SECRET`、`ADMIN_PASSWORD`、`RATE_LIMIT_PER_MIN` |
| `Server/index.js` | `dotenv`；`helmet`（cross-origin resource policy 放行）；`trust proxy 1`（隧道帶 X-Forwarded-For）；全域 rate-limit（有設才開）；CORS 白名單啟動時印出來 |
| `Deploy/cloudflared-config.yml` | ingress 只有 `api.erucmoney.com → localhost:3001`，其餘 404 |
| `Deploy/install_tunnel.ps1` | winget 裝 cloudflared → `tunnel login`（瀏覽器）→ `tunnel create money` → 寫 config → `route dns` → `service install`；重跑安全 |
| `Deploy/install_api_task.ps1` | Node API 註冊成工作排程器 `MoneyApi`（登入即啟動、失敗重啟、日誌 `Server/logs/api.log`），做法同 MoneyScheduler |
| `Deploy/README.md` | 使用者要做的 8 個步驟（.env → API 常駐 → 隧道 → DNS 五筆紀錄 → Pages 設定 → push → 驗證）、選配 Cloudflare Access、常見問題 |

新依賴：`dotenv`、`helmet`。

## 驗證（本機）

- Node 以新中介層啟動：`/health` 200；帶 `Origin: https://erucmoney.com` 時（尚未設 .env，白名單全開）回 `Access-Control-Allow-Origin: *`；helmet 的安全標頭存在。
- `vite build` 通過，`dist/CNAME` = `erucmoney.com`。

## 遠端

GitHub repo 改為 `https://github.com/eruc1117/erucMoney.git`（原 `eruc1117/money` 已不存在），`origin` 已指過去；
遠端目前是空的，第一次 `git push -u origin master` 會建立 master 並成為預設分支，Pages 工作流程對 master 觸發。

## 沒辦法由程式代勞的（在 Deploy/README.md 依序）

1. `.env` 填密鑰與密碼。
2. 跑 `install_api_task.ps1`（一般權限）與 `install_tunnel.ps1`（系統管理員；會開瀏覽器授權兩次）。
3. Cloudflare DNS 加 GitHub Pages 的 4 筆 A + 1 筆 CNAME（DNS only）；`api` 的 CNAME 由腳本自動加。
4. GitHub Settings → Pages：Source 選 GitHub Actions、Custom domain 填 `erucmoney.com`、Enforce HTTPS。
5. commit + push。

## 敏感資料（推送前的檢查，2026-09-25）

掃描結果（會進 commit 的檔案、以及 git 歷史）：
- 沒有 API 金鑰、token、憑證檔、個人信箱或本機路徑。`Server/.jwt_secret`、`.env` 都在 .gitignore、從未被追蹤。
- **唯一的問題是 PostgreSQL 密碼寫死在三個檔案**（`Server/db.js`、`Crawler/config.py`、`LSTM/config.py`，值是 `password`），
  而且已經在既有的 git 歷史裡。

處理：
- 三個檔案改成從 repo 根目錄 `.env` 讀 `DB_HOST/PORT/NAME/USER/PASSWORD`（Node 用 dotenv；Python 用內建的小型讀檔，不加依賴），
  程式裡不再有預設密碼；FinMind token 同樣改 `FINMIND_TOKEN`。`.env.example` 是唯一進 repo 的範本，`.env`／`.env.*` 一律忽略。
- 歷史裡的 `password` 這個值：因為 PostgreSQL 只聽 localhost、隧道只開 3001，外面連不到資料庫，所以它本身不構成入侵路徑；
  但 GitHub Pages 免費方案需要 repo 公開，建議**推送前把 PostgreSQL 密碼換掉**（`ALTER USER postgres PASSWORD '…'` 後同步 `.env`），
  歷史裡那個值就變成無效的舊密碼。要完全不留痕跡，可以改成把工作區當成新的初始 commit 推到空的遠端（捨棄歷史）——那是使用者的決定。
- 公開 repo 也會公開 `AI/Doc` 全部文件（迭代紀錄、事件研究、模型結果）與 `news_pilot` 的 300 則新聞樣本；裡面沒有帳號或持股明細，
  只有筆數統計。

## 設計上的取捨

- **前端放 apex 網域、API 放子網域**，而不是 `eruc1117.github.io/money/`：不用改 `base`、路徑乾淨、之後換靜態主機也不動程式。
- **GitHub Pages 的 DNS 紀錄用 DNS only（灰雲）**：讓 GitHub 自己簽憑證；橘雲要另外處理 SSL 模式與 www 轉址，沒必要。
- **API 網域走橘雲（隧道本來就是）**：TLS、DDoS 擋、可加 Access 都在 Cloudflare 那一層。
- **rate-limit 用環境變數開關**：本機開發不限流，對外時 `.env` 設 300/分鐘。
- **Access 列為選配**：JWT 已擋未登入請求；Access 多一道 Email OTP 但要處理 CORS 與 cookie，等前四步跑通再開。
