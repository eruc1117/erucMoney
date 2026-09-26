/**
 * 帳號路由（階段 1）
 *
 *   POST /auth/login                    {username, password} → {token, user}
 *   GET  /auth/me                       目前登入者
 *   POST /auth/change-password          {old_password, new_password}
 *   GET  /auth/users                    admin：列表
 *   POST /auth/users                    admin：建帳號 {username, password, role, display_name}
 *   PUT  /auth/users/:id                admin：改角色／顯示名／停用、重設密碼 {password}
 *   DELETE /auth/users/:id              admin：刪帳號（持股與交易一起刪，CASCADE）
 *
 * 不開放自助註冊：帳號由 admin 建。密碼 bcrypt（cost 10）。
 */
const { Router } = require('express')
const bcrypt = require('bcryptjs')
const rateLimit = require('express-rate-limit')
const db = require('../db')
const { signToken, requireAuth, requireRole } = require('../lib/auth')

const router = Router()
const loginLimiter = rateLimit({ windowMs: 60 * 1000, limit: 10, standardHeaders: true, legacyHeaders: false,
                                 message: { detail: '登入嘗試太頻繁，一分鐘後再試' } })

const PUBLIC = 'id, username, role, display_name, is_active, created_at, last_login_at, external_id'

// SSO：AUTH_API_URL 有設時，先拿帳密去行事曆平台（meeting_API_Server）登入；成功就回它簽的 token
// （本系統用同一把密鑰驗證，requireAuth 會自動建立對應使用者）。行事曆說帳號不存在／密碼錯，才退回本地帳號（admin）。
async function loginViaCalendar(account, password) {
  const base = (process.env.AUTH_API_URL || '').replace(/\/+$/, '')
  if (!base) return null
  const ctrl = new AbortController()
  const timer = setTimeout(() => ctrl.abort(), 10000)
  try {
    const r = await fetch(`${base}/api/auth/login`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ account, password }), signal: ctrl.signal,
    })
    const body = await r.json().catch(() => ({}))
    if (!r.ok || !body?.data?.token) return { ok: false, status: r.status }
    return { ok: true, token: body.data.token, user: body.data.user }
  } catch (e) {
    console.warn('[auth] 行事曆登入服務連不到，改用本地帳號：', e.message)
    return null
  } finally {
    clearTimeout(timer)
  }
}

router.post('/login', loginLimiter, async (req, res) => {
  const { username, password } = req.body ?? {}
  if (!username || !password) return res.status(400).json({ detail: '請輸入帳號與密碼' })
  try {
    const cal = await loginViaCalendar(String(username).trim(), String(password))
    if (cal && cal.ok) {
      const { resolveExternalUser } = require('../lib/auth')
      const u = await resolveExternalUser(Number(cal.user.id), cal.user.username)
      if (!u) return res.status(401).json({ detail: '帳號已停用' })
      await db.query('UPDATE users SET last_login_at = CURRENT_TIMESTAMP WHERE id = $1', [u.id])
      return res.json({ token: cal.token, sso: 'calendar',
                        user: { id: u.id, username: u.name, role: u.role, display_name: cal.user.username, external: true } })
    }
    const { rows } = await db.query('SELECT * FROM users WHERE username = $1', [String(username).trim()])
    const u = rows[0]
    const ok = u && u.is_active && u.password_hash && await bcrypt.compare(String(password), u.password_hash)
    if (!ok) return res.status(401).json({ detail: '帳號或密碼錯誤' })
    await db.query('UPDATE users SET last_login_at = CURRENT_TIMESTAMP WHERE id = $1', [u.id])
    res.json({ token: signToken(u),
               user: { id: u.id, username: u.username, role: u.role, display_name: u.display_name } })
  } catch (e) {
    console.error('[POST /auth/login]', e.message)
    res.status(500).json({ detail: e.message })
  }
})

router.get('/me', requireAuth, async (req, res) => {
  const { rows } = await db.query(`SELECT ${PUBLIC} FROM users WHERE id = $1`, [req.user.id])
  if (!rows[0] || !rows[0].is_active) return res.status(401).json({ detail: '帳號不存在或已停用' })
  res.json(rows[0])
})

router.post('/change-password', requireAuth, async (req, res) => {
  const { old_password, new_password } = req.body ?? {}
  if (!new_password || String(new_password).length < 6)
    return res.status(400).json({ detail: '新密碼至少 6 個字' })
  const { rows } = await db.query('SELECT password_hash FROM users WHERE id = $1', [req.user.id])
  if (!rows[0] || !(await bcrypt.compare(String(old_password ?? ''), rows[0].password_hash)))
    return res.status(401).json({ detail: '舊密碼錯誤' })
  await db.query('UPDATE users SET password_hash = $1 WHERE id = $2',
                 [await bcrypt.hash(String(new_password), 10), req.user.id])
  res.json({ ok: true })
})

// ── admin ──
router.get('/users', requireAuth, requireRole('admin'), async (_req, res) => {
  const { rows } = await db.query(`
    SELECT ${PUBLIC},
           (SELECT COUNT(*) FROM user_holdings h WHERE h.user_id = users.id)::int AS holdings,
           (SELECT COUNT(*) FROM user_trades t WHERE t.user_id = users.id)::int AS trades
      FROM users ORDER BY id`)
  res.json(rows)
})

router.post('/users', requireAuth, requireRole('admin'), async (req, res) => {
  const { username, password, role = 'user', display_name } = req.body ?? {}
  if (!username || !/^[A-Za-z0-9_.-]{2,50}$/.test(username))
    return res.status(400).json({ detail: '帳號 2~50 字，只能英數、底線、點、連字號' })
  if (!password || String(password).length < 6) return res.status(400).json({ detail: '密碼至少 6 個字' })
  if (!['admin', 'user'].includes(role)) return res.status(400).json({ detail: 'role 只能是 admin 或 user' })
  try {
    const { rows } = await db.query(
      `INSERT INTO users (username, password_hash, role, display_name) VALUES ($1, $2, $3, $4) RETURNING ${PUBLIC}`,
      [username, await bcrypt.hash(String(password), 10), role, display_name || null])
    res.status(201).json(rows[0])
  } catch (e) {
    if (e.code === '23505') return res.status(409).json({ detail: '帳號已存在' })
    console.error('[POST /auth/users]', e.message)
    res.status(500).json({ detail: e.message })
  }
})

router.put('/users/:id', requireAuth, requireRole('admin'), async (req, res) => {
  const id = Number(req.params.id)
  const { role, display_name, is_active, password } = req.body ?? {}
  if (id === req.user.id && (is_active === false || (role && role !== 'admin')))
    return res.status(400).json({ detail: '不能停用或降級自己' })
  try {
    if (password != null) {
      if (String(password).length < 6) return res.status(400).json({ detail: '密碼至少 6 個字' })
      await db.query('UPDATE users SET password_hash = $1 WHERE id = $2', [await bcrypt.hash(String(password), 10), id])
    }
    const { rows } = await db.query(`
      UPDATE users SET role = COALESCE($1, role), display_name = COALESCE($2, display_name),
                       is_active = COALESCE($3, is_active)
       WHERE id = $4 RETURNING ${PUBLIC}`,
      [role ?? null, display_name ?? null, typeof is_active === 'boolean' ? is_active : null, id])
    if (!rows[0]) return res.status(404).json({ detail: '找不到使用者' })
    res.json(rows[0])
  } catch (e) {
    console.error('[PUT /auth/users/:id]', e.message)
    res.status(500).json({ detail: e.message })
  }
})

router.delete('/users/:id', requireAuth, requireRole('admin'), async (req, res) => {
  const id = Number(req.params.id)
  if (id === req.user.id) return res.status(400).json({ detail: '不能刪除自己' })
  const { rowCount } = await db.query('DELETE FROM users WHERE id = $1', [id])
  if (!rowCount) return res.status(404).json({ detail: '找不到使用者' })
  res.json({ ok: true })
})

module.exports = router
