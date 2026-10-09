/**
 * 工作進度的資料層（只讀）：progress.md、AI/progress/checks.json、AI/progress/events.jsonl、迭代紀錄、git。
 * progress_report.js（終端機文字）與 progress_ui.js（獨立畫面）都用這一份，兩邊永遠一致。
 *
 *   const { collect } = require('./progress_data')
 *   collect({ events: 30 })  → { root, updated, dirty, sections, sessions, checks, iterations, commits, events }
 *
 * 「目前負責的代理人」怎麼算：events.jsonl 裡 PostToolUse tool=Agent 的 summary 是「<agent 類型>：<描述>」= 派出一個子代理；
 * 同一 session 之後的 SubagentStop 依先進先出把最早還在跑的那個標成完成。主 session 本身也是一個代理人（最近一句指令就是它負責的事）。
 */
'use strict'
const fs = require('fs')
const path = require('path')
const { execFileSync } = require('child_process')

const ROOT = process.env.CLAUDE_PROJECT_DIR || path.resolve(__dirname, '..', '..')
const DAY = 24 * 3600 * 1000
const SECTION_KEYS = ['任務', '產出', '已完成', '決策', '未解', '下一步', '階段']

const read = p => { try { return fs.readFileSync(path.join(ROOT, p), 'utf8') } catch { return null } }
const git = a => { try { return execFileSync('git', a, { cwd: ROOT, encoding: 'utf8' }).trim() } catch { return '' } }

function parseProgress(md) {
  const sections = {}
  let cur = null
  for (const line of (md || '').split(/\r?\n/)) {
    const m = line.match(/^##\s+(.+?)\s*$/)
    if (m) { cur = m[1]; sections[cur] = []; continue }
    if (cur && line.trim()) sections[cur].push(line.trimEnd())
  }
  const stages = (sections['階段'] || []).map(l => {
    const m = l.match(/^-\s*\[( |x|~)\]\s*(.+)$/)
    return m ? { state: m[1] === 'x' ? 'done' : m[1] === '~' ? 'active' : 'todo', text: m[2] } : { state: 'todo', text: l }
  })
  return { updated: ((md || '').match(/\*\*更新：\*\*\s*(\S+)/) || [])[1] || null, sections, stages }
}

function parseEvents(text) {
  return (text || '').split(/\r?\n/).filter(Boolean).map(l => { try { return JSON.parse(l) } catch { return null } }).filter(Boolean)
}

function sessionsFrom(events, now = Date.now()) {
  const by = new Map()
  for (const e of events) {
    if (!e.session) continue
    const s = by.get(e.session) || { id: e.session, first: e.ts, last: e.ts, tools: 0, failures: 0, prompts: [], lastTool: null, stopped: false, agents: [] }
    s.last = e.ts
    if (e.event === 'SessionStart') s.stopped = false
    if (e.event === 'UserPromptSubmit') {
      // 系統通知（<task-notification>、[Subagent hand-back]、<cross-session-message>）也會以 UserPromptSubmit 進來，不是使用者交辦的事
      const text = String(e.summary || '')
      if (text && !/^\s*</.test(text) && !/^\s*\[Subagent/.test(text) && !/^\s*Another Claude session/.test(text)) s.prompts.push({ ts: e.ts, text })
      s.stopped = false
    }
    if (e.event === 'PostToolUse') {
      s.tools += 1; s.lastTool = e.tool; s.stopped = false
      if (e.tool === 'Agent' && e.summary) {
        const [type, ...rest] = String(e.summary).split('：')
        s.agents.push({ type: type.trim(), description: rest.join('：').trim(), started: e.ts, running: true })
      }
    }
    if (e.event === 'PostToolUseFailure') s.failures += 1
    if (e.event === 'SubagentStop') {
      const a = s.agents.find(x => x.running)
      if (a) { a.running = false; a.stopped = e.ts }
    }
    if (e.event === 'Stop') s.stopped = true
    by.set(e.session, s)
  }
  return [...by.values()].filter(s => now - new Date(s.last) < DAY).sort((a, b) => new Date(b.last) - new Date(a.last))
    .map(s => ({ ...s, state: s.stopped ? 'idle' : 'working', task: s.prompts.at(-1) || null,
                 running_agents: s.agents.filter(a => a.running), done_agents: s.agents.filter(a => !a.running).slice(-6) }))
}

function iterations(n = 5) {
  try {
    return fs.readdirSync(path.join(ROOT, 'AI', 'Doc', 'Iterations')).filter(f => /^Iteration-\d+\.md$/.test(f))
      .map(f => ({ n: Number(f.match(/\d+/)[0]), f })).sort((a, b) => b.n - a.n).slice(0, n)
      .map(x => {
        const txt = read(`AI/Doc/Iterations/${x.f}`) || ''
        return { n: x.n, title: txt.split(/\r?\n/)[0].replace(/^#\s*Iteration \d+\s*—\s*/, '').replace(/^#\s*/, ''),
                 date: (txt.match(/\*\*日期：\*\*\s*(\S+)/) || [])[1] || null }
      })
  } catch { return [] }
}

function collect({ events: nEvents = 30 } = {}) {
  const now = Date.now()
  const prog = parseProgress(read('progress.md'))
  const events = parseEvents(read('AI/progress/events.jsonl'))
  let checks = []
  try { checks = JSON.parse(read('AI/progress/checks.json') || '{}').checks || [] } catch { /* ignore */ }
  checks = [...checks].sort((a, b) => new Date(b.at) - new Date(a.at))
  const commits = git(['log', '--format=%h%x09%cI%x09%s', '-8']).split('\n').filter(Boolean)
    .map(l => { const [hash, date, ...s] = l.split('\t'); return { hash, date, subject: s.join('\t') } })
  const dirty = git(['status', '--short']).split('\n').filter(Boolean)
  return {
    root: ROOT, now: new Date(now).toISOString(), updated: prog.updated, sections: prog.sections, stages: prog.stages,
    dirty_files: dirty.length, dirty: dirty.slice(0, 40),
    sessions: sessionsFrom(events, now), checks, iterations: iterations(), commits,
    events: events.slice(-nEvents).reverse(),
  }
}

module.exports = { collect, parseProgress, parseEvents, sessionsFrom, ROOT }
