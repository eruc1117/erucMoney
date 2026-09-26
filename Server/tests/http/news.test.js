/**
 * /news：使用者貼入的新聞 CRUD。
 */
const request = require('supertest')
const { getApp } = require('../helpers/app')
const { db, resetUserData, closeDb } = require('../helpers/db')
const { calendarToken, bearer } = require('../helpers/tokens')

let app
const A = bearer(calendarToken({ id: 7101, username: 'na' }))
const B = bearer(calendarToken({ id: 7102, username: 'nb' }))

beforeAll(async () => { app = await getApp(); await resetUserData() })
afterAll(closeDb)

describe('/news', () => {
  let id
  it('沒 token → 401', async () => {
    expect((await request(app).get('/news')).status).toBe(401)
  })
  it('POST 存下來並記 user_id；tickers / keywords 是陣列', async () => {
    const r = await request(app).post('/news').set(A)
      .send({ platform: '鉅亨', title: '台積電法說會', content: '內容…', stock_tickers: ['2330', '2303'], keywords: ['法說'] })
    expect(r.status).toBe(200)
    expect(r.body.status).toBe('saved')
    id = r.body.source_id
    const { rows } = await db.query('SELECT user_id, tickers, keywords, title FROM user_news WHERE id = $1', [id])
    const me = await request(app).get('/auth/me').set(A)
    expect(rows[0].user_id).toBe(me.body.id)
    expect(rows[0].tickers).toEqual(['2330', '2303'])
    expect(rows[0].keywords).toEqual(['法說'])
  })
  it('沒標題 → 存成「(無標題)」', async () => {
    const r = await request(app).post('/news').set(A).send({ platform: 'x', content: 'c' })
    const { rows } = await db.query('SELECT title FROM user_news WHERE id = $1', [r.body.source_id])
    expect(rows[0].title).toBe('(無標題)')
  })
  it('GET 列表：新的在前、含 tickers', async () => {
    const r = await request(app).get('/news').set(A)
    expect(r.status).toBe(200)
    expect(r.body[0].title).toBe('(無標題)')
    expect(r.body.find(n => n.id === id).tickers).toEqual(['2330', '2303'])
  })
  it('PUT 修改自己的', async () => {
    const r = await request(app).put(`/news/${id}`).set(A).send({ platform: '鉅亨', title: '改標題', content: 'c2', stock_tickers: ['2330'] })
    expect(r.status).toBe(200)
    const { rows } = await db.query('SELECT title, tickers FROM user_news WHERE id = $1', [id])
    expect(rows[0]).toEqual({ title: '改標題', tickers: ['2330'] })
  })
  it('PUT / DELETE 不存在 → 404', async () => {
    expect((await request(app).put('/news/999999').set(A).send({ title: 'x', content: 'y' })).status).toBe(404)
    expect((await request(app).delete('/news/999999').set(A)).status).toBe(404)
  })
  it('B 不能改或刪 A 的新聞 → 403；admin 可以', async () => {
    const { localToken } = require('../helpers/tokens')
    const ADMIN = bearer(localToken({ id: 1, role: 'admin', name: 'admin' }))
    expect((await request(app).put(`/news/${id}`).set(B).send({ title: '偷改', content: 'x' })).status).toBe(403)
    expect((await request(app).delete(`/news/${id}`).set(B)).status).toBe(403)
    const { rows } = await db.query('SELECT title FROM user_news WHERE id = $1', [id])
    expect(rows[0].title).toBe('改標題')
    const r = await request(app).put(`/news/${id}`).set(ADMIN).send({ platform: '鉅亨', title: 'admin 改', content: 'c3', stock_tickers: ['2330'] })
    expect(r.status).toBe(200)
    await request(app).put(`/news/${id}`).set(ADMIN).send({ platform: '鉅亨', title: '改標題', content: 'c2', stock_tickers: ['2330'] })
  })
  it('PUT / DELETE id 不是數字 → 400', async () => {
    expect((await request(app).put('/news/abc').set(A).send({ title: 'x', content: 'y' })).status).toBe(400)
  })
  it('DELETE 自己的', async () => {
    const r = await request(app).delete(`/news/${id}`).set(A)
    expect(r.status).toBe(200)
    expect((await db.query('SELECT 1 FROM user_news WHERE id = $1', [id])).rowCount).toBe(0)
  })
  it('B 也看得到列表（新聞是共享的，只有 user_id 記錄誰貼的）', async () => {
    const r = await request(app).get('/news').set(B)
    expect(r.status).toBe(200)
    expect(Array.isArray(r.body)).toBe(true)
  })
})
