/**
 * /auth：本地登入、SSO（先問行事曆）、/me、改密碼、admin 的使用者 CRUD。
 * 注意：/auth/login 有 10 次/分鐘的限流，這個檔案的登入次數要留在 10 以內；429 案例在 security.test.js。
 */
const request = require('supertest')
const { getApp } = require('../helpers/app')
const { db, resetUserData, closeDb } = require('../helpers/db')
const { localToken, calendarToken, bearer } = require('../helpers/tokens')
const { startFakeCalendar } = require('../helpers/calendar-mock')

let app
const ADMIN = localToken({ id: 1, role: 'admin', name: 'admin' })
const ADMIN_PW = process.env.ADMIN_PASSWORD

beforeAll(async () => { app = await getApp(); await resetUserData() })
afterAll(closeDb)

describe('POST /auth/login（本地帳號）', () => {
  it('admin 用 ADMIN_PASSWORD 登入 → token + user', async () => {
    const r = await request(app).post('/auth/login').send({ username: 'admin', password: ADMIN_PW })
    expect(r.status).toBe(200)
    expect(r.body.token).toEqual(expect.any(String))
    expect(r.body.user).toMatchObject({ id: 1, username: 'admin', role: 'admin' })
    expect(r.body.sso).toBeUndefined()
    // 簽出的 token 能用
    const me = await request(app).get('/auth/me').set(bearer(r.body.token))
    expect(me.body.username).toBe('admin')
  })
  it('密碼錯 → 401', async () => {
    const r = await request(app).post('/auth/login').send({ username: 'admin', password: 'nope' })
    expect(r.status).toBe(401)
  })
  it('缺欄位 → 400', async () => {
    const r = await request(app).post('/auth/login').send({ username: 'admin' })
    expect(r.status).toBe(400)
  })
})

describe('POST /auth/login（SSO：AUTH_API_URL 有設就先問行事曆）', () => {
  let cal
  beforeAll(async () => { cal = await startFakeCalendar() })
  afterAll(() => cal.close())

  it('行事曆登入成功 → 回它簽的 token、sso=calendar，並自動建立對應使用者', async () => {
    const token = calendarToken({ id: 900, username: 'calu', role: 'user' })
    cal.reply = () => ({ status: 200, body: { message: '登入成功', data: { token, user: { id: 900, username: 'calu', role: 'user' } } } })
    const r = await request(app).post('/auth/login').send({ username: 'calu', password: 'Passw0rd!' })
    expect(r.status).toBe(200)
    expect(r.body.sso).toBe('calendar')
    expect(r.body.token).toBe(token)
    expect(r.body.user).toMatchObject({ username: 'calu', role: 'user', external: true })
    expect(cal.calls[0]).toEqual({ account: 'calu', password: 'Passw0rd!' })
    const { rows } = await db.query('SELECT external_id, role FROM users WHERE username = $1', ['calu'])
    expect(rows[0]).toEqual({ external_id: 900, role: 'user' })
  })
  it('行事曆說帳號不存在 → 退回本地帳號', async () => {
    cal.reply = () => ({ status: 404, body: { message: '帳號不存在', error: { code: 'E008_ACCOUNT_NOT_EXIST' } } })
    const r = await request(app).post('/auth/login').send({ username: 'admin', password: ADMIN_PW })
    expect(r.status).toBe(200)
    expect(r.body.sso).toBeUndefined()
    expect(r.body.user.username).toBe('admin')
  })
  it('行事曆連不到 → 退回本地帳號', async () => {
    process.env.AUTH_API_URL = 'http://127.0.0.1:1'
    const r = await request(app).post('/auth/login').send({ username: 'admin', password: ADMIN_PW })
    expect(r.status).toBe(200)
    expect(r.body.user.username).toBe('admin')
  })
})

describe('GET /auth/me', () => {
  it('沒 token → 401', async () => {
    expect((await request(app).get('/auth/me')).status).toBe(401)
  })
  it('行事曆 token 第一次出現 → 自動建立並回對應使用者', async () => {
    const r = await request(app).get('/auth/me').set(bearer(calendarToken({ id: 901, username: 'first' })))
    expect(r.status).toBe(200)
    expect(r.body).toMatchObject({ username: 'first', role: 'user', is_active: true })
  })
  it('停用後 → 401', async () => {
    const t = calendarToken({ id: 902, username: 'willstop' })
    const me = await request(app).get('/auth/me').set(bearer(t))
    await request(app).put(`/auth/users/${me.body.id}`).set(bearer(ADMIN)).send({ is_active: false })
    // 停用只反映在 /me 的查詢（requireAuth 對已快取的帳號不會重查）
    const r = await request(app).get('/auth/me').set(bearer(t))
    expect(r.status).toBe(401)
  })
})

describe('POST /auth/change-password', () => {
  const NEW = 'NewPass456!'
  it('舊密碼錯 → 401；新密碼太短 → 400', async () => {
    expect((await request(app).post('/auth/change-password').set(bearer(ADMIN)).send({ old_password: 'x', new_password: NEW })).status).toBe(401)
    expect((await request(app).post('/auth/change-password').set(bearer(ADMIN)).send({ old_password: ADMIN_PW, new_password: '123' })).status).toBe(400)
  })
  it('成功後舊密碼失效、新密碼可登入；再改回來', async () => {
    expect((await request(app).post('/auth/change-password').set(bearer(ADMIN)).send({ old_password: ADMIN_PW, new_password: NEW })).status).toBe(200)
    const r = await request(app).post('/auth/login').send({ username: 'admin', password: NEW })
    expect(r.status).toBe(200)
    expect((await request(app).post('/auth/change-password').set(bearer(ADMIN)).send({ old_password: NEW, new_password: ADMIN_PW })).status).toBe(200)
  })
})

describe('admin：/auth/users', () => {
  const USER = calendarToken({ id: 903, username: 'plain' })
  it('一般使用者 → 403', async () => {
    expect((await request(app).get('/auth/users').set(bearer(USER))).status).toBe(403)
    expect((await request(app).post('/auth/users').set(bearer(USER)).send({ username: 'x', password: 'y' })).status).toBe(403)
  })
  it('建立：帳號格式、密碼長度、角色都會檢查', async () => {
    expect((await request(app).post('/auth/users').set(bearer(ADMIN)).send({ username: 'bad name!', password: 'secret1' })).status).toBe(400)
    expect((await request(app).post('/auth/users').set(bearer(ADMIN)).send({ username: 'ok_name', password: '123' })).status).toBe(400)
    expect((await request(app).post('/auth/users').set(bearer(ADMIN)).send({ username: 'ok_name', password: 'secret1', role: 'root' })).status).toBe(400)
  })
  let created
  it('建立成功 201；重複 409', async () => {
    const r = await request(app).post('/auth/users').set(bearer(ADMIN)).send({ username: 'local_da', password: 'secret1', display_name: '達叔' })
    expect(r.status).toBe(201)
    expect(r.body).toMatchObject({ username: 'local_da', role: 'user', display_name: '達叔', is_active: true })
    created = r.body
    expect((await request(app).post('/auth/users').set(bearer(ADMIN)).send({ username: 'local_da', password: 'secret1' })).status).toBe(409)
  })
  it('列表含持股／交易筆數', async () => {
    const r = await request(app).get('/auth/users').set(bearer(ADMIN))
    expect(r.status).toBe(200)
    const row = r.body.find(u => u.username === 'local_da')
    expect(row).toMatchObject({ holdings: 0, trades: 0 })
  })
  it('改角色、顯示名、密碼；本地帳號新密碼可登入', async () => {
    const r = await request(app).put(`/auth/users/${created.id}`).set(bearer(ADMIN)).send({ role: 'admin', display_name: '達', password: 'another1' })
    expect(r.status).toBe(200)
    expect(r.body).toMatchObject({ role: 'admin', display_name: '達' })
    const login = await request(app).post('/auth/login').send({ username: 'local_da', password: 'another1' })
    expect(login.status).toBe(200)
    expect(login.body.user.role).toBe('admin')
  })
  it('密碼太短 400；不存在 404；自己不能降級或停用 400；不能刪自己 400', async () => {
    expect((await request(app).put(`/auth/users/${created.id}`).set(bearer(ADMIN)).send({ password: '1' })).status).toBe(400)
    expect((await request(app).put('/auth/users/999999').set(bearer(ADMIN)).send({ role: 'user' })).status).toBe(404)
    expect((await request(app).put('/auth/users/1').set(bearer(ADMIN)).send({ role: 'user' })).status).toBe(400)
    expect((await request(app).put('/auth/users/1').set(bearer(ADMIN)).send({ is_active: false })).status).toBe(400)
    expect((await request(app).delete('/auth/users/1').set(bearer(ADMIN))).status).toBe(400)
    expect((await request(app).delete('/auth/users/999999').set(bearer(ADMIN))).status).toBe(404)
  })
  it('刪除使用者：持股與交易一起刪（CASCADE），新聞的 user_id 變 NULL', async () => {
    await db.query(`INSERT INTO user_trades (stock_id, trade_date, side, shares, price, user_id) VALUES ('2330', CURRENT_DATE, 'Buy', 10, 100, $1)`, [created.id])
    await db.query(`INSERT INTO user_holdings (stock_id, shares, avg_cost, user_id) VALUES ('2330', 10, 100, $1)`, [created.id])
    const { rows: news } = await db.query(`INSERT INTO user_news (platform, title, content, user_id) VALUES ('t', 't', 'c', $1) RETURNING id`, [created.id])
    const r = await request(app).delete(`/auth/users/${created.id}`).set(bearer(ADMIN))
    expect(r.status).toBe(200)
    expect((await db.query('SELECT COUNT(*)::int AS n FROM user_trades WHERE user_id = $1', [created.id])).rows[0].n).toBe(0)
    expect((await db.query('SELECT COUNT(*)::int AS n FROM user_holdings WHERE user_id = $1', [created.id])).rows[0].n).toBe(0)
    expect((await db.query('SELECT user_id FROM user_news WHERE id = $1', [news[0].id])).rows[0].user_id).toBeNull()
  })
})
