// 條件規則（Iteration 61）：「條件 → 買／賣」的模組化輸入。使用者挑股票、條件、動作，可套模板；後端逐日用實際行情判斷、觸發隔天開盤成交。
// 用在 TradingSim（公開頁）。runRules 由頁面給（公開頁用 /sim/rules）。
import { useEffect, useState } from 'react'
import ReactApexChart from 'react-apexcharts'

const RULES_KEY = 'sim_rules'
const money = v => (v == null ? '–' : Number(v).toLocaleString('zh-TW', { maximumFractionDigits: 0 }))
const pct = (v, d = 1) => (v == null ? '–' : `${(Number(v) * 100).toFixed(d)}%`)
const spct = (v, d = 2) => (v == null ? '–' : `${Number(v) > 0 ? '+' : ''}${(Number(v) * 100).toFixed(d)}%`)
function Sub({ children }) { return <div className="muted" style={{ fontSize: '0.74rem' }}>{children}</div> }
function Empty({ children }) { return <div className="muted" style={{ padding: '1rem 1.25rem', fontSize: '.88rem' }}>{children}</div> }
function readJSON(k, fallback) { try { const v = JSON.parse(localStorage.getItem(k)); return v ?? fallback } catch { return fallback } }
function writeLS(k, v) { try { localStorage.setItem(k, v) } catch { /* 隱私模式 */ } }
const dark = () => document.documentElement.dataset.theme === 'dark'
const codeOf = s => String(s || '').trim().split(/\s+/)[0].toUpperCase()

// 條件型別：label、參數（key、label、預設）、文字模板
export const CONDITIONS = {
  price_below:    { label: '收盤低於某價',      params: [['x', '價格', 100]],                  text: w => `收盤 < ${w.x}` },
  price_above:    { label: '收盤高於某價',      params: [['x', '價格', 100]],                  text: w => `收盤 > ${w.x}` },
  cross_above_ma: { label: '向上穿過均線',      params: [['n', '幾日均線', 20]],               text: w => `收盤由下往上穿過 ${w.n} 日均線` },
  cross_below_ma: { label: '跌破均線',          params: [['n', '幾日均線', 20]],               text: w => `收盤由上往下跌破 ${w.n} 日均線` },
  above_ma:       { label: '在均線之上',        params: [['n', '幾日均線', 60]],               text: w => `收盤在 ${w.n} 日均線之上` },
  below_ma:       { label: '在均線之下',        params: [['n', '幾日均線', 60]],               text: w => `收盤在 ${w.n} 日均線之下` },
  rsi_below:      { label: 'RSI 低於',          params: [['n', 'RSI 天數', 14], ['x', '門檻', 30]], text: w => `RSI(${w.n}) < ${w.x}` },
  rsi_above:      { label: 'RSI 高於',          params: [['n', 'RSI 天數', 14], ['x', '門檻', 70]], text: w => `RSI(${w.n}) > ${w.x}` },
  change_below:   { label: 'N 日跌幅達到',      params: [['n', '幾日', 5], ['x', '報酬 %（負數）', -5]], text: w => `${w.n} 日報酬 ≤ ${w.x}%` },
  change_above:   { label: 'N 日漲幅達到',      params: [['n', '幾日', 5], ['x', '報酬 %', 5]],  text: w => `${w.n} 日報酬 ≥ ${w.x}%` },
  loss_from_cost: { label: '比成本低（停損）',  params: [['x', '%', 10]],                      text: w => `比平均成本低 ${w.x}%` },
  gain_from_cost: { label: '比成本高（停利）',  params: [['x', '%', 20]],                      text: w => `比平均成本高 ${w.x}%` },
  monthly_day:    { label: '每月固定日',        params: [['d', '每月幾號', 5]],                text: w => `每月 ${w.d} 日起第一個交易日` },
  on_date:        { label: '指定日期',          params: [['date', '日期', '2024-01-15']],      text: w => `${w.date} 當天` },
}
const UNITS_BUY = [['元', '元'], ['股', '股'], ['張', '張']]
const UNITS_SELL = [['全部', '全部'], ['股', '股'], ['張', '張']]

export function ruleText(r) {
  const c = CONDITIONS[r.when?.type]
  if (!c) return '（未設定）'
  const act = (r.then.side === 'buy' ? '買 ' : '賣 ') + (r.then.unit === '全部' ? '全部' : `${r.then.qty}${r.then.unit}`)
  return `${codeOf(r.stock_id)}：${c.text(r.when)} → ${act}`
}
function newRule(stock = '2330') { return { stock_id: stock, when: { type: 'cross_above_ma', n: 20 }, then: { side: 'buy', qty: 100000, unit: '元' }, max_times: 1, only_if_flat: true, cooldown: 0 } }
function withType(rule, type) {
  const when = { type }
  for (const [k, , dflt] of CONDITIONS[type].params) when[k] = dflt
  const monthly = type === 'monthly_day' || type === 'on_date'
  return { ...rule, when, max_times: type === 'monthly_day' ? null : 1, only_if_flat: rule.then.side === 'buy' && !monthly }
}

// 模板（stock 由表單帶入）
const TEMPLATES = [
  { key: 'ma', label: '均線進出', hint: '向上穿過 20 日均線買 10 萬，跌破就賣光', make: s => [
    { ...newRule(s), when: { type: 'cross_above_ma', n: 20 }, then: { side: 'buy', qty: 100000, unit: '元' }, max_times: null, only_if_flat: true },
    { ...newRule(s), when: { type: 'cross_below_ma', n: 20 }, then: { side: 'sell', unit: '全部' }, max_times: null, only_if_flat: false }] },
  { key: 'stop', label: '停損停利', hint: '起始日買 10 萬；比成本低 10% 賣光、高 20% 賣光', make: (s, start) => [
    { ...newRule(s), when: { type: 'on_date', date: start }, then: { side: 'buy', qty: 100000, unit: '元' }, max_times: 1, only_if_flat: false },
    { ...newRule(s), when: { type: 'loss_from_cost', x: 10 }, then: { side: 'sell', unit: '全部' }, max_times: null, only_if_flat: false },
    { ...newRule(s), when: { type: 'gain_from_cost', x: 20 }, then: { side: 'sell', unit: '全部' }, max_times: null, only_if_flat: false }] },
  { key: 'dip', label: '逢低加碼', hint: '每月 5 日買 1 萬；5 日跌 5% 以上再加 2 萬（最多 10 次）', make: s => [
    { ...newRule(s), when: { type: 'monthly_day', d: 5 }, then: { side: 'buy', qty: 10000, unit: '元' }, max_times: null, only_if_flat: false },
    { ...newRule(s), when: { type: 'change_below', n: 5, x: -5 }, then: { side: 'buy', qty: 20000, unit: '元' }, max_times: 10, only_if_flat: false, cooldown: 5 }] },
  { key: 'rsi', label: 'RSI 反轉', hint: 'RSI(14) < 30 買 5 萬，> 70 賣光', make: s => [
    { ...newRule(s), when: { type: 'rsi_below', n: 14, x: 30 }, then: { side: 'buy', qty: 50000, unit: '元' }, max_times: null, only_if_flat: true, cooldown: 5 },
    { ...newRule(s), when: { type: 'rsi_above', n: 14, x: 70 }, then: { side: 'sell', unit: '全部' }, max_times: null, only_if_flat: false, cooldown: 5 }] },
]

function RuleRow({ r, onChange, onRemove, stocks }) {
  const c = CONDITIONS[r.when.type]
  const units = r.then.side === 'buy' ? UNITS_BUY : UNITS_SELL
  const setWhen = (k, v) => onChange({ ...r, when: { ...r.when, [k]: k === 'date' ? v : Number(v) } })
  const setThen = (k, v) => onChange({ ...r, then: { ...r.then, [k]: k === 'qty' ? Number(v) : v } })
  return (
    <div style={{ display: 'flex', gap: '.45rem', flexWrap: 'wrap', alignItems: 'flex-end', padding: '.55rem .75rem', border: '1px solid var(--border-soft)', borderRadius: 8, marginBottom: '.45rem' }}>
      <div className="ctrl-group"><div className="ctrl-label">股票</div><input className="ctrl-select" list="sim-stocks" style={{ width: 120 }} value={r.stock_id} onChange={e => onChange({ ...r, stock_id: e.target.value })} /></div>
      <div className="ctrl-group"><div className="ctrl-label">當</div>
        <select className="ctrl-select" value={r.when.type} onChange={e => onChange(withType(r, e.target.value))}>{Object.entries(CONDITIONS).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}</select>
      </div>
      {c.params.map(([k, label]) => (
        <div className="ctrl-group" key={k}><div className="ctrl-label">{label}</div>
          <input className="ctrl-select" type={k === 'date' ? 'date' : 'number'} style={{ width: k === 'date' ? 140 : 84, textAlign: k === 'date' ? 'left' : 'right' }} value={r.when[k] ?? ''} onChange={e => setWhen(k, e.target.value)} />
        </div>
      ))}
      <div className="ctrl-group"><div className="ctrl-label">就</div>
        <div className="btn-group">
          <button className={`btn-period${r.then.side === 'buy' ? ' active' : ''}`} onClick={() => onChange({ ...r, then: { side: 'buy', qty: r.then.qty || 100000, unit: '元' }, only_if_flat: true })}>買</button>
          <button className={`btn-period${r.then.side === 'sell' ? ' active' : ''}`} onClick={() => onChange({ ...r, then: { side: 'sell', unit: '全部' }, only_if_flat: false })}>賣</button>
        </div>
      </div>
      {r.then.unit !== '全部' ? <div className="ctrl-group"><div className="ctrl-label">數量</div><input className="ctrl-select" type="number" style={{ width: 100, textAlign: 'right' }} value={r.then.qty ?? ''} onChange={e => setThen('qty', e.target.value)} /></div> : null}
      <div className="ctrl-group"><div className="ctrl-label">單位</div><select className="ctrl-select" value={r.then.unit} onChange={e => setThen('unit', e.target.value)}>{units.map(([u, l]) => <option key={u} value={u}>{l}</option>)}</select></div>
      <div className="ctrl-group"><div className="ctrl-label">最多次數</div><input className="ctrl-select" type="number" style={{ width: 70, textAlign: 'right' }} placeholder="不限" value={r.max_times ?? ''} onChange={e => onChange({ ...r, max_times: e.target.value === '' ? null : Number(e.target.value) })} /></div>
      {r.then.side === 'buy' ? <label style={{ fontSize: '.8rem', display: 'flex', alignItems: 'center', gap: '.3rem', paddingBottom: '.4rem' }}><input type="checkbox" checked={!!r.only_if_flat} onChange={e => onChange({ ...r, only_if_flat: e.target.checked })} />沒持股才買</label> : null}
      <div className="ctrl-group"><div className="ctrl-label">冷卻（日）</div><input className="ctrl-select" type="number" style={{ width: 64, textAlign: 'right' }} value={r.cooldown ?? 0} onChange={e => onChange({ ...r, cooldown: Number(e.target.value) })} /></div>
      <button className="btn-icon" title="刪除" onClick={onRemove}>✕</button>
      <div style={{ flexBasis: '100%', fontFamily: 'ui-monospace, Consolas, monospace', fontSize: '.78rem' }} className="muted">{ruleText(r)}</div>
    </div>
  )
}

function RulesChart({ series }) {
  if (!series?.length) return null
  const data = [{ name: '規則', data: series.map(p => [new Date(p.d).getTime(), p.nav]) }, { name: '0050 含息', data: series.map(p => [new Date(p.d).getTime(), p.bench]) }]
  const options = {
    chart: { type: 'line', toolbar: { show: false }, animations: { enabled: false }, background: 'transparent' },
    stroke: { width: [2.5, 1.5], curve: 'straight', dashArray: [0, 4] }, colors: [dark() ? '#5b9dff' : '#1d6ff2', '#9aa4b2'],
    xaxis: { type: 'datetime', labels: { datetimeUTC: false } }, yaxis: { labels: { formatter: v => v.toFixed(2) }, title: { text: '淨值（起點 1）' } },
    tooltip: { x: { format: 'yyyy-MM-dd' }, y: { formatter: v => v?.toFixed(3) } }, legend: { position: 'top' }, grid: { borderColor: 'rgba(128,128,128,0.18)' }, theme: { mode: dark() ? 'dark' : 'light' },
  }
  return <div className="chart-pad"><ReactApexChart type="line" series={data} options={options} height={300} /></div>
}

const RESULT_LABEL = { triggered: ['yellow', '觸發'], filled: ['green', '成交'], unfilled: ['yellow', '未成交'], rejected: ['red', '拒絕'], skipped: ['', '略過'] }

export default function RuleBuilder({ form, stocks, runRules }) {
  const [rules, setRules] = useState(() => readJSON(RULES_KEY, null) || TEMPLATES[0].make('2330', form.start))
  const [tplStock, setTplStock] = useState('2330')
  const [r, setR] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  useEffect(() => { writeLS(RULES_KEY, JSON.stringify(rules)) }, [rules])
  const update = (i, nr) => setRules(rules.map((x, j) => (j === i ? nr : x)))

  async function run() {
    if (!rules.length) { setError('先加一條規則。'); return }
    setBusy(true); setError('')
    const payload = { rules: rules.map(x => ({ ...x, stock_id: codeOf(x.stock_id) })), ...form }
    const { data, error } = await runRules(payload)
    setBusy(false)
    if (error) { setError(error); return }
    if (!data.available) { setError(`沒辦法模擬：${data.reason}${data.errors?.length ? `：${data.errors.join('；')}` : ''}`); setR(null); return }
    setR(data)
  }
  const m = r?.metrics
  return (
    <>
      <datalist id="sim-stocks">{(stocks || []).map(s => <option key={s.stock_id} value={`${s.stock_id} ${s.stock_name || ''}`.trim()} />)}</datalist>
      <div style={{ display: 'flex', gap: '.5rem', flexWrap: 'wrap', alignItems: 'flex-end', padding: '.6rem .9rem', border: '1px solid var(--border-soft)', borderRadius: 8, marginBottom: '.7rem' }}>
        <div className="ctrl-group"><div className="ctrl-label">模板</div>
          <div className="btn-group">{TEMPLATES.map(t => <button key={t.key} className="btn-period" title={t.hint} onClick={() => setRules(t.make(codeOf(tplStock), form.start))}>{t.label}</button>)}</div>
        </div>
        <div className="ctrl-group"><div className="ctrl-label">套在哪檔</div><input className="ctrl-select" list="sim-stocks" style={{ width: 130 }} value={tplStock} onChange={e => setTplStock(e.target.value)} /></div>
        <button className="btn-secondary" onClick={() => setRules([...rules, newRule(codeOf(tplStock))])}>＋ 加一條規則</button>
        <button className="btn-secondary" onClick={() => setRules([])}>清空</button>
        <button className="btn-primary" disabled={busy} onClick={run}>{busy ? '模擬中…' : '跑模擬'}</button>
        <Sub>條件每天收盤判斷、隔天開盤成交；每月固定日／指定日期當天開盤。「最多次數」空白 = 不限；「沒持股才買」避免每天加碼。</Sub>
      </div>
      {rules.length ? rules.map((x, i) => <RuleRow key={i} r={x} stocks={stocks} onChange={nr => update(i, nr)} onRemove={() => setRules(rules.filter((_, j) => j !== i))} />) : <Empty>還沒有規則。套個模板或加一條。</Empty>}
      {error ? <div className="down" style={{ fontSize: '.86rem', marginTop: '.4rem' }}>{error}</div> : null}

      {r ? (
        <div style={{ marginTop: '1rem' }}>
          {r.missing?.length ? <div className="note-box" style={{ color: 'var(--orange)' }}>沒有行情的代號（規則不會觸發）：{r.missing.join('、')}</div> : null}
          <div className="stat-grid">
            <div className="stat-tile"><div className="k">總報酬</div><div className="v"><span className={m.total_return > 0 ? 'up' : m.total_return < 0 ? 'down' : ''}>{spct(m.total_return)}</span></div><div className="s">{r.start} ～ {r.end} · 資金 {money(r.capital)} → 期末 {money(r.final.value)}</div></div>
            <div className="stat-tile"><div className="k">0050 含息</div><div className="v">{spct(m.bench_return)}</div><div className="s">主動報酬 <span className={m.active_return > 0 ? 'up' : 'down'}>{spct(m.active_return)}</span> · 年化 {spct(m.ann_active)}</div></div>
            <div className="stat-tile"><div className="k">已實現損益</div><div className="v"><span className={r.realized_pnl > 0 ? 'up' : r.realized_pnl < 0 ? 'down' : ''}>{money(r.realized_pnl)}</span></div><div className="s">費用合計 {money(r.costs)} · 成交 {r.trades.length} 筆</div></div>
            <div className="stat-tile"><div className="k">最大回撤</div><div className="v">{pct(m.mdd_port)}</div><div className="s">0050 {pct(m.mdd_bench)} · 相對最大落後 {pct(m.rel_mdd)}</div></div>
            <div className="stat-tile"><div className="k">規則觸發</div><div className="v">{r.rules.reduce((s, x) => s + x.fired, 0)} 次</div><div className="s">{r.rules.map(x => `#${x.i + 1} ${x.fired}${x.max_times != null ? `/${x.max_times}` : ''}`).join(' · ')}</div></div>
          </div>
          <RulesChart series={r.series} />
          <div className="two-col" style={{ gap: '1.1rem' }}>
            <div className="card">
              <div className="card-header"><div className="card-title">觸發紀錄</div><Sub>最近 {r.triggers.length} 筆 · 觸發日 → 成交日</Sub></div>
              {r.triggers.length ? (
                <div style={{ maxHeight: 380, overflowY: 'auto' }}>
                  <table className="data-table" style={{ fontSize: '.84rem' }}>
                    <thead><tr><th>日期</th><th>規則</th><th className="mid">結果</th><th>說明</th></tr></thead>
                    <tbody>{[...r.triggers].reverse().map((t, i) => { const [cls, label] = RESULT_LABEL[t.result] || ['', t.result]; return (
                      <tr key={i}><td>{t.date}{t.signal_date !== t.date ? <Sub>觸發 {t.signal_date}</Sub> : null}</td><td style={{ whiteSpace: 'normal' }}>#{t.rule + 1} {t.text}</td><td className="mid"><span className={`tag ${cls}`}>{label}</span></td><td style={{ whiteSpace: 'normal' }}>{t.note || ''}</td></tr>) })}</tbody>
                  </table>
                </div>
              ) : <Empty>沒有任何規則觸發。</Empty>}
            </div>
            <div>
              <div className="card" style={{ marginBottom: '1.1rem' }}>
                <div className="card-header"><div className="card-title">成交</div></div>
                {r.trades.length ? (
                  <div style={{ maxHeight: 220, overflowY: 'auto' }}>
                    <table className="data-table" style={{ fontSize: '.84rem' }}>
                      <thead><tr><th>成交日</th><th>動作</th><th>股票</th><th className="num">股數</th><th className="num">價格</th><th className="num">損益</th></tr></thead>
                      <tbody>{r.trades.map((t, i) => <tr key={i}><td>{t.date}</td><td><strong className={t.side === 'buy' ? 'up' : 'down'}>{t.side === 'buy' ? '買' : '賣'}</strong><Sub>#{t.rule + 1}</Sub></td><td><strong>{t.stock_id}</strong></td><td className="num">{t.shares.toLocaleString()}</td><td className="num">{t.price}</td><td className="num">{t.pnl == null ? '–' : <span className={t.pnl > 0 ? 'up' : t.pnl < 0 ? 'down' : 'muted'}>{money(t.pnl)}</span>}</td></tr>)}</tbody>
                    </table>
                  </div>
                ) : <Empty>沒有成交。</Empty>}
              </div>
              <div className="card">
                <div className="card-header"><div className="card-title">期末持股</div><Sub>以 {r.end} 收盤估值 · 現金 {money(r.final.cash)}</Sub></div>
                {r.final.holdings.length ? (
                  <table className="data-table" style={{ fontSize: '.84rem' }}>
                    <thead><tr><th>股票</th><th className="num">股數</th><th className="num">均價</th><th className="num">期末價</th><th className="num">市值</th></tr></thead>
                    <tbody>{r.final.holdings.map(h => <tr key={h.stock_id}><td><strong>{h.stock_id}</strong></td><td className="num">{h.shares.toLocaleString()}</td><td className="num">{h.avg_cost ?? '–'}</td><td className="num">{h.last ?? '–'}</td><td className="num">{money(h.value)}</td></tr>)}</tbody>
                  </table>
                ) : <Empty>期末全現金。</Empty>}
              </div>
            </div>
          </div>
          <div className="note-box">{r.caveat}</div>
        </div>
      ) : null}
    </>
  )
}
