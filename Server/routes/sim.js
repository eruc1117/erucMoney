/**
 * 公開的交易模擬（Iteration 60）：不用登入。
 *
 *   GET  /sim/replay?start&end&capital&run_id&stop_loss_pct&rel_dd_guard&limit_slip&max_attempts
 *        歷史回放（引擎規則 vs 照單全收，候選期間）——同 /trading/engine/replay，只是不要登入
 *   POST /sim/run   { text, start, end, capital }
 *        自訂交易指令：使用者寫幾行「日期 買/賣 代號 數量」，設定期間與資金，跑完給收益對 0050
 *
 * 兩個都只讀資料庫、不寫；算一次約 1～3 秒，所以設了輸入上限（文字 4000 字、期間 8 年）並靠全域 rate-limit 擋濫用。
 */
const { Router } = require('express')
const { proxyToFastAPI } = require('../lib/proxy')

const router = Router()
const CRAWLER_DOWN = res => res.status(503).json({ detail: '爬蟲服務未啟動，請執行 python main.py --mode server' })
const DATE = /^\d{4}-\d{2}-\d{2}$/
const MAX_TEXT = 4000

router.get('/replay', (req, res) => {
  const qs = new URLSearchParams()
  for (const k of ['start', 'end', 'capital', 'run_id', 'stop_loss_pct', 'rel_dd_guard', 'limit_slip', 'max_attempts']) {
    if (req.query[k] != null && req.query[k] !== '') qs.set(k, String(req.query[k]))
  }
  const q = qs.toString()
  proxyToFastAPI({ port: 8000, path: `/trading/engine/replay${q ? `?${q}` : ''}`, res, onError: () => CRAWLER_DOWN(res) })
})

router.post('/run', (req, res) => {
  const { text, start, end, capital } = req.body ?? {}
  if (typeof text !== 'string' || !text.trim()) return res.status(400).json({ detail: 'text 要是指令文字（一行一筆：日期 買/賣 代號 數量）' })
  if (text.length > MAX_TEXT) return res.status(400).json({ detail: `指令文字最多 ${MAX_TEXT} 字` })
  if (!DATE.test(String(start || '')) || !DATE.test(String(end || ''))) return res.status(400).json({ detail: 'start／end 要是 YYYY-MM-DD' })
  const cap = capital == null || capital === '' ? 1000000 : Number(capital)
  if (!(cap > 0) || cap > 1e12) return res.status(400).json({ detail: 'capital 要是 > 0 的數字' })
  proxyToFastAPI({ port: 8000, path: '/trading/sim', method: 'POST', body: { text, start, end, capital: cap }, res, onError: () => CRAWLER_DOWN(res) })
})

module.exports = router
