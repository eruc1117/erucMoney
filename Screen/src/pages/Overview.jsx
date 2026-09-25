// 總覽頁 — 資料來源：PostgreSQL（is_tracking=TRUE 股票）
// 大盤指數 / NLP 情緒：待爬蟲與模型模組部署

import { useState, useEffect, useMemo } from 'react'
import { getTrackedStocks, getIndustries } from '../services/api'
import ModelBar from '../components/ModelBar'
import { shortDate, holdingLag, holdingTitle } from '../services/holding'

export default function Overview({ onSelectStock }) {
  const [stocks,     setStocks]     = useState([])
  const [industries, setIndustries] = useState([])   // [{ industry_type, stock_count }]
  const [loading,    setLoading]    = useState(true)
  const [error,      setError]      = useState('')
  const [industryFilter, setIndustryFilter] = useState('')  // '' = 全部

  // 切換產業篩選時重新拉資料
  useEffect(() => {
    setLoading(true)
    getTrackedStocks(industryFilter || null).then(({ data, error: e }) => {
      if (e) setError(e)
      else setStocks(data || [])
      setLoading(false)
    })
  }, [industryFilter])

  // 載入產業清單（只需一次）
  useEffect(() => {
    getIndustries().then(({ data }) => {
      if (data) setIndustries(data)
    })
  }, [])

  const upCount   = stocks.filter(s => Number(s.change_rate) > 0).length
  const downCount = stocks.filter(s => Number(s.change_rate) < 0).length
  const flatCount = stocks.length - upCount - downCount

  // 從追蹤股票統計各產業分布（前端計算，反映目前篩選前全量，用 industries 清單）
  const industryCount = industries.length

  return (
    <>
      <ModelBar page="overview" />
      {/* Metric Cards */}
      <div className="cards-grid">
        <div className="metric-card">
          <div className="metric-label">追蹤股票數</div>
          <div className="metric-value">{loading ? '…' : stocks.length}</div>
          <div className="metric-delta muted">
            {industryFilter ? `篩選：${industryFilter}` : 'is_tracking = TRUE'}
          </div>
        </div>
        <div className="metric-card">
          <div className="metric-label">上漲 / 下跌</div>
          <div className="metric-value">
            <span className="up">{upCount}</span>
            <span className="muted"> / </span>
            <span className="down">{downCount}</span>
          </div>
          <div className="metric-delta muted">平盤 {flatCount} 支</div>
        </div>
        <div className="metric-card">
          <div className="metric-label">產業類別數</div>
          <div className="metric-value">{industryCount || '…'}</div>
          <div className="metric-delta muted">已收錄產業種類</div>
        </div>
        <div className="metric-card">
          <div className="metric-label">市場情緒</div>
          <div className="metric-value muted">–</div>
          <div className="metric-delta muted">NLP 模組待部署</div>
        </div>
      </div>

      {/* 產業分布 */}
      {industries.length > 0 && (
        <div className="card">
          <div className="card-header">
            <span className="card-title">產業分布</span>
            {industryFilter && (
              <button
                className="btn-chip active"
                onClick={() => setIndustryFilter('')}
              >
                {industryFilter} ✕
              </button>
            )}
          </div>
          <div style={{ padding: '12px 18px', display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            {industries.map(ind => (
              <button
                key={ind.industry_type}
                className={`btn-chip${industryFilter === ind.industry_type ? ' active' : ''}`}
                onClick={() =>
                  setIndustryFilter(
                    industryFilter === ind.industry_type ? '' : ind.industry_type
                  )
                }
              >
                {ind.industry_type}
                <span className="muted" style={{ marginLeft: 5, fontSize: '0.6875rem' }}>
                  {ind.stock_count}
                </span>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Watchlist Table */}
      <div className="card">
        <div className="card-header">
          <span className="card-title">追蹤股票</span>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            {industryFilter && (
              <span className="tag blue">{industryFilter}</span>
            )}
            <span className="muted" style={{ fontSize: '0.6875rem' }}>
              資料來源：PostgreSQL · 顯示最新交易日資料
            </span>
          </div>
        </div>

        {loading && (
          <div style={{ padding: '24px', color: 'var(--dim)', textAlign: 'center' }}>載入中…</div>
        )}

        {error && (
          <div className="alert-error" style={{ margin: '12px 18px' }}>
            連線失敗：{error} — 請確認 Node.js Server 已啟動
          </div>
        )}

        {!loading && !error && stocks.length === 0 && (
          <div className="empty-state">
            <div className="empty-icon">📈</div>
            <div>{industryFilter ? `${industryFilter} 目前無追蹤股票` : '尚無追蹤股票'}</div>
            <div className="muted" style={{ fontSize: '0.75rem' }}>
              {industryFilter
                ? '請切換其他產業篩選，或清除篩選查看全部'
                : '請至「個股分析」頁面輸入股票代碼並執行爬蟲，資料寫入後即會顯示於此'}
            </div>
          </div>
        )}

        {!loading && stocks.length > 0 && (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>代碼</th><th>名稱</th><th>產業</th><th>市場</th>
                  <th>資料日期</th>
                  <th>收盤價</th><th>漲跌</th><th>漲跌幅</th>
                  <th>成交量(張)</th><th>三大法人合計</th><th title="外資真實持股比例；持股統計偶爾比行情晚一天揭露，落後時括號標出資料日期">外資持股%</th><th></th>
                </tr>
              </thead>
              <tbody>
                {stocks.map(s => {
                  const cr    = Number(s.change_rate)
                  const cv    = Number(s.change_value)
                  const nb    = s.total_net_buy != null ? Number(s.total_net_buy) : null
                  const cls   = cr > 0 ? 'up' : cr < 0 ? 'down' : ''
                  const arrow = cr > 0 ? '▲' : cr < 0 ? '▼' : '－'
                  const nbCls = nb != null ? (nb >= 0 ? 'up' : 'down') : ''
                  return (
                    <tr key={s.stock_id}>
                      <td><strong>{s.stock_id}</strong></td>
                      <td>{s.stock_name}</td>
                      <td>
                        {s.industry_type
                          ? (
                            <button
                              className={`btn-chip${industryFilter === s.industry_type ? ' active' : ''}`}
                              style={{ fontSize: '0.6875rem' }}
                              onClick={() =>
                                setIndustryFilter(
                                  industryFilter === s.industry_type ? '' : s.industry_type
                                )
                              }
                            >
                              {s.industry_type}
                            </button>
                          )
                          : <span className="muted">–</span>
                        }
                      </td>
                      <td className="muted">{s.market_type || '上市'}</td>
                      <td className="muted" style={{ whiteSpace: 'nowrap' }}>
                        {s.trade_date ?? '–'}
                      </td>
                      <td className={cls}>
                        {s.close_price != null ? Number(s.close_price).toFixed(2) : '–'}
                      </td>
                      <td className={cls}>
                        {cv ? `${arrow} ${Math.abs(cv).toFixed(2)}` : '－'}
                      </td>
                      <td className={cls}>
                        {cr ? `${arrow} ${Math.abs(cr).toFixed(2)}%` : '－'}
                      </td>
                      <td>{s.volume != null ? Number(s.volume).toLocaleString() : '–'}</td>
                      <td className={nbCls}>
                        {nb != null ? `${nb >= 0 ? '+' : ''}${nb.toLocaleString()}` : '–'}
                      </td>
                      <td className="muted" title={holdingTitle(s)}>
                        {s.foreign_holding_ratio != null ? `${s.foreign_holding_ratio}%` : '–'}
                        {holdingLag(s) ? <span className="lag-mark"> ({shortDate(s.foreign_holding_date)})</span> : null}
                      </td>
                      <td>
                        <button className="btn-chip" onClick={() => onSelectStock?.(s.stock_id)}>
                          分析
                        </button>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </>
  )
}
