/**
 * 閒置資金配置路由（Iteration 26）
 *
 * GET /cash/plan?amount=&risk_budget=&max_positions=&exclude_held=
 *
 * 全部交給 FastAPI：配置需要振幅、波動率、籌碼三個模型，都在 Python 端。
 */
const { Router } = require('express')
const { proxyToFastAPI } = require('../lib/proxy')

const router = Router()

router.get('/plan', (req, res) => {
  const { amount, risk_budget = 0.02, max_positions = 5, exclude_held = false, models } = req.query
  if (!(Number(amount) > 0))
    return res.status(400).json({ detail: 'amount 必須大於 0' })
  const qs = new URLSearchParams({
    amount, risk_budget, max_positions, exclude_held: String(exclude_held),
    user_id: String(req.user.id),           // 階段 1：排除持股時只看登入者自己的
    ...(models ? { models } : {}),   // 使用者勾選的模型目錄鍵（Iteration 31）
  }).toString()
  proxyToFastAPI({
    path: `/cash/plan?${qs}`, res,
    onError: () => res.status(503).json({
      detail: '爬蟲服務未啟動（FastAPI :8000）。請執行 cd Crawler && python main.py --mode server',
    }),
  })
})

module.exports = router
