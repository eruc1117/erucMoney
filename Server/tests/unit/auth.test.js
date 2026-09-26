/**
 * lib/auth.js：兩種 token、行事曆帳號的自動建立與角色同步、requireRole。db 全部 mock。
 */
jest.mock('../../db', () => ({ query: jest.fn() }))
const db = require('../../db')
const express = require('express')
const request = require('supertest')
const jwt = require('jsonwebtoken')
const { requireAuth, requireRole, signToken, resolveExternalUser } = require('../../lib/auth')
const { localToken, calendarToken, bearer, SECRET } = require('../helpers/tokens')

const app = express()
app.get('/who', requireAuth, (req, res) => res.json(req.user))
app.get('/admin', requireAuth, requireRole('admin'), (_req, res) => res.json({ ok: true }))

/** 依 SQL 內容回應的 db.query：用 Map 記住「外部 id → users 列」 */
function fakeUsers(initial = {}) {
  const users = new Map(Object.entries(initial).map(([k, v]) => [Number(k), v]))
  let nextId = 100
  const taken = new Set(['admin'])
  db.query.mockReset()
  db.query.mockImplementation(async (sql, params) => {
    if (/SELECT id, username, role, is_active FROM users WHERE external_id/.test(sql)) {
      const u = users.get(params[0])
      return { rows: u ? [u] : [] }
    }
    if (/SELECT 1 FROM users WHERE username/.test(sql)) return { rows: taken.has(params[0]) ? [{}] : [] }
    if (/INSERT INTO users/.test(sql)) {
      const u = { id: nextId++, username: params[0], role: 'user', is_active: true }
      users.set(params[2], u)
      return { rows: [u] }
    }
    if (/UPDATE users SET role/.test(sql)) {
      for (const u of users.values()) if (u.id === params[0]) u.role = params[1]
      return { rows: [], rowCount: 1 }
    }
    return { rows: [], rowCount: 0 }
  })
  return { users, sqlCalls: () => db.query.mock.calls.map(c => c[0].replace(/\s+/g, ' ').trim()) }
}

beforeEach(() => fakeUsers())

describe('requireAuth：本地 token', () => {
  it('沒帶 token → 401 NO_TOKEN', async () => {
    const r = await request(app).get('/who')
    expect(r.status).toBe(401)
    expect(r.body.code).toBe('NO_TOKEN')
  })
  it('壞簽章 → 401 INVALID', async () => {
    const bad = jwt.sign({ sub: '1', role: 'admin' }, 'wrong-secret-wrong-secret-wrong-secret')
    const r = await request(app).get('/who').set(bearer(bad))
    expect(r.status).toBe(401)
    expect(r.body.code).toBe('INVALID')
  })
  it('過期 → 401 EXPIRED', async () => {
    const old = jwt.sign({ sub: '1', role: 'admin', name: 'admin' }, SECRET, { expiresIn: -10 })
    const r = await request(app).get('/who').set(bearer(old))
    expect(r.status).toBe(401)
    expect(r.body.code).toBe('EXPIRED')
  })
  it('{sub, role, name} → req.user 直接來自 token，不查 db', async () => {
    const r = await request(app).get('/who').set(bearer(localToken({ id: 7, role: 'user', name: 'da' })))
    expect(r.status).toBe(200)
    expect(r.body).toEqual({ id: 7, role: 'user', name: 'da' })
    expect(db.query).not.toHaveBeenCalled()
  })
  it('signToken 簽出來的能被 requireAuth 接受', async () => {
    const t = signToken({ id: 3, role: 'admin', username: 'root' })
    const r = await request(app).get('/who').set(bearer(t))
    expect(r.body).toEqual({ id: 3, role: 'admin', name: 'root' })
  })
  it('沒有 sub 也沒有 id 的 token → 401', async () => {
    const t = jwt.sign({ foo: 'bar' }, SECRET)
    const r = await request(app).get('/who').set(bearer(t))
    expect(r.status).toBe(401)
    expect(r.body.code).toBe('INVALID')
  })
})

describe('requireAuth：行事曆 token（external_id 對應）', () => {
  it('第一次出現：建一列，role 依 token（user）', async () => {
    const { users } = fakeUsers()
    const r = await request(app).get('/who').set(bearer(calendarToken({ id: 501, username: 'calu', role: 'user' })))
    expect(r.status).toBe(200)
    expect(r.body).toMatchObject({ role: 'user', name: 'calu', external: true })
    expect(users.get(501)).toMatchObject({ username: 'calu', role: 'user' })
  })
  it('第一次出現且 token 是 admin：建列後同步成 admin', async () => {
    const { users, sqlCalls } = fakeUsers()
    const r = await request(app).get('/who').set(bearer(calendarToken({ id: 502, username: 'boss', role: 'admin' })))
    expect(r.body.role).toBe('admin')
    expect(users.get(502).role).toBe('admin')
    expect(sqlCalls().some(s => /UPDATE users SET role/.test(s))).toBe(true)
  })
  it('username 與本地帳號撞名 → 改用 cal_<id>', async () => {
    const { users } = fakeUsers()
    await request(app).get('/who').set(bearer(calendarToken({ id: 503, username: 'admin' })))
    expect(users.get(503).username).toBe('cal_503')
  })
  it('已存在且角色相同 → 第二次走快取，不再查 db', async () => {
    fakeUsers({ 504: { id: 40, username: 'x', role: 'user', is_active: true } })
    await request(app).get('/who').set(bearer(calendarToken({ id: 504, username: 'x' })))
    const before = db.query.mock.calls.length
    const r = await request(app).get('/who').set(bearer(calendarToken({ id: 504, username: 'x' })))
    expect(r.body.id).toBe(40)
    expect(db.query.mock.calls.length).toBe(before)
  })
  it('角色改變（user → admin → user）：每次都 UPDATE 並更新快取', async () => {
    const { users, sqlCalls } = fakeUsers({ 505: { id: 41, username: 'y', role: 'user', is_active: true } })
    let r = await request(app).get('/who').set(bearer(calendarToken({ id: 505, username: 'y', role: 'admin' })))
    expect(r.body.role).toBe('admin')
    expect(users.get(505).role).toBe('admin')
    r = await request(app).get('/who').set(bearer(calendarToken({ id: 505, username: 'y', role: 'user' })))
    expect(r.body.role).toBe('user')
    expect(users.get(505).role).toBe('user')
    expect(sqlCalls().filter(s => /UPDATE users SET role/.test(s)).length).toBe(2)
  })
  it('token 帶奇怪的 role → 視為 user', async () => {
    const { users } = fakeUsers()
    await request(app).get('/who').set(bearer(calendarToken({ id: 506, username: 'z', role: 'root' })))
    expect(users.get(506).role).toBe('user')
  })
  it('停用的帳號 → 401 INACTIVE', async () => {
    fakeUsers({ 507: { id: 42, username: 'off', role: 'user', is_active: false } })
    const r = await request(app).get('/who').set(bearer(calendarToken({ id: 507, username: 'off' })))
    expect(r.status).toBe(401)
    expect(r.body.code).toBe('INACTIVE')
  })
  it('db 出錯 → 500 帶訊息，不會當成登入成功', async () => {
    db.query.mockRejectedValue(new Error('connection refused'))
    const r = await request(app).get('/who').set(bearer(calendarToken({ id: 508, username: 'e' })))
    expect(r.status).toBe(500)
    expect(r.body.detail).toMatch(/connection refused/)
  })
  it('resolveExternalUser 可直接呼叫（/auth/login 的 SSO 分支用）', async () => {
    const { users } = fakeUsers()
    const u = await resolveExternalUser(509, 'direct', 'user')
    expect(u).toMatchObject({ id: users.get(509).id, role: 'user', name: 'direct', external: true })
  })
})

describe('requireRole', () => {
  it('admin 通過', async () => {
    const r = await request(app).get('/admin').set(bearer(localToken({ id: 1, role: 'admin' })))
    expect(r.status).toBe(200)
  })
  it('user → 403 並說明需要的角色', async () => {
    const r = await request(app).get('/admin').set(bearer(localToken({ id: 2, role: 'user', name: 'u' })))
    expect(r.status).toBe(403)
    expect(r.body.detail).toMatch(/admin/)
  })
  it('行事曆 admin token 也通過', async () => {
    fakeUsers()
    const r = await request(app).get('/admin').set(bearer(calendarToken({ id: 510, username: 'cadmin', role: 'admin' })))
    expect(r.status).toBe(200)
  })
  it('沒 token → 401（requireAuth 先擋）', async () => {
    const r = await request(app).get('/admin')
    expect(r.status).toBe(401)
  })
})
