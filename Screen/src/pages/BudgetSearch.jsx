// 需求 1：輸入金額後，比對資料庫去抓取可購買範圍的股票

import { useState, useEffect } from 'react'
import { getStocksByBudget, getIndustries } from '../services/api'
import { addHistory } from '../services/history'

function calcLots(budget, closePrice) {
  return Math.floor(budget / (closePrice * 1000))
}

export default function BudgetSearch({ onSelectStock }) {
  const [budget,   setBudget]   = useState('')
  const [results,  setResults]  = useState(null)   // null=未查, []=無結果, [...]=有結果
  const [loading,  setLoading]  = useState(false)
  const [error,    setError]    = useState('')

  const [industries,     setIndustries]     = useState([])  // [{ industry_type, stock_count }]
  const [industryFilter, setIndustryFilter] = useState('')  // '' = 全部

  const maxPrice = budget ? Math.floor(Number(budget) / 1000) : 0

  // 載入產業清單
  useEffect(() => {
    getIndustries().then(({ data }) => {
      if (data) setIndustries(data)
    })
  }, [])

  async function handleSearch() {
    const val = Number(budget)
    if (!val || val <= 0) { setError('請輸入有效金額（新台幣）'); return }
    setError('')
    setLoading(true)
    setResults(null)

    const { data, error: apiErr } = await getStocksByBudget(
      maxPrice,
      industryFilter || null,
    )
    setLoading(false)

    if (apiErr) {
      setError(`連線失敗：${apiErr}`)
      addHistory({ type: 'budget', query: `NT$${Number(budget).toLocaleString()}`, result: 'error' })
      return
    }

    const list = data || []
    setResults(list)
    addHistory({
      type: 'budget',
      query: `NT$${Number(budget).toLocaleString()}`,
      result: list.length > 0 ? `找到 ${list.length} 支` : '無符合股票',
      detail: `≤ ${maxPrice} 元/股${industryFilter ? ` · ${industryFilter}` : ''}`,
    })
  }

  return (
    <>
      {/* Budget Input Card */}
      <div className="card">
        <div className="card-header">
          <span className="card-title">輸入可用預算</span>
          <span className="tag blue">比對資料庫</span>
        </div>
        <div className="budget-form">
          <div className="budget-input-wrap">
            <span className="currency-prefix">NT$</span>
            <input
              className="budget-input"
              type="number"
              min="1000"
              step="1000"
              placeholder="例：50000"
              value={budget}
              onChange={e => setBudget(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && handleSearch()}
            />
          </div>

          {/* 產業篩選 */}
          <select
            className="form-input"
            style={{ width: 160 }}
            value={industryFilter}
            onChange={e => setIndustryFilter(e.target.value)}
          >
            <option value="">所有產業</option>
            {industries.map(ind => (
              <option key={ind.industry_type} value={ind.industry_type}>
                {ind.industry_type}（{ind.stock_count}）
              </option>
            ))}
          </select>

          <button className="btn-primary" onClick={handleSearch} disabled={loading}>
            {loading ? '查詢中...' : '查詢可買股票'}
          </button>
        </div>

        {/* Budget Hint */}
        {budget > 0 && (
          <div className="budget-hint">
            <span className="hint-item">
              <span className="muted">預算</span>
              <strong>NT${Number(budget).toLocaleString()}</strong>
            </span>
            <span className="hint-sep">→</span>
            <span className="hint-item">
              <span className="muted">每張 1,000 股，可買</span>
              <strong className="up">≤ {maxPrice.toLocaleString()} 元/股</strong>
              <span className="muted">的股票</span>
            </span>
            {industryFilter && (
              <>
                <span className="hint-sep">·</span>
                <span className="hint-item">
                  <span className="tag blue">{industryFilter}</span>
                </span>
              </>
            )}
          </div>
        )}

        {error && <div className="alert-error">{error}</div>}
      </div>

      {/* Results */}
      {results === null && !loading && (
        <div className="empty-state">
          <div className="empty-icon">💰</div>
          <div>輸入預算金額，系統將從資料庫篩選可負擔的股票</div>
          <div className="muted" style={{ fontSize: '0.75rem', marginTop: 6 }}>1 張 = 1,000 股</div>
        </div>
      )}

      {results !== null && results.length === 0 && (
        <div className="empty-state">
          <div className="empty-icon">🔍</div>
          <div>
            資料庫中無 ≤ {maxPrice} 元
            {industryFilter ? ` · ${industryFilter}` : ''} 的股票
          </div>
          <div className="muted" style={{ fontSize: '0.75rem' }}>
            請提高預算{industryFilter ? '、切換產業' : ''}，或先至「個股分析」頁面執行爬蟲
          </div>
        </div>
      )}

      {results && results.length > 0 && (
        <div className="card">
          <div className="card-header">
            <span className="card-title">符合預算的股票</span>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              {industryFilter && <span className="tag blue">{industryFilter}</span>}
              <span className="tag green">{results.length} 支</span>
            </div>
          </div>
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>代碼</th><th>名稱</th><th>產業</th><th>收盤價</th><th>漲跌幅</th>
                  <th>成交量(張)</th><th>可買張數</th><th>所需金額</th><th></th>
                </tr>
              </thead>
              <tbody>
                {results.map(s => {
                  const close = Number(s.close_price)
                  const cr    = Number(s.change_rate)
                  const vol   = Number(s.volume) || 0
                  const lots  = calcLots(Number(budget), close)
                  const cost  = (close * 1000 * lots).toLocaleString()
                  const up    = cr > 0
                  const dn    = cr < 0
                  const cls   = up ? 'up' : dn ? 'down' : ''
                  const arrow = up ? '▲' : dn ? '▼' : '－'
                  return (
                    <tr key={s.stock_id}>
                      <td><strong>{s.stock_id}</strong></td>
                      <td>{s.stock_name}</td>
                      <td>
                        {s.industry_type
                          ? <span className="tag" style={{ fontSize: '0.6875rem' }}>{s.industry_type}</span>
                          : <span className="muted">–</span>
                        }
                      </td>
                      <td className={cls}>{close.toFixed(2)}</td>
                      <td className={cls}>{arrow} {Math.abs(cr).toFixed(2)}%</td>
                      <td>{vol.toLocaleString()}</td>
                      <td className="up"><strong>{lots} 張</strong></td>
                      <td className="muted">NT${cost}</td>
                      <td>
                        <button
                          className="btn-chip"
                          onClick={() => onSelectStock(s.stock_id)}
                        >
                          詳細分析
                        </button>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </>
  )
}
