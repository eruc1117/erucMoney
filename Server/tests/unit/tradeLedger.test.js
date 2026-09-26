/**
 * 交易台帳回放（lib/tradeLedger.js）— 純邏輯，不碰資料庫。
 * 費率：手續費 0.1425%（最低 20）、證交稅 0.3%（只有賣出）。
 */
const ledger = require('../../lib/tradeLedger')

const buy  = (shares, price, extra = {}) => ({ side: 'Buy', shares, price, ...extra })
const sell = (shares, price, extra = {}) => ({ side: 'Sell', shares, price, ...extra })

describe('estimateCosts：台股費率', () => {
  it('手續費 0.1425%，四捨五入', () => {
    expect(ledger.estimateCosts('Buy', 1000, 50)).toEqual({ fee: 71, tax: 0, gross: 50000 })   // 71.25 → 71
  })
  it('手續費最低 20 元', () => {
    expect(ledger.estimateCosts('Buy', 100, 50).fee).toBe(20)                                   // 7.1 → 20
  })
  it('賣出加證交稅 0.3%', () => {
    expect(ledger.estimateCosts('Sell', 1000, 50)).toEqual({ fee: 71, tax: 150, gross: 50000 })
  })
  it('買進沒有證交稅', () => {
    expect(ledger.estimateCosts('Buy', 1000, 50).tax).toBe(0)
  })
  it('接受字串輸入', () => {
    expect(ledger.estimateCosts('Sell', '1000', '50').tax).toBe(150)
  })
})

describe('replay：分批買進的平均成本', () => {
  it('單筆買進：成本 = (價金 + 手續費) / 股數', () => {
    const r = ledger.replay([buy(100, 100, { fee: 20 })])
    expect(r.shares).toBe(100)
    expect(r.avgCost).toBe(100.2)
    expect(r.realized).toBe(0)
  })
  it('兩批不同價位：移動平均，手續費計入成本', () => {
    const r = ledger.replay([buy(100, 100, { fee: 20 }), buy(100, 120, { fee: 20 })])
    // (100*100.2 + 100*120 + 20) / 200 = 110.2
    expect(r.avgCost).toBe(110.2)
    expect(r.shares).toBe(200)
  })
  it('沒給 fee/tax 視為 0', () => {
    const r = ledger.replay([buy(10, 50)])
    expect(r.avgCost).toBe(50)
  })
})

describe('replay：賣出與已實現損益', () => {
  it('部分賣出：損益 = 賣出股數 × (賣價 − 均價) − 費用；均價不變', () => {
    const r = ledger.replay([buy(100, 100, { fee: 20 }), sell(40, 110, { fee: 20, tax: 13 })])
    expect(r.shares).toBe(60)
    expect(r.avgCost).toBe(100.2)
    expect(r.realized).toBe(+(40 * (110 - 100.2) - 20 - 13).toFixed(2))   // 359
    expect(r.rows[1].realized_pnl).toBe(359)
    expect(r.rows[0].realized_pnl).toBeNull()
  })
  it('賣超過持有：只認列到持有量，多出的部分視為 0 成本，持股歸零不變負數', () => {
    const r = ledger.replay([buy(100, 100), sell(150, 110)])
    expect(r.shares).toBe(0)
    expect(r.realized).toBe(+(100 * 10 + 50 * 110).toFixed(2))
  })
  it('全部出清後成本歸零，再買進以新價重算', () => {
    const r = ledger.replay([buy(100, 100), sell(100, 120), buy(50, 200, { fee: 20 })])
    expect(r.rows[1].avg_cost_after).toBe(0)
    expect(r.shares).toBe(50)
    expect(r.avgCost).toBe(+(((50 * 200) + 20) / 50).toFixed(4))   // 200.4
  })
  it('每列回填 shares_after / avg_cost_after，供寫回 user_trades', () => {
    const r = ledger.replay([{ id: 7, ...buy(10, 100) }, { id: 8, ...sell(4, 90) }])
    expect(r.rows.map(x => x.id)).toEqual([7, 8])
    expect(r.rows[0].shares_after).toBe(10)
    expect(r.rows[1].shares_after).toBe(6)
  })
  it('同日多筆依傳入順序處理（順序由 SQL 的 trade_date, id 決定）', () => {
    const a = ledger.replay([buy(100, 100), sell(100, 110), buy(100, 120)])
    const b = ledger.replay([buy(100, 100), buy(100, 120), sell(100, 110)])
    expect(a.avgCost).toBe(120)          // 賣光再買：成本 120
    expect(b.avgCost).toBe(110)          // 先買兩批再賣：均價 110 不變
    expect(a.realized).not.toBe(b.realized)
  })
})

describe('rebuild：以假 db 驗證使用者隔離與寫回', () => {
  function fakeDb(trades) {
    const log = []
    return {
      log,
      async query(sql, params) {
        log.push({ sql: sql.replace(/\s+/g, ' ').trim(), params })
        if (/^SELECT id, side, shares, price, fee, tax/.test(sql.trim())) {
          const [stockId, userId] = params
          return { rows: trades.filter(t => t.stock_id === stockId && t.user_id === userId) }
        }
        return { rows: [], rowCount: 0 }
      },
    }
  }

  it('沒有 userId 直接拒絕', async () => {
    await expect(ledger.rebuild(fakeDb([]), '2330')).rejects.toThrow('userId')
  })

  it('兩個使用者同一檔股票各算各的', async () => {
    const db = fakeDb([
      { id: 1, stock_id: '2330', user_id: 1, side: 'Buy', shares: 10, price: 100, fee: 20, tax: 0 },
      { id: 2, stock_id: '2330', user_id: 2, side: 'Buy', shares: 5,  price: 200, fee: 20, tax: 0 },
      { id: 3, stock_id: '2330', user_id: 2, side: 'Sell', shares: 5, price: 250, fee: 20, tax: 4 },
    ])
    const u1 = await ledger.rebuild(db, '2330', 1)
    const u2 = await ledger.rebuild(db, '2330', 2)
    expect(u1.shares).toBe(10)
    expect(u1.realized).toBe(0)
    expect(u2.shares).toBe(0)
    expect(u2.realized).toBe(+(5 * (250 - 204) - 24).toFixed(2))
  })

  it('有持股 → 以 ON CONFLICT (user_id, stock_id) upsert；出清 → 刪 source=trades 的持倉列', async () => {
    const db = fakeDb([
      { id: 1, stock_id: '0050', user_id: 3, side: 'Buy', shares: 100, price: 100, fee: 20, tax: 0 },
    ])
    await ledger.rebuild(db, '0050', 3)
    expect(db.log.some(l => /INSERT INTO user_holdings/.test(l.sql) && l.params[4] === 3)).toBe(true)
    expect(db.log.some(l => /UPDATE user_trades/.test(l.sql) && l.params[3] === 1)).toBe(true)

    const db2 = fakeDb([
      { id: 1, stock_id: '0050', user_id: 3, side: 'Buy', shares: 100, price: 100 },
      { id: 2, stock_id: '0050', user_id: 3, side: 'Sell', shares: 100, price: 100 },
    ])
    await ledger.rebuild(db2, '0050', 3)
    expect(db2.log.some(l => /DELETE FROM user_holdings/.test(l.sql) && /source = 'trades'/.test(l.sql))).toBe(true)
    expect(db2.log.some(l => /INSERT INTO user_holdings/.test(l.sql))).toBe(false)
  })

  it('交易全刪光：只刪台帳推導的持倉，不動手動快照', async () => {
    const db = fakeDb([])
    const r = await ledger.rebuild(db, '2303', 9)
    expect(r.shares).toBe(0)
    const del = db.log.find(l => /DELETE FROM user_holdings/.test(l.sql))
    expect(del.sql).toMatch(/source = 'trades'/)
    expect(del.params).toEqual(['2303', 9])
  })
})
