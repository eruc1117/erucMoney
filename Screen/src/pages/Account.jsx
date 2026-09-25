import { useEffect, useState } from 'react'
import { changePassword, listUsers, createUser, updateUser, deleteUser } from '../services/api'
import { getUser, isAdmin, clearSession } from '../services/auth'

// 帳號頁（階段 1）：自己改密碼；admin 管理使用者（建帳號、改角色、停用、重設密碼、刪除）。
// 不開放自助註冊——帳號一律由 admin 建。
const input = { padding: '.45rem .6rem', border: '1px solid var(--border)', borderRadius: 6,
                background: 'var(--bg, transparent)', color: 'var(--text-strong, inherit)' }

function ChangePassword() {
  const [oldPw, setOld] = useState(''); const [newPw, setNew] = useState(''); const [msg, setMsg] = useState('')
  async function submit(e) {
    e.preventDefault(); setMsg('')
    const { error } = await changePassword(oldPw, newPw)
    setMsg(error ? error : '密碼已更新'); if (!error) { setOld(''); setNew('') }
  }
  return (
    <form className="card" onSubmit={submit} style={{ padding: '1.2rem', maxWidth: 480 }}>
      <div className="card-title" style={{ marginBottom: '.8rem' }}>修改密碼</div>
      <div style={{ display: 'grid', gap: '.6rem' }}>
        <input id="pw-old" style={input} type="password" placeholder="舊密碼" value={oldPw} onChange={e => setOld(e.target.value)} required autoComplete="current-password" />
        <input id="pw-new" style={input} type="password" placeholder="新密碼（至少 6 個字）" value={newPw} onChange={e => setNew(e.target.value)} required minLength={6} autoComplete="new-password" />
        <div style={{ display: 'flex', gap: '.6rem', alignItems: 'center' }}>
          <button className="btn-primary" type="submit">更新</button>
          <span style={{ fontSize: '.9rem', color: msg.includes('已') ? 'var(--green)' : 'var(--red)' }}>{msg}</span>
        </div>
      </div>
    </form>
  )
}

function UserAdmin() {
  const me = getUser()
  const [rows, setRows] = useState([]); const [err, setErr] = useState('')
  const [form, setForm] = useState({ username: '', password: '', role: 'user', display_name: '' })
  async function load() { const { data, error } = await listUsers(); setErr(error || ''); setRows(data || []) }
  useEffect(() => { load() }, [])

  async function add(e) {
    e.preventDefault()
    const { error } = await createUser(form)
    if (error) return setErr(error)
    setForm({ username: '', password: '', role: 'user', display_name: '' }); load()
  }
  async function patch(id, body) { const { error } = await updateUser(id, body); if (error) setErr(error); else load() }
  async function resetPw(u) {
    const pw = window.prompt(`為 ${u.username} 設定新密碼（至少 6 個字）`)
    if (pw) patch(u.id, { password: pw })
  }
  async function remove(u) {
    if (!window.confirm(`刪除 ${u.username}？他的持股與交易紀錄會一起刪除，無法復原。`)) return
    const { error } = await deleteUser(u.id); if (error) setErr(error); else load()
  }

  return (
    <div className="card" style={{ padding: '1.2rem', marginTop: '1rem' }}>
      <div className="card-title" style={{ marginBottom: '.8rem' }}>使用者管理（admin）</div>
      {err && <div style={{ color: 'var(--red)', marginBottom: '.6rem' }}>{err}</div>}
      <div style={{ overflowX: 'auto' }}>
        <table className="data-table" style={{ width: '100%', fontSize: '.92rem' }}>
          <thead><tr><th>帳號</th><th>顯示名</th><th>角色</th><th>狀態</th><th>持股／交易</th><th>最近登入</th><th></th></tr></thead>
          <tbody>
            {rows.map(u => (
              <tr key={u.id}>
                <td>{u.username}{u.id === me?.id && '（我）'}</td>
                <td>{u.display_name || '—'}</td>
                <td>
                  <select value={u.role} disabled={u.id === me?.id} onChange={e => patch(u.id, { role: e.target.value })} style={input}>
                    <option value="user">user</option><option value="admin">admin</option>
                  </select>
                </td>
                <td>{u.is_active ? '啟用' : '停用'}</td>
                <td>{u.holdings} / {u.trades}</td>
                <td>{u.last_login_at ? String(u.last_login_at).slice(0, 16).replace('T', ' ') : '—'}</td>
                <td style={{ whiteSpace: 'nowrap' }}>
                  <button className="btn-secondary" onClick={() => resetPw(u)}>重設密碼</button>{' '}
                  {u.id !== me?.id && <>
                    <button className="btn-secondary" onClick={() => patch(u.id, { is_active: !u.is_active })}>{u.is_active ? '停用' : '啟用'}</button>{' '}
                    <button className="btn-secondary" onClick={() => remove(u)}>刪除</button>
                  </>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <form onSubmit={add} style={{ display: 'flex', flexWrap: 'wrap', gap: '.5rem', marginTop: '1rem', alignItems: 'center' }}>
        <input id="nu-username" style={input} placeholder="新帳號" value={form.username} onChange={e => setForm({ ...form, username: e.target.value })} required />
        <input id="nu-password" style={input} type="password" placeholder="密碼" value={form.password} onChange={e => setForm({ ...form, password: e.target.value })} required minLength={6} />
        <input id="nu-name" style={input} placeholder="顯示名（選填）" value={form.display_name} onChange={e => setForm({ ...form, display_name: e.target.value })} />
        <select id="nu-role" style={input} value={form.role} onChange={e => setForm({ ...form, role: e.target.value })}>
          <option value="user">user</option><option value="admin">admin</option>
        </select>
        <button className="btn-primary" type="submit">建立帳號</button>
      </form>
    </div>
  )
}

export default function Account() {
  const me = getUser()
  return (
    <div>
      <div className="card" style={{ padding: '1rem 1.2rem', marginBottom: '1rem', display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '.6rem' }}>
        <div>
          <div style={{ fontWeight: 650 }}>{me?.display_name || me?.username}</div>
          <div style={{ fontSize: '.85rem', color: 'var(--text-muted, #8a94a6)' }}>@{me?.username} · {me?.role}</div>
        </div>
        <button className="btn-secondary" onClick={clearSession}>登出</button>
      </div>
      <ChangePassword />
      {isAdmin() && <UserAdmin />}
    </div>
  )
}
