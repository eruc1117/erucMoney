/**
 * Express 應用程式（不含 listen）
 *
 * 從 index.js 拆出來，讓測試（supertest）可以 require 它而不啟動監聽；
 * index.js 只負責 `init()` 後 `app.listen(3001)`。行為與拆分前完全相同。
 *
 *   const { app, init } = require('./app')
 *   await init()          // migration → ensureAdmin → 建表（原本 start() 的前半）
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
const { requireAuth, requireRole, optionalAuth, readPublic, requireUser } = require('./lib/auth')
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
const portfolioRouter   = require('./routes/portfolio')
const progressRouter    = require('./routes/progress')
const tradingRouter     = require('./routes/trading')

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

// ── 權限（Iteration 52）：三種路由 ──
//   公開讀取  readPublic   行情、預測、投票、新聞、美股、月調倉…的 GET 不用登入（和個人無關的分析頁）；寫入（POST／PUT／DELETE）要登入
//   個人      requireUser  持股、閒置資金：全部要登入，資料只有自己的
//   管理      requireUser + requireRole('admin')  爬蟲、資料回填、模型版本
// optionalAuth 掛最外層：有 token 就解析（壞的回 401 讓前端清登入），沒有就匿名。
app.get('/health', (_req, res) => res.json({ ok: true, time: new Date().toISOString() }))
app.use('/auth',        authRouter)
app.use(optionalAuth)
app.use('/stocks',      readPublic, stocksRouter)
app.use('/crawler',     requireUser, requireRole('admin'), crawlerRouter)
app.use('/news',        readPublic, newsRouter)
app.use('/model',       readPublic, modelRouter)
app.use('/predictions', readPublic, predictionsRouter)
app.use('/voting',      readPublic, votingRouter)
app.use('/gap',         readPublic, gapRouter)
app.use('/models',      requireUser, requireRole('admin'), modelsRouter)
app.use('/holdings',    requireUser, holdingsRouter)
app.use('/cash',        requireUser, cashRouter)
app.use('/data',        requireUser, requireRole('admin'), dataRouter)
app.use('/catalog',     readPublic, catalogRouter)
app.use('/us',          readPublic, usRouter)
app.use('/forecast',    readPublic, forecastRouter)
app.use('/portfolio',   readPublic, portfolioRouter)
app.use('/trading',     requireUser, tradingRouter)   // 程式交易：清單 → 這個人的下單指令（個人資料）
app.use('/progress',    requireUser, requireRole('admin'), progressRouter)   // 工作進度（harness 狀態，只讀檔案與 git）

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

// ── 初始化：執行 Migration → 建立資料表（原 index.js start() 的前半）──────────
async function init() {
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
}

module.exports = { app, init, ensureAdmin }
