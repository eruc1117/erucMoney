// 張／零股單位（Iteration 24）
//
// 資料庫一律以「股數」儲存——那是唯一不會因為單位換算產生誤差的表示法，
// 也是損益計算真正用到的量。但台股的日常語彙是「張」（1 張 = 1000 股），
// 而零股交易早已普及（盤中零股自 2020 年開放），
// 要使用者把「2 張又 500 股」自己心算成 2500 再填進去是沒有道理的。
//
// 所以：**輸入與顯示用張／零股，儲存與計算用股數。**

export const SHARES_PER_LOT = 1000

export function splitShares(shares) {
  const n = Math.max(Number(shares) || 0, 0)
  return { lots: Math.floor(n / SHARES_PER_LOT), odd: Math.round(n % SHARES_PER_LOT) }
}

export function joinShares(lots, odd) {
  return (Number(lots) || 0) * SHARES_PER_LOT + (Number(odd) || 0)
}

/** 「2 張 500 股」；不足一張時只顯示零股，整張時不顯示 0 股。 */
export function formatShares(shares) {
  const n = Number(shares) || 0
  const { lots, odd } = splitShares(n)
  if (lots === 0) return `${odd.toLocaleString('zh-TW')} 股`
  if (odd === 0) return `${lots.toLocaleString('zh-TW')} 張`
  return `${lots.toLocaleString('zh-TW')} 張 ${odd} 股`
}

/** 顯示元件：主要看張，滑鼠移上去看確切股數。 */
export function Shares({ value, muted }) {
  const n = Number(value) || 0
  return (
    <span title={`${n.toLocaleString('zh-TW')} 股`}
          style={muted ? { color: 'var(--dim)' } : undefined}>
      {formatShares(n)}
    </span>
  )
}

/**
 * 輸入元件：張 + 零股兩欄，對外只吐股數。
 *
 * 零股欄限制 0~999：填 1000 應該進位成一張，讓它停在「0 張 1000 股」
 * 只會讓後續顯示變得奇怪。
 */
export function SharesInput({ value, onChange, disabled }) {
  const { lots, odd } = splitShares(value)
  const emit = (l, o) => onChange(joinShares(l, Math.min(Math.max(Number(o) || 0, 0), 999)))
  const total = Number(value) || 0

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
      <input className="ctrl-select" type="number" min="0" step="1" disabled={disabled}
             value={lots === 0 && total === 0 ? '' : lots}
             placeholder="0" onChange={e => emit(e.target.value, odd)}
             style={{ width: 74 }} />
      <span style={{ fontSize: '0.75rem', color: 'var(--dim)' }}>張</span>
      <input className="ctrl-select" type="number" min="0" max="999" step="1" disabled={disabled}
             value={odd === 0 && total === 0 ? '' : odd}
             placeholder="0" onChange={e => emit(lots, e.target.value)}
             style={{ width: 74 }} />
      <span style={{ fontSize: '0.75rem', color: 'var(--dim)' }}>股</span>
      {total > 0 && (
        <span style={{ fontSize: '0.6875rem', color: 'var(--dim)', marginLeft: 2 }}>
          ＝{total.toLocaleString('zh-TW')} 股
        </span>
      )}
    </div>
  )
}
