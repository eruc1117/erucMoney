// 需求 4+7：由使用者畫面貼上新聞資料 / 輸入新聞的頁面

import { useState, useRef, useEffect } from 'react'
import { submitNews, getNewsList, updateNews, deleteNews, triggerNewsCrawl, getNewsCrawlStatus } from '../services/api'
import { addHistory } from '../services/history'

const PLATFORMS = ['Yahoo Finance 台灣', 'CNN Business', '鉅亨網', 'MoneyDJ', '其他']

function detectTickers(text) {
  const matches = text.match(/\b[0-9]{4,5}\b/g) || []
  return [...new Set(matches)].filter(t => Number(t) >= 1000 && Number(t) <= 99999)
}

// ── Modal 元件 ────────────────────────────────────────────────────────────────
function NewsModal({ news, onClose, onSaved, onDeleted }) {
  const [editMode, setEditMode]   = useState(false)
  const [confirmDel, setConfirmDel] = useState(false)
  const [saving, setSaving]       = useState(false)
  const [deleting, setDeleting]   = useState(false)

  // edit form state
  const [platform, setPlatform]   = useState(news.platform || PLATFORMS[0])
  const [title, setTitle]         = useState(news.title || '')
  const [content, setContent]     = useState(news.content || '')
  const [tickerText, setTickerText] = useState((news.tickers || []).join(', '))

  function parseTickers(str) {
    return str.split(/[,\s，]+/).map(t => t.trim()).filter(t => t.length > 0)
  }

  async function handleSave() {
    setSaving(true)
    const { error } = await updateNews(news.id, {
      platform,
      title:         title.trim() || '(無標題)',
      content:       content.trim(),
      stock_tickers: parseTickers(tickerText),
    })
    setSaving(false)
    if (!error) {
      setEditMode(false)
      onSaved()
    }
  }

  async function handleDelete() {
    setDeleting(true)
    const { error } = await deleteNews(news.id)
    setDeleting(false)
    if (!error) onDeleted()
  }

  // 點擊背景關閉
  function handleOverlayClick(e) {
    if (e.target === e.currentTarget) onClose()
  }

  return (
    <div className="modal-overlay" onClick={handleOverlayClick}>
      <div className="modal">
        {/* Header */}
        <div className="modal-header">
          {editMode
            ? <input
                className="form-input"
                style={{ flex: 1, fontSize: '0.9375rem', fontWeight: 600 }}
                value={title}
                onChange={e => setTitle(e.target.value)}
              />
            : <div className="modal-title">{news.title}</div>
          }
          <button className="btn-icon" onClick={onClose} title="關閉">✕</button>
        </div>

        {/* Body */}
        <div className="modal-body">
          {editMode ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
              {/* Platform */}
              <div className="form-row">
                <label className="form-label">來源平台</label>
                <div className="platform-select">
                  {PLATFORMS.map(p => (
                    <button
                      key={p}
                      className={`btn-chip${platform === p ? ' active' : ''}`}
                      onClick={() => setPlatform(p)}
                    >
                      {p}
                    </button>
                  ))}
                </div>
              </div>
              {/* Tickers */}
              <div className="form-row">
                <label className="form-label">相關股票代碼（逗號分隔）</label>
                <input
                  className="form-input"
                  placeholder="例：2330, 2454"
                  value={tickerText}
                  onChange={e => setTickerText(e.target.value)}
                />
              </div>
              {/* Content */}
              <div className="form-row">
                <label className="form-label">新聞內文</label>
                <textarea
                  className="form-textarea"
                  value={content}
                  onChange={e => setContent(e.target.value)}
                  rows={12}
                />
                <div className="char-count muted">{content.length} 字</div>
              </div>
            </div>
          ) : (
            <>
              {/* Meta */}
              <div className="news-meta" style={{ marginBottom: 12 }}>
                <span className="tag">{news.platform}</span>
                {news.tickers?.length > 0 && (
                  <span>📌 {news.tickers.join(', ')}</span>
                )}
                <span className="muted">
                  {new Date(news.submitted_at).toLocaleString('zh-TW', {
                    year: 'numeric', month: 'numeric', day: 'numeric',
                    hour: '2-digit', minute: '2-digit',
                  })}
                </span>
              </div>
              {/* Full content */}
              <div style={{ fontSize: '0.875rem', lineHeight: 1.8, whiteSpace: 'pre-wrap', color: 'var(--text)' }}>
                {news.content || <span className="muted">（無內文）</span>}
              </div>
            </>
          )}
        </div>

        {/* Footer */}
        <div className="modal-footer">
          {editMode ? (
            <>
              <button className="btn-primary" onClick={handleSave} disabled={saving}>
                {saving ? '儲存中…' : '儲存'}
              </button>
              <button className="btn-secondary" onClick={() => setEditMode(false)}>取消</button>
            </>
          ) : confirmDel ? (
            <>
              <span style={{ fontSize: '0.8125rem', color: 'var(--red)', flex: 1 }}>確定要刪除？</span>
              <button className="btn-danger" onClick={handleDelete} disabled={deleting}>
                {deleting ? '刪除中…' : '確定刪除'}
              </button>
              <button className="btn-secondary" onClick={() => setConfirmDel(false)}>取消</button>
            </>
          ) : (
            <>
              <button className="btn-secondary" onClick={() => setEditMode(true)}>編輯</button>
              <button className="btn-danger" onClick={() => setConfirmDel(true)}>刪除</button>
              <div style={{ flex: 1 }} />
              <button className="btn-secondary" onClick={onClose}>關閉</button>
            </>
          )}
        </div>
      </div>
    </div>
  )
}

// ── 主頁面 ────────────────────────────────────────────────────────────────────
export default function NewsInput() {
  const [platform, setPlatform] = useState(PLATFORMS[0])
  const [title, setTitle]       = useState('')
  const [content, setContent]   = useState('')
  const [manualTicker, setManualTicker] = useState('')
  const [extraTickers, setExtraTickers] = useState([])
  const [submitState, setSubmitState]   = useState('idle')
  const [errorMsg, setErrorMsg] = useState('')

  const [history, setHistory]           = useState([])
  const [historyLoading, setHistoryLoading] = useState(true)
  const [query, setQuery]               = useState('')
  const [selected, setSelected]         = useState(null)
  const textareaRef = useRef(null)

  // ── 爬蟲狀態 ────────────────────────────────────────────────────────────────
  const [crawlState,    setCrawlState]    = useState('idle')  // idle | running | done | error
  const [crawlMode,     setCrawlMode]     = useState('')      // realtime | history
  const [crawlMsg,      setCrawlMsg]      = useState('')
  const [lastCount,     setLastCount]     = useState(null)
  const [startDate,     setStartDate]     = useState('')
  const [endDate,       setEndDate]       = useState('')
  const [crawlKws,      setCrawlKws]      = useState([])      // 已加入的關鍵字
  const [crawlKwInput,  setCrawlKwInput]  = useState('')      // 輸入框暫存
  const pollRef = useRef(null)

  function addCrawlKw() {
    const w = crawlKwInput.trim()
    if (w && !crawlKws.includes(w)) setCrawlKws(prev => [...prev, w])
    setCrawlKwInput('')
  }
  function removeCrawlKw(w) { setCrawlKws(prev => prev.filter(x => x !== w)) }

  function stopPolling() {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null }
  }

  function startPolling() {
    stopPolling()
    pollRef.current = setInterval(async () => {
      const { data } = await getNewsCrawlStatus()
      if (!data) return
      if (data.status === 'running') {
        setCrawlMsg(`爬取中… 已取得 ${data.last_count ?? 0} 則`)
      } else {
        setLastCount(data.last_count ?? 0)
        setCrawlState('done')
        setCrawlMsg(`完成！本次新增 ${data.last_count ?? 0} 則`)
        stopPolling()
        fetchHistory()
      }
    }, 2000)
  }

  async function handleRealtimeCrawl() {
    setCrawlState('running'); setCrawlMode('realtime'); setCrawlMsg('送出爬取請求…')
    const { error } = await triggerNewsCrawl({ keywords: crawlKws })
    if (error) { setCrawlState('error'); setCrawlMsg(`失敗：${error}`); return }
    startPolling()
  }

  async function handleHistoryCrawl() {
    if (!startDate || !endDate) { setCrawlMsg('請選擇起訖日期'); return }
    setCrawlState('running'); setCrawlMode('history'); setCrawlMsg('送出歷史爬取請求…')
    const { error } = await triggerNewsCrawl({ start_date: startDate, end_date: endDate, keywords: crawlKws })
    if (error) { setCrawlState('error'); setCrawlMsg(`失敗：${error}`); return }
    startPolling()
  }

  useEffect(() => () => stopPolling(), [])

  async function fetchHistory() {
    setHistoryLoading(true)
    const { data } = await getNewsList()
    setHistory(data || [])
    setHistoryLoading(false)
  }

  useEffect(() => { fetchHistory() }, [])

  const autoTickers = detectTickers(title + ' ' + content)
  const allTickers  = [...new Set([...autoTickers, ...extraTickers])]

  function addTicker() {
    const t = manualTicker.trim()
    if (t && !extraTickers.includes(t)) setExtraTickers(prev => [...prev, t])
    setManualTicker('')
  }
  function removeTicker(t) {
    setExtraTickers(prev => prev.filter(x => x !== t))
  }

  async function handleSubmit() {
    if (!content.trim()) return
    setSubmitState('loading')
    setErrorMsg('')
    const payload = {
      platform,
      title:         title.trim() || '(無標題)',
      content:       content.trim(),
      stock_tickers: allTickers,
    }
    const { error } = await submitNews(payload)
    if (error) { setSubmitState('error'); setErrorMsg(error); return }
    setSubmitState('success')
    addHistory({ type: 'news', query: payload.title.slice(0, 30), result: '已送出', detail: platform })
    fetchHistory()
    setTitle(''); setContent(''); setExtraTickers([])
    setTimeout(() => setSubmitState('idle'), 3000)
  }

  // 搜尋過濾
  const filtered = history.filter(n => {
    if (!query.trim()) return true
    const q = query.toLowerCase()
    return n.title?.toLowerCase().includes(q) ||
           n.content?.toLowerCase().includes(q) ||
           n.platform?.toLowerCase().includes(q) ||
           n.tickers?.some(t => t.includes(q))
  })

  // 依日期分組（submitted_at 已是降序）
  const grouped = filtered.reduce((acc, n) => {
    const label = new Date(n.submitted_at).toLocaleDateString('zh-TW', {
      year: 'numeric', month: 'long', day: 'numeric', weekday: 'short',
    })
    if (!acc[label]) acc[label] = []
    acc[label].push(n)
    return acc
  }, {})

  return (
    <>
      {/* Modal */}
      {selected && (
        <NewsModal
          news={selected}
          onClose={() => setSelected(null)}
          onSaved={async () => { await fetchHistory(); setSelected(null) }}
          onDeleted={() => { setSelected(null); fetchHistory() }}
        />
      )}

      {/* 新聞爬蟲 */}
      <div className="card">
        <div className="card-header">
          <span className="card-title">新聞爬蟲</span>
          <span className="tag blue">POST /crawler/news</span>
        </div>
        <div style={{ padding: '16px 18px', display: 'flex', flexDirection: 'column', gap: 14 }}>

          {/* 關鍵字過濾 */}
          <div className="form-row" style={{ marginBottom: 0 }}>
            <label className="form-label">關鍵字過濾 <span className="muted" style={{ fontSize: '0.6875rem' }}>（留空 = 不過濾）</span></label>
            <div className="ticker-area">
              {crawlKws.map(w => (
                <span key={w} className="ticker-tag manual">
                  {w}
                  <button className="ticker-remove" onClick={() => removeCrawlKw(w)} disabled={crawlState === 'running'}>×</button>
                </span>
              ))}
              <div className="ticker-input-wrap">
                <input
                  className="ticker-input"
                  placeholder="輸入關鍵字"
                  value={crawlKwInput}
                  onChange={e => setCrawlKwInput(e.target.value)}
                  onKeyDown={e => e.key === 'Enter' && addCrawlKw()}
                  disabled={crawlState === 'running'}
                />
                <button className="btn-chip" onClick={addCrawlKw} disabled={crawlState === 'running'}>+</button>
              </div>
            </div>
          </div>

          {/* 即時爬取 */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
            <button
              className="btn-primary"
              onClick={handleRealtimeCrawl}
              disabled={crawlState === 'running'}
            >
              {crawlState === 'running' && crawlMode === 'realtime' ? '爬取中…' : '即時爬取'}
            </button>
            <span className="muted" style={{ fontSize: '0.75rem' }}>抓取最新新聞並寫入資料庫</span>
          </div>

          {/* 歷史爬取 */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
            <input
              type="date"
              className="form-input"
              style={{ width: 140 }}
              value={startDate}
              onChange={e => setStartDate(e.target.value)}
              disabled={crawlState === 'running'}
            />
            <span className="muted">～</span>
            <input
              type="date"
              className="form-input"
              style={{ width: 140 }}
              value={endDate}
              onChange={e => setEndDate(e.target.value)}
              disabled={crawlState === 'running'}
            />
            <button
              className="btn-secondary"
              onClick={handleHistoryCrawl}
              disabled={crawlState === 'running' || !startDate || !endDate}
            >
              {crawlState === 'running' && crawlMode === 'history' ? '爬取中…' : '歷史爬取'}
            </button>
          </div>

          {/* 狀態列 */}
          {crawlMsg && (
            <div style={{
              fontSize: '0.8125rem',
              padding: '8px 12px',
              borderRadius: 6,
              background: crawlState === 'error'   ? 'rgba(var(--red-rgb,220,53,69),0.1)'
                        : crawlState === 'done'    ? 'rgba(var(--green-rgb,34,197,94),0.1)'
                        : 'rgba(var(--accent-rgb,99,102,241),0.1)',
              color:      crawlState === 'error'   ? 'var(--red)'
                        : crawlState === 'done'    ? 'var(--green)'
                        : 'var(--accent)',
              display: 'flex', alignItems: 'center', gap: 8,
            }}>
              {crawlState === 'running' && (
                <span style={{ display: 'inline-block', width: 12, height: 12, borderRadius: '50%',
                  border: '2px solid currentColor', borderTopColor: 'transparent',
                  animation: 'spin 0.8s linear infinite' }} />
              )}
              {crawlState === 'done'    && '✓ '}
              {crawlState === 'error'   && '✗ '}
              {crawlMsg}
            </div>
          )}
        </div>
      </div>

      {/* Input Form */}
      <div className="card">
        <div className="card-header">
          <span className="card-title">貼上新聞內容</span>
          <span className="tag blue">POST /news</span>
        </div>

        <div className="news-form">
          {/* Platform */}
          <div className="form-row">
            <label className="form-label">來源平台</label>
            <div className="platform-select">
              {PLATFORMS.map(p => (
                <button
                  key={p}
                  className={`btn-chip${platform === p ? ' active' : ''}`}
                  onClick={() => setPlatform(p)}
                >
                  {p}
                </button>
              ))}
            </div>
          </div>

          {/* Title */}
          <div className="form-row">
            <label className="form-label">新聞標題</label>
            <input
              className="form-input"
              placeholder="貼上或輸入新聞標題"
              value={title}
              onChange={e => setTitle(e.target.value)}
            />
          </div>

          {/* Content */}
          <div className="form-row">
            <label className="form-label">新聞內文</label>
            <textarea
              ref={textareaRef}
              className="form-textarea"
              placeholder="在此貼上新聞全文，系統將自動進行情感分析並寫入資料庫..."
              value={content}
              onChange={e => setContent(e.target.value)}
              rows={10}
            />
            <div className="char-count muted">{content.length} 字</div>
          </div>

          {/* Ticker Tags */}
          <div className="form-row">
            <label className="form-label">相關股票代碼</label>
            <div className="ticker-area">
              {autoTickers.map(t => (
                <span key={t} className="ticker-tag auto" title="自動偵測">
                  {t} <span className="muted" style={{ fontSize: '0.5625rem' }}>auto</span>
                </span>
              ))}
              {extraTickers.map(t => (
                <span key={t} className="ticker-tag manual">
                  {t}
                  <button className="ticker-remove" onClick={() => removeTicker(t)}>×</button>
                </span>
              ))}
              <div className="ticker-input-wrap">
                <input
                  className="ticker-input"
                  placeholder="新增代碼"
                  value={manualTicker}
                  onChange={e => setManualTicker(e.target.value)}
                  onKeyDown={e => e.key === 'Enter' && addTicker()}
                  maxLength={6}
                />
                <button className="btn-chip" onClick={addTicker}>+</button>
              </div>
            </div>
          </div>

          {/* Submit */}
          <div className="form-actions">
            <button
              className="btn-primary"
              onClick={handleSubmit}
              disabled={!content.trim() || submitState === 'loading'}
            >
              {submitState === 'loading' ? '送出中...' : '送出新聞'}
            </button>
            <button className="btn-secondary" onClick={() => { setTitle(''); setContent(''); setExtraTickers([]) }}>
              清除
            </button>
            {submitState === 'success' && <span className="status-ok">✓ 已儲存</span>}
            {submitState === 'error'   && <span className="status-err">✗ 連線失敗：{errorMsg}</span>}
          </div>
        </div>
      </div>

      {/* 已收錄新聞 */}
      <div className="card">
        <div className="card-header">
          <span className="card-title">已收錄新聞</span>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <span className="tag blue">PostgreSQL</span>
            <span className="tag">{historyLoading ? '…' : `${filtered.length} / ${history.length} 則`}</span>
          </div>
        </div>

        {/* 搜尋列 */}
        <div style={{ padding: '10px 18px', borderBottom: '1px solid var(--border)' }}>
          <input
            className="form-input"
            style={{ width: '100%' }}
            placeholder="搜尋標題、內文、平台、股票代碼…"
            value={query}
            onChange={e => setQuery(e.target.value)}
          />
        </div>

        {historyLoading && (
          <div style={{ padding: '24px', color: 'var(--dim)', textAlign: 'center' }}>載入中…</div>
        )}

        {!historyLoading && filtered.length === 0 && (
          <div className="empty-state">
            <div className="empty-icon">📰</div>
            <div>{query ? '找不到符合的新聞' : '尚無收錄新聞'}</div>
            {!query && <div className="muted" style={{ fontSize: '0.75rem' }}>送出後資料將即時顯示於此</div>}
          </div>
        )}

        {Object.entries(grouped).map(([dateLabel, items]) => (
          <div key={dateLabel}>
            {/* 日期分隔列 */}
            <div style={{
              padding: '6px 18px',
              background: 'var(--hover)',
              borderBottom: '1px solid var(--border)',
              borderTop: '1px solid var(--border)',
              display: 'flex', alignItems: 'center', gap: 10,
            }}>
              <span style={{ fontSize: '0.8125rem', fontWeight: 600, color: 'var(--accent)' }}>{dateLabel}</span>
              <span style={{ fontSize: '0.6875rem', color: 'var(--dim)' }}>{items.length} 則</span>
            </div>

            {items.map(n => {
              const t = new Date(n.submitted_at)
              const timeStr = t.toLocaleTimeString('zh-TW', { hour: '2-digit', minute: '2-digit', hour12: false })
              return (
                <div
                  key={n.id}
                  className="news-card"
                  onClick={() => setSelected(n)}
                  title="點擊查看全文"
                >
                  {/* 時間欄（左側突顯） */}
                  <div style={{
                    minWidth: 48, display: 'flex', flexDirection: 'column',
                    alignItems: 'center', justifyContent: 'flex-start',
                    paddingTop: 2,
                  }}>
                    <span style={{
                      fontSize: '0.9375rem', fontWeight: 700, letterSpacing: 0.5,
                      color: 'var(--accent)', lineHeight: 1.2,
                    }}>{timeStr}</span>
                    <span style={{ fontSize: '0.5625rem', color: 'var(--dim)', marginTop: 3 }}>
                      {n.platform?.split(' ')[0]}
                    </span>
                  </div>

                  <div className="news-body">
                    <div className="news-title">{n.title}</div>
                    <div className="news-meta">
                      <span>{n.platform}</span>
                      {n.tickers?.length > 0 && <span>📌 {n.tickers.join(', ')}</span>}
                      {n.keywords?.length > 0 && (
                        <span style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                          {n.keywords.slice(0, 5).map(k => (
                            <span key={k} style={{
                              fontSize: '0.625rem', padding: '1px 6px', borderRadius: 10,
                              background: 'rgba(99,102,241,0.12)', color: 'var(--accent)',
                            }}>{k}</span>
                          ))}
                        </span>
                      )}
                    </div>
                    {n.content && (
                      <div className="muted" style={{ fontSize: '0.75rem', marginTop: 4, maxHeight: 36, overflow: 'hidden' }}>
                        {n.content.slice(0, 120)}{n.content.length > 120 ? '…' : ''}
                      </div>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        ))}
      </div>
    </>
  )
}
