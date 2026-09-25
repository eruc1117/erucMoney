/**
 * 使用者持股路由（Iteration 22；階段 1 起每筆 SQL 以 req.user.id 隔離）
 *
 * GET    /holdings         全部持股 + 最新市價、浮動損益
 * POST   /holdings         新增或更新一檔（同一 stock_id 視為更新）
 * PUT    /holdings/:id     修改
 * DELETE /holdings/:id     刪除
 *
 * 市值與損益一律以 `close_price`（未還原）計算——使用者手上的成本是實際
 * 付出的錢，要與同樣未還原的市價相比才是真實損益。
 * 這與模型評估用 adj_close 是兩件事：模型算的是報酬率，這裡算的是帳面金額。
 */
const { Router } = require('express')
const db = require('../db')
const ledger = require('../lib/tradeLedger')

const router = Router()

const WITH_MARKET = `
  SELECT h.id, h.stock_id, h.shares, h.avg_cost, h.note,
         h.created_at, h.updated_at, h.source, h.realized_pnl,
         (SELECT COUNT(*) FROM user_trades t WHERE t.stock_id = h.stock_id AND t.user_id = h.user_id) AS trade_count,
         si.stock_name, si.industry_type,
         p.close_price      AS last_price,
         p.trade_date       AS price_date,
         (h.shares * h.avg_cost)                        AS cost_value,
         (h.shares * p.close_price)                     AS market_value,
         (h.shares * (p.close_price - h.avg_cost))      AS unrealized_pnl,
         CASE WHEN h.avg_cost > 0
              THEN (p.close_price - h.avg_cost) / h.avg_cost * 100 END AS unrealized_pct
    FROM user_holdings h
    LEFT JOIN stock_info si ON si.stock_id = h.stock_id
    LEFT JOIN LATERAL (
      SELECT close_price, trade_date FROM stock_daily_prices
       WHERE stock_id = h.stock_id AND close_price > 0
       ORDER BY trade_date DESC LIMIT 1
    ) p ON TRUE
`

router.get('/', async (req, res) => {
  try {
    const { rows } = await db.query(`${WITH_MARKET} WHERE h.user_id = $1 ORDER BY h.stock_id`, [req.user.id])
    const num = v => (v == null ? null : Number(v))
    const items = rows.map(r => ({
      ...r,
      shares: num(r.shares), avg_cost: num(r.avg_cost), last_price: num(r.last_price),
      cost_value: num(r.cost_value), market_value: num(r.market_value),
      unrealized_pnl: num(r.unrealized_pnl), unrealized_pct: num(r.unrealized_pct),
      realized_pnl: num(r.realized_pnl), trade_count: Number(r.trade_count ?? 0),
    }))
    const totalCost = items.reduce((s, r) => s + (r.cost_value ?? 0), 0)
    const totalValue = items.reduce((s, r) => s + (r.market_value ?? r.cost_value ?? 0), 0)

    // 已實現損益必須從台帳撈，不能只看 user_holdings——
    // 已全部出清的股票不會留在持倉表裡，但它賺賠的錢是真的
    const { rows: realizedRows } = await db.query(
      `SELECT COALESCE(SUM(realized_pnl), 0) AS total,
              COUNT(*) FILTER (WHERE side = 'Sell') AS sells,
              COUNT(*) AS trades
         FROM user_trades WHERE user_id = $1`, [req.user.id])
    const realized = Number(realizedRows[0]?.total ?? 0)

    res.json({
      items,
      summary: {
        count: items.length,
        total_cost: +totalCost.toFixed(2),
        total_value: +totalValue.toFixed(2),
        unrealized_pnl: +(totalValue - totalCost).toFixed(2),
        unrealized_pct: totalCost > 0
          ? +(((totalValue - totalCost) / totalCost) * 100).toFixed(2) : null,
        realized_pnl: +realized.toFixed(2),
        total_pnl: +(realized + totalValue - totalCost).toFixed(2),
        trade_count: Number(realizedRows[0]?.trades ?? 0),
        sell_count: Number(realizedRows[0]?.sells ?? 0),
        // 集中度：最大單一持股佔比。過高時「持倉管家」角色會示警。
        max_weight_pct: totalValue > 0
          ? +(Math.max(0, ...items.map(r => (r.market_value ?? 0))) / totalValue * 100).toFixed(1)
          : null,
      },
    })
  } catch (e) {
    console.error('[GET /holdings]', e.message)
    res.status(500).json({ detail: e.message })
  }
})

// ── 交易紀錄 ──────────────────────────────────────────────────────────────────
// GET  /holdings/trades[?stock_id=]   台帳（新到舊）
// POST /holdings/trades               新增一筆並回放
// DELETE /holdings/trades/:id         刪除一筆並回放
// GET  /holdings/trades/estimate      依台股費率試算手續費與證交稅

router.get('/trades/estimate', (req, res) => {
  const { side = 'Buy', shares, price } = req.query
  if (!(Number(shares) > 0) || !(Number(price) > 0))
    return res.status(400).json({ detail: 'shares 與 price 須大於 0' })
  res.json({
    ...ledger.estimateCosts(side, shares, price),
    note: `手續費 ${(ledger.FEE_RATE * 100).toFixed(4)}%（最低 ${ledger.FEE_MIN} 元）`
          + (side === 'Sell' ? `、證交稅 ${(ledger.TAX_RATE * 100).toFixed(1)}%` : '')
          + '；這是預設值，實際費率依券商折扣可覆寫',
  })
})

// ── 建議 vs 實際（Iteration 24）────────────────────────────────────────────
// 系統當天建議什麼（voting_results）、使用者實際做了什麼（user_trades），
// 這兩件事一直各自躺在資料庫裡沒被放在一起看過。
//
// 對照的意義不在「使用者有沒有聽話」，而在**兩邊都要被檢驗**：
// 聽了建議結果變差，是模型的問題；沒聽建議結果更好，也是模型的問題。
// 所以每一筆都會附上事後 5 個交易日的實際報酬。
const REVIEW_SQL = `
  SELECT t.id, t.stock_id, t.trade_date::text AS trade_date, t.side,
         t.shares, t.price, t.note, si.stock_name,
         v.vote_date::text AS vote_date, v.final_signal, v.final_action, v.score,
         (t.trade_date - v.vote_date) AS vote_age_days,
         r.a0, r.a5, r.d5::text AS fwd_date
    FROM user_trades t
    LEFT JOIN stock_info si ON si.stock_id = t.stock_id
    -- 交易當日或之前最近一次的投票建議
    LEFT JOIN LATERAL (
      SELECT vote_date, final_signal, final_action, score
        FROM voting_results
       WHERE stock_id = t.stock_id AND vote_date <= t.trade_date
       ORDER BY vote_date DESC LIMIT 1
    ) v ON TRUE
    -- 事後 5 個交易日的報酬，一律用 adj_close（已還原除權息與減資）
    LEFT JOIN LATERAL (
      SELECT p0.adj_close AS a0, p5.adj_close AS a5, p5.trade_date AS d5
        FROM (SELECT adj_close, trade_date FROM stock_daily_prices
               WHERE stock_id = t.stock_id AND trade_date <= t.trade_date
                 AND adj_close IS NOT NULL
               ORDER BY trade_date DESC LIMIT 1) p0
        LEFT JOIN LATERAL (
          SELECT adj_close, trade_date FROM stock_daily_prices
           WHERE stock_id = t.stock_id AND trade_date > t.trade_date
             AND adj_close IS NOT NULL
           ORDER BY trade_date OFFSET 4 LIMIT 1
        ) p5 ON TRUE
    ) r ON TRUE
   WHERE t.user_id = $1
   ORDER BY t.trade_date DESC, t.id DESC
`

// 建議與動作的一致性。Reduce／NoAdd 也算在賣出側／不加碼側——
// 它們是 Iteration 22 加進來的動作，不能因為不是純 Sell 就當成沒建議。
const BUY_SIDE = new Set(['Buy'])
const SELL_SIDE = new Set(['Sell', 'Reduce'])
const NEUTRAL = new Set(['Hold', 'NoAdd'])

function classify(side, rec) {
  if (!rec) return { key: 'none', label: '當時無建議' }
  if (NEUTRAL.has(rec)) return { key: 'neutral', label: '建議觀望' }
  if (side === 'Buy') {
    if (BUY_SIDE.has(rec)) return { key: 'follow', label: '與建議一致' }
    if (SELL_SIDE.has(rec)) return { key: 'against', label: '與建議相反' }
  } else {
    if (SELL_SIDE.has(rec)) return { key: 'follow', label: '與建議一致' }
    if (BUY_SIDE.has(rec)) return { key: 'against', label: '與建議相反' }
  }
  return { key: 'none', label: '當時無建議' }
}

router.get('/review', async (req, res) => {
  try {
    const { rows } = await db.query(REVIEW_SQL, [req.user.id])
    const num = v => (v == null ? null : Number(v))

    const items = rows.map(r => {
      const a0 = num(r.a0), a5 = num(r.a5)
      const fwd = (a0 && a5) ? +(((a5 - a0) / a0) * 100).toFixed(2) : null
      // 「做對了嗎」對買賣的定義相反：買進之後漲是好的，賣出之後跌才是好的
      const benefit = fwd == null ? null : +(r.side === 'Buy' ? fwd : -fwd).toFixed(2)
      const cls = classify(r.side, r.final_action ?? r.final_signal)
      // 建議超過 7 天沒更新就不該算數——那是舊訊號，不是當天的判斷
      const stale = r.vote_age_days != null && Number(r.vote_age_days) > 7
      return {
        ...r,
        shares: num(r.shares), price: num(r.price), score: num(r.score),
        vote_age_days: r.vote_age_days == null ? null : Number(r.vote_age_days),
        recommendation: stale ? null : (r.final_action ?? r.final_signal),
        stale_vote: stale,
        match: stale ? { key: 'none', label: '建議已過期' } : cls,
        fwd_return_5d: fwd, benefit,
        a0: undefined, a5: undefined,
      }
    })

    // 反向檢查：系統喊買但使用者沒動作的日子
    const { rows: missed } = await db.query(`
      SELECT v.stock_id, v.vote_date::text AS vote_date,
             COALESCE(v.final_action, v.final_signal) AS recommendation
        FROM voting_results v
       WHERE COALESCE(v.final_action, v.final_signal) IN ('Buy', 'Sell', 'Reduce')
         AND NOT EXISTS (
           SELECT 1 FROM user_trades t
            WHERE t.stock_id = v.stock_id AND t.user_id = $1
              AND t.trade_date BETWEEN v.vote_date AND v.vote_date + 3
         )
       ORDER BY v.vote_date DESC LIMIT 50
    `, [req.user.id])

    const withBenefit = items.filter(r => r.benefit != null)
    const agg = key => {
      const g = withBenefit.filter(r => r.match.key === key)
      return {
        n: g.length,
        avg_benefit: g.length
          ? +(g.reduce((s, r) => s + r.benefit, 0) / g.length).toFixed(2) : null,
        win_rate: g.length
          ? +((g.filter(r => r.benefit > 0).length / g.length) * 100).toFixed(1) : null,
      }
    }

    const decided = items.filter(r => ['follow', 'against'].includes(r.match.key))
    res.json({
      items,
      missed,
      summary: {
        trades: items.length,
        matured: withBenefit.length,
        follow: agg('follow'),
        against: agg('against'),
        neutral: agg('neutral'),
        follow_rate: decided.length
          ? +((decided.filter(r => r.match.key === 'follow').length / decided.length) * 100).toFixed(1)
          : null,
        missed_count: missed.length,
      },
      note: '事後報酬為交易日之後 5 個交易日的 adj_close 變動（已還原除權息與減資）；'
            + '買進看漲幅、賣出看跌幅，故「效益」對兩者的定義相反。'
            + '交易筆數少於數十筆時，這裡的任何差異都在雜訊範圍內，'
            + '不足以判斷模型好壞，也不足以判斷使用者的判斷好壞。',
    })
  } catch (e) {
    console.error('[GET /holdings/review]', e.message)
    res.status(500).json({ detail: e.message })
  }
})

router.get('/trades', async (req, res) => {
  const params = [req.user.id]
  let where = 'WHERE t.user_id = $1'
  if (req.query.stock_id) { params.push(req.query.stock_id); where += ' AND t.stock_id = $2' }
  try {
    const { rows } = await db.query(`
      -- trade_date 必須轉字串再送出。node-postgres 會把 DATE 轉成 JS Date
      -- 並在序列化時走 UTC，讓 2026-05-12 在前端顯示成 05-11。
      SELECT t.*, t.trade_date::text AS trade_date, si.stock_name
        FROM user_trades t
        LEFT JOIN stock_info si ON si.stock_id = t.stock_id
       ${where}
       ORDER BY t.trade_date DESC, t.id DESC
    `, params)
    const num = v => (v == null ? null : Number(v))
    res.json(rows.map(r => ({
      ...r,
      shares: num(r.shares), price: num(r.price), fee: num(r.fee), tax: num(r.tax),
      avg_cost_after: num(r.avg_cost_after), shares_after: num(r.shares_after),
      realized_pnl: num(r.realized_pnl),
      gross: +(num(r.shares) * num(r.price)).toFixed(2),
    })))
  } catch (e) {
    console.error('[GET /holdings/trades]', e.message)
    res.status(500).json({ detail: e.message })
  }
})

router.post('/trades', async (req, res) => {
  const { stock_id, trade_date, side, shares, price, fee, tax, note } = req.body ?? {}
  if (!stock_id || !trade_date || !['Buy', 'Sell'].includes(side)
      || !(Number(shares) > 0) || !(Number(price) > 0))
    return res.status(400).json({
      detail: 'stock_id、trade_date、side（Buy/Sell）、shares（>0）、price（>0）為必填' })

  try {
    // 這檔原本是手動快照 → 一旦開始記交易，快照就該讓位給台帳，
    // 否則兩邊會各說各話。先清掉，讓回放重建。
    await db.query(
      `DELETE FROM user_holdings WHERE stock_id = $1 AND user_id = $2 AND source = 'manual'`,
      [String(stock_id).trim(), req.user.id])

    const est = ledger.estimateCosts(side, shares, price)
    await db.query(
      `INSERT INTO user_trades
         (stock_id, trade_date, side, shares, price, fee, tax, note, user_id)
       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)`,
      [String(stock_id).trim(), trade_date, side, Number(shares), Number(price),
       fee != null && fee !== '' ? Number(fee) : est.fee,
       tax != null && tax !== '' ? Number(tax) : est.tax,
       note ?? null, req.user.id])

    const result = await ledger.rebuild(db, String(stock_id).trim(), req.user.id)
    res.status(201).json({ ok: true, ...result, rows: undefined })
  } catch (e) {
    console.error('[POST /holdings/trades]', e.message)
    res.status(500).json({ detail: e.message })
  }
})

router.delete('/trades/:id', async (req, res) => {
  try {
    const { rows } = await db.query(
      'DELETE FROM user_trades WHERE id = $1 AND user_id = $2 RETURNING stock_id', [req.params.id, req.user.id])
    if (rows.length === 0) return res.status(404).json({ detail: '找不到此筆交易' })
    const result = await ledger.rebuild(db, rows[0].stock_id, req.user.id)
    res.json({ ok: true, ...result, rows: undefined })
  } catch (e) {
    console.error('[DELETE /holdings/trades/:id]', e.message)
    res.status(500).json({ detail: e.message })
  }
})

// ── 持倉快照（手動輸入）───────────────────────────────────────────────────────
router.post('/', async (req, res) => {
  const { stock_id, shares, avg_cost, note } = req.body ?? {}
  if (!stock_id || !(Number(shares) > 0) || !(Number(avg_cost) > 0))
    return res.status(400).json({ detail: 'stock_id、shares（>0）、avg_cost（>0）為必填' })

  try {
    // 有交易台帳的股票不接受手動覆寫——台帳是事實，持倉是結論，
    // 允許手改結論就等於允許兩者矛盾
    const { rows: tc } = await db.query(
      'SELECT COUNT(*)::int AS n FROM user_trades WHERE stock_id = $1 AND user_id = $2',
      [String(stock_id).trim(), req.user.id])
    if (tc[0].n > 0)
      return res.status(409).json({
        detail: `${stock_id} 已有 ${tc[0].n} 筆交易紀錄，持倉由台帳自動推導；`
                + '要調整請新增或刪除交易，不要直接改持倉' })

    const { rows } = await db.query(
      `INSERT INTO user_holdings (stock_id, shares, avg_cost, note, user_id)
       VALUES ($1, $2, $3, $4, $5)
       ON CONFLICT (user_id, stock_id) DO UPDATE
         SET shares = EXCLUDED.shares, avg_cost = EXCLUDED.avg_cost,
             note = EXCLUDED.note, updated_at = CURRENT_TIMESTAMP
       RETURNING *`,
      [String(stock_id).trim(), Number(shares), Number(avg_cost), note ?? null, req.user.id])
    res.status(201).json(rows[0])
  } catch (e) {
    console.error('[POST /holdings]', e.message)
    res.status(500).json({ detail: e.message })
  }
})

router.put('/:id', async (req, res) => {
  const { shares, avg_cost, note } = req.body ?? {}
  try {
    const { rows: src } = await db.query(
      'SELECT stock_id, source FROM user_holdings WHERE id = $1 AND user_id = $2', [req.params.id, req.user.id])
    if (src.length && src[0].source === 'trades')
      return res.status(409).json({
        detail: `${src[0].stock_id} 的持倉由交易台帳推導，不能直接編輯；`
                + '請新增或刪除交易紀錄' })

    const { rows } = await db.query(
      `UPDATE user_holdings
          SET shares   = COALESCE($1, shares),
              avg_cost = COALESCE($2, avg_cost),
              note     = COALESCE($3, note),
              updated_at = CURRENT_TIMESTAMP
        WHERE id = $4 AND user_id = $5 RETURNING *`,
      [shares != null ? Number(shares) : null,
       avg_cost != null ? Number(avg_cost) : null, note ?? null, req.params.id, req.user.id])
    if (rows.length === 0) return res.status(404).json({ detail: '找不到此筆持股' })
    res.json(rows[0])
  } catch (e) {
    console.error('[PUT /holdings/:id]', e.message)
    res.status(500).json({ detail: e.message })
  }
})

router.delete('/:id', async (req, res) => {
  try {
    const { rowCount } = await db.query('DELETE FROM user_holdings WHERE id = $1 AND user_id = $2', [req.params.id, req.user.id])
    if (rowCount === 0) return res.status(404).json({ detail: '找不到此筆持股' })
    res.json({ ok: true })
  } catch (e) {
    console.error('[DELETE /holdings/:id]', e.message)
    res.status(500).json({ detail: e.message })
  }
})

module.exports = router
