const NAV_ITEMS = [
  { key: 'overview',   icon: '🏠', label: '市場總覽' },
  { key: 'budget',     icon: '💰', label: '預算查詢' },
  { key: 'stock',      icon: '📈', label: '個股分析' },
  { key: 'institutional', icon: '🏦', label: '法人持股' },
  { key: 'news',       icon: '📝', label: '新聞輸入' },
  { key: 'sentiment',  icon: '📰', label: '新聞情緒' },
  { key: 'prediction', icon: '🤖', label: '趨勢預測' },
  { key: 'compare',    icon: '📊', label: '預測比對' },
  { key: 'weekly',     icon: '📅', label: '週預測' },
  { key: 'history',    icon: '📋', label: '查詢紀錄' },
  { key: 'holdings',   icon: '💼', label: '我的持股' },
  { key: 'cash',       icon: '💵', label: '閒置資金' },
  { key: 'us',         icon: '🇺🇸', label: '美股跳空' },
  { key: 'voting',     icon: '🗳️', label: '投票決策' },
  { key: 'models',     icon: '🗂️', label: '模型版本' },
  { key: 'account',    icon: '👤', label: '帳號' },
]

export default function Sidebar({ currentPage, onNavigate }) {
  return (
    <aside className="sidebar">
      <div className="sidebar-brand">
        <div className="brand-icon">📊</div>
        <div>
          <div className="brand-name">智慧投資</div>
          <div className="brand-sub">AI Stock Dashboard</div>
        </div>
      </div>

      <nav className="sidebar-nav">
        {NAV_ITEMS.map(item => (
          <button
            key={item.key}
            className={`nav-item${currentPage === item.key ? ' active' : ''}`}
            onClick={() => onNavigate(item.key)}
          >
            <span className="nav-icon">{item.icon}</span>
            <span>{item.label}</span>
          </button>
        ))}
      </nav>

      <div className="sidebar-footer">
        <div className="sys-status"><span className="dot green" /><span>爬蟲就緒</span></div>
        <div className="sys-status"><span className="dot blue"  /><span>模型就緒</span></div>
        <div className="api-stack">Node.js :3001 · FastAPI :8000<br />PostgreSQL · MongoDB</div>
      </div>
    </aside>
  )
}
