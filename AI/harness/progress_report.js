#!/usr/bin/env node
/**
 * 工作進度（終端機文字版；資料來自 progress_data.js，與獨立畫面 progress_ui.js、網頁版同一來源）
 *
 *   node AI/harness/progress_report.js            # 任務、下一步、階段、各 session 與負責的代理人、驗證結果、迭代、提交、未解
 *   node AI/harness/progress_report.js --events 20 # 多印最近 20 筆 hook 事件
 * /progress 這個 skill 就是跑這支，把輸出原樣貼給使用者。
 */
'use strict'
const { collect } = require('./progress_data')

const args = process.argv.slice(2)
const nEvents = args.includes('--events') ? Number(args[args.indexOf('--events') + 1] || 10) : 0
const d = collect({ events: nEvents || 1 })
const pad = (s, n) => String(s ?? '').padEnd(n)
const local = iso => { try { const x = new Date(iso); return new Date(x - x.getTimezoneOffset() * 60000).toISOString().replace('T', ' ').slice(5, 16) } catch { return iso } }
const ago = iso => { const m = Math.round((Date.now() - new Date(iso)) / 60000); return m < 60 ? `${m} 分鐘前` : m < 1440 ? `${Math.round(m / 60)} 小時前` : `${Math.round(m / 1440)} 天前` }
const s = d.sections
const out = []
out.push(`工作進度（${d.root}）  筆記更新 ${d.updated || '?'}  工作區 ${d.dirty_files ? `${d.dirty_files} 個檔案未提交` : '乾淨'}`)
out.push('')
out.push('【任務】'); out.push(...(s['任務'] || ['（progress.md 沒有任務段）']).map(l => '  ' + l))
out.push('【下一步】'); out.push(...(s['下一步'] || []).map(l => '  ' + l))
out.push('【階段】'); out.push(...(s['階段'] || []).map(l => '  ' + l))
out.push('')
out.push(`【負責的代理人：Claude session（24 小時內，${d.sessions.length} 個）】`)
if (!d.sessions.length) out.push('  （events.jsonl 沒有事件）')
for (const x of d.sessions) {
  out.push(`  ${x.id}  ${x.state === 'working' ? '進行中' : '閒置'}  最後活動 ${local(x.last)}（${ago(x.last)}）  工具呼叫 ${x.tools} 次${x.failures ? `，失敗 ${x.failures}` : ''}${x.lastTool ? `，最近 ${x.lastTool}` : ''}`)
  if (x.task) out.push(`      負責：${x.task.text.slice(0, 90)}${x.task.text.length > 90 ? '…' : ''}（${local(x.task.ts)}）`)
  for (const a of x.running_agents) out.push(`      ▶ 子代理 ${a.type}：${a.description}（${ago(a.started)}起）`)
  for (const a of x.done_agents.slice(-2)) out.push(`      ✓ 子代理 ${a.type}：${a.description}（完成 ${local(a.stopped)}）`)
}
out.push('')
out.push('【驗證結果 checks.json】')
if (!d.checks.length) out.push('  （沒有檢查）')
for (const c of d.checks) out.push(`  ${c.status === 'pass' ? '✔' : '✘'} ${pad(c.name, 22)} ${local(c.at)}  ${(c.summary || '').slice(0, 70)}`)
out.push('')
out.push('【最近迭代】'); out.push(...d.iterations.map(i => `  Iteration-${i.n}：${i.title}`))
out.push('【最近提交】'); out.push(...d.commits.slice(0, 5).map(c => `  ${c.hash} ${c.subject.slice(0, 100)}`))
if (s['未解']?.length) { out.push(''); out.push('【未解】'); out.push(...s['未解'].map(l => '  ' + l.slice(0, 120))) }
if (nEvents) {
  out.push(''); out.push(`【最近 ${nEvents} 筆事件（新的在前）】`)
  for (const e of d.events) out.push(`  ${local(e.ts)} ${pad(e.session || '', 8)} ${pad(e.event, 16)} ${(e.tool || '')} ${(e.summary || '').slice(0, 60)}`)
}
out.push(''); out.push('獨立畫面：node AI/harness/progress_ui.js（http://localhost:3010，每 5 秒更新）')
process.stdout.write(out.join('\n') + '\n')
