/**
 * 認證（階段 1 多使用者；SSO 後接受行事曆平台的 JWT）
 *
 * 兩種 token 都用同一把密鑰驗證（JWT_SECRET 必須等於行事曆 meeting_API_Server 的 SECRET）：
 *   本地 token   { sub: <users.id>, role, name }               本系統 /auth/login 簽的（admin 等本地帳號）
 *   行事曆 token { id: <行事曆 users.id>, username }           meeting_API_Server 簽的（1 小時）
 * 行事曆 token 第一次出現時，在本系統 users 表自動建立一列（external_id = 行事曆 id，role = user），
 * 之後 req.user.id 就是本系統的 id，持股／交易的隔離照常以它為準。
 *
 *   簽發：signToken(user) → JWT（sub = user.id, role, name；7 天）
 *   驗證：requireAuth 中介層 → req.user = { id, role, name, external? }；沒有或無效 → 401
 *   角色：requireRole('admin') → 403
 *
 * 密鑰：環境變數 JWT_SECRET；沒有就在 Server/.jwt_secret 產生一把並重複使用。
 */
const fs = require('fs')
const path = require('path')
const crypto = require('crypto')
const jwt = require('jsonwebtoken')
const db = require('../db')

const SECRET_FILE = path.join(__dirname, '..', '.jwt_secret')
const TOKEN_TTL = process.env.JWT_TTL || '7d'

function loadSecret() {
  if (process.env.JWT_SECRET) return process.env.JWT_SECRET
  try {
    const s = fs.readFileSync(SECRET_FILE, 'utf8').trim()
    if (s.length >= 32) return s
  } catch { /* 沒有就產生 */ }
  const s = crypto.randomBytes(48).toString('hex')
  fs.writeFileSync(SECRET_FILE, s, { mode: 0o600 })
  console.log('[auth] 已產生 JWT 密鑰：Server/.jwt_secret（不要提交到 git）')
  return s
}
const SECRET = loadSecret()

function signToken(user) {
  return jwt.sign({ sub: String(user.id), role: user.role, name: user.username },
                  SECRET, { expiresIn: TOKEN_TTL })
}

function readToken(req) {
  const h = req.headers.authorization || ''
  if (h.startsWith('Bearer ')) return h.slice(7).trim()
  return null
}

// 行事曆 id → 本系統使用者，記憶體快取（重啟就重讀 DB）
const externalCache = new Map()
const SSO_ADMINS = new Set(String(process.env.SSO_ADMIN_USERNAMES || '').split(',').map(s => s.trim()).filter(Boolean))

/** 把行事曆帳號對應到本系統 users 列，沒有就建立。回傳 { id, role, name, external: true } 或 null（已停用）。 */
async function resolveExternalUser(externalId, username) {
  const hit = externalCache.get(externalId)
  if (hit) return hit
  let { rows } = await db.query(
    'SELECT id, username, role, is_active FROM users WHERE external_id = $1', [externalId])
  if (!rows[0]) {
    // username 若與本地帳號撞名（例如都叫 admin），用 cal_<id> 避開；顯示名保留原名
    const base = (username || `cal_${externalId}`).slice(0, 50)
    const { rows: taken } = await db.query('SELECT 1 FROM users WHERE username = $1', [base])
    const uname = taken.length ? `cal_${externalId}` : base
    const ins = await db.query(
      `INSERT INTO users (username, password_hash, role, display_name, external_id)
       VALUES ($1, '', 'user', $2, $3)
       ON CONFLICT (external_id) WHERE external_id IS NOT NULL DO UPDATE SET display_name = EXCLUDED.display_name
       RETURNING id, username, role, is_active`,
      [uname, username || null, externalId])
    rows = ins.rows
    console.log(`[auth] 行事曆帳號 ${username || externalId} 第一次登入，建立本系統使用者 id=${rows[0].id}`)
  }
  let u = rows[0]
  if (!u.is_active) return null
  // 單一登入的管理者：.env 的 SSO_ADMIN_USERNAMES（逗號分隔的行事曆帳號 username）第一次進來就升成 admin，
  // 不必先有一個本地 admin 去改角色。之後在「使用者」頁改回 user 也會被這裡再升回來——要降級就從清單移除。
  if (username && SSO_ADMINS.has(username) && u.role !== 'admin') {
    await db.query('UPDATE users SET role = $2 WHERE id = $1', [u.id, 'admin'])
    u = { ...u, role: 'admin' }
    console.log(`[auth] ${username} 在 SSO_ADMIN_USERNAMES 內，升為 admin（users.id=${u.id}）`)
  }
  const out = { id: u.id, role: u.role, name: u.username, external: true }
  externalCache.set(externalId, out)
  return out
}

async function requireAuth(req, res, next) {
  const token = readToken(req)
  if (!token) return res.status(401).json({ detail: '未登入', code: 'NO_TOKEN' })
  let p
  try {
    p = jwt.verify(token, SECRET)
  } catch (e) {
    const expired = e.name === 'TokenExpiredError'
    return res.status(401).json({ detail: expired ? '登入已過期，請重新登入' : '登入憑證無效', code: expired ? 'EXPIRED' : 'INVALID' })
  }
  try {
    if (p.sub) {
      req.user = { id: Number(p.sub), role: p.role, name: p.name }
    } else if (p.id) {
      const u = await resolveExternalUser(Number(p.id), p.username)
      if (!u) return res.status(401).json({ detail: '帳號已停用', code: 'INACTIVE' })
      req.user = u
    } else {
      return res.status(401).json({ detail: '登入憑證無法辨識', code: 'INVALID' })
    }
    next()
  } catch (e) {
    console.error('[auth] 對應行事曆帳號失敗：', e.message)
    res.status(500).json({ detail: e.message })
  }
}

function requireRole(role) {
  return (req, res, next) => {
    if (!req.user) return res.status(401).json({ detail: '未登入' })
    if (req.user.role !== role) return res.status(403).json({ detail: `需要 ${role} 權限` })
    next()
  }
}

module.exports = { signToken, requireAuth, requireRole, resolveExternalUser }
