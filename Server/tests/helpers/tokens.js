/**
 * 直接簽測試用 JWT（不必每次走登入）。密鑰 = .env.test 的 JWT_SECRET。
 *   localToken({ id, role, name })          本系統 /auth/login 簽的形狀 { sub, role, name }
 *   calendarToken({ id, username, role })   行事曆平台簽的形狀 { id, username, role }
 */
const jwt = require('jsonwebtoken')

const SECRET = process.env.JWT_SECRET

function localToken({ id = 1, role = 'admin', name = 'admin' } = {}, opts = {}) {
  return jwt.sign({ sub: String(id), role, name }, SECRET, { expiresIn: '1h', ...opts })
}

function calendarToken({ id, username, role = 'user' }, opts = {}) {
  return jwt.sign({ id, username, role }, SECRET, { expiresIn: '1h', ...opts })
}

const bearer = t => ({ Authorization: `Bearer ${t}` })

module.exports = { localToken, calendarToken, bearer, SECRET }
