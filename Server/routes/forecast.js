/**
 * 每週自動預測路由（Iteration 37）
 * 代理至 Crawler FastAPI（localhost:8000）
 *
 * GET  /forecast/weekly         最新一次執行：每檔一列，LSTM 兩週摘要 + 各模型
 * GET  /forecast/weekly/status  是否正在執行、下次排程時間
 * POST /forecast/weekly/run     手動補跑（平常不需要；排程每週日 08:00 自動跑）
 */
const { Router } = require('express')
const { proxyToFastAPI } = require('../lib/proxy')

const router = Router()

const onError = (res) => () => res.status(503).json({
  detail: '爬蟲服務未啟動（FastAPI :8000）。請執行 cd Crawler && python main.py --mode server',
})

router.get('/weekly', (_req, res) => {
  proxyToFastAPI({ port: 8000, path: '/forecast/weekly', res, onError: onError(res) })
})

router.get('/weekly/status', (_req, res) => {
  proxyToFastAPI({ port: 8000, path: '/forecast/weekly/status', res, onError: onError(res) })
})

router.post('/weekly/run', (_req, res) => {
  proxyToFastAPI({ port: 8000, path: '/forecast/weekly/run', method: 'POST', body: {}, res, onError: onError(res) })
})

module.exports = router
