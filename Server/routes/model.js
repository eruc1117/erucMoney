/**
 * 模型預測路由
 * 代理至 LSTM 預測伺服器（localhost:8001）
 *
 * GET  /model/predict?stock_id=&model=lstm|prophet|gru&days=7[&market=tw|us]
 * POST /model/retrain  Body: { stock_id }
 */
const { Router } = require('express')
const { proxyToFastAPI } = require('../lib/proxy')

const router = Router()

// ── 模型預測 ─────────────────────────────────────────────────────────────────
router.get('/predict', (req, res) => {
  const { model = 'lstm', days = 7, market = 'tw' } = req.query
  // 代號一律去空白並轉半形數字。貼上時夾帶的一個尾隨空白，
  // 會讓 'ABCD ' 在資料庫查到 0 筆，錯誤訊息卻只說「資料不足」——
  // 那是最難查的一種錯誤：看起來像資料問題，其實是輸入問題。
  const stock_id = String(req.query.stock_id ?? '')
    .trim()
    .replace(/[０-９]/g, c => String.fromCharCode(c.charCodeAt(0) - 0xfee0))
  if (!stock_id) return res.status(400).json({ detail: 'stock_id 為必填' })

  proxyToFastAPI({
    port: 8001,
    path: `/model/predict?stock_id=${encodeURIComponent(stock_id)}&model=${model}&days=${days}`
        + `&market=${encodeURIComponent(market)}`,
    res,
    onError: () => res.status(503).json({ detail: 'LSTM 預測伺服器未啟動，請執行 python serve.py' }),
  })
})

// ── 手動重訓 ─────────────────────────────────────────────────────────────────
router.post('/retrain', (req, res) => {
  proxyToFastAPI({
    port:   8001,
    path:   '/model/retrain',
    method: 'POST',
    body:   req.body,
    res,
    onError: () => res.status(503).json({ detail: 'LSTM 預測伺服器未啟動，請執行 python serve.py' }),
  })
})

module.exports = router
