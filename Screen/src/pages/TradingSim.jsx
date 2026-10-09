// 交易模擬（Iteration 60）——給所有人（不用登入）
// ───────────────────────────────────────────────────────────────────────────
// 兩種模擬，都只讀資料庫、不動任何帳戶：
//   自訂指令：你自己寫「哪天買賣哪檔多少」，設期間與資金，用實際日線跑完，給收益對 0050
//     簡易模式（Iteration 61）：用表單一筆一筆加、或套模板（買進持有／定期定額／進出一次），文字自動產生；進階模式直接寫文字
//   歷史回放：候選策略的月清單套上引擎規則（限價、重掛、停損、守門），和「照單全收」對照（Iteration 59 的面板）
// 統一前端（erucmoney.com）放在「預測」群組，匿名可用；儀表板這邊登入後也看得到。
import { useEffect, useMemo, useState } from 'react'
import ReactApexChart from 'react-apexcharts'
import { getSimReplay, runSim, getTrackedStocks } from '../services/api'
import ReplayPanel from '../components/ReplayPanel'

const TAB_KEY = 'sim_tab'
const TEXT_KEY = 'sim_text'
const FORM_KEY = 'sim_form'
const ROWS_KEY = 'sim_rows'
const MODE_KEY = 'sim_mode'
const EXAMPLE = `# 一行一筆：日期 買/賣 代號 數量（10股、2張、50000元、全部）
2024-01-15 買 2330 10股
2024-01-15 買 0050 100000元
2024-04-01 買 2454 1張
2024-06-03 賣 2330 全部
2024-09-02 賣 2454 500股`
const DEFAULT_FORM = { start: '2024-01-02', end: '2024-09-30', capital: 1000000 }
const UNITS = [['股', '股'], ['張', '張（1000 股）'], ['元', '元（金額）'], ['全部', '全部（賣出）']]

const money = v => (v == null ? '–' : Number(v).toLocaleString('zh-TW', { maximumFractionDigits: 0 }))
const pct = (v, d = 1) => (v == null ? '–' : `${(Number(v) * 100).toFixed(d)}%`)
const spct = (v, d = 2) => (v == null ? '–' : `${Number(v) > 0 ? '+' : ''}${(Number(v) * 100).toFixed(d)}%`)
function Sub({ children }) { return <div className="muted" style={{ fontSize: '0.74rem' }}>{children}</div> }
function Empty({ children }) { return <div className="muted" style={{ padding: '1rem 1.25rem', fontSize: '.88rem' }}>{children}</div> }
function readLS(k, fallback) { try { const v = localStorage.getItem(k); return v == null ? fallback : v } catch { return fallback } }
function writeLS(k, v) { try { localStorage.setItem(k, String(v)) } catch { /* 隱私模式 */ } }
function readJSON(k, fallback) { try { const v = JSON.parse(readLS(k, 'null')); return v ?? fallback } catch { return fallback } }
const dark = () => document.documentElement.dataset.theme === 'dark'
const iso = d => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
const codeOf = s => String(s || '').trim().split(/\s+/)[0].toUpperCase()

// 一筆 row → 一行指令文字；rows → 整段文字
function rowToLine(r) {
  const side = r.side === 'buy' ? '買' : '賣'
  const qty = r.unit === '全部' ? '全部' : `${r.qty}${r.unit}`
  return `${r.date} ${side} ${codeOf(r.stock)} ${qty}`
}
function rowsToText(rows) { return rows.filter(r => r.date && codeOf(r.stock) && (r.unit === '全部' || Number(r.qty) > 0)).map(rowToLine).join('\n') }
function rowOk(r) { return r.date && codeOf(r.stock).length >= 4 && (r.unit === '全部' || Number(r.qty) > 0) }

// ── 模板：產生 rows ──
function tplBuyHold({ stock, amount, start }) { return [{ date: start, side: 'buy', stock, qty: amount, unit: '元' }] }
function tplRoundTrip({ stock, amount, start, end }) { return [{ date: start, side: 'buy', stock, qty: amount, unit: '元' }, { date: end, side: 'sell', stock, qty: '', unit: '全部' }] }
function tplDca({ stock, amount, day, start, end }) {
  const rows = []
  const s = new Date(start + 'T00:00:00'), e = new Date(end + 'T00:00:00')
  const d = new Date(s.getFullYear(), s.getMonth(), Math.min(Number(day) || 1, 28))
  if (d < s) d.setMonth(d.getMonth() + 1)
  while (d <= e && rows.length < 120) { rows.push({ date: iso(d), side: 'buy', stock, qty: amount, unit: '元' }); d.setMonth(d.getMonth() + 1) }
  return rows
}
const TEMPLATES = [
  { key: 'buyhold', label: '買進持有', hint: '起始日用一筆金額買進，抱到期末', fields: ['stock', 'amount'], make: tplBuyHold },
  { key: 'dca', label: '定期定額', hint: '每月固定日期買固定金額，抱到期末', fields: ['stock', 'amount', 'day'], make: tplDca },
  { key: 'roundtrip', label: '進出一次', hint: '起始日買進、結束日全部賣出', fields: ['stock', 'amount'], make: tplRoundTrip },
]

function SimChart({ series }) {
  if (!series?.length) return null
  const data = [
    { name: '你的指令', data: series.map(p => [new Date(p.d).getTime(), p.nav]) },
    { name: '0050 含息', data: series.map(p => [new Date(p.d).getTime(), p.bench]) },
  ]
  const options = {
    chart: { type: 'line', toolbar: { show: false }, animations: { enabled: false }, background: 'transparent' },
    stroke: { width: [2.5, 1.5], curve: 'straight', dashArray: [0, 4] },
    colors: [dark() ? '#5b9dff' : '#1d6ff2', '#9aa4b2'],
    xaxis: { type: 'datetime', labels: { datetimeUTC: false } },
    yaxis: { labels: { formatter: v => v.toFixed(2) }, title: { text: '淨值（起點 1）' } },
    tooltip: { x: { format: 'yyyy-MM-dd' }, y: { formatter: v => v?.toFixed(3) } },
    legend: { position: 'top' },
    grid: { borderColor: 'rgba(128,128,128,0.18)' },
    theme: { mode: dark() ? 'dark' : 'light' },
  }
  return <div className="chart-pad"><ReactApexChart type="line" series={data} options={options} height={300} /></div>
}

// ── 簡易模式：表單加一筆、模板、列表 ──
function SimpleBuilder({ rows, setRows, form, stocks }) {
  const [draft, setDraft] = useState({ date: form.start, side: 'buy', stock: '2330', qty: 10, unit: '股' })
  const [tpl, setTpl] = useState('buyhold')
  const [tplForm, setTplForm] = useState({ stock: '0050', amount: 100000, day: 5 })
  useEffect(() => { setDraft(d => ({ ...d, date: d.date || form.start })) }, [form.start])
  const T = TEMPLATES.find(t => t.key === tpl)

  function add() {
    if (!rowOk(draft)) return
    setRows([...rows, { ...draft, stock: codeOf(draft.stock) }].sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0)))
  }
  function applyTemplate(replace) {
    const made = T.make({ ...tplForm, stock: codeOf(tplForm.stock), start: form.start, end: form.end })
    const next = replace ? made : [...rows, ...made]
    setRows(next.sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0)))
  }
  const list = <datalist id="sim-stocks">{(stocks || []).map(s => <option key={s.stock_id} value={`${s.stock_id} ${s.stock_name || ''}`.trim()} />)}</datalist>

  return (
    <div>
      {list}
      {/* 模板 */}
      <div style={{ display: 'flex', gap: '.5rem', flexWrap: 'wrap', alignItems: 'flex-end', padding: '.6rem .9rem', border: '1px solid var(--border-soft)', borderRadius: 8, marginBottom: '.7rem' }}>
        <div className="ctrl-group"><div className="ctrl-label">模板</div>
          <div className="btn-group">{TEMPLATES.map(t => <button key={t.key} className={`btn-period${tpl === t.key ? ' active' : ''}`} onClick={() => setTpl(t.key)} title={t.hint}>{t.label}</button>)}</div>
        </div>
        <div className="ctrl-group"><div className="ctrl-label">股票</div><input className="ctrl-select" list="sim-stocks" style={{ width: 150 }} value={tplForm.stock} onChange={e => setTplForm({ ...tplForm, stock: e.target.value })} placeholder="0050" /></div>
        <div className="ctrl-group"><div className="ctrl-label">{tpl === 'dca' ? '每月金額（元）' : '金額（元）'}</div><input type="number" className="ctrl-select" style={{ width: 120, textAlign: 'right' }} step={10000} value={tplForm.amount} onChange={e => setTplForm({ ...tplForm, amount: Number(e.target.value) })} /></div>
        {tpl === 'dca' ? <div className="ctrl-group"><div className="ctrl-label">每月幾號</div><input type="number" className="ctrl-select" style={{ width: 70, textAlign: 'right' }} min={1} max={28} value={tplForm.day} onChange={e => setTplForm({ ...tplForm, day: Number(e.target.value) })} /></div> : null}
        <button className="btn-secondary" onClick={() => applyTemplate(true)}>套用（取代）</button>
        <button className="btn-secondary" onClick={() => applyTemplate(false)}>加到清單</button>
        <Sub>{T.hint}；期間用上方的起迄。</Sub>
      </div>

      {/* 加一筆 */}
      <div style={{ display: 'flex', gap: '.5rem', flexWrap: 'wrap', alignItems: 'flex-end', marginBottom: '.6rem' }}>
        <div className="ctrl-group"><div className="ctrl-label">日期</div><input type="date" className="ctrl-select" value={draft.date} onChange={e => setDraft({ ...draft, date: e.target.value })} /></div>
        <div className="ctrl-group"><div className="ctrl-label">動作</div>
          <div className="btn-group"><button className={`btn-period${draft.side === 'buy' ? ' active' : ''}`} onClick={() => setDraft({ ...draft, side: 'buy' })}>買</button><button className={`btn-period${draft.side === 'sell' ? ' active' : ''}`} onClick={() => setDraft({ ...draft, side: 'sell', unit: draft.unit === '元' ? '全部' : draft.unit })}>賣</button></div>
        </div>
        <div className="ctrl-group"><div className="ctrl-label">股票</div><input className="ctrl-select" list="sim-stocks" style={{ width: 150 }} value={draft.stock} onChange={e => setDraft({ ...draft, stock: e.target.value })} placeholder="2330" /></div>
        <div className="ctrl-group"><div className="ctrl-label">數量</div><input type="number" className="ctrl-select" style={{ width: 100, textAlign: 'right' }} min={0} value={draft.unit === '全部' ? '' : draft.qty} disabled={draft.unit === '全部'} onChange={e => setDraft({ ...draft, qty: Number(e.target.value) })} /></div>
        <div className="ctrl-group"><div className="ctrl-label">單位</div>
          <select className="ctrl-select" value={draft.unit} onChange={e => setDraft({ ...draft, unit: e.target.value })}>
            {UNITS.filter(([u]) => draft.side === 'sell' ? u !== '元' : u !== '全部').map(([u, l]) => <option key={u} value={u}>{l}</option>)}
          </select>
        </div>
        <button className="btn-primary" onClick={add} disabled={!rowOk(draft)}>加一筆</button>
      </div>

      {/* 清單 */}
      {rows.length ? (
        <table className="data-table" style={{ fontSize: '.86rem' }}>
          <thead><tr><th>日期</th><th>動作</th><th>股票</th><th className="num">數量</th><th>指令</th><th /></tr></thead>
          <tbody>{rows.map((r, i) => (
            <tr key={i}><td>{r.date}</td><td><span className={r.side === 'buy' ? 'up' : 'down'}>{r.side === 'buy' ? '買' : '賣'}</span></td><td><strong>{codeOf(r.stock)}</strong></td>
              <td className="num">{r.unit === '全部' ? '全部' : `${Number(r.qty).toLocaleString()} ${r.unit}`}</td>
              <td className="muted" style={{ fontFamily: 'ui-monospace, Consolas, monospace', fontSize: '.78rem' }}>{rowToLine(r)}</td>
              <td><button className="btn-icon" title="刪除" onClick={() => setRows(rows.filter((_, j) => j !== i))}>✕</button></td></tr>
          ))}</tbody>
        </table>
      ) : <Empty>還沒有指令。用上面的模板一鍵產生，或一筆一筆加。</Empty>}
    </div>
  )
}

function InstructionsTab() {
  const [mode, setMode] = useState(() => readLS(MODE_KEY, 'simple'))
  const [rows, setRows] = useState(() => readJSON(ROWS_KEY, []))
  const [text, setText] = useState(() => readLS(TEXT_KEY, EXAMPLE))
  const [form, setForm] = useState(() => ({ ...DEFAULT_FORM, ...readJSON(FORM_KEY, {}) }))
  const [stocks, setStocks] = useState([])
  const [r, setR] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  useEffect(() => { getTrackedStocks().then(({ data }) => setStocks(Array.isArray(data) ? data : (data?.items ?? []))) }, [])
  useEffect(() => { writeLS(ROWS_KEY, JSON.stringify(rows)) }, [rows])
  const effectiveText = useMemo(() => (mode === 'simple' ? rowsToText(rows) : text), [mode, rows, text])

  async function run() {
    if (!effectiveText.trim()) { setError('先加幾筆指令。'); return }
    setBusy(true); setError('')
    writeLS(TEXT_KEY, mode === 'simple' ? text : text); writeLS(FORM_KEY, JSON.stringify(form)); writeLS(MODE_KEY, mode)
    const { data, error } = await runSim({ text: effectiveText, ...form })
    setBusy(false)
    if (error) { setError(error); return }
    if (!data.available) { setError(`沒辦法模擬：${data.reason}${data.errors?.length ? `；看不懂的行：${data.errors.map(e => `第 ${e.line} 行（${e.reason}）`).join('、')}` : ''}`); setR(null); return }
    setR(data)
  }
  function switchMode(m) {
    if (m === 'text' && mode === 'simple' && rows.length) setText(rowsToText(rows))   // 簡易 → 進階：把產生的文字帶過去
    setMode(m); writeLS(MODE_KEY, m)
  }
  const m = r?.metrics
  return (
    <>
      <div style={{ padding: '1rem 1.25rem .4rem', display: 'flex', gap: '.5rem', flexWrap: 'wrap', alignItems: 'flex-end' }}>
        <div className="btn-group"><button className={`btn-period${mode === 'simple' ? ' active' : ''}`} onClick={() => switchMode('simple')}>簡易（表單／模板）</button><button className={`btn-period${mode === 'text' ? ' active' : ''}`} onClick={() => switchMode('text')}>進階（文字）</button></div>
        <div className="ctrl-group"><div className="ctrl-label">起</div><input type="date" className="ctrl-select" value={form.start} onChange={e => setForm({ ...form, start: e.target.value })} /></div>
        <div className="ctrl-group"><div className="ctrl-label">迄</div><input type="date" className="ctrl-select" value={form.end} onChange={e => setForm({ ...form, end: e.target.value })} /></div>
        <div className="ctrl-group"><div className="ctrl-label">資金（NT$）</div><input type="number" className="ctrl-select" style={{ width: 130, textAlign: 'right' }} step={100000} value={form.capital} onChange={e => setForm({ ...form, capital: Number(e.target.value) })} /></div>
        <button className="btn-primary" disabled={busy} onClick={run}>{busy ? '模擬中…' : '跑模擬'}</button>
        {mode === 'text' ? <><button className="btn-secondary" onClick={() => setText(EXAMPLE)}>放範例</button><button className="btn-secondary" onClick={() => setText('')}>清空</button></> : <button className="btn-secondary" onClick={() => setRows([])}>清空清單</button>}
      </div>
      <div style={{ padding: '.4rem 1.25rem 1rem' }}>
        {mode === 'simple' ? <SimpleBuilder rows={rows} setRows={setRows} form={form} stocks={stocks} /> : (
          <>
            <textarea className="form-textarea" rows={9} value={text} onChange={e => setText(e.target.value)} spellCheck={false}
                      style={{ width: '100%', fontFamily: 'ui-monospace, Consolas, monospace', fontSize: '.86rem', lineHeight: 1.6 }} />
            <Sub>一行一筆：日期 買/賣 代號 數量。數量可以是 10股、2張（= 2000 股）、50000元（執行那天開盤換算）、全部（賣出）；# 之後是註解。</Sub>
          </>
        )}
        <Sub>只讀、不登入、不動任何帳戶。資料從 2018-01 起；價格是還原價（含息），手續費 0.0855%、賣出稅 0.3%、無滑價。日期不是交易日就順延到下一個有行情的日子。</Sub>
        {error ? <div className="down" style={{ fontSize: '.86rem', marginTop: '.4rem' }}>{error}</div> : null}
      </div>

      {r ? (
        <>
          {r.errors?.length ? <div className="note-box" style={{ color: 'var(--orange)' }}>看不懂、已略過的行：{r.errors.map(e => `第 ${e.line} 行「${e.text.trim()}」（${e.reason}）`).join('；')}</div> : null}
          <div className="stat-grid">
            <div className="stat-tile"><div className="k">總報酬</div><div className="v"><span className={m.total_return > 0 ? 'up' : m.total_return < 0 ? 'down' : ''}>{spct(m.total_return)}</span></div><div className="s">{r.start} ～ {r.end} · 資金 {money(r.capital)} → 期末 {money(r.final.value)}</div></div>
            <div className="stat-tile"><div className="k">0050 含息</div><div className="v">{spct(m.bench_return)}</div><div className="s">主動報酬 <span className={m.active_return > 0 ? 'up' : 'down'}>{spct(m.active_return)}</span> · 年化 {spct(m.ann_active)}</div></div>
            <div className="stat-tile"><div className="k">已實現損益</div><div className="v"><span className={r.realized_pnl > 0 ? 'up' : r.realized_pnl < 0 ? 'down' : ''}>{money(r.realized_pnl)}</span></div><div className="s">費用合計 {money(r.costs)}</div></div>
            <div className="stat-tile"><div className="k">最大回撤</div><div className="v">{pct(m.mdd_port)}</div><div className="s">0050 {pct(m.mdd_bench)} · 相對最大落後 {pct(m.rel_mdd)}</div></div>
            <div className="stat-tile"><div className="k">指令</div><div className="v">{r.n_instructions}</div><div className="s">成交 {r.trades.length} · 略過 {r.skipped.length} · {r.n_days} 個交易日</div></div>
          </div>
          <SimChart series={r.series} />
          <div className="two-col" style={{ padding: '0 1.25rem 1rem', gap: '1.1rem' }}>
            <div className="card">
              <div className="card-header"><div className="card-title">成交</div><Sub>指令日 → 實際成交日</Sub></div>
              {r.trades.length ? (
                <div style={{ maxHeight: 360, overflowY: 'auto' }}>
                  <table className="data-table">
                    <thead><tr><th>行</th><th>指令日</th><th>成交日</th><th>動作</th><th>股票</th><th className="num">股數</th><th className="num">價格</th><th className="num">金額</th><th className="num">費用</th><th className="num">損益</th></tr></thead>
                    <tbody>{r.trades.map((t, i) => (
                      <tr key={i}><td className="muted">{t.line}</td><td>{t.asked}</td><td>{t.date}{t.date !== t.asked ? <Sub>順延</Sub> : null}</td>
                        <td><strong className={t.side === 'buy' ? 'up' : 'down'}>{t.side === 'buy' ? '買' : '賣'}</strong>{t.note ? <Sub>{t.note}</Sub> : null}</td>
                        <td><strong>{t.stock_id}</strong></td><td className="num">{t.shares.toLocaleString()}</td><td className="num">{t.price}</td><td className="num">{money(t.gross)}</td><td className="num">{money(t.fee + t.tax)}</td>
                        <td className="num">{t.pnl == null ? '–' : <span className={t.pnl > 0 ? 'up' : t.pnl < 0 ? 'down' : 'muted'}>{money(t.pnl)}</span>}</td></tr>
                    ))}</tbody>
                  </table>
                </div>
              ) : <Empty>沒有任何成交。</Empty>}
            </div>
            <div>
              <div className="card" style={{ marginBottom: '1.1rem' }}>
                <div className="card-header"><div className="card-title">期末持股</div><Sub>以 {r.end} 收盤估值 · 現金 {money(r.final.cash)}</Sub></div>
                {r.final.holdings.length ? (
                  <table className="data-table">
                    <thead><tr><th>股票</th><th className="num">股數</th><th className="num">均價</th><th className="num">期末價</th><th className="num">市值</th></tr></thead>
                    <tbody>{r.final.holdings.map(h => <tr key={h.stock_id}><td><strong>{h.stock_id}</strong></td><td className="num">{h.shares.toLocaleString()}</td><td className="num">{h.avg_cost ?? '–'}</td><td className="num">{h.last ?? '–'}</td><td className="num">{money(h.value)}</td></tr>)}</tbody>
                  </table>
                ) : <Empty>期末全現金。</Empty>}
              </div>
              <div className="card">
                <div className="card-header"><div className="card-title">略過的指令</div></div>
                {r.skipped.length ? (
                  <table className="data-table">
                    <thead><tr><th>行</th><th>日期</th><th>股票</th><th>原因</th></tr></thead>
                    <tbody>{r.skipped.map((s, i) => <tr key={i}><td className="muted">{s.line}</td><td>{s.date}</td><td><strong>{s.stock_id}</strong></td><td style={{ whiteSpace: 'normal' }}>{s.reason}</td></tr>)}</tbody>
                  </table>
                ) : <Empty>全部執行了。</Empty>}
              </div>
            </div>
          </div>
          <div className="note-box">{r.caveat}</div>
        </>
      ) : null}
    </>
  )
}

const TABS = [['instructions', '自訂指令'], ['replay', '歷史回放']]

export default function TradingSim() {
  const [tab, setTab] = useState(() => readLS(TAB_KEY, 'instructions'))
  function pick(k) { setTab(k); writeLS(TAB_KEY, k) }
  return (
    <div className="card">
      <div className="card-header">
        <div>
          <div className="card-title">交易模擬</div>
          <Sub>不用登入。自訂指令：你說怎麼買賣，用實際日線跑完給收益；歷史回放：候選策略加上引擎規則在過去六年會怎樣。</Sub>
        </div>
        <div className="btn-group">{TABS.map(([k, l]) => <button key={k} className={`btn-period${tab === k ? ' active' : ''}`} onClick={() => pick(k)}>{l}</button>)}</div>
      </div>
      {tab === 'instructions' ? <InstructionsTab /> : <ReplayPanel rules={null} fetchReplay={getSimReplay} />}
    </div>
  )
}
