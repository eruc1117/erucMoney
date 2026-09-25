import { useState, useEffect } from 'react'
import Login          from './pages/Login'
import Account        from './pages/Account'
import { getUser, onAuthChange, takeTokenFromHash, setSession, clearSession, getToken } from './services/auth'
import { getMe } from './services/api'

// 行事曆平台交接過來的 token（#token=…）：先收下，再向後端確認身分
const HANDOFF = takeTokenFromHash()
import Sidebar        from './components/Sidebar'
import Topbar         from './components/Topbar'
import Overview       from './pages/Overview'
import BudgetSearch   from './pages/BudgetSearch'
import StockAnalysis  from './pages/StockAnalysis'
import NewsInput      from './pages/NewsInput'
import NewsSentiment  from './pages/NewsSentiment'
import Prediction          from './pages/Prediction'
import PredictionCompare   from './pages/PredictionCompare'
import QueryHistory        from './pages/QueryHistory'
import VotingDashboard    from './pages/VotingDashboard'
import ModelVersions      from './pages/ModelVersions'
import Holdings           from './pages/Holdings'
import IdleCash           from './pages/IdleCash'
import USMarket           from './pages/USMarket'
import InstitutionalHoldings from './pages/InstitutionalHoldings'
import WeeklyForecast     from './pages/WeeklyForecast'

const PAGE_TITLES = {
  overview:   '市場總覽',
  budget:     '預算查詢',
  stock:      '個股分析',
  news:       '新聞輸入',
  sentiment:  '新聞情緒',
  prediction: '趨勢預測',
  compare:    '預測比對',
  weekly:     '每週全模型預測',
  history:    '查詢紀錄',
  voting:     '投票決策',
  models:     '模型版本',
  holdings:   '我的持股',
  cash:       '閒置資金',
  us:         '美股開盤跳空',
  institutional: '三大法人持股變化',
  account:    '帳號',
}

export default function App() {
  const [page, setPage]   = useState('overview')
  const [stock, setStock] = useState('')
  const [user, setUser]   = useState(getUser())

  // 登入／登出（含 401 自動登出）都經 auth.js 廣播；沒登入就只顯示登入頁
  useEffect(() => onAuthChange(setUser), [])
  // 單一登入交接：用交接來的 token 問 /auth/me，成功就把真正的使用者資料存起來
  useEffect(() => {
    if (!HANDOFF) return
    getMe().then(({ data, error }) => {
      if (error || !data) { clearSession(); return }
      setSession(getToken(), { id: data.id, username: data.username, role: data.role, display_name: data.display_name })
    })
  }, [])
  if (!user) return <Login />

  // 從其他頁面跳轉到個股分析
  function goToStock(stockId) {
    setStock(stockId)
    setPage('stock')
  }

  return (
    <div className="app">
      <Sidebar currentPage={page} onNavigate={setPage} />
      <div className="main">
        <Topbar title={PAGE_TITLES[page]} user={user} onAccount={() => setPage('account')} />
        <main className="content">
          {page === 'account'    && <Account />}
          {page === 'overview'   && <Overview onSelectStock={goToStock} />}
          {page === 'budget'     && <BudgetSearch  onSelectStock={goToStock} />}
          {page === 'stock'      && <StockAnalysis initStock={stock} />}
          {page === 'news'       && <NewsInput />}
          {page === 'sentiment'  && <NewsSentiment />}
          {page === 'prediction' && <Prediction />}
          {page === 'compare'    && <PredictionCompare />}
          {page === 'weekly'     && <WeeklyForecast onSelectStock={goToStock} />}
          {page === 'history'    && <QueryHistory onSelectStock={goToStock} />}
          {page === 'voting'     && <VotingDashboard />}
          {page === 'models'     && <ModelVersions />}
          {page === 'holdings'   && <Holdings />}
          {page === 'cash'       && <IdleCash />}
          {page === 'us'         && <USMarket />}
          {page === 'institutional' && <InstitutionalHoldings initStock={stock} />}
        </main>
      </div>
    </div>
  )
}
