/**
 * 美股路由（Iteration 32）
 * 代理至 Crawler FastAPI（localhost:8000）
 *
 * GET /us/overview[?days=60]  全部標的最新報價 + 下一場開盤跳空預測 + 資料新鮮度
 * GET /us/gap[?tickers=TSM,SPY]
 * GET /us/tickers             標的清單（代號、名稱、分類；Iteration 34 起 23 檔），趨勢預測頁的下拉選單用
 *
 * 這一頁的模型與台股跳空模型方向相反：拿**台股與韓日的當日盤**預測美股當晚開盤。
 * 只用美股自身歷史時走查相關僅 0.0085 ≈ 0，訊號全部來自亞洲時區。
 */
const { Router } = require('express')
const { proxyToFastAPI } = require('../lib/proxy')

const router = Router()

const onError = (res) => () => res.status(503).json({
  detail: '爬蟲服務未啟動（FastAPI :8000）。請執行 cd Crawler && python main.py --mode server',
})

router.get('/overview', (req, res) => {
  const qs = req.query.days ? `?days=${encodeURIComponent(req.query.days)}` : ''
  proxyToFastAPI({ port: 8000, path: `/us/overview${qs}`, res, onError: onError(res) })
})

router.get('/gap', (req, res) => {
  const qs = req.query.tickers ? `?tickers=${encodeURIComponent(req.query.tickers)}` : ''
  proxyToFastAPI({ port: 8000, path: `/us/gap${qs}`, res, onError: onError(res) })
})

router.get('/tickers', (_req, res) => {
  proxyToFastAPI({ port: 8000, path: '/us/tickers', res, onError: onError(res) })
})

module.exports = router
