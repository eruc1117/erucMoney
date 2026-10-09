// 月調倉（打敗大盤計畫）頁（Iteration 51）
// ───────────────────────────────────────────────────────────────────────────
// 顯示實驗日誌裡「標記為候選」的設定：開發期、驗證期、全期間三列的指標對門檻，
// 全期間的淨值曲線對 0050、逐年主動報酬、最後一次持股，以及全部實驗（N 只增不減）。
//
// 這一頁刻意把 DSR 放在和主動報酬一樣大的位置：44 次嘗試後挑最好的，
// 月 Sharpe 0.16 這種程度純靠運氣也挑得到，所以「超越了」和「不是運氣」是兩件事。
import { useEffect, useState } from 'react'
import ReactApexChart from 'react-apexcharts'
import { getPortfolioCandidate, getPortfolioRuns, getPortfolioPaper } from '../services/api'

function num(v, d = 2) { return v === null || v === undefined || Number.isNaN(Number(v)) ? '–' : Number(v).toFixed(d) }
function pct(v, d = 2) {
  if (v === null || v === undefined || Number.isNaN(Number(v))) return '–'
  const n = Number(v) * 100
  return `${n > 0 ? '+' : ''}${n.toFixed(d)}%`
}
function tone(v) { return v === null || v === undefined ? 'muted' : Number(v) > 0 ? 'up' : Number(v) < 0 ? 'down' : 'muted' }
function Sub({ children }) { return <div className="muted" style={{ fontSize: '0.72rem' }}>{children}</div> }
function Pass({ ok }) { return ok === null || ok === undefined ? <span className="muted">–</span> : ok ? <span className="up">通過</span> : <span className="down">未過</span> }

function gatesOf(m, t) {
  if (!m || !t) return {}
  return {
    ann_active: m.ann_active >= t.ann_active,
    info_ratio: m.info_ratio !== null && m.info_ratio >= t.info_ratio,
    dsr: m.dsr >= t.dsr,
    turnover: m.turnover_annual >= t.turnover_min && m.turnover_annual <= t.turnover_max,
  }
}

function RuleLine({ p }) {
  if (!p) return null
  const bits = [
    `訊號 ${p.signal}`,
    p.tranches > 1 ? `分 ${p.tranches} 批輪動（每月換 1/${p.tranches}）` : `緩衝 ${p.buffer} 名`,
    `流動性前 ${p.universe_n}`, `前 ${p.top_n} 檔${p.weighting === 'liq' ? '成交金額加權' : '等權'}`,
    p.tsmc_weight ? `台積電固定持 0050 權重（${p.tsmc_weight === 'est' ? '滾動迴歸估' : p.tsmc_weight}）` : '不持台積電',
  ]
  return <Sub>{bits.join(' · ')}</Sub>
}

function CandidateTable({ rows, t }) {
  if (!rows?.length) return <div className="card-body muted">還沒有標記為候選的實驗（portfolio_backtest.py --tag）</div>
  return (
    <div style={{ overflowX: 'auto' }}>
      <table className="data-table">
        <thead>
          <tr>
            <th>期間</th>
            <th style={{ textAlign: 'right' }}>年化主動報酬<Sub>門檻 ≥ {pct(t.ann_active, 0)}</Sub></th>
            <th style={{ textAlign: 'right' }}>資訊比率<Sub>≥ {t.info_ratio}</Sub></th>
            <th style={{ textAlign: 'right' }}>DSR<Sub>≥ {t.dsr}</Sub></th>
            <th style={{ textAlign: 'right' }}>月勝率</th>
            <th style={{ textAlign: 'right' }}>追蹤誤差</th>
            <th style={{ textAlign: 'right' }}>相對最大落後</th>
            <th style={{ textAlign: 'right' }}>年換手<Sub>{t.turnover_min}~{t.turnover_max} 倍</Sub></th>
            <th style={{ textAlign: 'right' }}>成本/年</th>
            <th style={{ textAlign: 'right' }}>組合 / 0050</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(r => {
            const m = r.metrics || {}; const g = gatesOf(m, t)
            return (
              <tr key={r.id}>
                <td style={{ whiteSpace: 'nowrap' }}>
                  <strong>{r.segment_label}{r.name?.includes('dev+valid') ? '＋驗證期' : ''}</strong>
                  <Sub>#{r.experiment_n} · {r.period_start} ~ {r.period_end} · {m.months} 個月</Sub>
                </td>
                <td style={{ textAlign: 'right' }}><strong className={tone(m.ann_active)}>{pct(m.ann_active)}</strong><Sub><Pass ok={g.ann_active} /></Sub></td>
                <td style={{ textAlign: 'right' }}>{num(m.info_ratio)}<Sub><Pass ok={g.info_ratio} /></Sub></td>
                <td style={{ textAlign: 'right' }}><strong className={g.dsr ? 'up' : 'down'}>{num(m.dsr, 2)}</strong><Sub>N = {m.experiment_n}，SR* {num(m.sr_star_m)}</Sub></td>
                <td style={{ textAlign: 'right' }}>{pct(m.monthly_win_rate, 0).replace('+', '')}</td>
                <td style={{ textAlign: 'right' }}>{pct(m.tracking_error, 1).replace('+', '')}</td>
                <td style={{ textAlign: 'right' }}><span className="down">{pct(m.rel_mdd, 1)}</span></td>
                <td style={{ textAlign: 'right' }}>{num(m.turnover_annual, 1)}<Sub><Pass ok={g.turnover} /></Sub></td>
                <td style={{ textAlign: 'right' }}>{pct(m.cost_drag_annual).replace('+', '')}</td>
                <td style={{ textAlign: 'right' }}>{pct(m.cagr_port, 1)} / {pct(m.cagr_bench, 1)}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function NavChart({ series }) {
  if (!series?.length) return <div className="card-body muted">這個 run 沒有淨值曲線（portfolio_backtest.py --attach-series 補上）</div>
  const toPts = key => series.map(p => [new Date(p.d).getTime(), Number(p[key])])
  const data = [{ name: '組合', data: toPts('nav') }, { name: '0050 含息', data: toPts('bench') }]
  const options = {
    chart: { type: 'line', toolbar: { show: false }, animations: { enabled: false }, background: 'transparent' },
    stroke: { width: [2.5, 1.5], curve: 'straight', dashArray: [0, 4] },
    colors: ['#2f80ed', '#9aa4b2'],
    xaxis: { type: 'datetime', labels: { datetimeUTC: false } },
    yaxis: { labels: { formatter: v => v.toFixed(2) }, title: { text: '淨值（起點 1）' } },
    tooltip: { x: { format: 'yyyy-MM-dd' }, y: { formatter: v => v.toFixed(3) } },
    legend: { position: 'top' },
    grid: { borderColor: 'rgba(128,128,128,0.2)' },
    theme: { mode: document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light' },
  }
  return <div className="chart-pad"><ReactApexChart type="line" series={data} options={options} height={320} /></div>
}

function YearlyTable({ yearly }) {
  const ys = Object.keys(yearly || {}).sort()
  if (!ys.length) return null
  return (
    <table className="data-table" style={{ maxWidth: 420 }}>
      <thead><tr><th>年</th><th style={{ textAlign: 'right' }}>主動報酬</th></tr></thead>
      <tbody>{ys.map(y => <tr key={y}><td>{y}</td><td style={{ textAlign: 'right' }}><span className={tone(yearly[y])}>{pct(yearly[y])}</span></td></tr>)}</tbody>
    </table>
  )
}

function CurrentList({ list }) {
  if (!list?.items?.length) return <div className="card-body muted">還沒算本月清單（portfolio_backtest.py --current-list 44）</div>
  const items = list.items
  const tsmc = items.find(i => i.stock_id === '2330')
  const picks = items.filter(i => i.stock_id !== '2330')   // rank 空的是上幾批進場、本月沒進排名但還沒到期的續抱
  return (
    <div className="card-body" style={{ paddingTop: 8 }}>
      <div className="muted" style={{ fontSize: '0.82rem', marginBottom: 8 }}>
        訊號日 <strong>{list.rebalance_date}</strong> 收盤算，{list.exec_date} 開盤以限價單成交；共 {items.length} 檔。
        {tsmc ? <> 台積電固定 <strong>{pct(tsmc.target_weight, 1).replace('+', '')}</strong>（0050 權重估計），其餘 {picks.length} 檔各 {pct(picks[0]?.target_weight, 1).replace('+', '')}。</> : null}
        <span className="up"> ★</span> 是這個月新進場的一批（分三批輪動，每月只換三分之一）。
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))', gap: 8 }}>
        {tsmc ? (
          <div className="stat-tile" title="台積電不參與排名，固定持 0050 的台積電權重">
            <div className="k">固定</div>
            <div className="v">{tsmc.stock_id} {tsmc.stock_name || ''}</div>
            <div className="s">{pct(tsmc.target_weight, 1).replace('+', '')}</div>
          </div>
        ) : null}
        {picks.map(p => (
          <div key={p.stock_id} className="stat-tile" title={p.rank === null || p.rank === undefined ? '上幾批進場、本月未進排名的續抱（到期才賣）' : `本月排名 ${p.rank}，訊號值 ${p.signal_value === null ? '–' : num(p.signal_value, 3)}`}>
            <div className="k">{p.rank === null || p.rank === undefined ? '續抱' : `#${p.rank}`}{p.is_new ? <span className="up"> ★</span> : null}</div>
            <div className="v">{p.stock_id} {p.stock_name || ''}</div>
            <div className="s">{pct(p.target_weight, 1).replace('+', '')}</div>
          </div>
        ))}
      </div>
      <Sub>算到 {String(list.computed_at).slice(0, 16).replace('T', ' ')}；這是候選策略的目標清單，不是投資建議。保留期（2024-10 起）的績效沒有算、沒有存。</Sub>
    </div>
  )
}

function Positions({ positions, last }) {
  if (!positions?.length) return <div className="card-body muted">沒有持股紀錄</div>
  return (
    <div style={{ overflowX: 'auto' }}>
      <table className="data-table">
        <thead><tr><th>排名</th><th>代碼</th><th style={{ textAlign: 'right' }}>訊號值</th><th style={{ textAlign: 'right' }}>權重</th><th>成交</th></tr></thead>
        <tbody>
          {positions.map(p => (
            <tr key={p.stock_id}>
              <td>{p.stock_id === '2330' ? <span className="muted" title="台積電不參與排名，固定持 0050 權重">固定</span> : (p.rank ?? <span className="muted" title="上幾批進場、該月未進排名的續抱">續抱</span>)}</td>
              <td><strong>{p.stock_id}</strong></td>
              <td style={{ textAlign: 'right' }}>{p.signal_value === null ? '–' : num(p.signal_value, 3)}</td>
              <td style={{ textAlign: 'right' }}>{pct(p.target_weight, 1).replace('+', '')}</td>
              <td>{p.filled ? <span className="up">是</span> : <span className="down" title="成交日一字鎖漲跌停，視為未成交">未成交</span>}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <Sub>訊號日 {last}，次一交易日開盤成交；這是回測期最後一次調倉，不是今天的清單（紙上交易上線後才會每月出新清單）</Sub>
    </div>
  )
}

function PaperCard({ paper }) {
  if (!paper) return null
  if (!paper.opened) return <div className="card-body muted">模擬帳戶還沒開（python portfolio_paper.py --start）</div>
  const r = paper.review || {}
  const st = r.state || {}
  const exp = r.expected || {}
  const series = r.series || []
  const toPts = key => series.filter(p => p[key] !== null && p[key] !== undefined).map(p => [new Date(p.d).getTime(), Number(p[key])])
  const chart = series.length > 1 ? {
    data: [{ name: '模擬帳戶', data: toPts('nav') }, { name: '0050 含息', data: toPts('bench') }],
    options: {
      chart: { type: 'line', toolbar: { show: false }, animations: { enabled: false }, background: 'transparent' },
      stroke: { width: [2.5, 1.5], curve: 'straight', dashArray: [0, 4] }, colors: ['#27ae60', '#9aa4b2'],
      xaxis: { type: 'datetime', labels: { datetimeUTC: false } }, yaxis: { labels: { formatter: v => v.toFixed(3) } },
      tooltip: { x: { format: 'yyyy-MM-dd' }, y: { formatter: v => v.toFixed(4) } }, legend: { position: 'top' },
      grid: { borderColor: 'rgba(128,128,128,0.2)' }, theme: { mode: document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light' },
    },
  } : null
  const holdings = paper.holdings || []
  const trades = (paper.trades || []).slice(0, 40)
  return (
    <>
      <div className="card-body" style={{ paddingTop: 8 }}>
        <div className="stat-grid">
          <div className="stat-tile"><div className="k">起始</div><div className="v">{st.started_on || '–'}</div><div className="s">資金 {Number(st.start_capital || 0).toLocaleString()}</div></div>
          <div className="stat-tile"><div className="k">淨值</div><div className="v">{r.nav ? Number(r.nav).toLocaleString() : '–'}</div><div className="s">現金 {r.cash ? Number(r.cash).toLocaleString() : '–'} · 持股 {r.n_holdings ?? 0} 檔</div></div>
          <div className="stat-tile"><div className="k">模擬帳戶報酬</div><div className={`v ${tone(r.port_return)}`}>{pct(r.port_return)}</div><div className="s">{r.since || ''} ~ {r.as_of || ''}（{r.days ?? 0} 個交易日）</div></div>
          <div className="stat-tile"><div className="k">0050 同期</div><div className={`v ${tone(r.bench_return)}`}>{pct(r.bench_return)}</div><div className="s">含息還原價</div></div>
          <div className="stat-tile"><div className="k">主動報酬</div><div className={`v ${tone(r.active_return)}`}>{pct(r.active_return)}</div><div className="s">回測預期：每月約 {pct(exp.monthly_active_mean)}、月勝率 {exp.monthly_win_rate ? pct(exp.monthly_win_rate, 0).replace('+', '') : '–'}</div></div>
          <div className="stat-tile"><div className="k">待成交清單</div><div className="v">{paper.pending?.length ? paper.pending.join('、') : '無'}</div><div className="s">訊號日次一交易日開盤成交</div></div>
        </div>
      </div>
      {chart && <div className="chart-pad"><ReactApexChart type="line" series={chart.data} options={chart.options} height={240} /></div>}
      {r.monthly?.length ? (
        <div className="card-body" style={{ paddingTop: 0 }}>
          <table className="data-table" style={{ maxWidth: 520 }}>
            <thead><tr><th>月</th><th style={{ textAlign: 'right' }}>模擬帳戶</th><th style={{ textAlign: 'right' }}>0050</th><th style={{ textAlign: 'right' }}>主動</th><th style={{ textAlign: 'right' }}>回測預期（月均）</th></tr></thead>
            <tbody>{r.monthly.map(m => (
              <tr key={m.month}><td>{m.month}</td><td style={{ textAlign: 'right' }}>{pct(m.port)}</td><td style={{ textAlign: 'right' }}>{pct(m.bench)}</td>
                <td style={{ textAlign: 'right' }}><span className={tone(m.active)}>{pct(m.active)}</span></td><td style={{ textAlign: 'right' }} className="muted">{pct(exp.monthly_active_mean)}</td></tr>
            ))}</tbody>
          </table>
        </div>
      ) : null}
      <div className="card-body" style={{ paddingTop: 0 }}>
        <Sub>持股 {holdings.length} 檔：{holdings.map(h => `${h.stock_id}×${h.shares}`).join('、') || '全現金'}</Sub>
        {trades.length ? (
          <div style={{ overflowX: 'auto', marginTop: 8 }}>
            <table className="data-table" style={{ fontSize: '0.82rem' }}>
              <thead><tr><th>成交日</th><th>清單</th><th>代碼</th><th>買/賣</th><th style={{ textAlign: 'right' }}>股</th><th style={{ textAlign: 'right' }}>價</th><th style={{ textAlign: 'right' }}>金額</th><th style={{ textAlign: 'right' }}>費+稅</th><th>狀態</th></tr></thead>
              <tbody>{trades.map((t, i) => (
                <tr key={i}><td>{t.trade_date}</td><td className="muted">{t.rebalance_date}</td><td><strong>{t.stock_id}</strong></td>
                  <td className={t.side === 'buy' ? 'up' : 'down'}>{t.side === 'buy' ? '買' : '賣'}</td>
                  <td style={{ textAlign: 'right' }}>{t.shares.toLocaleString()}</td><td style={{ textAlign: 'right' }}>{num(t.price)}</td>
                  <td style={{ textAlign: 'right' }}>{Math.round(t.gross).toLocaleString()}</td><td style={{ textAlign: 'right' }}>{Math.round(t.fee + t.tax).toLocaleString()}</td>
                  <td>{t.filled ? <span className="up">成交</span> : <span className="down" title={t.note || ''}>未成交</span>}</td></tr>
              ))}</tbody>
            </table>
          </div>
        ) : <Sub>還沒有成交紀錄：第一份清單在本月 11 日起第一個交易日收盤算，次一交易日開盤成交。</Sub>}
        <Sub>規則與回測相同：零股、單邊手續費 0.0855%、賣出稅 0.3%、一字鎖死不成交；每天 18:40 自動成交／結算，漏跑會補。這是階段 4 的紙上交易，不是真錢。</Sub>
      </div>
    </>
  )
}

// ── 次分頁「買多少股」：輸入金額 → 依最近清單的目標權重與最新收盤價算零股股數 ──────────
const FEE_RATE = 0.000855      // 單邊手續費（6 折）；與回測、紙上交易同一個數字
const FEE_MIN = 1              // 零股最低手續費（多數券商 NT$1）；整張是 NT$20
const TAX_RATE = 0.003

function planShares(items, amount) {
  // 先按比例縮以留手續費，再逐檔 floor；剩餘現金最後報出來（不硬塞）
  const usable = amount / (1 + FEE_RATE)
  const rows = items.map(it => {
    if (!it.price || it.price <= 0) return { ...it, shares: 0, cost: 0, fee: 0, note: '沒有價格' }
    const shares = Math.floor(usable * it.target_weight / it.price)
    const cost = shares * it.price
    const fee = shares > 0 ? Math.max(FEE_MIN, Math.round(cost * FEE_RATE)) : 0
    return { ...it, shares, cost, fee, lots: Math.floor(shares / 1000), odd: shares % 1000 }
  })
  const totalCost = rows.reduce((a, r) => a + r.cost, 0)
  const totalFee = rows.reduce((a, r) => a + r.fee, 0)
  return { rows, totalCost, totalFee, left: amount - totalCost - totalFee, invested: amount > 0 ? totalCost / amount : 0 }
}

function BuyCalculator({ list }) {
  const [amountText, setAmountText] = useState(() => { try { return localStorage.getItem('pf_buy_amount') || '300000' } catch { return '300000' } })
  const amount = Math.max(0, Number(String(amountText).replace(/[^0-9.]/g, '')) || 0)
  useEffect(() => { try { localStorage.setItem('pf_buy_amount', String(amountText)) } catch { /* ignore */ } }, [amountText])
  if (!list?.items?.length) return <div className="card-body muted">還沒有清單（每月 11 日起第一個交易日收盤後才有）</div>
  const plan = planShares(list.items, amount)
  const noPrice = plan.rows.filter(r => !r.price).length
  return (
    <>
      <div className="card-body">
        <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
          <label className="ctrl-label" htmlFor="pf-amount">投入金額（NT$）</label>
          <input id="pf-amount" className="budget-input" inputMode="numeric" value={amountText} onChange={e => setAmountText(e.target.value)} style={{ width: 160 }} />
          <div className="btn-group">
            {[100000, 300000, 500000, 1000000].map(v => <button key={v} className="btn-filter" onClick={() => setAmountText(String(v))}>{(v / 10000).toFixed(0)} 萬</button>)}
          </div>
        </div>
        <Sub>依 {list.rebalance_date} 清單的目標權重與 {list.price_date || '最新'} 收盤價；零股（1 股起），買單先留手續費 {(FEE_RATE * 100).toFixed(4)}%（最低 NT${FEE_MIN}）再取整，所以會剩一點現金。賣出另有 {TAX_RATE * 100}% 證交稅。</Sub>
      </div>
      <div className="card-body" style={{ paddingTop: 0 }}>
        <div className="stat-grid">
          <div className="stat-tile"><div className="k">投入</div><div className="v">{amount.toLocaleString()}</div><div className="s">{plan.rows.filter(r => r.shares > 0).length} 檔有買到</div></div>
          <div className="stat-tile"><div className="k">買進成本</div><div className="v">{Math.round(plan.totalCost).toLocaleString()}</div><div className="s">投入的 {(plan.invested * 100).toFixed(1)}%</div></div>
          <div className="stat-tile"><div className="k">手續費</div><div className="v">{plan.totalFee.toLocaleString()}</div><div className="s">含零股最低費</div></div>
          <div className="stat-tile"><div className="k">剩餘現金</div><div className="v">{Math.round(plan.left).toLocaleString()}</div><div className="s">{noPrice ? `${noPrice} 檔沒有價格` : '取整後的零頭'}</div></div>
        </div>
      </div>
      <div style={{ overflowX: 'auto' }}>
        <table className="data-table">
          <thead>
            <tr><th>排名</th><th>代碼</th><th>名稱</th><th style={{ textAlign: 'right' }}>目標權重</th><th style={{ textAlign: 'right' }}>收盤價</th>
              <th style={{ textAlign: 'right' }}>買幾股</th><th style={{ textAlign: 'right' }}>張＋零股</th><th style={{ textAlign: 'right' }}>成本</th><th style={{ textAlign: 'right' }}>手續費</th><th style={{ textAlign: 'right' }}>實際權重</th></tr>
          </thead>
          <tbody>
            {plan.rows.map(r => (
              <tr key={r.stock_id} style={r.shares === 0 ? { opacity: 0.55 } : undefined}>
                <td>{r.stock_id === '2330' ? <span className="muted" title="台積電固定持 0050 權重">固定</span> : (r.rank ?? <span className="muted">續抱</span>)}</td>
                <td><strong>{r.stock_id}</strong>{r.is_new ? <span className="up" title="這個月新進場"> ★</span> : null}</td>
                <td>{r.stock_name || ''}</td>
                <td style={{ textAlign: 'right' }}>{pct(r.target_weight, 1).replace('+', '')}</td>
                <td style={{ textAlign: 'right' }}>{r.price ? num(r.price, 2) : <span className="down">–</span>}</td>
                <td style={{ textAlign: 'right' }}><strong>{r.shares.toLocaleString()}</strong>{r.note ? <Sub>{r.note}</Sub> : null}</td>
                <td style={{ textAlign: 'right' }} className="muted">{r.shares > 0 ? `${r.lots} 張 ${r.odd} 股` : '–'}</td>
                <td style={{ textAlign: 'right' }}>{Math.round(r.cost).toLocaleString()}</td>
                <td style={{ textAlign: 'right' }}>{r.fee.toLocaleString()}</td>
                <td style={{ textAlign: 'right' }}>{amount > 0 ? pct(r.cost / amount, 1).replace('+', '') : '–'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="card-body muted" style={{ fontSize: '0.8rem', lineHeight: 1.7 }}>
        這是把候選策略的目標權重換算成股數，不是投資建議。清單每月更新一次（11 日起第一個交易日收盤算），換月時要先賣掉不在新清單裡的、再買新進場的★，賣出才有證交稅。
        金額小的時候高價股（台積電）會吃掉大半權重、低價股零頭多；投入 30 萬以下建議看「剩餘現金」與「實際權重」是否偏離目標太多。
      </div>
    </>
  )
}

function RunLog({ runs, t }) {
  if (!runs?.length) return <div className="card-body muted">實驗日誌是空的</div>
  return (
    <div style={{ overflowX: 'auto' }}>
      <table className="data-table" style={{ fontSize: '0.84rem' }}>
        <thead>
          <tr><th>N</th><th>設定</th><th>段</th><th>期間</th><th style={{ textAlign: 'right' }}>年化主動</th><th style={{ textAlign: 'right' }}>IR</th>
            <th style={{ textAlign: 'right' }}>DSR</th><th style={{ textAlign: 'right' }}>換手</th><th style={{ textAlign: 'right' }}>成本/年</th><th>備註</th></tr>
        </thead>
        <tbody>
          {runs.map(r => {
            const m = r.metrics || {}
            const cand = r.tag === 'candidate'
            return (
              <tr key={r.id} style={cand ? { background: 'rgba(47,128,237,0.08)' } : undefined}>
                <td>{r.experiment_n}{cand ? <span className="up" title="候選"> ★</span> : null}</td>
                <td style={{ whiteSpace: 'nowrap' }}>{r.name}</td>
                <td>{r.segment_label}</td>
                <td style={{ whiteSpace: 'nowrap' }}><Sub>{r.period_start} ~ {r.period_end}</Sub></td>
                <td style={{ textAlign: 'right' }}><span className={tone(m.ann_active)}>{pct(m.ann_active)}</span></td>
                <td style={{ textAlign: 'right' }}>{num(m.info_ratio)}</td>
                <td style={{ textAlign: 'right' }}><span className={m.dsr >= t.dsr ? 'up' : ''}>{num(m.dsr, 2)}</span></td>
                <td style={{ textAlign: 'right' }}>{num(m.turnover_annual, 1)}</td>
                <td style={{ textAlign: 'right' }}>{pct(m.cost_drag_annual).replace('+', '')}</td>
                <td className="muted" style={{ maxWidth: 360, fontSize: '0.78rem' }}>{r.notes}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

export default function PortfolioLab() {
  const [cand, setCand] = useState(null)
  const [log, setLog] = useState(null)
  const [paper, setPaper] = useState(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [showLog, setShowLog] = useState(false)
  const [tab, setTab] = useState(() => { try { return localStorage.getItem('pf_tab') || 'overview' } catch { return 'overview' } })
  useEffect(() => { try { localStorage.setItem('pf_tab', tab) } catch { /* ignore */ } }, [tab])

  useEffect(() => {
    let alive = true
    setLoading(true)
    Promise.all([getPortfolioCandidate(), getPortfolioRuns(), getPortfolioPaper()]).then(([c, l, p]) => {
      if (!alive) return
      if (c.error) setError(c.error)
      setCand(c.data); setLog(l.data); setPaper(p.data); setLoading(false)
    })
    return () => { alive = false }
  }, [])

  const t = cand?.thresholds || log?.thresholds || { ann_active: 0.03, info_ratio: 0.5, dsr: 0.95, turnover_min: 3, turnover_max: 6 }
  const full = cand?.full
  const fm = full?.run?.metrics

  const tabs = [['overview', '總覽'], ['buy', '買多少股']]
  const tabBar = (
    <div className="btn-group" role="tablist" style={{ marginBottom: 12 }}>
      {tabs.map(([k, label]) => <button key={k} role="tab" aria-selected={tab === k} className={tab === k ? 'btn-primary' : 'btn-secondary'} onClick={() => setTab(k)}>{label}</button>)}
    </div>
  )

  if (tab === 'buy') {
    return (
      <>
        {tabBar}
        <div className="card">
          <div className="card-header">
            <span className="card-title">買多少股：把最近清單換算成股數</span>
            <span className="muted" style={{ fontSize: '.82rem' }}>清單訊號日 {cand?.current_list?.rebalance_date || '–'} · 收盤價 {cand?.current_list?.price_date || '–'}</span>
          </div>
          {loading && <div className="card-body muted">載入中…</div>}
          {error && <div className="card-body" style={{ color: 'var(--orange)' }}>{error}</div>}
          {!loading && !error && <BuyCalculator list={cand?.current_list} />}
        </div>
      </>
    )
  }

  return (
    <>
      {tabBar}
      <div className="card">
        <div className="card-header">
          <span className="card-title">打敗大盤：目前候選對門檻</span>
          <span className="muted" style={{ fontSize: '.82rem' }}>
            對手 0050 含息 · 實驗日誌 N = {cand?.n_total ?? log?.n_total ?? '–'} · 保留期（2024-10 起）{cand?.holdout_opened ? '已開' : '未開'}
          </span>
        </div>
        {loading && <div className="card-body muted">載入中…</div>}
        {error && <div className="card-body" style={{ color: 'var(--orange)' }}>{error}</div>}
        {!loading && !error && (
          <>
            <div className="card-body" style={{ paddingBottom: 0 }}>
              <RuleLine p={full?.run?.params || cand?.candidates?.[0]?.params} />
            </div>
            <CandidateTable rows={cand?.candidates} t={t} />
            <div className="card-header" style={{ borderTop: '1px solid rgba(128,128,128,0.2)' }}>
              <span className="card-title">現在該買哪些：最近一次訊號日的目標持股</span>
            </div>
            <CurrentList list={cand?.current_list} />
            <div className="card-body muted" style={{ fontSize: '0.8rem', lineHeight: 1.7 }}>
              三列是同一組參數：開發期（2018~2021）找到、驗證期（2022~2024-09）參數不動確認、全期間逐年檢視。
              年化主動報酬與資訊比率過了門檻，<strong>DSR 沒過</strong>：N 次嘗試後挑最好的，這個月 Sharpe 純靠運氣也挑得到（SR* 是「純運氣的最佳 Sharpe」）。
              要讓 DSR 過，只能用沒碰過的資料——紙上交易，與只能開一次的保留期。
            </div>
          </>
        )}
      </div>

      <div className="card">
        <div className="card-header">
          <span className="card-title">紙上交易（階段 4）：候選策略的模擬帳戶對 0050</span>
          <span className="muted" style={{ fontSize: '.82rem' }}>每月 11 日起第一個交易日收盤算清單 · 次一交易日開盤成交 · 每天結算</span>
        </div>
        <PaperCard paper={paper} />
      </div>

      {full && (
        <div className="two-col">
          <div className="card">
            <div className="card-header">
              <span className="card-title">淨值曲線：組合 vs 0050（{full.run.period_start} ~ {full.run.period_end}）</span>
              {fm && <span className="muted" style={{ fontSize: '.82rem' }}>年化 {pct(fm.cagr_port, 1)} 對 {pct(fm.cagr_bench, 1)} · 最大回撤 {pct(fm.mdd_port, 1)} 對 {pct(fm.mdd_bench, 1)}</span>}
            </div>
            <NavChart series={full.series} />
          </div>
          <div className="card">
            <div className="card-header"><span className="card-title">逐年主動報酬</span></div>
            <div className="card-body"><YearlyTable yearly={fm?.yearly_active} /></div>
          </div>
        </div>
      )}

      {full && (
        <div className="card">
          <div className="card-header"><span className="card-title">最後一次持股（回測期末）</span><span className="muted" style={{ fontSize: '.82rem' }}>台積電平均權重 {num(fm?.tsmc_weight_mean)}</span></div>
          <Positions positions={full.positions} last={full.last_rebalance} />
        </div>
      )}

      <div className="card">
        <div className="card-header">
          <span className="card-title">實驗日誌（每一次回測一列，N 只增不減）</span>
          <button className="btn-secondary" onClick={() => setShowLog(v => !v)}>{showLog ? '收起' : `展開 ${log?.n_total ?? ''} 次`}</button>
        </div>
        {showLog ? <RunLog runs={log?.runs} t={t} /> : <div className="card-body muted" style={{ fontSize: '0.8rem' }}>
          失敗的也在裡面——DSR 的 N 就是這張表的長度，刪掉失敗的 N 就是假的。★ 是候選。
        </div>}
      </div>

      <div className="card">
        <div className="card-header"><span className="card-title">怎麼讀這一頁</span></div>
        <div className="card-body" style={{ lineHeight: 1.8 }}>
          <p><strong>規則。</strong> 每月 11 日收盤後算訊號，次一交易日開盤以限價單成交；一字鎖漲跌停的單不成交；成本單邊手續費 0.0855%、賣出稅 0.3%、滑價 0.15%（小型股 0.3%）；股利用還原價含息再投入，與 0050 同一基準。</p>
          <p><strong>訊號。</strong> 「公告窗口反應」是當月 1 日到訊號日的累積異常報酬（市場對本月營收的反應），win3 是最近三個窗口相加；mom 是 12-1 個月動能；組合是兩者在候選池內的百分位排名平均。</p>
          <p><strong>轉折是持台積電。</strong> 不持台積電而對手是 0050（台積電佔一半），追蹤誤差 20%、相對落後 40%，等於在賭小型股對台積電；固定持有後八個設定全部轉正。0050 真實持股權重表還沒有，暫用滾動迴歸估（2018 約 0.38、近兩年 0.55）。</p>
        </div>
      </div>
    </>
  )
}
