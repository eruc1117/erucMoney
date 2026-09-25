// 需求  3：畫面輸入需要撈取的股票資料
// 需求  6：當輸入的股票資料不在資料庫中，才去執行爬蟲
// 需求 10：執行爬蟲時，前端提供進度條畫面，及完成通知
// 需求 11：個股分析加上時間範圍，預設 1 週，上限 1 個月，時間單位為週

import { useState, useEffect, useMemo, useRef } from 'react'
import { chartBase, cssColor, cssColors, chartPx, useTheme } from '../theme'
import ReactApexChart from 'react-apexcharts'
import {
  getStockInfo, getStockPrices, getChipData,
  triggerCrawler, getCrawlerStatus, getStockPricesHistory,
} from '../services/api'
import { addHistory } from '../services/history'
import ModelBar from '../components/ModelBar'
import { shortDate, holdingLag, holdingTitle } from '../services/holding'

// 圖表底層設定隨主題切換。ApexCharts 會把顏色直接寫進 SVG 屬性、不吃 CSS 變數，
// 所以顏色必須在 JS 這邊給，且要在 render 當下才讀——寫成模組層級的常數
// 就會永遠停在載入時的那個主題。
function chartBaseNow(extra) {
  const b = chartBase(document.documentElement.dataset.theme)
  return extra ? { ...b, chart: { ...b.chart, ...extra } } : b
}

// ── 可拖曳調整高度的圖表容器 ────────────────────────────────────────────────
// chartId：用內容命名的唯一識別（如 'kline', 'volume'），高度存入 localStorage
function ResizableChart({ chartId, defaultHeight, minHeight = 100, className = 'chart-pad', children }) {
  const storageKey = `chart_h_${chartId}`
  const saved = parseInt(localStorage.getItem(storageKey), 10)
  const [height, setHeight] = useState(!isNaN(saved) ? saved : defaultHeight)
  const startY = useRef(null)
  const startH = useRef(null)

  function onMouseDown(e) {
    e.preventDefault()
    startY.current = e.clientY
    startH.current = height
    function onMove(ev) {
      const h = Math.max(minHeight, startH.current + (ev.clientY - startY.current))
      setHeight(h)
      localStorage.setItem(storageKey, h)
    }
    function onUp() {
      document.removeEventListener('mousemove', onMove)
      document.removeEventListener('mouseup', onUp)
    }
    document.addEventListener('mousemove', onMove)
    document.addEventListener('mouseup', onUp)
  }

  return (
    <div>
      <div className={className}>
        {children(height)}
      </div>
      <div
        onMouseDown={onMouseDown}
        title="拖曳調整圖表高度"
        style={{
          height: 10,
          cursor: 'ns-resize',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          margin: '2px 12px 0',
          borderTop: '2px solid var(--border)',
          userSelect: 'none',
          color: 'var(--dim)',
          fontSize: '0.625rem',
          letterSpacing: 3,
        }}
      >
        ···
      </div>
    </div>
  )
}

const WEEK_OPTIONS        = [1, 2, 3, 4]   // 1週=7天 … 4週=28天（上限1個月）
const CRAWL_COOLDOWN_MS   = 30 * 60 * 1000 // 前端冷卻 30 分鐘（localStorage）

// LOAD STATE:  idle | loading | found | notfound | error
// CRAWL STATE: idle | confirming | running | done | error
export default function StockAnalysis({ initStock = '' }) {
  useTheme()   // 訂閱主題：切換時重新 render，圖表才會換色
  const [inputVal,   setInputVal]   = useState(initStock)
  const [stockId,    setStockId]    = useState('')
  const [weeks,      setWeeks]      = useState(1)          // 需求 11：預設 1 週

  const [info,   setInfo]   = useState(null)
  const [prices, setPrices] = useState([])
  const [chips,  setChips]  = useState(null)

  const [loadState,  setLoadState]  = useState('idle')
  const [crawlState, setCrawlState] = useState('idle')
  const [errorMsg,   setErrorMsg]   = useState('')

  // 需求 10：進度條 + 完成通知
  const [progress,   setProgress]   = useState(0)
  const [countdown,  setCountdown]  = useState(0)
  const [showToast,  setShowToast]  = useState(false)
  const progressRef    = useRef(null)
  const pollRef        = useRef(null)
  const countRef       = useRef(null)
  const autoCrawledRef = useRef(false)   // 本次查詢是否已自動觸發過爬蟲

  // ── 歷史資料補充 ─────────────────────────────────────────────
  const today1YAgo = new Date(); today1YAgo.setFullYear(today1YAgo.getFullYear() - 1)
  const [histStart,    setHistStart]    = useState(today1YAgo.toISOString().slice(0, 10))
  const [histEnd,      setHistEnd]      = useState(new Date().toISOString().slice(0, 10))
  const [histState,    setHistState]    = useState('idle')   // idle|running|done|error
  const [histProgress, setHistProgress] = useState(0)
  const [histMsg,      setHistMsg]      = useState('')
  const histProgressRef = useRef(null)
  const histPollRef     = useRef(null)

  // ── 全部歷史行情 ────────────────────────────────────────────────────────
  const [histAll,      setHistAll]      = useState([])
  const [histAllState, setHistAllState] = useState('idle')  // idle | loading | loaded | error
  const [histAllError, setHistAllError] = useState('')

  // ── 進度條動畫（爬蟲執行中時，模擬進度到 85%）────────────────
  useEffect(() => {
    if (crawlState !== 'running') return
    setProgress(5)
    progressRef.current = setInterval(() => {
      setProgress(prev => {
        if (prev >= 85) return prev
        return +(prev + (Math.random() * 7 + 1)).toFixed(1)
      })
    }, 700)
    return () => clearInterval(progressRef.current)
  }, [crawlState])

  // ── Polling 查詢爬蟲狀態（每 2 秒）────────────────────────────
  useEffect(() => {
    if (crawlState !== 'running' || !stockId) return
    pollRef.current = setInterval(async () => {
      const { data } = await getCrawlerStatus(stockId)
      if (data && data.status === 'idle') {
        clearInterval(pollRef.current)
        clearInterval(progressRef.current)
        setProgress(100)
        setCrawlState('done')
        // 完成通知倒數 5 秒後自動重新查詢
        setShowToast(true)
        setCountdown(5)
        addHistory({ type: 'stock', query: stockId, result: '爬蟲完成' })
      }
    }, 2000)
    return () => clearInterval(pollRef.current)
  }, [crawlState, stockId])

  // ── 歷史補充進度動畫 ────────────────────────────────────────────
  useEffect(() => {
    if (histState !== 'running') return
    setHistProgress(5)
    histProgressRef.current = setInterval(() => {
      setHistProgress(prev => prev >= 85 ? prev : +(prev + (Math.random() * 5 + 1)).toFixed(1))
    }, 800)
    return () => clearInterval(histProgressRef.current)
  }, [histState])

  // ── 歷史補充 Polling ────────────────────────────────────────────
  useEffect(() => {
    if (histState !== 'running' || !stockId) return
    histPollRef.current = setInterval(async () => {
      const { data } = await getCrawlerStatus(stockId)
      if (data && data.status === 'idle') {
        clearInterval(histPollRef.current)
        clearInterval(histProgressRef.current)
        setHistProgress(100)
        setHistState('done')
        setHistMsg('歷史資料補充完成，可重新查詢檢視')
        addHistory({ type: 'stock', query: stockId, result: '歷史補充完成', detail: `${histStart} ~ ${histEnd}` })
      }
    }, 2000)
    return () => clearInterval(histPollRef.current)
  }, [histState, stockId])

  // ── 倒數計時後自動重新查詢 ─────────────────────────────────────
  useEffect(() => {
    if (!showToast || countdown <= 0) return
    if (countdown === 0) { handleAutoReload(); return }
    countRef.current = setTimeout(() => setCountdown(c => c - 1), 1000)
    return () => clearTimeout(countRef.current)
  }, [showToast, countdown])

  useEffect(() => {
    if (showToast && countdown === 0) handleAutoReload()
  }, [countdown])

  function handleAutoReload() {
    setShowToast(false)
    loadStock(stockId)
  }

  // ── weeks 切換時自動重查行情（股票已載入時）────────────────────
  useEffect(() => {
    if (loadState === 'found' && stockId) loadStock(stockId)
  }, [weeks])

  // ── 初始化（從其他頁跳轉帶入 initStock）────────────────────────
  useEffect(() => {
    if (initStock) {
      setInputVal(initStock)
      loadStock(initStock)
    }
  }, [initStock])

  // ── 查詢股票資料 ────────────────────────────────────────────────
  async function loadStock(id) {
    if (!id) return
    const days = weeks * 7
    setStockId(id)
    setLoadState('loading')
    setCrawlState('idle')
    setProgress(0); setShowToast(false)
    setInfo(null); setPrices([]); setChips(null)
    setHistAll([]); setHistAllState('idle'); setHistAllError('')

    const { data, notFound, error } = await getStockInfo(id)

    // notFound 必須排在 error 之前：404 現在也會帶回伺服器的說明文字
    // （request() 不再把它丟掉），若先判斷 error 就會走進「連線失敗」，
    // 而「查無此股票 → 詢問是否爬取」的流程再也不會觸發。
    if (notFound) {
      setLoadState('notfound')
      setCrawlState('confirming')
      addHistory({ type: 'stock', query: id, result: '不在資料庫' })
      return
    }
    if (error) {
      setLoadState('error'); setErrorMsg(error)
      addHistory({ type: 'stock', query: id, result: 'error', detail: error })
      return
    }

    setInfo(data)
    setLoadState('found')
    addHistory({ type: 'stock', query: id, result: '已找到', detail: data.stock_name })

    const [priceRes, chipRes] = await Promise.all([
      getStockPrices(id, days),
      getChipData(id, 20),
    ])
    const priceData = priceRes.data || []
    setPrices(priceData)
    if (chipRes.data) setChips(chipRes.data)

    // ── 資料量不足時自動觸發爬蟲（含冷卻 + 單次限制）──────────────
    const minExpected = weeks * 3   // 每週至少 3 個交易日
    if (priceData.length < minExpected && !autoCrawledRef.current) {
      const lsKey          = `crawl_ts_${id}`
      const lastTs         = Number(localStorage.getItem(lsKey)) || 0
      const cooldownRemain = CRAWL_COOLDOWN_MS - (Date.now() - lastTs)

      if (cooldownRemain > 0) {
        // 前端冷卻中，不重複觸發
        const mins = Math.ceil(cooldownRemain / 60000)
        console.log(`[auto-crawl] ${id} 冷卻中，剩 ${mins} 分鐘`)
      } else {
        autoCrawledRef.current = true
        localStorage.setItem(lsKey, String(Date.now()))
        setCrawlState('running')
        setProgress(0)
        const { data: crawlData, error: crawlErr } = await triggerCrawler(id)
        if (crawlErr || crawlData?.status === 'rate_limited') {
          // 後端拒絕（rate_limited / 錯誤）→ 靜默回到 idle，顯示現有資料
          setCrawlState('idle')
          clearInterval(progressRef.current)
          clearInterval(pollRef.current)
        }
      }
    }
  }

  // ── 觸發爬蟲 ────────────────────────────────────────────────────
  async function handleCrawl() {
    setCrawlState('running')
    setProgress(0)
    const { error } = await triggerCrawler(stockId)
    if (error) { setCrawlState('error'); setErrorMsg(error); return }
  }

  function handleSearch() {
    const id = inputVal.trim()
    if (!id || !weeks) return
    autoCrawledRef.current = false   // 手動搜尋重置，允許重新觸發一次自動爬蟲
    loadStock(id)
  }

  // ── 歷史資料補充 ────────────────────────────────────────────────
  async function handleHistCrawl() {
    if (!stockId || histState === 'running') return
    if (!histStart || !histEnd || histStart >= histEnd) {
      setHistMsg('請確認起始日 < 結束日'); return
    }
    setHistState('running')
    setHistProgress(0)
    setHistMsg('')
    const { data, error } = await triggerCrawler(stockId, { start_date: histStart, end_date: histEnd })
    if (error) { setHistState('error'); setHistMsg(error); return }
    if (data?.status === 'already_running') {
      setHistState('idle'); setHistMsg('爬蟲執行中，請稍候'); return
    }
  }

  // ── 載入全部歷史行情 ─────────────────────────────────────────────
  async function loadAllHistory() {
    if (!stockId || histAllState === 'loading') return
    setHistAllState('loading')
    const { data, error } = await getStockPricesHistory(stockId)
    if (error) { setHistAllState('error'); setHistAllError(error); return }
    setHistAll(data || [])
    setHistAllState('loaded')
  }

  // ── Chart options ───────────────────────────────────────────────

  // ── 期間統計（useMemo）─────────────────────────────────────────
  const periodStats = useMemo(() => {
    if (!prices.length) return null
    const closes  = prices.map(p => Number(p.close_price)).filter(v => !isNaN(v))
    const highs   = prices.map(p => Number(p.high_price)).filter(v => !isNaN(v))
    const lows    = prices.map(p => Number(p.low_price)).filter(v => !isNaN(v))
    const volumes = prices.map(p => Number(p.volume)).filter(v => !isNaN(v))
    return {
      high:    Math.max(...highs),
      low:     Math.min(...lows),
      avgClose: closes.reduce((a, b) => a + b, 0) / closes.length,
      totalVol: volumes.reduce((a, b) => a + b, 0),
    }
  }, [prices])

  const candles = useMemo(() => prices.map(p => ({
    x: new Date(p.trade_date).getTime(),
    y: [+p.open_price, +p.high_price, +p.low_price, +p.close_price],
  })), [prices])

  const volData = useMemo(() => prices.map(p => ({
    x: new Date(p.trade_date).getTime(),
    y: Number(p.volume) || 0,          // BIGINT → pg 回傳字串，需轉換
    up: Number(p.close_price) >= Number(p.open_price),
  })), [prices])

  const candleOptions = useMemo(() => ({
    ...chartBaseNow({ animations: { enabled: false } }),
    chart: { ...chartBaseNow({ animations: { enabled: false } }).chart, type: 'candlestick', height: 300 },
    xaxis: { type: 'datetime', labels: { style: { colors: cssColor('var(--dim)'), fontSize: chartPx(0.6875) }, datetimeUTC: false } },
    yaxis: { tooltip: { enabled: true }, labels: { style: { colors: cssColor('var(--dim)'), fontSize: chartPx(0.6875) } } },
    plotOptions: { candlestick: { colors: { upward: cssColor('var(--up)'), downward: cssColor('var(--down)') }, wick: { useFillColor: true } } },
    tooltip: { theme: 'dark', x: { format: 'yyyy-MM-dd' } },
  }), [])

  const volOptions = useMemo(() => ({
    ...chartBaseNow({ animations: { enabled: false } }),
    chart: { ...chartBaseNow({ animations: { enabled: false } }).chart, type: 'bar', height: 110 },
    xaxis: { type: 'datetime', categories: volData.map(v => v.x), labels: { show: false } },
    yaxis: { labels: { style: { colors: cssColor('var(--dim)'), fontSize: chartPx(0.625) }, formatter: v => (v / 1000).toFixed(0) + 'K' } },
    plotOptions: { bar: { columnWidth: '80%', distributed: true } },
    colors: volData.map(v => v.up ? cssColor('var(--up)') : cssColor('var(--down)')),
    dataLabels: { enabled: false },
    legend: { show: false },
    tooltip: { theme: 'dark', x: { format: 'yyyy-MM-dd' } },
  }), [volData])

  // 收盤價走勢：過濾掉 null/0，避免 ApexCharts y 軸範圍為 0 而崩潰
  const validPrices = useMemo(() =>
    prices.filter(p => p.close_price != null && Number(p.close_price) > 0)
  , [prices])

  const trendData = useMemo(() =>
    validPrices.map(p => ({ x: new Date(p.trade_date).getTime(), y: Number(p.close_price) }))
  , [validPrices])

  // MA5（5日移動平均）、MA20（20日移動平均）
  const ma5Data = useMemo(() =>
    validPrices.map((p, i, arr) => {
      const window = arr.slice(Math.max(0, i - 4), i + 1)
      const avg = window.reduce((sum, x) => sum + Number(x.close_price), 0) / window.length
      return { x: new Date(p.trade_date).getTime(), y: +avg.toFixed(2) }
    })
  , [validPrices])

  const ma20Data = useMemo(() =>
    validPrices.map((p, i, arr) => {
      if (i < 19) return { x: new Date(p.trade_date).getTime(), y: null }
      const window = arr.slice(i - 19, i + 1)
      const avg = window.reduce((sum, x) => sum + Number(x.close_price), 0) / window.length
      return { x: new Date(p.trade_date).getTime(), y: +avg.toFixed(2) }
    })
  , [validPrices])

  const trendSeries = useMemo(() => [
    { name: '收盤價', data: trendData },
    { name: 'MA5',   data: ma5Data },
    { name: 'MA20',  data: ma20Data },
  ], [trendData, ma5Data, ma20Data])

  const trendOptions = useMemo(() => ({
    ...chartBaseNow({ animations: { enabled: false } }),
    chart: { ...chartBaseNow({ animations: { enabled: false } }).chart, type: 'line', height: 200 },
    stroke: { curve: 'smooth', width: [2, 1.5, 1.5] },
    xaxis: { type: 'datetime', labels: { style: { colors: cssColor('var(--dim)'), fontSize: chartPx(0.6875) }, datetimeUTC: false } },
    yaxis: { labels: { style: { colors: cssColor('var(--dim)'), fontSize: chartPx(0.6875) }, formatter: v => v != null ? Number(v).toFixed(1) : '' } },
    colors: [cssColor('var(--blue)'), cssColor('var(--yellow)'), cssColor('var(--purple)')],
    markers: { size: [3, 0, 0], strokeWidth: 0 },
    legend: { position: 'top', labels: { colors: cssColor('var(--dim)') }, fontSize: chartPx(0.75) },
    tooltip: { theme: 'dark', x: { format: 'yyyy-MM-dd' } },
  }), [])

  // 日漲跌幅統計
  const crData  = useMemo(() => prices.map(p => Number(p.change_rate) || 0), [prices])
  const crColors = useMemo(() => crData.map(v => v >= 0 ? cssColor('var(--up)') : cssColor('var(--down)')), [crData])

  const crOptions = useMemo(() => ({
    ...chartBaseNow({ animations: { enabled: false } }),
    chart: { ...chartBaseNow({ animations: { enabled: false } }).chart, type: 'bar', height: 180 },
    xaxis: {
      categories: prices.map(p => p.trade_date),
      labels: { style: { colors: cssColor('var(--dim)'), fontSize: chartPx(0.625) }, rotate: -30 },
    },
    yaxis: {
      labels: {
        style: { colors: cssColor('var(--dim)'), fontSize: chartPx(0.6875) },
        formatter: v => (v >= 0 ? '+' : '') + Number(v).toFixed(2) + '%',
      },
    },
    colors: crColors,
    plotOptions: { bar: { columnWidth: '65%', distributed: true } },
    dataLabels: { enabled: false },
    legend: { show: false },
    tooltip: {
      theme: 'dark',
      y: { formatter: v => (v >= 0 ? '+' : '') + v.toFixed(2) + '%' },
    },
  }), [prices, crColors])

  const chipSeries = useMemo(() => chips ? [
    { name: '外資買超', data: chips.map(c => c.foreign_investor_buy) },
    { name: '投信買超', data: chips.map(c => c.investment_trust_buy) },
    { name: '自營商買超', data: chips.map(c => c.dealer_buy) },
  ] : [], [chips])

  const chipOptions = useMemo(() => ({
    ...chartBaseNow({ animations: { enabled: false } }),
    chart: { ...chartBaseNow({ animations: { enabled: false } }).chart, type: 'bar', height: 250 },
    xaxis: {
      categories: chips ? chips.map(c => c.trade_date) : [],
      labels: { style: { colors: cssColor('var(--dim)'), fontSize: chartPx(0.625) }, rotate: -30 },
    },
    yaxis: {
      labels: {
        style: { colors: cssColor('var(--dim)'), fontSize: chartPx(0.6875) },
        formatter: v => (v >= 0 ? '+' : '') + Number(v).toLocaleString(),
      },
    },
    colors: [cssColor('var(--blue)'), cssColor('var(--green)'), cssColor('var(--yellow)')],
    plotOptions: { bar: { columnWidth: '70%', grouped: true } },
    dataLabels: { enabled: false },
    legend: { position: 'top', labels: { colors: cssColor('var(--dim)') }, fontSize: chartPx(0.75) },
  }), [chips])

  // ── 全部歷史行情 Chart / Stats ────────────────────────────────────
  const histAllTrendData = useMemo(() =>
    histAll
      .filter(p => p.close_price != null && Number(p.close_price) > 0)
      .map(p => ({ x: new Date(p.trade_date).getTime(), y: Number(p.close_price) }))
  , [histAll])

  const histAllStats = useMemo(() => {
    if (!histAll.length) return null
    const closes = histAll.map(p => Number(p.close_price)).filter(v => !isNaN(v) && v > 0)
    return {
      count: histAll.length,
      from:  histAll[0]?.trade_date,
      to:    histAll[histAll.length - 1]?.trade_date,
      high:  Math.max(...closes).toFixed(2),
      low:   Math.min(...closes).toFixed(2),
    }
  }, [histAll])

  const histAllChartOptions = useMemo(() => {
    const now        = Date.now()
    const oneWeekAgo = now - 7 * 24 * 60 * 60 * 1000
    return {
      ...chartBaseNow({ animations: { enabled: false } }),
      chart: {
        id:        'histAllMain',
        type:      'area',
        height:    240,
        toolbar:   { show: false },
        animations: { enabled: false },
      },
      stroke:      { curve: 'smooth', width: 1.5 },
      xaxis: {
        type:   'datetime',
        min:    oneWeekAgo,
        max:    now,
        labels: { style: { colors: cssColor('var(--dim)'), fontSize: chartPx(0.6875) }, datetimeUTC: false, format: 'MM/dd' },
      },
      yaxis: {
        labels: {
          style:     { colors: cssColor('var(--dim)'), fontSize: chartPx(0.6875) },
          formatter: v => v != null ? Number(v).toFixed(1) : '',
        },
      },
      colors:     [cssColor('var(--blue)')],
      fill:       { type: 'gradient', gradient: { shadeIntensity: 1, opacityFrom: 0.35, opacityTo: 0.02, stops: [0, 100] } },
      dataLabels: { enabled: false },
      tooltip:    { theme: 'dark', x: { format: 'yyyy-MM-dd' } },
    }
  }, [])

  // Brush chart（全覽 + 拖拉選取）
  const histAllBrushOptions = useMemo(() => {
    const now        = Date.now()
    const oneWeekAgo = now - 7 * 24 * 60 * 60 * 1000
    return {
      ...chartBaseNow({ animations: { enabled: false } }),
      chart: {
        id:        'histAllBrush',
        type:      'area',
        height:    90,
        brush:     { target: 'histAllMain', enabled: true },
        selection: { enabled: true, xaxis: { min: oneWeekAgo, max: now } },
        toolbar:   { show: false },
        animations: { enabled: false },
      },
      xaxis: {
        type:   'datetime',
        labels: { style: { colors: cssColor('var(--dim)'), fontSize: chartPx(0.625) }, datetimeUTC: false, format: 'yy/MM' },
      },
      yaxis:      { labels: { show: false } },
      colors:     [cssColor('var(--blue)')],
      fill:       { type: 'gradient', gradient: { shadeIntensity: 1, opacityFrom: 0.2, opacityTo: 0.0, stops: [0, 100] } },
      dataLabels: { enabled: false },
      stroke:     { curve: 'smooth', width: 1 },
      tooltip:    { enabled: false },
    }
  }, [])

  // ── Render ──────────────────────────────────────────────────────

  const up    = info && info.change_rate > 0
  const dn    = info && info.change_rate < 0
  const cls   = up ? 'up' : dn ? 'down' : ''
  const arrow = up ? '▲' : dn ? '▼' : '－'
  const canSearch = !!inputVal.trim() && !!weeks && loadState !== 'loading'

  return (
    <>
      <ModelBar page="analysis" />
      {/* ── 完成通知 Toast（需求 10）─────────────────────────── */}
      {showToast && (
        <div className="crawl-toast">
          <span className="dot green" />
          <div className="toast-body">
            <strong>爬蟲完成！</strong>
            <span>資料已寫入資料庫，{countdown} 秒後自動重新查詢</span>
          </div>
          <button className="btn-chip" onClick={handleAutoReload}>立即查詢</button>
          <button className="toast-close" onClick={() => setShowToast(false)}>✕</button>
        </div>
      )}

      {/* ── 搜尋表單 ────────────────────────────────────────────── */}
      <div className="card">
        <div className="card-header">
          <span className="card-title">股票代碼查詢</span>
          <span className="tag blue">PostgreSQL → 爬蟲 fallback</span>
        </div>

        <div className="stock-form">
          {/* 股票代碼 */}
          <div className="stock-form-row">
            <label className="form-label">股票代碼 <span className="required">*</span></label>
            <input
              className="stock-input"
              value={inputVal}
              onChange={e => setInputVal(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && handleSearch()}
              placeholder="如 2330"
            />
          </div>

          {/* 時間範圍（需求 11）*/}
          <div className="stock-form-row">
            <label className="form-label">時間範圍 <span className="required">*</span></label>
            <div className="btn-group">
              {WEEK_OPTIONS.map(w => (
                <button
                  key={w}
                  className={`btn-period${weeks === w ? ' active' : ''}`}
                  onClick={() => setWeeks(w)}
                >
                  {w} 週
                </button>
              ))}
            </div>
            <span className="muted" style={{ fontSize: '0.6875rem' }}>
              預設 1 週，上限 4 週（1 個月）
            </span>
          </div>

          <button
            className="btn-primary"
            onClick={handleSearch}
            disabled={!canSearch}
          >
            {loadState === 'loading' ? '查詢中...' : '查詢'}
          </button>
        </div>
      </div>

      {/* ── 爬蟲確認 / 進度（需求 10）───────────────────────────── */}
      {loadState === 'notfound' && (
        <div className="alert-card warn">
          <div className="alert-icon">⚠️</div>
          <div className="alert-body" style={{ flex: 1 }}>
            <div className="alert-title">資料庫中找不到股票：{stockId}</div>

            {crawlState === 'confirming' && (
              <>
                <div className="alert-sub muted">是否立即執行爬蟲從 TWSE 抓取資料？</div>
                <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
                  <button className="btn-primary" onClick={handleCrawl}>執行爬蟲</button>
                  <button className="btn-secondary" onClick={() => setLoadState('idle')}>取消</button>
                </div>
              </>
            )}

            {/* 進度條（需求 10）*/}
            {crawlState === 'running' && (
              <div className="crawl-progress">
                <div className="progress-label">
                  <span className="dot green blink" />
                  <span>正在從 FinMind 抓取資料...</span>
                  <span className="muted">{Math.round(progress)}%</span>
                </div>
                <div className="progress-track">
                  <div className="progress-fill" style={{ width: `${progress}%` }} />
                </div>
              </div>
            )}

            {crawlState === 'done' && (
              <div className="crawl-status">
                <span className="dot green" />
                <span>爬蟲完成，資料已寫入</span>
                <button className="btn-chip" style={{ marginLeft: 8 }} onClick={() => loadStock(stockId)}>
                  重新查詢
                </button>
              </div>
            )}

            {crawlState === 'error' && (
              <div className="crawl-status down">{errorMsg}</div>
            )}
          </div>
        </div>
      )}

      {/* ── 連線失敗 ────────────────────────────────────────────── */}
      {loadState === 'error' && (
        <div className="alert-card error">
          <div className="alert-icon">❌</div>
          <div className="alert-body">
            <div className="alert-title">連線失敗</div>
            <div className="alert-sub muted">{errorMsg} — 請確認 Node.js Server 已啟動</div>
          </div>
        </div>
      )}

      {/* ── Idle ────────────────────────────────────────────────── */}
      {loadState === 'idle' && (
        <div className="empty-state">
          <div className="empty-icon">📈</div>
          <div>輸入股票代碼與時間範圍後查詢</div>
          <div className="muted" style={{ fontSize: '0.75rem' }}>若資料庫無此股票，系統會提示執行爬蟲</div>
        </div>
      )}

      {/* ── 查詢結果 ────────────────────────────────────────────── */}
      {loadState === 'found' && info && (
        <>
          {/* 資料不足自動補充進度（found 狀態下的爬蟲）*/}
          {crawlState === 'running' && (
            <div className="alert-card warn">
              <div className="alert-icon">🔄</div>
              <div className="alert-body" style={{ flex: 1 }}>
                <div className="alert-title">
                  資料量不足（目前 {prices.length} 筆），自動補充歷史資料中…
                </div>
                <div className="crawl-progress">
                  <div className="progress-label">
                    <span className="dot green blink" />
                    <span>正在從 FinMind 抓取資料...</span>
                    <span className="muted">{Math.round(progress)}%</span>
                  </div>
                  <div className="progress-track">
                    <div className="progress-fill" style={{ width: `${progress}%` }} />
                  </div>
                </div>
              </div>
            </div>
          )}

          <div className="cards-grid">
            <div className="metric-card">
              <div className="metric-label">收盤價</div>
              <div className={`metric-value ${cls}`}>{Number(info.close_price).toFixed(2)}</div>
              <div className={`metric-delta ${cls}`}>
                {arrow} {Math.abs(info.change_value).toFixed(2)} ({Math.abs(info.change_rate).toFixed(2)}%)
              </div>
            </div>
            <div className="metric-card">
              <div className="metric-label">成交張數</div>
              <div className="metric-value">{Number(info.volume || 0).toLocaleString()}</div>
              <div className="metric-delta muted">成交額 {Math.round((info.turnover_value || 0) / 100)} 億</div>
            </div>
            <div className="metric-card">
              <div className="metric-label">三大法人合計</div>
              <div className={`metric-value ${Number(info.total_net_buy) >= 0 ? 'up' : 'down'}`}>
                {Number(info.total_net_buy) >= 0 ? '+' : ''}{Number(info.total_net_buy || 0).toLocaleString()} 張
              </div>
              <div className="metric-delta muted" title={holdingTitle(info)}>
                外資持股 {info.foreign_holding_ratio != null ? `${info.foreign_holding_ratio}%` : 'N/A'}
                {info.foreign_holding_date ? ` · ${shortDate(info.foreign_holding_date)}` : ''}
                {holdingLag(info) ? '（晚於行情）' : ''}
              </div>
            </div>
            <div className="metric-card">
              <div className="metric-label">產業類別</div>
              <div className="metric-value sm">{info.industry_type || '－'}</div>
              <div className="metric-delta muted">{info.market_type || '上市'} · TWSE</div>
            </div>
          </div>

          {/* K 線圖 */}
          {candles.length > 0 ? (
            <div className="card">
              <div className="card-header">
                <span className="card-title">
                  {info.stock_id} {info.stock_name} — 日K線
                </span>
                <span className="tag blue">近 {weeks} 週（{weeks * 7} 日）</span>
              </div>
              <ResizableChart chartId="kline" defaultHeight={300} minHeight={150}>
                {h => (
                  <ReactApexChart
                    type="candlestick"
                    series={[{ data: candles }]}
                    options={candleOptions}
                    height={h}
                  />
                )}
              </ResizableChart>
              {volData.length > 0 && (
                <ResizableChart chartId="volume" defaultHeight={110} minHeight={60} className="chart-pad-sm">
                  {h => (
                    <ReactApexChart
                      type="bar"
                      series={[{ name: '成交量', data: volData.map(v => v.y) }]}
                      options={volOptions}
                      height={h}
                    />
                  )}
                </ResizableChart>
              )}
            </div>
          ) : (
            <div className="empty-state">
              <div className="muted">尚無K線資料（等待爬蟲寫入）</div>
            </div>
          )}

          {/* 期間統計 */}
          {periodStats && (
            <div className="cards-grid">
              <div className="metric-card">
                <div className="metric-label">期間最高價</div>
                <div className="metric-value up">{periodStats.high.toFixed(2)}</div>
                <div className="metric-delta muted">近 {weeks} 週最高</div>
              </div>
              <div className="metric-card">
                <div className="metric-label">期間最低價</div>
                <div className="metric-value down">{periodStats.low.toFixed(2)}</div>
                <div className="metric-delta muted">近 {weeks} 週最低</div>
              </div>
              <div className="metric-card">
                <div className="metric-label">期間平均收盤</div>
                <div className="metric-value">{periodStats.avgClose.toFixed(2)}</div>
                <div className="metric-delta muted">{prices.length} 個交易日均值</div>
              </div>
              <div className="metric-card">
                <div className="metric-label">期間總成交量</div>
                <div className="metric-value sm">{periodStats.totalVol.toLocaleString()} 張</div>
                <div className="metric-delta muted">日均 {Math.round(periodStats.totalVol / prices.length).toLocaleString()} 張</div>
              </div>
            </div>
          )}

          {/* 收盤價走勢 + 漲跌幅統計 */}
          {trendData.length > 0 && (
            <div className="card">
              <div className="card-header">
                <span className="card-title">收盤價走勢</span>
                <span className="tag blue">近 {weeks} 週逐日收盤</span>
              </div>
              <ResizableChart chartId="trend" defaultHeight={200} minHeight={120}>
                {h => <ReactApexChart type="line" series={trendSeries} options={trendOptions} height={h} />}
              </ResizableChart>
            </div>
          )}

          {crData.some(v => v !== 0) && (
            <div className="card">
              <div className="card-header">
                <span className="card-title">日漲跌幅（%）</span>
                <span className="tag green">統計圖表</span>
              </div>
              <ResizableChart chartId="changerate" defaultHeight={180} minHeight={120}>
                {h => (
                  <ReactApexChart
                    type="bar"
                    series={[{ name: '漲跌幅', data: crData }]}
                    options={crOptions}
                    height={h}
                  />
                )}
              </ResizableChart>
            </div>
          )}

          {/* 每日行情明細 */}
          {prices.length > 0 && (
            <div className="card">
              <div className="card-header">
                <span className="card-title">每日行情明細</span>
                <span className="muted" style={{ fontSize: '0.6875rem' }}>近 {weeks} 週 · {prices.length} 個交易日</span>
              </div>
              <div className="table-wrap">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>日期</th><th>開盤</th><th>最高</th><th>最低</th>
                      <th>收盤</th><th>漲跌</th><th>漲跌幅(%)</th><th>成交量(張)</th>
                    </tr>
                  </thead>
                  <tbody>
                    {[...prices].reverse().map(p => {
                      const cr  = Number(p.change_rate)
                      const cv  = Number(p.change_value)
                      const cls = cr > 0 ? 'up' : cr < 0 ? 'down' : ''
                      const arrow = cr > 0 ? '▲' : cr < 0 ? '▼' : '－'
                      return (
                        <tr key={p.trade_date}>
                          <td className="muted" style={{ whiteSpace: 'nowrap' }}>{p.trade_date}</td>
                          <td>{p.open_price != null ? Number(p.open_price).toFixed(2) : '–'}</td>
                          <td className="up">{p.high_price != null ? Number(p.high_price).toFixed(2) : '–'}</td>
                          <td className="down">{p.low_price != null ? Number(p.low_price).toFixed(2) : '–'}</td>
                          <td className={cls}>{p.close_price != null ? Number(p.close_price).toFixed(2) : '–'}</td>
                          <td className={cls}>{cv ? `${arrow} ${Math.abs(cv).toFixed(2)}` : '－'}</td>
                          <td className={cls}>{cr ? `${arrow} ${Math.abs(cr).toFixed(2)}%` : '－'}</td>
                          <td>{p.volume != null ? Number(p.volume).toLocaleString() : '–'}</td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* 三大法人籌碼 */}
          {chips && chips.length > 0 && (
            <div className="card">
              <div className="card-header">
                <span className="card-title">三大法人籌碼（近20日）</span>
                <span className="tag blue">stock_chip_analysis</span>
              </div>
              <ResizableChart chartId="chips" defaultHeight={250} minHeight={120}>
                {h => <ReactApexChart type="bar" series={chipSeries} options={chipOptions} height={h} />}
              </ResizableChart>
            </div>
          )}

          {/* 歷史資料補充 */}
          <div className="card">
            <div className="card-header">
              <span className="card-title">歷史資料補充</span>
              <span className="tag yellow">FinMind · 上限 365 天</span>
            </div>
            <div className="stock-form" style={{ paddingTop: 12, paddingBottom: 14 }}>
              <div className="stock-form-row" style={{ flexDirection: 'row', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
                <label className="form-label" style={{ whiteSpace: 'nowrap' }}>起始日</label>
                <input
                  type="date" className="stock-input" style={{ width: 'auto' }}
                  value={histStart} max={histEnd}
                  onChange={e => setHistStart(e.target.value)}
                />
                <label className="form-label" style={{ whiteSpace: 'nowrap' }}>結束日</label>
                <input
                  type="date" className="stock-input" style={{ width: 'auto' }}
                  value={histEnd} max={new Date().toISOString().slice(0, 10)}
                  onChange={e => setHistEnd(e.target.value)}
                />
                <button
                  className="btn-primary"
                  onClick={handleHistCrawl}
                  disabled={histState === 'running' || crawlState === 'running'}
                >
                  {histState === 'running' ? '補充中…' : '補充歷史資料'}
                </button>
              </div>

              {histState === 'running' && (
                <div className="crawl-progress">
                  <div className="progress-label">
                    <span className="dot green blink" />
                    <span>正在從 FinMind 抓取 {histStart} ~ {histEnd} 資料…</span>
                    <span className="muted">{Math.round(histProgress)}%</span>
                  </div>
                  <div className="progress-track">
                    <div className="progress-fill" style={{ width: `${histProgress}%` }} />
                  </div>
                </div>
              )}

              {histState === 'done' && (
                <div className="crawl-status">
                  <span className="dot green" />
                  <span className="up">{histMsg}</span>
                  <button className="btn-chip" style={{ marginLeft: 8 }} onClick={() => loadStock(stockId)}>
                    重新查詢
                  </button>
                </div>
              )}

              {(histState === 'error' || (histState === 'idle' && histMsg)) && (
                <div className="crawl-status down">{histMsg}</div>
              )}
            </div>
          </div>

          {/* ── 全部歷史行情 ─────────────────────────────────────────── */}
          <div className="card">
            <div className="card-header">
              <span className="card-title">全部歷史行情</span>
              {histAllStats && (
                <span className="muted" style={{ fontSize: '0.6875rem' }}>
                  {histAllStats.from} ~ {histAllStats.to}（{histAllStats.count} 個交易日）
                </span>
              )}
              {histAllState === 'idle' && (
                <button className="btn-chip" onClick={loadAllHistory}>載入</button>
              )}
              {histAllState === 'loading' && (
                <span className="muted" style={{ fontSize: '0.75rem' }}>載入中…</span>
              )}
              {histAllState === 'loaded' && (
                <button className="btn-chip" onClick={loadAllHistory}>重新載入</button>
              )}
            </div>

            {histAllState === 'idle' && (
              <div className="empty-state" style={{ padding: '20px 0' }}>
                <div className="muted" style={{ fontSize: '0.75rem' }}>點擊「載入」取得資料庫中全部歷史收盤走勢</div>
              </div>
            )}

            {histAllState === 'error' && (
              <div className="alert-error" style={{ margin: '12px 18px' }}>{histAllError}</div>
            )}

            {histAllState === 'loaded' && histAllStats && (
              <>
                {/* 統計摘要 */}
                <div className="cards-grid" style={{ margin: '0 0 4px' }}>
                  <div className="metric-card">
                    <div className="metric-label">資料起始</div>
                    <div className="metric-value sm">{histAllStats.from}</div>
                  </div>
                  <div className="metric-card">
                    <div className="metric-label">最新資料</div>
                    <div className="metric-value sm">{histAllStats.to}</div>
                  </div>
                  <div className="metric-card">
                    <div className="metric-label">歷史最高</div>
                    <div className="metric-value up">{histAllStats.high}</div>
                  </div>
                  <div className="metric-card">
                    <div className="metric-label">歷史最低</div>
                    <div className="metric-value down">{histAllStats.low}</div>
                  </div>
                </div>

                {/* 全歷史收盤走勢（主圖 + brush 縮圖）*/}
                {histAllTrendData.length > 0 && (
                  <>
                    <div className="chart-pad">
                      <ReactApexChart
                        type="area"
                        series={[{ name: '收盤價', data: histAllTrendData }]}
                        options={histAllChartOptions}
                        height={240}
                      />
                    </div>
                    <div className="chart-pad-sm">
                      <ReactApexChart
                        type="area"
                        series={[{ name: '收盤價', data: histAllTrendData }]}
                        options={histAllBrushOptions}
                        height={90}
                      />
                    </div>
                  </>
                )}

                {/* 全部歷史明細表格（固定高度可捲動）*/}
                <div className="table-wrap">
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>日期</th><th>開盤</th><th>最高</th><th>最低</th>
                        <th>收盤</th><th>漲跌</th><th>漲跌幅(%)</th><th>成交量(張)</th>
                      </tr>
                    </thead>
                    <tbody>
                      {[...histAll].reverse().map(p => {
                        const cr    = Number(p.change_rate)
                        const cv    = Number(p.change_value)
                        const cls   = cr > 0 ? 'up' : cr < 0 ? 'down' : ''
                        const arrow = cr > 0 ? '▲' : cr < 0 ? '▼' : '－'
                        return (
                          <tr key={p.trade_date}>
                            <td className="muted" style={{ whiteSpace: 'nowrap' }}>{p.trade_date}</td>
                            <td>{p.open_price  != null ? Number(p.open_price).toFixed(2)  : '–'}</td>
                            <td className="up">{p.high_price != null ? Number(p.high_price).toFixed(2) : '–'}</td>
                            <td className="down">{p.low_price != null ? Number(p.low_price).toFixed(2) : '–'}</td>
                            <td className={cls}>{p.close_price != null ? Number(p.close_price).toFixed(2) : '–'}</td>
                            <td className={cls}>{cv ? `${arrow} ${Math.abs(cv).toFixed(2)}` : '－'}</td>
                            <td className={cls}>{cr ? `${arrow} ${Math.abs(cr).toFixed(2)}%` : '－'}</td>
                            <td>{p.volume != null ? Number(p.volume).toLocaleString() : '–'}</td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>
              </>
            )}
          </div>

          <div style={{ height: 120 }} />
        </>
      )}
    </>
  )
}
