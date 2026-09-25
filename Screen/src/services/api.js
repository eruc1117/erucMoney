// ============================================================
//  API Service — calls Node.js backend (http://localhost:3001)
//  Node.js server proxies /crawler/run → FastAPI (localhost:8000)
// ============================================================

import { getToken, clearSession } from './auth'

// API 位址：設定頁存的 localStorage（階段 2 前端獨立部署用）→ 建置環境變數 → 本機
// 正式網域：前端在 erucmoney.com（GitHub Pages），API 在 api.erucmoney.com（Cloudflare Tunnel → 本機 3001）
const PROD_API = 'https://api.erucmoney.com'
export function defaultApiBase() {
  if (typeof location !== 'undefined' && /(^|\.)erucmoney\.com$/.test(location.hostname)) return PROD_API
  return import.meta.env.VITE_API_URL || 'http://localhost:3001'
}
export function getApiBase() {
  try { const v = localStorage.getItem('api_base'); if (v) return v.replace(/\/+$/, '') } catch { /* ignore */ }
  return defaultApiBase()
}
export function setApiBase(url) {
  try { url ? localStorage.setItem('api_base', url.replace(/\/+$/, '')) : localStorage.removeItem('api_base') } catch { /* ignore */ }
}
const BASE_GETTER = getApiBase

// 單次請求的等待上限。沒有 timeout 的 fetch 在後端卡住時會永遠轉圈，
// 使用者只看到「載入中」，分不出是慢還是壞掉。
const TIMEOUT_MS = 60000

async function request(path, options = {}) {
  const ctrl = new AbortController()
  const timer = setTimeout(() => ctrl.abort(), options.timeout ?? TIMEOUT_MS)
  try {
    const token = getToken()
    const res = await fetch(`${BASE_GETTER()}${path}`, {
      signal: ctrl.signal,
      ...options,
      headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}),
                 ...(options.headers || {}) },
    })

    // 401：憑證無效或過期 → 清掉登入狀態，App 會切回登入頁
    if (res.status === 401 && !path.startsWith('/auth/login')) {
      clearSession()
      return { data: null, notFound: false, error: '登入已過期，請重新登入' }
    }

    // 後端的錯誤說明一律讀出來。
    // 舊版的 404 分支直接回 { data: null, error: null } **而不讀回應內容**，
    // 於是伺服器明明回了「股票 XXXX 資料不足（需 20 筆，目前 0 筆）」，
    // 畫面上卻只顯示「回應格式非預期」——那句話既不是事實，也幫不上任何忙。
    if (!res.ok) {
      let detail = ''
      try { detail = (await res.json())?.detail || '' } catch { /* 非 JSON 回應 */ }
      const msg = detail ? `${detail}（HTTP ${res.status}）` : `HTTP ${res.status}`
      if (res.status === 404) {
        // notFound 仍要保留：個股分析靠它區分「查無此股」與「連線失敗」
        return { data: detail ? { detail } : null, notFound: true, error: msg }
      }
      throw new Error(msg)
    }
    return { data: await res.json(), notFound: false, error: null }
  } catch (err) {
    const msg = err.name === 'AbortError'
      ? `等待逾時（超過 ${Math.round((options.timeout ?? TIMEOUT_MS) / 1000)} 秒）——`
        + '後端可能正在載入模型或處理量過大，稍後再試'
      : err.message
    return { data: null, notFound: false, error: msg }
  }
}

// ── 股票基本資訊 ──────────────────────────────────────────────
// GET /stocks/{stock_id}
export const getStockInfo = (stockId) =>
  request(`/stocks/${stockId}`)

// ── 依預算篩選股票 ─────────────────────────────────────────────
// GET /stocks?max_price={maxPrice}[&industry=X]
export const getStocksByBudget = (maxPrice, industry = null) =>
  request(`/stocks?max_price=${maxPrice}${industry ? `&industry=${encodeURIComponent(industry)}` : ''}`)

// ── 產業類別清單（含各類股票數）────────────────────────────────
// GET /stocks/industries
export const getIndustries = () =>
  request('/stocks/industries')

// ── 追蹤中股票（Overview 頁使用）────────────────────────────────
// GET /stocks?tracked=true[&industry=X]
export const getTrackedStocks = (industry = null) =>
  request(`/stocks?tracked=true${industry ? `&industry=${encodeURIComponent(industry)}` : ''}`)

// ── 每日行情（K線，最近 N 天）─────────────────────────────────
// GET /stocks/{stock_id}/prices?days={days}
export const getStockPrices = (stockId, days = 90) =>
  request(`/stocks/${stockId}/prices?days=${days}`)

// ── 歷史行情（指定日期區間 or 全部）──────────────────────────
// GET /stocks/{stock_id}/prices?start_date=&end_date=  → 指定區間
// GET /stocks/{stock_id}/prices                        → 全部歷史
export const getStockPricesHistory = (stockId, { start_date, end_date } = {}) => {
  if (start_date && end_date) {
    return request(`/stocks/${stockId}/prices?start_date=${start_date}&end_date=${end_date}`)
  }
  return request(`/stocks/${stockId}/prices`)
}

// ── 三大法人籌碼 ──────────────────────────────────────────────
// GET /stocks/{stock_id}/chips?days={days}
export const getChipData = (stockId, days = 20) =>
  request(`/stocks/${stockId}/chips?days=${days}`)

// ── 三大法人持股變化（每日買賣超 + 期間累計 + 收盤價）──────────
// GET /stocks/{stock_id}/institutional?days={days}
export const getInstitutionalFlow = (stockId, days = 60) =>
  request(`/stocks/${stockId}/institutional?days=${days}`)

// ── 觸發爬蟲（近期資料 or 歷史補充）────────────────────────────
// POST /crawler/run  Body: { stock_id, start_date?, end_date? }
// options: { start_date: 'YYYY-MM-DD', end_date: 'YYYY-MM-DD' }（歷史補充用）
export const triggerCrawler = (stockId, options = {}) =>
  request('/crawler/run', {
    method: 'POST',
    body: JSON.stringify({ stock_id: stockId, ...options }),
  })

// ── 爬蟲執行狀態 ──────────────────────────────────────────────
// GET /crawler/status/{stock_id}
// Response: { stock_id, status: "running" | "idle" }
export const getCrawlerStatus = (stockId) =>
  request(`/crawler/status/${stockId}`)

// ── 取得新聞列表 ──────────────────────────────────────────────
// GET /news
export const getNewsList = () =>
  request('/news')

// ── 新聞輸入 ──────────────────────────────────────────────────
// POST /news  Body: { platform, title, content, stock_tickers }
export const submitNews = (payload) =>
  request('/news', {
    method: 'POST',
    body: JSON.stringify(payload),
  })

// ── 修改新聞 ──────────────────────────────────────────────────
// PUT /news/:id  Body: { platform, title, content, stock_tickers }
export const updateNews = (id, payload) =>
  request(`/news/${id}`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  })

// ── 刪除新聞 ──────────────────────────────────────────────────
// DELETE /news/:id
export const deleteNews = (id) =>
  request(`/news/${id}`, { method: 'DELETE' })

// ── 觸發新聞爬蟲 ──────────────────────────────────────────────
// POST /crawler/news  Body: { start_date?, end_date?, keywords? }
// 無日期 → 即時首頁；有日期 → Wayback Machine 歷史爬取（上限 7 天）
// keywords → 字串陣列，爬完後只保留包含任一關鍵字的文章（空陣列 = 不過濾）
export const triggerNewsCrawl = ({ start_date, end_date, keywords } = {}) =>
  request('/crawler/news', {
    method: 'POST',
    body: JSON.stringify({
      start_date: start_date || null,
      end_date:   end_date   || null,
      keywords:   keywords?.length ? keywords : null,
    }),
  })

// ── 查詢新聞爬蟲狀態 ──────────────────────────────────────────
// GET /crawler/news/status  → { status: "running"|"idle", last_count: N }
export const getNewsCrawlStatus = () =>
  request('/crawler/news/status')

// ── 模型預測 ──────────────────────────────────────────────────
// GET /model/predict?stock_id={id}&model={lstm|prophet|gru}&days=7
// 代號先正規化再送出：使用者貼上的代號常夾帶空白或全形數字，
// 而後端查不到時只會說「資料不足」，看不出是輸入問題。
export const normaliseStockId = (v) =>
  String(v ?? '').trim().replace(/[０-９]/g, c => String.fromCharCode(c.charCodeAt(0) - 0xfee0))

// market：'tw'（stock_daily_prices，預設）或 'us'（us_daily_prices）。
// 同一批跨股票 LSTM，輸入是 z-score 後的收盤價視窗，與價格尺度無關。
export const getPrediction = (stockId, model = 'lstm', days = 7, market = 'tw') =>
  request(`/model/predict?stock_id=${encodeURIComponent(normaliseStockId(stockId))}`
          + `&model=${model}&days=${days}&market=${market}`)

// ── 手動重訓 ──────────────────────────────────────────────────
// POST /model/retrain  Body: { stock_id }
export const retrainModel = (stockId) =>
  request('/model/retrain', {
    method: 'POST',
    body: JSON.stringify({ stock_id: stockId }),
  })

// ── 儲存預測結果 ───────────────────────────────────────────────
// POST /predictions  Body: { stock_id, model_key, model_label, predictions, market }
export const savePrediction = (payload) =>
  request('/predictions', {
    method: 'POST',
    body: JSON.stringify(payload),
  })

// ── 取得所有已儲存預測（列表）────────────────────────────────────
// GET /predictions[?stock_id=&model_key=&status=matured|pending&sort=&market=tw|us]
export const getSavedPredictions = (filters = {}) => {
  const qs = new URLSearchParams(
    Object.entries(filters).filter(([, v]) => v != null && v !== '')
  ).toString()
  return request(`/predictions${qs ? `?${qs}` : ''}`)
}

// ── 依模型彙總線上表現（含天真基準對照）──────────────────────────
// GET /predictions/summary[?market=tw|us] —— 台幣與美元的 MAE 不能混在一列，一律帶市場
export const getPredictionSummary = (market = null) =>
  request(`/predictions/summary${market ? `?market=${market}` : ''}`)

// ── 刪除已儲存預測 ─────────────────────────────────────────────
// DELETE /predictions/:id
export const deleteSavedPrediction = (id) =>
  request(`/predictions/${id}`, { method: 'DELETE' })

// ── 取得預測 + 實際比對 ────────────────────────────────────────
// GET /predictions/:id/compare
export const getPredictionCompare = (id) =>
  request(`/predictions/${id}/compare`)

// ── 使用者持股（投票決策的條件之一）────────────────────────────────────────
// GET /holdings —— 回 { items, summary }，市值與損益以最新收盤價計算
export const getHoldings = () => request('/holdings')

// POST /holdings —— 同一 stock_id 視為更新持倉
export const saveHolding = (payload) =>
  request('/holdings', { method: 'POST', body: JSON.stringify(payload) })

export const updateHolding = (id, payload) =>
  request(`/holdings/${id}`, { method: 'PUT', body: JSON.stringify(payload) })

export const deleteHolding = (id) =>
  request(`/holdings/${id}`, { method: 'DELETE' })

// ── 交易紀錄（分批進出與已實現損益）──────────────────────────────────────────
// 持倉由台帳回放推導：有交易紀錄的股票不能直接改持倉，只能新增或刪除交易。
// GET /holdings/trades[?stock_id=]
export const getTrades = (stockId = null) =>
  request(`/holdings/trades${stockId ? `?stock_id=${encodeURIComponent(stockId)}` : ''}`)

// POST /holdings/trades —— fee/tax 留空則依台股費率自動估算
export const addTrade = (payload) =>
  request('/holdings/trades', { method: 'POST', body: JSON.stringify(payload) })

export const deleteTrade = (id) =>
  request(`/holdings/trades/${id}`, { method: 'DELETE' })

// GET /holdings/trades/estimate —— 手續費與證交稅試算
export const estimateTradeCosts = (side, shares, price) =>
  request(`/holdings/trades/estimate?side=${side}&shares=${shares}&price=${price}`)

// GET /holdings/review —— 系統建議 vs 使用者實際動作，附事後 5 日報酬
export const getDecisionReview = () => request('/holdings/review')

// ── 資料新鮮度（預測比對要能運作，前提是目標日期的收盤價已進資料庫）────────
// GET /data/freshness —— 每檔最後交易日與落後幾個交易日
export const getDataFreshness = (stockIds = null) =>
  request(`/data/freshness${stockIds?.length ? `?stock_ids=${stockIds.join(',')}` : ''}`)

// POST /data/backfill —— 把落後的補到最新（FinMind 匿名額度 30 次/小時）
export const backfillData = (stockIds = null, maxStocks = 8) => {
  const p = new URLSearchParams({ max_stocks: maxStocks })
  if (stockIds?.length) p.set('stock_ids', stockIds.join(','))
  return request(`/data/backfill?${p}`, { method: 'POST', timeout: 180000 })
}

// GET /data/freshness/exogenous —— 美股／台指期／韓日指數三張表的最新日期
export const getExogenousFreshness = () => request('/data/freshness/exogenous')

// POST /data/backfill/exogenous —— 把上述三張表補到最新（14 次 FinMind 呼叫）
export const backfillExogenous = () =>
  request('/data/backfill/exogenous', { method: 'POST', timeout: 180000 })

// ── 閒置資金一週配置 ──────────────────────────────────────────────────────
// 最大化的是「風險調整後的期望價差空間」，不是預測報酬——
// 回應的 honesty / diagnostics 會說明這個限制，前端要照樣顯示。
export const getCashPlan = ({ amount, risk_budget = 0.02, max_positions = 5,
                              exclude_held = false, models } = {}) =>
  request(`/cash/plan?${new URLSearchParams({
    amount, risk_budget, max_positions, exclude_held: String(exclude_held),
    ...(models?.length ? { models: models.join(',') } : {}),
  })}`)

// ── 角色化決策 + 本週交易計畫 ──────────────────────────────────────────────
// GET /voting/roles?stock_id= —— 六個角色各自的訊號與理由
export const getRoleDecision = (stockId, models) =>
  request(`/voting/roles?${new URLSearchParams({
    stock_id: stockId, ...(models?.length ? { models: models.join(',') } : {}),
  })}`)

// ── 模型目錄（Iteration 31）───────────────────────────────────────────────
// 「有哪些模型、預設開哪些、各自的可信度如何」的唯一來源。
// page 帶了就只回該頁面適用的；selectableOnly 只回可勾選的。
export const getCatalog = ({ page, selectableOnly = false } = {}) =>
  request(`/catalog?${new URLSearchParams({
    ...(page ? { page } : {}),
    ...(selectableOnly ? { selectable_only: 'true' } : {}),
  })}`)

// GET /voting/weekly-plan?stock_id= —— 本週 5 個交易日的每日動作
export const getWeeklyPlan = (stockId) =>
  request(`/voting/weekly-plan?stock_id=${encodeURIComponent(stockId)}`)

// ── 模型版本管理（凍結／長期服役）──────────────────────────────────────────
// 「凍結」＝把目前的 candidate 固定成長期服役版本，重訓不再動到它，
// 同時自動開出下一版 candidate 繼續迭代。
// GET /models —— 版本清單 + 線上實測指標（需 FastAPI :8000）
export const getModelVersions = (modelType = null) =>
  request(`/models${modelType ? `?model_type=${encodeURIComponent(modelType)}` : ''}`)

// GET /models/registry —— 只讀清單，FastAPI 未啟動時的後備
export const getModelRegistry = () => request('/models/registry')

// POST /models/:type/freeze
export const freezeModel = (modelType, note = null) =>
  request(`/models/${encodeURIComponent(modelType)}/freeze`, {
    method: 'POST', body: JSON.stringify({ note }),
  })

// POST /models/version/:id/serve —— 切換服役版本（只能指定已凍結的版本）
export const serveModelVersion = (versionId) =>
  request(`/models/version/${versionId}/serve`, { method: 'POST' })

// POST /models/version/:id/retire
export const retireModelVersion = (versionId) =>
  request(`/models/version/${versionId}/retire`, { method: 'POST' })

// POST /models/evaluate[?apply=1] —— 回填實際值 + 重算；apply=1 才會自動凍結
export const evaluateModels = (apply = false) =>
  request(`/models/evaluate${apply ? '?apply=1' : ''}`, { method: 'POST' })

// ── 開盤跳空預測（盤前參考資訊，非買賣訊號）────────────────────────────────
// GET /gap/predict[?stock_ids=2330,2303]
export const getGapPrediction = (stockIds = null) =>
  request(`/gap/predict${stockIds?.length ? `?stock_ids=${stockIds.join(',')}` : ''}`)

// ── 週振幅預測（波段選股；振幅大不代表會漲）──────────────────────────────
// GET /gap/weekly-range[?only_significant=true]
export const getWeeklyRange = (onlySignificant = false) =>
  request(`/gap/weekly-range${onlySignificant ? '?only_significant=true' : ''}`)

// ── 投票決策 ──────────────────────────────────────────────────────────────
// GET /voting
export const getVotingResults = () => request('/voting')

// GET /voting/:stockId
export const getVotingHistory = (stockId) => request(`/voting/${stockId}`)

// POST /voting/run  Body: { stock_ids: [...] }
export const triggerVoting = (stockIds, models) =>
  request('/voting/run', {
    method: 'POST',
    // models 省略時後端用 model_catalog 的預設集合（Iteration 31）
    body: JSON.stringify({ stock_ids: stockIds, ...(models?.length ? { models } : {}) }),
  })

// GET /voting/status
export const getVotingStatus = () => request('/voting/status')

// ── 美股（Iteration 32）────────────────────────────────────────────────────
// GET /us/overview[?days=60] —— 12 檔報價 + 下一場開盤跳空預測 + 資料新鮮度
// 訊號來自台股與韓日的當日盤（美股開盤前 8 小時已收盤）；
// 只用美股自身歷史時走查相關僅 0.0085，等於沒有。
export const getUsOverview = (days = 60) => request(`/us/overview?days=${days}`)

// GET /us/gap[?tickers=TSM,SPY]
export const getUsGap = (tickers = null) =>
  request(`/us/gap${tickers?.length ? `?tickers=${tickers.join(',')}` : ''}`)

// GET /us/tickers —— 12 檔標的清單（趨勢預測頁切到美股時的下拉選單）
export const getUsTickers = () => request('/us/tickers')

// ── 每週自動預測（Iteration 37）──────────────────────────────
// GET /forecast/weekly：最新一次執行；POST /forecast/weekly/run：手動補跑
export const getWeeklyForecast = () => request('/forecast/weekly', { timeout: 90000 })
export const getWeeklyForecastStatus = () => request('/forecast/weekly/status')

// ── 帳號（階段 1，多使用者）──────────────────────────────────────
export const login = (username, password) =>
  request('/auth/login', { method: 'POST', body: JSON.stringify({ username, password }), timeout: 15000 })
export const getMe = () => request('/auth/me', { timeout: 15000 })
export const changePassword = (old_password, new_password) =>
  request('/auth/change-password', { method: 'POST', body: JSON.stringify({ old_password, new_password }) })
export const listUsers = () => request('/auth/users')
export const createUser = (body) => request('/auth/users', { method: 'POST', body: JSON.stringify(body) })
export const updateUser = (id, body) => request(`/auth/users/${id}`, { method: 'PUT', body: JSON.stringify(body) })
export const deleteUser = (id) => request(`/auth/users/${id}`, { method: 'DELETE' })
export const getHealth = () => request('/health', { timeout: 8000 })
export const runWeeklyForecast = () => request('/forecast/weekly/run', { method: 'POST' })
