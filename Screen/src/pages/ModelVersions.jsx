// 模型版本管理 — 凍結長期服役版本、檢視線上實測表現
//
// 「凍結」把目前迭代中的 candidate 固定成長期服役版本：之後重訓不再動到它，
// 系統同時自動開出下一版 candidate 繼續迭代。凍結有兩條路徑——
// 達到線上實測門檻（自動），或使用者在這裡按下（手動）。
//
// 頁面刻意把「訓練走查指標」和「線上實測指標」分開顯示：前者是回頭在歷史上
// 模擬，後者是模型真的送出、事後被實際價格驗證的預測。兩者不一致時以後者為準。

import { useEffect, useState } from 'react'
import {
  getModelVersions, getModelRegistry, freezeModel,
  serveModelVersion, retireModelVersion, evaluateModels,
} from '../services/api'
import ModelBar from '../components/ModelBar'

const STATUS_STYLE = {
  candidate: { label: '迭代中', color: 'var(--yellow)', bg: 'var(--yellow-soft)',
               hint: '指向工作區檔案，下次重訓會被覆寫' },
  frozen:    { label: '已凍結', color: 'var(--green)', bg: 'var(--green-soft)',
               hint: '指向不可變快照，重訓碰不到' },
  retired:   { label: '已退役', color: 'var(--dim)', bg: 'var(--dim-soft)',
               hint: '曾經服役或權重已被覆寫，僅供回溯' },
}

const pct = v => (v == null ? '–' : `${(v * 100).toFixed(1)}%`)
const num = (v, d = 4) => (v == null ? '–' : Number(v).toFixed(d))

function StatusTag({ status, isServing }) {
  const s = STATUS_STYLE[status] ?? STATUS_STYLE.retired
  return (
    <>
      <span className="tag" style={{ color: s.color, background: s.bg }} title={s.hint}>
        {s.label}
      </span>
      {isServing && (
        <span className="tag blue" title="推論端目前實際載入的版本">服役中</span>
      )}
    </>
  )
}

// ── 線上指標：方向類與量級類的呈現方式不同 ────────────────────────────────────
function LiveMetrics({ m }) {
  if (!m || !m.n) {
    return <div className="muted" style={{ fontSize: '0.75rem' }}>尚無已到期的預測可比對</div>
  }
  const directional = m.direction_acc != null
  return (
    <div style={{ display: 'flex', gap: 22, flexWrap: 'wrap', alignItems: 'flex-end' }}>
      <Metric label="已到期樣本" value={m.n} />
      {directional ? (
        <>
          <Metric label="方向準確率" value={pct(m.direction_acc)}
                  color={m.margin > 0 ? 'var(--green)' : 'var(--red)'} />
          <Metric label="多數類別基準" value={pct(m.baseline_direction_acc)} color='var(--dim)'
                  title="一律猜漲（或一律猜跌，取高者）能拿到的準確率" />
          <Metric label="超越基準" value={m.margin == null ? '–' :
                    `${m.margin >= 0 ? '+' : ''}${(m.margin * 100).toFixed(1)}%`}
                  color={m.margin > 0 ? 'var(--green)' : 'var(--red)'} />
          <Metric label="p 值" value={m.p_value == null ? '–' : m.p_value.toFixed(4)}
                  color={m.p_value <= 0.05 ? 'var(--green)' : 'var(--dim)'}
                  title="單尾二項檢定：模型準確率高於多數類別基準純屬偶然的機率" />
          <Metric label="實際出手" value={m.direction_n ?? '–'}
                  title="棄權（Hold／平盤）不計入方向準確率" />
        </>
      ) : (
        <>
          <Metric label="排序相關" value={num(m.rank_corr, 3)}
                  color={m.rank_corr > 0.2 ? 'var(--green)' : 'var(--yellow)'} />
          <Metric label="天真基準" value={num(m.baseline_rank_corr, 3)} color='var(--dim)' />
        </>
      )}
      <Metric label="MAE" value={num(m.mae)} />
      <Metric label="基準 MAE" value={num(m.baseline_mae)} color='var(--dim)' />
      {m.ci_hit_rate != null && (
        <Metric label="信賴區間命中" value={pct(m.ci_hit_rate)} />
      )}
      {m.evaluations > 1 && (
        <Metric label="已評估次數" value={m.evaluations} color='var(--yellow)'
                title="反覆評估會系統性高估被選中版本的表現，次數多請自行打折" />
      )}
    </div>
  )
}

function Metric({ label, value, color, title }) {
  return (
    <div title={title}>
      <div style={{ fontSize: '0.6875rem', color: 'var(--dim)', marginBottom: 3 }}>{label}</div>
      <div style={{ fontSize: '0.9375rem', fontWeight: 700, color: color ?? 'var(--text-strong)' }}>{value}</div>
    </div>
  )
}

// ── 單一模型類型的卡片（含其所有版本）─────────────────────────────────────────
function TypeCard({ modelType, label, versions, onAction, busy }) {
  const [open, setOpen] = useState(false)
  // effective_serving 才是「現在真的在對外輸出的那一版」。
  // 沒有任何一版被明確指定服役時，推論端會直接拿 candidate 上場，
  // 此時 is_serving 為 false 卻確實在跑（見 model_registry.loadable_versions）。
  const serving = versions.find(v => v.effective_serving ?? v.is_serving)
  const candidate = versions.find(v => v.status === 'candidate')
  const frozenCount = versions.filter(v => v.status === 'frozen').length

  return (
    <div className="card">
      <div className="card-header" style={{ cursor: 'pointer' }} onClick={() => setOpen(o => !o)}>
        <span className="card-title">{label}</span>
        <span className="tag" style={{ color: 'var(--dim)' }}>{modelType}</span>
        {serving
          ? <span className="tag green">服役 v{serving.version}（{STATUS_STYLE[serving.status]?.label}）</span>
          : <span className="tag" style={{ color: 'var(--yellow)', background: 'var(--yellow-soft)' }}>尚無凍結版本，暫由 candidate 服役</span>}
        {frozenCount > 0 && <span className="tag blue">{frozenCount} 個凍結版本</span>}
        <span style={{ marginLeft: 'auto', color: 'var(--dim)', fontSize: '0.8125rem' }}>{open ? '▲' : '▼'}</span>
      </div>

      {/* candidate 的線上表現與凍結入口 */}
      {candidate && (
        <div style={{ padding: '12px 18px', borderTop: '1px solid var(--border)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10 }}>
            <strong style={{ fontSize: '0.8125rem' }}>v{candidate.version}（迭代中）</strong>
            <span className="muted" style={{ fontSize: '0.75rem' }}>{candidate.gate_note}</span>
            <button
              className={candidate.gate_passed ? 'btn-primary' : 'btn-secondary'}
              style={{ marginLeft: 'auto' }}
              disabled={busy}
              onClick={() => onAction('freeze', modelType, candidate)}
            >
              {candidate.gate_passed ? '✔ 已達門檻 — 凍結為長期版本' : '手動凍結'}
            </button>
          </div>
          <LiveMetrics m={candidate.metrics} />
          {!candidate.gate_passed && (
            <div className="muted" style={{ fontSize: '0.6875rem', marginTop: 8 }}>
              手動凍結會略過門檻——這是你的判斷，不是模型的成績。凍結後此版本永不重訓，
              系統自動開出 v{candidate.version + 1} 繼續迭代。
            </div>
          )}
        </div>
      )}

      {/* 全部版本 */}
      {open && (
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>版本</th><th>狀態</th><th>樣本</th><th>主要指標</th>
                <th>凍結時間</th><th>凍結原因</th><th>操作</th>
              </tr>
            </thead>
            <tbody>
              {versions.map(v => {
                const m = v.metrics ?? {}
                const main = m.direction_acc != null
                  ? `方向 ${pct(m.direction_acc)} / 基準 ${pct(m.baseline_direction_acc)}`
                  : m.rank_corr != null ? `排序相關 ${num(m.rank_corr, 3)}` : '–'
                return (
                  <tr key={v.id}>
                    <td><strong>v{v.version}</strong></td>
                    <td><StatusTag status={v.status} isServing={v.effective_serving ?? v.is_serving} /></td>
                    <td className="muted">{m.n ?? 0}</td>
                    <td className="muted">{main}</td>
                    <td className="muted">
                      {v.frozen_at ? new Date(v.frozen_at).toLocaleDateString('zh-TW') : '–'}
                    </td>
                    <td className="muted" style={{ fontSize: '0.6875rem', maxWidth: 260 }}>
                      {v.freeze_reason === 'auto' ? '自動（達門檻）'
                        : v.freeze_reason === 'manual' ? '手動選取' : '–'}
                      {v.freeze_note ? `：${v.freeze_note}` : ''}
                    </td>
                    <td>
                      {v.status === 'frozen' && !(v.effective_serving ?? v.is_serving) && (
                        <button className="btn-chip" disabled={busy}
                                onClick={() => onAction('serve', modelType, v)}>切換服役</button>
                      )}
                      {v.status === 'frozen' && (
                        <button className="btn-chip" style={{ color: 'var(--dim)' }} disabled={busy}
                                onClick={() => onAction('retire', modelType, v)}>退役</button>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

// ── 主頁面 ────────────────────────────────────────────────────────────────────
export default function ModelVersions() {
  const [byType, setByType] = useState([])
  const [gate, setGate] = useState(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')
  const [err, setErr] = useState('')

  async function load() {
    setLoading(true); setErr('')
    const { data, error } = await getModelVersions()
    if (error) {
      // FastAPI 沒開時退回只讀清單，至少看得到版本狀態而不是整頁空白
      const fb = await getModelRegistry()
      setErr(`${error}　（已退回只讀模式，無法顯示線上指標或執行凍結）`)
      setGate(null)
      setByType(group(fb.data ?? []))
    } else {
      setGate(data.gate)
      setByType(group(data.versions ?? []))
    }
    setLoading(false)
  }

  function group(versions) {
    const map = new Map()
    for (const v of versions) {
      if (!map.has(v.model_type)) {
        map.set(v.model_type, { modelType: v.model_type, label: v.label ?? v.model_type, versions: [] })
      }
      map.get(v.model_type).versions.push(v)
    }
    for (const g of map.values()) g.versions.sort((a, b) => b.version - a.version)
    return [...map.values()].sort((a, b) => a.modelType.localeCompare(b.modelType))
  }

  useEffect(() => { load() }, [])

  async function handleAction(action, modelType, version) {
    const confirmText = {
      freeze: `凍結 ${modelType} v${version.version}？\n\n此版本之後不再重訓，直接成為長期服役版本，`
        + `系統會自動開出 v${version.version + 1} 繼續迭代。`,
      serve: `把 ${modelType} 的服役版本切到 v${version.version}？`,
      retire: `退役 ${modelType} v${version.version}？檔案與紀錄都會保留。`,
    }[action]
    if (!window.confirm(confirmText)) return

    setBusy(true); setMsg(''); setErr('')
    const fn = action === 'freeze' ? () => freezeModel(modelType)
      : action === 'serve' ? () => serveModelVersion(version.id)
      : () => retireModelVersion(version.id)
    const { data, error } = await fn()
    if (error) setErr(error)
    else setMsg(action === 'freeze'
      ? `已凍結 ${modelType} v${version.version}，並開出 v${data?.next_candidate?.version ?? '?'} 繼續迭代`
      : action === 'serve' ? `服役版本已切換至 v${version.version}`
      : `v${version.version} 已退役`)
    setBusy(false)
    load()
  }

  async function handleEvaluate(apply) {
    if (apply && !window.confirm(
      '執行自動凍結？\n\n所有達到門檻的 candidate 會立刻成為長期服役版本並停止重訓。'
      + '這是不可逆的部署決定。')) return
    setBusy(true); setMsg(''); setErr('')
    const { data, error } = await evaluateModels(apply)
    if (error) setErr(error)
    else {
      const f = data.frozen ?? []
      setMsg(`已回填 ${data.resolved?.resolved ?? 0} 筆實際值、評估 ${data.evaluated} 個版本`
        + (f.length ? `；自動凍結：${f.map(x => `${x.model_type} v${x.version}`).join('、')}`
                    : apply ? '；無版本達到門檻' : '（僅重算指標，未執行凍結）'))
    }
    setBusy(false)
    load()
  }

  return (
    <>
      <ModelBar page="models" />
      <div className="card">
        <div className="card-header">
          <span className="card-title">模型版本</span>
          <span className="tag blue">{byType.length} 個模型類型</span>
          <button className="btn-secondary" style={{ marginLeft: 'auto' }}
                  disabled={busy} onClick={() => handleEvaluate(false)}>
            回填並重算指標
          </button>
          <button className="btn-secondary" disabled={busy}
                  onClick={() => handleEvaluate(true)}>
            執行自動凍結
          </button>
          <button className="btn-secondary" disabled={busy} onClick={load}>重新整理</button>
        </div>
        <div style={{ padding: '8px 18px 14px', color: 'var(--dim)', fontSize: '0.75rem', lineHeight: 1.7 }}>
          <strong style={{ color: 'var(--text-strong)' }}>凍結</strong>＝把目前迭代中的版本固定成長期服役版本：
          模型檔案複製成不可變快照，之後重訓只會寫進新開的 candidate，永遠不會覆寫它。
          兩條凍結路徑——線上實測達到門檻（自動），或你在此手動選取。
          {gate && (
            <div style={{ marginTop: 6 }}>
              <strong style={{ color: 'var(--text-strong)' }}>自動門檻：</strong>{gate.note}
              　樣本數下限 {gate.min_samples} 筆。
            </div>
          )}
          <div style={{ marginTop: 6 }}>
            這裡的準確率全部是<strong style={{ color: 'var(--text-strong)' }}>線上實測</strong>——模型當時真的送出、
            事後被實際價格驗證的預測，與訓練報表的走查指標是兩回事。實際值一律以 adj_close
            計算（已還原除權息與減資）。
          </div>
        </div>
      </div>

      {msg && (
        <div className="card" style={{ padding: '10px 18px', color: 'var(--green)', fontSize: '0.8125rem' }}>{msg}</div>
      )}
      {err && (
        <div className="card" style={{ padding: '10px 18px', color: 'var(--red)', fontSize: '0.8125rem' }}>{err}</div>
      )}

      {loading && <div className="empty-state"><div className="muted">載入中...</div></div>}

      {!loading && byType.length === 0 && (
        <div className="empty-state">
          <div className="empty-icon">🗂️</div>
          <div>尚未登錄任何模型版本</div>
          <div className="muted" style={{ fontSize: '0.75rem', marginTop: 6 }}>
            執行任一訓練腳本（如 UnifiedModel/train_range.py），或呼叫一次模型推論即會自動登錄
          </div>
        </div>
      )}

      {byType.map(g => (
        <TypeCard key={g.modelType} {...g} onAction={handleAction} busy={busy} />
      ))}
    </>
  )
}
