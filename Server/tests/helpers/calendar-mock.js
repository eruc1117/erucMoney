/**
 * 假的行事曆登入服務（meeting_API_Server 的 POST /api/auth/login）。
 * routes/auth.js 用全域 fetch（undici），nock 攔不到，所以直接起一個真的 http 伺服器。
 *
 *   const cal = await startFakeCalendar()      // 並把 process.env.AUTH_API_URL 指過去
 *   cal.reply = (req) => ({ status: 200, body: {...} })
 *   cal.calls                                  // 收到的 body
 *   await cal.close()                          // 關掉並清 AUTH_API_URL
 */
const express = require('express')

async function startFakeCalendar() {
  const app = express()
  app.use(express.json())
  const state = { calls: [], reply: () => ({ status: 404, body: { message: '登入失敗，帳號不存在', data: {}, error: { code: 'E008_ACCOUNT_NOT_EXIST' } } }) }
  app.post('/api/auth/login', (req, res) => {
    state.calls.push(req.body)
    const out = state.reply(req)
    res.status(out.status).json(out.body)
  })
  const server = await new Promise(resolve => { const s = app.listen(0, '127.0.0.1', () => resolve(s)) })
  const port = server.address().port
  const prev = process.env.AUTH_API_URL
  process.env.AUTH_API_URL = `http://127.0.0.1:${port}`
  return {
    port,
    get calls() { return state.calls },
    set reply(fn) { state.reply = fn },
    close: () => new Promise(resolve => {
      if (prev === undefined) delete process.env.AUTH_API_URL; else process.env.AUTH_API_URL = prev
      server.close(() => resolve())
    }),
  }
}

module.exports = { startFakeCalendar }
