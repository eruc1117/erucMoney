import { useState } from 'react'
import { login, getApiBase, setApiBase, getHealth } from '../services/api'
import { setSession } from '../services/auth'

// 登入頁（階段 1）。API 位址可在這裡改——前端獨立部署到 GitHub Pages 之後，
// 每個人要自己填家裡後端的網址（階段 2～4），所以放在登入頁而不是藏在設定裡。
export default function Login() {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [api, setApi] = useState(getApiBase())
  const [showApi, setShowApi] = useState(false)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const [ping, setPing] = useState('')

  async function submit(e) {
    e.preventDefault()
    setErr(''); setBusy(true)
    setApiBase(api.trim())
    const { data, error } = await login(username.trim(), password)
    setBusy(false)
    if (error || !data?.token) return setErr(error || '登入失敗')
    setSession(data.token, data.user)
  }

  async function testApi() {
    setApiBase(api.trim()); setPing('測試中…')
    const { data, error } = await getHealth()
    setPing(error ? `連不到：${error}` : `可連線（${data?.time?.slice(0, 19).replace('T', ' ')}）`)
  }

  const input = { width: '100%', padding: '.55rem .7rem', border: '1px solid var(--border)', borderRadius: 6,
                  background: 'var(--bg, transparent)', color: 'var(--text-strong, inherit)', fontSize: '1rem' }
  return (
    <div style={{ minHeight: '100vh', display: 'grid', placeItems: 'center', padding: '1rem', background: 'var(--bg, transparent)' }}>
      <form className="card" onSubmit={submit} style={{ width: 'min(380px, 100%)', padding: '1.6rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '.6rem', marginBottom: '1.2rem' }}>
          <div className="brand-icon">📊</div>
          <div>
            <div className="brand-name">智慧投資</div>
            <div className="brand-sub">請登入</div>
          </div>
        </div>
        <label style={{ display: 'block', marginBottom: '.8rem' }}>
          <div style={{ fontSize: '.85rem', color: 'var(--text-muted, #8a94a6)', marginBottom: '.25rem' }}>帳號</div>
          <input id="login-username" style={input} value={username} onChange={e => setUsername(e.target.value)}
                 autoComplete="username" autoFocus required />
        </label>
        <label style={{ display: 'block', marginBottom: '1rem' }}>
          <div style={{ fontSize: '.85rem', color: 'var(--text-muted, #8a94a6)', marginBottom: '.25rem' }}>密碼</div>
          <input id="login-password" style={input} type="password" value={password} onChange={e => setPassword(e.target.value)}
                 autoComplete="current-password" required />
        </label>
        {err && <div style={{ color: 'var(--red)', fontSize: '.9rem', marginBottom: '.8rem' }}>{err}</div>}
        <button className="btn-primary" type="submit" disabled={busy} style={{ width: '100%' }}>
          {busy ? '登入中…' : '登入'}
        </button>

        <div style={{ marginTop: '1.2rem', fontSize: '.85rem' }}>
          <button type="button" className="btn-secondary" onClick={() => setShowApi(v => !v)} style={{ fontSize: '.8rem' }}>
            {showApi ? '收起' : '後端位址'}：{api}
          </button>
          {showApi && (
            <div style={{ marginTop: '.6rem' }}>
              <input id="login-api" style={input} value={api} onChange={e => setApi(e.target.value)}
                     placeholder="http://localhost:3001 或 https://api.你的網域" />
              <div style={{ display: 'flex', gap: '.5rem', alignItems: 'center', marginTop: '.4rem' }}>
                <button type="button" className="btn-secondary" onClick={testApi}>測試連線</button>
                <span style={{ color: 'var(--text-muted, #8a94a6)' }}>{ping}</span>
              </div>
            </div>
          )}
        </div>
      </form>
    </div>
  )
}
