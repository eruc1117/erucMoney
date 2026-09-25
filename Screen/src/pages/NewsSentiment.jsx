// 需求 4+7+14+15：新聞情緒頁
// 支援即時爬取 & 指定日期範圍歷史爬取（Wayback Machine）

import { useState, useEffect, useRef } from 'react'
import { getNewsList, triggerNewsCrawl, getNewsCrawlStatus } from '../services/api'

const FILTERS = [
  { key: 'all',     label: '全部' },
  { key: 'today',   label: '今日' },
  { key: 'pos',     label: '正面' },
  { key: 'neg',     label: '負面' },
  { key: 'neu',     label: '中性' },
  { key: 'unknown', label: '未分析' },
]

// ── 關鍵字情緒分析 ───────────────────────────────────────────────────────────
const POS_WORDS = [
  '上漲','漲','獲利','盈餘','成長','創新高','突破','看漲','買超','利多',
  '增加','強勁','回升','反彈','樂觀','超越','優於','亮眼','加速','擴大',
  'growth','profit','rise','gain','bull','strong','increase','beat',
  'upgrade','rally','surge','record','high','positive','opportunity',
]
const NEG_WORDS = [
  '下跌','跌','虧損','虧','衰退','創新低','跌破','看跌','賣超','利空',
  '減少','疲軟','下滑','走弱','悲觀','低於','警訊','放緩','縮小','壓力',
  'loss','decline','fall','drop','bear','weak','decrease','miss',
  'downgrade','sell','crash','low','negative','risk','warning',
]

function analyzeSentiment(text) {
  if (!text || text.trim().length < 5) return { label: 'unknown', score: 0, pos: 0, neg: 0 }
  const lower = text.toLowerCase()
  let pos = 0, neg = 0
  POS_WORDS.forEach(w => { if (lower.includes(w.toLowerCase())) pos++ })
  NEG_WORDS.forEach(w => { if (lower.includes(w.toLowerCase())) neg++ })
  const total = pos + neg
  // 完全無關鍵字命中 → 無法分析
  if (total === 0) return { label: 'unknown', score: 0, pos, neg }
  const score = Math.round(((pos - neg) / total) * 100)
  const label = score > 15 ? 'positive' : score < -15 ? 'negative' : 'neutral'
  return { label, score, pos, neg }
}

const SENTIMENT_META = {
  positive: { text: '正面', className: 'bullish', icon: '▲' },
  negative: { text: '負面', className: 'bearish', icon: '▼' },
  neutral:  { text: '中性', className: 'neutral', icon: '─' },
  unknown:  { text: '未知', className: 'unknown',  icon: '?' },
}

function isToday(dateStr) {
  const d = new Date(dateStr), now = new Date()
  return d.getFullYear() === now.getFullYear() &&
         d.getMonth()    === now.getMonth() &&
         d.getDate()     === now.getDate()
}

function todayStr() {
  return new Date().toISOString().slice(0, 10)
}

function dayDiff(start, end) {
  if (!start || !end) return 0
  return Math.round((new Date(end) - new Date(start)) / 86400000) + 1
}

// ── 詳細 Modal ───────────────────────────────────────────────────────────────
function SentimentModal({ news, sentiment, onClose }) {
  function handleOverlayClick(e) {
    if (e.target === e.currentTarget) onClose()
  }

  const meta = SENTIMENT_META[sentiment.label]
  const scoreColor = sentiment.score > 0
    ? 'var(--green)'
    : sentiment.score < 0
    ? 'var(--red)'
    : 'var(--dim)'

  return (
    <div className="modal-overlay" onClick={handleOverlayClick}>
      <div className="modal">
        {/* Header */}
        <div className="modal-header">
          <div className="modal-title">{news.title}</div>
          <button className="btn-icon" onClick={onClose} title="關閉">✕</button>
        </div>

        {/* Body */}
        <div className="modal-body">
          {/* Meta */}
          <div className="news-meta" style={{ marginBottom: 16 }}>
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

          {/* 情緒分析結果 */}
          <div style={{
            background: 'var(--surface)',
            border: '1px solid var(--border)',
            borderRadius: 8,
            padding: '14px 18px',
            marginBottom: 18,
          }}>
            <div style={{ fontSize: '0.6875rem', color: 'var(--dim)', textTransform: 'uppercase', letterSpacing: '.04em', marginBottom: 12 }}>
              情緒分析結果（關鍵字模型）
            </div>
            <div style={{ display: 'flex', gap: 24, alignItems: 'center', flexWrap: 'wrap' }}>
              {/* 情緒標籤 */}
              <div style={{ textAlign: 'center' }}>
                <div style={{ fontSize: '1.75rem', lineHeight: 1 }}>{meta.icon}</div>
                <div style={{ marginTop: 4 }}>
                  <span className={`sentiment-label ${meta.className}`} style={{ fontSize: '0.875rem', padding: '3px 10px' }}>
                    {meta.text}
                  </span>
                </div>
              </div>
              {/* 分數 */}
              <div style={{ textAlign: 'center' }}>
                <div style={{ fontSize: '1.75rem', fontWeight: 700, color: scoreColor, lineHeight: 1 }}>
                  {sentiment.score > 0 ? '+' : ''}{sentiment.score}
                </div>
                <div className="muted" style={{ fontSize: '0.6875rem', marginTop: 4 }}>情緒分數</div>
              </div>
              {/* 關鍵字統計 */}
              <div style={{ display: 'flex', gap: 16 }}>
                <div style={{ textAlign: 'center' }}>
                  <div style={{ fontSize: '1.25rem', fontWeight: 600, color: 'var(--green)', lineHeight: 1 }}>{sentiment.pos}</div>
                  <div className="muted" style={{ fontSize: '0.6875rem', marginTop: 4 }}>正面關鍵字</div>
                </div>
                <div style={{ textAlign: 'center' }}>
                  <div style={{ fontSize: '1.25rem', fontWeight: 600, color: 'var(--red)', lineHeight: 1 }}>{sentiment.neg}</div>
                  <div className="muted" style={{ fontSize: '0.6875rem', marginTop: 4 }}>負面關鍵字</div>
                </div>
              </div>
              {/* 說明 */}
              <div className="muted" style={{ fontSize: '0.6875rem', lineHeight: 1.6, flex: 1, minWidth: 160 }}>
                基於 {POS_WORDS.length + NEG_WORDS.length} 個中英文財經關鍵字<br />
                分析標題與內文詞頻比例
              </div>
            </div>
          </div>

          {/* 關鍵字 */}
          {news.keywords?.length > 0 && (
            <div style={{ marginBottom: 16 }}>
              <div style={{ fontSize: '0.6875rem', color: 'var(--dim)', textTransform: 'uppercase', letterSpacing: '.04em', marginBottom: 8 }}>
                關鍵詞
              </div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                {news.keywords.map(kw => (
                  <span key={kw} style={{
                    fontSize: '0.75rem', padding: '3px 10px', borderRadius: 12,
                    background: 'var(--blue-soft)', color: 'var(--blue)',
                    border: '1px solid var(--blue-soft)',
                  }}>{kw}</span>
                ))}
              </div>
            </div>
          )}

          {/* 全文 */}
          <div style={{ fontSize: '0.875rem', lineHeight: 1.8, whiteSpace: 'pre-wrap', color: 'var(--text)' }}>
            {news.content || <span className="muted">（無內文）</span>}
          </div>
        </div>

        {/* Footer */}
        <div className="modal-footer">
          <div style={{ flex: 1 }} />
          <button className="btn-secondary" onClick={onClose}>關閉</button>
        </div>
      </div>
    </div>
  )
}

// ── 主頁面 ───────────────────────────────────────────────────────────────────
export default function NewsSentiment() {
  const [news, setNews]       = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError]     = useState('')
  const [filter, setFilter]   = useState('all')
  const [selected, setSelected] = useState(null)

  // 日期範圍輸入
  const [startDate, setStartDate] = useState('')
  const [endDate,   setEndDate]   = useState('')

  // 爬蟲狀態
  const [crawlState, setCrawlState] = useState('idle')  // idle | running | done | error
  const [crawlMode,  setCrawlMode]  = useState('')       // realtime | historical
  const [lastCount,  setLastCount]  = useState(null)
  const [crawlMsg,   setCrawlMsg]   = useState('')
  const pollRef = useRef(null)

  async function fetchNews() {
    const { data, error: e } = await getNewsList()
    if (e) setError(e)
    else setNews(data || [])
    setLoading(false)
  }

  useEffect(() => {
    fetchNews()
    return () => clearInterval(pollRef.current)
  }, [])

  function startPolling(mode) {
    pollRef.current = setInterval(async () => {
      const { data } = await getNewsCrawlStatus()
      if (!data) return
      if (data.status === 'idle') {
        clearInterval(pollRef.current)
        setCrawlState('done')
        setLastCount(data.last_count)
        fetchNews()
      }
    }, 2500)
  }

  async function handleRealtimeCrawl() {
    setCrawlState('running')
    setCrawlMode('realtime')
    setCrawlMsg('正在爬取 Yahoo Finance TW & CNN Business 首頁…')
    setLastCount(null)
    const { error: e } = await triggerNewsCrawl()
    if (e) { setCrawlState('error'); return }
    startPolling('realtime')
  }

  async function handleHistoryCrawl() {
    if (!startDate) return
    const ed = endDate || startDate
    const days = dayDiff(startDate, ed)

    setCrawlState('running')
    setCrawlMode('historical')
    setCrawlMsg(
      days === 1
        ? `正在爬取 ${startDate} 的存檔新聞（Wayback Machine）…`
        : `正在爬取 ${startDate} ~ ${ed}（共 ${days} 天）的存檔新聞…`
    )
    setLastCount(null)
    const { error: e } = await triggerNewsCrawl({ start_date: startDate, end_date: ed })
    if (e) { setCrawlState('error'); return }
    startPolling('historical')
  }

  // 情緒分析（加入快取避免重複計算）
  const newsWithSentiment = news.map(n => ({
    ...n,
    sentiment: analyzeSentiment((n.title || '') + ' ' + (n.content || '')),
  }))

  const todayCount   = newsWithSentiment.filter(n => isToday(n.submitted_at)).length
  const posCount     = newsWithSentiment.filter(n => n.sentiment.label === 'positive').length
  const negCount     = newsWithSentiment.filter(n => n.sentiment.label === 'negative').length
  const neuCount     = newsWithSentiment.filter(n => n.sentiment.label === 'neutral').length
  const unknownCount = newsWithSentiment.filter(n => n.sentiment.label === 'unknown').length

  const filtered = newsWithSentiment.filter(n => {
    if (filter === 'today')   return isToday(n.submitted_at)
    if (filter === 'pos')     return n.sentiment.label === 'positive'
    if (filter === 'neg')     return n.sentiment.label === 'negative'
    if (filter === 'neu')     return n.sentiment.label === 'neutral'
    if (filter === 'unknown') return n.sentiment.label === 'unknown'
    return true
  })

  const isRunning = crawlState === 'running'
  const diffDays  = dayDiff(startDate, endDate || startDate)
  const overLimit = diffDays > 7

  // 選中新聞
  const selectedSentiment = selected
    ? analyzeSentiment((selected.title || '') + ' ' + (selected.content || ''))
    : null

  return (
    <>
      {/* 詳細 Modal */}
      {selected && selectedSentiment && (
        <SentimentModal
          news={selected}
          sentiment={selectedSentiment}
          onClose={() => setSelected(null)}
        />
      )}

      {/* Summary Cards */}
      <div className="cards-grid">
        <div className="metric-card">
          <div className="metric-label">已收錄新聞</div>
          <div className="metric-value">{loading ? '…' : news.length}</div>
          <div className="metric-delta muted">使用者提交 + 自動爬取</div>
        </div>
        <div className="metric-card">
          <div className="metric-label">今日新增</div>
          <div className="metric-value">{loading ? '…' : todayCount}</div>
          <div className="metric-delta muted">今日筆數</div>
        </div>
        <div className="metric-card">
          <div className="metric-label">正面 / 負面</div>
          <div className="metric-value" style={{ display: 'flex', gap: 6, alignItems: 'baseline' }}>
            {loading ? '…' : (
              <>
                <span style={{ color: 'var(--green)' }}>{posCount}</span>
                <span className="muted" style={{ fontSize: '0.875rem' }}>/</span>
                <span style={{ color: 'var(--red)' }}>{negCount}</span>
              </>
            )}
          </div>
          <div className="metric-delta muted">關鍵字情緒分析</div>
        </div>
        <div className="metric-card">
          <div className="metric-label">中性</div>
          <div className="metric-value">{loading ? '…' : neuCount}</div>
          <div className="metric-delta muted">有關鍵字但無明顯傾向</div>
        </div>
        <div className="metric-card">
          <div className="metric-label">未分析</div>
          <div className="metric-value" style={{ color: 'var(--dim)' }}>{loading ? '…' : unknownCount}</div>
          <div className="metric-delta muted">無法命中關鍵字（多為標題）</div>
        </div>
      </div>

      {/* 爬取控制 */}
      <div className="card">
        <div className="card-header">
          <span className="card-title">新聞爬蟲</span>
          <div style={{ display: 'flex', gap: 8 }}>
            <span className="tag blue">Yahoo Finance TW</span>
            <span className="tag">CNN Business</span>
          </div>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 0, borderBottom: '1px solid var(--border)' }}>

          {/* 即時爬取 */}
          <div style={{ padding: '16px 18px', borderRight: '1px solid var(--border)' }}>
            <div style={{ fontSize: '0.6875rem', color: 'var(--dim)', textTransform: 'uppercase', letterSpacing: '.04em', marginBottom: 10 }}>
              即時首頁
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
              <button
                className="btn-primary"
                onClick={handleRealtimeCrawl}
                disabled={isRunning}
              >
                {isRunning && crawlMode === 'realtime' ? '爬取中…' : '立即爬取'}
              </button>
              <span className="muted" style={{ fontSize: '0.75rem' }}>抓取目前首頁 ~25 則 × 2 來源</span>
            </div>
          </div>

          {/* 歷史爬取 */}
          <div style={{ padding: '16px 18px' }}>
            <div style={{ fontSize: '0.6875rem', color: 'var(--dim)', textTransform: 'uppercase', letterSpacing: '.04em', marginBottom: 10 }}>
              指定日期範圍（Wayback Machine，上限 7 天）
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <input
                  type="date"
                  className="form-input"
                  style={{ width: 140 }}
                  value={startDate}
                  max={todayStr()}
                  onChange={e => setStartDate(e.target.value)}
                />
                <span className="muted">至</span>
                <input
                  type="date"
                  className="form-input"
                  style={{ width: 140 }}
                  value={endDate}
                  min={startDate || undefined}
                  max={todayStr()}
                  onChange={e => setEndDate(e.target.value)}
                />
              </div>
              <button
                className="btn-secondary"
                onClick={handleHistoryCrawl}
                disabled={isRunning || !startDate || overLimit}
                title={overLimit ? '超過 7 天上限' : ''}
              >
                {isRunning && crawlMode === 'historical' ? '爬取中…' : '執行歷史爬蟲'}
              </button>
              {startDate && (
                <span className="muted" style={{ fontSize: '0.75rem', color: overLimit ? 'var(--red)' : 'var(--dim)' }}>
                  {endDate && endDate !== startDate ? `共 ${diffDays} 天` : '單日'}{overLimit ? '（超過上限）' : ''}
                </span>
              )}
            </div>
          </div>
        </div>

        {/* 狀態列 */}
        <div style={{ padding: '10px 18px', minHeight: 38, display: 'flex', alignItems: 'center', gap: 10 }}>
          {isRunning && (
            <>
              <span className="dot blue blink" />
              <span className="muted" style={{ fontSize: '0.8125rem' }}>{crawlMsg}</span>
            </>
          )}
          {crawlState === 'done' && (
            <span className="status-ok">
              ✓ 爬取完成（{crawlMode === 'historical' ? 'Wayback' : '即時'}），新增 {lastCount} 則（重複略過）
            </span>
          )}
          {crawlState === 'error' && (
            <span className="status-err">✗ 啟動失敗，請確認 FastAPI（:8000）已啟動</span>
          )}
        </div>
      </div>

      {/* News List */}
      <div className="card">
        <div className="card-header">
          <span className="card-title">新聞列表</span>
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
            <span className="tag">{filtered.length} 則</span>
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
        {!loading && !error && filtered.length === 0 && (
          <div className="empty-state">
            <div className="empty-icon">📰</div>
            <div>尚無收錄新聞</div>
            <div className="muted" style={{ fontSize: '0.75rem' }}>點「立即爬取」或選擇日期執行歷史爬蟲</div>
          </div>
        )}

        {filtered.map(n => {
          const meta = SENTIMENT_META[n.sentiment.label]
          return (
            <div
              key={n.id}
              className="news-card"
              onClick={() => setSelected(n)}
              title="點擊查看詳細情緒分析"
              style={{ cursor: 'pointer' }}
            >
              <div className="news-sentiment">
                <span className={`sentiment-label ${meta.className}`}>{meta.text}</span>
                <span className="muted" style={{ fontSize: '0.625rem', marginTop: 4 }}>
                  {n.sentiment.score > 0 ? '+' : ''}{n.sentiment.score}
                </span>
              </div>
              <div className="news-body">
                <div className="news-title">{n.title}</div>
                <div className="news-meta">
                  <span>{n.platform}</span>
                  {n.tickers?.length > 0 && <span>📌 {n.tickers.join(', ')}</span>}
                  <span>{new Date(n.submitted_at).toLocaleString('zh-TW', {
                    month: 'numeric', day: 'numeric',
                    hour: '2-digit', minute: '2-digit',
                  })}</span>
                </div>
                {n.keywords?.length > 0 && (
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 6 }}>
                    {n.keywords.slice(0, 8).map(kw => (
                      <span key={kw} style={{
                        fontSize: '0.625rem', padding: '1px 6px', borderRadius: 10,
                        background: 'var(--blue-soft)', color: 'var(--blue)',
                        border: '1px solid var(--blue-soft)',
                      }}>{kw}</span>
                    ))}
                  </div>
                )}
                {n.content && (
                  <div className="muted" style={{ fontSize: '0.75rem', marginTop: 4, maxHeight: 40, overflow: 'hidden' }}>
                    {n.content.slice(0, 120)}{n.content.length > 120 ? '…' : ''}
                  </div>
                )}
              </div>
            </div>
          )
        })}
      </div>
    </>
  )
}
