/**
 * 程式交易（Iteration 57）：候選策略的月清單 → 這個使用者的下單指令 → 執行紀錄
 *
 *   GET /trading/plan?cash=300000&min_trade=1000   下單指令表（清單來自 FastAPI /portfolio/candidate 的 current_list，
 *                                                  持股來自 user_holdings，策略範圍看台帳 note 是否以 [程式交易] 開頭）
 *   GET /trading/log                               用程式交易登記過的交易（台帳裡 note 以 [程式交易] 開頭的）
 *
 * 執行不在這裡：頁面把勾選的指令用既有的 POST /holdings/trades 登記（note = "[程式交易] 清單 YYYY-MM-DD"），
 * 台帳仍是唯一的事實來源；這裡只「算」，不「做」。沒有券商 API——下單是人到券商 App 做，這裡給的是指令與對帳。
 */
const { Router } = require('express')
const db = require('../db')
const { fetchFastAPI } = require('../lib/proxy')
const { buildPlan, nextSignalDate, NOTE_PREFIX } = require('../lib/tradingPlan')

const router = Router()

async function userHoldings(userId) {
  const { rows } = await db.query(`
    SELECT h.stock_id, h.shares, h.avg_cost, si.stock_name, p.close_price AS last_price, p.trade_date::text AS price_date
      FROM user_holdings h
      LEFT JOIN stock_info si ON si.stock_id = h.stock_id
      LEFT JOIN LATERAL (SELECT close_price, trade_date FROM stock_daily_prices
                          WHERE stock_id = h.stock_id AND close_price > 0 ORDER BY trade_date DESC LIMIT 1) p ON TRUE
     WHERE h.user_id = $1 AND h.shares > 0`, [userId])
  return rows.map(r => ({ ...r, shares: Number(r.shares), avg_cost: r.avg_cost == null ? null : Number(r.avg_cost), last_price: r.last_price == null ? null : Number(r.last_price) }))
}

async function managedIds(userId) {
  const { rows } = await db.query(
    `SELECT DISTINCT stock_id FROM user_trades WHERE user_id = $1 AND note LIKE $2`, [userId, `${NOTE_PREFIX}%`])
  return rows.map(r => r.stock_id)
}

router.get('/plan', async (req, res) => {
  const cash = Number(req.query.cash ?? 0)
  const minTrade = req.query.min_trade != null && req.query.min_trade !== '' ? Number(req.query.min_trade) : 1000
  if (!Number.isFinite(cash) || cash < 0 || !Number.isFinite(minTrade) || minTrade < 0)
    return res.status(400).json({ detail: 'cash 與 min_trade 要是 ≥ 0 的數字' })

  let candidate
  try {
    candidate = await fetchFastAPI({ port: 8000, path: '/portfolio/candidate' })
  } catch (e) {
    return res.status(503).json({ detail: `爬蟲服務未啟動或清單讀不到：${e.message}` })
  }
  const list = candidate?.current_list
  if (!list?.items?.length) return res.status(404).json({ detail: '還沒有月清單（portfolio_backtest.py --current-list 或等排程算）' })

  try {
    const [holdings, managed] = await Promise.all([userHoldings(req.user.id), managedIds(req.user.id)])
    const plan = buildPlan({ list: list.items, holdings, cash, managed, minTrade })
    res.json({
      list: { rebalance_date: list.rebalance_date, exec_date: list.exec_date, price_date: list.price_date, run_id: list.run_id,
              computed_at: list.computed_at, n: list.items.length },
      schedule: nextSignalDate(),
      managed,
      note: `${NOTE_PREFIX} 清單 ${list.rebalance_date}`,
      ...plan,
    })
  } catch (e) {
    console.error('[GET /trading/plan]', e.message)
    res.status(500).json({ detail: e.message })
  }
})

router.get('/log', async (req, res) => {
  try {
    const { rows } = await db.query(`
      SELECT t.id, t.stock_id, si.stock_name, t.trade_date::text AS trade_date, t.side, t.shares, t.price, t.fee, t.tax, t.note,
             t.shares_after, t.realized_pnl
        FROM user_trades t LEFT JOIN stock_info si ON si.stock_id = t.stock_id
       WHERE t.user_id = $1 AND t.note LIKE $2
       ORDER BY t.trade_date DESC, t.id DESC LIMIT 300`, [req.user.id, `${NOTE_PREFIX}%`])
    const num = v => (v == null ? null : Number(v))
    const items = rows.map(r => ({ ...r, shares: num(r.shares), price: num(r.price), fee: num(r.fee), tax: num(r.tax),
                                   shares_after: num(r.shares_after), realized_pnl: num(r.realized_pnl),
                                   gross: +(num(r.shares) * num(r.price)).toFixed(2),
                                   batch: (String(r.note || '').match(/清單\s*(\d{4}-\d{2}-\d{2})/) || [])[1] || null }))
    // 按清單分批：同一個訊號日的指令是一批，頁面用它對帳
    const batches = {}
    for (const it of items) {
      const k = it.batch || '（未標清單）'
      batches[k] = batches[k] || { batch: k, n: 0, buy: 0, sell: 0, fees: 0, first: it.trade_date, last: it.trade_date }
      const b = batches[k]; b.n++
      if (it.side === 'Buy') b.buy += it.gross; else b.sell += it.gross
      b.fees += (it.fee || 0) + (it.tax || 0)
      if (it.trade_date < b.first) b.first = it.trade_date
      if (it.trade_date > b.last) b.last = it.trade_date
    }
    res.json({ items, batches: Object.values(batches).sort((a, b) => (a.batch < b.batch ? 1 : -1)) })
  } catch (e) {
    console.error('[GET /trading/log]', e.message)
    res.status(500).json({ detail: e.message })
  }
})

module.exports = router
