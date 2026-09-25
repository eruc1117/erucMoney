/**
 * 爬蟲相關路由（Proxy → FastAPI :8000）
 *
 * POST /crawler/run          觸發爬蟲（近期 or 歷史補充）
 * GET  /crawler/status/:id   查詢爬蟲執行狀態
 */
const { Router } = require('express')
const { proxyToFastAPI } = require('../lib/proxy')

const router = Router()

// ── 觸發爬蟲 ────────────────────────────────────────────────────────────────
// Body: { stock_id, start_date?, end_date? }
router.post('/run', (req, res) => {
  proxyToFastAPI({
    path:   '/crawler/run',
    method: 'POST',
    body:   req.body,
    res,
  })
})

// ── 查詢爬蟲狀態 ─────────────────────────────────────────────────────────────
// Response: { stock_id, status: "running" | "idle" }
// FastAPI 不可用時回傳 idle（不影響前端 polling 正常結束）
router.get('/status/:stockId', (req, res) => {
  proxyToFastAPI({
    path:    `/crawler/status/${req.params.stockId}`,
    method:  'GET',
    res,
    onError: () => res.json({ stock_id: req.params.stockId, status: 'idle' }),
  })
})

// ── 觸發新聞爬蟲 ─────────────────────────────────────────────────────────────
// POST /crawler/news  → FastAPI /crawler/news
router.post('/news', (req, res) => {
  proxyToFastAPI({ path: '/crawler/news', method: 'POST', body: req.body, res })
})

// ── 查詢新聞爬蟲狀態 ──────────────────────────────────────────────────────────
// GET /crawler/news/status  → FastAPI /crawler/news/status
router.get('/news/status', (req, res) => {
  proxyToFastAPI({
    path:    '/crawler/news/status',
    method:  'GET',
    res,
    onError: () => res.json({ status: 'idle', last_count: 0 }),
  })
})

module.exports = router
