// 程式交易（Iteration 57）
// ───────────────────────────────────────────────────────────────────────────
// 把候選策略的月清單（目標權重）和你的實際持股、可投入現金，變成一張可以拿去券商 App 下的指令表；
// 執行完勾選「已執行」登記進交易台帳（note 以 [程式交易] 開頭），下次再算就會對帳出還差多少。
//
// 沒有券商 API：這一頁「算」，人「做」。零股用限價單（盤中或盤後），參考價是最新收盤，成交價自己填回來。
// 策略範圍只包含清單裡的股票和以前用這一頁登記過的股票；你自己買的其他持股一律不動（另列出來）。
import { useCallback, useEffect, useMemo, useState } from 'react'
import { getTradingPlan, getTradingLog, addTrade, getPortfolioPaper } from '../services/api'
import { formatShares } from '../components/Shares'

const CASH_KEY = 'algo_cash'
const MIN_KEY = 'algo_min_trade'
const QUICK = [100000, 300000, 500000, 1000000]

const money = v => (v == null ? '–' : Number(v).toLocaleString('zh-TW', { maximumFractionDigits: 0 }))
const pct = (v, d = 1) => (v == null ? '–' : `${(Number(v) * 100).toFixed(d)}%`)
const today = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}` }
function Sub({ children }) { return <div className="muted" style={{ fontSize: '0.74rem' }}>{children}</div> }
function readLS(k, fallback) { try { const v = localStorage.getItem(k); return v == null ? fallback : v } catch { return fallback } }
function writeLS(k, v) { try { localStorage.setItem(k, String(v)) } catch { /* 隱私模式 */ } }

const REASON = { new: ['新進場', 'green'], exit: ['退出清單', 'red'], rebalance: ['調整權重', 'blue'] }

// ── 指令表：勾選 → 登記 ────────────────────────────────────────────────────
function OrdersTable({ plan, onRegistered }) {
  const [checked, setChecked] = useState({})
  const [fills, setFills] = useState({})        // stock_id → 實際成交價（可改）
  const [date, setDate] = useState(today())
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')

  useEffect(() => { setChecked({}); setFills({}) }, [plan?.list?.rebalance_date, plan?.summary?.cash])

  const orders = plan.orders
  const picked = orders.filter(o => checked[o.stock_id])
  const allOn = orders.length > 0 && picked.length === orders.length

  async function register() {
    if (!picked.length) return
    setBusy(true); setMsg('')
    let ok = 0; const errs = []
    for (const o of picked) {
      const price = Number(fills[o.stock_id] ?? o.price)
      const { error } = await addTrade({ stock_id: o.stock_id, trade_date: date, side: o.side, shares: o.shares, price, note: plan.note })
      if (error) errs.push(`${o.stock_id}：${error}`); else ok++
    }
    setBusy(false)
    setMsg(errs.length ? `登記 ${ok} 筆，失敗 ${errs.length} 筆：${errs.join('；')}` : `已登記 ${ok} 筆進交易台帳（${plan.note}）`)
    setChecked({})
    onRegistered()
  }

  function copyText() {
    const lines = orders.map(o => `${o.side === 'Buy' ? '買' : '賣'} ${o.stock_id} ${o.stock_name || ''} ${o.shares} 股 @${o.price}（約 ${money(o.gross)}）`)
    const text = `${plan.note}\n${lines.join('\n')}`
    try { navigator.clipboard.writeText(text); setMsg('指令已複製到剪貼簿') } catch { setMsg('瀏覽器不讓複製，請手動選取') }
  }

  if (!orders.length) {
    return <div className="muted" style={{ padding: '1rem 1.25rem', fontSize: '.88rem' }}>依目前持股與現金，沒有需要下的單（偏離 {pct(plan.summary.drift_before)}，每筆調整都小於 NT${money(plan.summary.min_trade)}）。</div>
  }
  return (
    <>
      <div style={{ display: 'flex', gap: '.6rem', alignItems: 'center', flexWrap: 'wrap', padding: '.7rem 1.25rem', borderBottom: '1px solid var(--border-soft)' }}>
        <label style={{ display: 'flex', alignItems: 'center', gap: '.35rem', fontSize: '.84rem' }}>
          <input type="checkbox" checked={allOn} onChange={e => setChecked(e.target.checked ? Object.fromEntries(orders.map(o => [o.stock_id, true])) : {})} /> 全選
        </label>
        <label style={{ fontSize: '.84rem' }}>成交日 <input type="date" className="ctrl-select" value={date} onChange={e => setDate(e.target.value)} /></label>
        <button className="btn-primary" disabled={!picked.length || busy} onClick={register}>{busy ? '登記中…' : `登記已執行的 ${picked.length} 筆`}</button>
        <button className="btn-secondary" onClick={copyText}>複製指令文字</button>
        {msg ? <span className="muted" style={{ fontSize: '.8rem' }}>{msg}</span> : null}
      </div>
      <div style={{ overflowX: 'auto' }}>
        <table className="data-table">
          <thead>
            <tr>
              <th className="mid">已執行</th><th>動作</th><th>股票</th><th className="num">股數</th><th className="num">參考價</th>
              <th className="num">成交價<Sub>可改</Sub></th><th className="num">金額</th><th className="num">費用<Sub>手續費＋稅</Sub></th>
              <th className="num">權重<Sub>現在 → 目標</Sub></th><th>原因</th>
            </tr>
          </thead>
          <tbody>
            {orders.map(o => {
              const [label, cls] = REASON[o.reason] || [o.reason, '']
              return (
                <tr key={o.stock_id} style={{ background: checked[o.stock_id] ? 'var(--blue-soft)' : undefined }}>
                  <td className="mid"><input type="checkbox" checked={!!checked[o.stock_id]} onChange={e => setChecked({ ...checked, [o.stock_id]: e.target.checked })} /></td>
                  <td><strong className={o.side === 'Buy' ? 'up' : 'down'}>{o.side === 'Buy' ? '買進' : '賣出'}</strong></td>
                  <td><strong>{o.stock_id}</strong> {o.stock_name || ''}</td>
                  <td className="num"><strong>{o.shares.toLocaleString()}</strong> 股<Sub>{formatShares(o.shares)}</Sub></td>
                  <td className="num">{o.price}</td>
                  <td className="num"><input type="number" step="0.01" className="ctrl-select" style={{ width: 96, textAlign: 'right' }} value={fills[o.stock_id] ?? o.price} onChange={e => setFills({ ...fills, [o.stock_id]: e.target.value })} /></td>
                  <td className="num">{money(o.gross)}</td>
                  <td className="num">{money(o.fee + o.tax)}</td>
                  <td className="num">{pct(o.weight_now)} → {pct(o.weight_target)}<Sub>{o.shares_now.toLocaleString()} → {o.shares_target.toLocaleString()} 股</Sub></td>
                  <td><span className={`tag ${cls}`}>{label}</span></td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </>
  )
}

function PositionsTable({ positions }) {
  if (!positions?.length) return null
  return (
    <div style={{ overflowX: 'auto' }}>
      <table className="data-table">
        <thead><tr><th>股票</th><th className="num">排名</th><th className="num">持有</th><th className="num">目標</th><th className="num">權重 現在</th><th className="num">目標</th><th className="num">參考價</th><th>本次</th></tr></thead>
        <tbody>
          {positions.map(p => (
            <tr key={p.stock_id}>
              <td><strong>{p.stock_id}</strong> {p.stock_name || ''}{p.is_new ? <span className="up"> ★</span> : null}</td>
              <td className="num">{p.rank == null ? (p.weight_target > 0 ? '固定/續抱' : '退出') : `#${p.rank}`}</td>
              <td className="num">{p.shares_now.toLocaleString()}</td>
              <td className="num">{p.shares_target.toLocaleString()}</td>
              <td className="num">{pct(p.weight_now)}</td>
              <td className="num">{pct(p.weight_target)}</td>
              <td className="num">{p.price}</td>
              <td>{p.side ? <span className={p.side === 'Buy' ? 'up' : 'down'}>{p.side === 'Buy' ? '買' : '賣'} {p.shares.toLocaleString()}</span> : <span className="muted">不動</span>}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function LogTable({ log }) {
  if (!log?.items?.length) return <div className="muted" style={{ padding: '1rem 1.25rem', fontSize: '.88rem' }}>還沒有用程式交易登記過的交易。登記後這裡按清單分批，對得出每一批買了多少、賣了多少、花了多少費用。</div>
  return (
    <>
      <div className="stat-grid">
        {log.batches.slice(0, 4).map(b => (
          <div className="stat-tile" key={b.batch}>
            <div className="k">清單 {b.batch}</div>
            <div className="v">{b.n} 筆</div>
            <div className="s">買 {money(b.buy)} · 賣 {money(b.sell)} · 費用 {money(b.fees)} · {b.first}{b.last !== b.first ? `～${b.last}` : ''}</div>
          </div>
        ))}
      </div>
      <div style={{ maxHeight: 360, overflowY: 'auto' }}>
        <table className="data-table">
          <thead><tr><th>成交日</th><th>清單</th><th>動作</th><th>股票</th><th className="num">股數</th><th className="num">價格</th><th className="num">金額</th><th className="num">費用</th><th className="num">之後持有</th><th className="num">已實現</th></tr></thead>
          <tbody>
            {log.items.map(t => (
              <tr key={t.id}>
                <td>{t.trade_date}</td><td>{t.batch || '–'}</td>
                <td><span className={t.side === 'Buy' ? 'up' : 'down'}>{t.side === 'Buy' ? '買' : '賣'}</span></td>
                <td><strong>{t.stock_id}</strong> {t.stock_name || ''}</td>
                <td className="num">{t.shares?.toLocaleString()}</td><td className="num">{t.price}</td><td className="num">{money(t.gross)}</td>
                <td className="num">{money((t.fee || 0) + (t.tax || 0))}</td><td className="num">{t.shares_after?.toLocaleString() ?? '–'}</td>
                <td className="num">{t.realized_pnl != null ? <span className={t.realized_pnl > 0 ? 'up' : t.realized_pnl < 0 ? 'down' : 'muted'}>{money(t.realized_pnl)}</span> : '–'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  )
}

export default function AlgoTrading() {
  const [cash, setCash] = useState(() => Number(readLS(CASH_KEY, 300000)))
  const [minTrade, setMinTrade] = useState(() => Number(readLS(MIN_KEY, 1000)))
  const [plan, setPlan] = useState(null)
  const [log, setLog] = useState(null)
  const [paper, setPaper] = useState(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const load = useCallback(async (c = cash, m = minTrade) => {
    setLoading(true)
    const [p, l, pp] = await Promise.all([getTradingPlan(c, m), getTradingLog(), getPortfolioPaper()])
    if (p.error) { setError(p.error); setPlan(null) } else { setError(''); setPlan(p.data) }
    setLog(l.data); setPaper(pp.data)
    setLoading(false)
  }, [cash, minTrade])

  useEffect(() => { load() }, [])   // eslint-disable-line react-hooks/exhaustive-deps
  function run() { writeLS(CASH_KEY, cash); writeLS(MIN_KEY, minTrade); load(cash, minTrade) }

  const s = plan?.summary
  const review = paper?.review
  const managedValue = useMemo(() => s ? s.position_value : null, [s])

  return (
    <>
      {/* 控制列 */}
      <div className="card" style={{ marginBottom: '1.1rem' }}>
        <div className="card-header">
          <div>
            <div className="card-title">候選策略 → 下單指令</div>
            <Sub>
              {plan?.list ? <>清單訊號日 <strong>{plan.list.rebalance_date}</strong> · {plan.list.n} 檔 · 參考價至 {plan.list.price_date || '–'} · run #{plan.list.run_id}</> : '清單讀取中'}
              {plan?.schedule ? <> · 下一個訊號日約 <strong>{plan.schedule.signal_date}</strong>（{plan.schedule.exec_date} 開盤成交）</> : null}
            </Sub>
          </div>
          <div style={{ display: 'flex', gap: '.5rem', alignItems: 'flex-end', flexWrap: 'wrap' }}>
            <div className="ctrl-group">
              <div className="ctrl-label">可投入現金（NT$）</div>
              <input type="number" className="ctrl-select" style={{ width: 140, textAlign: 'right' }} value={cash} min={0} step={10000} onChange={e => setCash(Number(e.target.value))} />
            </div>
            <div className="btn-group">
              {QUICK.map(q => <button key={q} className={`btn-period${cash === q ? ' active' : ''}`} onClick={() => setCash(q)}>{q / 10000} 萬</button>)}
            </div>
            <div className="ctrl-group">
              <div className="ctrl-label">最小下單金額</div>
              <input type="number" className="ctrl-select" style={{ width: 96, textAlign: 'right' }} value={minTrade} min={0} step={500} onChange={e => setMinTrade(Number(e.target.value))} />
            </div>
            <button className="btn-primary" onClick={run} disabled={loading}>{loading ? '計算中…' : '產生指令'}</button>
          </div>
        </div>
        {error ? <div className="down" style={{ padding: '1rem 1.25rem' }}>{error}</div> : null}
        {s ? (
          <div className="stat-grid">
            <div className="stat-tile"><div className="k">總資產（範圍內）</div><div className="v">{money(s.total)}</div><div className="s">現金 {money(s.cash)} ＋ 策略持股 {money(managedValue)}</div></div>
            <div className="stat-tile"><div className="k">指令</div><div className="v"><span className="down">{s.n_sell} 賣</span> / <span className="up">{s.n_buy} 買</span></div><div className="s">賣出淨入 {money(s.sell_net)} · 買進成本 {money(s.buy_cost)}</div></div>
            <div className="stat-tile"><div className="k">執行後現金</div><div className="v">{money(s.cash_after)}</div><div className="s">費用合計 {money(s.fees)}</div></div>
            <div className="stat-tile"><div className="k">權重偏離</div><div className="v">{pct(s.drift_before)} → {pct(s.drift_after)}</div><div className="s">Σ|現在 − 目標| ÷ 2</div></div>
            <div className="stat-tile"><div className="k">紙上帳戶</div><div className="v">{review?.active_return != null ? <span className={review.active_return > 0 ? 'up' : 'down'}>{pct(review.active_return, 2)}</span> : '–'}</div><div className="s">{review?.days ? `對 0050，${review.days} 個交易日；待成交清單 ${paper?.pending?.length || 0} 份` : paper?.opened ? `已開戶（${review?.state?.started_on || ''}），尚未結算；待成交清單 ${paper?.pending?.length || 0} 份` : paper ? '模擬帳戶未開' : '讀不到'}</div></div>
            <div className="stat-tile"><div className="k">策略範圍</div><div className="v">{plan.positions.length} 檔</div><div className="s">不動的其他持股 {plan.untouched.length} 檔</div></div>
          </div>
        ) : null}
        {plan?.warnings?.length ? <div className="note-box" style={{ color: 'var(--orange)' }}>{plan.warnings.map((w, i) => <div key={i}>⚠ {w}</div>)}</div> : null}
      </div>

      {/* 指令表 */}
      {plan ? (
        <div className="card" style={{ marginBottom: '1.1rem' }}>
          <div className="card-header"><div className="card-title">下單指令</div><Sub>先賣後買 · 零股限價單 · 執行完勾選登記，台帳是唯一的事實來源</Sub></div>
          <OrdersTable plan={plan} onRegistered={() => load(cash, minTrade)} />
        </div>
      ) : null}

      <div className="two-col" style={{ marginBottom: '1.1rem' }}>
        <div className="card">
          <div className="card-header"><div className="card-title">策略範圍內的部位</div><Sub>清單股票 ＋ 以前用這頁登記過的股票</Sub></div>
          {plan ? <PositionsTable positions={plan.positions} /> : <div className="muted" style={{ padding: '1rem 1.25rem', fontSize: '.88rem' }}>–</div>}
        </div>
        <div className="card">
          <div className="card-header"><div className="card-title">不動的其他持股</div><Sub>你自己買的，程式不會替你賣</Sub></div>
          {plan?.untouched?.length ? (
            <table className="data-table">
              <thead><tr><th>股票</th><th className="num">股數</th><th className="num">最後收盤</th><th className="num">市值</th></tr></thead>
              <tbody>{plan.untouched.map(u => <tr key={u.stock_id}><td><strong>{u.stock_id}</strong> {u.stock_name || ''}</td><td className="num">{u.shares.toLocaleString()}</td><td className="num">{u.last_price ?? '–'}</td><td className="num">{money(u.market_value)}</td></tr>)}</tbody>
            </table>
          ) : <div className="muted" style={{ padding: '1rem 1.25rem', fontSize: '.88rem' }}>沒有範圍外的持股</div>}
        </div>
      </div>

      <div className="card" style={{ marginBottom: '1.1rem' }}>
        <div className="card-header"><div className="card-title">執行紀錄</div><Sub>台帳裡 note 以 [程式交易] 開頭的交易，按清單分批</Sub></div>
        <LogTable log={log} />
      </div>

      <div className="card">
        <div className="note-box">
          沒有券商 API：這一頁算指令，你到券商 App 用零股限價單下；成交價填回「成交價」欄再登記，台帳會重算均價與已實現損益（在「我的持股」也看得到，note 標 [程式交易]）。<br />
          參考價是最新收盤，實際成交是下一個開盤；候選策略的回測與紙上交易都用開盤價，所以這裡的金額是「約」。<br />
          手續費 0.1425%（零股最低 1 元、整股最低 20 元），賣出另有 0.3% 證交稅；券商折扣自己在登記時改 fee。<br />
          每月 11 日起第一個交易日收盤算新清單（週末已避開，假日沒有）；清單換了再回來這一頁，退出清單的會出現賣單。
        </div>
      </div>
    </>
  )
}
