/**
 * /stocks：行情、產業、籌碼、法人的讀取端點（seed 3 檔追蹤 + 1 檔未追蹤，各 30 個交易日）。
 */
const request = require('supertest')
const { getApp } = require('../helpers/app')
const { db, resetMarket, closeDb } = require('../helpers/db')
const { seedMarket, lastClose } = require('../helpers/seed')
const { localToken, bearer } = require('../helpers/tokens')

let app, seed
const T = bearer(localToken({ id: 1, role: 'admin', name: 'admin' }))

beforeAll(async () => { app = await getApp(); await resetMarket(); seed = await seedMarket(db) })
afterAll(closeDb)

describe('GET /stocks', () => {
  it('沒 token → 401', async () => {
    expect((await request(app).get('/stocks?tracked=true')).status).toBe(401)
  })
  it('?tracked=true 只回 is_tracking，含最新收盤、外資持股與日期', async () => {
    const r = await request(app).get('/stocks?tracked=true').set(T)
    expect(r.status).toBe(200)
    expect(r.body.map(s => s.stock_id).sort()).toEqual(['0050', '2303', '2330'])
    const tsmc = r.body.find(s => s.stock_id === '2330')
    expect(Number(tsmc.close_price)).toBe(lastClose('2330', seed.dates))
    expect(tsmc.trade_date).toBe(seed.dates.at(-1))
    expect(tsmc.foreign_holding_date).toBe(seed.dates.at(-1))
    expect(Number(tsmc.foreign_holding_ratio)).toBeGreaterThan(40)
  })
  it('?tracked=true&industry= 篩產業', async () => {
    const r = await request(app).get('/stocks?tracked=true&industry=ETF').set(T)
    expect(r.body.map(s => s.stock_id)).toEqual(['0050'])
  })
  it('?max_price= 依預算篩，價格由高到低；未追蹤的也算', async () => {
    const r = await request(app).get('/stocks?max_price=200').set(T)
    expect(r.body.map(s => s.stock_id)).toEqual(['2303', '0050'])
    expect(r.body.every(s => Number(s.close_price) <= 200)).toBe(true)
    const r2 = await request(app).get('/stocks?max_price=5000&industry=半導體業').set(T)
    expect(r2.body.map(s => s.stock_id).sort()).toEqual(['2303', '2330', '2454'])
  })
  it('沒給 max_price 也不是 tracked → 400', async () => {
    expect((await request(app).get('/stocks').set(T)).status).toBe(400)
  })
})

describe('GET /stocks/industries', () => {
  it('各產業股票數，多的在前', async () => {
    const r = await request(app).get('/stocks/industries').set(T)
    expect(r.body).toEqual([{ industry_type: '半導體業', stock_count: 3 }, { industry_type: 'ETF', stock_count: 1 }])
  })
})

describe('GET /stocks/:id', () => {
  it('基本資訊 + 最新行情 + 籌碼 + 外資持股', async () => {
    const r = await request(app).get('/stocks/2330').set(T)
    expect(r.status).toBe(200)
    expect(r.body).toMatchObject({ stock_id: '2330', stock_name: '台積電', industry_type: '半導體業', trade_date: seed.dates.at(-1) })
    expect(Number(r.body.close_price)).toBe(lastClose('2330', seed.dates))
    expect(Number(r.body.total_net_buy)).toBe(1000 * 30)
    expect(r.body.foreign_holding_date).toBe(seed.dates.at(-1))
  })
  it('外資持股比行情晚一天揭露：foreign_holding_date 早於 trade_date（前端據此標示）', async () => {
    const r = await request(app).get('/stocks/2303').set(T)
    expect(r.body.trade_date).toBe(seed.dates.at(-1))
    expect(r.body.foreign_holding_date).toBe(seed.dates.at(-2))
    expect(r.body.foreign_holding_date < r.body.trade_date).toBe(true)
  })
  it('查無此股 → 404', async () => {
    expect((await request(app).get('/stocks/9999').set(T)).status).toBe(404)
  })
})

describe('GET /stocks/:id/prices', () => {
  it('無參數 → 全部歷史，由舊到新，日期是 YYYY-MM-DD 字串', async () => {
    const r = await request(app).get('/stocks/0050/prices').set(T)
    expect(r.body).toHaveLength(30)
    expect(r.body[0].trade_date).toBe(seed.dates[0])
    expect(r.body.at(-1).trade_date).toBe(seed.dates.at(-1))
    expect(r.body[0]).toEqual(expect.objectContaining({ open_price: expect.any(String), close_price: expect.any(String), volume: expect.any(String) }))
  })
  it('?days=10 → 最近 10 個日曆日內的列（上限 365）', async () => {
    const r = await request(app).get('/stocks/0050/prices?days=10').set(T)
    expect(r.body.length).toBeGreaterThanOrEqual(6)
    expect(r.body.length).toBeLessThanOrEqual(10)
    const r2 = await request(app).get('/stocks/0050/prices?days=9999').set(T)
    expect(r2.body).toHaveLength(30)
  })
  it('?start_date&end_date → 指定區間（含頭尾）', async () => {
    const r = await request(app).get(`/stocks/0050/prices?start_date=${seed.dates[5]}&end_date=${seed.dates[9]}`).set(T)
    expect(r.body.map(x => x.trade_date)).toEqual(seed.dates.slice(5, 10))
  })
  it('沒資料的代號 → 空陣列（不是 404）', async () => {
    expect((await request(app).get('/stocks/9999/prices').set(T)).body).toEqual([])
  })
})

describe('GET /stocks/:id/chips 與 /institutional', () => {
  it('chips：三大法人每日買賣超', async () => {
    const r = await request(app).get('/stocks/2330/chips?days=400').set(T)
    expect(r.body).toHaveLength(30)
    expect(r.body.at(-1)).toMatchObject({ trade_date: seed.dates.at(-1), total_net_buy: '30000', foreign_investor_buy: '18000' })
  })
  it('institutional：累計買賣超、收盤價、外資真實持股與期間摘要', async () => {
    const r = await request(app).get('/stocks/2330/institutional?days=400').set(T)
    expect(r.status).toBe(200)
    expect(r.body).toMatchObject({ stock_id: '2330', stock_name: '台積電', trading_days: 30, start_date: seed.dates[0], end_date: seed.dates.at(-1) })
    const last = r.body.series.at(-1)
    expect(last.cum_total).toBe(1000 * (30 * 31 / 2))       // Σ 1000·i
    expect(last.close_price).toBe(lastClose('2330', seed.dates))
    expect(last.foreign_ratio).toBeCloseTo(40 + 29 * 0.1, 1)
    expect(r.body.summary.total.buy_days).toBe(30)
    expect(r.body.summary.foreign_holding.days).toBe(30)
    expect(r.body.summary.foreign_holding.ratio_change).toBeCloseTo(2.9, 1)
    expect(r.body.summary.price_change_pct).toBeGreaterThan(0)
  })
  it('institutional：外資持股少最後一天 → 摘要以最後一筆有值的列為準', async () => {
    const r = await request(app).get('/stocks/2303/institutional?days=400').set(T)
    expect(r.body.series.at(-1).foreign_ratio).toBeNull()
    expect(r.body.summary.foreign_holding.days).toBe(29)
    expect(r.body.summary.foreign_holding.end_date).toBe(seed.dates.at(-2))
  })
  it('institutional：不在主檔 → 404', async () => {
    expect((await request(app).get('/stocks/9999/institutional').set(T)).status).toBe(404)
  })
})
