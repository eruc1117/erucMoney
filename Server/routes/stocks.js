/**
 * 股票相關路由
 *
 * GET /stocks/industries                        產業類別清單（含各類股票數）
 * GET /stocks/:id                               個股基本資訊 + 最新行情 + 最新籌碼
 * GET /stocks?tracked=true[&industry=X]         追蹤中股票清單，可依產業篩選
 * GET /stocks?max_price=N[&industry=X]          依預算篩選可買股票，可依產業篩選
 * GET /stocks/:id/prices?days=N                 最近 N 天行情（預設 90，上限 365）
 * GET /stocks/:id/prices?start_date=&end_date=  指定日期區間行情（無上限）
 * GET /stocks/:id/prices                        資料庫全部歷史行情
 * GET /stocks/:id/chips?days=N                  最近 N 天三大法人籌碼（預設 20，上限 365）
 * GET /stocks/:id/institutional?days=N          三大法人持股變化：每日買賣超 + 期間累計 + 外資真實持股 + 收盤價（預設 60，上限 1825）
 *
 * 日期：db.js 已把 DATE 型別設成原樣回傳字串，這裡不再 toISOString()——
 * 那個寫法在台北時區會讓每個日期少一天（Iteration 35 修正）。
 */
const { Router } = require('express')
const db = require('../db')

const router = Router()

const log500 = (endpoint, id, err) =>
  console.error(`[500] ${endpoint}${id ? ` (${id})` : ''} → ${err.message}`)

// ── 產業類別清單（含各類股票數）─────────────────────────────────────────────
// 注意：此路由必須在 /:id 之前，否則 'industries' 會被當成股票代碼
router.get('/industries', async (req, res) => {
  try {
    const { rows } = await db.query(`
      SELECT industry_type, COUNT(*)::int AS stock_count
      FROM stock_info
      WHERE industry_type IS NOT NULL AND industry_type <> ''
      GROUP BY industry_type
      ORDER BY stock_count DESC, industry_type ASC
    `)
    res.json(rows)
  } catch (e) {
    log500('GET /stocks/industries', null, e)
    res.status(500).json({ detail: e.message })
  }
})

// ── 個股基本資訊 + 最新行情 + 最新籌碼 ──────────────────────────────────────
router.get('/:id', async (req, res) => {
  try {
    const { rows } = await db.query(`
      SELECT
        i.stock_id, i.stock_name, i.market_type, i.industry_type,
        p.close_price, p.change_value, p.change_rate,
        p.volume, p.turnover_value,
        c.total_net_buy, h.foreign_ratio AS foreign_holding_ratio,
        -- 持股統計偶爾比行情晚一天揭露，把日期一起給前端，讓畫面能標出來
        h.trade_date AS foreign_holding_date, p.trade_date
      FROM stock_info i
      LEFT JOIN LATERAL (
        SELECT trade_date, close_price, change_value, change_rate, volume, turnover_value
        FROM stock_daily_prices
        WHERE stock_id = i.stock_id
        ORDER BY trade_date DESC LIMIT 1
      ) p ON TRUE
      LEFT JOIN LATERAL (
        SELECT total_net_buy
        FROM stock_chip_analysis
        WHERE stock_id = i.stock_id
        ORDER BY trade_date DESC LIMIT 1
      ) c ON TRUE
      -- 外資持股比例改自 stock_foreign_holding（Iteration 35）；chip 表那欄從未寫入
      LEFT JOIN LATERAL (
        SELECT foreign_ratio, trade_date
        FROM stock_foreign_holding
        WHERE stock_id = i.stock_id
        ORDER BY trade_date DESC LIMIT 1
      ) h ON TRUE
      WHERE i.stock_id = $1
    `, [req.params.id])

    if (!rows.length) return res.status(404).json({ detail: '股票不存在' })
    res.json(rows[0])
  } catch (e) {
    log500('GET /stocks/:id', req.params.id, e)
    res.status(500).json({ detail: e.message })
  }
})

// ── 追蹤中股票 / 依預算篩選 ─────────────────────────────────────────────────
router.get('/', async (req, res) => {
  try {
    const { max_price, tracked, industry } = req.query

    if (tracked === 'true') {
      const params = []
      if (industry) params.push(industry)
      const industryClause = industry ? `AND i.industry_type = $${params.length}` : ''

      const { rows } = await db.query(`
        SELECT
          i.stock_id, i.stock_name, i.market_type, i.industry_type,
          p.trade_date,
          p.close_price, p.change_value, p.change_rate,
          p.volume, p.turnover_value,
          c.total_net_buy, h.foreign_ratio AS foreign_holding_ratio,
          h.trade_date AS foreign_holding_date
        FROM stock_info i
        LEFT JOIN LATERAL (
          SELECT trade_date, close_price, change_value, change_rate, volume, turnover_value
          FROM stock_daily_prices
          WHERE stock_id = i.stock_id
          ORDER BY trade_date DESC LIMIT 1
        ) p ON TRUE
        LEFT JOIN LATERAL (
          SELECT total_net_buy
          FROM stock_chip_analysis
          WHERE stock_id = i.stock_id
          ORDER BY trade_date DESC LIMIT 1
        ) c ON TRUE
        LEFT JOIN LATERAL (
          SELECT foreign_ratio, trade_date
          FROM stock_foreign_holding
          WHERE stock_id = i.stock_id
          ORDER BY trade_date DESC LIMIT 1
        ) h ON TRUE
        WHERE i.is_tracking = TRUE ${industryClause}
        ORDER BY p.volume DESC NULLS LAST
      `, params)

      return res.json(rows)
    }

    if (!max_price) return res.status(400).json({ detail: 'max_price 為必填參數' })

    const params = [Number(max_price)]
    if (industry) params.push(industry)
    const industryClause = industry ? `AND i.industry_type = $${params.length}` : ''

    const { rows } = await db.query(`
      SELECT
        i.stock_id, i.stock_name, i.industry_type,
        p.close_price, p.change_rate, p.volume
      FROM stock_info i
      JOIN LATERAL (
        SELECT close_price, change_rate, volume
        FROM stock_daily_prices
        WHERE stock_id = i.stock_id
          AND close_price IS NOT NULL
        ORDER BY trade_date DESC LIMIT 1
      ) p ON p.close_price <= $1
      WHERE TRUE ${industryClause}
      ORDER BY p.close_price DESC
    `, params)

    res.json(rows)
  } catch (e) {
    log500('GET /stocks', null, e)
    res.status(500).json({ detail: e.message })
  }
})

// ── 每日行情（K線 / 歷史區間）────────────────────────────────────────────────
// 優先順序：start_date + end_date > days > 無參數（全部）
router.get('/:id/prices', async (req, res) => {
  try {
    const { days, start_date, end_date } = req.query
    const formatRows = rows => rows   // DATE 已是 'YYYY-MM-DD' 字串（見 db.js）

    const COLS = `
      SELECT trade_date, open_price, high_price, low_price,
             close_price, volume, change_value, change_rate
      FROM stock_daily_prices`

    if (start_date && end_date) {
      const { rows } = await db.query(`
        ${COLS}
        WHERE stock_id = $1
          AND trade_date BETWEEN $2::date AND $3::date
        ORDER BY trade_date ASC
      `, [req.params.id, start_date, end_date])
      return res.json(formatRows(rows))
    }

    if (days) {
      const d = Math.min(Math.max(Number(days), 1), 365)
      const { rows } = await db.query(`
        ${COLS}
        WHERE stock_id = $1
          AND trade_date >= CURRENT_DATE - ($2::int)
        ORDER BY trade_date ASC
      `, [req.params.id, d])
      return res.json(formatRows(rows))
    }

    // 無參數 → 全部歷史資料
    const { rows } = await db.query(`
      ${COLS}
      WHERE stock_id = $1
      ORDER BY trade_date ASC
    `, [req.params.id])
    res.json(formatRows(rows))
  } catch (e) {
    log500('GET /stocks/:id/prices', req.params.id, e)
    res.status(500).json({ detail: e.message })
  }
})

// ── 三大法人籌碼 ───────────────────────────────────────────────────────────
router.get('/:id/chips', async (req, res) => {
  try {
    const days = Math.min(Math.max(Number(req.query.days) || 20, 1), 365)
    const { rows } = await db.query(`
      SELECT trade_date, foreign_investor_buy, investment_trust_buy,
             dealer_buy, total_net_buy
      FROM stock_chip_analysis
      WHERE stock_id = $1
        AND trade_date >= CURRENT_DATE - ($2::int)
      ORDER BY trade_date ASC
    `, [req.params.id, days])

    res.json(rows)
  } catch (e) {
    log500('GET /stocks/:id/chips', req.params.id, e)
    res.status(500).json({ detail: e.message })
  }
})

// ── 三大法人持股變化 ───────────────────────────────────────────────────────
// 兩種資料，意義不同，要分開講：
//   · stock_chip_analysis：每日買賣超。「持股變化」＝期間內買賣超的累計，
//     第一天起算，累計線往上是加碼、往下是減碼。三大法人都有。
//   · stock_foreign_holding：外資**真實持股**（股數與佔比），Iteration 35 接入。
//     只有外資有這份每日揭露；投信、自營商沒有，所以它們只能看累計。
// 單位：FinMind 回的是「股」，這裡照原樣回傳，前端再換算成張（÷1000）顯示。
// 收盤價一併回傳，畫面把價格疊在累計線上，才看得出「法人買、股價卻沒漲」這類背離。
router.get('/:id/institutional', async (req, res) => {
  try {
    const days = Math.min(Math.max(Number(req.query.days) || 60, 1), 1825)
    const { rows: info } = await db.query(
      'SELECT stock_id, stock_name, industry_type FROM stock_info WHERE stock_id = $1',
      [req.params.id],
    )
    if (!info.length) return res.status(404).json({ detail: `股票 ${req.params.id} 不在資料庫中` })

    const { rows } = await db.query(`
      WITH c AS (
        SELECT trade_date,
               COALESCE(foreign_investor_buy, 0) AS foreign_net,
               COALESCE(investment_trust_buy, 0) AS trust_net,
               COALESCE(dealer_buy, 0)           AS dealer_net,
               COALESCE(total_net_buy, 0)        AS total_net
        FROM stock_chip_analysis
        WHERE stock_id = $1
          AND trade_date >= CURRENT_DATE - ($2::int)
      )
      SELECT c.trade_date,
             c.foreign_net, c.trust_net, c.dealer_net, c.total_net,
             SUM(c.foreign_net) OVER w AS cum_foreign,
             SUM(c.trust_net)   OVER w AS cum_trust,
             SUM(c.dealer_net)  OVER w AS cum_dealer,
             SUM(c.total_net)   OVER w AS cum_total,
             p.close_price, p.change_rate,
             h.foreign_shares, h.foreign_ratio, h.shares_issued
      FROM c
      LEFT JOIN stock_daily_prices p
        ON p.stock_id = $1 AND p.trade_date = c.trade_date
      LEFT JOIN stock_foreign_holding h
        ON h.stock_id = $1 AND h.trade_date = c.trade_date
      WINDOW w AS (ORDER BY c.trade_date ROWS UNBOUNDED PRECEDING)
      ORDER BY c.trade_date ASC
    `, [req.params.id, days])

    const num = v => (v === null || v === undefined ? null : Number(v))
    const series = rows.map(r => ({
      trade_date:  r.trade_date,
      foreign_net: num(r.foreign_net),
      trust_net:   num(r.trust_net),
      dealer_net:  num(r.dealer_net),
      total_net:   num(r.total_net),
      cum_foreign: num(r.cum_foreign),
      cum_trust:   num(r.cum_trust),
      cum_dealer:  num(r.cum_dealer),
      cum_total:   num(r.cum_total),
      close_price: num(r.close_price),
      change_rate: num(r.change_rate),
      foreign_shares: num(r.foreign_shares),
      foreign_ratio:  num(r.foreign_ratio),
      shares_issued:  num(r.shares_issued),
    }))

    const last = series[series.length - 1] || null
    const countBuyDays = key => series.filter(r => r[key] > 0).length
    // 外資真實持股：期間內第一筆與最後一筆有值的列（持股統計偶爾比買賣超晚一天）
    const withHolding = series.filter(r => r.foreign_ratio !== null)
    const hFirst = withHolding[0] || null
    const hLast  = withHolding[withHolding.length - 1] || null
    res.json({
      ...info[0],
      days_requested: days,
      trading_days: series.length,
      start_date: series[0]?.trade_date || null,
      end_date:   last?.trade_date || null,
      summary: last ? {
        foreign: { cum: last.cum_foreign, buy_days: countBuyDays('foreign_net') },
        trust:   { cum: last.cum_trust,   buy_days: countBuyDays('trust_net') },
        dealer:  { cum: last.cum_dealer,  buy_days: countBuyDays('dealer_net') },
        total:   { cum: last.cum_total,   buy_days: countBuyDays('total_net') },
        price_change_pct: (series[0]?.close_price && last.close_price)
          ? (last.close_price / series[0].close_price - 1) * 100 : null,
        foreign_holding: hLast ? {
          start_date:   hFirst.trade_date,
          end_date:     hLast.trade_date,
          start_ratio:  hFirst.foreign_ratio,
          end_ratio:    hLast.foreign_ratio,
          ratio_change: hLast.foreign_ratio - hFirst.foreign_ratio,
          start_shares: hFirst.foreign_shares,
          end_shares:   hLast.foreign_shares,
          shares_change: (hLast.foreign_shares !== null && hFirst.foreign_shares !== null)
            ? hLast.foreign_shares - hFirst.foreign_shares : null,
          shares_issued: hLast.shares_issued,
          days:          withHolding.length,
        } : null,
      } : null,
      series,
    })
  } catch (e) {
    log500('GET /stocks/:id/institutional', req.params.id, e)
    res.status(500).json({ detail: e.message })
  }
})

module.exports = router
