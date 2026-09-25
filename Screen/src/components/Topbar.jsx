import { useState, useEffect } from 'react'
import { useTheme } from '../theme'

// 外觀設定：主題與字級。兩者都存在 localStorage，重開仍在。
// 放在頂欄而不是設定頁，是因為調字級這件事需要當場看到結果才知道合不合適。
function UiSettings() {
  const { theme, size, toggleTheme, setSize } = useTheme()
  return (
    <>
      <div className="ui-toggle" title="字級">
        {[['sm', '小'], ['md', '中'], ['lg', '大']].map(([k, label]) => (
          <button key={k} className={size === k ? 'active' : ''}
                  onClick={() => setSize(k)}>{label}</button>
        ))}
      </div>
      <div className="ui-toggle" title={theme === 'dark' ? '切換為淺色' : '切換為深色'}>
        <button className="active" onClick={toggleTheme}>
          {theme === 'dark' ? '☾ 深色' : '☼ 淺色'}
        </button>
      </div>
    </>
  )
}

function isMarketOpen() {
  const now = new Date()
  const wd = now.getDay()
  const h = now.getHours()
  const m = now.getMinutes()
  if (wd < 1 || wd > 5) return false
  const mins = h * 60 + m
  return mins >= 9 * 60 && mins < 13 * 60 + 30
}

export default function Topbar({ title, user, onAccount }) {
  const [time, setTime] = useState('')
  const [open, setOpen] = useState(false)

  useEffect(() => {
    const tick = () => {
      setTime(new Date().toLocaleTimeString('zh-TW', { hour12: false }))
      setOpen(isMarketOpen())
    }
    tick()
    const id = setInterval(tick, 1000)
    return () => clearInterval(id)
  }, [])

  return (
    <header className="topbar">
      <h1 className="page-title">{title}</h1>

      <div className="topbar-right">
        <div className="index-ticker">
          <span className="idx-label">加權指數</span>
          <span className="idx-val up">21,456.83</span>
          <span className="idx-chg up">▲ 312.45 (1.48%)</span>
        </div>
        <div className="idx-divider" />
        <div className="index-ticker">
          <span className="idx-label">OTC指數</span>
          <span className="idx-val up">228.74</span>
          <span className="idx-chg up">▲ 2.31 (1.02%)</span>
        </div>
        <div className={`market-badge${open ? ' open' : ''}`}>
          <span className={`dot ${open ? 'green' : 'red'}`} />
          <span>{open ? '開市中' : '休市'}</span>
        </div>
        <div className="time-display">{time}</div>
        <div className="idx-divider" />
        <UiSettings />
        {user && (
          <div className="ui-toggle" title="帳號">
            <button className="active" onClick={onAccount}>👤 {user.display_name || user.username}</button>
          </div>
        )}
      </div>
    </header>
  )
}
