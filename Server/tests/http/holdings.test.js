/**
 * /holdings：持股、交易台帳回放、手續費試算、建議 vs 實際。兩個使用者（行事曆 token）互相看不到。
 */
const request = require('supertest')
const { getApp } = require('../helpers/app')
const { db, resetUserData, resetMarket, closeDb } = require('../helpers/db')
const { seedMarket, lastClose } = require('../helpers/seed')
const { calendarToken, bearer } = require('../helpers/tokens')

let app, seed
const A = bearer(calendarToken({ id: 7001, username: 'alice' }))
const B = bearer(calendarToken({ id: 7002, username: 'bob' }))

beforeAll(async () => {
  app = await getApp()
  await resetUserData()
  await resetMarket()
  seed = await seedMarket(db)
})
afterAll(closeDb)

describe('交易台帳 → 持股', () => {
  let sellId
  it('POST /holdings/trades 買進 → 201，持股由回放產生', async () => {
    const r = await request(app).post('/holdings/trades').set(A)
      .send({ stock_id: '0050', trade_date: seed.dates[10], side: 'Buy', shares: 100, price: 100 })
    expect(r.status).toBe(201)
    expect(r.body).toMatchObject({ ok: true, shares: 100, avgCost: 100.2, realized: 0 })   // 手續費 20 計入成本
    const h = await request(app).get('/holdings').set(A)
    expect(h.body.items).toHaveLength(1)
    expect(h.body.items[0]).toMatchObject({ stock_id: '0050', shares: 100, avg_cost: 100.2, source: 'trades', trade_count: 1, stock_name: '元大台灣50' })
    expect(h.body.items[0].last_price).toBe(lastClose('0050', seed.dates))
    expect(h.body.items[0].market_value).toBeCloseTo(100 * lastClose('0050', seed.dates), 2)
    expect(h.body.summary).toMatchObject({ count: 1, trade_count: 1, sell_count: 0, max_weight_pct: 100 })
  })
  it('欄位不完整 → 400', async () => {
    expect((await request(app).post('/holdings/trades').set(A).send({ stock_id: '0050', side: 'Hold', shares: 1, price: 1 })).status).toBe(400)
    expect((await request(app).post('/holdings/trades').set(A).send({ stock_id: '0050', trade_date: seed.dates[1], side: 'Buy', shares: 0, price: 1 })).status).toBe(400)
  })
  it('另一個使用者看不到', async () => {
    const h = await request(app).get('/holdings').set(B)
    expect(h.body.items).toHaveLength(0)
    expect(h.body.summary.count).toBe(0)
    expect((await request(app).get('/holdings/trades').set(B)).body).toHaveLength(0)
  })
  it('賣出 → 已實現損益，均價不變、股數減少', async () => {
    const r = await request(app).post('/holdings/trades').set(A)
      .send({ stock_id: '0050', trade_date: seed.dates[12], side: 'Sell', shares: 40, price: 110 })
    expect(r.status).toBe(201)
    expect(r.body).toMatchObject({ shares: 60, avgCost: 100.2, realized: 359 })   // 40*(110-100.2) - 20 - 13
    const t = await request(app).get('/holdings/trades?stock_id=0050').set(A)
    expect(t.body).toHaveLength(2)
    sellId = t.body.find(x => x.side === 'Sell').id
    expect(t.body.find(x => x.side === 'Sell')).toMatchObject({ fee: 20, tax: 13, realized_pnl: 359, shares_after: 60 })
    const h = await request(app).get('/holdings').set(A)
    expect(h.body.summary.realized_pnl).toBe(359)
    expect(h.body.summary.sell_count).toBe(1)
  })
  it('使用者自填 fee/tax 不被覆蓋', async () => {
    const r = await request(app).post('/holdings/trades').set(A)
      .send({ stock_id: '2303', trade_date: seed.dates[3], side: 'Buy', shares: 1000, price: 150, fee: 50, tax: 0 })
    expect(r.status).toBe(201)
    expect(r.body.avgCost).toBe(150.05)
  })
  it('DELETE 交易 → 回放重算；刪別人的 → 404', async () => {
    expect((await request(app).delete(`/holdings/trades/${sellId}`).set(B)).status).toBe(404)
    const r = await request(app).delete(`/holdings/trades/${sellId}`).set(A)
    expect(r.status).toBe(200)
    expect(r.body).toMatchObject({ shares: 100, realized: 0 })
    expect((await request(app).delete(`/holdings/trades/${sellId}`).set(A)).status).toBe(404)
  })
  it('有交易紀錄的股票不能手動改持股（409）', async () => {
    const r = await request(app).post('/holdings').set(A).send({ stock_id: '0050', shares: 5, avg_cost: 1 })
    expect(r.status).toBe(409)
    const { rows } = await db.query('SELECT id FROM user_holdings WHERE stock_id = $1', ['0050'])
    const put = await request(app).put(`/holdings/${rows[0].id}`).set(A).send({ shares: 5 })
    expect(put.status).toBe(409)
  })
  it('全部賣光 → 持倉列消失，已實現損益留在 summary', async () => {
    await request(app).post('/holdings/trades').set(A).send({ stock_id: '0050', trade_date: seed.dates[13], side: 'Sell', shares: 100, price: 120 })
    const h = await request(app).get('/holdings').set(A)
    expect(h.body.items.find(i => i.stock_id === '0050')).toBeUndefined()
    expect(h.body.summary.realized_pnl).toBeGreaterThan(0)
  })
})

describe('手動持倉快照', () => {
  let id
  it('POST /holdings 建立（source=manual）；同檔再 POST 視為更新', async () => {
    const r = await request(app).post('/holdings').set(B).send({ stock_id: '2330', shares: 10, avg_cost: 500, note: '舊持股' })
    expect(r.status).toBe(201)
    expect(r.body).toMatchObject({ stock_id: '2330', source: 'manual' })
    id = r.body.id
    const r2 = await request(app).post('/holdings').set(B).send({ stock_id: '2330', shares: 20, avg_cost: 510 })
    expect(r2.status).toBe(201)
    expect(r2.body.id).toBe(id)
    expect(Number(r2.body.shares)).toBe(20)
  })
  it('欄位不合法 → 400', async () => {
    expect((await request(app).post('/holdings').set(B).send({ stock_id: '2330', shares: -1, avg_cost: 1 })).status).toBe(400)
  })
  it('PUT 改 note；別人的 → 404', async () => {
    expect((await request(app).put(`/holdings/${id}`).set(A).send({ note: 'hack' })).status).toBe(404)
    const r = await request(app).put(`/holdings/${id}`).set(B).send({ note: '改了' })
    expect(r.status).toBe(200)
    expect(r.body.note).toBe('改了')
  })
  it('記了交易後，手動快照讓位給台帳', async () => {
    await request(app).post('/holdings/trades').set(B).send({ stock_id: '2330', trade_date: seed.dates[2], side: 'Buy', shares: 5, price: 2400 })
    const h = await request(app).get('/holdings').set(B)
    const row = h.body.items.find(i => i.stock_id === '2330')
    expect(row.source).toBe('trades')
    expect(row.shares).toBe(5)
  })
  it('DELETE 持股；別人的 → 404', async () => {
    const r = await request(app).post('/holdings').set(B).send({ stock_id: '2454', shares: 1, avg_cost: 1300 })
    expect((await request(app).delete(`/holdings/${r.body.id}`).set(A)).status).toBe(404)
    expect((await request(app).delete(`/holdings/${r.body.id}`).set(B)).status).toBe(200)
    expect((await request(app).delete(`/holdings/${r.body.id}`).set(B)).status).toBe(404)
  })
})

describe('GET /holdings/trades/estimate', () => {
  it('依台股費率試算', async () => {
    const r = await request(app).get('/holdings/trades/estimate?side=Sell&shares=1000&price=50').set(A)
    expect(r.body).toMatchObject({ fee: 71, tax: 150, gross: 50000 })
    expect(r.body.note).toMatch(/證交稅/)
  })
  it('參數不合法 → 400', async () => {
    expect((await request(app).get('/holdings/trades/estimate?shares=0&price=50').set(A)).status).toBe(400)
  })
})

describe('GET /holdings/review：建議 vs 實際', () => {
  const C = bearer(calendarToken({ id: 7003, username: 'carol' }))
  beforeAll(async () => {
    const d = seed.dates
    // 建議：0050 在 d[10] Buy、d[12] Hold；2303 在 d[0] Buy（到 d[10] 已過期 > 7 天）；2330 在 d[5] Buy 但沒交易（missed）
    for (const [sid, date, action] of [['0050', d[10], 'Buy'], ['0050', d[12], 'Hold'], ['2303', d[0], 'Buy'], ['2330', d[5], 'Buy']]) {
      await db.query(`INSERT INTO voting_results (stock_id, vote_date, final_signal, final_action, score) VALUES ($1, $2, $3, $3, 0.7)
                      ON CONFLICT (stock_id, vote_date) DO UPDATE SET final_action = EXCLUDED.final_action`, [sid, date, action])
    }
    await request(app).post('/holdings/trades').set(C).send({ stock_id: '0050', trade_date: d[10], side: 'Buy', shares: 10, price: 115 })
    await request(app).post('/holdings/trades').set(C).send({ stock_id: '0050', trade_date: d[11], side: 'Sell', shares: 5, price: 116 })
    await request(app).post('/holdings/trades').set(C).send({ stock_id: '0050', trade_date: d[12], side: 'Buy', shares: 5, price: 116 })
    await request(app).post('/holdings/trades').set(C).send({ stock_id: '2303', trade_date: d[10], side: 'Buy', shares: 1000, price: 153 })
  })
  it('每筆交易對到當時最近一次建議並分類，附 5 日 adj_close 報酬', async () => {
    const r = await request(app).get('/holdings/review').set(C)
    expect(r.status).toBe(200)
    const by = (sid, side) => r.body.items.find(i => i.stock_id === sid && i.side === side)
    const buy = r.body.items.find(i => i.stock_id === '0050' && i.side === 'Buy' && i.trade_date === seed.dates[10])
    expect(buy.match.key).toBe('follow')
    expect(buy.recommendation).toBe('Buy')
    // 5 日報酬：seed 0050 第 10 天 115 → 第 15 天 117.5 = +2.17%
    expect(buy.fwd_return_5d).toBeCloseTo(2.17, 1)
    expect(buy.benefit).toBeCloseTo(2.17, 1)
    expect(by('0050', 'Sell').match.key).toBe('against')       // 建議 Buy 卻賣
    expect(by('0050', 'Sell').benefit).toBeLessThan(0)          // 賣出後上漲 → 負效益
    const hold = r.body.items.find(i => i.stock_id === '0050' && i.trade_date === seed.dates[12])
    expect(hold.match.key).toBe('neutral')
    const stale = by('2303', 'Buy')
    expect(stale.stale_vote).toBe(true)
    expect(stale.recommendation).toBeNull()
    expect(stale.match.label).toBe('建議已過期')
  })
  it('summary 統計與「錯過的建議」', async () => {
    const r = await request(app).get('/holdings/review').set(C)
    expect(r.body.summary).toMatchObject({ trades: 4, follow: { n: 1 }, against: { n: 1 }, neutral: { n: 1 } })
    expect(r.body.summary.follow_rate).toBe(50)
    expect(r.body.missed.some(m => m.stock_id === '2330')).toBe(true)
    expect(r.body.summary.missed_count).toBeGreaterThanOrEqual(1)
  })
  it('別人的檢討只有自己的交易（A 有 3 筆：0050 買、2303 買、0050 賣光）', async () => {
    const r = await request(app).get('/holdings/review').set(A)
    expect(r.body.summary.trades).toBe(3)
    expect(r.body.items.some(i => i.stock_id === '2303' && i.price === 153)).toBe(false)   // 那是 C 的
  })
})
