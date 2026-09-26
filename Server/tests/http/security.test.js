/**
 * 安全與設定：helmet 標頭、CORS 白名單、限流、公開端點。
 * 這個檔案自己一個模組登錄（jest 每檔獨立），限流計數不會被別的檔案影響；限流案例放最後。
 */
const request = require('supertest')
const { getApp } = require('../helpers/app')
const { closeDb } = require('../helpers/db')
const { localToken, bearer } = require('../helpers/tokens')

let app
beforeAll(async () => { app = await getApp() })
afterAll(closeDb)

describe('公開與受保護端點', () => {
  it('/health 免登入', async () => {
    const r = await request(app).get('/health')
    expect(r.status).toBe(200)
    expect(r.body.ok).toBe(true)
    expect(r.body.time).toMatch(/^\d{4}-\d{2}-\d{2}T/)
  })
  it('其餘沒 token 一律 401', async () => {
    for (const p of ['/stocks?tracked=true', '/holdings', '/news', '/catalog', '/forecast/weekly', '/voting', '/crawler/status/2330', '/models']) {
      expect((await request(app).get(p)).status).toBe(401)
    }
  })
  it('admin 專用路由對一般使用者 403', async () => {
    const u = bearer(localToken({ id: 2, role: 'user', name: 'u' }))
    for (const p of ['/crawler/status/2330', '/data/freshness', '/models', '/auth/users']) {
      expect((await request(app).get(p).set(u)).status).toBe(403)
    }
  })
})

describe('helmet', () => {
  it('帶安全標頭、不洩漏 X-Powered-By', async () => {
    const r = await request(app).get('/health')
    expect(r.headers['x-content-type-options']).toBe('nosniff')
    expect(r.headers['x-frame-options']).toBeDefined()
    expect(r.headers['x-powered-by']).toBeUndefined()
    expect(r.headers['cross-origin-resource-policy']).toBe('cross-origin')
  })
})

describe('CORS 白名單（ALLOWED_ORIGINS）', () => {
  it('白名單內的 Origin 拿到 access-control-allow-origin', async () => {
    const r = await request(app).get('/health').set('Origin', 'http://allowed.test')
    expect(r.headers['access-control-allow-origin']).toBe('http://allowed.test')
  })
  it('白名單外的 Origin 沒有 CORS 標頭', async () => {
    const r = await request(app).get('/health').set('Origin', 'http://evil.test')
    expect(r.headers['access-control-allow-origin']).toBeUndefined()
  })
  it('preflight 對白名單 Origin 回 204', async () => {
    const r = await request(app).options('/holdings').set('Origin', 'http://allowed.test').set('Access-Control-Request-Method', 'POST')
    expect(r.status).toBe(204)
    expect(r.headers['access-control-allow-origin']).toBe('http://allowed.test')
  })
})

describe('body 大小', () => {
  it('超過 1mb 的 JSON → 413', async () => {
    const big = { platform: 'x', title: 't', content: 'a'.repeat(1_100_000) }
    const r = await request(app).post('/news').set(bearer(localToken())).send(big)
    expect(r.status).toBe(413)
  })
})

describe('限流', () => {
  it('登入 10 次/分鐘：第 11 次 429', async () => {
    let last
    for (let i = 0; i < 11; i++) {
      last = await request(app).post('/auth/login').send({ username: 'nobody', password: 'x' })
    }
    expect(last.status).toBe(429)
    expect(last.body.detail).toMatch(/頻繁/)
    expect(last.headers['ratelimit-limit']).toBeDefined()
  })
  it('全域 RATE_LIMIT_PER_MIN=60：一分鐘內第 61 個請求 429', async () => {
    let hit429 = false
    for (let i = 0; i < 70; i++) {
      const r = await request(app).get('/health')
      if (r.status === 429) { hit429 = true; break }
    }
    expect(hit429).toBe(true)
  })
})
