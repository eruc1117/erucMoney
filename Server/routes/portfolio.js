/**
 * 月調倉實驗日誌（Iteration 51）：代理到 FastAPI
 *
 * GET /portfolio/candidate      目前候選（開發期／驗證期／全期間）、全期間淨值曲線與最後持股
 * GET /portfolio/paper          紙上交易：模擬帳戶、對 0050 檢討、成交、持股
 * GET /portfolio/runs           實驗日誌全部（每一次回測一列，N 只增不減）
 * GET /portfolio/runs/:id       單一 run：指標、參數、淨值曲線、最後持股
 */
const { Router } = require('express')
const { proxyToFastAPI } = require('../lib/proxy')

const router = Router()
const CRAWLER_DOWN = res => res.status(503).json({ detail: '爬蟲服務未啟動，請執行 python main.py --mode server' })

router.get('/candidate', (_req, res) => {
  proxyToFastAPI({ port: 8000, path: '/portfolio/candidate', res, onError: () => CRAWLER_DOWN(res) })
})
router.get('/paper', (_req, res) => {
  proxyToFastAPI({ port: 8000, path: '/portfolio/paper', res, onError: () => CRAWLER_DOWN(res) })
})
router.get('/runs', (_req, res) => {
  proxyToFastAPI({ port: 8000, path: '/portfolio/runs', res, onError: () => CRAWLER_DOWN(res) })
})
router.get('/runs/:id', (req, res) => {
  const id = Number(req.params.id)
  if (!Number.isInteger(id) || id <= 0) return res.status(400).json({ detail: 'id 格式錯誤' })
  const step = Number(req.query.step)
  const qs = Number.isInteger(step) && step > 0 ? `?step=${step}` : ''
  proxyToFastAPI({ port: 8000, path: `/portfolio/runs/${id}${qs}`, res, onError: () => CRAWLER_DOWN(res) })
})

module.exports = router
