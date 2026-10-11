// 正式策略（Iteration 64）
// ───────────────────────────────────────────────────────────────────────────
// 候選 #44 升格後的頁面：三段指標（開發期、驗證期、保留期——保留期只開一次、凍結）、全期間至今的淨值曲線
// （live 列，每天 18:50 用同參數重算到最新行情）、逐年主動報酬、本月清單、紙上帳戶摘要。
// 資料來自 GET /portfolio/official（匿名可讀）；admin 可按「立刻更新」跑一次每日更新。
import { useCallback, useEffect, useState } from 'react'
import { getPortfolioOfficial, updatePortfolioOfficial } from '../services/api'
import NavRangeChart from '../components/NavRangeChart'
import { isAdmin } from '../services/auth'

const pct = (v, d = 2) => (v == null || Number.isNaN(Number(v)) ? '–' : `${Number(v) > 0 ? '+' : ''}${(Number(v) * 100).toFixed(d)}%`)
const num = (v, d = 2) => (v == null ? '–' : Number(v).toFixed(d))
const tone = v => (v == null ? 'muted' : Number(v) > 0 ? 'up' : Number(v) < 0 ? 'down' : 'muted')
function Sub({ children }) { return <div className="muted" style={{ fontSize: '0.74rem' }}>{children}</div> }
function Empty({ children }) { return <div className="muted" style={{ padding: '1rem 1.25rem', fontSize: '.88rem' }}>{children}</div> }
const SEG_LABEL = { dev: '開發期', valid: '驗證期', full: '開發＋驗證', holdout: '保留期（只開一次）', live: '全期間至今（每日更新）' }
const SEG_ORDER = ['dev', 'valid', 'full', 'holdout', 'live']

function SegmentTable({ segments, thresholds }) {
  const keys = SEG_ORDER.filter(k => segments[k])
  if (!keys.length) return <Empty>沒有指標。</Empty>
  return (
    <div style={{ overflowX: 'auto' }}>
      <table className="data-table">
        <thead><tr><th>期間</th><th className="num">年化主動<Sub>門檻 ≥ {pct(thresholds?.ann_active, 0)}</Sub></th><th className="num">資訊比率<Sub>≥ {thresholds?.info_ratio}</Sub></th><th className="num">組合年化</th><th className="num">0050 年化</th><th className="num">追蹤誤差</th><th className="num">相對最大落後</th><th className="num">月勝率</th><th className="num">年換手</th><th className="num">實驗 #</th></tr></thead>
        <tbody>{keys.map(k => { const s = segments[k]; const m = s.metrics || {}; return (
          <tr key={k} style={{ background: k === 'live' ? 'var(--blue-soft)' : undefined }}>
            <td style={{ whiteSpace: 'nowrap' }}><strong>{SEG_LABEL[k]}</strong><Sub>{s.period_start} ～ {s.period_end}{m.months ? ` · ${m.months} 個月` : ''}</Sub></td>
            <td className="num"><strong className={tone(m.ann_active)}>{pct(m.ann_active)}</strong></td>
            <td className="num">{num(m.info_ratio)}</td>
            <td className="num">{pct(m.cagr_port, 1)}</td><td className="num">{pct(m.cagr_bench, 1)}</td>
            <td className="num">{m.tracking_error != null ? `${(m.tracking_error * 100).toFixed(1)}%` : '–'}</td>
            <td className="num"><span className="down">{pct(m.rel_mdd, 1)}</span></td>
            <td className="num">{m.monthly_win_rate != null ? `${(m.monthly_win_rate * 100).toFixed(0)}%` : '–'}</td>
            <td className="num">{num(m.turnover_annual, 1)}</td>
            <td className="num muted">#{s.experiment_n}</td>
          </tr>) })}</tbody>
      </table>
    </div>
  )
}

function YearlyTable({ yearly }) {
  const ys = Object.keys(yearly || {}).sort()
  if (!ys.length) return <Empty>–</Empty>
  return (
    <table className="data-table" style={{ maxWidth: 360 }}>
      <thead><tr><th>年</th><th className="num">主動報酬</th></tr></thead>
      <tbody>{ys.map(y => <tr key={y}><td>{y}</td><td className="num"><span className={tone(yearly[y])}>{pct(yearly[y])}</span></td></tr>)}</tbody>
    </table>
  )
}

function CurrentList({ list }) {
  if (!list?.items?.length) return <Empty>還沒有本月清單。</Empty>
  const tsmc = list.items.find(i => i.stock_id === '2330')
  const picks = list.items.filter(i => i.stock_id !== '2330')
  return (
    <div style={{ padding: '.5rem 1.25rem 1rem' }}>
      <Sub>訊號日 {list.rebalance_date} 收盤算，{list.exec_date || '次一交易日'} 開盤成交；{list.items.length} 檔。{tsmc ? `台積電固定 ${(tsmc.target_weight * 100).toFixed(1)}%，` : ''}其餘各 {picks[0] ? (picks[0].target_weight * 100).toFixed(1) : '–'}%。★ 本月新進。</Sub>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))', gap: 8, marginTop: 8 }}>
        {tsmc ? <div className="stat-tile"><div className="k">固定</div><div className="v">{tsmc.stock_id} {tsmc.stock_name || ''}</div><div className="s">{(tsmc.target_weight * 100).toFixed(1)}%</div></div> : null}
        {picks.map(p => <div key={p.stock_id} className="stat-tile"><div className="k">{p.rank == null ? '續抱' : `#${p.rank}`}{p.is_new ? <span className="up"> ★</span> : null}</div><div className="v">{p.stock_id}</div><div className="s">{p.stock_name || ''}{p.price ? ` · ${p.price}` : ''}</div></div>)}
      </div>
    </div>
  )
}

export default function OfficialStrategy() {
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')
  const load = useCallback(async () => {
    const { data, error } = await getPortfolioOfficial()
    if (error) setError(error); else { setData(data); setError('') }
  }, [])
  useEffect(() => { load() }, [load])
  async function runUpdate() {
    setBusy(true); setMsg('')
    const { data: r, error } = await updatePortfolioOfficial()
    setBusy(false)
    setMsg(error ? `更新失敗：${error}` : r?.skipped ? `略過：${r.skipped}` : `已更新到 ${r.end}（${r.points} 點、年化主動 ${pct(r.ann_active)}）`)
    load()
  }
  if (error) return <div className="alert-card alert-error"><div className="alert-icon">⚠</div><div className="alert-body"><div className="alert-title">讀不到正式策略</div><div className="alert-sub">{error}</div></div></div>
  if (!data) return <div className="empty-state"><div className="empty-icon">⏳</div>載入中…</div>
  if (!data.promoted) return <div className="empty-state"><div className="empty-icon">🏁</div>還沒有正式策略。<Sub>候選升格：python portfolio_official.py --promote 44 --note 理由（保留期只能開一次）</Sub></div>

  const o = data.official; const seg = data.segments || {}; const live = seg.live; const p = data.params || {}
  const paper = data.paper?.review
  return (
    <>
      <div className="card" style={{ marginBottom: '1.1rem' }}>
        <div className="card-header">
          <div>
            <div className="card-title">正式策略：{live?.name?.replace('-live', '') || `候選 #${o.candidate_run_id}`}</div>
            <Sub>{o.promoted_on} 升格（候選 #{o.candidate_run_id}）· 訊號 {p.signal} · 流動性前 {p.universe_n} · 前 {p.top_n} 檔{p.tranches > 1 ? `分 ${p.tranches} 批輪動` : ''} · 台積電固定持 0050 權重（{p.tsmc_weight === 'est' ? '滾動迴歸估' : p.tsmc_weight}）· 每月 11 日起第一個交易日調倉</Sub>
          </div>
          <div style={{ display: 'flex', gap: '.5rem', alignItems: 'center' }}>
            <Sub>淨值最後更新 {o.last_update_at ? new Date(o.last_update_at).toLocaleString('zh-TW', { hour12: false }) : '–'} · 行情到 {o.last_update_end || '–'}{o.last_error ? <span className="down">（錯誤：{o.last_error}）</span> : ''}</Sub>
            {isAdmin() ? <button className="btn-secondary" disabled={busy} onClick={runUpdate}>{busy ? '更新中…' : '立刻更新'}</button> : null}
            {msg ? <Sub>{msg}</Sub> : null}
          </div>
        </div>
        <div className="stat-grid">
          {['full', 'holdout', 'live'].filter(k => seg[k]).map(k => { const m = seg[k].metrics || {}; return (
            <div className="stat-tile" key={k}><div className="k">{SEG_LABEL[k]}</div><div className="v"><span className={tone(m.ann_active)}>{pct(m.ann_active)}</span></div><div className="s">年化主動 · IR {num(m.info_ratio)} · {seg[k].period_start} ～ {seg[k].period_end}</div></div>) })}
          <div className="stat-tile"><div className="k">紙上帳戶（實際執行）</div><div className="v">{paper?.days ? <span className={tone(paper.active_return)}>{pct(paper.active_return)}</span> : '–'}</div><div className="s">{paper?.days ? `對 0050，${paper.days} 個交易日` : data.paper?.opened ? '已開戶，等第一份清單成交' : '未開戶'}</div></div>
        </div>
        <div className="note-box">保留期（2024-10 起）只開這一次，數字凍結、不再重跑；「全期間至今」是同一組參數每天收盤後重算到最新行情，會隨新資料變。紙上帳戶是引擎真的照清單執行的結果，和回測曲線不是同一條線。</div>
      </div>

      <div className="card" style={{ marginBottom: '1.1rem' }}>
        <div className="card-header"><span className="card-title">淨值曲線：組合 vs 0050（{live?.period_start} ~ {live?.period_end}，每日更新）</span>{live?.metrics ? <span className="muted" style={{ fontSize: '.82rem' }}>年化 {pct(live.metrics.cagr_port, 1)} 對 {pct(live.metrics.cagr_bench, 1)} · 最大回撤 {pct(live.metrics.mdd_port, 1)} 對 {pct(live.metrics.mdd_bench, 1)}</span> : null}</div>
        <NavRangeChart series={data.live_series} periodStart={live?.period_start} periodEnd={live?.period_end} extraPresets={[['保留期', '2024-10-01', live?.period_end]]} />
      </div>

      <div className="card" style={{ marginBottom: '1.1rem' }}>
        <div className="card-header"><span className="card-title">三段指標</span><Sub>開發期與驗證期是候選階段的紀錄；保留期是升格時開的那一次；全期間至今每日重算</Sub></div>
        <SegmentTable segments={seg} thresholds={data.thresholds} />
      </div>

      <div className="two-col" style={{ marginBottom: '1.1rem' }}>
        <div className="card"><div className="card-header"><span className="card-title">逐年主動報酬（全期間至今）</span></div><div style={{ padding: '.5rem 1.25rem 1rem' }}><YearlyTable yearly={live?.metrics?.yearly_active} /></div></div>
        <div className="card"><div className="card-header"><span className="card-title">本月清單</span><Sub>引擎照這份下單</Sub></div><CurrentList list={data.current_list} /></div>
      </div>
    </>
  )
}
