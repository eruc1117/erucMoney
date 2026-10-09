/**
 * FastAPI Proxy 工具
 * 將請求轉發至 Crawler FastAPI (localhost:8000)
 *
 * 測試用：環境變數 FASTAPI_HOST / FASTAPI_PORT 可把目標改到假伺服器；沒設就是原本的 localhost 與呼叫端給的 port。
 */
const http = require('http')

/**
 * @param {object} opts
 * @param {string}   opts.path      - FastAPI 路徑（如 '/crawler/run'）
 * @param {string}   [opts.method]  - HTTP method，預設 'GET'
 * @param {object}   [opts.body]    - POST body（會序列化為 JSON）
 * @param {object}   opts.res       - Express res 物件
 * @param {Function} [opts.onError] - 連線失敗時的自訂處理；預設回傳 503
 */
function proxyToFastAPI({ path, method = 'GET', body = null, res, onError, port = 8000 }) {
  const bodyStr = body ? JSON.stringify(body) : ''
  const options = {
    hostname: process.env.FASTAPI_HOST || 'localhost',
    port: process.env.FASTAPI_PORT ? Number(process.env.FASTAPI_PORT) : port,
    path,
    method,
    headers: {
      'Content-Type': 'application/json',
      ...(bodyStr && { 'Content-Length': Buffer.byteLength(bodyStr) }),
    },
  }

  const req = http.request(options, proxyRes => {
    let data = ''
    proxyRes.on('data', chunk => { data += chunk })
    proxyRes.on('end', () => {
      // 必須沿用上游狀態碼。舊版一律 res.json(...) 送出 200，
      // 使上游的 503 `{"detail": "模型尚未訓練"}` 在前端看起來是成功回應，
      // 前端拿到物件卻當成陣列 → `data.map is not a function`。
      const status = proxyRes.statusCode || 502
      try {
        res.status(status).json(JSON.parse(data))
      } catch {
        // 上游回的不是 JSON（例如 FastAPI 未攔截的例外會回純文字 Internal Server Error）
        res.status(status >= 400 ? status : 502).json({
          detail: data ? String(data).slice(0, 300) : 'Invalid response from upstream service',
          upstream_status: status,
        })
      }
    })
  })

  req.on('error', () => {
    if (onError) {
      onError()
    } else {
      res.status(503).json({ status: 'error', detail: 'Crawler service unavailable (FastAPI not running)' })
    }
  })

  if (bodyStr) req.write(bodyStr)
  req.end()
}

/**
 * 向 FastAPI 取 JSON 回來給 Node 端用（不是轉給前端）。連不上或非 JSON 都 reject。
 *   const data = await fetchFastAPI({ port: 8000, path: '/portfolio/candidate' })
 */
function fetchFastAPI({ path, port = 8000, timeout = 15000 }) {
  return new Promise((resolve, reject) => {
    const req = http.get({ hostname: process.env.FASTAPI_HOST || 'localhost',
                           port: process.env.FASTAPI_PORT ? Number(process.env.FASTAPI_PORT) : port, path, timeout }, r => {
      let data = ''
      r.on('data', c => { data += c })
      r.on('end', () => {
        try {
          const json = JSON.parse(data)
          if ((r.statusCode || 500) >= 400) return reject(new Error(json.detail || `upstream ${r.statusCode}`))
          resolve(json)
        } catch { reject(new Error(`upstream ${r.statusCode}: ${String(data).slice(0, 120)}`)) }
      })
    })
    req.on('timeout', () => req.destroy(new Error('upstream timeout')))
    req.on('error', reject)
  })
}

module.exports = { proxyToFastAPI, fetchFastAPI }
