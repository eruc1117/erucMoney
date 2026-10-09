/**
 * 程式交易的下單指令（純函式）：目標股數、範圍、先賣後買、現金不夠就縮、最小下單金額、下一個訊號日。
 */
const { buildPlan, nextSignalDate, feeOf, taxOf } = require('../../lib/tradingPlan')

const LIST = [
  { stock_id: '2330', stock_name: '台積電', target_weight: 0.5, price: 2500, rank: null, is_new: false },
  { stock_id: '2303', stock_name: '聯電', target_weight: 0.25, price: 100, rank: 1, is_new: true },
  { stock_id: '2454', stock_name: '聯發科', target_weight: 0.25, price: 1000, rank: 2, is_new: false },
]

describe('費用', () => {
  it('零股最低 1 元、整股最低 20 元；只有賣出有證交稅', () => {
    expect(feeOf(500, 5)).toBe(1)
    expect(feeOf(100000, 1000)).toBe(143)
    expect(feeOf(5000, 1000)).toBe(20)
    expect(taxOf('Buy', 100000)).toBe(0)
    expect(taxOf('Sell', 100000)).toBe(300)
  })
})

describe('buildPlan', () => {
  it('空手＋現金：每檔 floor(總資產 × 權重 ÷ 價)，全部是買單、依目標權重排序', () => {
    const p = buildPlan({ list: LIST, holdings: [], cash: 100000 })
    expect(p.summary.total).toBe(100000)
    // 權重合計 100%，手續費放不下 → 最大的那筆（台積電 20 股）縮 1 股
    expect(p.orders.map(o => [o.stock_id, o.side, o.shares])).toEqual([['2330', 'Buy', 19], ['2303', 'Buy', 250], ['2454', 'Buy', 25]])
    expect(p.warnings.some(w => /縮股數/.test(w))).toBe(true)
    expect(p.orders.every(o => o.reason === 'new')).toBe(true)
    expect(p.summary.n_buy).toBe(3)
    expect(p.summary.cash_after).toBeGreaterThanOrEqual(0)
    expect(p.summary.drift_before).toBe(0.5)       // 全現金 → 偏離 = Σ目標權重 ÷ 2
    expect(p.summary.drift_after).toBeLessThan(0.05)
  })

  it('已持有且在清單裡的只調差額；太小的調整不下單', () => {
    const holdings = [{ stock_id: '2330', shares: 20, last_price: 2500 }, { stock_id: '2303', shares: 248, last_price: 100 }]
    const p = buildPlan({ list: LIST, holdings, cash: 25200 })
    // 總資產 = 25200 + 50000 + 24800 = 100000
    expect(p.summary.total).toBe(100000)
    expect(p.orders.find(o => o.stock_id === '2330')).toBeUndefined()           // 已達標
    expect(p.orders.find(o => o.stock_id === '2303')).toBeUndefined()           // 差 2 股 = 200 元 < 1000
    expect(p.orders.find(o => o.stock_id === '2454')).toMatchObject({ side: 'Buy', shares: 25, reason: 'new' })
    expect(p.positions.find(x => x.stock_id === '2303').shares_target).toBe(250)
  })

  it('範圍外的持股不動、另列；以前用程式交易買過的才算範圍內（退出清單 → 全賣）', () => {
    const holdings = [
      { stock_id: '0050', stock_name: '元大台灣50', shares: 1000, last_price: 110 },   // 使用者自己的
      { stock_id: '2412', stock_name: '中華電', shares: 300, last_price: 120 },        // 以前程式買的、這期不在清單
    ]
    const p = buildPlan({ list: LIST, holdings, cash: 0, managed: ['2412'] })
    expect(p.untouched.map(u => u.stock_id)).toEqual(['0050'])
    expect(p.orders[0]).toMatchObject({ stock_id: '2412', side: 'Sell', shares: 300, reason: 'exit' })
    expect(p.orders[0].tax).toBe(Math.round(36000 * 0.003))
    expect(p.summary.position_value).toBe(36000)    // 0050 不算進總資產
    // 賣出淨額拿去買清單
    expect(p.summary.sell_net).toBeGreaterThan(0)
    expect(p.orders.filter(o => o.side === 'Buy').length).toBeGreaterThan(0)
  })

  it('現金不夠買齊：從金額最大的買單縮，執行後現金不為負', () => {
    const list = [{ stock_id: 'A', target_weight: 0.6, price: 1000 }, { stock_id: 'B', target_weight: 0.4, price: 10 }]
    // 權重 1.0 整個吃滿現金，手續費放不下 → 一定要縮
    const p = buildPlan({ list, holdings: [], cash: 10000, minTrade: 0 })
    expect(p.summary.cash_after).toBeGreaterThanOrEqual(0)
    expect(p.warnings.some(w => /縮股數/.test(w))).toBe(true)
    const a = p.orders.find(o => o.stock_id === 'A')
    expect(a.shares).toBeLessThan(6)
  })

  it('沒有參考價的檔略過並警告；cash 負數當 0', () => {
    const p = buildPlan({ list: [{ stock_id: 'X', target_weight: 0.5, price: null }], holdings: [], cash: -5 })
    expect(p.orders).toEqual([])
    expect(p.warnings[0]).toMatch(/X 沒有參考價/)
    expect(p.summary.cash).toBe(0)
  })

  it('先賣後買：賣單在前、買單在後', () => {
    const holdings = [{ stock_id: '2454', shares: 100, last_price: 1000 }]   // 10 萬，目標 25%
    const p = buildPlan({ list: LIST, holdings, cash: 0 })
    expect(p.orders[0]).toMatchObject({ stock_id: '2454', side: 'Sell', shares: 75, reason: 'rebalance' })
    expect(p.orders.slice(1).every(o => o.side === 'Buy')).toBe(true)
  })
})

describe('nextSignalDate', () => {
  it('每月 11 日起第一個平日；今天已過就下個月；成交日是訊號日的下一個平日', () => {
    expect(nextSignalDate(new Date(2026, 9, 1))).toEqual({ signal_date: '2026-10-12', exec_date: '2026-10-13' })   // 10/11 週日 → 10/12
    expect(nextSignalDate(new Date(2026, 9, 13))).toEqual({ signal_date: '2026-11-11', exec_date: '2026-11-12' })
    expect(nextSignalDate(new Date(2026, 9, 12))).toEqual({ signal_date: '2026-10-12', exec_date: '2026-10-13' })   // 當天算
    expect(nextSignalDate(new Date(2026, 11, 30))).toEqual({ signal_date: '2027-01-11', exec_date: '2027-01-12' })
  })
})
