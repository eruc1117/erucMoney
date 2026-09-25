/**
 * 投票決策路由
 * GET  /voting           取得所有股票最新一筆投票結果
 * GET  /voting/:id       取得單一股票歷史投票（最近 30 筆）
 * POST /voting/run       觸發投票（proxy → FastAPI）
 * GET  /voting/status    查詢投票執行狀態（proxy → FastAPI）
 * GET  /voting/roles      角色化決策（proxy → FastAPI）
 * GET  /voting/weekly-plan 本週 5 日交易計畫（proxy → FastAPI）
 */
const { Router } = require('express')
const db = require('../db')
const { proxyToFastAPI } = require('../lib/proxy')

const router = Router()

router.get('/', async (_req, res) => {
  try {
    const { rows } = await db.query(`
      SELECT DISTINCT ON (stock_id)
        id, stock_id, vote_date, m1_signal, m2_signal, m3_signal,
        final_signal, score, weights, m1_reason, m2_reason, m3_reason,
        m2_features, created_at,
        predicted_vol, vol_regime, stop_pct, position_pct, risk_reason,
        roles, final_action, target_position_pct, decision_path, holding_snapshot
      FROM voting_results
      ORDER BY stock_id, vote_date DESC
    `)
    res.json(rows)
  } catch (e) {
    res.status(500).json({ detail: e.message })
  }
})

router.get('/status', (req, res) => {
  proxyToFastAPI({
    path: '/voting/status', method: 'GET', res,
    onError: () => res.json({ status: 'idle', last_count: 0 }),
  })
})

router.post('/run', (req, res) => {
  proxyToFastAPI({ path: '/voting/run', method: 'POST', body: req.body, res })
})

// 具名路由必須排在 /:stockId 之前，否則 'roles' 會被當成股票代號吃掉
router.get('/roles', (req, res) => {
  const sid = req.query.stock_id
  if (!sid) return res.status(400).json({ detail: 'stock_id 為必填' })
  // models 是使用者勾選的模型目錄鍵（Iteration 31）。不帶就用後端預設集合
  const qs = new URLSearchParams({
    stock_id: sid, ...(req.query.models ? { models: req.query.models } : {}),
  }).toString()
  proxyToFastAPI({
    path: `/voting/roles?${qs}`, res,
    onError: () => res.status(503).json({ detail: '爬蟲服務未啟動（FastAPI :8000）' }),
  })
})

router.get('/weekly-plan', (req, res) => {
  const sid = req.query.stock_id
  if (!sid) return res.status(400).json({ detail: 'stock_id 為必填' })
  proxyToFastAPI({
    path: `/voting/weekly-plan?stock_id=${encodeURIComponent(sid)}`, res,
    onError: () => res.status(503).json({ detail: '爬蟲服務未啟動（FastAPI :8000）' }),
  })
})

router.get('/:stockId', async (req, res) => {
  try {
    const { rows } = await db.query(`
      SELECT id, stock_id, vote_date, m1_signal, m2_signal, m3_signal,
             final_signal, score, weights, m1_reason, m2_reason, m3_reason, created_at
      FROM voting_results
      WHERE stock_id = $1
      ORDER BY vote_date DESC
      LIMIT 30
    `, [req.params.stockId])
    res.json(rows)
  } catch (e) {
    res.status(500).json({ detail: e.message })
  }
})

module.exports = router
