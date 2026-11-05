// 使用說明模式（Iteration 89）：每個頁簽一份「這頁做什麼／怎麼用／怎麼看／注意」。
//
// 做成「模式」而不是每頁一個問號：開著的時候換頁簽，說明跟著換成那一頁的，
// 第一次用的人可以一頁一頁看過去；看熟了關掉，版面完全不佔位置。開關存在 localStorage。
// 內容集中在 lib/helpContent.js（依頁簽 key），兩個前端（Screen、統一前端 src/stock）共用同一份。
import { useEffect, useState } from 'react'
import { HELP, HELP_SECTIONS } from '../lib/helpContent'

const HELP_KEY = 'ui.help'   // '1' 開、其他關

export function useHelpMode() {
  const [on, setOn] = useState(() => {
    try { return localStorage.getItem(HELP_KEY) === '1' } catch { return false }   // 隱私模式下 localStorage 可能拋例外
  })
  useEffect(() => {
    try { localStorage.setItem(HELP_KEY, on ? '1' : '0') } catch { /* 忽略 */ }
  }, [on])
  return [on, () => setOn(v => !v)]
}

export function HelpToggle({ on, onToggle }) {
  return (
    <div className="ui-toggle" title={on ? '關閉使用說明模式' : '開啟使用說明模式：每個頁簽上方顯示該頁的使用說明'}>
      <button className={on ? 'active' : ''} aria-pressed={on} aria-label="使用說明模式" onClick={onToggle}>
        ？<span className="help-label"> 使用說明</span>
      </button>
    </div>
  )
}

export default function PageHelp({ pageKey, title, onClose }) {
  const h = HELP[pageKey]
  return (
    <section className="card help-panel" aria-label="使用說明">
      <div className="card-header">
        <div className="card-title">使用說明{title ? `：${title}` : ''}</div>
        <button className="btn-secondary" onClick={onClose}>關閉說明</button>
      </div>
      {!h ? (
        <div className="help-what muted">這個頁簽還沒有使用說明。</div>
      ) : (
        <>
          <div className="help-what">{h.what}</div>
          <div className="help-grid">
            {HELP_SECTIONS.filter(s => h[s.key]?.length).map(s => {
              const List = s.ordered ? 'ol' : 'ul'
              return (
                <div className="help-sec" key={s.key}>
                  <h4>{s.label}</h4>
                  <List>{h[s.key].map((t, i) => <li key={i}>{t}</li>)}</List>
                </div>
              )
            })}
          </div>
        </>
      )}
    </section>
  )
}
