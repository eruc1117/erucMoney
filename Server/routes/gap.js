/**
 * 開盤跳空預測路由
 * 代理至 Crawler FastAPI（localhost:8000）
 *
 * GET /gap/predict[?stock_ids=2330,2303]
 *
 * 定位是盤前參考資訊，不是買賣訊號 —— 跳空發生在開盤瞬間，事後無法交易。
 */
const { Router } = require('express')
const { proxyToFastAPI } = require('../lib/proxy')

const router = Router()

router.get('/predict', (req, res) => {
  const { stock_ids } = req.query
  const qs = stock_ids ? `?stock_ids=${encodeURIComponent(stock_ids)}` : ''
  proxyToFastAPI({
    port: 8000,
    path: `/gap/predict${qs}`,
    res,
    onError: () => res.status(503).json({
      detail: '爬蟲服務未啟動，請執行 python main.py --mode server',
    }),
  })
})

/**
 * GET /gap/weekly-range[?stock_ids=...][&only_significant=true]
 * 週振幅預測——挑出未來一週高低點差距顯著偏大的股票（波段選股用）。
 * 注意：振幅大不代表會漲，方向仍不可預測。
 */
router.get('/weekly-range', (req, res) => {
  const { stock_ids, only_significant } = req.query
  const params = new URLSearchParams()
  if (stock_ids) params.set('stock_ids', stock_ids)
  if (only_significant) params.set('only_significant', only_significant)
  const qs = params.toString() ? `?${params.toString()}` : ''
  proxyToFastAPI({
    port: 8000,
    path: `/range/weekly${qs}`,
    res,
    onError: () => res.status(503).json({
      detail: '爬蟲服務未啟動，請執行 python main.py --mode server',
    }),
  })
})

module.exports = router
