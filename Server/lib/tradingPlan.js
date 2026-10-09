/**
 * 程式交易：把「候選策略的月清單（目標權重）」和「使用者實際持股＋可投入現金」變成一張下單指令表（Iteration 57）
 *
 * 純函式、不碰資料庫，所以可以單元測試。路由 routes/trading.js 負責撈資料再呼叫 buildPlan。
 *
 * 規則（和紙上交易 portfolio_paper.fill 的精神一致，但對象是真人的帳戶）：
 * - 「策略範圍」= 清單裡的股票 ∪ 以前用程式交易買過（台帳 note 以 [程式交易] 開頭）的股票。
 *   範圍外的持股（使用者自己買的）一律不動、另列出來——程式不能替人賣掉他沒交給程式管的東西。
 * - 總資產 = 可投入現金 ＋ 範圍內持股市值；目標股數 = floor(總資產 × 目標權重 ÷ 參考價)。
 * - 先賣後買：賣出淨額（扣手續費、證交稅）加進可用現金；買進總成本（含手續費）超過可用現金時，
 *   從金額最大的買單開始縮股數，直到放得下——寧可少買，不能叫人透支。
 * - 小於 minTrade（預設 NT$1,000）的調整不下單（零股手續費最低 1 元，太小的單只是在付費用）；
 *   但目標權重為 0 的（退出清單）一律全賣。
 * - 參考價是清單帶的最新收盤（沒有就用持股表的最後收盤）；實際成交看隔天開盤，所以頁面叫它「參考價」。
 */
const FEE_RATE = 0.001425
const TAX_RATE = 0.003

function feeOf(gross, shares) {
  // 整股最低 20 元（與 tradeLedger 一致）；零股最低 1 元
  return Math.max(shares >= 1000 ? 20 : 1, Math.round(gross * FEE_RATE))
}
function taxOf(side, gross) { return side === 'Sell' ? Math.round(gross * TAX_RATE) : 0 }

function priceOrders(o) {
  o.gross = +(o.shares * o.price).toFixed(2)
  o.fee = feeOf(o.gross, o.shares)
  o.tax = taxOf(o.side, o.gross)
  o.net = +(o.side === 'Sell' ? o.gross - o.fee - o.tax : o.gross + o.fee).toFixed(2)   // 賣：入帳；買：出帳
  return o
}

/**
 * @param {object} args
 * @param {Array}  args.list      清單 [{ stock_id, stock_name, target_weight, price, rank, is_new }]
 * @param {Array}  args.holdings  持股 [{ stock_id, stock_name, shares, last_price, avg_cost }]
 * @param {number} args.cash      可投入現金
 * @param {Array}  [args.managed] 以前用程式交易碰過的股票代號（範圍判斷用）
 * @param {number} [args.minTrade=1000] 最小下單金額
 */
function buildPlan({ list = [], holdings = [], cash = 0, managed = [], minTrade = 1000 }) {
  cash = Math.max(0, Number(cash) || 0)
  minTrade = Math.max(0, Number(minTrade) || 0)
  const listMap = new Map(list.map(i => [i.stock_id, i]))
  const inScope = new Set([...managed, ...listMap.keys()])
  const held = new Map(holdings.filter(h => Number(h.shares) > 0).map(h => [h.stock_id, h]))
  const warnings = []

  const priceOf = id => {
    const p = listMap.get(id)?.price ?? held.get(id)?.last_price
    return p != null && Number(p) > 0 ? Number(p) : null
  }

  const scopeIds = [...new Set([...listMap.keys(), ...[...held.keys()].filter(id => inScope.has(id))])]
  const untouched = [...held.values()].filter(h => !inScope.has(h.stock_id))
    .map(h => ({ stock_id: h.stock_id, stock_name: h.stock_name || null, shares: Number(h.shares), last_price: h.last_price ?? null,
                 market_value: h.last_price != null ? +(Number(h.shares) * Number(h.last_price)).toFixed(2) : null }))

  let positionValue = 0
  for (const id of scopeIds) {
    const h = held.get(id); const p = priceOf(id)
    if (h && p) positionValue += Number(h.shares) * p
  }
  const total = cash + positionValue

  const positions = []
  for (const id of scopeIds) {
    const li = listMap.get(id); const h = held.get(id)
    const cur = h ? Number(h.shares) : 0
    const price = priceOf(id)
    const wTarget = li ? Number(li.target_weight) : 0
    if (!price) { warnings.push(`${id} 沒有參考價，略過`); continue }
    const wNow = total > 0 ? (cur * price) / total : 0
    const targetShares = total > 0 ? Math.floor((total * wTarget) / price) : 0
    const diff = targetShares - cur
    const reason = wTarget === 0 ? 'exit' : cur === 0 ? 'new' : 'rebalance'
    let side = diff > 0 ? 'Buy' : diff < 0 ? 'Sell' : null
    let shares = Math.abs(diff)
    // 太小的調整不下單；退出清單例外（全賣）
    if (side && reason !== 'exit' && shares * price < minTrade) { side = null; shares = 0 }
    positions.push({
      stock_id: id, stock_name: li?.stock_name || h?.stock_name || null, rank: li?.rank ?? null, is_new: !!li?.is_new,
      price, shares_now: cur, shares_target: targetShares, weight_now: +wNow.toFixed(4), weight_target: +wTarget.toFixed(4),
      side, shares, reason,
    })
  }

  const orders = positions.filter(p => p.side).map(p => priceOrders({
    stock_id: p.stock_id, stock_name: p.stock_name, side: p.side, shares: p.shares, price: p.price, reason: p.reason,
    weight_now: p.weight_now, weight_target: p.weight_target, shares_now: p.shares_now, shares_target: p.shares_target,
  }))

  // 現金可行性：先賣後買；買不下就從最大的買單開始縮
  const sells = orders.filter(o => o.side === 'Sell')
  const buys = orders.filter(o => o.side === 'Buy')
  const sellNet = sells.reduce((s, o) => s + o.net, 0)
  let available = cash + sellNet
  let buyCost = buys.reduce((s, o) => s + o.net, 0)
  let trimmed = false
  while (buyCost > available && buys.some(o => o.shares > 0)) {
    const big = buys.filter(o => o.shares > 0).sort((a, b) => b.gross - a.gross)[0]
    const cut = Math.max(1, Math.ceil((buyCost - available) / big.price))
    big.shares = Math.max(0, big.shares - cut)
    priceOrders(big)
    buyCost = buys.reduce((s, o) => s + o.net, 0)
    trimmed = true
  }
  if (trimmed) warnings.push('可投入現金不夠買齊目標，已從金額最大的買單開始縮股數')
  const finalOrders = [
    ...sells.sort((a, b) => b.gross - a.gross),
    ...buys.filter(o => o.shares > 0).sort((a, b) => b.weight_target - a.weight_target),
  ]

  // 執行後的權重偏離（Σ|現在 − 目標| ÷ 2）：執行前 vs 執行後，讓人看得出這張單值不值得跑
  const driftBefore = positions.reduce((s, p) => s + Math.abs(p.weight_now - p.weight_target), 0) / 2
  const afterShares = new Map(positions.map(p => [p.stock_id, p.shares_now]))
  for (const o of finalOrders) afterShares.set(o.stock_id, afterShares.get(o.stock_id) + (o.side === 'Buy' ? o.shares : -o.shares))
  const cashAfter = available - buyCost
  const totalAfter = cashAfter + positions.reduce((s, p) => s + afterShares.get(p.stock_id) * p.price, 0)
  const driftAfter = totalAfter > 0
    ? positions.reduce((s, p) => s + Math.abs((afterShares.get(p.stock_id) * p.price) / totalAfter - p.weight_target), 0) / 2 : 0

  return {
    orders: finalOrders,
    positions,
    untouched,
    warnings,
    summary: {
      cash, position_value: +positionValue.toFixed(2), total: +total.toFixed(2),
      sell_net: +sellNet.toFixed(2), buy_cost: +buyCost.toFixed(2), cash_after: +cashAfter.toFixed(2),
      n_sell: sells.length, n_buy: finalOrders.filter(o => o.side === 'Buy').length,
      fees: +finalOrders.reduce((s, o) => s + o.fee + o.tax, 0).toFixed(2),
      drift_before: +driftBefore.toFixed(4), drift_after: +driftAfter.toFixed(4),
      min_trade: minTrade,
    },
  }
}

/**
 * 下一個訊號日：每月 11 日起第一個交易日（候選策略的規則，portfolio_paper.signal_date_for_month）。
 * 這裡只避開週末、不知道假日——頁面上要寫「約」。回 { signal_date, exec_date }（成交日 = 訊號日的下一個平日）。
 */
function nextSignalDate(today = new Date()) {
  const d = new Date(today); d.setHours(0, 0, 0, 0)
  const nextWeekday = x => { const y = new Date(x); while (y.getDay() === 0 || y.getDay() === 6) y.setDate(y.getDate() + 1); return y }
  let sig = nextWeekday(new Date(d.getFullYear(), d.getMonth(), 11))
  if (sig < d) sig = nextWeekday(new Date(d.getFullYear(), d.getMonth() + 1, 11))
  const exec = nextWeekday(new Date(sig.getFullYear(), sig.getMonth(), sig.getDate() + 1))
  const iso = x => `${x.getFullYear()}-${String(x.getMonth() + 1).padStart(2, '0')}-${String(x.getDate()).padStart(2, '0')}`
  return { signal_date: iso(sig), exec_date: iso(exec) }
}

const NOTE_PREFIX = '[程式交易]'

module.exports = { buildPlan, nextSignalDate, feeOf, taxOf, FEE_RATE, TAX_RATE, NOTE_PREFIX }
