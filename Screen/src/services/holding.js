// 外資持股比例的顯示輔助（Iteration 36）
//
// 持股統計（stock_foreign_holding）偶爾比行情晚一天揭露：
// 市場總覽與個股分析顯示的「外資持股%」可能對應前一個交易日。
// API 現在會一併回傳 foreign_holding_date 與行情的 trade_date，
// 這裡判斷兩者是否對齊，讓畫面能把落後標出來，而不是靜靜顯示一個舊數字。

export function shortDate(d) {
  if (!d) return ''
  const s = String(d).slice(0, 10)          // DATE 由連線層以字串回傳（Iteration 35）
  return s.length === 10 ? `${Number(s.slice(5, 7))}/${Number(s.slice(8, 10))}` : s
}

// 持股資料日期早於行情日期 → 落後
export function holdingLag(row) {
  if (!row || !row.foreign_holding_date || !row.trade_date) return false
  return String(row.foreign_holding_date).slice(0, 10) < String(row.trade_date).slice(0, 10)
}

export function holdingTitle(row) {
  if (!row || row.foreign_holding_ratio == null) return '尚無外資持股資料'
  const d = String(row.foreign_holding_date || '').slice(0, 10)
  return holdingLag(row)
    ? `外資持股資料日期 ${d}，比行情（${String(row.trade_date).slice(0, 10)}）晚揭露`
    : `外資持股資料日期 ${d}`
}
