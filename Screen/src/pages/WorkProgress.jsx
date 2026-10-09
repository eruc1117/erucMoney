// 工作進度（harness 工程，Iteration 55）
// ───────────────────────────────────────────────────────────────────────────
// 這一頁回答三個問題：現在做到哪（交接筆記與階段）、證據在哪（驗證結果、迭代紀錄、提交）、
// Claude 正在做什麼（hook 事件時間軸）。資料全部來自 GET /progress（admin），後端只讀檔案與 git。
//
// 真相來源是 repo 根目錄的 progress.md：模型每做完一個階段就更新它，下一個 session 從它接手。
// 這裡不提供編輯——改筆記要在 repo 裡改，否則儀表板和工作區會各說各話。
import { useCallback, useEffect, useState } from 'react'
import ReactApexChart from 'react-apexcharts'
import { getProgress } from '../services/api'

const REFRESH_MS = 30_000

function rel(ts) {
  if (!ts) return '–'
  const s = Math.round((Date.now() - new Date(ts).getTime()) / 1000)
  if (s < 60) return `${s} 秒前`
  if (s < 3600) return `${Math.floor(s / 60)} 分鐘前`
  if (s < 86400) return `${Math.floor(s / 3600)} 小時前`
  return `${Math.floor(s / 86400)} 天前`
}
function hhmm(ts) { return ts ? new Date(ts).toLocaleTimeString('zh-TW', { hour12: false }) : '–' }
function ymd(ts) { return ts ? new Date(ts).toLocaleDateString('zh-TW') : '–' }
function Sub({ children }) { return <div className="muted" style={{ fontSize: '0.74rem' }}>{children}</div> }

// ── 階段路線圖：一條線、每階段一個點 ─────────────────────────────────────────
const STAGE_STYLE = {
  done: { color: 'var(--green)', bg: 'var(--green-soft)', mark: '✓', label: '完成' },
  doing: { color: 'var(--blue)', bg: 'var(--blue-soft)', mark: '●', label: '進行中' },
  todo: { color: 'var(--dim)', bg: 'var(--dim-soft)', mark: '○', label: '未開始' },
}
function Stepper({ stages }) {
  if (!stages?.length) return <div className="muted" style={{ padding: '1rem 1.25rem', fontSize: '.88rem' }}>progress.md 沒有「## 階段」清單（- [x] 完成、- [~] 進行中、- [ ] 未開始）</div>
  return (
    <div style={{ display: 'grid', gridTemplateColumns: `repeat(${stages.length}, minmax(0, 1fr))`, padding: '1.1rem 1rem .9rem', gap: 0 }}>
      {stages.map((s, i) => {
        const st = STAGE_STYLE[s.status] || STAGE_STYLE.todo
        const lineL = i > 0 ? (stages[i - 1].status === 'done' ? 'var(--green)' : 'var(--border)') : 'transparent'
        const lineR = i < stages.length - 1 ? (s.status === 'done' ? 'var(--green)' : 'var(--border)') : 'transparent'
        return (
          <div key={i} style={{ textAlign: 'center', position: 'relative', minWidth: 0 }}>
            <div style={{ display: 'flex', alignItems: 'center' }}>
              <div style={{ flex: 1, height: 2, background: lineL }} />
              <div title={st.label} style={{ width: '1.7rem', height: '1.7rem', borderRadius: '50%', background: st.bg, color: st.color, border: `2px solid ${st.color}`, display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 700, fontSize: '.8rem', flexShrink: 0 }}>{st.mark}</div>
              <div style={{ flex: 1, height: 2, background: lineR }} />
            </div>
            <div style={{ marginTop: '.5rem', fontSize: '.8rem', fontWeight: s.status === 'doing' ? 700 : 500, color: s.status === 'todo' ? 'var(--dim)' : 'var(--text-strong)', padding: '0 .3rem', lineHeight: 1.35 }}>{s.label}</div>
          </div>
        )
      })}
    </div>
  )
}

// ── 交接筆記的一個區塊 ─────────────────────────────────────────────────────
function NoteList({ title, items, tone, empty = '（無）' }) {
  return (
    <div style={{ padding: '.75rem 1.25rem', borderBottom: '1px solid var(--border-soft)' }}>
      <div style={{ fontSize: '.74rem', fontWeight: 700, color: tone || 'var(--dim)', letterSpacing: '.04em', marginBottom: '.35rem' }}>{title}</div>
      {items?.length
        ? <ul style={{ margin: 0, paddingLeft: '1.1rem', fontSize: '.88rem', lineHeight: 1.65 }}>{items.map((it, i) => <li key={i}>{it}</li>)}</ul>
        : <div className="muted" style={{ fontSize: '.84rem' }}>{empty}</div>}
    </div>
  )
}

// ── 驗證結果 ──────────────────────────────────────────────────────────────
const CHECK_STYLE = { pass: ['green', '通過'], fail: ['red', '失敗'], skip: ['yellow', '略過'] }
function ChecksTable({ checks }) {
  const [open, setOpen] = useState(null)
  if (!checks?.length) return <div className="muted" style={{ padding: '1rem 1.25rem', fontSize: '.88rem' }}>還沒有驗證紀錄。跑測試時用 <code>node AI/harness/record_check.js --name jest --cwd Server -- npm test</code>，結果就會出現在這裡。</div>
  return (
    <table className="data-table">
      <thead><tr><th>檢查</th><th className="mid">結果</th><th>摘要</th><th className="num">時間</th></tr></thead>
      <tbody>
        {checks.map(c => {
          const [cls, label] = CHECK_STYLE[c.status] || ['', c.status]
          return [
            <tr key={c.name} onClick={() => c.detail && setOpen(open === c.name ? null : c.name)} style={{ cursor: c.detail ? 'pointer' : 'default' }}>
              <td><strong>{c.name}</strong>{c.command ? <Sub>{c.cwd && c.cwd !== '.' ? `${c.cwd}: ` : ''}{c.command}{c.duration_s != null ? `（${c.duration_s}s）` : ''}</Sub> : null}</td>
              <td className="mid"><span className={`tag ${cls}`}>{label}</span></td>
              <td style={{ whiteSpace: 'normal', maxWidth: 420 }}>{c.summary || '–'}{c.detail ? <Sub>{open === c.name ? '收起' : '點一下看最後 30 行輸出'}</Sub> : null}</td>
              <td className="num" title={c.at}>{rel(c.at)}</td>
            </tr>,
            open === c.name && c.detail ? (
              <tr key={`${c.name}-d`}><td colSpan={4} style={{ whiteSpace: 'pre-wrap', fontFamily: 'ui-monospace, Consolas, monospace', fontSize: '.74rem', background: 'var(--bg3)', lineHeight: 1.5 }}>{c.detail}</td></tr>
            ) : null,
          ]
        })}
      </tbody>
    </table>
  )
}

// ── 活動：每日事件數（單一序列，不需要圖例） ──────────────────────────────
function ActivityChart({ perDay }) {
  if (!perDay?.length) return null
  const dark = document.documentElement.dataset.theme === 'dark'
  const options = {
    chart: { type: 'bar', toolbar: { show: false }, animations: { enabled: false }, background: 'transparent', sparkline: { enabled: false } },
    plotOptions: { bar: { columnWidth: '58%', borderRadius: 3, borderRadiusApplication: 'end' } },
    colors: [dark ? '#5b9dff' : '#1d6ff2'],
    dataLabels: { enabled: false },
    xaxis: { categories: perDay.map(p => p.d.slice(5)), labels: { rotate: 0, style: { fontSize: '10px' } }, axisTicks: { show: false } },
    yaxis: { labels: { formatter: v => Math.round(v) }, title: { text: '事件數' }, forceNiceScale: true },
    grid: { borderColor: 'rgba(128,128,128,0.18)', strokeDashArray: 3 },
    tooltip: { x: { formatter: (_v, { dataPointIndex }) => perDay[dataPointIndex]?.d }, y: { formatter: v => `${v} 筆` } },
    theme: { mode: dark ? 'dark' : 'light' },
  }
  return <div className="chart-pad"><ReactApexChart type="bar" series={[{ name: 'hook 事件', data: perDay.map(p => p.n) }]} options={options} height={180} /></div>
}

const EVENT_ICON = {
  SessionStart: ['▶', 'var(--green)'], UserPromptSubmit: ['💬', 'var(--blue)'], PostToolUse: ['🔧', 'var(--dim)'], PreToolUse: ['🔧', 'var(--dim)'],
  Stop: ['⏹', 'var(--orange)'], SubagentStop: ['🤖', 'var(--purple)'], SubagentStart: ['🤖', 'var(--purple)'], PreCompact: ['🗜', 'var(--yellow)'],
  Notification: ['🔔', 'var(--yellow)'], check: ['✔', 'var(--green)'], SessionEnd: ['■', 'var(--dim)'],
}
function EventList({ events }) {
  if (!events?.length) return <div className="muted" style={{ padding: '1rem 1.25rem', fontSize: '.88rem' }}>還沒有事件。.claude/settings.json 的 hooks 會把 Claude Code 的每一步寫進 AI/progress/events.jsonl。</div>
  return (
    <div style={{ maxHeight: 380, overflowY: 'auto' }}>
      {events.map((e, i) => {
        const [icon, color] = EVENT_ICON[e.event] || ['·', 'var(--dim)']
        const failed = e.ok === false
        return (
          <div key={i} style={{ display: 'grid', gridTemplateColumns: '1.4rem 4.2rem 1fr auto', gap: '.5rem', alignItems: 'baseline', padding: '.42rem 1.25rem', borderBottom: '1px solid var(--border-soft)', fontSize: '.84rem', background: failed ? 'var(--red-soft)' : undefined }}>
            <span style={{ color: failed ? 'var(--red)' : color, textAlign: 'center' }}>{failed ? '✖' : icon}</span>
            <span className="muted" style={{ fontSize: '.74rem', fontVariantNumeric: 'tabular-nums' }}>{hhmm(e.ts)}</span>
            <span style={{ minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={e.summary}>
              {e.tool ? <strong style={{ marginRight: '.4rem' }}>{e.tool}</strong> : <strong style={{ marginRight: '.4rem', color }}>{e.event}</strong>}
              {e.summary}
            </span>
            <span className="muted" style={{ fontSize: '.7rem' }}>{e.session || ''}</span>
          </div>
        )
      })}
    </div>
  )
}

function HarnessLayers({ layers }) {
  return (
    <div style={{ padding: '.4rem 0' }}>
      {layers.map(l => (
        <div key={l.key} style={{ display: 'flex', gap: '.7rem', alignItems: 'baseline', padding: '.4rem 1.25rem', fontSize: '.86rem' }}>
          <span style={{ color: l.ok ? 'var(--green)' : 'var(--red)', fontWeight: 700, width: '1rem' }}>{l.ok ? '✓' : '✗'}</span>
          <span style={{ minWidth: '9.5rem', fontWeight: 600 }}>{l.label}</span>
          <span className="muted" style={{ fontSize: '.8rem', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={l.detail}>{l.detail}</span>
        </div>
      ))}
    </div>
  )
}

export default function WorkProgress() {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)
  const [fetchedAt, setFetchedAt] = useState(null)

  const load = useCallback(async () => {
    setLoading(true)
    const { data, error } = await getProgress()
    if (error) setError(error); else { setData(data); setError(null) }
    setFetchedAt(new Date())
    setLoading(false)
  }, [])

  useEffect(() => {
    load()
    const t = setInterval(load, REFRESH_MS)
    return () => clearInterval(t)
  }, [load])

  if (error && !data) return <div className="alert-card alert-error"><div className="alert-icon">⚠</div><div className="alert-body"><div className="alert-title">讀不到工作進度</div><div className="alert-sub">{error}（這一頁要 admin；後端要能讀 repo 根目錄）</div></div></div>
  if (!data) return <div className="empty-state"><div className="empty-icon">⏳</div>載入中…</div>

  const { handoff, checks, events, iterations, git, harness } = data
  const stagesDone = handoff.stages.filter(s => s.status === 'done').length
  const current = handoff.stages.find(s => s.status === 'doing')
  const checkPass = checks.checks.filter(c => c.status === 'pass').length
  const checkFail = checks.checks.filter(c => c.status === 'fail').length
  const latestIter = iterations[0]
  const dirty = (git.modified || 0) + (git.untracked || 0)

  return (
    <>
      {/* 頂列：一眼看完 */}
      <div className="card" style={{ marginBottom: '1.1rem' }}>
        <div className="card-header">
          <div>
            <div className="card-title">{handoff.task || '（progress.md 沒有「## 任務」）'}</div>
            <Sub>交接筆記 progress.md · 更新 {handoff.updated || ymd(handoff.updated_at)} · {handoff.exists ? '' : '檔案不存在 · '}每 {REFRESH_MS / 1000} 秒重讀</Sub>
          </div>
          <div style={{ display: 'flex', gap: '.6rem', alignItems: 'center' }}>
            <span className="sys-status"><span className={`dot ${events.active ? 'green' : 'red'}`} /><span style={{ fontSize: '.8rem' }}>{events.active ? 'Claude 正在工作' : `最後活動 ${rel(events.last_event_at)}`}</span></span>
            <button className="btn-secondary" onClick={load} disabled={loading}>{loading ? '更新中…' : '重新整理'}</button>
          </div>
        </div>
        <div className="stat-grid">
          <div className="stat-tile"><div className="k">階段</div><div className="v">{stagesDone} / {handoff.stages.length}</div><div className="s">{current ? `進行中：${current.label}` : '沒有進行中的階段'}</div></div>
          <div className="stat-tile"><div className="k">最近迭代</div><div className="v">#{latestIter?.n ?? '–'}</div><div className="s" style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={latestIter?.title}>{latestIter?.date || ''} {latestIter?.title || ''}</div></div>
          <div className="stat-tile"><div className="k">驗證</div><div className="v"><span className={checkFail ? 'down' : 'up'}>{checkPass}</span> / {checks.checks.length}</div><div className="s">{checkFail ? `${checkFail} 項失敗` : checks.updated_at ? `最近 ${rel(checks.updated_at)}` : '尚無紀錄'}</div></div>
          <div className="stat-tile"><div className="k">未解問題</div><div className="v">{handoff.open_issues.length}</div><div className="s">決策 {handoff.decisions.length} 條</div></div>
          <div className="stat-tile"><div className="k">工作區</div><div className="v"><span className={dirty ? 'down' : 'up'}>{git.available ? dirty : '–'}</span></div><div className="s">{git.available ? `${git.modified} 已修改 · ${git.untracked} 未追蹤 · ${git.branch || ''}` : '不是 git repo'}</div></div>
          <div className="stat-tile"><div className="k">本次重讀</div><div className="v" style={{ fontSize: '1rem' }}>{fetchedAt ? hhmm(fetchedAt) : '–'}</div><div className="s">{events.total} 筆事件 · {events.sessions} 個 session</div></div>
        </div>
      </div>

      {/* 路線圖 */}
      <div className="card" style={{ marginBottom: '1.1rem' }}>
        <div className="card-header"><div className="card-title">階段路線圖</div><Sub>progress.md「## 階段」：✓ 完成 · ● 進行中 · ○ 未開始</Sub></div>
        <Stepper stages={handoff.stages} />
      </div>

      <div className="two-col" style={{ marginBottom: '1.1rem' }}>
        {/* 交接筆記 */}
        <div className="card">
          <div className="card-header"><div className="card-title">交接筆記</div><Sub>下一個 session 從這裡接手</Sub></div>
          <div style={{ padding: '.75rem 1.25rem', borderBottom: '1px solid var(--border-soft)', background: 'var(--blue-soft)' }}>
            <div style={{ fontSize: '.74rem', fontWeight: 700, color: 'var(--blue)', letterSpacing: '.04em', marginBottom: '.25rem' }}>下一步</div>
            <div style={{ fontSize: '.95rem', fontWeight: 600 }}>{handoff.next_action || '（未填）'}</div>
          </div>
          <NoteList title="未解問題" items={handoff.open_issues} tone="var(--red)" empty="沒有未解問題" />
          <NoteList title="已完成" items={handoff.completed} tone="var(--green)" />
          <NoteList title="決策（含日期與理由）" items={handoff.decisions} />
          <NoteList title="產出（路徑）" items={handoff.outputs} />
          {git.dirty_files?.length ? <NoteList title="工作區未提交的檔案" items={git.dirty_files} tone="var(--orange)" /> : null}
        </div>

        {/* 驗證結果 ＋ harness */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '1.1rem' }}>
          <div className="card">
            <div className="card-header"><div className="card-title">驗證結果</div><Sub>AI/progress/checks.json · 完成條件要看這裡，不看對話</Sub></div>
            <div style={{ overflowX: 'auto' }}><ChecksTable checks={checks.checks} /></div>
          </div>
          <div className="card">
            <div className="card-header"><div className="card-title">Harness 七層</div><Sub>{harness.filter(l => l.ok).length} / 7 就位</Sub></div>
            <HarnessLayers layers={harness} />
          </div>
        </div>
      </div>

      {/* 活動 */}
      <div className="card" style={{ marginBottom: '1.1rem' }}>
        <div className="card-header"><div className="card-title">Claude Code 活動</div><Sub>hook 事件 · 最近 30 天每日筆數與最後 {events.recent.length} 筆</Sub></div>
        <ActivityChart perDay={events.per_day} />
        <EventList events={events.recent} />
      </div>

      {/* 歷史 */}
      <div className="two-col">
        <div className="card">
          <div className="card-header"><div className="card-title">迭代紀錄</div><Sub>AI/Doc/Iterations · {iterations.length} 篇</Sub></div>
          <div style={{ maxHeight: 420, overflowY: 'auto' }}>
            <table className="data-table">
              <thead><tr><th className="num">#</th><th>日期</th><th>標題</th></tr></thead>
              <tbody>{iterations.map(it => (
                <tr key={it.n} title={it.basis}><td className="num">{it.n}</td><td>{it.date || '–'}</td><td style={{ whiteSpace: 'normal' }}>{it.title}</td></tr>
              ))}</tbody>
            </table>
          </div>
        </div>
        <div className="card">
          <div className="card-header"><div className="card-title">最近提交</div><Sub>git log · {git.branch || ''}</Sub></div>
          <div style={{ maxHeight: 420, overflowY: 'auto' }}>
            {git.commits.length ? (
              <table className="data-table">
                <thead><tr><th>hash</th><th>日期</th><th>說明</th></tr></thead>
                <tbody>{git.commits.map(c => (
                  <tr key={c.hash}><td style={{ fontFamily: 'ui-monospace, Consolas, monospace' }}>{c.hash}</td><td>{c.date}</td><td style={{ whiteSpace: 'normal' }}>{c.subject}</td></tr>
                ))}</tbody>
              </table>
            ) : <div className="muted" style={{ padding: '1rem 1.25rem', fontSize: '.88rem' }}>讀不到 git log</div>}
          </div>
        </div>
      </div>
    </>
  )
}
