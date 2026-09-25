// 需求 2：模型分析未來走向，產出圖表
// 支援 10 種 LSTM 模型，個別或整合預測
//
// 市場切換（台股／美股）：同一批跨股票 LSTM，輸入是 z-score 後的收盤價視窗，
// 與價格尺度無關，所以美股直接套用。差別只在後端去哪張表取價、
// 存進「預測比對」時標記哪個市場。它在美股上一樣沒有 edge（Iteration 32：
// 只用美股自身歷史，走查相關 0.0085），這一點 ModelBar 會照樣標出來。

import { useEffect, useState } from 'react'
import ReactApexChart from 'react-apexcharts'
import { getPrediction, retrainModel, savePrediction,
         triggerCrawler, getCrawlerStatus, normaliseStockId,
         getUsTickers, backfillExogenous } from '../services/api'
import { chartBase, cssColor, cssColors, chartPx, useTheme } from '../theme'
import { addHistory } from '../services/history'
import ModelBar from '../components/ModelBar'

// ── 三層結構定義 ───────────────────────────────────────────────────────────────
// 第一層：模型家族
const FAMILIES = [
  { key: 'lstm',    label: 'LSTM',    icon: '🧠', desc: '長短期記憶網路，10 種架構變體' },
  { key: 'gru',     label: 'GRU',     icon: '⚡', desc: '門控循環單元（開發中）' },
  { key: 'prophet', label: 'Prophet', icon: '📈', desc: 'Facebook 時序預測（開發中）' },
]

// 第二層：群組（隸屬某 family）
const GROUPS = [
  { key: 'basic',        family: 'lstm', label: '基礎 LSTM',   icon: '🔵', desc: '單特徵收盤價序列' },
  { key: 'advanced',     family: 'lstm', label: '進階 LSTM',   icon: '🟣', desc: 'Attention / Seq2Seq / MC Dropout' },
  { key: 'multifeature', family: 'lstm', label: '多特徵 LSTM', icon: '🟠', desc: 'CNN / OHLCV / 技術指標' },
  { key: 'ensemble',     family: 'lstm', label: '集成模型',     icon: '🏆', desc: '多模型加權集成' },
]

// 第三層：個別模型
const MODELS = [
  { key: 'm01_vanilla',       label: 'M01 Vanilla',    color: 'var(--blue)', icon: '🧠', desc: 'Vanilla LSTM · 單特徵基準',       group: 'basic' },
  { key: 'm02_stacked',       label: 'M02 Stacked',    color: 'var(--green)', icon: '📚', desc: 'Stacked LSTM · 3 層堆疊',         group: 'basic' },
  { key: 'm03_bidirectional', label: 'M03 BiLSTM',     color: 'var(--yellow)', icon: '↔️',  desc: 'Bidirectional · 雙向時序',        group: 'basic' },
  { key: 'm04_attention',     label: 'M04 Attention',  color: 'var(--purple)', icon: '👁️',  desc: 'LSTM+Attention · 關鍵步聚焦',     group: 'advanced' },
  { key: 'm07_seq2seq',       label: 'M07 Seq2Seq',    color: 'var(--green)', icon: '⏩', desc: 'Seq2Seq · 多步直接輸出',          group: 'advanced' },
  { key: 'm08_mc_dropout',    label: 'M08 MC Dropout', color: 'var(--orange)', icon: '🎲', desc: 'MC Dropout · 不確定性量化',       group: 'advanced' },
  { key: 'm05_cnn_lstm',      label: 'M05 CNN-LSTM',   color: 'var(--red)', icon: '🔍', desc: 'CNN-LSTM · 局部+長程特徵',        group: 'multifeature' },
  { key: 'm06_multifeature',  label: 'M06 Multi',      color: 'var(--blue)', icon: '📊', desc: 'Multi-feature · OHLCV+籌碼',     group: 'multifeature' },
  { key: 'm09_technical',     label: 'M09 Technical',  color: 'var(--orange)', icon: '📈', desc: 'LSTM+技術指標 · 20 特徵',         group: 'multifeature' },
  { key: 'm10_ensemble',      label: 'M10 Ensemble',   color: 'var(--purple)', icon: '🏆', desc: 'Ensemble · M01+M02+M03 加權',    group: 'ensemble' },
]

const DEFAULT_SELECTED = new Set(['m02_stacked', 'm09_technical'])
const VIEW_MODES = ['個別', '整合']

// 市場：決定後端查哪張價格表、存檔時標記哪個市場，以及 ModelBar 顯示哪組模型
const MARKETS = [
  { key: 'tw', label: '台股', defaultStock: '2330', unit: '元',
    note: '這一頁的十個模型實測 MAE 全落在 5.17~5.25，天真基準（明日＝今日）是 5.20——價格序列本身沒有訊號（Iteration 11）。' },
  { key: 'us', label: '美股', defaultStock: 'TSM', unit: '美元',
    note: '同一批 LSTM 套在美股上。Iteration 32 實測只用美股自身歷史，走查相關 0.0085 ≈ 0——這裡的曲線是參考，不是訊號；日期為美東場次日期。' },
]
const US_CATEGORY = { index: '指數 ETF', semiconductor: '半導體', equipment: '半導體設備',
                      tw_adr: '台股 ADR', tw_etf: '台股 ETF', bigtech: '大型科技' }

// ── 圖表設定 ───────────────────────────────────────────────────────────────────
// 圖表底層設定隨主題切換。ApexCharts 會把顏色直接寫進 SVG 屬性、不吃 CSS 變數，
// 所以顏色必須在 JS 這邊給，且要在 render 當下才讀——寫成模組層級的常數
// 就會永遠停在載入時的那個主題。
function chartBaseNow(extra) {
  const b = chartBase(document.documentElement.dataset.theme)
  return extra ? { ...b, chart: { ...b.chart, ...extra } } : b
}

function buildLineOptions(color, dates) {
  return {
    ...chartBaseNow(),
    chart: { ...chartBaseNow().chart, type: 'line', height: 220 },
    xaxis: {
      categories: dates,
      labels: { style: { colors: cssColor('var(--dim)'), fontSize: chartPx(0.6875) }, rotate: -30 },
      tickAmount: 7,
    },
    yaxis: { labels: { style: { colors: cssColor('var(--dim)'), fontSize: chartPx(0.6875) } } },
    stroke: { curve: 'smooth', width: 2, colors: [cssColor(color)] },
    colors: [cssColor(color)],
    markers: { size: 4, colors: [cssColor(color)] },
    dataLabels: { enabled: false },
  }
}

function buildIntegratedOptions(dates, colors) {
  colors = cssColors(colors)   // 系列色可能是 CSS 變數，Apex 得吃實際色值
  return {
    ...chartBaseNow(),
    chart: { ...chartBaseNow().chart, type: 'line', height: 320 },
    xaxis: {
      categories: dates,
      labels: { style: { colors: cssColor('var(--dim)'), fontSize: chartPx(0.6875) }, rotate: -30 },
      tickAmount: 7,
    },
    yaxis: { labels: { style: { colors: cssColor('var(--dim)'), fontSize: chartPx(0.6875) } } },
    stroke: { curve: 'smooth', width: 2 },
    colors,
    markers: { size: 3 },
    dataLabels: { enabled: false },
    legend: { position: 'top', labels: { colors: cssColor('var(--dim)') }, fontSize: chartPx(0.75) },
  }
}

function nextNDates(n) {
  const dates = []
  const base = new Date()
  for (let i = 1; i <= n; i++) {
    const d = new Date(base); d.setDate(base.getDate() + i)
    dates.push(d.toISOString().slice(0, 10))
  }
  return dates
}

const initModelData = () =>
  Object.fromEntries(MODELS.map(m => [m.key, { dates: [], values: [], ciLow: [], ciHigh: [], loading: false, error: '' }]))

// ── 元件 ───────────────────────────────────────────────────────────────────────
export default function Prediction() {
  useTheme()   // 訂閱主題：切換時重新 render，圖表才會換色
  const [market, setMarket]           = useState('tw')
  const [usTickers, setUsTickers]     = useState([])
  const [targetStock, setTargetStock] = useState('2330')
  const [predDays, setPredDays]       = useState(7)
  const [viewMode, setViewMode]       = useState('個別')
  const [selected, setSelected]       = useState(new Set(DEFAULT_SELECTED))
  const [modelData, setModelData]     = useState(initModelData)
  const [savedKeys, setSavedKeys]       = useState(new Set())
  const [activeFamily, setActiveFamily] = useState('lstm')
  const [activeGroup, setActiveGroup]   = useState('basic')
  const [retrainState, setRetrainState] = useState('idle')
  const [retrainMsg, setRetrainMsg]     = useState('')
  // 補資料：預測失敗在「這檔沒有行情」時，直接在頁面上把資料抓回來再重試
  const [backfill, setBackfill] = useState({ state: 'idle', msg: '' })
  const [saveAll, setSaveAll]   = useState({ state: 'idle', msg: '' })

  const mk = MARKETS.find(m => m.key === market) ?? MARKETS[0]

  // 美股標的清單是固定的（Iteration 34 起 23 檔），用下拉選單而不是自由輸入——輸入 'tsm' 或 '2330'
  // 得到的都只是「資料不足」，不如一開始就只給能選的
  useEffect(() => {
    let alive = true
    getUsTickers().then(({ data }) => { if (alive && data?.items) setUsTickers(data.items) })
    return () => { alive = false }
  }, [])

  // 切市場：清掉舊結果（台股 2330 的曲線掛在美股頁上會誤導），換預設標的
  function switchMarket(key) {
    if (key === market) return
    const next = MARKETS.find(m => m.key === key)
    setMarket(key)
    setTargetStock(next.defaultStock)
    setModelData(initModelData())
    setBackfill({ state: 'idle', msg: '' })
  }

  // 這檔的行情不足時，直接觸發爬蟲補資料，補完自動重跑選中的模型。
  // 沒有這個入口的話，使用者只會看到「資料不足」然後卡住——
  // 而補資料本來就是系統做得到的事（個股分析頁早就有同一套流程）。
  async function backfillAndRetry() {
    const sid = normaliseStockId(targetStock)
    if (!sid) return
    if (market === 'us') {
      // 美股走外生資料那條路（與排程 06:10／19:10 同一個函式），一次補全部標的
      setBackfill({ state: 'running', msg: '正在補齊美股／台指期／韓日指數…' })
      const { data, error } = await backfillExogenous()
      if (error) { setBackfill({ state: 'error', msg: `補齊失敗：${error}` }); return }
      setBackfill({ state: 'done', msg: `${data?.reason ?? '已完成'}，正在重跑模型…` })
      MODELS.filter(m => selected.has(m.key)).forEach(m => runModel(m.key))
      return
    }
    setBackfill({ state: 'running', msg: `正在抓取 ${sid} 的歷史行情…` })
    const { error } = await triggerCrawler(sid)
    if (error) {
      setBackfill({ state: 'error', msg: `爬蟲觸發失敗：${error}` })
      return
    }
    // 爬蟲是背景執行，要輪詢到 idle 才知道抓完了
    for (let i = 0; i < 60; i++) {
      await new Promise(r => setTimeout(r, 2000))
      const { data } = await getCrawlerStatus(sid)
      if (data?.status !== 'running') break
      setBackfill({ state: 'running', msg: `正在抓取 ${sid} 的歷史行情…（${(i + 1) * 2} 秒）` })
    }
    setBackfill({ state: 'done', msg: `${sid} 資料已更新，正在重跑模型…` })
    MODELS.filter(m => selected.has(m.key)).forEach(m => runModel(m.key))
  }

  function toggleModel(key) {
    setSelected(prev => {
      const next = new Set(prev)
      next.has(key) ? next.delete(key) : next.add(key)
      return next
    })
  }

  async function runModel(modelKey) {
    setModelData(prev => ({ ...prev, [modelKey]: { ...prev[modelKey], loading: true, error: '' } }))
    const { data, error } = await getPrediction(targetStock, modelKey, predDays, market)
    // 預測端點正常時回傳陣列；後端錯誤會回 { detail }。
    // 舊版只檢查 `!data`，物件同樣是真值 → data.map is not a function 讓整頁崩潰。
    if (error || !Array.isArray(data) || data.length === 0) {
      // 訊息一律優先用後端說的話。「回應格式非預期」只有在後端既沒回錯誤、
      // 也沒回陣列時才會出現——那種情況使用者也無從處理，所以要寫清楚下一步。
      const msg = error || data?.detail
        || (Array.isArray(data) ? '此股票沒有可用的預測結果（資料可能不足）'
                                : '後端回傳了非預期的內容，請確認 LSTM 預測伺服器（:8001）是否正常')
      setModelData(prev => ({ ...prev, [modelKey]: { ...prev[modelKey], loading: false, error: msg } }))
      return
    }
    setModelData(prev => ({
      ...prev,
      [modelKey]: {
        dates:   data.map(r => r.date),
        values:  data.map(r => r.predicted_close),
        ciLow:   data.map(r => r.ci_low),
        ciHigh:  data.map(r => r.ci_high),
        loading: false,
        error:   '',
      },
    }))
    const m = MODELS.find(m => m.key === modelKey)
    addHistory({ type: 'stock',
                 query: `${market === 'us' ? '美股 ' : ''}${targetStock} ${m?.label ?? modelKey} 預測`,
                 result: '已完成' })
  }

  function runSelected() {
    MODELS.filter(m => selected.has(m.key)).forEach(m => runModel(m.key))
  }

  function clearResult(modelKey) {
    setModelData(prev => ({
      ...prev,
      [modelKey]: { dates: [], values: [], ciLow: [], ciHigh: [], loading: false, error: '' },
    }))
  }

  // 單筆與「全部儲存」走同一條組裝路徑，避免兩邊的欄位或代號處理走鐘
  function buildPayload(modelKey) {
    const d = modelData[modelKey]
    if (!d?.values.length) return null
    const m = MODELS.find(m => m.key === modelKey)
    return {
      stock_id:    market === 'us' ? normaliseStockId(targetStock).toUpperCase()
                                   : normaliseStockId(targetStock),
      market,
      model_key:   modelKey,
      model_label: m?.label ?? modelKey,
      predictions: d.dates.map((date, i) => ({
        date,
        predicted_close: d.values[i],
        ci_low:  d.ciLow?.[i] ?? null,
        ci_high: d.ciHigh?.[i] ?? null,
      })),
    }
  }

  function markSaved(keys) {
    setSavedKeys(prev => new Set([...prev, ...keys]))
    setTimeout(() => setSavedKeys(prev => {
      const n = new Set(prev)
      keys.forEach(k => n.delete(k))
      return n
    }), 3000)
  }

  async function handleSave(modelKey) {
    const payload = buildPayload(modelKey)
    if (!payload) return
    const { error } = await savePrediction(payload)
    if (error) { setSaveAll({ state: 'error', msg: `儲存失敗：${error}` }); return }
    markSaved([modelKey])
  }

  // 全部儲存：把目前所有有結果的模型一次存進「預測比對」。
  // 逐一按 💾 在同時跑十個模型時很煩，而且容易漏存——
  // 漏掉的那個之後就沒有比對紀錄，等於白跑一次。
  async function handleSaveAll() {
    const keys = MODELS.filter(m => modelData[m.key]?.values.length).map(m => m.key)
    if (!keys.length) return
    setSaveAll({ state: 'running', msg: `儲存中… 0/${keys.length}` })

    const failed = []
    let done = 0
    for (const key of keys) {
      const payload = buildPayload(key)
      if (!payload) continue
      const { error } = await savePrediction(payload)
      if (error) failed.push(`${key}：${error}`)
      done += 1
      setSaveAll({ state: 'running', msg: `儲存中… ${done}/${keys.length}` })
    }
    markSaved(keys.filter(k => !failed.some(f => f.startsWith(k))))
    setSaveAll(failed.length
      ? { state: 'error',
          msg: `${keys.length - failed.length}/${keys.length} 筆已存，${failed.length} 筆失敗：${failed[0]}` }
      : { state: 'done', msg: `已儲存 ${keys.length} 筆預測，可到「預測比對」頁查看` })
    setTimeout(() => setSaveAll({ state: 'idle', msg: '' }), 6000)
  }

  function removeBlock(modelKey) {
    clearResult(modelKey)
    setSelected(prev => { const next = new Set(prev); next.delete(modelKey); return next })
  }

  function removeAllBlocks() {
    selectedModels.forEach(m => clearResult(m.key))
    setSelected(new Set())
  }

  async function handleRetrain() {
    setRetrainState('running'); setRetrainMsg('')
    const { error } = await retrainModel(targetStock)
    if (error) { setRetrainState('error'); setRetrainMsg(error); return }
    setRetrainState('done'); setRetrainMsg('模型重訓已啟動')
    setTimeout(() => setRetrainState('idle'), 5000)
  }

  // ── 整合模式資料 ─────────────────────────────────────────────────────────────
  const selectedModels = MODELS.filter(m => selected.has(m.key))
  const integratedDates = selectedModels.reduce((acc, m) =>
    acc.length ? acc : modelData[m.key].dates, []
  ).length ? selectedModels.reduce((acc, m) => acc.length ? acc : modelData[m.key].dates, []) : nextNDates(predDays)

  const avgValues = integratedDates.map((_, i) => {
    const vals = selectedModels.map(m => modelData[m.key].values[i]).filter(v => v != null)
    return vals.length ? +(vals.reduce((a, b) => a + b, 0) / vals.length).toFixed(2) : null
  })

  const integratedSeries = [
    ...selectedModels.map(m => ({ name: m.label, data: modelData[m.key].values })),
    ...(selectedModels.length > 1 ? [{ name: '加權平均', data: avgValues }] : []),
  ]
  const integratedColors = [
    ...selectedModels.map(m => m.color),
    ...(selectedModels.length > 1 ? ['var(--text-strong)'] : []),
  ]

  const savableCount = MODELS.filter(m => modelData[m.key]?.values.length).length

  const saveAllBar = saveAll.state !== 'idle' && saveAll.state !== 'running' && (
    <div className="card">
      <div style={{ padding: '.85rem 1.25rem', fontSize: '.88rem',
                    color: saveAll.state === 'error' ? 'var(--red)' : 'var(--green)' }}>
        {saveAll.state === 'done' ? '✓ ' : '✗ '}{saveAll.msg}
      </div>
    </div>
  )

  const backfillBar = backfill.state !== 'idle' && (
    <div className="card">
      <div style={{ padding: '.85rem 1.25rem', fontSize: '.88rem',
                    color: backfill.state === 'error' ? 'var(--red)'
                         : backfill.state === 'done' ? 'var(--green)' : 'var(--text)' }}>
        {backfill.state === 'running' && '⏳ '}
        {backfill.msg}
        {backfill.state === 'running' && (
          <span className="muted" style={{ marginLeft: '.5rem', fontSize: '.8rem' }}>
            首次抓取整段歷史可能要一分鐘以上
          </span>
        )}
      </div>
    </div>
  )

  return (
    <>
      <ModelBar page={market === 'us' ? 'predict_us' : 'predict'} note={mk.note} />
      {backfillBar}
      {saveAllBar}
      {/* ── 設定區 ── */}
      <div className="card">
        <div className="card-header">
          <span className="card-title">預測設定</span>
          <span className="tag green">{selected.size} 個模型已選</span>
        </div>
        <div className="model-controls">
          {/* 市場 + 股票 + 天數 + 視圖 */}
          <div className="ctrl-group">
            <label className="ctrl-label">市場</label>
            <div className="btn-group">
              {MARKETS.map(m => (
                <button key={m.key} className={`btn-period${market === m.key ? ' active' : ''}`}
                        onClick={() => switchMarket(m.key)}>{m.label}</button>
              ))}
            </div>
          </div>
          <div className="ctrl-group">
            <label className="ctrl-label">{market === 'us' ? '目標標的' : '目標股票'}</label>
            {market === 'us' ? (
              <select className="ctrl-select" value={targetStock}
                      onChange={e => setTargetStock(e.target.value)} style={{ minWidth: 200 }}>
                {usTickers.length === 0 && <option value={targetStock}>{targetStock}</option>}
                {usTickers.map(t => (
                  <option key={t.ticker} value={t.ticker}>
                    {t.ticker}　{t.name}{t.category ? `（${US_CATEGORY[t.category] ?? t.category}）` : ''}
                  </option>
                ))}
              </select>
            ) : (
              <input
                className="ctrl-select"
                value={targetStock}
                onChange={e => setTargetStock(e.target.value)}
                placeholder="股票代碼"
                style={{ width: 120 }}
              />
            )}
          </div>
          <div className="ctrl-group">
            <label className="ctrl-label">預測天數</label>
            <select className="ctrl-select" value={predDays} onChange={e => setPredDays(Number(e.target.value))}>
              <option value={3}>3 天</option>
              <option value={7}>7 天</option>
              <option value={14}>14 天</option>
            </select>
          </div>
          <div className="ctrl-group">
            <label className="ctrl-label">顯示模式</label>
            <div className="btn-group">
              {VIEW_MODES.map(v => (
                <button key={v} className={`btn-period${viewMode === v ? ' active' : ''}`} onClick={() => setViewMode(v)}>{v}</button>
              ))}
            </div>
          </div>
          <button className="btn-primary" onClick={runSelected}>執行預測（已選）</button>
          <button className="btn-secondary" onClick={handleSaveAll}
                  disabled={savableCount === 0 || saveAll.state === 'running'}
                  title={savableCount === 0
                    ? '先執行預測才有東西可存'
                    : `把 ${savableCount} 個模型的預測一次存進「預測比對」`}>
            {saveAll.state === 'running' ? saveAll.msg : `💾 全部儲存${savableCount ? `（${savableCount}）` : ''}`}
          </button>
          {/* 重訓只有台股：train_cross.py 讀的是 stock_daily_prices，美股沒有對應流程 */}
          {market === 'tw' && (
            <button className="btn-secondary" onClick={handleRetrain} disabled={retrainState === 'running'}>
              {retrainState === 'running' ? '重訓中...' : '重新訓練'}
            </button>
          )}
        </div>

        {/* ── 模型選擇（三層）── */}
        <div style={{ padding: '0 18px 16px' }}>
          <div className="ctrl-label" style={{ marginBottom: 8 }}>選擇模型</div>

          {/* 第一層：模型家族 LSTM / GRU / Prophet */}
          <div style={{ display: 'flex', gap: 8, marginBottom: 10 }}>
            {FAMILIES.map(f => {
              const familySelected = MODELS.filter(m =>
                GROUPS.find(g => g.key === m.group)?.family === f.key && selected.has(m.key)
              ).length
              const isActive = activeFamily === f.key
              return (
                <button
                  key={f.key}
                  onClick={() => {
                    setActiveFamily(f.key)
                    const firstGroup = GROUPS.find(g => g.family === f.key)
                    if (firstGroup) setActiveGroup(firstGroup.key)
                  }}
                  style={{
                    flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'flex-start',
                    gap: 3, padding: '10px 14px', borderRadius: 6, cursor: 'pointer',
                    border: `1px solid ${isActive ? 'var(--blue)' : 'var(--border)'}`,
                    background: isActive ? 'var(--blue-soft)' : 'transparent',
                    color: isActive ? 'var(--blue)' : 'var(--dim)',
                    transition: 'all .15s', textAlign: 'left',
                  }}
                >
                  <span style={{ fontSize: '0.875rem', fontWeight: 700 }}>{f.icon} {f.label}</span>
                  <span style={{ fontSize: '0.625rem', opacity: .7 }}>{f.desc}</span>
                  {familySelected > 0 && (
                    <span style={{ fontSize: '0.625rem', marginTop: 2, background: 'var(--blue-soft)', color: 'var(--blue)', padding: '1px 6px', borderRadius: 10 }}>
                      已選 {familySelected}
                    </span>
                  )}
                </button>
              )
            })}
          </div>

          {/* 第二層：群組（僅顯示當前 family 的群組） */}
          {GROUPS.some(g => g.family === activeFamily) ? (
            <>
              <div style={{ display: 'flex', gap: 6, marginBottom: 8 }}>
                {GROUPS.filter(g => g.family === activeFamily).map(g => {
                  const cnt = MODELS.filter(m => m.group === g.key && selected.has(m.key)).length
                  const isActive = activeGroup === g.key
                  return (
                    <button
                      key={g.key}
                      onClick={() => setActiveGroup(g.key)}
                      style={{
                        display: 'flex', alignItems: 'center', gap: 6,
                        padding: '6px 12px', borderRadius: 6, cursor: 'pointer',
                        border: `1px solid ${isActive ? 'var(--yellow)' : 'var(--border)'}`,
                        background: isActive ? 'var(--yellow-soft)' : 'transparent',
                        color: isActive ? 'var(--yellow)' : 'var(--dim)',
                        fontSize: '0.75rem', fontWeight: 600, transition: 'all .15s',
                      }}
                    >
                      {g.icon} {g.label}
                      {cnt > 0 && (
                        <span style={{ background: 'var(--yellow-soft)', color: 'var(--yellow)', padding: '0 5px', borderRadius: 8, fontSize: '0.625rem' }}>
                          {cnt}
                        </span>
                      )}
                    </button>
                  )
                })}
              </div>

              {/* 第三層：個別模型 */}
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                {MODELS.filter(m => m.group === activeGroup).map(m => {
                  const on = selected.has(m.key)
                  return (
                    <button
                      key={m.key}
                      onClick={() => toggleModel(m.key)}
                      style={{
                        display: 'flex', flexDirection: 'column', alignItems: 'flex-start',
                        gap: 2, padding: '8px 12px', borderRadius: 6, cursor: 'pointer',
                        border: `1px solid ${on ? m.color : 'var(--border)'}`,
                        background: on ? `${m.color}18` : 'transparent',
                        color: on ? m.color : 'var(--dim)',
                        transition: 'all .15s', textAlign: 'left', minWidth: 140,
                      }}
                    >
                      <span style={{ fontSize: '0.8125rem', fontWeight: 600 }}>{m.icon} {m.label}</span>
                      <span style={{ fontSize: '0.625rem', opacity: .75, lineHeight: 1.3 }}>{m.desc}</span>
                    </button>
                  )
                })}
              </div>
            </>
          ) : (
            <div style={{ padding: '20px 0', color: 'var(--dim)', fontSize: '0.8125rem' }}>
              🚧 {FAMILIES.find(f => f.key === activeFamily)?.label} 模型開發中，敬請期待
            </div>
          )}
        </div>

        {retrainState !== 'idle' && (
          <div className="retrain-status" style={{ margin: '0 18px 14px' }}>
            <span className={`dot ${retrainState === 'error' ? 'red' : 'green'}${retrainState === 'running' ? ' blink' : ''}`} />
            <span>{retrainMsg || (retrainState === 'running' ? '模型重訓中...' : '')}</span>
          </div>
        )}
      </div>

      {/* ── 個別模式 ── */}
      {viewMode === '個別' && (
        <div className="models-grid">
          {MODELS.filter(m => selected.has(m.key)).map(m => {
            const d = modelData[m.key]
            const lineOpts = buildLineOptions(m.color, d.dates.length ? d.dates : nextNDates(predDays))
            return (
              <div className="card" key={m.key}>
                <div className="card-header">
                  <span className="card-title">{m.icon} {m.label}</span>
                  <span className="tag" style={{ color: m.color, background: `${m.color}18` }}>{m.desc}</span>
                  <button className="btn-chip" onClick={() => runModel(m.key)} disabled={d.loading}>
                    {d.loading ? '計算中...' : '執行'}
                  </button>
                  {d.values.length > 0 && (
                    <button
                      className="btn-chip"
                      onClick={() => handleSave(m.key)}
                      title="儲存此預測以供日後比對"
                      style={{ color: savedKeys.has(m.key) ? 'var(--green)' : 'var(--dim)' }}
                    >
                      {savedKeys.has(m.key) ? '✓ 已儲存' : '💾 儲存'}
                    </button>
                  )}
                  <button
                    className="btn-chip"
                    onClick={() => removeBlock(m.key)}
                    title="刪除此區塊"
                    style={{ color: 'var(--dim)' }}
                  >
                    ✕
                  </button>
                </div>

                {d.error && (
                  <div className="alert-error" style={{ margin: '12px 18px' }}>
                    {d.error}
                    {/^.*資料不足|沒有這檔|找不到/.test(d.error) && (
                      <button className="btn-secondary" style={{ marginLeft: '.6rem' }}
                              disabled={backfill.state === 'running'}
                              onClick={backfillAndRetry}>
                        {backfill.state === 'running' ? '補資料中…' : '補足資料並重試'}
                      </button>
                    )}
                  </div>
                )}

                {d.values.length > 0 ? (
                  <>
                    <div className="chart-pad">
                      <ReactApexChart
                        type="line"
                        series={[{ name: `${m.label} 預測`, data: d.values }]}
                        options={lineOpts}
                        height={220}
                      />
                    </div>
                    <div className="table-wrap">
                      <table className="data-table">
                        <thead>
                          <tr><th>日期</th><th>預測收盤</th><th>95% 下界</th><th>95% 上界</th></tr>
                        </thead>
                        <tbody>
                          {d.dates.map((date, i) => (
                            <tr key={date}>
                              <td>{date}</td>
                              <td className="up"><strong>{d.values[i]?.toFixed(2)}</strong></td>
                              <td className="muted">{d.ciLow?.[i]?.toFixed(2) ?? '–'}</td>
                              <td className="muted">{d.ciHigh?.[i]?.toFixed(2) ?? '–'}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </>
                ) : !d.loading && !d.error ? (
                  <div className="empty-state" style={{ padding: '30px 0' }}>
                    <div className="muted">點擊「執行」取得預測結果</div>
                  </div>
                ) : null}
              </div>
            )
          })}
        </div>
      )}

      {/* ── 整合模式 ── */}
      {viewMode === '整合' && (
        <div className="card">
          <div className="card-header">
            <span className="card-title">整合預測 — {market === 'us' ? '美股 ' : ''}{targetStock}</span>
            <span className="tag blue">{selectedModels.map(m => m.label).join(' + ')}</span>
            <button
              className="btn-chip"
              onClick={removeAllBlocks}
              title="刪除所有區塊"
              style={{ color: 'var(--dim)' }}
            >
              ✕ 刪除全部
            </button>
          </div>
          {integratedSeries.some(s => s.data.length > 0) ? (
            <>
              <div className="chart-pad">
                <ReactApexChart
                  type="line"
                  series={integratedSeries}
                  options={buildIntegratedOptions(integratedDates, integratedColors)}
                  height={320}
                />
              </div>
              <div className="table-wrap">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>日期</th>
                      {selectedModels.map(m => <th key={m.key} style={{ color: m.color }}>{m.label}</th>)}
                      {selectedModels.length > 1 && <th>加權平均</th>}
                    </tr>
                  </thead>
                  <tbody>
                    {integratedDates.map((date, i) => (
                      <tr key={date}>
                        <td>{date}</td>
                        {selectedModels.map(m => (
                          <td key={m.key} style={{ color: m.color }}>
                            {modelData[m.key].values[i]?.toFixed(2) ?? <span className="muted">–</span>}
                          </td>
                        ))}
                        {selectedModels.length > 1 && (
                          <td className="up"><strong>{avgValues[i]?.toFixed(2) ?? '–'}</strong></td>
                        )}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          ) : (
            <div className="empty-state">
              <div className="empty-icon">🤖</div>
              <div>請先點擊「執行預測（已選）」</div>
            </div>
          )}
        </div>
      )}
    </>
  )
}
