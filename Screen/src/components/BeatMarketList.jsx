// 贏過大盤的回測清單（Iteration 76）
// ───────────────────────────────────────────────────────────────────────────
// 實驗日誌裡年化主動報酬 > 0（贏過 0050 含息）的每一次回測，照主動報酬排序列在月調倉頁最上面；
// 點一列展開那次回測每個訊號日買了哪些股票（GET /portfolio/runs/:id/positions——點開才抓、抓過就留著），
// 並畫淨值折線圖對比組合／0050 含息／大盤（Iteration 77：GET /portfolio/runs/:id 的 series，每 3 日一點；沒存曲線的舊回測只顯示說明）。
// 「贏過」只是對手輸了，不等於過門檻：年化主動 ≥ 3%、IR ≥ 0.5、DSR ≥ 0.95 三項另外標在每列。
// 作廢（tag = void，例如 0050 分割沒還原那次保留期）的不列，免得假的 +131% 排在第一；實驗日誌本身仍是全部。
import { Fragment, useState } from 'react'
import { getPortfolioRunPositions, getPortfolioRun } from '../services/api'
import NavRangeChart from './NavRangeChart'

function num(v, d = 2) { return v === null || v === undefined || Number.isNaN(Number(v)) ? '–' : Number(v).toFixed(d) }
function pct(v, d = 2) {
  if (v === null || v === undefined || Number.isNaN(Number(v))) return '–'
  const n = Number(v) * 100
  return `${n > 0 ? '+' : ''}${n.toFixed(d)}%`
}
function Sub({ children }) { return <div className="muted" style={{ fontSize: '0.72rem' }}>{children}</div> }

const SEG_ORDER = ['dev', 'valid', 'holdout', 'paper', 'live']
const TAG_LABEL = { candidate: '候選 ★', official: '正式', 'official-live': '正式 live', void: '作廢' }

/** 贏過大盤的列：年化主動報酬 > 0、不是作廢；主動報酬高的在前。 */
export function beaters(runs) {
  return (runs || [])
    .filter(r => r.tag !== 'void' && Number(r.metrics?.ann_active) > 0)
    .sort((a, b) => Number(b.metrics.ann_active) - Number(a.metrics.ann_active))
}

function gates(m, t) {
  const ann = Number(m.ann_active) >= t.ann_active
  const ir = m.info_ratio !== null && m.info_ratio !== undefined && Number(m.info_ratio) >= t.info_ratio
  const dsr = Number(m.dsr) >= t.dsr
  const passed = [ann, ir, dsr].filter(Boolean).length
  return { ann, ir, dsr, passed, all: passed === 3 }
}

function Chart({ r, detail }) {
  if (!r.has_series) return <div className="muted" style={{ fontSize: '.82rem', marginBottom: 8 }}>這次回測沒有存淨值曲線（早期只存指標；`portfolio_backtest.py --attach-series` 可補），下面只有持股。</div>
  if (!detail || detail.loading) return <div className="muted" style={{ fontSize: '.82rem', marginBottom: 8 }}>載入淨值曲線…</div>
  if (detail.error) return <div style={{ color: 'var(--orange)', fontSize: '.82rem', marginBottom: 8 }}>{detail.error}</div>
  const m = detail.run?.metrics || {}
  return (
    <div style={{ marginBottom: 10 }}>
      <div className="muted" style={{ fontSize: '.82rem' }}>
        淨值曲線：組合 vs 0050 含息 vs 大盤（{detail.run?.period_start} ~ {detail.run?.period_end}）· 年化 {pct(m.cagr_port, 1)} 對 0050 {pct(m.cagr_bench, 1)} · 最大回撤 {pct(m.mdd_port, 1)} 對 {pct(m.mdd_bench, 1)}
      </div>
      <NavRangeChart series={detail.series} periodStart={detail.run?.period_start} periodEnd={detail.run?.period_end} storageKey={`pf_beat_nav_${r.id}`} />
    </div>
  )
}

function Holdings({ data }) {
  const [date, setDate] = useState(null)
  const rebs = data.rebalances || []
  if (!rebs.length) return <div className="muted" style={{ fontSize: '.82rem' }}>這次回測沒有存持股紀錄</div>
  const cur = rebs.find(r => r.rebalance_date === date) || rebs[rebs.length - 1]
  const tsmc = cur.positions.find(p => p.stock_id === '2330' && (p.rank === null || p.rank === undefined))
  const picks = cur.positions.filter(p => p !== tsmc)
  return (
    <div>
      <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap', marginBottom: 8, fontSize: '.82rem' }}>
        <span className="muted">共 {data.n_rebalances} 次調倉、曾持有 {data.n_stocks} 檔。訊號日</span>
        <select className="ctrl-select" value={cur.rebalance_date} onChange={e => setDate(e.target.value)}>
          {rebs.map(r => <option key={r.rebalance_date} value={r.rebalance_date}>{r.rebalance_date}</option>)}
        </select>
        <span className="muted">{cur.exec_date ? `${cur.exec_date} 開盤成交 · ` : ''}{cur.positions.length} 檔</span>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))', gap: 6 }}>
        {tsmc ? (
          <div className="stat-tile" title="台積電不參與排名，固定持 0050 的台積電權重">
            <div className="k">固定</div>
            <div className="v">2330 {tsmc.stock_name || ''}</div>
            <div className="s">{pct(tsmc.target_weight, 1).replace('+', '')}</div>
          </div>
        ) : null}
        {picks.map(p => (
          <div key={p.stock_id} className="stat-tile" style={p.filled ? undefined : { opacity: 0.55 }}
            title={p.filled ? `訊號值 ${p.signal_value === null || p.signal_value === undefined ? '–' : num(p.signal_value, 3)}` : '成交日一字鎖漲跌停，視為未成交'}>
            <div className="k">{p.rank === null || p.rank === undefined ? '續抱' : `#${p.rank}`}{p.filled ? '' : <span className="down"> 未成交</span>}</div>
            <div className="v">{p.stock_id} {p.stock_name || ''}</div>
            <div className="s">{pct(p.target_weight, 1).replace('+', '')}</div>
          </div>
        ))}
      </div>
      {data.frequent?.length ? (
        <Sub>最常買到（次數 / {data.n_rebalances} 次調倉）：{data.frequent.slice(0, 10).map(f => `${f.stock_id} ${f.stock_name || ''} ×${f.times}`).join('、')}</Sub>
      ) : null}
    </div>
  )
}

export default function BeatMarketList({ runs, t }) {
  const [seg, setSeg] = useState('all')
  const [onlyPass, setOnlyPass] = useState(false)
  const [open, setOpen] = useState(null)      // 展開的 run id
  const [cache, setCache] = useState({})      // run id → /positions 回應（loading／error／資料）
  const [detail, setDetail] = useState({})    // run id → /runs/:id 回應（淨值曲線；沒存曲線的不抓）
  const all = beaters(runs)
  const segs = SEG_ORDER.filter(s => all.some(r => r.segment === s))
  const segLabel = s => all.find(r => r.segment === s)?.segment_label || s
  const rows = all.filter(r => (seg === 'all' || r.segment === seg) && (!onlyPass || gates(r.metrics || {}, t).all))

  const toggle = (r) => {
    const next = open === r.id ? null : r.id
    setOpen(next)
    if (next && !cache[next]) {
      setCache(c => ({ ...c, [next]: { loading: true } }))
      getPortfolioRunPositions(next).then(res => setCache(c => ({ ...c, [next]: res.error ? { error: res.error } : res.data })))
    }
    if (next && r.has_series && !detail[next]) {
      setDetail(d => ({ ...d, [next]: { loading: true } }))
      getPortfolioRun(next, 3).then(res => setDetail(d => ({ ...d, [next]: res.error ? { error: res.error } : res.data })))
    }
  }

  if (!all.length) return <div className="card-body muted">實驗日誌裡還沒有贏過大盤的回測</div>
  return (
    <>
      <div className="card-body" style={{ paddingBottom: 8, display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
        <div className="btn-group">
          <button className={seg === 'all' ? 'btn-primary' : 'btn-filter'} onClick={() => setSeg('all')}>全部 {all.length}</button>
          {segs.map(s => <button key={s} className={seg === s ? 'btn-primary' : 'btn-filter'} onClick={() => setSeg(s)}>{segLabel(s)} {all.filter(r => r.segment === s).length}</button>)}
        </div>
        <label className="muted" style={{ fontSize: '.82rem', display: 'flex', gap: 4, alignItems: 'center', cursor: 'pointer' }}>
          <input type="checkbox" checked={onlyPass} onChange={e => setOnlyPass(e.target.checked)} /> 只看三項門檻都過的
        </label>
        <Sub>贏過 = 年化主動報酬 &gt; 0（對手 0050 含息）；同一組參數在開發期、驗證期各是一列。點一列展開：淨值折線圖（組合／0050／大盤）與每個訊號日買了什麼。</Sub>
      </div>
      <div style={{ overflowX: 'auto', maxHeight: 560, overflowY: 'auto' }}>
        <table className="data-table" style={{ fontSize: '.84rem' }}>
          <thead>
            <tr>
              <th style={{ width: 18 }}></th><th>N</th><th>設定</th><th>段</th><th>期間</th>
              <th style={{ textAlign: 'right' }}>年化主動<Sub>門檻 ≥ {pct(t.ann_active, 0)}</Sub></th>
              <th style={{ textAlign: 'right' }}>IR<Sub>≥ {t.info_ratio}</Sub></th>
              <th style={{ textAlign: 'right' }}>DSR<Sub>≥ {t.dsr}</Sub></th>
              <th>門檻</th>
              <th style={{ textAlign: 'right' }}>換手</th>
              <th style={{ textAlign: 'right' }}>組合 / 0050</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? <tr><td colSpan={11} className="muted">這個篩選下沒有列</td></tr> : null}
            {rows.map(r => {
              const m = r.metrics || {}
              const g = gates(m, t)
              const isOpen = open === r.id
              const d = cache[r.id]
              const missing = [g.ann ? '' : '主動', g.ir ? '' : 'IR', g.dsr ? '' : 'DSR'].filter(Boolean)
              return (
                <Fragment key={r.id}>
                  <tr onClick={() => toggle(r)} aria-expanded={isOpen}
                    style={{ cursor: 'pointer', background: r.tag === 'candidate' ? 'rgba(47,128,237,0.08)' : isOpen ? 'rgba(128,128,128,0.06)' : undefined }}>
                    <td className="muted">{isOpen ? '▾' : '▸'}</td>
                    <td>{r.experiment_n}{r.tag ? <Sub>{TAG_LABEL[r.tag] || r.tag}</Sub> : null}</td>
                    <td style={{ whiteSpace: 'nowrap' }}>{r.name}</td>
                    <td>{r.segment_label}</td>
                    <td style={{ whiteSpace: 'nowrap' }}><Sub>{r.period_start} ~ {r.period_end}</Sub></td>
                    <td style={{ textAlign: 'right' }}><strong className="up">{pct(m.ann_active)}</strong></td>
                    <td style={{ textAlign: 'right' }}><span className={g.ir ? 'up' : ''}>{num(m.info_ratio)}</span></td>
                    <td style={{ textAlign: 'right' }}><span className={g.dsr ? 'up' : ''}>{num(m.dsr, 2)}</span></td>
                    <td style={{ whiteSpace: 'nowrap' }}>
                      {g.all ? <span className="up">3/3</span> : <span className={g.passed ? '' : 'down'}>{g.passed}/3</span>}
                      <Sub>{missing.length ? `沒過：${missing.join('、')}` : '全過'}</Sub>
                    </td>
                    <td style={{ textAlign: 'right' }}>{num(m.turnover_annual, 1)}</td>
                    <td style={{ textAlign: 'right', whiteSpace: 'nowrap' }}>{pct(m.cagr_port, 1)} / {pct(m.cagr_bench, 1)}</td>
                  </tr>
                  {isOpen ? (
                    <tr>
                      <td colSpan={11} style={{ background: 'rgba(128,128,128,0.06)', padding: '10px 14px' }}>
                        <Chart r={r} detail={detail[r.id]} />
                        {!d || d.loading ? <span className="muted">載入持股…</span>
                          : d.error ? <span style={{ color: 'var(--orange)' }}>{d.error}</span>
                          : <Holdings data={d} />}
                      </td>
                    </tr>
                  ) : null}
                </Fragment>
              )
            })}
          </tbody>
        </table>
      </div>
    </>
  )
}
