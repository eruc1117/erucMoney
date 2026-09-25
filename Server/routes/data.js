/**
 * 資料新鮮度路由（Iteration 27）
 *
 * GET  /data/freshness[?stock_ids=a,b]   每檔最後交易日與落後交易日數
 * POST /data/backfill[?stock_ids=&max_stocks=]  把落後的補到最新
 * GET  /data/freshness/exogenous          美股／台指期／韓日指數的最新日期（Iteration 32）
 * POST /data/backfill/exogenous           把上述三張表補到最新（美股趨勢預測與比對用）
 *
 * 實作在 Python 端（爬蟲與 FinMind 都在那裡），這裡只轉發。
 */
const { Router } = require('express')
const { proxyToFastAPI } = require('../lib/proxy')

const router = Router()
const down = res => res.status(503).json({
  detail: '爬蟲服務未啟動（FastAPI :8000）。請執行 cd Crawler && python main.py --mode server',
})

// 外生資料的路由要放在 /freshness 與 /backfill 之前——Express 依註冊順序比對，
// 但這兩條的路徑本來就不會互相吃到；放前面只是讓讀的人一眼看到有兩種。
router.get('/freshness/exogenous', (_req, res) => {
  proxyToFastAPI({ path: '/data/freshness/exogenous', res, onError: () => down(res) })
})

router.post('/backfill/exogenous', (_req, res) => {
  proxyToFastAPI({ path: '/data/backfill/exogenous', method: 'POST',
                   res, onError: () => down(res) })
})

router.get('/freshness', (req, res) => {
  const q = req.query.stock_ids ? `?stock_ids=${encodeURIComponent(req.query.stock_ids)}` : ''
  proxyToFastAPI({ path: `/data/freshness${q}`, res, onError: () => down(res) })
})

router.post('/backfill', (req, res) => {
  const p = new URLSearchParams()
  if (req.query.stock_ids) p.set('stock_ids', req.query.stock_ids)
  if (req.query.max_stocks) p.set('max_stocks', req.query.max_stocks)
  const qs = p.toString()
  proxyToFastAPI({ path: `/data/backfill${qs ? `?${qs}` : ''}`, method: 'POST',
                   res, onError: () => down(res) })
})

module.exports = router
