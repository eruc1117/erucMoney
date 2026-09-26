/**
 * 新聞相關路由
 *
 * GET  /news   取得使用者提交的新聞列表（最新 200 筆）
 * POST /news   儲存使用者貼上的新聞至 user_news 表
 * PUT  /news/:id、DELETE /news/:id   只能動自己的（admin 可動任何一筆）
 */
const { Router } = require('express')
const db = require('../db')

const router = Router()

// 修改／刪除只能動自己的新聞；admin 可以動任何一筆（含爬蟲抓進來、user_id 為空的）。
// 回傳 null 表示可以；否則 { status, detail }。
async function checkOwner(req) {
  const id = Number(req.params.id)
  if (!Number.isInteger(id) || id <= 0) return { status: 400, detail: 'id 格式錯誤' }
  const { rows } = await db.query('SELECT user_id FROM user_news WHERE id = $1', [id])
  if (!rows[0]) return { status: 404, detail: 'not found' }
  if (req.user?.role === 'admin') return null
  if (rows[0].user_id == null || rows[0].user_id !== req.user?.id) return { status: 403, detail: '只能修改或刪除自己提交的新聞' }
  return null
}

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
    const denied = await checkOwner(req)
    if (denied) return res.status(denied.status).json({ detail: denied.detail })
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
    const denied = await checkOwner(req)
    if (denied) return res.status(denied.status).json({ detail: denied.detail })
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
