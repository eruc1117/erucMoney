// 淨值曲線（可選區間）——月調倉頁與正式策略頁共用（Iteration 63 抽出；64 加 extraPresets）
// 選了區間後兩條線都從區間起點重新歸一到 1，並算這段的組合／0050／主動報酬；全期間的指標仍以日誌為準。
import { useEffect, useState } from 'react'
import ReactApexChart from 'react-apexcharts'

function pct(v, d = 2) {
  if (v === null || v === undefined || Number.isNaN(Number(v))) return '–'
  const n = Number(v) * 100
  return `${n > 0 ? '+' : ''}${n.toFixed(d)}%`
}
function tone(v) { return v === null || v === undefined ? 'muted' : Number(v) > 0 ? 'up' : Number(v) < 0 ? 'down' : 'muted' }

const NAV_RANGE_KEY = 'pf_nav_range'
const NAV_PRESETS = (ps, pe) => [
  ['全期間', ps, pe],
  ['開發期', '2018-01-01', '2021-12-31'],
  ['驗證期', '2022-01-01', '2024-09-30'],
  ['最近 1 年', shiftDays(pe, -365), pe],
  ['最近 3 年', shiftDays(pe, -365 * 3), pe],
]
function shiftDays(iso, days) { const d = new Date(iso + 'T00:00:00'); d.setDate(d.getDate() + days); return d.toISOString().slice(0, 10) }

// 淨值曲線可選區間（Iteration 63）：選了之後兩條線都從區間起點重新歸一到 1，才看得出「這一段」誰贏；
// 全期間的年化／回撤仍在卡片標題（那是日誌裡算好的），區間內的報酬在圖上方另算。
export default function NavRangeChart({ series, periodStart, periodEnd, extraPresets = [], storageKey = NAV_RANGE_KEY }) {
  const [range, setRange] = useState(() => {
    try { const v = JSON.parse(localStorage.getItem(storageKey)); if (v?.start && v?.end) return v } catch { /* ignore */ }
    return { start: periodStart, end: periodEnd }
  })
  useEffect(() => { try { localStorage.setItem(storageKey, JSON.stringify(range)) } catch { /* ignore */ } }, [range])
  if (!series?.length) return <div className="card-body muted">這個 run 沒有淨值曲線（portfolio_backtest.py --attach-series 補上）</div>
  const start = range.start && range.start > periodStart ? range.start : periodStart
  const end = range.end && range.end < periodEnd ? range.end : periodEnd
  const sub = series.filter(p => p.d >= start && p.d <= end && p.nav != null && p.bench != null)
  const first = sub[0]
  const rebased = first ? sub.map(p => ({ d: p.d, nav: Number(p.nav) / Number(first.nav), bench: Number(p.bench) / Number(first.bench) })) : []
  const last = rebased[rebased.length - 1]
  const years = first && last ? (new Date(last.d) - new Date(first.d)) / (365.25 * 86400e3) : 0
  const ann = v => (years >= 1 ? Math.pow(v, 1 / years) - 1 : null)
  const toPts = key => rebased.map(p => [new Date(p.d).getTime(), p[key]])
  const data = [{ name: '組合', data: toPts('nav') }, { name: '0050 含息', data: toPts('bench') }]
  const options = {
    chart: { type: 'line', toolbar: { show: false }, animations: { enabled: false }, background: 'transparent' },
    stroke: { width: [2.5, 1.5], curve: 'straight', dashArray: [0, 4] },
    colors: ['#2f80ed', '#9aa4b2'],
    xaxis: { type: 'datetime', labels: { datetimeUTC: false } },
    yaxis: { labels: { formatter: v => v.toFixed(2) }, title: { text: '淨值（區間起點 1）' } },
    tooltip: { x: { format: 'yyyy-MM-dd' }, y: { formatter: v => v.toFixed(3) } },
    legend: { position: 'top' },
    grid: { borderColor: 'rgba(128,128,128,0.2)' },
    theme: { mode: document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light' },
  }
  const presets = [...NAV_PRESETS(periodStart, periodEnd), ...extraPresets.filter(x => x && x[1] && x[2])]
  const activePreset = presets.find(([, s, e]) => s === start && e === end)?.[0]
  return (
    <>
      <div style={{ display: 'flex', gap: '.5rem', flexWrap: 'wrap', alignItems: 'flex-end', padding: '.6rem 1.25rem 0' }}>
        <div className="btn-group">{presets.map(([label, s, e]) => <button key={label} className={`btn-period${activePreset === label ? ' active' : ''}`} onClick={() => setRange({ start: s, end: e })}>{label}</button>)}</div>
        <div className="ctrl-group"><div className="ctrl-label">起</div><input type="date" className="ctrl-select" min={periodStart} max={periodEnd} value={start} onChange={e => setRange({ ...range, start: e.target.value })} /></div>
        <div className="ctrl-group"><div className="ctrl-label">迄</div><input type="date" className="ctrl-select" min={periodStart} max={periodEnd} value={end} onChange={e => setRange({ ...range, end: e.target.value })} /></div>
      </div>
      {last ? (
        <div className="muted" style={{ fontSize: '.82rem', padding: '.45rem 1.25rem 0' }}>
          {first.d} ～ {last.d}：組合 <strong className={tone(last.nav - 1)}>{pct(last.nav - 1, 1)}</strong>、0050 <strong>{pct(last.bench - 1, 1)}</strong>、主動 <strong className={tone(last.nav / last.bench - 1)}>{pct(last.nav / last.bench - 1, 1)}</strong>
          {years >= 1 ? <>　· 年化 {pct(ann(last.nav), 1)} 對 {pct(ann(last.bench), 1)}</> : null}
        </div>
      ) : <div className="card-body muted">這段區間沒有資料點（起點要早於迄點、都在 {periodStart} ～ {periodEnd} 內）</div>}
      {rebased.length > 1 ? <div className="chart-pad"><ReactApexChart type="line" series={data} options={options} height={320} /></div> : null}
    </>
  )
}

