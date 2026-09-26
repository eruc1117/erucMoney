/**
 * 行情 seed：3 檔追蹤（0050、2330、2303）＋ 1 檔未追蹤（2454），各 30 個交易日（平日，至昨天為止）。
 *
 * - 收盤價從 BASE 起每日 +STEP，adj_close = close（review 的 5 日報酬用 adj_close）
 * - 籌碼：每日 total_net_buy = 日序 × 1000（外資 600、投信 300、自營 100）
 * - 外資持股：2303 故意少最後一天 → foreign_holding_date 早於 trade_date（stocks 路由的「晚揭露」旗標）
 * 回傳 { dates, stocks }，dates 由舊到新。
 */
const STOCKS = [
  { id: '0050', name: '元大台灣50', industry: 'ETF',    base: 110,  step: 0.5, tracking: true },
  { id: '2330', name: '台積電',     industry: '半導體業', base: 2400, step: 5,   tracking: true },
  { id: '2303', name: '聯電',       industry: '半導體業', base: 150,  step: 0.3, tracking: true },
  { id: '2454', name: '聯發科',     industry: '半導體業', base: 1300, step: 2,   tracking: false },
]

function tradingDays(n) {
  const out = []
  const d = new Date()
  d.setHours(0, 0, 0, 0)
  d.setDate(d.getDate() - 1)          // 從昨天往回
  while (out.length < n) {
    const wd = d.getDay()
    if (wd !== 0 && wd !== 6) out.unshift(iso(d))
    d.setDate(d.getDate() - 1)
  }
  return out
}
const iso = d => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`

async function seedMarket(db, { days = 30 } = {}) {
  const dates = tradingDays(days)
  for (const s of STOCKS) {
    await db.query(
      `INSERT INTO stock_info (stock_id, stock_name, market_type, industry_type, is_tracking)
       VALUES ($1, $2, 'twse', $3, $4)
       ON CONFLICT (stock_id) DO UPDATE SET stock_name = EXCLUDED.stock_name, industry_type = EXCLUDED.industry_type, is_tracking = EXCLUDED.is_tracking`,
      [s.id, s.name, s.industry, s.tracking])
    for (let i = 0; i < dates.length; i++) {
      const close = +(s.base + i * s.step).toFixed(2)
      const prev = i ? +(s.base + (i - 1) * s.step).toFixed(2) : close
      await db.query(
        `INSERT INTO stock_daily_prices (stock_id, trade_date, open_price, high_price, low_price, close_price, volume,
                                         turnover_value, transaction_count, change_value, change_rate, adj_close)
         VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $6)
         ON CONFLICT (stock_id, trade_date) DO NOTHING`,
        [s.id, dates[i], prev, close + 1, prev - 1, close, 1000 * (i + 1), close * 1000 * (i + 1), 100 + i,
         +(close - prev).toFixed(2), prev ? +(((close - prev) / prev) * 100).toFixed(3) : 0])
      await db.query(
        `INSERT INTO stock_chip_analysis (stock_id, trade_date, foreign_investor_buy, investment_trust_buy, dealer_buy, total_net_buy)
         VALUES ($1, $2, $3, $4, $5, $6) ON CONFLICT (stock_id, trade_date) DO NOTHING`,
        [s.id, dates[i], 600 * (i + 1), 300 * (i + 1), 100 * (i + 1), 1000 * (i + 1)])
      const lastDay = i === dates.length - 1
      if (!(s.id === '2303' && lastDay)) {
        await db.query(
          `INSERT INTO stock_foreign_holding (stock_id, trade_date, foreign_shares, foreign_ratio, foreign_upper_limit_ratio, shares_issued)
           VALUES ($1, $2, $3, $4, 100, $5) ON CONFLICT (stock_id, trade_date) DO NOTHING`,
          [s.id, dates[i], 1000000 + i * 1000, +(40 + i * 0.1).toFixed(2), 2500000])
      }
    }
  }
  return { dates, stocks: STOCKS }
}

/** 某檔在 seed 裡最後一天的收盤價 */
function lastClose(stockId, dates) {
  const s = STOCKS.find(x => x.id === stockId)
  return +(s.base + (dates.length - 1) * s.step).toFixed(2)
}

module.exports = { seedMarket, tradingDays, lastClose, STOCKS }
