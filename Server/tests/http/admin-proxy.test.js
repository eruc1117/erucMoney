/**
 * /crawler、/data：admin 專用的 FastAPI 代理。用假 FastAPI 驗證權限、轉發的 body／query、FastAPI 掛掉時的回應。
 */
const request = require('supertest')
const { getApp } = require('../helpers/app')
const { closeDb } = require('../helpers/db')
const { localToken, calendarToken, bearer } = require('../helpers/tokens')
const { startFakeFastAPI, deadPort } = require('../helpers/fastapi-mock')

let app, fake
const ADMIN = bearer(localToken({ id: 1, role: 'admin', name: 'admin' }))
const USER = bearer(calendarToken({ id: 7201, username: 'pu' }))

beforeAll(async () => { app = await getApp() })
afterAll(closeDb)

describe('權限', () => {
  it('一般使用者 → 403；沒 token → 401', async () => {
    expect((await request(app).post('/crawler/run').set(USER).send({ stock_id: '2330' })).status).toBe(403)
    expect((await request(app).get('/data/freshness').set(USER)).status).toBe(403)
    expect((await request(app).post('/data/backfill').set(USER)).status).toBe(403)
    expect((await request(app).get('/crawler/status/2330')).status).toBe(401)
  })
})

describe('FastAPI 在線（假伺服器）', () => {
  beforeAll(async () => { fake = await startFakeFastAPI() })
  afterAll(() => fake.close())
  beforeEach(() => { fake.calls.length = 0 })

  it('POST /crawler/run 把 body 原樣轉過去，沿用上游狀態碼', async () => {
    const r = await request(app).post('/crawler/run').set(ADMIN).send({ stock_id: '2330', start_date: '2026-01-01', end_date: '2026-01-31' })
    expect(r.status).toBe(200)
    expect(r.body).toEqual({ status: 'started', stock_id: '2330' })
    expect(fake.calls[0]).toMatchObject({ method: 'POST', path: '/crawler/run', body: { stock_id: '2330', start_date: '2026-01-01', end_date: '2026-01-31' } })
  })
  it('GET /crawler/status/:id', async () => {
    const r = await request(app).get('/crawler/status/2330').set(ADMIN)
    expect(r.body).toEqual({ stock_id: '2330', status: 'idle' })
    expect(fake.calls[0].path).toBe('/crawler/status/2330')
  })
  it('POST /crawler/news 與 GET /crawler/news/status', async () => {
    const r = await request(app).post('/crawler/news').set(ADMIN).send({ start_date: null, end_date: null, keywords: ['台積電'] })
    expect(r.body.status).toBe('started')
    expect(fake.calls[0].body.keywords).toEqual(['台積電'])
    const s = await request(app).get('/crawler/news/status').set(ADMIN)
    expect(s.body).toMatchObject({ status: 'idle', last_count: 0 })
  })
  it('GET /data/freshness?stock_ids= 轉 query', async () => {
    const r = await request(app).get('/data/freshness?stock_ids=2330,0050').set(ADMIN)
    expect(r.status).toBe(200)
    expect(r.body.available).toBe(true)
    expect(fake.calls[0]).toMatchObject({ path: '/data/freshness', query: { stock_ids: '2330,0050' } })
  })
  it('POST /data/backfill?stock_ids=&max_stocks= 轉 query，不轉 body', async () => {
    const r = await request(app).post('/data/backfill?stock_ids=2330&max_stocks=5').set(ADMIN)
    expect(r.status).toBe(200)
    expect(fake.calls[0]).toMatchObject({ method: 'POST', path: '/data/backfill', query: { stock_ids: '2330', max_stocks: '5' } })
  })
  it('外生資料的兩條', async () => {
    expect((await request(app).get('/data/freshness/exogenous').set(ADMIN)).body.available).toBe(true)
    expect((await request(app).post('/data/backfill/exogenous').set(ADMIN)).body.ok).toBe(true)
    expect(fake.calls.map(c => c.path)).toEqual(['/data/freshness/exogenous', '/data/backfill/exogenous'])
  })
  it('上游 4xx／5xx 的狀態碼與 detail 原樣回；上游回非 JSON → 包成 detail', async () => {
    fake.respond('POST /crawler/run', () => ({ status: 429, body: { status: 'rate_limited', detail: '30 分鐘內已爬過' } }))
    const r = await request(app).post('/crawler/run').set(ADMIN).send({ stock_id: '2330' })
    expect(r.status).toBe(429)
    expect(r.body.status).toBe('rate_limited')
    fake.respond('GET /data/freshness', () => ({ status: 500, body: 'Internal Server Error' }))
    const r2 = await request(app).get('/data/freshness').set(ADMIN)
    expect(r2.status).toBe(500)
    expect(r2.body.detail).toMatch(/Internal Server Error/)
    expect(r2.body.upstream_status).toBe(500)
  })
})

describe('FastAPI 掛掉', () => {
  beforeAll(async () => { await deadPort() })
  afterAll(() => { delete process.env.FASTAPI_PORT; delete process.env.FASTAPI_HOST })

  it('/crawler/status/:id → 回 idle（讓前端輪詢正常結束）', async () => {
    const r = await request(app).get('/crawler/status/2330').set(ADMIN)
    expect(r.status).toBe(200)
    expect(r.body).toEqual({ stock_id: '2330', status: 'idle' })
  })
  it('/crawler/news/status → idle', async () => {
    const r = await request(app).get('/crawler/news/status').set(ADMIN)
    expect(r.body).toMatchObject({ status: 'idle', last_count: 0 })
  })
  it('/crawler/run → 503 且說明 FastAPI 未啟動', async () => {
    const r = await request(app).post('/crawler/run').set(ADMIN).send({ stock_id: '2330' })
    expect(r.status).toBe(503)
    expect(r.body.detail).toMatch(/FastAPI/)
  })
  it('/data/freshness、/data/backfill → 503 帶啟動說明', async () => {
    const r = await request(app).get('/data/freshness').set(ADMIN)
    expect(r.status).toBe(503)
    expect(r.body.detail).toMatch(/FastAPI :8000/)
    expect((await request(app).post('/data/backfill').set(ADMIN)).status).toBe(503)
  })
})
