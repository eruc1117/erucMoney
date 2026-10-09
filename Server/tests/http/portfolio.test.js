/**
 * /portfolio/*：月調倉實驗日誌（FastAPI 代理，Iteration 51）。只斷言轉發、授權與回應形狀。
 */
const request = require('supertest')
const { getApp } = require('../helpers/app')
const { closeDb } = require('../helpers/db')
const { calendarToken, bearer } = require('../helpers/tokens')
const { startFakeFastAPI, deadPort } = require('../helpers/fastapi-mock')

let app, fake
const USER = bearer(calendarToken({ id: 7501, username: 'pfu' }))

beforeAll(async () => { app = await getApp() })
afterAll(closeDb)

describe('FastAPI 在線', () => {
  beforeAll(async () => { fake = await startFakeFastAPI() })
  afterAll(() => fake.close())
  beforeEach(() => { fake.calls.length = 0 })

  it('沒 token → 401；一般使用者可讀', async () => {
    expect((await request(app).get('/portfolio/candidate')).status).toBe(401)
    expect((await request(app).get('/portfolio/candidate').set(USER)).status).toBe(200)
  })
  it('GET /portfolio/candidate 回候選三列、全期間曲線與門檻', async () => {
    const r = await request(app).get('/portfolio/candidate').set(USER)
    expect(r.status).toBe(200)
    expect(fake.calls[0].path).toBe('/portfolio/candidate')
    expect(r.body.candidates).toHaveLength(3)
    expect(r.body.full.series[0]).toMatchObject({ d: '2018-01-12', nav: 1, bench: 1 })
    expect(r.body.thresholds.dsr).toBe(0.95)
    expect(r.body.holdout_opened).toBe(false)
  })
  it('GET /portfolio/runs 回全部實驗', async () => {
    const r = await request(app).get('/portfolio/runs').set(USER)
    expect(r.status).toBe(200)
    expect(r.body.n_total).toBe(2)
    expect(r.body.runs[1]).toMatchObject({ experiment_n: 2, tag: 'candidate' })
  })
  it('GET /portfolio/runs/:id 轉 step；非整數 id → 400', async () => {
    const r = await request(app).get('/portfolio/runs/44?step=5').set(USER)
    expect(r.status).toBe(200)
    expect(fake.calls[0]).toMatchObject({ path: '/portfolio/runs/44', query: { step: '5' } })
    expect(r.body.run.id).toBe(44)
    expect((await request(app).get('/portfolio/runs/abc').set(USER)).status).toBe(400)
  })
})

describe('FastAPI 不在線', () => {
  beforeAll(deadPort)
  it('GET /portfolio/candidate → 503 並說明要啟動爬蟲服務', async () => {
    const r = await request(app).get('/portfolio/candidate').set(USER)
    expect(r.status).toBe(503)
    expect(r.body.detail).toMatch(/爬蟲服務未啟動/)
  })
})
