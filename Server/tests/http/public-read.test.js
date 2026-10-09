/**
 * 公開讀取（Iteration 52）：和個人無關的分析頁不用登入就能讀；寫入與個人資料仍要登入；管理端點要 admin。
 */
const request = require('supertest')
const { getApp } = require('../helpers/app')
const { closeDb } = require('../helpers/db')
const { calendarToken, bearer } = require('../helpers/tokens')
const { startFakeFastAPI } = require('../helpers/fastapi-mock')

let app, fake
const USER = bearer(calendarToken({ id: 7601, username: 'pub' }))

beforeAll(async () => { app = await getApp(); fake = await startFakeFastAPI() })
afterAll(async () => { await fake.close(); await closeDb() })

describe('匿名可讀', () => {
  it.each(['/stocks?tracked=true', '/us/tickers', '/news', '/news/signals', '/portfolio/candidate', '/portfolio/runs', '/catalog'])('GET %s → 不是 401', async (p) => {
    const r = await request(app).get(p)
    expect(r.status).not.toBe(401)
    expect(r.status).toBeLessThan(500)
  })
})

describe('寫入與個人資料要登入', () => {
  it('匿名 POST /news → 401；登入後不是 401', async () => {
    expect((await request(app).post('/news').send({ platform: 'x', title: 't', content: 'c' })).status).toBe(401)
    expect((await request(app).post('/news').set(USER).send({ platform: 'x', title: 't', content: 'c' })).status).not.toBe(401)
  })
  it('匿名 GET /holdings、/cash/* → 401', async () => {
    expect((await request(app).get('/holdings')).status).toBe(401)
    expect((await request(app).get('/holdings/trades')).status).toBe(401)
  })
  it('壞 token 仍 401（前端靠它清登入狀態）', async () => {
    expect((await request(app).get('/stocks?tracked=true').set('Authorization', 'Bearer not-a-token')).status).toBe(401)
  })
  it('管理端點：匿名 401、一般使用者 403', async () => {
    expect((await request(app).get('/crawler/status/2330')).status).toBe(401)
    expect((await request(app).get('/crawler/status/2330').set(USER)).status).toBe(403)
  })
})
