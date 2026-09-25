/**
 * 模型目錄路由（Iteration 31）
 *
 * GET /catalog?page=voting&selectable_only=true
 *
 * 全部轉給 FastAPI：目錄本身定義在 Crawler/model_catalog.py，
 * 那裡才知道每個模型用了哪些資料區塊與走查結果。
 *
 * 這支是前端「哪些模型可用、預設開哪些、可信度如何」的唯一來源。
 * Iteration 31 之前這件事散在四個地方各說各話。
 */
const { Router } = require('express')
const { proxyToFastAPI } = require('../lib/proxy')

const router = Router()

router.get('/', (req, res) => {
  const qs = new URLSearchParams({
    ...(req.query.page ? { page: req.query.page } : {}),
    ...(req.query.selectable_only ? { selectable_only: req.query.selectable_only } : {}),
  }).toString()
  proxyToFastAPI({
    path: `/catalog${qs ? `?${qs}` : ''}`, res,
    onError: () => res.status(503).json({
      detail: '爬蟲服務未啟動（FastAPI :8000）。請執行 cd Crawler && python main.py --mode server',
    }),
  })
})

module.exports = router
