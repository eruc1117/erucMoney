// 需求 5：紀錄查詢過的資料

import { useState, useEffect } from 'react'
import { readHistory, clearHistory, timeAgo } from '../services/history'

const TYPE_MAP = {
  budget: { label: '預算', color: 'yellow', icon: '💰' },
  stock:  { label: '個股', color: 'blue',   icon: '📈' },
  news:   { label: '新聞', color: 'purple', icon: '📝' },
}

const FILTERS = [
  { key: 'all',    label: '全部' },
  { key: 'budget', label: '預算' },
  { key: 'stock',  label: '個股' },
  { key: 'news',   label: '新聞' },
]

const RESULT_STATUS = (result) => {
  if (!result) return null
  if (result.includes('找到') || result.includes('已找到') || result.includes('已完成') || result.includes('已送出'))
    return <span className="tag green">{result}</span>
  if (result.includes('失敗') || result.includes('error'))
    return <span className="tag red">{result}</span>
  if (result.includes('爬蟲') || result.includes('不在'))
    return <span className="tag yellow">{result}</span>
  return <span className="tag">{result}</span>
}

export default function QueryHistory({ onSelectStock }) {
  const [list, setList]     = useState([])
  const [filter, setFilter] = useState('all')

  function reload() { setList(readHistory()) }

  useEffect(() => { reload() }, [])

  function handleClear() {
    clearHistory()
    reload()
  }

  const filtered = filter === 'all' ? list : list.filter(h => h.type === filter)

  return (
    <>
      {/* Header */}
      <div className="card">
        <div className="card-header">
          <span className="card-title">查詢紀錄</span>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <div className="filter-group">
              {FILTERS.map(f => (
                <button
                  key={f.key}
                  className={`btn-filter${filter === f.key ? ' active' : ''}`}
                  onClick={() => setFilter(f.key)}
                >
                  {f.label}
                </button>
              ))}
            </div>
            <button className="btn-secondary" onClick={reload}>重整</button>
            {list.length > 0 && (
              <button className="btn-secondary" style={{ color: 'var(--red)' }} onClick={handleClear}>
                清除紀錄
              </button>
            )}
          </div>
        </div>
      </div>

      {/* List */}
      {filtered.length === 0 ? (
        <div className="empty-state">
          <div className="empty-icon">📋</div>
          <div>尚無查詢紀錄</div>
          <div className="muted" style={{ fontSize: '0.75rem' }}>使用預算查詢、個股分析或新聞輸入後，紀錄會自動出現</div>
        </div>
      ) : (
        <div className="card">
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr><th>時間</th><th>類型</th><th>查詢內容</th><th>備註</th><th>結果</th><th></th></tr>
              </thead>
              <tbody>
                {filtered.map(h => {
                  const t = TYPE_MAP[h.type] || TYPE_MAP.stock
                  return (
                    <tr key={h.id}>
                      <td className="muted" style={{ whiteSpace: 'nowrap' }}>{timeAgo(h.timestamp)}</td>
                      <td><span className={`tag ${t.color}`}>{t.icon} {t.label}</span></td>
                      <td><strong>{h.query}</strong></td>
                      <td className="muted">{h.detail || '–'}</td>
                      <td>{RESULT_STATUS(h.result)}</td>
                      <td>
                        {h.type === 'stock' && (
                          <button className="btn-chip" onClick={() => onSelectStock(h.query)}>
                            再次分析
                          </button>
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
          <div style={{ padding: '10px 18px', fontSize: '0.6875rem', color: 'var(--dim)' }}>
            共 {filtered.length} 筆紀錄（儲存於 localStorage）
          </div>
        </div>
      )}
    </>
  )
}
