// 歷史回放面板（Iteration 59 抽出；Iteration 60 給公開頁共用）
// 把引擎的整套規則（限價、重掛、停損、守門）套在候選期間的歷史清單與實際日線上，和「照單全收」對照。
// fetchReplay 由頁面決定：登入頁用 /trading/engine/replay，公開頁用 /sim/replay（同一個 FastAPI 回放）。
import { useEffect, useState } from 'react'
import ReactApexChart from 'react-apexcharts'

const money = v => (v == null ? '–' : Number(v).toLocaleString('zh-TW', { maximumFractionDigits: 0 }))
const pct = (v, d = 1) => (v == null ? '–' : `${(Number(v) * 100).toFixed(d)}%`)
const spct = (v, d = 2) => (v == null ? '–' : `${Number(v) > 0 ? '+' : ''}${(Number(v) * 100).toFixed(d)}%`)
function Sub({ children }) { return <div className="muted" style={{ fontSize: '0.74rem' }}>{children}</div> }
function Empty({ children }) { return <div className="muted" style={{ padding: '1rem 1.25rem', fontSize: '.88rem' }}>{children}</div> }
function readLS(k, fallback) { try { const v = localStorage.getItem(k); return v == null ? fallback : v } catch { return fallback } }
function writeLS(k, v) { try { localStorage.setItem(k, String(v)) } catch { /* 隱私模式 */ } }
const dark = () => document.documentElement.dataset.theme === 'dark'

// ═══════════════════════════════════════ 歷史模擬（Iteration 59） ═══════════════════════════════════════
const REPLAY_KEY = 'algo_replay'
const REPLAY_DEFAULT = { start: '2018-11-12', end: '2024-09-30', capital: 1000000, stop_loss_pct: 0.15, rel_dd_guard: 0.10, limit_slip: 0.005, max_attempts: 3 }

function ReplayChart({ r }) {
  const e = r.variants.engine.series, p = r.variants.plain.series
  if (!e?.length) return null
  const toPts = (arr, k) => arr.map(x => [new Date(x.d).getTime(), x[k]])
  const data = [
    { name: '引擎規則（限價＋重掛＋停損＋守門）', data: toPts(e, 'nav') },
    { name: '照單全收（紙上原本的方式）', data: toPts(p, 'nav') },
    { name: '0050 含息', data: toPts(e, 'bench') },
  ]
  const options = {
    chart: { type: 'line', toolbar: { show: false }, animations: { enabled: false }, background: 'transparent' },
    stroke: { width: [2.5, 2, 1.5], curve: 'straight', dashArray: [0, 0, 4] },
    colors: [dark() ? '#5b9dff' : '#1d6ff2', '#f2c14e', '#9aa4b2'],
    xaxis: { type: 'datetime', labels: { datetimeUTC: false } },
    yaxis: { labels: { formatter: v => v.toFixed(2) }, title: { text: '淨值（起點 1）' }, logarithmic: false },
    tooltip: { x: { format: 'yyyy-MM-dd' }, y: { formatter: v => v?.toFixed(3) } },
    legend: { position: 'top' },
    grid: { borderColor: 'rgba(128,128,128,0.18)' },
    theme: { mode: dark() ? 'dark' : 'light' },
  }
  return <div className="chart-pad"><ReactApexChart type="line" series={data} options={options} height={320} /></div>
}

function ReplayMetricsTable({ r }) {
  const e = r.variants.engine, p = r.variants.plain
  const rows = [
    ['總報酬', 'total_return', spct], ['0050 含息', 'bench_return', spct], ['主動報酬（期末）', 'active_return', spct], ['年化主動報酬', 'ann_active', spct],
    ['追蹤誤差', 'tracking_error', v => pct(v)], ['資訊比率', 'info_ratio', v => v ?? '–'], ['月勝率', 'monthly_win_rate', v => pct(v, 0)],
    ['相對最大落後', 'rel_mdd', v => pct(v)], ['最大回撤', 'mdd_port', v => pct(v)], ['年換手', 'turnover_annual', v => v ?? '–'], ['成本／年', 'cost_drag_annual', v => pct(v, 2)],
    ['期末淨值', 'final_nav', money],
  ]
  return (
    <table className="data-table">
      <thead><tr><th>指標</th><th className="num">引擎規則</th><th className="num">照單全收</th><th className="num">引擎 − 照單</th></tr></thead>
      <tbody>
        {rows.map(([label, k, f]) => {
          const a = e.metrics[k], b = p.metrics[k]
          const d = (typeof a === 'number' && typeof b === 'number') ? a - b : null
          return <tr key={k}><td>{label}</td><td className="num">{f(a)}</td><td className="num">{f(b)}</td><td className="num">{d == null ? '–' : <span className={d > 0 ? 'up' : d < 0 ? 'down' : 'muted'}>{k === 'final_nav' ? money(d) : k === 'info_ratio' || k === 'turnover_annual' ? d.toFixed(2) : spct(d)}</span>}</td></tr>
        })}
        {[['委託', 'orders'], ['成交', 'filled'], ['未成交重掛', 'unfilled'], ['取消', 'cancelled'], ['拒絕', 'rejected'], ['停損觸發', 'stop_loss'], ['守門擋買單的清單', 'guard_days']].map(([label, k]) => (
          <tr key={k}><td className="muted">{label}</td><td className="num">{e.stats[k]}</td><td className="num">{p.stats[k]}</td><td className="num muted">{e.stats[k] - p.stats[k]}</td></tr>
        ))}
        <tr><td className="muted">停損的已實現損益合計</td><td className="num"><span className={e.stop_loss_pnl < 0 ? 'down' : 'up'}>{money(e.stop_loss_pnl)}</span></td><td className="num">–</td><td className="num">–</td></tr>
      </tbody>
    </table>
  )
}

export default function ReplayPanel({ rules, fetchReplay }) {
  const [form, setForm] = useState(() => { try { return { ...REPLAY_DEFAULT, ...(JSON.parse(readLS(REPLAY_KEY, 'null')) || {}) } } catch { return REPLAY_DEFAULT } })
  const [r, setR] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  useEffect(() => { if (rules && !readLS(REPLAY_KEY, null)) setForm(f => ({ ...f, stop_loss_pct: rules.stop_loss_pct, rel_dd_guard: rules.rel_dd_guard, limit_slip: rules.limit_slip, max_attempts: rules.max_attempts })) }, [rules])
  async function run() {
    setBusy(true); setError('')
    writeLS(REPLAY_KEY, JSON.stringify(form))
    const { data, error } = await fetchReplay(form)
    setBusy(false)
    if (error) { setError(error); return }
    if (!data.available) { setError(`沒辦法回放：${data.reason}${data.notes?.length ? `（${data.notes.join('；')}）` : ''}`); setR(null); return }
    setR(data)
  }
  const F = (k, label, props = {}) => (
    <div className="ctrl-group"><div className="ctrl-label">{label}</div>
      <input className="ctrl-select" style={{ width: props.width || 110, textAlign: props.type === 'date' ? 'left' : 'right' }} type={props.type || 'number'} step={props.step}
             value={form[k] ?? ''} onChange={e => setForm({ ...form, [k]: props.type === 'date' ? e.target.value : Number(e.target.value) })} />
    </div>
  )
  const yrs = r ? Object.keys({ ...r.variants.engine.metrics.yearly_active, ...r.variants.plain.metrics.yearly_active }).sort() : []
  return (
    <>
      <div style={{ display: 'flex', gap: '.5rem', alignItems: 'flex-end', flexWrap: 'wrap', padding: '.9rem 1.25rem', borderBottom: '1px solid var(--border-soft)' }}>
        {F('start', '起', { type: 'date', width: 140 })}{F('end', '迄', { type: 'date', width: 140 })}{F('capital', '資金', { step: 100000, width: 120 })}
        <div className="ctrl-group"><div className="ctrl-label">停損（0 = 關）</div><input className="ctrl-select" style={{ width: 80, textAlign: 'right' }} type="number" step={0.01} value={form.stop_loss_pct} onChange={e => setForm({ ...form, stop_loss_pct: Number(e.target.value) })} /></div>
        {F('rel_dd_guard', '相對回撤守門', { step: 0.01, width: 90 })}{F('limit_slip', '限價 ±', { step: 0.001, width: 90 })}{F('max_attempts', '重掛上限', { step: 1, width: 80 })}
        <button className="btn-primary" disabled={busy} onClick={run}>{busy ? '回放中…' : '回放'}</button>
        <div className="btn-group">
          {[['停損 15%', { stop_loss_pct: 0.15 }], ['停損 25%', { stop_loss_pct: 0.25 }], ['不停損', { stop_loss_pct: 0 }], ['限價 ±1%', { limit_slip: 0.01 }]].map(([l, patch]) => (
            <button key={l} className="btn-period" onClick={() => setForm({ ...form, ...patch })}>{l}</button>
          ))}
        </div>
      </div>
      {error ? <div className="down" style={{ padding: '1rem 1.25rem' }}>{error}</div> : null}
      {!r && !error ? <Empty>選期間與規則按「回放」：把引擎的整套規則套在候選期間的歷史清單與實際日線上，和「照單全收」對照。候選清單從 2018-11-12 起到 2024-09-11；保留期（2024-10 起）沒有清單、不在這裡開。</Empty> : null}
      {r ? (
        <>
          {r.notes?.length ? <div className="note-box" style={{ color: 'var(--orange)' }}>{r.notes.map((n, i) => <div key={i}>⚠ {n}</div>)}</div> : null}
          <div className="stat-grid">
            <div className="stat-tile"><div className="k">期間</div><div className="v" style={{ fontSize: '1rem' }}>{r.start} ～ {r.end}</div><div className="s">{r.n_lists} 份清單 · {r.n_days} 個交易日 · {r.n_stocks} 檔 · run #{r.run_id}{r.cached ? ' · 快取' : ` · ${r.computed_in_s}s`}</div></div>
            <div className="stat-tile"><div className="k">引擎規則</div><div className="v"><span className={r.variants.engine.metrics.total_return > 0 ? 'up' : 'down'}>{spct(r.variants.engine.metrics.total_return, 1)}</span></div><div className="s">年化主動 {spct(r.variants.engine.metrics.ann_active)} · IR {r.variants.engine.metrics.info_ratio ?? '–'}</div></div>
            <div className="stat-tile"><div className="k">照單全收</div><div className="v"><span className={r.variants.plain.metrics.total_return > 0 ? 'up' : 'down'}>{spct(r.variants.plain.metrics.total_return, 1)}</span></div><div className="s">年化主動 {spct(r.variants.plain.metrics.ann_active)} · IR {r.variants.plain.metrics.info_ratio ?? '–'}</div></div>
            <div className="stat-tile"><div className="k">0050 含息</div><div className="v">{spct(r.variants.engine.metrics.bench_return, 1)}</div><div className="s">年化 {spct(r.variants.engine.metrics.cagr_bench)}</div></div>
            <div className="stat-tile"><div className="k">規則的代價／好處</div><div className="v"><span className={r.engine_minus_plain.total_return > 0 ? 'up' : 'down'}>{spct(r.engine_minus_plain.total_return, 1)}</span></div><div className="s">停損 {r.variants.engine.stats.stop_loss} 次（損益 {money(r.variants.engine.stop_loss_pnl)}）· 重掛 {r.variants.engine.stats.unfilled} · 取消 {r.variants.engine.stats.cancelled}</div></div>
          </div>
          <ReplayChart r={r} />
          <div className="two-col" style={{ padding: '0 1.25rem 1rem', gap: '1.1rem' }}>
            <div className="card"><div className="card-header"><div className="card-title">指標對照</div></div><ReplayMetricsTable r={r} /></div>
            <div className="card">
              <div className="card-header"><div className="card-title">逐年主動報酬</div><Sub>對 0050</Sub></div>
              <table className="data-table">
                <thead><tr><th>年</th><th className="num">引擎規則</th><th className="num">照單全收</th></tr></thead>
                <tbody>{yrs.map(y => <tr key={y}><td>{y}</td><td className="num"><span className={(r.variants.engine.metrics.yearly_active[y] ?? 0) > 0 ? 'up' : 'down'}>{spct(r.variants.engine.metrics.yearly_active[y])}</span></td><td className="num"><span className={(r.variants.plain.metrics.yearly_active[y] ?? 0) > 0 ? 'up' : 'down'}>{spct(r.variants.plain.metrics.yearly_active[y])}</span></td></tr>)}</tbody>
              </table>
              <div className="card-header" style={{ borderTop: '1px solid var(--border-soft)' }}><div className="card-title">停損紀錄</div><Sub>最近 {r.variants.engine.stop_losses.length} 筆</Sub></div>
              {r.variants.engine.stop_losses.length ? (
                <div style={{ maxHeight: 260, overflowY: 'auto' }}>
                  <table className="data-table">
                    <thead><tr><th>賣出日</th><th>股票</th><th className="num">股數</th><th className="num">成本</th><th className="num">觸發收盤</th><th className="num">賣價</th><th className="num">損益</th></tr></thead>
                    <tbody>{[...r.variants.engine.stop_losses].reverse().map((s, i) => <tr key={i}><td>{s.date}</td><td><strong>{s.stock_id}</strong></td><td className="num">{s.shares}</td><td className="num">{s.cost}</td><td className="num">{s.trigger_close}</td><td className="num">{s.sold}</td><td className="num"><span className={s.pnl > 0 ? 'up' : 'down'}>{money(s.pnl)}</span></td></tr>)}</tbody>
                  </table>
                </div>
              ) : <Empty>這組規則沒有觸發停損。</Empty>}
            </div>
          </div>
          <div className="note-box">{r.caveat}</div>
        </>
      ) : null}
    </>
  )
}

