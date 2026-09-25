/**
 * 新聞相關路由
 *
 * GET  /news   取得使用者提交的新聞列表（最新 200 筆）
 * POST /news   儲存使用者貼上的新聞至 user_news 表
 */
const { Router } = require('express')
const db = require('../db')

const router = Router()

// ── 取得新聞列表 ─────────────────────────────────────────────────────────────
router.get('/', async (_req, res) => {
  try {
    const { rows } = await db.query(`
      SELECT id, platform, title, content, tickers, keywords, submitted_at
      FROM user_news
      ORDER BY submitted_at DESC
      LIMIT 200
    `)
    res.json(rows)
  } catch (e) {
    res.status(500).json({ detail: e.message })
  }
})

// ── 儲存新聞 ─────────────────────────────────────────────────────────────────
// Body: { platform, title, content, stock_tickers }
router.post('/', async (req, res) => {
  try {
    const { platform, title, content, stock_tickers, keywords } = req.body
    const { rows } = await db.query(`
      INSERT INTO user_news (platform, title, content, tickers, keywords, user_id)
      VALUES ($1, $2, $3, $4, $5, $6)
      RETURNING id
    `, [platform, title || '(無標題)', content, stock_tickers || [], keywords || [], req.user?.id ?? null])
    res.json({ source_id: rows[0].id, status: 'saved' })
  } catch (e) {
    res.status(500).json({ detail: e.message })
  }
})

// ── 修改新聞 ─────────────────────────────────────────────────────────────────
// Body: { platform, title, content, stock_tickers }
router.put('/:id', async (req, res) => {
  try {
    const { platform, title, content, stock_tickers, keywords } = req.body
    const { rowCount } = await db.query(`
      UPDATE user_news
      SET platform = $1, title = $2, content = $3, tickers = $4, keywords = $5
      WHERE id = $6
    `, [platform, title || '(無標題)', content, stock_tickers || [], keywords || [], req.params.id])
    if (rowCount === 0) return res.status(404).json({ detail: 'not found' })
    res.json({ status: 'updated' })
  } catch (e) {
    res.status(500).json({ detail: e.message })
  }
})

// ── 刪除新聞 ─────────────────────────────────────────────────────────────────
router.delete('/:id', async (req, res) => {
  try {
    const { rowCount } = await db.query(
      'DELETE FROM user_news WHERE id = $1', [req.params.id]
    )
    if (rowCount === 0) return res.status(404).json({ detail: 'not found' })
    res.json({ status: 'deleted' })
  } catch (e) {
    res.status(500).json({ detail: e.message })
  }
})

module.exports = router
