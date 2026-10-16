// 合成測試資料的警示（Iteration 75）：模擬結果的 source.kind 是 synthetic 時顯示，真實行情不顯示。
export default function SourceBanner({ source }) {
  if (source?.kind !== 'synthetic') return null
  return <div className="note-box" style={{ color: 'var(--orange)', margin: '0 1.25rem .6rem' }}>⚠ 這是{source.label}：隨機漫步產生的假行情，不是真實股價，數字沒有任何投資意義，只用來試功能。</div>
}
