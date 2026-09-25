// ============================================================
//  Query History — localStorage (需求 5: 紀錄查詢過的資料)
// ============================================================

const KEY = 'money_query_history'
const MAX = 100

export function addHistory(entry) {
  // entry: { type: 'budget'|'stock'|'news', query, result, detail? }
  const list = readHistory()
  list.unshift({ ...entry, id: Date.now(), timestamp: new Date().toISOString() })
  localStorage.setItem(KEY, JSON.stringify(list.slice(0, MAX)))
}

export function readHistory() {
  try {
    return JSON.parse(localStorage.getItem(KEY) || '[]')
  } catch {
    return []
  }
}

export function clearHistory() {
  localStorage.removeItem(KEY)
}

// Format timestamp to "幾分前 / 幾小時前 / 日期"
export function timeAgo(iso) {
  const diff = (Date.now() - new Date(iso)) / 1000
  if (diff < 60)   return `${Math.floor(diff)} 秒前`
  if (diff < 3600) return `${Math.floor(diff / 60)} 分前`
  if (diff < 86400) return `${Math.floor(diff / 3600)} 小時前`
  return new Date(iso).toLocaleDateString('zh-TW')
}
