/**
 * /news/signals、/news/signals/gates：新聞訊號（FastAPI 代理，Iteration 47）。
 * 只斷言轉發與回應形狀；模型輸出的數值不在本計畫範圍。
 */
const request = require('supertest')
const { getApp } = require('../helpers/app')
const { closeDb } = require('../helpers/db')
const { calendarToken, bearer } = require('../helpers/tokens')
const { startFakeFastAPI, deadPort } = require('../helpers/fastapi-mock')

let app, fake
const USER = bearer(calendarToken({ id: 7401, username: 'nsu' }))

beforeAll(async () => { app = await getApp() })
afterAll(closeDb)

describe('FastAPI 在線', () => {
  beforeAll(async () => { fake = await startFakeFastAPI() })
  afterAll(() => fake.close())
  beforeEach(() => { fake.calls.length = 0 })

  it('沒 token → 401；一般使用者可讀（不是 admin 端點）', async () => {
    expect((await request(app).get('/news/signals')).status).toBe(401)
    expect((await request(app).get('/news/signals').set(USER)).status).toBe(200)
  })
  it('GET /news/signals 轉 stock_ids，回六個維度與模型服役狀態', async () => {
    const r = await request(app).get('/news/signals?stock_ids=2330,2303').set(USER)
    expect(r.status).toBe(200)
    expect(fake.calls[0]).toMatchObject({ path: '/news/signals', query: { stock_ids: '2330,2303' } })
    expect(r.body.available).toBe(true)
    expect(r.body.models.news_event_vol).toMatchObject({ serving: true, credibility: 'proven' })
    expect(r.body.models.news_drift).toMatchObject({ serving: false })
    expect(r.body.results[0]).toMatchObject({ stock_id: '2330', dims: { ns_has_news: 1 } })
    expect(r.body.results[0].drift).toBeNull()          // 未服役的模型不給值
  })
  it('GET /news/signals/gates 原樣轉回關卡', async () => {
    const r = await request(app).get('/news/signals/gates').set(USER)
    expect(r.status).toBe(200)
    expect(fake.calls[0].path).toBe('/news/signals/gates')
    expect(r.body.models.news_event_vol.gates.deploy).toBe(true)
  })
  it('/news 的清單路由不受影響', async () => {
    const r = await request(app).get('/news').set(USER)
    expect(r.status).toBe(200)
    expect(Array.isArray(r.body)).toBe(true)
  })
})

describe('FastAPI 不在線', () => {
  beforeAll(deadPort)
  it('GET /news/signals → 503 並說明要啟動爬蟲服務', async () => {
    const r = await request(app).get('/news/signals').set(USER)
    expect(r.status).toBe(503)
    expect(r.body.detail).toMatch(/爬蟲服務未啟動/)
  })
})
