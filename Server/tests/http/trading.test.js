/**
 * /trading：清單（假 FastAPI 的 current_list）＋ 這個人的持股 → 下單指令；登記後 /trading/log 看得到、範圍會記住。
 * 個人資料：匿名 401；兩個使用者互相看不到。
 */
const request = require('supertest')
const { getApp } = require('../helpers/app')
const { db, resetUserData, resetMarket, closeDb } = require('../helpers/db')
const { seedMarket, lastClose } = require('../helpers/seed')
const { calendarToken, bearer } = require('../helpers/tokens')
const { startFakeFastAPI } = require('../helpers/fastapi-mock')

let app, fake, seed
const A = bearer(calendarToken({ id: 7801, username: 'algo-a' }))
const B = bearer(calendarToken({ id: 7802, username: 'algo-b' }))

beforeAll(async () => {
  app = await getApp()
  fake = await startFakeFastAPI()
  await resetUserData()
  await resetMarket()
  seed = await seedMarket(db)
})
afterAll(async () => { await fake.close(); await closeDb() })

describe('權限與參數', () => {
  it('匿名 401', async () => {
    expect((await request(app).get('/trading/plan?cash=1000')).status).toBe(401)
    expect((await request(app).get('/trading/log')).status).toBe(401)
  })
  it('cash 不是數字 → 400', async () => {
    expect((await request(app).get('/trading/plan?cash=abc').set(A)).status).toBe(400)
    expect((await request(app).get('/trading/plan?cash=-1').set(A)).status).toBe(400)
  })
})

describe('程式交易引擎代理（Iteration 58）', () => {
  it('GET status／orders／events／forecast：登入即可，轉給 FastAPI', async () => {
    expect((await request(app).get('/trading/engine/status')).status).toBe(401)
    const s = await request(app).get('/trading/engine/status').set(A)
    expect(s.status).toBe(200)
    expect(s.body.engine).toMatchObject({ enabled: true, mode: 'paper' })
    const o = await request(app).get('/trading/engine/orders?status=pending&limit=5').set(A)
    expect(o.body.orders[0].status).toBe('pending')
    expect(fake.calls.find(c => c.path === '/trading/engine/orders').query).toEqual({ status: 'pending', limit: '5' })
    expect((await request(app).get('/trading/engine/events').set(A)).body.events).toHaveLength(1)
    expect((await request(app).get('/trading/engine/forecast').set(A)).body.horizons[0].p_beat).toBe(0.714)
    const rp = await request(app).get('/trading/engine/replay?start=2018-11-12&end=2024-09-30&stop_loss_pct=0.2&junk=1').set(A)
    expect(rp.status).toBe(200)
    expect(rp.body.variants.engine.stats.stop_loss).toBe(3)
    expect(fake.calls.find(c => c.path === '/trading/engine/replay').query).toEqual({ start: '2018-11-12', end: '2024-09-30', stop_loss_pct: '0.2' })
  })
  it('POST config／run：一般使用者 403、admin 轉給 FastAPI；mode 亂給 400', async () => {
    const { localToken } = require('../helpers/tokens')
    const ADMIN = bearer(localToken({ id: 1, role: 'admin' }))
    expect((await request(app).post('/trading/engine/config').set(A).send({ enabled: true })).status).toBe(403)
    expect((await request(app).post('/trading/engine/config').set(ADMIN).send({ mode: 'yolo' })).status).toBe(400)
    const r = await request(app).post('/trading/engine/config').set(ADMIN).send({ enabled: true, mode: 'paper' })
    expect(r.status).toBe(200)
    expect(r.body).toEqual({ enabled: true, mode: 'paper' })
    expect((await request(app).post('/trading/engine/run?day=2026-10-14').set(A)).status).toBe(403)
    const run = await request(app).post('/trading/engine/run?day=2026-10-14').set(ADMIN)
    expect(run.status).toBe(200)
    expect(fake.calls.find(c => c.path === '/trading/engine/run').query).toEqual({ day: '2026-10-14' })
  })
})

describe('清單 → 指令 → 登記 → 紀錄', () => {
  it('空手、投入 10 萬：三檔買單，清單資訊與下一個訊號日都有', async () => {
    const r = await request(app).get('/trading/plan?cash=100000').set(A)
    expect(r.status).toBe(200)
    expect(r.body.list).toMatchObject({ rebalance_date: '2026-09-11', n: 3 })
    expect(r.body.schedule.signal_date).toMatch(/^\d{4}-\d{2}-\d{2}$/)
    expect(r.body.note).toBe('[程式交易] 清單 2026-09-11')
    expect(r.body.orders.map(o => o.stock_id)).toEqual(['2330', '2303', '2454'])
    expect(r.body.orders[0]).toMatchObject({ side: 'Buy', shares: Math.floor(100000 * 0.5 / 2545), price: 2545, reason: 'new' })
    expect(r.body.summary.cash_after).toBeGreaterThanOrEqual(0)
    expect(r.body.managed).toEqual([])
  })

  it('自己買的 0050 不在範圍內：不動、列在 untouched、不算總資產', async () => {
    await request(app).post('/holdings/trades').set(A)
      .send({ stock_id: '0050', trade_date: seed.dates[5], side: 'Buy', shares: 1000, price: 100, note: '自己買的' })
    const r = await request(app).get('/trading/plan?cash=100000').set(A)
    expect(r.body.untouched).toHaveLength(1)
    expect(r.body.untouched[0]).toMatchObject({ stock_id: '0050', shares: 1000, last_price: lastClose('0050', seed.dates) })
    expect(r.body.summary.total).toBe(100000)
  })

  it('用程式交易登記 2303 後：持股計入總資產、2303 進 managed、/trading/log 看得到並分批', async () => {
    const plan = (await request(app).get('/trading/plan?cash=100000').set(A)).body
    const o = plan.orders.find(x => x.stock_id === '2303')
    const reg = await request(app).post('/holdings/trades').set(A)
      .send({ stock_id: '2303', trade_date: seed.dates[29], side: 'Buy', shares: o.shares, price: o.price, note: plan.note })
    expect(reg.status).toBe(201)

    const r = await request(app).get('/trading/plan?cash=100000').set(A)
    expect(r.body.managed).toEqual(['2303'])
    const pos = r.body.positions.find(p => p.stock_id === '2303')
    expect(pos.shares_now).toBe(o.shares)
    // 持股用台帳的最後收盤（seed 的 2303）算市值
    expect(r.body.summary.position_value).toBeCloseTo(o.shares * lastClose('2303', seed.dates), 2)

    const log = await request(app).get('/trading/log').set(A)
    expect(log.status).toBe(200)
    expect(log.body.items).toHaveLength(1)
    expect(log.body.items[0]).toMatchObject({ stock_id: '2303', side: 'Buy', shares: o.shares, batch: '2026-09-11', stock_name: '聯電' })
    expect(log.body.batches).toEqual([expect.objectContaining({ batch: '2026-09-11', n: 1, sell: 0 })])
    expect(log.body.batches[0].buy).toBeCloseTo(o.shares * o.price, 2)
  })

  it('另一個使用者看不到 A 的持股與紀錄', async () => {
    const r = await request(app).get('/trading/plan?cash=50000').set(B)
    expect(r.body.positions.every(p => p.shares_now === 0)).toBe(true)
    expect(r.body.untouched).toEqual([])
    expect((await request(app).get('/trading/log').set(B)).body.items).toEqual([])
  })
})
