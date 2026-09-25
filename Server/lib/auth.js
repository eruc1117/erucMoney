/**
 * 認證（階段 1，多使用者）
 *
 *   簽發：signToken(user) → JWT（sub = user.id, role, name；7 天）
 *   驗證：requireAuth 中介層 → req.user = { id, role, name }；沒有或無效 → 401
 *   角色：requireRole('admin') → 403
 *
 * 密鑰：環境變數 JWT_SECRET；沒有就在 Server/.jwt_secret 產生一把並重複使用
 * （重啟不會讓所有人被登出）。這個檔案在 .gitignore 裡。
 */
const fs = require('fs')
const path = require('path')
const crypto = require('crypto')
const jwt = require('jsonwebtoken')

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

function requireAuth(req, res, next) {
  const token = readToken(req)
  if (!token) return res.status(401).json({ detail: '未登入', code: 'NO_TOKEN' })
  try {
    const p = jwt.verify(token, SECRET)
    req.user = { id: Number(p.sub), role: p.role, name: p.name }
    next()
  } catch (e) {
    const expired = e.name === 'TokenExpiredError'
    res.status(401).json({ detail: expired ? '登入已過期，請重新登入' : '登入憑證無效', code: expired ? 'EXPIRED' : 'INVALID' })
  }
}

function requireRole(role) {
  return (req, res, next) => {
    if (!req.user) return res.status(401).json({ detail: '未登入' })
    if (req.user.role !== role) return res.status(403).json({ detail: `需要 ${role} 權限` })
    next()
  }
}

module.exports = { signToken, requireAuth, requireRole }
