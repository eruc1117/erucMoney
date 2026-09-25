// 模型選擇器（Iteration 31）
// ───────────────────────────────────────────────────────────────────────────
// 投票決策與閒置資金共用。清單、預設值、可信度全部來自後端 `/catalog`——
// 前端不再自己維護一份模型名單（Iteration 31 之前有四份各說各話的清單）。
//
// 設計上刻意把 credibility 放在最顯眼的位置。使用者要決定「聽誰的」，
// 而這份資料上多數方向模型的實測結論是「沒有 edge」——不講出來就是誤導。
import { useEffect, useState } from 'react'
import { getCatalog } from '../services/api'

const CRED = {
  proven:      { label: '已驗證',  color: 'var(--green)' },
  weak:        { label: '邊際',    color: 'var(--yellow)' },
  none:        { label: '無 edge', color: 'var(--dim)' },
  unvalidated: { label: '未驗證',  color: 'var(--orange)' },
}

const KIND_ORDER = ['gate', 'magnitude', 'direction', 'reference']
const KIND_TITLE = {
  gate:      '閘門與調節（不投方向，決定押多少、停損放哪、進場價位）',
  magnitude: '量級預測',
  direction: '方向訊號（進加權計分）',
  reference: '參考',
}

export default function ModelPicker({ page, value, onChange, compact = false }) {
  const [models, setModels] = useState([])
  const [blocks, setBlocks] = useState([])
  const [state, setState] = useState('loading')
  const [open, setOpen] = useState(!compact)

  useEffect(() => {
    let alive = true
    setState('loading')
    getCatalog({ page, selectableOnly: true }).then(({ data, error }) => {
      if (!alive) return
      if (error || !data) { setState('error'); return }
      setModels(data.models || [])
      setBlocks(data.blocks || [])
      setState('ok')
      // 首次載入時若外部還沒給選擇，就套用後端預設——
      // 由後端決定預設值，前端寫死會與 model_catalog 分岔
      if (!value && data.defaults?.length) onChange?.(data.defaults)
    })
    return () => { alive = false }
  }, [page])   // eslint-disable-line react-hooks/exhaustive-deps

  const selected = value || []
  const toggle = (key) => {
    const next = selected.includes(key)
      ? selected.filter(k => k !== key)
      : [...selected, key]
    onChange?.(next)
  }

  const groups = KIND_ORDER
    .map(k => [k, models.filter(m => m.kind === k)])
    .filter(([, list]) => list.length)

  const usedBlocks = new Set(
    models.filter(m => selected.includes(m.key)).flatMap(m => m.blocks || []))

  return (
    <div className="card">
      <div className="card-header" style={{ cursor: 'pointer' }} onClick={() => setOpen(o => !o)}>
        <span className="card-title">🎛️ 使用哪些模型</span>
        <span className="muted" style={{ marginLeft: 'auto', fontSize: '0.8125rem' }}>
          {state === 'ok' ? `已選 ${selected.length} / ${models.length}` : ''}
          <span style={{ marginLeft: 8 }}>{open ? '▲' : '▼'}</span>
        </span>
      </div>

      {open && (
        <div className="card-body">
          {state === 'loading' && <div className="empty-state">載入模型目錄…</div>}
          {state === 'error' && (
            <div className="empty-state">
              模型目錄不可用（FastAPI :8000 未啟動）。將使用後端預設模型集合。
            </div>
          )}

          {state === 'ok' && groups.map(([kind, list]) => (
            <div key={kind} style={{ marginBottom: 14 }}>
              <div className="muted" style={{ fontSize: '0.75rem', marginBottom: 6 }}>
                {KIND_TITLE[kind]}
              </div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                {list.map(m => {
                  const on = selected.includes(m.key)
                  const c = CRED[m.credibility] || CRED.unvalidated
                  return (
                    <label key={m.key} title={`${m.target}\n${m.metric}\n${m.note}`}
                           style={{
                             display: 'flex', alignItems: 'center', gap: 6,
                             padding: '6px 10px', borderRadius: 8, cursor: 'pointer',
                             border: `1px solid ${on ? 'var(--accent)' : 'var(--border)'}`,
                             background: on ? 'var(--surface-2)' : 'transparent',
                             opacity: on ? 1 : 0.65,
                           }}>
                      <input type="checkbox" checked={on} onChange={() => toggle(m.key)} />
                      <span>{m.icon} {m.label}</span>
                      <span style={{
                        fontSize: '0.625rem', padding: '1px 6px', borderRadius: 4,
                        color: c.color, border: `1px solid ${c.color}`,
                      }}>{c.label}</span>
                    </label>
                  )
                })}
              </div>
            </div>
          ))}

          {state === 'ok' && selected.length === 0 && (
            <div style={{ color: 'var(--orange)', fontSize: '0.8125rem', marginTop: 4 }}>
              一個模型都沒選——後端會退回預設集合，否則畫面上的決策沒有任何依據。
            </div>
          )}

          {state === 'ok' && !!blocks.length && (
            <div className="muted" style={{ fontSize: '0.75rem', marginTop: 10,
                                            borderTop: '1px solid var(--border)', paddingTop: 10 }}>
              目前這組模型用到的資料：
              {blocks.filter(b => usedBlocks.has(b.name))
                     .map(b => `${b.name}（${b.n_features} 欄，${b.since} 起）`)
                     .join('、') || '—'}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
