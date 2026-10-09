/**
 * 工作進度（Iteration 55 的 harness 工程）：把「交接筆記、驗證結果、hook 事件、迭代紀錄、git」
 * 整理成一個 JSON，給儀表板「工作進度」頁畫。只讀檔案與 git，不碰資料庫。
 *
 *   GET /progress            全部（admin）
 *
 * 來源（都在 repo 根目錄；測試用 PROGRESS_ROOT 指到暫存目錄）：
 *   progress.md                    交接筆記（harness 文章的 progress note：任務／產出／已完成／決策／未解／下一步／階段）
 *   AI/progress/checks.json        驗證結果（AI/harness/record_check.js 寫）
 *   AI/progress/events.jsonl       Claude Code hook 事件（AI/harness/hook_log.js 寫）
 *   AI/Doc/Iterations/*.md         迭代紀錄（標題與日期）
 *   git log / git status           最近提交、工作區是否乾淨
 *   CLAUDE.md、.claude/*           harness 七層哪些已就位
 */
const fs = require('fs')
const path = require('path')
const { Router } = require('express')
const { execFileSync } = require('child_process')

const router = Router()

function root() { return process.env.PROGRESS_ROOT || path.resolve(__dirname, '..', '..') }
function readText(p) { try { return fs.readFileSync(p, 'utf8') } catch { return null } }
function mtime(p) { try { return fs.statSync(p).mtime.toISOString() } catch { return null } }

// ── progress.md：## 標題分段；清單行變陣列；「階段」段落的 - [x] / - [~] / - [ ] 變狀態 ──
const SECTION_KEYS = {
  '任務': 'task', '產出': 'outputs', '已完成': 'completed', '決策': 'decisions',
  '未解': 'open_issues', '下一步': 'next_action', '階段': 'stages',
}
function parseHandoff(md) {
  const out = { task: '', outputs: [], completed: [], decisions: [], open_issues: [], next_action: '', stages: [], updated: null }
  if (!md) return out
  let key = null
  for (const raw of md.split(/\r?\n/)) {
    const h = raw.match(/^##\s+(.+?)\s*$/)
    if (h) {
      const name = h[1].replace(/[（(].*$/, '').trim()
      key = SECTION_KEYS[name] || null
      continue
    }
    const u = raw.match(/^\*\*更新[:：]\*\*\s*(.+)$/) || raw.match(/^更新[:：]\s*(.+)$/)
    if (u && !out.updated) { out.updated = u[1].trim(); continue }
    if (!key) continue
    const line = raw.trim()
    if (!line) continue
    if (key === 'stages') {
      const m = line.match(/^[-*]\s*\[( |x|X|~|>)\]\s*(.+)$/)
      if (m) out.stages.push({ label: m[2].trim(), status: /x/i.test(m[1]) ? 'done' : m[1] === ' ' ? 'todo' : 'doing' })
      continue
    }
    if (key === 'task' || key === 'next_action') {
      out[key] = out[key] ? `${out[key]} ${line.replace(/^[-*]\s*/, '')}` : line.replace(/^[-*]\s*/, '')
      continue
    }
    const item = line.replace(/^(?:[-*]|\d+[.)])\s*/, '')
    if (item) out[key].push(item)
  }
  return out
}

// ── events.jsonl：最後 N 筆、每日筆數、是否「正在工作」 ──
function readEvents(p, limit = 120) {
  const txt = readText(p)
  if (!txt) return { recent: [], per_day: [], sessions: 0, last_event_at: null, active: false, total: 0 }
  const all = []
  for (const line of txt.split('\n')) {
    if (!line.trim()) continue
    try { all.push(JSON.parse(line)) } catch { /* 壞行略過 */ }
  }
  const byDay = new Map()
  const sessions = new Set()
  for (const e of all) {
    const d = (e.ts || '').slice(0, 10)
    if (d) byDay.set(d, (byDay.get(d) || 0) + 1)
    if (e.session) sessions.add(e.session)
  }
  const last = all.length ? all[all.length - 1].ts : null
  const active = last ? (Date.now() - new Date(last).getTime()) < 10 * 60 * 1000 : false
  const per_day = fillDays(byDay)
  return { recent: all.slice(-limit).reverse(), per_day, sessions: sessions.size, last_event_at: last, active, total: all.length }
}

// 連續日期窗：起點 = min(最早有事件的日, 今天 − 13 天)，最多 30 天，沒事件的日子補 0
// （只有一天有事件時，單一根柱子會填滿整張圖；補成日期窗後寬度才正常）
function fillDays(byDay, maxDays = 30) {
  const today = new Date(); today.setUTCHours(0, 0, 0, 0)
  const days = [...byDay.keys()].sort()
  let start = new Date(today); start.setUTCDate(start.getUTCDate() - 13)
  if (days.length && new Date(days[0] + 'T00:00:00Z') < start) start = new Date(days[0] + 'T00:00:00Z')
  const floor = new Date(today); floor.setUTCDate(floor.getUTCDate() - (maxDays - 1))
  if (start < floor) start = floor
  const out = []
  for (let d = new Date(start); d <= today; d.setUTCDate(d.getUTCDate() + 1)) {
    const key = d.toISOString().slice(0, 10)
    out.push({ d: key, n: byDay.get(key) || 0 })
  }
  return out
}

// ── 迭代紀錄：# Iteration NN — 標題 ＋ **日期：** YYYY-MM-DD ──
function readIterations(dir) {
  let files = []
  try { files = fs.readdirSync(dir).filter(f => /^Iteration-\d+\.md$/.test(f)) } catch { return [] }
  const rows = files.map(f => {
    const md = readText(path.join(dir, f)) || ''
    const n = Number(f.match(/\d+/)[0])
    const title = (md.match(/^#\s+Iteration\s+\d+\s*[—–-]+\s*(.+)$/m) || [])[1] || (md.match(/^#\s+(.+)$/m) || [])[1] || ''
    const date = (md.match(/\*\*日期[:：]\*\*\s*([0-9-]+)/) || [])[1] || null
    const basis = (md.match(/\*\*依據[:：]\*\*\s*(.+)/) || [])[1] || ''
    return { n, file: `AI/Doc/Iterations/${f}`, title: title.trim(), date, basis: basis.trim().slice(0, 160) }
  })
  return rows.sort((a, b) => b.n - a.n)
}

function git(args, cwd) {
  // 不能 .trim()：`git status --porcelain` 第一行開頭的空白是狀態欄（" M path"），吃掉就少一個字
  try { return execFileSync('git', args, { cwd, encoding: 'utf8', timeout: 5000, stdio: ['ignore', 'pipe', 'ignore'] }).replace(/\s+$/, '') } catch { return null }
}
function readGit(cwd) {
  const log = git(['log', '-15', '--date=short', '--format=%h%x09%ad%x09%s'], cwd)
  const commits = log ? log.split('\n').filter(Boolean).map(l => { const [hash, date, ...s] = l.split('\t'); return { hash, date, subject: s.join('\t') } }) : []
  const status = git(['status', '--porcelain'], cwd)
  const lines = status === null ? null : status.split('\n').filter(l => l.length > 3)
  return {
    available: log !== null,
    branch: (git(['rev-parse', '--abbrev-ref', 'HEAD'], cwd) || '').trim() || null,
    commits,
    modified: lines ? lines.filter(l => !l.startsWith('??')).length : null,
    untracked: lines ? lines.filter(l => l.startsWith('??')).length : null,
    dirty_files: lines ? lines.slice(0, 40).map(l => `${l.startsWith('??') ? '＋' : '✎'} ${l.slice(3)}`) : [],
  }
}

// ── harness 七層（照文章）：每層看代表檔案在不在 ──
function harnessLayers(r) {
  const exists = p => fs.existsSync(path.join(r, p))
  const listDir = p => { try { return fs.readdirSync(path.join(r, p)) } catch { return [] } }
  let hooks = 0, deny = 0
  try {
    const s = JSON.parse(readText(path.join(r, '.claude', 'settings.json')) || '{}')
    hooks = Object.values(s.hooks || {}).reduce((n, arr) => n + (Array.isArray(arr) ? arr.length : 0), 0)
    deny = ((s.permissions || {}).deny || []).length
  } catch { /* 沒有或壞掉都算 0 */ }
  const skills = listDir('.claude/skills').filter(d => exists(`.claude/skills/${d}/SKILL.md`))
  const agents = listDir('.claude/agents').filter(f => f.endsWith('.md')).map(f => f.replace(/\.md$/, ''))
  const rules = listDir('.claude/rules').filter(f => f.endsWith('.md'))
  return [
    { key: 'facts', label: '1 工作區事實', ok: exists('CLAUDE.md'), detail: exists('CLAUDE.md') ? `CLAUDE.md${rules.length ? `＋${rules.length} 條路徑規則` : ''}` : '缺 CLAUDE.md' },
    { key: 'skills', label: '2 重複流程（skills）', ok: skills.length > 0, detail: skills.length ? skills.map(s => `/${s}`).join('、') : '沒有 skill' },
    { key: 'sources', label: '3 來源存取', ok: exists('AI/Doc/README.md') && exists('AI/UserDoc/Spec.md'), detail: 'AI/Doc 索引、AI/UserDoc 規格' },
    { key: 'rules', label: '4 行動規則', ok: deny > 0 || hooks > 0, detail: `${deny} 條 deny、${hooks} 個 hook` },
    { key: 'reviewer', label: '5 審查者回證據', ok: agents.length > 0, detail: agents.length ? agents.join('、') : '沒有 subagent' },
    { key: 'effort', label: '6 effort 分配', ok: agents.some(a => /effort:/.test(readText(path.join(r, '.claude', 'agents', `${a}.md`)) || '')), detail: 'agent frontmatter 的 effort' },
    { key: 'goal', label: '7 完成條件', ok: exists('progress.md') && exists('AI/progress/checks.json'), detail: 'progress.md ＋ checks.json' },
  ]
}

router.get('/', (_req, res) => {
  const r = root()
  const handoffPath = path.join(r, 'progress.md')
  const md = readText(handoffPath)
  const handoff = parseHandoff(md)
  handoff.updated_at = mtime(handoffPath)
  handoff.exists = md !== null
  let checks = { updated_at: null, checks: [] }
  try { checks = JSON.parse(readText(path.join(r, 'AI', 'progress', 'checks.json')) || '{}'); if (!Array.isArray(checks.checks)) checks.checks = [] } catch { /* 沒有就空 */ }
  res.json({
    generated_at: new Date().toISOString(),
    handoff,
    checks,
    events: readEvents(path.join(r, 'AI', 'progress', 'events.jsonl')),
    iterations: readIterations(path.join(r, 'AI', 'Doc', 'Iterations')),
    git: readGit(r),
    harness: harnessLayers(r),
  })
})

module.exports = router
module.exports.parseHandoff = parseHandoff
