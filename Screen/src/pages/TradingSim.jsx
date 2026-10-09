// 交易模擬（Iteration 60）——給所有人（不用登入）
// ───────────────────────────────────────────────────────────────────────────
// 兩種模擬，都只讀資料庫、不動任何帳戶：
//   歷史回放：候選策略的月清單套上引擎規則（限價、重掛、停損、守門），和「照單全收」對照（Iteration 59 的面板）
//   自訂指令：你自己寫「哪天買賣哪檔多少」，設期間與資金，用實際日線跑完，給收益對 0050
// 統一前端（erucmoney.com）放在「預測」群組，匿名可用；儀表板這邊登入後也看得到。
import { useState } from 'react'
import ReactApexChart from 'react-apexcharts'
import { getSimReplay, runSim } from '../services/api'
import ReplayPanel from '../components/ReplayPanel'

const TAB_KEY = 'sim_tab'
const TEXT_KEY = 'sim_text'
const FORM_KEY = 'sim_form'
const EXAMPLE = `# 一行一筆：日期 買/賣 代號 數量（10股、2張、50000元、全部）
2024-01-15 買 2330 10股
2024-01-15 買 0050 100000元
2024-04-01 買 2454 1張
2024-06-03 賣 2330 全部
2024-09-02 賣 2454 500股`
const DEFAULT_FORM = { start: '2024-01-02', end: '2024-09-30', capital: 1000000 }

const money = v => (v == null ? '–' : Number(v).toLocaleString('zh-TW', { maximumFractionDigits: 0 }))
const pct = (v, d = 1) => (v == null ? '–' : `${(Number(v) * 100).toFixed(d)}%`)
const spct = (v, d = 2) => (v == null ? '–' : `${Number(v) > 0 ? '+' : ''}${(Number(v) * 100).toFixed(d)}%`)
function Sub({ children }) { return <div className="muted" style={{ fontSize: '0.74rem' }}>{children}</div> }
function Empty({ children }) { return <div className="muted" style={{ padding: '1rem 1.25rem', fontSize: '.88rem' }}>{children}</div> }
function readLS(k, fallback) { try { const v = localStorage.getItem(k); return v == null ? fallback : v } catch { return fallback } }
function writeLS(k, v) { try { localStorage.setItem(k, String(v)) } catch { /* 隱私模式 */ } }
const dark = () => document.documentElement.dataset.theme === 'dark'

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

function InstructionsTab() {
  const [text, setText] = useState(() => readLS(TEXT_KEY, EXAMPLE))
  const [form, setForm] = useState(() => { try { return { ...DEFAULT_FORM, ...(JSON.parse(readLS(FORM_KEY, 'null')) || {}) } } catch { return DEFAULT_FORM } })
  const [r, setR] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function run() {
    setBusy(true); setError('')
    writeLS(TEXT_KEY, text); writeLS(FORM_KEY, JSON.stringify(form))
    const { data, error } = await runSim({ text, ...form })
    setBusy(false)
    if (error) { setError(error); return }
    if (!data.available) { setError(`沒辦法模擬：${data.reason}${data.errors?.length ? `；看不懂的行：${data.errors.map(e => `第 ${e.line} 行（${e.reason}）`).join('、')}` : ''}`); setR(null); return }
    setR(data)
  }
  const m = r?.metrics
  return (
    <>
      <div className="two-col" style={{ padding: '1rem 1.25rem', gap: '1.1rem', alignItems: 'start' }}>
        <div>
          <div className="ctrl-label" style={{ marginBottom: '.35rem' }}>交易指令（一行一筆；# 開頭是註解）</div>
          <textarea className="form-textarea" rows={9} value={text} onChange={e => setText(e.target.value)} spellCheck={false}
                    style={{ width: '100%', fontFamily: 'ui-monospace, Consolas, monospace', fontSize: '.86rem', lineHeight: 1.6 }} />
          <Sub>數量可以是 10股、2張（= 2000 股）、50000元（執行那天開盤換算）、全部（賣出）。日期不是交易日就順延到下一個有行情的日子。</Sub>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '.6rem' }}>
          <div style={{ display: 'flex', gap: '.5rem', flexWrap: 'wrap', alignItems: 'flex-end' }}>
            <div className="ctrl-group"><div className="ctrl-label">起</div><input type="date" className="ctrl-select" value={form.start} onChange={e => setForm({ ...form, start: e.target.value })} /></div>
            <div className="ctrl-group"><div className="ctrl-label">迄</div><input type="date" className="ctrl-select" value={form.end} onChange={e => setForm({ ...form, end: e.target.value })} /></div>
            <div className="ctrl-group"><div className="ctrl-label">資金（NT$）</div><input type="number" className="ctrl-select" style={{ width: 130, textAlign: 'right' }} step={100000} value={form.capital} onChange={e => setForm({ ...form, capital: Number(e.target.value) })} /></div>
          </div>
          <div style={{ display: 'flex', gap: '.5rem', flexWrap: 'wrap' }}>
            <button className="btn-primary" disabled={busy} onClick={run}>{busy ? '模擬中…' : '跑模擬'}</button>
            <button className="btn-secondary" onClick={() => setText(EXAMPLE)}>放範例</button>
            <button className="btn-secondary" onClick={() => setText('')}>清空</button>
          </div>
          <Sub>只讀、不登入、不動任何帳戶。資料從 2018-01 起；價格是還原價（含息），手續費 0.0855%、賣出稅 0.3%、無滑價。</Sub>
          {error ? <div className="down" style={{ fontSize: '.86rem' }}>{error}</div> : null}
        </div>
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
