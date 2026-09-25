/**
 * FastAPI Proxy 工具
 * 將請求轉發至 Crawler FastAPI (localhost:8000)
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
    hostname: 'localhost',
    port,
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

module.exports = { proxyToFastAPI }
