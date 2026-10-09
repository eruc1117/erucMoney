// 程式交易（Iteration 57 手動指令 → Iteration 58 引擎）
// ───────────────────────────────────────────────────────────────────────────
// 程式交易 = 選股、進出場、停損、下單規則寫成程式，由電腦每天跑完整個流程；人看兩件事：
//   預測：如果回測成立，接下來 1／3／6／12 個月會長怎樣（期望、95% 區間、贏 0050 的機率），實際走勢有沒有在帶子裡
//   觀察：引擎今天做了什麼（委託、成交、未成交重掛、停損、守門）、每檔離停損還有多遠、下一個訊號日
//   歷史模擬：把整套規則套在候選期間的歷史清單與實際日線上，和「照單全收」對照——接上之後會賺還是賠，先在過去看一遍
// 券商：紙上（模擬帳戶）先跑，凱基接口已留（brokers/kgi.py），接上後切 live。
// 「手動指令」分頁留著：引擎沒開、或想用自己的帳戶照清單下單時用（Iteration 57）。
import { useCallback, useEffect, useState } from 'react'
import ReactApexChart from 'react-apexcharts'
import {
  getTradingPlan, getTradingLog, addTrade, getPortfolioPaper,
  getEngineStatus, getEngineOrders, getEngineEvents, getEngineForecast, setEngineConfig, runEngineDay, getEngineReplay,
} from '../services/api'
import ReplayPanel from '../components/ReplayPanel'
import { formatShares } from '../components/Shares'
import { isAdmin } from '../services/auth'

const TAB_KEY = 'algo_tab'
const CASH_KEY = 'algo_cash'
const MIN_KEY = 'algo_min_trade'
const QUICK = [100000, 300000, 500000, 1000000]

const money = v => (v == null ? '–' : Number(v).toLocaleString('zh-TW', { maximumFractionDigits: 0 }))
const pct = (v, d = 1) => (v == null ? '–' : `${(Number(v) * 100).toFixed(d)}%`)
const spct = (v, d = 2) => (v == null ? '–' : `${Number(v) > 0 ? '+' : ''}${(Number(v) * 100).toFixed(d)}%`)
const today = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}` }
const hhmm = ts => (ts ? new Date(ts).toLocaleString('zh-TW', { hour12: false, month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) : '–')
function Sub({ children }) { return <div className="muted" style={{ fontSize: '0.74rem' }}>{children}</div> }
function Empty({ children }) { return <div className="muted" style={{ padding: '1rem 1.25rem', fontSize: '.88rem' }}>{children}</div> }
function readLS(k, fallback) { try { const v = localStorage.getItem(k); return v == null ? fallback : v } catch { return fallback } }
function writeLS(k, v) { try { localStorage.setItem(k, String(v)) } catch { /* 隱私模式 */ } }
const dark = () => document.documentElement.dataset.theme === 'dark'

const ORDER_STATUS = { pending: ['yellow', '待成交'], filled: ['green', '已成交'], unfilled: ['yellow', '未成交'], cancelled: ['', '已取消'], rejected: ['red', '拒絕'] }
const ORDER_REASON = { rebalance: '調倉', exit: '退出清單', stop_loss: '停損' }
const EVENT_KIND = {
  signal: ['📋', '訊號日：算新清單'], orders: ['🧾', '產生委託'], fill: ['✅', '成交'], unfilled: ['↻', '未成交，重掛'], cancelled: ['✖', '重掛到上限，取消'],
  rejected: ['⛔', '券商拒絕'], stop_loss: ['🛑', '觸發停損'], guard: ['🛡', '相對回撤守門：暫停買單'], error: ['⚠', '錯誤'], config: ['⚙', '設定變更'], no_quote: ['？', '沒行情'],
}

// ═══════════════════════════════════════ 引擎 ═══════════════════════════════════════
function EngineTab({ status, reload }) {
  const [busy, setBusy] = useState('')
  const [msg, setMsg] = useState('')
  const admin = isAdmin()
  const e = status?.engine
  const rules = e?.rules || {}
  const [draft, setDraft] = useState(null)
  useEffect(() => { setDraft(e ? { stop_loss_pct: rules.stop_loss_pct, rel_dd_guard: rules.rel_dd_guard, limit_slip: rules.limit_slip, max_attempts: rules.max_attempts } : null) }, [status]) // eslint-disable-line

  async function act(label, fn) {
    setBusy(label); setMsg('')
    const { data, error } = await fn()
    setBusy('')
    setMsg(error ? `${label}失敗：${error}` : `${label}完成${data?.sent ? `：送單 ${data.sent.length} 日、結算 ${data.marked} 日、停損 ${data.stop_loss?.length || 0}、調倉單 ${data.orders?.length || 0}` : data?.skipped ? `（略過：${data.skipped}）` : ''}`)
    reload()
  }

  if (!status) return <Empty>讀不到引擎狀態（爬蟲服務要在跑）。</Empty>
  return (
    <>
      <div className="stat-grid">
        <div className="stat-tile"><div className="k">引擎</div><div className="v"><span className={e?.enabled ? 'up' : 'muted'}>{e?.enabled ? '執行中' : '關閉'}</span></div><div className="s">{e?.mode === 'live' ? '實單（凱基）' : '紙上（模擬帳戶）'} · 候選 run #{e?.run_id ?? status.account?.run_id ?? '–'}</div></div>
        <div className="stat-tile"><div className="k">券商</div><div className="v"><span className={status.broker_ready ? 'up' : 'down'}>{status.broker_ready ? '就緒' : '未就緒'}</span></div><div className="s" title={status.broker_note}>{status.broker_note || e?.broker}</div></div>
        <div className="stat-tile"><div className="k">下一個訊號日</div><div className="v" style={{ fontSize: '1.05rem' }}>{status.next_signal_date || '–'}</div><div className="s">最近清單 {status.last_list || '–'}</div></div>
        <div className="stat-tile"><div className="k">委託</div><div className="v">{(status.pending || []).length} 待成交</div><div className="s">{Object.entries(status.orders || {}).map(([k, v]) => `${ORDER_STATUS[k]?.[1] || k} ${v}`).join(' · ') || '還沒有委託'}</div></div>
        <div className="stat-tile"><div className="k">最後執行</div><div className="v" style={{ fontSize: '1.05rem' }}>{hhmm(e?.last_run_at)}</div><div className="s" style={{ color: e?.last_error ? 'var(--red)' : undefined }} title={e?.last_error || ''}>{e?.last_error ? `錯誤：${e.last_error}` : '每日 18:40 排程（日線進來之後）'}</div></div>
        <div className="stat-tile"><div className="k">模擬帳戶</div><div className="v" style={{ fontSize: '1.05rem' }}>{status.account ? money(status.account.cash) : '未開'}</div><div className="s">{status.account ? `現金 · ${status.account.started_on} 起 ${money(status.account.start_capital)}` : 'python portfolio_paper.py --start'}</div></div>
      </div>

      <div style={{ padding: '.9rem 1.25rem', borderTop: '1px solid var(--border-soft)' }}>
        <div style={{ fontSize: '.74rem', fontWeight: 700, color: 'var(--dim)', letterSpacing: '.04em', marginBottom: '.4rem' }}>規則（寫成程式的部分）</div>
        <table className="data-table" style={{ fontSize: '.86rem' }}>
          <tbody>{Object.entries(status.rules_text || {}).map(([k, v]) => <tr key={k}><td style={{ width: '6rem', fontWeight: 700 }}>{k}</td><td style={{ whiteSpace: 'normal' }}>{v}</td></tr>)}</tbody>
        </table>
      </div>

      {admin ? (
        <div style={{ padding: '.9rem 1.25rem', borderTop: '1px solid var(--border-soft)', display: 'flex', gap: '.6rem', flexWrap: 'wrap', alignItems: 'flex-end' }}>
          <button className={e?.enabled ? 'btn-danger' : 'btn-primary'} disabled={!!busy} onClick={() => act(e?.enabled ? '關閉引擎' : '啟動引擎', () => setEngineConfig({ enabled: !e?.enabled, mode: e?.mode || 'paper' }))}>{e?.enabled ? '關閉引擎' : '啟動引擎（紙上）'}</button>
          <button className="btn-secondary" disabled={!!busy || !e?.enabled} onClick={() => act('手動跑今天', () => runEngineDay())}>手動跑今天</button>
          <button className="btn-secondary" disabled={!!busy} title="凱基 API 要先申請並填 KGI_* 環境變數；沒設好引擎會停下來記錯誤，不會送單" onClick={() => act(e?.mode === 'live' ? '切回紙上' : '切到實單', () => setEngineConfig({ mode: e?.mode === 'live' ? 'paper' : 'live' }))}>{e?.mode === 'live' ? '切回紙上' : '切到實單（凱基）'}</button>
          {draft ? (
            <>
              {[['stop_loss_pct', '停損 %', 100], ['rel_dd_guard', '相對回撤守門 %', 100], ['limit_slip', '限價 ±%', 100], ['max_attempts', '重掛上限', 1]].map(([k, label, mul]) => (
                <div className="ctrl-group" key={k}>
                  <div className="ctrl-label">{label}</div>
                  <input type="number" className="ctrl-select" style={{ width: 92, textAlign: 'right' }} step={mul === 1 ? 1 : 0.1}
                         value={draft[k] == null ? '' : +(draft[k] * mul).toFixed(3)} onChange={ev => setDraft({ ...draft, [k]: Number(ev.target.value) / mul })} />
                </div>
              ))}
              <button className="btn-secondary" disabled={!!busy} onClick={() => act('儲存規則', () => setEngineConfig({ rules: draft }))}>儲存規則</button>
            </>
          ) : null}
          {busy ? <span className="muted" style={{ fontSize: '.8rem' }}>{busy}中…</span> : msg ? <span className="muted" style={{ fontSize: '.8rem' }}>{msg}</span> : null}
        </div>
      ) : <Empty>開關與規則只有 admin 能改。</Empty>}
    </>
  )
}

// ═══════════════════════════════════════ 預測 ═══════════════════════════════════════
function ForecastChart({ forecast, paper }) {
  const band = forecast?.band || []
  const series = paper?.review?.series || []
  if (!band.length) return null
  const start = new Date(forecast.started_on + 'T00:00:00')
  const monthTs = k => { const d = new Date(start); d.setMonth(d.getMonth() + k); return d.getTime() }
  const data = [
    { name: '預期（中位）', type: 'line', data: band.map(b => [monthTs(b.month), b.mid]) },
    { name: '95% 上緣', type: 'line', data: band.map(b => [monthTs(b.month), b.hi]) },
    { name: '95% 下緣', type: 'line', data: band.map(b => [monthTs(b.month), b.lo]) },
    { name: '實際（對 0050 的相對淨值）', type: 'line', data: series.filter(p => p.bench).map(p => [new Date(p.d).getTime(), +(p.nav / p.bench).toFixed(4)]) },
  ]
  const options = {
    chart: { type: 'line', toolbar: { show: false }, animations: { enabled: false }, background: 'transparent' },
    stroke: { width: [2, 1.2, 1.2, 2.5], curve: 'straight', dashArray: [0, 5, 5, 0] },
    colors: [dark() ? '#9aa4b2' : '#6b7280', '#35c76a', '#ff5f57', dark() ? '#5b9dff' : '#1d6ff2'],
    xaxis: { type: 'datetime', labels: { datetimeUTC: false } },
    yaxis: { labels: { formatter: v => v.toFixed(2) }, title: { text: '相對 0050（起點 1）' } },
    tooltip: { x: { format: 'yyyy-MM-dd' }, y: { formatter: v => v?.toFixed(3) } },
    legend: { position: 'top' },
    grid: { borderColor: 'rgba(128,128,128,0.18)' },
    theme: { mode: dark() ? 'dark' : 'light' },
  }
  return <div className="chart-pad"><ReactApexChart type="line" series={data} options={options} height={300} /></div>
}

function ForecastTab({ forecast, paper }) {
  if (!forecast) return <Empty>讀不到預測。</Empty>
  if (!forecast.available) return <Empty>沒辦法預測：{forecast.reason}</Empty>
  const a = forecast.actual
  const inp = forecast.inputs
  return (
    <>
      <div className="stat-grid">
        <div className="stat-tile"><div className="k">依據</div><div className="v" style={{ fontSize: '1rem' }}>run #{forecast.run_id}</div><div className="s">{forecast.run_name}</div></div>
        <div className="stat-tile"><div className="k">年化主動報酬（回測）</div><div className="v"><span className={inp.ann_active > 0 ? 'up' : 'down'}>{spct(inp.ann_active)}</span></div><div className="s">追蹤誤差 {pct(inp.tracking_error)} · IR {inp.info_ratio}</div></div>
        <div className="stat-tile"><div className="k">月勝率（回測）</div><div className="v">{pct(inp.monthly_win_rate, 0)}</div><div className="s">DSR {inp.dsr}（≥ 0.95 才算不是運氣）</div></div>
        <div className="stat-tile"><div className="k">實際 vs 預期</div><div className="v">{a ? <span className={a.active_return >= 0 ? 'up' : 'down'}>{spct(a.active_return)}</span> : '–'}</div><div className="s">{a ? `${a.days} 個交易日（約 ${a.months} 個月）· 預期 ${spct(a.expected)} ± ${pct(a.sd)} · z = ${a.z}${a.within_band ? '，在帶內' : '，出帶'}` : '模擬帳戶還沒有結算'}</div></div>
      </div>
      <div style={{ padding: '.9rem 1.25rem', borderTop: '1px solid var(--border-soft)' }}>
        <div style={{ fontSize: '.74rem', fontWeight: 700, color: 'var(--dim)', letterSpacing: '.04em', marginBottom: '.4rem' }}>接下來會長怎樣（如果回測成立）</div>
        <table className="data-table">
          <thead><tr><th>期間</th><th className="num">預期主動報酬</th><th className="num">95% 區間</th><th className="num">贏過 0050 的機率</th></tr></thead>
          <tbody>{forecast.horizons.map(h => (
            <tr key={h.months}><td>{h.months} 個月</td><td className="num"><strong className={h.expected_active > 0 ? 'up' : 'down'}>{spct(h.expected_active)}</strong></td>
              <td className="num">{spct(h.lo95)} ～ {spct(h.hi95)}</td><td className="num">{h.p_beat == null ? '–' : pct(h.p_beat, 0)}</td></tr>
          ))}</tbody>
        </table>
      </div>
      <ForecastChart forecast={forecast} paper={paper} />
      <div className="note-box">{forecast.caveat}</div>
    </>
  )
}

// ═══════════════════════════════════════ 觀察 ═══════════════════════════════════════
function OrdersTable({ orders }) {
  if (!orders?.length) return <Empty>還沒有委託。引擎在訊號日收盤後產生調倉單，隔天開盤送出。</Empty>
  return (
    <div style={{ overflowX: 'auto', maxHeight: 420, overflowY: 'auto' }}>
      <table className="data-table">
        <thead><tr><th>下單日</th><th>清單</th><th>動作</th><th>股票</th><th className="num">股數</th><th className="num">限價</th><th>原因</th><th className="mid">狀態</th><th className="num">成交</th><th>備註</th></tr></thead>
        <tbody>{orders.map(o => {
          const [cls, label] = ORDER_STATUS[o.status] || ['', o.status]
          return (
            <tr key={o.id}>
              <td>{o.order_date}</td><td>{o.rebalance_date || '–'}</td>
              <td><strong className={o.side === 'buy' ? 'up' : 'down'}>{o.side === 'buy' ? '買' : '賣'}</strong></td>
              <td><strong>{o.stock_id}</strong> {o.stock_name || ''}</td>
              <td className="num">{o.shares?.toLocaleString()}<Sub>{formatShares(o.shares || 0)}</Sub></td>
              <td className="num">{o.limit_price ?? '市價'}</td>
              <td>{ORDER_REASON[o.reason] || o.reason}</td>
              <td className="mid"><span className={`tag ${cls}`}>{label}</span>{o.attempts > 1 ? <Sub>第 {o.attempts} 次</Sub> : null}</td>
              <td className="num">{o.status === 'filled' ? <>{o.filled_shares?.toLocaleString()} @ {o.filled_price}<Sub>{o.filled_at}</Sub></> : '–'}</td>
              <td className="muted" style={{ whiteSpace: 'normal', maxWidth: 260, fontSize: '.78rem' }}>{o.note || ''}</td>
            </tr>
          )
        })}</tbody>
      </table>
    </div>
  )
}

function WatchTable({ watch }) {
  if (!watch?.length) return <Empty>模擬帳戶沒有持股。</Empty>
  return (
    <table className="data-table">
      <thead><tr><th>股票</th><th className="num">股數</th><th className="num">成本</th><th className="num">最後收盤</th><th className="num">損益</th><th className="num">停損價</th><th className="num">距停損</th></tr></thead>
      <tbody>{watch.map(w => (
        <tr key={w.stock_id} style={{ background: w.to_stop_pct != null && w.to_stop_pct < 0.03 ? 'var(--red-soft)' : undefined }}>
          <td><strong>{w.stock_id}</strong></td><td className="num">{w.shares.toLocaleString()}</td><td className="num">{w.cost ?? '–'}</td><td className="num">{w.last ?? '–'}</td>
          <td className="num"><span className={w.pnl_pct > 0 ? 'up' : w.pnl_pct < 0 ? 'down' : 'muted'}>{spct(w.pnl_pct)}</span></td>
          <td className="num">{w.stop ?? '–'}</td><td className="num">{w.to_stop_pct == null ? '–' : <span className={w.to_stop_pct < 0.03 ? 'down' : ''}>{pct(w.to_stop_pct)}</span>}</td>
        </tr>
      ))}</tbody>
    </table>
  )
}

function EventList({ events }) {
  if (!events?.length) return <Empty>還沒有事件。</Empty>
  return (
    <div style={{ maxHeight: 420, overflowY: 'auto' }}>
      {events.map(ev => {
        const [icon, label] = EVENT_KIND[ev.kind] || ['·', ev.kind]
        const d = ev.detail || {}
        const text = ev.kind === 'fill' ? `${d.side === 'buy' ? '買' : '賣'} ${d.shares} 股 @ ${d.price}（${ORDER_REASON[d.reason] || d.reason}）`
          : ev.kind === 'orders' ? `清單 ${d.rebalance_date}：${d.n} 張（賣 ${d.sell}、買 ${d.buy}）${d.guard ? '，守門擋掉買單' : ''}`
          : ev.kind === 'signal' ? `清單 ${d.rebalance_date}：${d.n} 檔，新進 ${(d.new || []).join('、') || '無'}`
          : ev.kind === 'stop_loss' ? `收盤 ${d.close} ≤ 成本 ${d.cost}，${d.shares} 股隔天賣`
          : ev.kind === 'unfilled' ? `${d.note}；新限價 ${d.new_limit}`
          : ev.kind === 'error' ? d.msg : ev.kind === 'guard' ? `清單 ${d.rebalance_date}：擋掉 ${d.skipped_buys} 張買單`
          : ev.kind === 'config' ? Object.entries(d).filter(([, v]) => v != null).map(([k, v]) => `${k}=${typeof v === 'object' ? JSON.stringify(v) : v}`).join(' ') : JSON.stringify(d)
        return (
          <div key={ev.id} style={{ display: 'grid', gridTemplateColumns: '1.4rem 7rem 1fr', gap: '.5rem', alignItems: 'baseline', padding: '.42rem 1.25rem', borderBottom: '1px solid var(--border-soft)', fontSize: '.84rem', background: ev.kind === 'error' ? 'var(--red-soft)' : undefined }}>
            <span>{icon}</span>
            <span className="muted" style={{ fontSize: '.74rem', fontVariantNumeric: 'tabular-nums' }}>{hhmm(ev.ts)}</span>
            <span><strong style={{ marginRight: '.4rem' }}>{label}</strong>{ev.stock_id ? <strong style={{ marginRight: '.3rem' }}>{ev.stock_id}</strong> : null}{text}</span>
          </div>
        )
      })}
    </div>
  )
}

function ObserveTab({ status, orders, events, paper }) {
  const [filter, setFilter] = useState('')
  const shown = filter ? (orders || []).filter(o => o.status === filter) : orders
  const r = paper?.review
  const nearest = [...(status?.watch || [])].filter(x => x.to_stop_pct != null).sort((a, b) => a.to_stop_pct - b.to_stop_pct)[0]
  return (
    <>
      <div className="stat-grid">
        <div className="stat-tile"><div className="k">模擬帳戶對 0050</div><div className="v">{r?.days ? <span className={r.active_return > 0 ? 'up' : 'down'}>{spct(r.active_return)}</span> : '–'}</div><div className="s">{r?.days ? `${r.since} ～ ${r.as_of}，${r.days} 個交易日 · 組合 ${spct(r.port_return)} / 0050 ${spct(r.bench_return)}` : '尚未結算'}</div></div>
        <div className="stat-tile"><div className="k">淨值</div><div className="v">{r?.nav ? money(r.nav) : '–'}</div><div className="s">{r?.nav ? `現金 ${money(r.cash)} · ${r.n_holdings} 檔` : ''}</div></div>
        <div className="stat-tile"><div className="k">待成交</div><div className="v">{(status?.pending || []).length}</div><div className="s">{(status?.pending || []).slice(0, 4).map(p => `${p.side === 'buy' ? '買' : '賣'} ${p.stock_id}`).join('、')}</div></div>
        <div className="stat-tile"><div className="k">最接近停損</div>{nearest ? <><div className="v"><span className={nearest.to_stop_pct < 0.03 ? 'down' : ''}>{nearest.stock_id}</span></div><div className="s">距停損 {pct(nearest.to_stop_pct)} · 損益 {spct(nearest.pnl_pct)}</div></> : <><div className="v">–</div><div className="s">沒有持股</div></>}</div>
      </div>
      <div className="two-col" style={{ padding: '1rem 1.25rem 0', gap: '1.1rem' }}>
        <div className="card">
          <div className="card-header"><div className="card-title">停損監看</div><Sub>收盤 ≤ 成本 × (1 − {pct(status?.engine?.rules?.stop_loss_pct ?? 0.15, 0)}) 隔天賣</Sub></div>
          <WatchTable watch={status?.watch} />
        </div>
        <div className="card">
          <div className="card-header"><div className="card-title">引擎事件</div><Sub>最近 {events?.length || 0} 筆</Sub></div>
          <EventList events={events} />
        </div>
      </div>
      <div style={{ padding: '1rem 1.25rem' }}>
        <div className="card">
          <div className="card-header">
            <div className="card-title">委託單</div>
            <div className="btn-group">{[['', '全部'], ['pending', '待成交'], ['filled', '已成交'], ['cancelled', '取消'], ['rejected', '拒絕']].map(([k, l]) => <button key={k} className={`btn-period${filter === k ? ' active' : ''}`} onClick={() => setFilter(k)}>{l}</button>)}</div>
          </div>
          <OrdersTable orders={shown} />
        </div>
      </div>
    </>
  )
}

// ═══════════════════════════════════════ 手動指令（Iteration 57） ═══════════════════════════════════════
const REASON = { new: ['新進場', 'green'], exit: ['退出清單', 'red'], rebalance: ['調整權重', 'blue'] }

function ManualOrders({ plan, onRegistered }) {
  const [checked, setChecked] = useState({})
  const [fills, setFills] = useState({})
  const [date, setDate] = useState(today())
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')
  useEffect(() => { setChecked({}); setFills({}) }, [plan?.list?.rebalance_date, plan?.summary?.cash])
  const orders = plan.orders
  const picked = orders.filter(o => checked[o.stock_id])
  async function register() {
    if (!picked.length) return
    setBusy(true); setMsg('')
    let ok = 0; const errs = []
    for (const o of picked) {
      const { error } = await addTrade({ stock_id: o.stock_id, trade_date: date, side: o.side, shares: o.shares, price: Number(fills[o.stock_id] ?? o.price), note: plan.note })
      if (error) errs.push(`${o.stock_id}：${error}`); else ok++
    }
    setBusy(false); setChecked({})
    setMsg(errs.length ? `登記 ${ok} 筆，失敗 ${errs.length} 筆：${errs.join('；')}` : `已登記 ${ok} 筆進交易台帳（${plan.note}）`)
    onRegistered()
  }
  function copyText() {
    const text = `${plan.note}\n${orders.map(o => `${o.side === 'Buy' ? '買' : '賣'} ${o.stock_id} ${o.stock_name || ''} ${o.shares} 股 @${o.price}（約 ${money(o.gross)}）`).join('\n')}`
    try { navigator.clipboard.writeText(text); setMsg('指令已複製到剪貼簿') } catch { setMsg('瀏覽器不讓複製，請手動選取') }
  }
  if (!orders.length) return <Empty>依目前持股與現金，沒有需要下的單（偏離 {pct(plan.summary.drift_before)}，每筆調整都小於 NT${money(plan.summary.min_trade)}）。</Empty>
  return (
    <>
      <div style={{ display: 'flex', gap: '.6rem', alignItems: 'center', flexWrap: 'wrap', padding: '.7rem 1.25rem', borderBottom: '1px solid var(--border-soft)' }}>
        <label style={{ display: 'flex', alignItems: 'center', gap: '.35rem', fontSize: '.84rem' }}><input type="checkbox" checked={orders.length > 0 && picked.length === orders.length} onChange={e => setChecked(e.target.checked ? Object.fromEntries(orders.map(o => [o.stock_id, true])) : {})} /> 全選</label>
        <label style={{ fontSize: '.84rem' }}>成交日 <input type="date" className="ctrl-select" value={date} onChange={e => setDate(e.target.value)} /></label>
        <button className="btn-primary" disabled={!picked.length || busy} onClick={register}>{busy ? '登記中…' : `登記已執行的 ${picked.length} 筆`}</button>
        <button className="btn-secondary" onClick={copyText}>複製指令文字</button>
        {msg ? <span className="muted" style={{ fontSize: '.8rem' }}>{msg}</span> : null}
      </div>
      <div style={{ overflowX: 'auto' }}>
        <table className="data-table">
          <thead><tr><th className="mid">已執行</th><th>動作</th><th>股票</th><th className="num">股數</th><th className="num">參考價</th><th className="num">成交價<Sub>可改</Sub></th><th className="num">金額</th><th className="num">費用</th><th className="num">權重<Sub>現在 → 目標</Sub></th><th>原因</th></tr></thead>
          <tbody>{orders.map(o => { const [label, cls] = REASON[o.reason] || [o.reason, '']; return (
            <tr key={o.stock_id} style={{ background: checked[o.stock_id] ? 'var(--blue-soft)' : undefined }}>
              <td className="mid"><input type="checkbox" checked={!!checked[o.stock_id]} onChange={e => setChecked({ ...checked, [o.stock_id]: e.target.checked })} /></td>
              <td><strong className={o.side === 'Buy' ? 'up' : 'down'}>{o.side === 'Buy' ? '買進' : '賣出'}</strong></td>
              <td><strong>{o.stock_id}</strong> {o.stock_name || ''}</td>
              <td className="num"><strong>{o.shares.toLocaleString()}</strong> 股<Sub>{formatShares(o.shares)}</Sub></td>
              <td className="num">{o.price}</td>
              <td className="num"><input type="number" step="0.01" className="ctrl-select" style={{ width: 96, textAlign: 'right' }} value={fills[o.stock_id] ?? o.price} onChange={e => setFills({ ...fills, [o.stock_id]: e.target.value })} /></td>
              <td className="num">{money(o.gross)}</td><td className="num">{money(o.fee + o.tax)}</td>
              <td className="num">{pct(o.weight_now)} → {pct(o.weight_target)}<Sub>{o.shares_now.toLocaleString()} → {o.shares_target.toLocaleString()} 股</Sub></td>
              <td><span className={`tag ${cls}`}>{label}</span></td>
            </tr>) })}</tbody>
        </table>
      </div>
    </>
  )
}

function ManualTab() {
  const [cash, setCash] = useState(() => Number(readLS(CASH_KEY, 300000)))
  const [minTrade, setMinTrade] = useState(() => Number(readLS(MIN_KEY, 1000)))
  const [plan, setPlan] = useState(null)
  const [log, setLog] = useState(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const load = useCallback(async (c = cash, m = minTrade) => {
    setLoading(true)
    const [p, l] = await Promise.all([getTradingPlan(c, m), getTradingLog()])
    if (p.error) { setError(p.error); setPlan(null) } else { setError(''); setPlan(p.data) }
    setLog(l.data); setLoading(false)
  }, [cash, minTrade])
  useEffect(() => { load() }, []) // eslint-disable-line react-hooks/exhaustive-deps
  const s = plan?.summary
  return (
    <>
      <div style={{ display: 'flex', gap: '.5rem', alignItems: 'flex-end', flexWrap: 'wrap', padding: '.9rem 1.25rem', borderBottom: '1px solid var(--border-soft)' }}>
        <Sub>{plan?.list ? <>清單訊號日 <strong>{plan.list.rebalance_date}</strong> · {plan.list.n} 檔 · 參考價至 {plan.list.price_date || '–'}</> : '清單讀取中'}</Sub>
        <div className="ctrl-group"><div className="ctrl-label">可投入現金（NT$）</div><input type="number" className="ctrl-select" style={{ width: 140, textAlign: 'right' }} value={cash} min={0} step={10000} onChange={e => setCash(Number(e.target.value))} /></div>
        <div className="btn-group">{QUICK.map(q => <button key={q} className={`btn-period${cash === q ? ' active' : ''}`} onClick={() => setCash(q)}>{q / 10000} 萬</button>)}</div>
        <div className="ctrl-group"><div className="ctrl-label">最小下單金額</div><input type="number" className="ctrl-select" style={{ width: 96, textAlign: 'right' }} value={minTrade} min={0} step={500} onChange={e => setMinTrade(Number(e.target.value))} /></div>
        <button className="btn-primary" onClick={() => { writeLS(CASH_KEY, cash); writeLS(MIN_KEY, minTrade); load(cash, minTrade) }} disabled={loading}>{loading ? '計算中…' : '產生指令'}</button>
      </div>
      {error ? <div className="down" style={{ padding: '1rem 1.25rem' }}>{error}</div> : null}
      {s ? (
        <div className="stat-grid">
          <div className="stat-tile"><div className="k">總資產（範圍內）</div><div className="v">{money(s.total)}</div><div className="s">現金 {money(s.cash)} ＋ 策略持股 {money(s.position_value)}</div></div>
          <div className="stat-tile"><div className="k">指令</div><div className="v"><span className="down">{s.n_sell} 賣</span> / <span className="up">{s.n_buy} 買</span></div><div className="s">賣出淨入 {money(s.sell_net)} · 買進成本 {money(s.buy_cost)}</div></div>
          <div className="stat-tile"><div className="k">執行後現金</div><div className="v">{money(s.cash_after)}</div><div className="s">費用合計 {money(s.fees)}</div></div>
          <div className="stat-tile"><div className="k">權重偏離</div><div className="v">{pct(s.drift_before)} → {pct(s.drift_after)}</div><div className="s">不動的其他持股 {plan.untouched.length} 檔</div></div>
        </div>
      ) : null}
      {plan?.warnings?.length ? <div className="note-box" style={{ color: 'var(--orange)' }}>{plan.warnings.map((w, i) => <div key={i}>⚠ {w}</div>)}</div> : null}
      {plan ? <ManualOrders plan={plan} onRegistered={() => load(cash, minTrade)} /> : null}
      <div className="card-header" style={{ borderTop: '1px solid var(--border-soft)' }}><div className="card-title">執行紀錄</div><Sub>台帳裡 note 以 [程式交易] 開頭的交易，按清單分批</Sub></div>
      {log?.items?.length ? (
        <div style={{ maxHeight: 320, overflowY: 'auto' }}>
          <table className="data-table">
            <thead><tr><th>成交日</th><th>清單</th><th>動作</th><th>股票</th><th className="num">股數</th><th className="num">價格</th><th className="num">金額</th><th className="num">費用</th><th className="num">之後持有</th><th className="num">已實現</th></tr></thead>
            <tbody>{log.items.map(t => (
              <tr key={t.id}><td>{t.trade_date}</td><td>{t.batch || '–'}</td><td><span className={t.side === 'Buy' ? 'up' : 'down'}>{t.side === 'Buy' ? '買' : '賣'}</span></td><td><strong>{t.stock_id}</strong> {t.stock_name || ''}</td>
                <td className="num">{t.shares?.toLocaleString()}</td><td className="num">{t.price}</td><td className="num">{money(t.gross)}</td><td className="num">{money((t.fee || 0) + (t.tax || 0))}</td><td className="num">{t.shares_after?.toLocaleString() ?? '–'}</td>
                <td className="num">{t.realized_pnl != null ? <span className={t.realized_pnl > 0 ? 'up' : t.realized_pnl < 0 ? 'down' : 'muted'}>{money(t.realized_pnl)}</span> : '–'}</td></tr>
            ))}</tbody>
          </table>
        </div>
      ) : <Empty>還沒有用手動指令登記過的交易。</Empty>}
      <div className="note-box">沒接券商時的手動路徑：這裡算指令，你到券商 App 用零股限價單下，成交價填回再登記；台帳會重算均價與已實現損益。手續費 0.1425%（零股最低 1 元），賣出另有 0.3% 證交稅。</div>
    </>
  )
}

// ═══════════════════════════════════════ 頁 ═══════════════════════════════════════
const TABS = [['engine', '引擎'], ['forecast', '預測'], ['observe', '觀察'], ['replay', '歷史模擬'], ['manual', '手動指令']]

export default function AlgoTrading() {
  const [tab, setTab] = useState(() => readLS(TAB_KEY, 'engine'))
  const [status, setStatus] = useState(null)
  const [orders, setOrders] = useState(null)
  const [events, setEvents] = useState(null)
  const [forecast, setForecast] = useState(null)
  const [paper, setPaper] = useState(null)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    const [s, o, ev, f, p] = await Promise.all([getEngineStatus(), getEngineOrders(null, 300), getEngineEvents(120), getEngineForecast(), getPortfolioPaper()])
    setError(s.error || '')
    setStatus(s.data); setOrders(o.data?.orders || null); setEvents(ev.data?.events || null); setForecast(f.data); setPaper(p.data)
  }, [])
  useEffect(() => { load(); const t = setInterval(load, 60_000); return () => clearInterval(t) }, [load])
  function pick(k) { setTab(k); writeLS(TAB_KEY, k) }

  const e = status?.engine
  return (
    <>
      <div className="card" style={{ marginBottom: '1.1rem' }}>
        <div className="card-header">
          <div>
            <div className="card-title">程式交易</div>
            <Sub>選股、進出場、停損、下單規則寫成程式，每天 18:40 自動跑；{e ? `${e.enabled ? '執行中' : '關閉'} · ${e.mode === 'live' ? '實單（凱基）' : '紙上（模擬帳戶）'}` : '狀態讀取中'}{status?.next_signal_date ? ` · 下一個訊號日約 ${status.next_signal_date}` : ''}</Sub>
          </div>
          <div className="btn-group">{TABS.map(([k, l]) => <button key={k} className={`btn-period${tab === k ? ' active' : ''}`} onClick={() => pick(k)}>{l}</button>)}</div>
        </div>
        {error ? <div className="down" style={{ padding: '.8rem 1.25rem' }}>{error}</div> : null}
        {tab === 'engine' ? <EngineTab status={status} reload={load} /> : null}
        {tab === 'forecast' ? <ForecastTab forecast={forecast} paper={paper} /> : null}
        {tab === 'observe' ? <ObserveTab status={status} orders={orders} events={events} paper={paper} /> : null}
        {tab === 'replay' ? <ReplayPanel rules={status?.engine?.rules} fetchReplay={getEngineReplay} /> : null}
        {tab === 'manual' ? <ManualTab /> : null}
      </div>
      <div className="card"><div className="note-box">
        紙上模式的成交用隔天實際開盤價模擬零股限價單（買：開盤 ≤ 限價才成交；賣：開盤 ≥ 限價），寫進同一本模擬帳戶，淨值曲線在「月調倉」頁也看得到。<br />
        凱基：官方 Python 套件 kgiapp（.NET Framework 4.5、要先申請）；接口在 Crawler/brokers/kgi.py，填好 KGI_* 環境變數並實作 execute 後切「實單」。沒設好引擎會停下來記錯誤，不會送出任何單。
      </div></div>
    </>
  )
}
