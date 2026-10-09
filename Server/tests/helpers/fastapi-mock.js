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
  'GET /news/signals':        (req) => ({ status: 200, body: {
    available: true, as_of: '2026-09-24', query: req.query,
    models: { news_event_vol: { serving: true, credibility: 'proven' }, news_drift: { serving: false, credibility: 'none' } },
    results: [{ stock_id: '2330', as_of: '2026-09-24', close: 2475, dims: { ns_has_news: 1, ns_sent: 0.3 },
                event_vol: { range_pct: 1.2, is_elevated: false }, drift: null }],
  } }),
  'GET /news/signals/gates':  ()    => ({ status: 200, body: { models: { news_event_vol: { gates: { deploy: true } } } } }),
  'GET /portfolio/candidate': ()    => ({ status: 200, body: {
    candidates: [
      { id: 30, experiment_n: 30, segment: 'dev', segment_label: '開發期', period_start: '2018-01-01', period_end: '2021-12-30', tag: 'candidate', metrics: { ann_active: 0.0864, info_ratio: 0.67, dsr: 0.377 } },
      { id: 38, experiment_n: 38, segment: 'valid', segment_label: '驗證期', period_start: '2022-01-01', period_end: '2024-09-30', tag: 'candidate', metrics: { ann_active: 0.1571, info_ratio: 1.085, dsr: 0.588 } },
      { id: 44, experiment_n: 44, segment: 'dev', segment_label: '開發期', name: 'win3+mom-t3-tsmcest-dev+valid', period_start: '2018-01-01', period_end: '2024-09-30', tag: 'candidate', metrics: { ann_active: 0.0705, info_ratio: 0.564, dsr: 0.129 } },
    ],
    full: { run: { id: 44, params: { signal: 'win3+mom', tranches: 3, universe_n: 300, top_n: 20, tsmc_weight: 'est' }, metrics: { yearly_active: { 2018: 0.117 } } },
            series: [{ d: '2018-01-12', nav: 1, bench: 1 }, { d: '2024-09-30', nav: 4.6, bench: 2.9 }], positions: [{ stock_id: '2330', rank: null, target_weight: 0.49, filled: true }], last_rebalance: '2024-09-11' },
    n_total: 44, thresholds: { ann_active: 0.03, info_ratio: 0.5, dsr: 0.95, turnover_min: 3, turnover_max: 6 }, holdout_opened: false,
  } }),
  'GET /portfolio/paper':     ()    => ({ status: 200, body: { opened: true, review: { days: 3, port_return: 0.01, bench_return: 0.005, active_return: 0.005, monthly: [] }, trades: [], holdings: [], pending: [] } }),
  'GET /portfolio/runs':      ()    => ({ status: 200, body: { n_total: 2, thresholds: { dsr: 0.95 },
    runs: [{ id: 1, experiment_n: 1, name: 'sue-dev-top20', segment: 'dev', tag: null, metrics: { ann_active: -0.0733 } },
           { id: 2, experiment_n: 2, name: 'win3+mom-t3-tsmcest-dev', segment: 'dev', tag: 'candidate', metrics: { ann_active: 0.0864 } }] } }),
  'GET /portfolio/runs/:id':  (req) => ({ status: 200, body: { run: { id: Number(req.params.id) }, series: [], positions: [], query: req.query } }),
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
