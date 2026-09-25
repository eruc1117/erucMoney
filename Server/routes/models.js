/**
 * 模型版本管理路由（Iteration 21）
 *
 * GET    /models                         版本清單 + 線上實測指標（proxy → FastAPI :8000）
 * GET    /models/registry                只讀版本清單（不經 FastAPI，供前端在爬蟲服務未啟動時仍可看）
 * POST   /models/:type/freeze            凍結目前的 candidate 為長期服役版本
 * POST   /models/version/:id/serve       切換服役版本
 * POST   /models/version/:id/retire      退役
 * POST   /models/evaluate                回填實際值 + 重算指標（?apply=1 才會執行自動凍結）
 *
 * 凍結需要複製模型檔案，只能由 Python 端執行，故一律 proxy 至 FastAPI。
 * 唯一由 Node 直接查資料庫的是 /models/registry——它不碰檔案，
 * 讓前端在 FastAPI 沒開的時候至少還看得到版本狀態，而不是整頁空白。
 */
const { Router } = require('express')
const db = require('../db')
const { proxyToFastAPI } = require('../lib/proxy')

const router = Router()

const CRAWLER_DOWN = res => res.status(503).json({
  detail: '爬蟲服務未啟動（FastAPI :8000）。請執行 cd Crawler && python main.py --mode server',
})

// ── 只讀版本清單（不依賴 FastAPI）────────────────────────────────────────────
router.get('/registry', async (_req, res) => {
  try {
    const { rows } = await db.query(`
      SELECT v.*,
             (SELECT COUNT(*) FROM model_predictions p
               WHERE p.model_version_id = v.id)                        AS pred_total,
             (SELECT COUNT(*) FROM model_predictions p
               WHERE p.model_version_id = v.id AND p.actual_value IS NOT NULL) AS pred_resolved
        FROM model_versions v
       ORDER BY v.model_type, v.version DESC
    `)
    res.json(rows)
  } catch (e) {
    console.error('[GET /models/registry]', e.message)
    res.status(500).json({ detail: e.message })
  }
})

// ── 版本清單 + 線上指標 ───────────────────────────────────────────────────────
router.get('/', (req, res) => {
  const q = req.query.model_type ? `?model_type=${encodeURIComponent(req.query.model_type)}` : ''
  proxyToFastAPI({ path: `/models${q}`, res, onError: () => CRAWLER_DOWN(res) })
})

// ── 凍結 ──────────────────────────────────────────────────────────────────────
// :type 可能含冒號（lstm:m02_stacked），故用萬用參數
router.post('/:type(*)/freeze', (req, res) => {
  proxyToFastAPI({
    path: `/models/${encodeURIComponent(req.params.type)}/freeze`,
    method: 'POST',
    body: { reason: 'manual', note: req.body?.note ?? null },
    res,
    onError: () => CRAWLER_DOWN(res),
  })
})

// ── 切換服役 / 退役 ───────────────────────────────────────────────────────────
router.post('/version/:id/serve', (req, res) => {
  proxyToFastAPI({
    path: `/models/version/${req.params.id}/serve`, method: 'POST',
    res, onError: () => CRAWLER_DOWN(res),
  })
})

router.post('/version/:id/retire', (req, res) => {
  proxyToFastAPI({
    path: `/models/version/${req.params.id}/retire`, method: 'POST',
    res, onError: () => CRAWLER_DOWN(res),
  })
})

// ── 回填 + 重算（apply=1 才會自動凍結）─────────────────────────────────────────
router.post('/evaluate', (req, res) => {
  const apply = req.query.apply === '1' || req.body?.apply === true
  proxyToFastAPI({
    path: `/models/evaluate?report_only=${apply ? 'false' : 'true'}`,
    method: 'POST',
    res,
    onError: () => CRAWLER_DOWN(res),
  })
})

module.exports = router
