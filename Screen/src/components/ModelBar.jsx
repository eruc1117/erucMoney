// 使用中的模型列（Iteration 31）
// ───────────────────────────────────────────────────────────────────────────
// 給不需要勾選、但應該讓使用者知道「這一頁的數字是誰算的」的頁面用。
//
// 這條列存在的理由：Iteration 31 之前，「預測比對」頁密集監控 10 個
// 已證實沒有 edge 的 LSTM，而真正在做買賣決策的四個模型完全不在那一頁上，
// 使用者無從得知自己看的是哪一批模型。
import { useEffect, useState } from 'react'
import { getCatalog } from '../services/api'

const CRED = {
  proven:      { label: '已驗證',  color: 'var(--green)' },
  weak:        { label: '邊際',    color: 'var(--yellow)' },
  none:        { label: '無 edge', color: 'var(--dim)' },
  unvalidated: { label: '未驗證',  color: 'var(--orange)' },
}

export default function ModelBar({ page, note }) {
  const [models, setModels] = useState([])
  const [open, setOpen] = useState(false)

  useEffect(() => {
    let alive = true
    getCatalog({ page }).then(({ data }) => {
      if (alive && data?.models) setModels(data.models)
    })
    return () => { alive = false }
  }, [page])

  if (!models.length) return null

  return (
    <div style={{
      display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 8,
      padding: '10px 14px', marginBottom: 12, borderRadius: 10,
      border: '1px solid var(--border)', background: 'var(--surface)',
      fontSize: '0.8125rem',
    }}>
      <span className="muted">本頁使用的模型：</span>
      {(open ? models : models.slice(0, 6)).map(m => {
        const c = CRED[m.credibility] || CRED.unvalidated
        return (
          <span key={m.key} title={`${m.target}\n${m.metric}\n${m.note}`}
                style={{
                  display: 'inline-flex', alignItems: 'center', gap: 5,
                  padding: '3px 9px', borderRadius: 8,
                  border: '1px solid var(--border)',
                }}>
            {m.icon} {m.label}
            <span style={{
              fontSize: '0.625rem', padding: '0 5px', borderRadius: 4,
              color: c.color, border: `1px solid ${c.color}`,
            }}>{c.label}</span>
          </span>
        )
      })}
      {models.length > 6 && (
        <button className="btn-chip" onClick={() => setOpen(o => !o)}>
          {open ? '收合' : `還有 ${models.length - 6} 個`}
        </button>
      )}
      {note && <span className="muted" style={{ width: '100%', marginTop: 4 }}>{note}</span>}
    </div>
  )
}
