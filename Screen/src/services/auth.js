// ============================================================
//  登入狀態（階段 1，多使用者）
//  token 與使用者存 localStorage；api.js 每次請求自動帶 Authorization: Bearer。
//  後端回 401 時清掉並通知 App 跳回登入頁。
// ============================================================

const TOKEN_KEY = 'auth_token'
const USER_KEY = 'auth_user'
const listeners = new Set()

function safeGet(k) { try { return localStorage.getItem(k) } catch { return null } }
function safeSet(k, v) { try { v == null ? localStorage.removeItem(k) : localStorage.setItem(k, v) } catch { /* 隱私模式 */ } }

export function getToken() { return safeGet(TOKEN_KEY) }
export function getUser() {
  try { return JSON.parse(safeGet(USER_KEY) || 'null') } catch { return null }
}
export function isAdmin() { return getUser()?.role === 'admin' }

export function setSession(token, user) {
  safeSet(TOKEN_KEY, token)
  safeSet(USER_KEY, JSON.stringify(user))
  listeners.forEach(fn => fn(user))
}

export function clearSession() {
  safeSet(TOKEN_KEY, null)
  safeSet(USER_KEY, null)
  listeners.forEach(fn => fn(null))
}

/** App 用：登入／登出時重新渲染 */
export function onAuthChange(fn) {
  listeners.add(fn)
  return () => listeners.delete(fn)
}
