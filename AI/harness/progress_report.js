#!/usr/bin/env node
/**
 * 工作進度（給 Claude Code 這一側看的版本；網頁版是 Server/routes/progress.js）
 *
 *   node AI/harness/progress_report.js            # 印目前任務、各 session 在做什麼、階段、驗證結果、最近迭代與提交
 *   node AI/harness/progress_report.js --events 20 # 多印最近 20 筆 hook 事件
 *
 * 來源都在 repo（只讀）：progress.md、AI/progress/checks.json、AI/progress/events.jsonl、AI/Doc/Iterations/*.md、git。
 * /progress 這個 skill 就是跑這支，把輸出原樣貼給使用者。
 */
'use strict'
const fs = require('fs')
const path = require('path')
const { execFileSync } = require('child_process')

const ROOT = process.env.CLAUDE_PROJECT_DIR || path.resolve(__dirname, '..', '..')
const args = process.argv.slice(2)
const nEvents = args.includes('--events') ? Number(args[args.indexOf('--events') + 1] || 10) : 0

const read = p => { try { return fs.readFileSync(path.join(ROOT, p), 'utf8') } catch { return null } }
const pad = (s, n) => String(s ?? '').padEnd(n)
const local = iso => { try { const d = new Date(iso); return new Date(d - d.getTimezoneOffset() * 60000).toISOString().replace('T', ' ').slice(5, 16) } catch { return iso } }
const ago = iso => { const m = Math.round((Date.now() - new Date(iso)) / 60000); return m < 60 ? `${m} 分鐘前` : m < 1440 ? `${Math.round(m / 60)} 小時前` : `${Math.round(m / 1440)} 天前` }

// ── progress.md ───────────────────────────────────────────────────────────────
const md = read('progress.md') || ''
const sections = {}
let cur = null
for (const line of md.split(/\r?\n/)) {
  const m = line.match(/^##\s+(.+?)\s*$/)
  if (m) { cur = m[1]; sections[cur] = []; continue }
  if (cur && line.trim()) sections[cur].push(line.trimEnd())
}
const updated = (md.match(/\*\*更新：\*\*\s*(\S+)/) || [])[1]

// ── events.jsonl：各 session 最近在做什麼 ────────────────────────────────────
const events = (read('AI/progress/events.jsonl') || '').split(/\r?\n/).filter(Boolean).map(l => { try { return JSON.parse(l) } catch { return null } }).filter(Boolean)
const bySession = new Map()
for (const e of events) {
  if (!e.session) continue
  const s = bySession.get(e.session) || { id: e.session, first: e.ts, last: e.ts, tools: 0, prompts: [], lastTool: null, stopped: false }
  s.last = e.ts
  if (e.event === 'UserPromptSubmit') { s.prompts.push({ ts: e.ts, text: e.summary || '' }); s.stopped = false }
  if (e.event === 'PostToolUse') { s.tools += 1; s.lastTool = e.tool; s.stopped = false }
  if (e.event === 'Stop') s.stopped = true
  bySession.set(e.session, s)
}
const DAY = 24 * 3600 * 1000
const recent = [...bySession.values()].filter(s => Date.now() - new Date(s.last) < DAY).sort((a, b) => new Date(b.last) - new Date(a.last))

// ── checks.json ───────────────────────────────────────────────────────────────
let checks = []
try { checks = JSON.parse(read('AI/progress/checks.json') || '{}').checks || [] } catch { /* ignore */ }

// ── 迭代與 git ────────────────────────────────────────────────────────────────
let iters = []
try {
  iters = fs.readdirSync(path.join(ROOT, 'AI', 'Doc', 'Iterations')).filter(f => /^Iteration-\d+\.md$/.test(f))
    .map(f => ({ n: Number(f.match(/\d+/)[0]), f })).sort((a, b) => b.n - a.n).slice(0, 4)
    .map(x => { const t = (read(`AI/Doc/Iterations/${x.f}`) || '').split(/\r?\n/)[0].replace(/^#\s*/, ''); return `${x.f.replace('.md', '')}：${t.replace(/^Iteration \d+ — /, '')}` })
} catch { /* ignore */ }
const git = (a) => { try { return execFileSync('git', a, { cwd: ROOT, encoding: 'utf8' }).trim() } catch { return '' } }
const log = git(['log', '--oneline', '-5'])
const dirty = git(['status', '--short']).split('\n').filter(Boolean).length

// ── 輸出 ──────────────────────────────────────────────────────────────────────
const out = []
out.push(`工作進度（${ROOT}）  筆記更新 ${updated || '?'}  工作區 ${dirty ? `${dirty} 個檔案未提交` : '乾淨'}`)
out.push('')
out.push('【任務】'); out.push(...(sections['任務'] || ['（progress.md 沒有任務段）']).map(l => '  ' + l))
out.push('【下一步】'); out.push(...(sections['下一步'] || []).map(l => '  ' + l))
out.push('【階段】'); out.push(...(sections['階段'] || []).map(l => '  ' + l))
out.push('')
out.push(`【Claude session（24 小時內，${recent.length} 個）】`)
if (!recent.length) out.push('  （events.jsonl 沒有事件）')
for (const s of recent) {
  const lastPrompt = s.prompts.at(-1)
  out.push(`  ${s.id}  ${s.stopped ? '閒置' : '進行中'}  最後活動 ${local(s.last)}（${ago(s.last)}）  工具呼叫 ${s.tools} 次${s.lastTool ? `，最近 ${s.lastTool}` : ''}`)
  if (lastPrompt) out.push(`      最近指令：${lastPrompt.text.slice(0, 90)}${lastPrompt.text.length > 90 ? '…' : ''}（${local(lastPrompt.ts)}）`)
}
out.push('')
out.push('【驗證結果 checks.json】')
if (!checks.length) out.push('  （沒有檢查）')
for (const c of checks) out.push(`  ${c.status === 'pass' ? '✔' : '✘'} ${pad(c.name, 22)} ${local(c.at)}  ${(c.summary || '').slice(0, 70)}`)
out.push('')
out.push('【最近迭代】'); out.push(...iters.map(l => '  ' + l))
out.push('【最近提交】'); out.push(...log.split('\n').filter(Boolean).map(l => '  ' + l.slice(0, 110)))
if (sections['未解']?.length) { out.push(''); out.push('【未解】'); out.push(...sections['未解'].map(l => '  ' + l.slice(0, 120))) }
if (nEvents) {
  out.push(''); out.push(`【最近 ${nEvents} 筆事件】`)
  for (const e of events.slice(-nEvents)) out.push(`  ${local(e.ts)} ${pad(e.session || '', 8)} ${pad(e.event, 16)} ${(e.tool || '')} ${(e.summary || '').slice(0, 60)}`)
}
process.stdout.write(out.join('\n') + '\n')
