/**
 * /us：美股報價與標的清單（FastAPI 代理）。只斷言報價與新鮮度欄位，不斷言跳空預測的數值。
 */
const request = require('supertest')
const { getApp } = require('../helpers/app')
const { closeDb } = require('../helpers/db')
const { calendarToken, bearer } = require('../helpers/tokens')
const { startFakeFastAPI, deadPort } = require('../helpers/fastapi-mock')

let app, fake
const USER = bearer(calendarToken({ id: 7301, username: 'usu' }))

beforeAll(async () => { app = await getApp() })
afterAll(closeDb)

describe('FastAPI 在線', () => {
  beforeAll(async () => { fake = await startFakeFastAPI() })
  afterAll(() => fake.close())
  beforeEach(() => { fake.calls.length = 0 })

  it('沒 token → 401；一般使用者可讀', async () => {
    expect((await request(app).get('/us/tickers')).status).toBe(401)
    expect((await request(app).get('/us/tickers').set(USER)).status).toBe(200)
  })
  it('GET /us/tickers 原樣轉回清單（追蹤與否由上游決定）', async () => {
    const r = await request(app).get('/us/tickers').set(USER)
    expect(r.body.map(t => t.ticker)).toEqual(['TSM', 'SPY'])
    expect(r.body.every(t => t.is_tracking)).toBe(true)
    expect(fake.calls[0].path).toBe('/us/tickers')
  })
  it('GET /us/overview?days= 轉 query，回報價與新鮮度', async () => {
    const r = await request(app).get('/us/overview?days=30').set(USER)
    expect(r.status).toBe(200)
    expect(fake.calls[0]).toMatchObject({ path: '/us/overview', query: { days: '30' } })
    expect(r.body.tickers[0]).toMatchObject({ ticker: 'TSM', close: 200.5, last_date: '2026-09-25' })
    expect(r.body.freshness).toMatchObject({ last_date: '2026-09-25', days_behind: 1 })
    expect(r.body).toHaveProperty('gap')   // 預測欄位存在即可，數值不在本計畫範圍
  })
  it('GET /us/gap?tickers= 轉 query', async () => {
    await request(app).get('/us/gap?tickers=TSM,SPY').set(USER)
    expect(fake.calls[0]).toMatchObject({ path: '/us/gap', query: { tickers: 'TSM,SPY' } })
  })
})

describe('FastAPI 掛掉', () => {
  beforeAll(async () => { await deadPort() })
  afterAll(() => { delete process.env.FASTAPI_PORT; delete process.env.FASTAPI_HOST })
  it('三條都回 503 並說明怎麼啟動', async () => {
    for (const p of ['/us/overview', '/us/gap', '/us/tickers']) {
      const r = await request(app).get(p).set(USER)
      expect(r.status).toBe(503)
      expect(r.body.detail).toMatch(/FastAPI :8000/)
    }
  })
})
