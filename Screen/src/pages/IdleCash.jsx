// 閒置資金 — 一週配置方案
//
// 這一頁刻意把「它不能做到什麼」放在最上面，而不是藏在附註裡。
//
// 需求是「一週內買賣最大化利益」，但最大化報酬需要知道哪支會漲多少，
// 而本專案已反覆實測方向不可預測（Iteration 11、12），
// Iteration 22 的每日進出策略走查也輸給買進持有。
// 所以這裡最大化的是**風險調整後的期望價差空間**：
// 在有走查驗證的振幅與波動率上，把資金配到單位風險能換到最多價差的標的。
//
// 頁面上每個數字都已扣除來回手續費與證交稅——不扣成本的期望值會系統性偏高，
// 而資金小的時候，成本就是決定這件事可不可行的關鍵。

import { useState } from 'react'
import { getCashPlan } from '../services/api'
import { Shares } from '../components/Shares'
import ErrorBoundary from '../components/ErrorBoundary'
import ModelPicker from '../components/ModelPicker'

const money = v => (v == null ? '–' : Number(v).toLocaleString('zh-TW', { maximumFractionDigits: 0 }))
const PRESETS = [50000, 100000, 300000, 500000, 1000000]

function StatTile({ label, value, sub, color, title }) {
  return (
    <div className="stat-tile" title={title}>
      <div className="k">{label}</div>
      <div className="v" style={{ color: color ?? 'var(--text-strong)' }}>{value}</div>
      {sub && <div className="s">{sub}</div>}
    </div>
  )
}

export default function IdleCash() {
  const [amount, setAmount] = useState(300000)
  const [risk, setRisk] = useState(2)          // %
  const [positions, setPositions] = useState(5)
  const [excludeHeld, setExcludeHeld] = useState(true)
  // null = 還沒從 /catalog 拿到預設值。ModelPicker 載入後會回填，
  // 在那之前不要送出請求，否則第一次配置用的是「後端預設」而畫面顯示的是空選單
  const [models, setModels] = useState(null)
  const [plan, setPlan] = useState(null)
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState('')

  async function run() {
    if (!(Number(amount) > 0)) { setErr('請輸入大於 0 的閒置資金'); return }
    setLoading(true); setErr(''); setPlan(null)
    const { data, error } = await getCashPlan({
      amount: Number(amount), risk_budget: Number(risk) / 100,
      max_positions: Number(positions), exclude_held: excludeHeld,
      models,
    })
    setLoading(false)
    if (error) setErr(error)
    else if (!data?.available) setErr(data?.reason ?? '無法產生配置')
    else setPlan(data)
  }

  const s = plan?.summary

  return (
    <>
      <ModelPicker page="idlecash" value={models} onChange={setModels} compact />

      {/* ── 條件 ── */}
      <div className="card">
        <div className="card-header">
          <div style={{ flex: 1, minWidth: 0 }}>
            <div className="row-head">
              <span className="card-title">閒置資金一週配置</span>
              <span className="tag yellow">風險調整後的價差空間，非獲利預測</span>
            </div>
            <div className="row-sub">
              以走查驗證過的週振幅與波動率為基礎，把資金配到「單位風險能換到最多價差」的標的
            </div>
          </div>
          <button className="btn-primary" onClick={run} disabled={loading}>
            {loading ? '計算中…' : '產生配置方案'}
          </button>
        </div>

        <div className="toolbar">
          <label className="fld">
            <span>閒置資金（元）</span>
            <input className="ctrl-select" type="number" min="1000" step="10000"
                   value={amount} style={{ width: '9rem' }}
                   onChange={e => setAmount(e.target.value)} />
          </label>
          <label className="fld">
            <span>整週風險上限</span>
            <select className="ctrl-select" value={risk} onChange={e => setRisk(e.target.value)}>
              {[1, 2, 3, 4, 6, 8, 10].map(v => <option key={v} value={v}>{v}%</option>)}
            </select>
          </label>
          <label className="fld">
            <span>最多分散</span>
            <select className="ctrl-select" value={positions}
                    onChange={e => setPositions(e.target.value)}>
              {[1, 2, 3, 4, 5, 6, 8].map(v => <option key={v} value={v}>{v} 檔</option>)}
            </select>
          </label>
          <label className="fld">
            <span>已持有的股票</span>
            <select className="ctrl-select" value={excludeHeld ? '1' : '0'}
                    onChange={e => setExcludeHeld(e.target.value === '1')}>
              <option value="1">排除（不重複押注）</option>
              <option value="0">一併納入</option>
            </select>
          </label>
          <div style={{ marginLeft: 'auto', display: 'flex', gap: '.3rem', alignItems: 'flex-end' }}>
            {PRESETS.map(v => (
              <button key={v} className={Number(amount) === v ? 'btn-chip active' : 'btn-chip'}
                      onClick={() => setAmount(v)}>{money(v)}</button>
            ))}
          </div>
        </div>

        <div className="note-box">
          <strong style={{ color: 'var(--yellow)' }}>這個功能不預測漲跌。</strong>
          「最大化利益」需要知道哪支會漲多少，而本專案已反覆實測方向不可預測
          （Iteration 11：LSTM 等同天真基準；Iteration 12：超越基準 −0.09%），
          Iteration 22 的每日進出策略走查外樣本也輸給買進持有。
          這裡最大化的是<strong style={{ color: 'var(--text)' }}>風險調整後的期望價差空間</strong>——
          振幅模型（走查 lift 1.98）決定「這週值不值得動用資金」，
          波動率模型（走查相關 0.606）決定「停損放哪、能押多少」，
          籌碼機率只做 0.85~1.15 的微調。所有金額都已扣除來回手續費與證交稅。
        </div>
      </div>

      {err && (
        <div className="card"><div className="note-box" style={{ color: 'var(--red)' }}>{err}</div></div>
      )}

      {loading && <div className="card"><div className="empty-state">計算中…</div></div>}

      {/* ── 摘要 ── */}
      {plan && s && (
        <div className="card">
          <div className="card-header">
            <span className="card-title">配置摘要</span>
            <span className="tag blue">
              風險上限 {plan.risk_budget_pct}%　最多 {plan.max_positions} 檔
            </span>
          </div>
          <div className="stat-grid">
            <StatTile label="選出檔數" value={`${s.n_picks} 檔`} />
            <StatTile label="投入金額" value={`${money(s.invested)} 元`}
                      sub={`佔閒置資金 ${s.invested_pct}%`} />
            <StatTile label="留存現金" value={`${money(s.idle_left)} 元`}
                      title="固定風險法下投不滿是正常的，不是系統少配" />
            <StatTile label="最大可能虧損" value={`${money(s.total_risk)} 元`}
                      color="var(--down)" sub={`${s.total_risk_pct}%（全部觸及停損）`}
                      title="這是這份配置裡證據最強的數字——由走查驗證過的波動率模型換算" />
            <StatTile label="來回交易成本" value={`${money(s.total_cost)} 元`} color="var(--dim)" />
            <StatTile label="期望淨價差空間"
                      value={`${money(s.expected_net)} 元`}
                      color={s.expected_net > 0 ? 'var(--up)' : 'var(--down)'}
                      sub={`${s.expected_net_pct}%（已扣成本，非獲利保證）`} />
          </div>

          {plan.diagnostics?.length > 0 && (
            <div className="note-box">
              {plan.diagnostics.map((d, i) => (
                <div key={i} style={{ marginBottom: '.35rem' }}>
                  {d.replace(/\*\*/g, '')}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* ── 配置明細 ── */}
      {plan && plan.picks.length > 0 && (
        <div className="card">
          <div className="card-header">
            <span className="card-title">建議部位</span>
            <span className="tag" style={{ color: 'var(--dim)' }}>
              效率＝期望價差 ÷ 停損距離
            </span>
          </div>
          <ErrorBoundary label="建議部位">
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>股票</th>
                    <th className="num">現價</th>
                    <th>買進數量</th>
                    <th className="num">投入金額</th>
                    <th className="num">佔比</th>
                    <th className="num" title="未來 5 個交易日的預測高低差">預測振幅</th>
                    <th className="num" title="由波動率模型換算">停損價</th>
                    <th className="num">最大虧損</th>
                    <th className="num" title="預測振幅 × 捕捉率 0.35，扣除來回成本">期望淨價差</th>
                    <th className="num">效率</th>
                  </tr>
                </thead>
                <tbody>
                  {plan.picks.map(p => (
                    <tr key={p.stock_id}>
                      <td>
                        <strong>{p.stock_id}</strong>
                        {p.is_significant && (
                          <span className="tag red" style={{ marginLeft: '.4rem' }}>振幅顯著</span>
                        )}
                      </td>
                      <td className="num muted">{p.close.toFixed(2)}</td>
                      <td><Shares value={p.shares} /></td>
                      <td className="num">{money(p.cost_basis)}</td>
                      <td className="num muted">{p.weight_pct}%</td>
                      <td className="num">{p.range_pct}%</td>
                      <td className="num" style={{ color: 'var(--down)' }}>{p.stop_price}</td>
                      <td className="num muted">−{money(p.risk_amount)}</td>
                      <td className="num" style={{
                        color: p.expected_net > 0 ? 'var(--up)' : 'var(--down)', fontWeight: 600,
                      }}>
                        {money(p.expected_net)}
                      </td>
                      <td className="num muted">{p.efficiency}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </ErrorBoundary>
        </div>
      )}

      {/* ── 被排除的候選 ── */}
      {plan && plan.rejected?.length > 0 && (
        <div className="card">
          <div className="card-header">
            <span className="card-title">未納入的候選</span>
            <span className="tag" style={{ color: 'var(--dim)' }}>{plan.rejected.length} 檔</span>
          </div>
          <div className="muted" style={{ padding: '0 1.25rem .6rem', fontSize: '.8rem', lineHeight: 1.8 }}>
            系統刻意不出手的名單。一筆扣完成本期望為負的交易，不該送到你面前——
            這比多給幾個建議有用。
          </div>
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>股票</th><th className="num">現價</th><th className="num">預測振幅</th>
                  <th className="num">停損距離</th><th>未納入原因</th>
                </tr>
              </thead>
              <tbody>
                {plan.rejected.map(r => (
                  <tr key={r.stock_id}>
                    <td><strong>{r.stock_id}</strong></td>
                    <td className="num muted">{r.close?.toFixed(2)}</td>
                    <td className="num muted">{r.range_pct}%</td>
                    <td className="num muted">{r.stop_pct}%</td>
                    <td className="muted" style={{ whiteSpace: 'normal', fontSize: '.82rem' }}>
                      {r.reason}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ── 假設與限制 ── */}
      {plan?.honesty && (
        <div className="card">
          <div className="card-header"><span className="card-title">這份配置的假設與限制</span></div>
          <div className="note-box">
            {plan.honesty.map((h, i) => (
              <div key={i} style={{ marginBottom: '.5rem' }}>
                {i + 1}. {h.replace(/\*\*/g, '')}
              </div>
            ))}
            <div style={{ marginTop: '.6rem', color: 'var(--dim)' }}>
              參數：捕捉率 {plan.assumptions.capture_ratio}、持有 {plan.assumptions.hold_days} 個交易日、
              單檔上限 {plan.assumptions.max_weight_pct}%、最小單筆 {money(plan.assumptions.min_ticket)} 元、
              手續費 {(plan.assumptions.fee_rate * 100).toFixed(4)}%（最低 {plan.assumptions.fee_min} 元）、
              證交稅 {(plan.assumptions.tax_rate * 100).toFixed(1)}%
            </div>
          </div>
        </div>
      )}

      {!plan && !loading && !err && (
        <div className="card">
          <div className="empty-state">
            <div className="empty-icon">💵</div>
            <div>輸入閒置資金與風險上限，產生一週配置方案</div>
            <div className="muted" style={{ fontSize: '.85rem', marginTop: '.3rem', maxWidth: '34rem', lineHeight: 1.8 }}>
              配置會依「單位風險能換到多少價差空間」排序，並扣除來回手續費與證交稅。
              投不滿是正常的——固定風險法下，可投入比例約等於風險上限 ÷ 停損距離。
            </div>
          </div>
        </div>
      )}
    </>
  )
}
