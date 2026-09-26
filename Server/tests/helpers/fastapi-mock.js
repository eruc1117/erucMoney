/**
 * 假的 FastAPI（:8000 的替身）。
 *
 *   const fake = await startFakeFastAPI()   // 隨機埠；並把 process.env.FASTAPI_PORT 指過去
 *   fake.calls                              // [{ method, path, query, body }] 收到的每個請求
 *   fake.respond('GET /data/freshness', (req) => ({ status: 200, body: {...} }))   // 覆寫某條回應
 *   await fake.close()                      // 關掉並清 FASTAPI_PORT
 *
 *   await deadPort()                        // 一個沒人在聽的埠，模擬 FastAPI 掛掉
 */
const express = require('express')
const net = require('net')

const DEFAULTS = {
  'POST /crawler/run':        (req) => ({ status: 200, body: { status: 'started', stock_id: req.body.stock_id } }),
  'GET /crawler/status/:id':  (req) => ({ status: 200, body: { stock_id: req.params.id, status: 'idle' } }),
  'POST /crawler/news':       ()    => ({ status: 200, body: { status: 'started' } }),
  'GET /crawler/news/status': ()    => ({ status: 200, body: { status: 'idle', mode: '', last_count: 0 } }),
  'GET /data/freshness':      (req) => ({ status: 200, body: { available: true, market_last: '2026-09-22', items: [], query: req.query } }),
  'POST /data/backfill':      (req) => ({ status: 200, body: { ok: true, query: req.query } }),
  'GET /data/freshness/exogenous': () => ({ status: 200, body: { available: true, items: [], problems: [] } }),
  'POST /data/backfill/exogenous': () => ({ status: 200, body: { ok: true } }),
  'GET /us/tickers':          ()    => ({ status: 200, body: [
    { ticker: 'TSM', name: '台積電 ADR', category: 'semi', is_tracking: true },
    { ticker: 'SPY', name: 'S&P 500 ETF', category: 'index', is_tracking: true },
  ] }),
  'GET /us/overview':         (req) => ({ status: 200, body: {
    days: Number(req.query.days || 60),
    tickers: [{ ticker: 'TSM', close: 200.5, change_rate: 1.2, last_date: '2026-09-25' }],
    freshness: { last_date: '2026-09-25', days_behind: 1, stale: false },
    gap: { TSM: { predicted_gap_pct: 0.4 } },
  } }),
  'GET /us/gap':              ()    => ({ status: 200, body: { items: [] } }),
}

async function startFakeFastAPI() {
  const app = express()
  app.use(express.json())
  const calls = []
  const handlers = { ...DEFAULTS }
  app.use((req, res) => {
    calls.push({ method: req.method, path: req.path, query: { ...req.query }, body: req.body })
    for (const key of Object.keys(handlers)) {
      const [m, pattern] = key.split(' ')
      if (m !== req.method) continue
      const re = new RegExp('^' + pattern.replace(/:[^/]+/g, '([^/]+)') + '$')
      const match = re.exec(req.path)
      if (!match) continue
      req.params = { id: match[1] }
      const out = handlers[key](req)
      if (typeof out.body === 'string') return res.status(out.status).type('text').send(out.body)
      return res.status(out.status).json(out.body)
    }
    res.status(404).json({ detail: `fake fastapi: no handler for ${req.method} ${req.path}` })
  })
  const server = await new Promise(resolve => { const s = app.listen(0, '127.0.0.1', () => resolve(s)) })
  const port = server.address().port
  process.env.FASTAPI_HOST = '127.0.0.1'
  process.env.FASTAPI_PORT = String(port)
  return {
    port, calls,
    respond(key, fn) { handlers[key] = fn },
    close: () => new Promise(resolve => {
      delete process.env.FASTAPI_PORT
      delete process.env.FASTAPI_HOST
      server.close(() => resolve())
    }),
  }
}

/** 找一個閒置埠並把 FASTAPI_PORT 指過去（沒人在聽 → 連線被拒 → 路由走 onError） */
async function deadPort() {
  const port = await new Promise(resolve => {
    const s = net.createServer()
    s.listen(0, '127.0.0.1', () => { const p = s.address().port; s.close(() => resolve(p)) })
  })
  process.env.FASTAPI_HOST = '127.0.0.1'
  process.env.FASTAPI_PORT = String(port)
  return port
}

module.exports = { startFakeFastAPI, deadPort }
