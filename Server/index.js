/**
 * Node.js Server — 處理資料庫與前端畫面資料
 * 監聽 http://localhost:3001
 *
 * 啟動方式：
 *   npm start          (生產)
 *   npm run dev        (開發，自動重載)
 *
 * 架構：
 *   Frontend (React) → Node.js Server (3001) → PostgreSQL
 *   /crawler/*        → Proxy → FastAPI (8000) → FinMind API
 */

const path = require('path')
require('dotenv').config({ path: path.join(__dirname, '..', '.env') })   // repo 根目錄 .env（見 .env.example）
require('dotenv').config({ path: path.join(__dirname, '.env') })         // Server/.env 可覆寫（選用）
const express      = require('express')
const cors         = require('cors')
const helmet       = require('helmet')
const rateLimit    = require('express-rate-limit')
const bcrypt       = require('bcryptjs')
const db           = require('./db')
const runMigrations = require('./lib/migrate')
const { requireAuth, requireRole } = require('./lib/auth')
const authRouter   = require('./routes/auth')

const stocksRouter      = require('./routes/stocks')
const crawlerRouter     = require('./routes/crawler')
const newsRouter        = require('./routes/news')
const modelRouter       = require('./routes/model')
const predictionsRouter = require('./routes/predictions')
const votingRouter      = require('./routes/voting')
const gapRouter         = require('./routes/gap')
const modelsRouter      = require('./routes/models')
const holdingsRouter    = require('./routes/holdings')
const cashRouter        = require('./routes/cash')
const dataRouter        = require('./routes/data')
const catalogRouter     = require('./routes/catalog')
const usRouter          = require('./routes/us')
const forecastRouter    = require('./routes/forecast')

const app = express()
// 對外（階段 3～4）：經 Cloudflare Tunnel 進來的請求帶 X-Forwarded-For，信任一層代理，rate-limit 才拿得到真實 IP
app.set('trust proxy', 1)
app.use(helmet({ crossOriginResourcePolicy: { policy: 'cross-origin' } }))   // 純 API，資源給 erucmoney.com 用
// CORS：ALLOWED_ORIGINS="https://erucmoney.com,http://localhost:5173"；沒設就全開（本機開發）
const allowed = (process.env.ALLOWED_ORIGINS || '').split(',').map(s => s.trim()).filter(Boolean)
app.use(cors(allowed.length ? { origin: allowed } : undefined))
if (allowed.length) console.log('[cors] 白名單：', allowed.join(', '))
else console.log('[cors] ⚠ 未設 ALLOWED_ORIGINS，全部來源放行（只適合本機開發）')
const perMin = Number(process.env.RATE_LIMIT_PER_MIN || 0)
if (perMin > 0) app.use(rateLimit({ windowMs: 60 * 1000, limit: perMin, standardHeaders: true, legacyHeaders: false }))
app.use(express.json({ limit: '1mb' }))

// ── 階段 1（多使用者）：/auth 與 /health 公開，其餘全部要登入；管理端點要 admin ──
app.get('/health', (_req, res) => res.json({ ok: true, time: new Date().toISOString() }))
app.use('/auth',        authRouter)
app.use(requireAuth)
app.use('/stocks',      stocksRouter)
app.use('/crawler',    requireRole('admin'), crawlerRouter)
app.use('/news',       newsRouter)
app.use('/model',      modelRouter)
app.use('/predictions', predictionsRouter)
app.use('/voting',      votingRouter)
app.use('/gap',         gapRouter)
app.use('/models',      requireRole('admin'), modelsRouter)
app.use('/holdings',    holdingsRouter)
app.use('/cash',        cashRouter)
app.use('/data',        requireRole('admin'), dataRouter)
app.use('/catalog',     catalogRouter)
app.use('/us',          usRouter)
app.use('/forecast',    forecastRouter)

// 第一次啟動：admin 密碼從環境變數 ADMIN_PASSWORD 來；沒設就用 admin123 並警告。
// 只在 password_hash 為空（migration 017 剛建的占位列）時寫入，之後改密碼走 /auth/change-password。
async function ensureAdmin() {
  const { rows } = await db.query("SELECT id, password_hash FROM users WHERE username = 'admin'")
  if (rows[0] && !rows[0].password_hash) {
    const pw = process.env.ADMIN_PASSWORD || 'admin123'
    await db.query('UPDATE users SET password_hash = $1 WHERE id = $2', [await bcrypt.hash(pw, 10), rows[0].id])
    console.log(process.env.ADMIN_PASSWORD
      ? '[auth] admin 密碼已依 ADMIN_PASSWORD 設定'
      : '[auth] ⚠ admin 密碼為預設 admin123，登入後請立刻到「帳號」改掉')
  }
}

// ── 初始化：執行 Migration → 建立資料表 → 啟動伺服器 ────────────────────────
async function start() {
  await runMigrations()
  await ensureAdmin()

  await db.query(`
    CREATE TABLE IF NOT EXISTS user_news (
      id           SERIAL PRIMARY KEY,
      platform     VARCHAR(100),
      title        VARCHAR(500),
      content      TEXT,
      tickers      TEXT[],
      keywords     TEXT[] DEFAULT ARRAY[]::TEXT[],
      submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
  `)
  // 既有資料表補欄位（idempotent）
  await db.query(`
    ALTER TABLE user_news
    ADD COLUMN IF NOT EXISTS keywords TEXT[] DEFAULT ARRAY[]::TEXT[]
  `)
  await db.query(`
    CREATE TABLE IF NOT EXISTS saved_predictions (
      id          SERIAL PRIMARY KEY,
      stock_id    VARCHAR(10)  NOT NULL,
      model_key   VARCHAR(50)  NOT NULL,
      model_label VARCHAR(100),
      saved_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
      predictions JSONB NOT NULL
    )
  `)
  await db.query(`
    CREATE TABLE IF NOT EXISTS voting_results (
      id            SERIAL PRIMARY KEY,
      stock_id      VARCHAR(10)  NOT NULL,
      vote_date     DATE         NOT NULL,
      m1_signal     VARCHAR(4),
      m2_signal     VARCHAR(4),
      m3_signal     VARCHAR(4),
      final_signal  VARCHAR(4),
      score         FLOAT,
      weights       JSONB,
      m1_reason     TEXT,
      m2_reason     TEXT,
      m3_reason     TEXT,
      created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
      UNIQUE (stock_id, vote_date)
    )
  `)
  await db.query(`
    ALTER TABLE voting_results
    ADD COLUMN IF NOT EXISTS m2_features JSONB
  `)
  await db.query(`
    CREATE TABLE IF NOT EXISTS news_features (
      id            SERIAL PRIMARY KEY,
      stock_id      VARCHAR(10)  NOT NULL,
      feature_date  DATE         NOT NULL,
      sentiment     FLOAT,
      keyword_hits  JSONB,
      article_count INT DEFAULT 0,
      updated_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
      UNIQUE (stock_id, feature_date)
    )
  `)
  console.log('資料表確認完畢')

  app.listen(3001, () => {
    console.log('Node.js Server 已啟動：http://localhost:3001')
    console.log('前端請將 API_URL 指向 http://localhost:3001')
    console.log('爬蟲觸發將 proxy 至 http://localhost:8000')
  })
}

start().catch(err => {
  console.error('伺服器啟動失敗：', err.message)
  process.exit(1)
})
