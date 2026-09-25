/**
 * 交易台帳回放（Iteration 23）
 *
 * 把某檔股票的所有交易依日期重放一次，重算平均成本、持股數與已實現損益，
 * 並把結論寫回 user_holdings。
 *
 * **為什麼是「回放」而不是「增量更新」**
 * 增量更新在新增交易時很簡單，但刪除或修改一筆早期交易時，
 * 後面每一筆的平均成本都會變——增量算法只能整段重來，
 * 那不如一開始就只有重放這一條路徑。台帳是事實，持倉是結論，
 * 結論永遠可以從事實重建，而且重建出來的一定自洽。
 */

// 台股費率（可在單筆交易上覆寫）
const FEE_RATE = 0.001425      // 券商手續費
const FEE_MIN = 20             // 最低手續費
const TAX_RATE = 0.003         // 證交稅（僅賣出）

/** 依台股慣例估算費用。使用者輸入了就用使用者的，不要偷偷覆蓋。 */
function estimateCosts(side, shares, price) {
  const gross = Number(shares) * Number(price)
  const fee = Math.max(Math.round(gross * FEE_RATE), FEE_MIN)
  const tax = side === 'Sell' ? Math.round(gross * TAX_RATE) : 0
  return { fee, tax, gross: +gross.toFixed(2) }
}

/**
 * 回放單一股票的交易，回傳 { shares, avgCost, realized, rows }。
 * rows 是每筆交易回填後的狀態，供寫回 user_trades。
 */
function replay(trades) {
  let shares = 0
  let cost = 0          // 平均成本（每股）
  let realized = 0
  const rows = []

  for (const t of trades) {
    const s = Number(t.shares)
    const px = Number(t.price)
    const fee = Number(t.fee ?? 0)
    const tax = Number(t.tax ?? 0)
    let pnl = null

    if (t.side === 'Buy') {
      // 手續費計入成本：那是取得這些股票實際付出的錢
      const newShares = shares + s
      cost = newShares > 0 ? (shares * cost + s * px + fee) / newShares : 0
      shares = newShares
    } else {
      // 賣超過持有量：不擋，但只認列到持有量為止，多的部分視為 0 成本。
      // 擋下來會讓使用者卡在無法輸入的狀態（例如漏記了一筆買進），
      // 照實算下去反而會讓錯誤在報表上顯眼。
      const sold = Math.min(s, shares)
      pnl = +(sold * (px - cost) + (s - sold) * px - fee - tax).toFixed(2)
      realized += pnl
      shares = Math.max(shares - s, 0)
      if (shares === 0) cost = 0      // 全部出清，成本歸零
    }

    rows.push({
      id: t.id,
      shares_after: +shares.toFixed(3),
      avg_cost_after: +cost.toFixed(4),
      realized_pnl: pnl,
    })
  }

  return { shares: +shares.toFixed(3), avgCost: +cost.toFixed(4),
           realized: +realized.toFixed(2), rows }
}

/**
 * 重放某檔股票並同步 user_holdings。
 * 回傳 { shares, avgCost, realized }。
 */
async function rebuild(db, stockId, userId) {
  if (!userId) throw new Error('rebuild 需要 userId')
  const { rows: trades } = await db.query(
    `SELECT id, side, shares, price, fee, tax
       FROM user_trades WHERE stock_id = $1 AND user_id = $2
      ORDER BY trade_date, id`, [stockId, userId])

  const res = replay(trades)

  for (const r of res.rows) {
    await db.query(
      `UPDATE user_trades
          SET shares_after = $1, avg_cost_after = $2, realized_pnl = $3
        WHERE id = $4`,
      [r.shares_after, r.avg_cost_after, r.realized_pnl, r.id])
  }

  if (trades.length === 0) {
    // 交易全刪光：若這檔的持倉是台帳推導出來的，就該一起消失；
    // 手動輸入的快照不動——那是使用者自己填的，不歸台帳管
    await db.query(
      `DELETE FROM user_holdings WHERE stock_id = $1 AND user_id = $2 AND source = 'trades'`, [stockId, userId])
    return res
  }

  if (res.shares > 0) {
    await db.query(
      `INSERT INTO user_holdings (stock_id, shares, avg_cost, source, realized_pnl, user_id)
       VALUES ($1, $2, $3, 'trades', $4, $5)
       ON CONFLICT (user_id, stock_id) DO UPDATE
         SET shares = EXCLUDED.shares, avg_cost = EXCLUDED.avg_cost,
             source = 'trades', realized_pnl = EXCLUDED.realized_pnl,
             updated_at = CURRENT_TIMESTAMP`,
      [stockId, res.shares, res.avgCost || 0.0001, res.realized, userId])
  } else {
    // 已全部出清：持倉列刪除，但已實現損益仍需保留在台帳裡（user_trades 有）
    await db.query(
      `DELETE FROM user_holdings WHERE stock_id = $1 AND user_id = $2 AND source = 'trades'`, [stockId, userId])
  }
  return res
}

module.exports = { estimateCosts, replay, rebuild, FEE_RATE, FEE_MIN, TAX_RATE }
