// 投票決策儀表板
import { useState, useEffect, useRef } from 'react'
import { getVotingResults, triggerVoting, getVotingStatus,
         getGapPrediction, getWeeklyRange,
         getWeeklyPlan, getHoldings } from '../services/api'
import { Shares } from '../components/Shares'
import ModelPicker from '../components/ModelPicker'

const SIGNAL_META = {
  // 買賣與漲跌一律台股慣例：買進／看多＝紅，賣出／看空＝綠
  Buy:  { label: '買入', color: 'var(--up)',   bg: 'var(--up-soft)',   icon: '▲' },
  Sell: { label: '賣出', color: 'var(--down)', bg: 'var(--down-soft)', icon: '▼' },
  Hold: { label: '持有', color: 'var(--dim)',     bg: 'var(--dim-soft)', icon: '─' },
}

function SignalBadge({ signal }) {
  const m = SIGNAL_META[signal] || SIGNAL_META.Hold
  return (
    <span style={{
      display: 'inline-block', padding: '2px 10px', borderRadius: 12,
      fontSize: '0.75rem', fontWeight: 600,
      background: m.bg, color: m.color,
    }}>{m.icon} {m.label}</span>
  )
}

function ScoreBar({ score }) {
  const pct = Math.round(Math.abs(score) * 100)
  // 分數為正＝偏多，用紅色（台股慣例）
  const color = score >= 0.3 ? 'var(--up)' : score <= -0.3 ? 'var(--down)' : 'var(--dim)'
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6, minWidth: 100 }}>
      <div style={{ flex: 1, height: 6, borderRadius: 3, background: 'var(--border)', overflow: 'hidden' }}>
        <div style={{ width: `${pct}%`, height: '100%', background: color, borderRadius: 3, transition: 'width .3s' }} />
      </div>
      <span style={{ fontSize: '0.6875rem', color, minWidth: 32, textAlign: 'right' }}>
        {score >= 0 ? '+' : ''}{score?.toFixed ? score.toFixed(2) : score}
      </span>
    </div>
  )
}

// 波動區間標籤。風險欄位不參與投票計分，只回答「該押多少、停損放哪」。
const REGIME_META = {
  低: { bg: 'var(--green-soft)',  color: 'var(--green)' },
  中: { bg: 'var(--yellow-soft)',  color: 'var(--yellow)' },
  高: { bg: 'var(--red-soft)',  color: 'var(--red)' },
}

function RegimeBadge({ regime, vol }) {
  if (!regime) return <span style={{ color: 'var(--dim)', fontSize: '0.75rem' }}>—</span>
  const m = REGIME_META[regime] || REGIME_META['中']
  return (
    <span
      title={vol != null ? `預測日波動率 ${(Number(vol) * 100).toFixed(2)}%` : ''}
      style={{
        display: 'inline-block', padding: '2px 10px', borderRadius: 10,
        fontSize: '0.75rem', fontWeight: 600, background: m.bg, color: m.color,
      }}
    >
      {regime}{vol != null ? ` ${(Number(vol) * 100).toFixed(1)}%` : ''}
    </span>
  )
}

// 開盤跳空預測面板。這是**盤前參考資訊，不是買賣訊號**——
// 跳空發生在開盤瞬間，事後無法交易；它能被預測是因為美股隔夜與台股開盤跳空
// 相關高達 +0.66，而這也正是它對「收盤到收盤」漲跌預測毫無幫助的原因。
function GapPanel({ gap }) {
  const [open, setOpen] = useState(false)
  const preds = gap.predictions || []
  if (!preds.length) return null

  const shown = open ? preds : [...preds.slice(0, 3), ...preds.slice(-3)]
  const color = v => (v > 0.1 ? 'var(--red)' : v < -0.1 ? 'var(--green)' : 'var(--dim)')

  return (
    <div style={{
      margin: '0 0 16px', padding: '14px 18px', borderRadius: 10,
      border: '1px solid var(--border)', background: 'var(--surface)',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10,
                    flexWrap: 'wrap', marginBottom: 10 }}>
        <span style={{ fontWeight: 700, fontSize: '0.875rem' }}>明日開盤跳空預估</span>
        <span style={{ fontSize: '0.6875rem', color: 'var(--dim)' }}>
          依 {gap.us_date} 美股收盤　／　台股最新 {gap.tw_last_date}
        </span>
        <span style={{
          fontSize: '0.6875rem', padding: '2px 8px', borderRadius: 8,
          background: 'var(--yellow-soft)', color: 'var(--yellow)',
        }}>參考資訊，非買賣訊號</span>
        <button
          onClick={() => setOpen(o => !o)}
          style={{
            marginLeft: 'auto', fontSize: '0.75rem', padding: '3px 10px',
            borderRadius: 6, cursor: 'pointer',
            border: '1px solid var(--border)', background: 'var(--bg)',
            color: 'var(--text)',
          }}
        >{open ? '收合' : `全部 ${preds.length} 檔`}</button>
      </div>

      <div style={{ display: 'grid',
                    gridTemplateColumns: 'repeat(auto-fill, minmax(148px, 1fr))',
                    gap: 8 }}>
        {shown.map(p => (
          <div key={p.stock_id} style={{
            padding: '8px 10px', borderRadius: 8,
            border: '1px solid var(--border)', background: 'var(--bg)',
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between',
                          alignItems: 'baseline' }}>
              <span style={{ fontWeight: 700, fontSize: '0.8125rem' }}>{p.stock_id}</span>
              <span style={{ fontWeight: 700, fontSize: '0.875rem',
                             color: color(p.gap_pct) }}>
                {p.gap_pct > 0 ? '+' : ''}{p.gap_pct.toFixed(2)}%
              </span>
            </div>
            <div style={{ fontSize: '0.6875rem', color: 'var(--dim)', marginTop: 3 }}>
              {p.last_close} → {p.implied_open}
            </div>
          </div>
        ))}
      </div>

      <div style={{ fontSize: '0.6875rem', color: 'var(--dim)', marginTop: 10,
                    lineHeight: 1.6 }}>
        {gap.model_note}
      </div>
    </div>
  )
}

// 週振幅預測面板：挑出未來一週高低點差距顯著偏大的股票（波段選股用）。
// 「顯著」同時要求：預測振幅 ≥ 自身歷史中位數 1.15 倍，且同儕排名前 30%。
// **振幅大不代表會漲**——方向仍不可預測，此面板只回答「會不會震」。
function RangePanel({ range }) {
  const [showAll, setShowAll] = useState(false)
  const rows = range.results || []
  if (!rows.length) return null

  const sig = rows.filter(r => r.is_significant)
  const shown = showAll ? rows : (sig.length ? sig : rows.slice(0, 5))

  return (
    <div style={{
      margin: '0 0 16px', padding: '14px 18px', borderRadius: 10,
      border: '1px solid var(--border)', background: 'var(--surface)',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10,
                    flexWrap: 'wrap', marginBottom: 10 }}>
        <span style={{ fontWeight: 700, fontSize: '0.875rem' }}>
          未來一週振幅預估
        </span>
        <span style={{ fontSize: '0.6875rem', color: 'var(--dim)' }}>
          基準日 {range.as_of}　／　{range.horizon_days} 個交易日
        </span>
        <span style={{
          fontSize: '0.6875rem', padding: '2px 8px', borderRadius: 8,
          background: sig.length ? 'var(--red-soft)' : 'var(--dim-soft)',
          color: sig.length ? 'var(--red)' : 'var(--dim)',
        }}>
          顯著偏大 {range.n_significant} 檔
        </span>
        <button
          onClick={() => setShowAll(s => !s)}
          style={{
            marginLeft: 'auto', fontSize: '0.75rem', padding: '3px 10px',
            borderRadius: 6, cursor: 'pointer',
            border: '1px solid var(--border)', background: 'var(--bg)',
            color: 'var(--text)',
          }}
        >{showAll ? '只看顯著' : `全部 ${rows.length} 檔`}</button>
      </div>

      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.75rem' }}>
          <thead>
            <tr style={{ color: 'var(--dim)', fontSize: '0.6875rem' }}>
              {['股票', '預測振幅', '自身歷史', '倍數', '同儕', '預期區間'].map(h => (
                <th key={h} style={{ padding: '4px 8px', textAlign: 'left',
                                     fontWeight: 600 }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {shown.map(r => (
              <tr key={r.stock_id} style={{ borderTop: '1px solid var(--border)' }}>
                <td style={{ padding: '5px 8px', fontWeight: 700 }}>
                  {r.is_significant && <span style={{ color: 'var(--red)' }}>★ </span>}
                  {r.stock_id}
                </td>
                <td style={{ padding: '5px 8px', fontWeight: 700,
                             color: r.is_significant ? 'var(--red)' : 'var(--text)' }}>
                  {r.range_pct.toFixed(2)}%
                </td>
                <td style={{ padding: '5px 8px', color: 'var(--dim)' }}>
                  {r.hist_median_pct != null ? `${r.hist_median_pct.toFixed(2)}%` : '—'}
                </td>
                <td style={{ padding: '5px 8px',
                             color: (r.self_ratio ?? 0) >= 1.15 ? 'var(--red)' : 'var(--dim)' }}>
                  {r.self_ratio != null ? `${r.self_ratio.toFixed(2)}×` : '—'}
                </td>
                <td style={{ padding: '5px 8px', color: 'var(--dim)' }}>
                  前 {(100 - r.peer_pct).toFixed(0)}%
                </td>
                <td style={{ padding: '5px 8px', fontFamily: 'monospace',
                             color: 'var(--dim)' }}>
                  {r.expected_low} ~ {r.expected_high}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div style={{ fontSize: '0.6875rem', color: 'var(--dim)', marginTop: 10,
                    lineHeight: 1.6 }}>
        判定：{range.criteria}。{range.model_note}
      </div>
    </div>
  )
}

// ── 角色化決策（Iteration 22）────────────────────────────────────────────────
// 每個角色都標註它所依據的模型有沒有走查證據。這不是裝飾——
// 「消息面說買」和「風險控管說別買」的分量本來就不該一樣，
// 使用者有權當場看出哪個意見有實測支撐。
const CREDIBILITY_META = {
  proven:      { label: '走查驗證', color: 'var(--green)', bg: 'var(--green-soft)' },
  weak:        { label: '證據薄弱', color: 'var(--yellow)', bg: 'var(--yellow-soft)' },
  unvalidated: { label: '未經驗證', color: 'var(--yellow)', bg: 'var(--yellow-soft)' },
  none:        { label: '實測無效', color: 'var(--red)', bg: 'var(--red-soft)' },
  rule:        { label: '不依賴模型', color: 'var(--blue)', bg: 'var(--blue-soft)' },
}

const KIND_META = {
  direction:  { label: '投票', hint: '有投票權，決定買賣方向' },
  gate:       { label: '否決', hint: '不投方向，只決定要不要出手與押多少' },
  discipline: { label: '覆蓋', hint: '不做預測，執行停損停利紀律，優先於前兩者' },
}

const ACTION_META = {
  Buy:    { label: '買進',   color: 'var(--up)',   bg: 'var(--up-soft)' },
  Sell:   { label: '賣出',   color: 'var(--down)', bg: 'var(--down-soft)' },
  Hold:   { label: '不動',   color: 'var(--dim)',   bg: 'var(--dim-soft)' },
  Reduce: { label: '減碼',   color: 'var(--orange)',      bg: 'var(--yellow-soft)' },
  NoAdd:  { label: '不加碼', color: 'var(--orange)',      bg: 'var(--yellow-soft)' },
}

function RolePanel({ roles, path, action, target, holding }) {
  if (!roles?.length) return null
  const act = ACTION_META[action] || ACTION_META.Hold
  return (
    <div style={{ padding: '0 24px 14px' }}>
      <div style={{ padding: '12px 14px', borderRadius: 8,
                    border: '1px solid var(--border)', background: 'var(--bg)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10,
                      flexWrap: 'wrap', marginBottom: 10 }}>
          <span style={{ fontWeight: 700, fontSize: '0.8125rem' }}>角色決策</span>
          <span style={{ padding: '3px 12px', borderRadius: 12, fontWeight: 700,
                         fontSize: '0.8125rem', background: act.bg, color: act.color }}>
            最終：{act.label}
          </span>
          {target != null && (
            <span style={{ fontSize: '0.75rem', color: 'var(--dim)' }}>
              目標部位 {Number(target).toFixed(0)}%
            </span>
          )}
          {holding && (
            <span style={{ fontSize: '0.75rem', color: 'var(--dim)' }}>
              目前持有 {Number(holding.shares).toFixed(0)} 股 · 成本 {Number(holding.avg_cost).toFixed(2)}
            </span>
          )}
        </div>

        <div style={{ display: 'grid',
                      gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: 10 }}>
          {roles.map(r => {
            const c = CREDIBILITY_META[r.credibility] || CREDIBILITY_META.unvalidated
            const k = KIND_META[r.kind] || KIND_META.direction
            return (
              <div key={r.key} style={{ padding: '10px 12px', borderRadius: 8,
                                        border: '1px solid var(--border)',
                                        background: 'var(--surface)' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6,
                              marginBottom: 6, flexWrap: 'wrap' }}>
                  <span style={{ fontSize: '0.875rem' }}>{r.icon}</span>
                  <span style={{ fontWeight: 700, fontSize: '0.75rem' }}>{r.name}</span>
                  <span title={k.hint} style={{ fontSize: '0.625rem', padding: '1px 6px',
                        borderRadius: 6, background: 'var(--dim-soft)',
                        color: 'var(--dim)' }}>{k.label}</span>
                  <span title={r.credibility_note} style={{ fontSize: '0.625rem', padding: '1px 6px',
                        borderRadius: 6, background: c.bg, color: c.color, cursor: 'help' }}>
                    {c.label}
                  </span>
                  {r.weight > 0 && (
                    <span style={{ fontSize: '0.625rem', color: 'var(--dim)' }}>權重 {r.weight}</span>
                  )}
                </div>
                {r.kind === 'direction' && (
                  <div style={{ marginBottom: 5 }}><SignalBadge signal={r.signal} /></div>
                )}
                <div style={{ fontSize: '0.6875rem', color: 'var(--text)', lineHeight: 1.6 }}>
                  {r.reason || '—'}
                </div>
                <div style={{ fontSize: '0.625rem', color: 'var(--dim)', lineHeight: 1.6,
                              marginTop: 6, borderTop: '1px dashed var(--border)',
                              paddingTop: 5 }}>
                  依據：{r.basis}。{r.credibility_note}
                </div>
              </div>
            )
          })}
        </div>

        {path?.length > 0 && (
          <div style={{ marginTop: 10, padding: '8px 12px', borderRadius: 6,
                        background: 'var(--surface)', border: '1px dashed var(--border)' }}>
            <div style={{ fontSize: '0.6875rem', color: 'var(--dim)', marginBottom: 4 }}>
              決策過程（為什麼最後是這個動作）
            </div>
            {path.map((t, i) => (
              <div key={i} style={{ fontSize: '0.6875rem', color: 'var(--text)', lineHeight: 1.7 }}>
                {i + 1}. {t}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

// ── 本週 5 日計畫 ────────────────────────────────────────────────────────────
// 策略未通過走查時 deployed=false，這裡會把「它輸給買進持有」直接寫在最上面。
// 把沒通過驗證的策略包裝成建議是不誠實的。
const PLAN_ACTION = {
  Flat:   { label: '空手', color: 'var(--dim)',   bg: 'var(--dim-soft)' },
  Buy:    { label: '買進', color: 'var(--up)',   bg: 'var(--up-soft)' },
  Hold:   { label: '續抱', color: 'var(--blue)',      bg: 'var(--blue-soft)' },
  Sell:   { label: '賣出', color: 'var(--down)', bg: 'var(--down-soft)' },
  Manage: { label: '管理', color: 'var(--orange)',      bg: 'var(--yellow-soft)' },
}

function WeeklyPlanPanel({ stockId }) {
  const [plan, setPlan] = useState(null)
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState('')

  useEffect(() => {
    let alive = true
    setLoading(true); setErr('')
    getWeeklyPlan(stockId).then(({ data, error }) => {
      if (!alive) return
      if (error) setErr(error)
      else setPlan(data)
      setLoading(false)
    })
    return () => { alive = false }
  }, [stockId])

  if (loading) return <div style={{ padding: '0 24px 14px', fontSize: '0.75rem', color: 'var(--dim)' }}>本週計畫載入中…</div>
  if (err) return <div style={{ padding: '0 24px 14px', fontSize: '0.75rem', color: 'var(--red)' }}>本週計畫：{err}</div>
  if (!plan?.available) {
    return (
      <div style={{ padding: '0 24px 14px', fontSize: '0.75rem', color: 'var(--dim)' }}>
        本週計畫不可用：{plan?.reason ?? '未知原因'}
      </div>
    )
  }

  return (
    <div style={{ padding: '0 24px 16px' }}>
      <div style={{ padding: '12px 14px', borderRadius: 8,
                    border: `1px solid ${plan.deployed ? 'var(--border)' : 'var(--red)'}`,
                    background: 'var(--bg)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10,
                      flexWrap: 'wrap', marginBottom: 8 }}>
          <span style={{ fontWeight: 700, fontSize: '0.8125rem' }}>本週交易計畫</span>
          <span style={{ fontSize: '0.6875rem', color: 'var(--dim)' }}>{plan.week_start} 那一週</span>
          <span style={{ fontSize: '0.6875rem', padding: '2px 8px', borderRadius: 8,
                         background: plan.deployed ? 'var(--green-soft)' : 'rgba(248,81,73,.15)',
                         color: plan.deployed ? 'var(--green)' : 'var(--red)' }}>
            {plan.deployed ? '已通過走查' : '未通過走查 · 僅供參考'}
          </span>
        </div>

        {!plan.deployed && (
          <div style={{ fontSize: '0.6875rem', color: 'var(--red)', lineHeight: 1.7,
                        marginBottom: 10, padding: '8px 10px', borderRadius: 6,
                        background: 'var(--red-soft)' }}>
            {String(plan.status_note).split('**').join('')}
          </div>
        )}

        <div style={{ fontSize: '0.75rem', color: 'var(--text)', lineHeight: 1.6, marginBottom: 10 }}>
          {plan.summary}
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 8 }}>
          {plan.days.map(d => {
            const a = PLAN_ACTION[d.action] || PLAN_ACTION.Flat
            return (
              <div key={d.day} style={{ padding: '8px 10px', borderRadius: 8,
                                        border: '1px solid var(--border)',
                                        background: 'var(--surface)' }}>
                <div style={{ fontSize: '0.625rem', color: 'var(--dim)' }}>第 {d.day} 日 · {d.date.slice(5)}</div>
                <div style={{ margin: '5px 0', padding: '2px 8px', borderRadius: 10,
                              display: 'inline-block', fontSize: '0.75rem', fontWeight: 700,
                              background: a.bg, color: a.color }}>{a.label}</div>
                <div style={{ fontSize: '0.625rem', color: 'var(--dim)', lineHeight: 1.6 }}>{d.reason}</div>
              </div>
            )
          })}
        </div>

        <div style={{ fontSize: '0.625rem', color: 'var(--dim)', marginTop: 10, lineHeight: 1.7 }}>
          進場條件：籌碼機率 ≥ {plan.policy.buy_th}、預測振幅 ≥ {(plan.policy.range_min * 100).toFixed(0)}%、
          預測日波動 ≤ {(plan.policy.vol_max * 100).toFixed(1)}%；
          停損 {plan.policy.stop_sigma}σ×√{plan.policy.max_hold} 日、停利 {plan.policy.take_r}× 停損距離。
          <div>{plan.costs_note}</div>
          {plan.signals_missing?.length > 0 && (
            <div style={{ color: 'var(--red)' }}>
              缺少訊號：{plan.signals_missing.join('、')}——計畫的把關條件不完整
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function VoteRow({ row, holding }) {
  const [open, setOpen] = useState(false)
  const final = SIGNAL_META[row.final_signal] || SIGNAL_META.Hold
  return (
    <>
      <tr
        onClick={() => setOpen(o => !o)}
        style={{ cursor: 'pointer', background: open ? 'var(--hover)' : 'transparent' }}
      >
        <td style={{ padding: '10px 16px', fontWeight: 700, fontSize: '0.9375rem' }}>{row.stock_id}</td>
        {holding && (
          <td style={{ padding: '10px 8px', textAlign: 'center', fontSize: '0.75rem' }}>
            <Shares value={holding.shares} />
            <div style={{ fontSize: '0.6875rem', fontWeight: 700,
                          color: holding.unrealized_pct > 0 ? 'var(--up)'
                               : holding.unrealized_pct < 0 ? 'var(--down)' : 'var(--dim)' }}>
              {holding.unrealized_pct == null ? '—'
                : `${holding.unrealized_pct > 0 ? '+' : ''}${holding.unrealized_pct.toFixed(2)}%`}
            </div>
          </td>
        )}
        <td style={{ padding: '10px 8px', textAlign: 'center' }}><SignalBadge signal={row.m1_signal} /></td>
        <td style={{ padding: '10px 8px', textAlign: 'center' }}><SignalBadge signal={row.m2_signal} /></td>
        <td style={{ padding: '10px 8px', textAlign: 'center' }}><SignalBadge signal={row.m3_signal} /></td>
        <td style={{ padding: '10px 16px' }}>
          {(() => {
            // final_action 是角色化之後的最終動作，比三分類的 final_signal
            // 多了「減碼」與「不加碼」——那兩個既不是買也不是賣
            const a = ACTION_META[row.final_action]
            const m = a ?? final
            return (
              <span style={{
                display: 'inline-block', padding: '4px 14px', borderRadius: 14,
                fontWeight: 700, fontSize: '0.8125rem',
                background: m.bg, color: m.color,
              }}>{a ? m.label : final.icon + ' ' + final.label}</span>
            )
          })()}
        </td>
        <td style={{ padding: '10px 16px' }}><ScoreBar score={row.score} /></td>
        <td style={{ padding: '10px 8px', textAlign: 'center' }}>
          <RegimeBadge regime={row.vol_regime} vol={row.predicted_vol} />
        </td>
        <td style={{ padding: '10px 8px', textAlign: 'center', fontSize: '0.8125rem', fontWeight: 600 }}>
          {row.position_pct != null ? `${Number(row.position_pct).toFixed(0)}%` : '—'}
        </td>
        <td style={{ padding: '10px 8px', textAlign: 'center', fontSize: '0.8125rem',
                     color: 'var(--dim)' }}>
          {row.stop_pct != null ? `${Number(row.stop_pct).toFixed(1)}%` : '—'}
        </td>
        <td style={{ padding: '10px 12px', color: 'var(--dim)', fontSize: '0.6875rem' }}>
          {row.vote_date}
        </td>
        <td style={{ padding: '10px 8px', color: 'var(--dim)', fontSize: '0.8125rem' }}>
          {open ? '▲' : '▼'}
        </td>
      </tr>
      {open && (
        <tr>
          <td colSpan={holding ? 12 : 11} style={{ padding: 0, background: 'var(--surface)' }}>
            <div style={{ padding: '12px 24px', display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 12 }}>
              {[
                { label: 'M1 LSTM', signal: row.m1_signal, reason: row.m1_reason },
                { label: 'M2 新聞', signal: row.m2_signal, reason: row.m2_reason },
                { label: 'M3 籌碼', signal: row.m3_signal, reason: row.m3_reason },
              ].map(m => (
                <div key={m.label} style={{
                  padding: '10px 14px', borderRadius: 8,
                  border: '1px solid var(--border)', background: 'var(--bg)',
                }}>
                  <div style={{ fontSize: '0.6875rem', color: 'var(--dim)', marginBottom: 6 }}>{m.label}</div>
                  <div style={{ marginBottom: 4 }}><SignalBadge signal={m.signal} /></div>
                  <div style={{ fontSize: '0.75rem', color: 'var(--text)', lineHeight: 1.5 }}>
                    {m.reason || '—'}
                  </div>
                  {m.label === 'M2 新聞' && row.m2_features && (
                    <div style={{ marginTop: 8, display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 4 }}>
                      {[
                        ['情緒均值', row.m2_features.avg_sentiment_72h?.toFixed(3)],
                        ['新聞量差', row.m2_features.news_volume_gap?.toFixed(2)],
                        ['關鍵詞分', row.m2_features.keyword_recovery_hit],
                        ['昨日漲跌', `${row.m2_features.price_return_t1?.toFixed(2)}%`],
                        ['產業情緒', row.m2_features.sector_sentiment?.toFixed(3)],
                        ['相關文章', `${row.m2_features.stock_articles}/${row.m2_features.total_articles}`],
                      ].map(([k, v]) => (
                        <div key={k} style={{ fontSize: '0.6875rem' }}>
                          <span style={{ color: 'var(--dim)' }}>{k}: </span>
                          <span style={{ color: 'var(--text)', fontFamily: 'monospace' }}>{v ?? '—'}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
            <RolePanel roles={row.roles} path={row.decision_path}
                       action={row.final_action} target={row.target_position_pct}
                       holding={row.holding_snapshot} />
            <WeeklyPlanPanel stockId={row.stock_id} />
            {row.risk_reason && (
              <div style={{ padding: '0 24px 14px' }}>
                <div style={{
                  padding: '10px 14px', borderRadius: 8,
                  border: '1px solid var(--border)', background: 'var(--bg)',
                }}>
                  <div style={{ fontSize: '0.6875rem', color: 'var(--dim)', marginBottom: 6 }}>
                    風險控管（不參與投票計分）
                  </div>
                  <div style={{ display: 'flex', gap: 18, flexWrap: 'wrap', marginBottom: 6 }}>
                    {[
                      ['預測日波動率', row.predicted_vol != null
                        ? `${(Number(row.predicted_vol) * 100).toFixed(2)}%` : '—'],
                      ['波動區間', row.vol_regime || '—'],
                      ['建議停損距離', row.stop_pct != null
                        ? `${Number(row.stop_pct).toFixed(1)}%` : '—'],
                      ['建議部位比例', row.position_pct != null
                        ? `${Number(row.position_pct).toFixed(1)}%` : '—'],
                    ].map(([k, v]) => (
                      <div key={k} style={{ fontSize: '0.75rem' }}>
                        <span style={{ color: 'var(--dim)' }}>{k}: </span>
                        <span style={{ color: 'var(--text)', fontWeight: 600,
                                       fontFamily: 'monospace' }}>{v}</span>
                      </div>
                    ))}
                  </div>
                  <div style={{ fontSize: '0.75rem', color: 'var(--text)', lineHeight: 1.5 }}>
                    {row.risk_reason}
                  </div>
                </div>
              </div>
            )}
          </td>
        </tr>
      )}
    </>
  )
}

// ── 投票結果表格（持有／未持有共用）──────────────────────────────────────────
// 拆成兩區塊不只是排版：兩邊該先看的東西不一樣。
// 持有中要先看「有沒有該出場的」，未持有要先看「有沒有該進場的」，
// 所以兩邊的預設排序方向相反。
const HELD_PRIORITY = { Sell: 0, Reduce: 1, NoAdd: 2, Hold: 3, Buy: 4 }
const FREE_PRIORITY = { Buy: 0, Hold: 1, NoAdd: 2, Reduce: 3, Sell: 4 }

function VoteTable({ rows, holdings, held }) {
  const priority = held ? HELD_PRIORITY : FREE_PRIORITY
  const sorted = [...rows].sort((a, b) => {
    const pa = priority[a.final_action ?? a.final_signal] ?? 9
    const pb = priority[b.final_action ?? b.final_signal] ?? 9
    if (pa !== pb) return pa - pb
    return String(a.stock_id).localeCompare(String(b.stock_id))
  })

  const headers = held
    ? ['股票代碼', '持有', 'M1 LSTM', 'M2 新聞', 'M3 籌碼', '最終建議', '分數',
       '波動', '建議部位', '停損', '日期', '']
    : ['股票代碼', 'M1 LSTM', 'M2 新聞', 'M3 籌碼', '最終建議', '分數',
       '波動', '建議部位', '停損', '日期', '']

  return (
    <div style={{ overflowX: 'auto' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
        <thead>
          <tr style={{ borderBottom: '1px solid var(--border)', background: 'var(--surface)' }}>
            {headers.map((h, i) => (
              <th key={i} style={{
                padding: '8px 16px', textAlign: i < 2 ? 'left' : 'center',
                fontSize: '0.6875rem', color: 'var(--dim)', fontWeight: 600,
                textTransform: 'uppercase', letterSpacing: '.04em',
              }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.map(row => (
            <VoteRow key={row.id || row.stock_id} row={row}
                     holding={held ? holdings[row.stock_id] : null} />
          ))}
        </tbody>
      </table>
    </div>
  )
}

export default function VotingDashboard() {
  const [results, setResults] = useState([])
  const [loading, setLoading] = useState(true)
  const [voteState, setVoteState] = useState('idle')  // idle | running | done | error
  const [voteMsg, setVoteMsg]     = useState('')
  const [stockInput, setStockInput] = useState('')
  const [stockList, setStockList]   = useState([])
  const pollRef = useRef(null)

  const [gap, setGap] = useState(null)
  const [range, setRange] = useState(null)
  // 持有與否用「目前」的持股判斷，而不是投票當下的快照——
  // 使用者要問的是「我現在手上這些該怎麼辦」
  const [holdings, setHoldings] = useState({})
  // null = 還沒從 /catalog 取得預設值；ModelPicker 掛載後回填
  const [models, setModels] = useState(null)

  async function fetchResults() {
    setLoading(true)
    const { data } = await getVotingResults()
    setResults(data || [])
    setLoading(false)
  }

  async function fetchGap() {
    const { data } = await getGapPrediction()
    if (data?.available) setGap(data)
  }

  async function fetchRange() {
    const { data } = await getWeeklyRange()
    if (data?.available) setRange(data)
  }

  async function fetchHoldings() {
    const { data } = await getHoldings()
    setHoldings(Object.fromEntries((data?.items ?? []).map(h => [h.stock_id, h])))
  }

  useEffect(() => { fetchResults(); fetchGap(); fetchRange(); fetchHoldings() }, [])
  useEffect(() => () => clearInterval(pollRef.current), [])

  const heldRows = results.filter(r => holdings[r.stock_id])
  const freeRows = results.filter(r => !holdings[r.stock_id])

  function addStock() {
    const s = stockInput.trim()
    if (s && !stockList.includes(s)) setStockList(p => [...p, s])
    setStockInput('')
  }

  async function handleVote() {
    setVoteState('running')
    setVoteMsg(`正在對 ${stockList.length} 支股票執行三模型投票…`)
    const { error } = await triggerVoting(stockList, models)
    if (error) { setVoteState('error'); setVoteMsg(`失敗：${error}`); return }

    clearInterval(pollRef.current)
    pollRef.current = setInterval(async () => {
      const { data } = await getVotingStatus()
      if (!data) return
      if (data.status === 'idle') {
        clearInterval(pollRef.current)
        setVoteState('done')
        setVoteMsg(`投票完成，共處理 ${data.last_count} 支股票`)
        fetchResults()
      }
    }, 2000)
  }

  const buyCount  = results.filter(r => r.final_signal === 'Buy').length
  const sellCount = results.filter(r => r.final_signal === 'Sell').length
  const holdCount = results.filter(r => r.final_signal === 'Hold').length

  return (
    <>
      {/* 選了哪些模型會直接改變下一次投票的結果——所以放在最上面，
          而不是藏在設定裡。勾選變更後要重新執行投票才會反映 */}
      <ModelPicker page="voting" value={models} onChange={setModels} compact />

      {/* 摘要卡片 */}
      <div className="cards-grid">
        <div className="metric-card">
          <div className="metric-label">追蹤股票數</div>
          <div className="metric-value">{loading ? '…' : results.length}</div>
          <div className="metric-delta muted">已有投票結果</div>
        </div>
        <div className="metric-card">
          <div className="metric-label">買入建議</div>
          <div className="metric-value up">{loading ? '…' : buyCount}</div>
          <div className="metric-delta muted">三模型加權 ≥ +0.3</div>
        </div>
        <div className="metric-card">
          <div className="metric-label">賣出建議</div>
          <div className="metric-value down">{loading ? '…' : sellCount}</div>
          <div className="metric-delta muted">三模型加權 ≤ -0.3</div>
        </div>
        <div className="metric-card">
          <div className="metric-label">持有觀望</div>
          <div className="metric-value" style={{ color: 'var(--dim)' }}>{loading ? '…' : holdCount}</div>
          <div className="metric-delta muted">信號不明確</div>
        </div>
      </div>

      {/* 控制面板 */}
      <div className="card">
        <div className="card-header">
          <span className="card-title">執行投票</span>
          <span className="tag blue">POST /voting/run</span>
        </div>
        <div style={{ padding: '14px 18px', display: 'flex', flexDirection: 'column', gap: 12 }}>

          {/* 股票清單 */}
          <div>
            <div className="form-label" style={{ marginBottom: 6 }}>股票清單</div>
            <div className="ticker-area">
              {stockList.map(s => (
                <span key={s} className="ticker-tag manual">
                  {s}
                  <button className="ticker-remove"
                    onClick={() => setStockList(p => p.filter(x => x !== s))}
                    disabled={voteState === 'running'}>×</button>
                </span>
              ))}
              <div className="ticker-input-wrap">
                <input
                  className="ticker-input"
                  placeholder="新增代碼"
                  value={stockInput}
                  onChange={e => setStockInput(e.target.value)}
                  onKeyDown={e => e.key === 'Enter' && addStock()}
                  disabled={voteState === 'running'}
                  maxLength={6}
                />
                <button className="btn-chip" onClick={addStock} disabled={voteState === 'running'}>+</button>
              </div>
            </div>
          </div>

          {/* 執行按鈕 */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
            <button
              className="btn-primary"
              onClick={handleVote}
              disabled={voteState === 'running' || stockList.length === 0}
            >
              {voteState === 'running' ? '投票中…' : `執行投票（${stockList.length} 支）`}
            </button>
            <button className="btn-secondary" onClick={fetchResults} disabled={voteState === 'running'}>
              重新整理
            </button>
          </div>

          {/* 狀態列 */}
          {voteMsg && (
            <div style={{
              fontSize: '0.8125rem', padding: '8px 12px', borderRadius: 6,
              background: voteState === 'error' ? 'rgba(248,81,73,.1)'
                        : voteState === 'done'  ? 'rgba(63,185,80,.1)'
                        : 'rgba(99,102,241,.1)',
              color: voteState === 'error' ? 'var(--red)'
                   : voteState === 'done'  ? 'var(--green)'
                   : 'var(--accent)',
              display: 'flex', alignItems: 'center', gap: 8,
            }}>
              {voteState === 'running' && (
                <span style={{
                  display: 'inline-block', width: 12, height: 12, borderRadius: '50%',
                  border: '2px solid currentColor', borderTopColor: 'transparent',
                  animation: 'spin 0.8s linear infinite',
                }} />
              )}
              {voteState === 'done'  && '✓ '}
              {voteState === 'error' && '✗ '}
              {voteMsg}
            </div>
          )}
        </div>
      </div>

      {loading && (
        <div className="card">
          <div style={{ padding: 24, textAlign: 'center', color: 'var(--dim)' }}>載入中…</div>
        </div>
      )}

      {!loading && results.length === 0 && (
        <div className="card">
          <div className="empty-state">
            <div className="empty-icon">🗳️</div>
            <div>尚無投票結果</div>
            <div className="muted" style={{ fontSize: '0.75rem' }}>輸入股票代碼後點「執行投票」</div>
          </div>
        </div>
      )}

      {gap && <GapPanel gap={gap} />}
      {range && <RangePanel range={range} />}

      {/* 持有中 —— 這裡的問題是「手上的部位該怎麼辦」，先看該出場的 */}
      {results.length > 0 && (
        <div className="card">
          <div className="card-header">
            <span className="card-title">持有中</span>
            <span className="tag blue">{heldRows.length} 檔</span>
            {heldRows.length > 0 && (
              <span className="muted" style={{ fontSize: '0.6875rem' }}>
                依「該處理的優先」排序：賣出 → 減碼 → 不加碼 → 不動 → 買進
              </span>
            )}
          </div>
          {heldRows.length > 0 ? (
            <VoteTable rows={heldRows} holdings={holdings} held />
          ) : (
            <div style={{ padding: '18px 24px', color: 'var(--dim)', fontSize: '0.75rem',
                          lineHeight: 1.8 }}>
              目前沒有持股，或持股不在本次投票的股票清單內。
              到「💼 我的持股」輸入持股或記錄交易後，這裡會顯示每一檔的處理建議
              （加碼／減碼／停損／不動），並由「持倉管家」角色以浮動損益與集中度把關。
            </div>
          )}
        </div>
      )}

      {/* 未持有 —— 這裡的問題是「要不要進場」，先看該買的 */}
      {results.length > 0 && (
        <div className="card">
          <div className="card-header">
            <span className="card-title">未持有</span>
            <span className="tag">{freeRows.length} 檔</span>
            <span className="muted" style={{ fontSize: '0.6875rem' }}>
              依「該進場的優先」排序；未持有的股票不會出現賣出建議——本系統不做放空
            </span>
          </div>
          {freeRows.length > 0 ? (
            <VoteTable rows={freeRows} holdings={holdings} held={false} />
          ) : (
            <div style={{ padding: '18px 24px', color: 'var(--dim)', fontSize: '0.75rem' }}>
              本次投票的股票全部都在持股清單內。
            </div>
          )}
        </div>
      )}
    </>
  )
}
