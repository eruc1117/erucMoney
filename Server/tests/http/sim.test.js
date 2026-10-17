/**
 * /sim（Iteration 60）：公開的交易模擬——匿名就能用；回放與自訂指令都轉給 FastAPI，Node 只驗參數與上限。
 */
const request = require('supertest')
const { getApp } = require('../helpers/app')
const { closeDb } = require('../helpers/db')
const { startFakeFastAPI } = require('../helpers/fastapi-mock')

let app, fake
beforeAll(async () => { app = await getApp(); fake = await startFakeFastAPI() })
afterAll(async () => { await fake.close(); await closeDb() })

describe('匿名可用', () => {
  it('GET /sim/replay → 200，參數只轉白名單八個', async () => {
    const r = await request(app).get('/sim/replay?start=2018-11-12&end=2024-09-30&stop_loss_pct=0&junk=1')
    expect(r.status).toBe(200)
    expect(r.body.variants.engine.stats.stop_loss).toBe(3)
    expect(fake.calls.find(c => c.path === '/trading/engine/replay').query).toEqual({ start: '2018-11-12', end: '2024-09-30', stop_loss_pct: '0' })
  })
  it('POST /sim/run → 200，body 原樣轉給 FastAPI /trading/sim，capital 預設 100 萬', async () => {
    const text = '2024-01-15 買 2330 10股\n2024-06-03 賣 2330 全部'
    const r = await request(app).post('/sim/run').send({ text, start: '2024-01-02', end: '2024-09-30' })
    expect(r.status).toBe(200)
    expect(r.body).toMatchObject({ available: true, start: '2024-01-02', end: '2024-09-30', capital: 1000000, n_instructions: 2 })
    const call = fake.calls.find(c => c.path === '/trading/sim')
    expect(call.method).toBe('POST')
    expect(call.body).toEqual({ text, start: '2024-01-02', end: '2024-09-30', capital: 1000000 })
  })
})

describe('條件規則 /sim/rules（Iteration 61）', () => {
  it('匿名 POST → 200，rules 原樣轉；空陣列與超過 50 條 400', async () => {
    const rules = [{ stock_id: '2330', when: { type: 'cross_below_ma', n: 20 }, then: { side: 'sell', unit: '全部' } }]
    const r = await request(app).post('/sim/rules').send({ rules, start: '2024-01-02', end: '2024-09-30' })
    expect(r.status).toBe(200)
    expect(r.body).toMatchObject({ available: true, n_rules: 1, capital: 1000000 })
    expect(fake.calls.find(c => c.path === '/trading/sim/rules').body.rules).toEqual(rules)
    expect((await request(app).post('/sim/rules').send({ rules: [], start: '2024-01-02', end: '2024-09-30' })).status).toBe(400)
    expect((await request(app).post('/sim/rules').send({ rules: Array(51).fill(rules[0]), start: '2024-01-02', end: '2024-09-30' })).status).toBe(400)
  })
})

describe('資料來源 source／seed（Iteration 75）', () => {
  it('有給才轉：synthetic + seed 原樣進 body；沒給就不帶', async () => {
    const text = '2022-01-03 買 2330 10股'
    const r = await request(app).post('/sim/run').send({ text, start: '2022-01-01', end: '2022-03-31', source: 'synthetic', seed: 9 })
    expect(r.status).toBe(200)
    expect(r.body.source).toEqual({ kind: 'synthetic', seed: 9 })
    const call = fake.calls.filter(c => c.path === '/trading/sim').pop()
    expect(call.body).toEqual({ text, start: '2022-01-01', end: '2022-03-31', capital: 1000000, source: 'synthetic', seed: 9 })
    const rules = [{ stock_id: '2330', when: { type: 'price_above', x: 1 }, then: { side: 'buy', qty: 1, unit: '股' } }]
    const r2 = await request(app).post('/sim/rules').send({ rules, start: '2022-01-01', end: '2022-03-31', source: 'synthetic', seed: '12' })
    expect(r2.status).toBe(200)
    expect(fake.calls.filter(c => c.path === '/trading/sim/rules').pop().body).toMatchObject({ source: 'synthetic', seed: 12 })
    const r3 = await request(app).post('/sim/rules').send({ rules, start: '2022-01-01', end: '2022-03-31' })
    expect(r3.status).toBe(200)
    expect(fake.calls.filter(c => c.path === '/trading/sim/rules').pop().body).toEqual({ rules, start: '2022-01-01', end: '2022-03-31', capital: 1000000 })
  })
  it.each([
    [{ source: 'fake' }, 'source'],
    [{ source: 'synthetic', seed: -1 }, 'seed'],
    [{ source: 'synthetic', seed: 1.5 }, 'seed'],
    [{ seed: 1e10 }, 'seed'],
  ])('%j → 400', async (extra, word) => {
    const r = await request(app).post('/sim/run').send({ text: '2022-01-03 買 2330 10股', start: '2022-01-01', end: '2022-03-31', ...extra })
    expect(r.status).toBe(400)
    expect(r.body.detail).toContain(word)
  })
})

describe('參數驗證（不打 FastAPI）', () => {
  it.each([
    [{ start: '2024-01-02', end: '2024-09-30' }, 'text'],
    [{ text: 'x'.repeat(4001), start: '2024-01-02', end: '2024-09-30' }, '4000'],
    [{ text: '2024-01-15 買 2330 1股', start: '2024/01/02', end: '2024-09-30' }, 'YYYY-MM-DD'],
    [{ text: '2024-01-15 買 2330 1股', start: '2024-01-02', end: '2024-09-30', capital: -1 }, 'capital'],
  ])('%j → 400', async (body, word) => {
    const r = await request(app).post('/sim/run').send(body)
    expect(r.status).toBe(400)
    expect(r.body.detail).toContain(word)
  })
})

describe('策略範本 /sim/presets 與 /sim/compare（Iteration 79）', () => {
  it('GET /sim/presets → 200，只轉 stock／start／capital 三個參數', async () => {
    const r = await request(app).get('/sim/presets?stock=2454&start=2024-01-02&capital=500000&junk=1')
    expect(r.status).toBe(200)
    expect(r.body.presets[0].key).toBe('buyhold')
    expect(fake.calls.find(c => c.path === '/trading/sim/presets').query).toEqual({ stock: '2454', start: '2024-01-02', capital: '500000' })
  })
  it('POST /sim/compare → 200，stock_id 轉大寫、capital 預設 100 萬、source 有給才轉；代號／日期／來源壞掉 400', async () => {
    const r = await request(app).post('/sim/compare').send({ stock_id: ' 00878 ', start: '2024-01-02', end: '2024-09-30', source: 'synthetic', seed: 3 })
    expect(r.status).toBe(200)
    expect(r.body).toMatchObject({ available: true, stock_id: '00878', n_presets: 1, source: { kind: 'synthetic', seed: 3 } })
    expect(fake.calls.find(c => c.path === '/trading/sim/presets/compare').body).toEqual({ stock_id: '00878', start: '2024-01-02', end: '2024-09-30', capital: 1000000, source: 'synthetic', seed: 3 })
    expect((await request(app).post('/sim/compare').send({ stock_id: '23', start: '2024-01-02', end: '2024-09-30' })).status).toBe(400)
    expect((await request(app).post('/sim/compare').send({ stock_id: '2330', start: '2024/01/02', end: '2024-09-30' })).status).toBe(400)
    expect((await request(app).post('/sim/compare').send({ stock_id: '2330', start: '2024-01-02', end: '2024-09-30', source: 'fake' })).status).toBe(400)
  })
})
