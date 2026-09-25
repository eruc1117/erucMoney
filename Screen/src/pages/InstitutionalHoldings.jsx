// 三大法人持股變化（單一股票）
// ───────────────────────────────────────────────────────────────────────────
// 回答一個問題：「這段期間外資／投信／自營商在這檔股票上是加碼還是減碼？」
//
// 兩種資料，意義不同，畫面上分開講：
//   · 買賣超累計（stock_chip_analysis）：三大法人都有。從期間第一天起算，
//     曲線往上是加碼、往下是減碼；換期間起點，數字就跟著變。
//   · 外資真實持股（stock_foreign_holding，Iteration 35）：外資今天「手上有多少」，
//     股數與佔已發行股數的比例。這是絕對值，不隨期間起點變。
//     只有外資有這份每日揭露；投信、自營商沒有，所以它們只能看累計。
//
// FinMind 回傳的單位是「股」，畫面一律換算成「張」（÷1000）——台股講籌碼都用張。
// 顏色沿用全站台股慣例：買超／增加（正）紅、賣超／減少（負）綠。
import { useEffect, useMemo, useState } from 'react'
import ReactApexChart from 'react-apexcharts'
import { chartBase, cssColor, chartPx, useTheme } from '../theme'
import { getInstitutionalFlow, getTrackedStocks } from '../services/api'

const PERIODS = [
  { days: 20,   label: '20 日' },
  { days: 60,   label: '60 日' },
  { days: 120,  label: '120 日' },
  { days: 365,  label: '1 年' },
  { days: 1095, label: '3 年' },
]

// 三大法人的顏色與「個股分析」頁的籌碼圖一致，換頁看不會錯認
const GROUPS = [
  { key: 'foreign', net: 'foreign_net', cum: 'cum_foreign', label: '外資',   color: 'var(--blue)' },
  { key: 'trust',   net: 'trust_net',   cum: 'cum_trust',   label: '投信',   color: 'var(--green)' },
  { key: 'dealer',  net: 'dealer_net',  cum: 'cum_dealer',  label: '自營商', color: 'var(--yellow)' },
]

const toLots = shares => (shares === null || shares === undefined ? null : shares / 1000)

function fmtLots(shares, { sign = true } = {}) {
  const v = toLots(shares)
  if (v === null || Number.isNaN(v)) return '–'
  const r = Math.round(v)
  return `${sign && r > 0 ? '+' : ''}${r.toLocaleString()}`
}

function fmtPct(v, digits = 2, { sign = true } = {}) {
  if (v === null || v === undefined || Number.isNaN(Number(v))) return '–'
  const n = Number(v)
  return `${sign && n > 0 ? '+' : ''}${n.toFixed(digits)}%`
}

function toneClass(v) {
  if (v === null || v === undefined || Number.isNaN(Number(v))) return 'muted'
  return Number(v) > 0 ? 'up' : Number(v) < 0 ? 'down' : 'muted'
}

function chartBaseNow() {
  return chartBase(document.documentElement.dataset.theme)
}

// 三張時間序列圖共用的 x 軸設定
function xaxisFor(b, dates, axisStyle) {
  return {
    ...b.xaxis,
    categories: dates,
    tickAmount: Math.min(12, Math.max(dates.length - 1, 1)),
    labels: { ...axisStyle, rotate: -30, hideOverlappingLabels: true },
    tooltip: { enabled: false },
  }
}

export default function InstitutionalHoldings({ initStock = '' }) {
  useTheme()   // 主題切換時重新 render，圖表才會換色

  const [inputVal, setInputVal] = useState(initStock || '2330')
  const [stockId,  setStockId]  = useState('')
  const [days,     setDays]     = useState(60)
  const [tracked,  setTracked]  = useState([])

  const [data,    setData]    = useState(null)
  const [loading, setLoading] = useState(false)
  const [error,   setError]   = useState('')

  useEffect(() => {
    getTrackedStocks().then(({ data: list }) => { if (Array.isArray(list)) setTracked(list) })
  }, [])

  // 進頁面就查一檔：從其他頁帶進來的代碼優先，否則台積電
  useEffect(() => { search(inputVal) }, [])          // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (stockId) load(stockId, days) }, [days])   // eslint-disable-line react-hooks/exhaustive-deps

  function search(raw) {
    const id = String(raw || '').trim()
    if (!id) return
    setStockId(id)
    load(id, days)
  }

  function load(id, d) {
    setLoading(true)
    setError('')
    getInstitutionalFlow(id, d).then(({ data: res, error: e, notFound }) => {
      if (e) {
        setError(notFound ? `資料庫中找不到股票 ${id}，可先到「個股分析」執行爬蟲` : e)
        setData(null)
      } else {
        setData(res)
      }
      setLoading(false)
    })
  }

  const series  = data?.series || []
  const summary = data?.summary
  const holding = summary?.foreign_holding || null
  const dates   = useMemo(() => series.map(r => r.trade_date), [series])
  const hasHolding = useMemo(() => series.some(r => r.foreign_ratio !== null && r.foreign_ratio !== undefined), [series])

  // ── 累計買賣超（線）+ 收盤價（右軸）────────────────────────────────────
  const cumSeries = useMemo(() => [
    ...GROUPS.map(g => ({ name: g.label, data: series.map(r => toLots(r[g.cum])) })),
    { name: '合計',   data: series.map(r => toLots(r.cum_total)) },
    { name: '收盤價', data: series.map(r => r.close_price) },
  ], [series])

  const cumOptions = useMemo(() => {
    const b = chartBaseNow()
    const axisStyle = { style: { colors: cssColor('var(--dim)'), fontSize: chartPx(0.6875) } }
    const titleStyle = { color: cssColor('var(--dim)'), fontSize: chartPx(0.6875) }
    return {
      ...b,
      chart: { ...b.chart, type: 'line', animations: { enabled: false }, zoom: { enabled: false } },
      stroke: { width: [2, 2, 2, 3, 1.5], curve: 'straight', dashArray: [0, 0, 0, 0, 4] },
      colors: [
        ...GROUPS.map(g => cssColor(g.color)),
        cssColor('var(--purple)'),
        cssColor('var(--dim)'),
      ],
      xaxis: xaxisFor(b, dates, axisStyle),
      // 前四條共用左軸（張），收盤價用右軸。ApexCharts 4 的 seriesName 可以給陣列，一個軸綁多條線。
      yaxis: [
        { seriesName: ['外資', '投信', '自營商', '合計'],
          title: { text: '累計買賣超（張）', style: titleStyle },
          labels: { ...axisStyle, formatter: v => (v > 0 ? '+' : '') + Math.round(v).toLocaleString() } },
        { seriesName: '收盤價', opposite: true,
          title: { text: '收盤價', style: titleStyle },
          labels: { ...axisStyle, formatter: v => (v === null || v === undefined ? '' : Number(v).toFixed(1)) } },
      ],
      annotations: { yaxis: [{ y: 0, yAxisIndex: 0, borderColor: cssColor('var(--border)'), strokeDashArray: 0 }] },
      tooltip: {
        ...b.tooltip, shared: true, intersect: false,
        y: { formatter: (v, { seriesIndex }) =>
          seriesIndex === 4
            ? (v === null || v === undefined ? '–' : Number(v).toFixed(2))
            : (v === null || v === undefined ? '–' : `${v > 0 ? '+' : ''}${Math.round(v).toLocaleString()} 張`) },
      },
      dataLabels: { enabled: false },
      markers: { size: 0 },
      // ApexCharts 4 遇到多 y 軸會把同一軸的系列在圖例裡分組直排（clusterGroupedSeries），
      // 五個名字疊成一柱很難讀，關掉讓它照一般方式橫排
      legend: { ...b.legend, position: 'top', horizontalAlign: 'center', clusterGroupedSeries: false },
    }
  }, [dates])

  // ── 外資真實持股（比例 + 張數）───────────────────────────────────────────
  const holdingSeries = useMemo(() => [
    { name: '外資持股比例', data: series.map(r => r.foreign_ratio) },
    { name: '外資持股張數', data: series.map(r => toLots(r.foreign_shares)) },
  ], [series])

  const holdingOptions = useMemo(() => {
    const b = chartBaseNow()
    const axisStyle = { style: { colors: cssColor('var(--dim)'), fontSize: chartPx(0.6875) } }
    const titleStyle = { color: cssColor('var(--dim)'), fontSize: chartPx(0.6875) }
    return {
      ...b,
      chart: { ...b.chart, type: 'line', animations: { enabled: false }, zoom: { enabled: false } },
      stroke: { width: [2.5, 1.5], curve: 'straight', dashArray: [0, 4] },
      colors: [cssColor('var(--blue)'), cssColor('var(--dim)')],
      xaxis: xaxisFor(b, dates, axisStyle),
      yaxis: [
        { seriesName: '外資持股比例',
          title: { text: '持股比例（%）', style: titleStyle },
          labels: { ...axisStyle, formatter: v => (v === null || v === undefined ? '' : Number(v).toFixed(2)) } },
        { seriesName: '外資持股張數', opposite: true,
          title: { text: '持股張數', style: titleStyle },
          labels: { ...axisStyle, formatter: v => (v === null || v === undefined ? '' : Math.round(v).toLocaleString()) } },
      ],
      tooltip: {
        ...b.tooltip, shared: true, intersect: false,
        y: { formatter: (v, { seriesIndex }) =>
          v === null || v === undefined ? '–'
            : seriesIndex === 0 ? `${Number(v).toFixed(2)}%` : `${Math.round(v).toLocaleString()} 張` },
      },
      dataLabels: { enabled: false },
      markers: { size: 0 },
      legend: { ...b.legend, position: 'top', horizontalAlign: 'center', clusterGroupedSeries: false },
    }
  }, [dates])

  // ── 每日買賣超（柱）─────────────────────────────────────────────────
  const dailySeries = useMemo(() =>
    GROUPS.map(g => ({ name: g.label, data: series.map(r => toLots(r[g.net])) })),
  [series])

  const dailyOptions = useMemo(() => {
    const b = chartBaseNow()
    const axisStyle = { style: { colors: cssColor('var(--dim)'), fontSize: chartPx(0.6875) } }
    return {
      ...b,
      chart: { ...b.chart, type: 'bar', animations: { enabled: false }, zoom: { enabled: false } },
      colors: GROUPS.map(g => cssColor(g.color)),
      plotOptions: { bar: { columnWidth: '70%' } },
      xaxis: xaxisFor(b, dates, axisStyle),
      yaxis: { labels: { ...axisStyle, formatter: v => (v > 0 ? '+' : '') + Math.round(v).toLocaleString() } },
      tooltip: {
        ...b.tooltip, shared: true, intersect: false,
        y: { formatter: v => (v === null || v === undefined ? '–' : `${v > 0 ? '+' : ''}${Math.round(v).toLocaleString()} 張`) },
      },
      dataLabels: { enabled: false },
      legend: { ...b.legend, position: 'top' },
    }
  }, [dates])

  const recent = useMemo(() => [...series].reverse().slice(0, 30), [series])

  const canSearch = !!inputVal.trim() && !loading

  return (
    <>
      {/* ── 查詢列 ─────────────────────────────────────────────────────── */}
      <div className="card">
        <div className="card-header">
          <span className="card-title">股票代碼與期間</span>
          <span className="tag blue">stock_chip_analysis · stock_foreign_holding · 單位：張</span>
        </div>
        <div className="stock-form" style={{ flexDirection: 'row', alignItems: 'flex-end', flexWrap: 'wrap' }}>
          <div className="stock-form-row">
            <label className="form-label">股票代碼</label>
            <input
              className="stock-input"
              list="institutional-stock-list"
              value={inputVal}
              onChange={e => setInputVal(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && canSearch && search(inputVal)}
              placeholder="如 2330"
            />
            <datalist id="institutional-stock-list">
              {tracked.map(s => <option key={s.stock_id} value={s.stock_id}>{s.stock_name}</option>)}
            </datalist>
          </div>
          <div className="stock-form-row">
            <label className="form-label">期間（日曆天）</label>
            <div className="btn-group">
              {PERIODS.map(p => (
                <button key={p.days} className={`btn-period${days === p.days ? ' active' : ''}`}
                        onClick={() => setDays(p.days)}>{p.label}</button>
              ))}
            </div>
          </div>
          <button className="btn-primary" disabled={!canSearch} onClick={() => search(inputVal)}>
            {loading ? '查詢中…' : '查詢'}
          </button>
        </div>
      </div>

      {error && (
        <div className="card" style={{ borderColor: 'var(--orange)' }}>
          <div style={{ padding: '1rem 1.25rem', color: 'var(--orange)' }}>{error}</div>
        </div>
      )}

      {data && series.length === 0 && !error && (
        <div className="card">
          <div className="empty-state">
            <div className="empty-icon">🏦</div>
            <div>{data.stock_id} {data.stock_name} 在最近 {days} 天沒有法人資料</div>
            <div className="muted" style={{ fontSize: '.82rem' }}>可到「個股分析」用「歷史資料補充」回補籌碼</div>
          </div>
        </div>
      )}

      {data && series.length > 0 && (
        <>
          {/* ── 期間總結 ────────────────────────────────────────────────── */}
          <div className="card">
            <div className="card-header">
              <div className="row-head">
                <span className="card-title">
                  {data.stock_id} {data.stock_name}
                  {data.industry_type ? <span className="muted"> · {data.industry_type}</span> : null}
                </span>
              </div>
              <span className="muted" style={{ fontSize: '.82rem' }}>
                {data.start_date} ～ {data.end_date} · {data.trading_days} 個交易日
              </span>
            </div>
            <div className="stat-grid">
              {GROUPS.map(g => {
                const s = summary?.[g.key]
                return (
                  <div className="stat-tile" key={g.key}>
                    <div className="k">{g.label}累計買賣超</div>
                    <div className={`v ${toneClass(s?.cum)}`}>{fmtLots(s?.cum)} 張</div>
                    <div className="s">買超 {s?.buy_days ?? '–'} 日 / {data.trading_days} 日</div>
                  </div>
                )
              })}
              <div className="stat-tile">
                <div className="k">三大法人合計</div>
                <div className={`v ${toneClass(summary?.total?.cum)}`}>{fmtLots(summary?.total?.cum)} 張</div>
                <div className="s">買超 {summary?.total?.buy_days ?? '–'} 日 / {data.trading_days} 日</div>
              </div>
              <div className="stat-tile">
                <div className="k">外資持股比例（真實）</div>
                <div className="v">{holding ? fmtPct(holding.end_ratio, 2, { sign: false }) : '–'}</div>
                <div className={`s ${holding ? toneClass(holding.ratio_change) : ''}`}>
                  {holding
                    ? `${fmtPct(holding.start_ratio, 2, { sign: false })} → ${fmtPct(holding.end_ratio, 2, { sign: false })}（${fmtPct(holding.ratio_change, 2)} 點）`
                    : '尚無持股統計'}
                </div>
              </div>
              <div className="stat-tile">
                <div className="k">外資持股張數變化（真實）</div>
                <div className={`v ${holding ? toneClass(holding.shares_change) : ''}`}>
                  {holding ? `${fmtLots(holding.shares_change)} 張` : '–'}
                </div>
                <div className="s">
                  {holding ? `現持 ${fmtLots(holding.end_shares, { sign: false })} 張` : '尚無持股統計'}
                </div>
              </div>
              <div className="stat-tile">
                <div className="k">同期股價</div>
                <div className={`v ${toneClass(summary?.price_change_pct)}`}>{fmtPct(summary?.price_change_pct)}</div>
                <div className="s">
                  {series[0]?.close_price ?? '–'} → {series[series.length - 1]?.close_price ?? '–'}
                </div>
              </div>
            </div>
          </div>

          {/* ── 累計買賣超 ──────────────────────────────────────────────── */}
          <div className="card">
            <div className="card-header">
              <span className="card-title">累計買賣超（三大法人）</span>
              <span className="muted" style={{ fontSize: '.82rem' }}>
                自 {data.start_date} 起算；虛線為收盤價（右軸）
              </span>
            </div>
            <div className="chart-pad">
              <ReactApexChart type="line" series={cumSeries} options={cumOptions} height={340} />
            </div>
          </div>

          {/* ── 外資真實持股 ────────────────────────────────────────────── */}
          <div className="card">
            <div className="card-header">
              <span className="card-title">外資真實持股</span>
              <span className="tag blue">TaiwanStockShareholding · 絕對值，不隨期間起點變</span>
            </div>
            {hasHolding ? (
              <div className="chart-pad">
                <ReactApexChart type="line" series={holdingSeries} options={holdingOptions} height={280} />
              </div>
            ) : (
              <div className="empty-state" style={{ padding: '2rem 1.25rem' }}>
                <div>這段期間還沒有外資持股統計</div>
                <div className="muted" style={{ fontSize: '.82rem' }}>
                  每日 18:00 排程會抓；歷史可用 <code>backfill_prices.py --holding-only</code> 回補
                </div>
              </div>
            )}
          </div>

          {/* ── 每日買賣超 ──────────────────────────────────────────────── */}
          <div className="card">
            <div className="card-header">
              <span className="card-title">每日買賣超</span>
              <span className="tag">正值買超、負值賣超</span>
            </div>
            <div className="chart-pad">
              <ReactApexChart type="bar" series={dailySeries} options={dailyOptions} height={260} />
            </div>
          </div>

          {/* ── 明細 ───────────────────────────────────────────────────── */}
          <div className="card">
            <div className="card-header">
              <span className="card-title">近 {recent.length} 個交易日明細</span>
              <span className="tag">單位：張</span>
            </div>
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>日期</th>
                    <th className="num">收盤</th>
                    <th className="num">漲跌幅</th>
                    <th className="num">外資</th>
                    <th className="num">投信</th>
                    <th className="num">自營商</th>
                    <th className="num">合計</th>
                    <th className="num">累計合計</th>
                    <th className="num">外資持股</th>
                    <th className="num">持股比例</th>
                  </tr>
                </thead>
                <tbody>
                  {recent.map(r => (
                    <tr key={r.trade_date}>
                      <td>{r.trade_date}</td>
                      <td className="num">{r.close_price ?? '–'}</td>
                      <td className={`num ${toneClass(r.change_rate)}`}>{fmtPct(r.change_rate)}</td>
                      <td className={`num ${toneClass(r.foreign_net)}`}>{fmtLots(r.foreign_net)}</td>
                      <td className={`num ${toneClass(r.trust_net)}`}>{fmtLots(r.trust_net)}</td>
                      <td className={`num ${toneClass(r.dealer_net)}`}>{fmtLots(r.dealer_net)}</td>
                      <td className={`num ${toneClass(r.total_net)}`}>{fmtLots(r.total_net)}</td>
                      <td className={`num ${toneClass(r.cum_total)}`}>{fmtLots(r.cum_total)}</td>
                      <td className="num">{fmtLots(r.foreign_shares, { sign: false })}</td>
                      <td className="num">{fmtPct(r.foreign_ratio, 2, { sign: false })}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="note-box">
              「累計」是從期間第一天起算的買賣超淨變化，換期間起點就會跟著變；
              「外資持股」與「持股比例」是證交所每日揭露的真實持股，不隨起點變。
              投信與自營商沒有對應的每日持股揭露，只能看累計。這是籌碼流向的參考，不是買賣訊號。
            </div>
          </div>
        </>
      )}
    </>
  )
}
