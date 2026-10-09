#!/usr/bin/env node
/**
 * Claude Code hook 事件記錄器（harness 第 4 層「執行層」的觀測點）
 *
 * settings.json 的每個 hook 都呼叫這支：stdin 收 Claude Code 送來的 JSON，
 * 壓成一行摘要，append 到 AI/progress/events.jsonl。儀表板「工作進度」頁
 * （Server/routes/progress.js → Screen/src/pages/WorkProgress.jsx）讀它畫活動時間軸。
 *
 * 規則：永遠 exit 0、不印東西到 stdout（印了會被當成給模型的訊息）、任何錯誤都吞掉——
 * 記錄器壞了不能把工作卡住。檔案超過 5 MB 就只留最後 3000 行。
 */
const fs = require('fs')
const path = require('path')

const ROOT = process.env.CLAUDE_PROJECT_DIR || path.resolve(__dirname, '..', '..')
const OUT_DIR = path.join(ROOT, 'AI', 'progress')
const OUT = path.join(OUT_DIR, 'events.jsonl')
const MAX_BYTES = 5 * 1024 * 1024
const KEEP_LINES = 3000

function clip(s, n = 160) {
  if (s === undefined || s === null) return ''
  s = String(s).replace(/\s+/g, ' ').trim()
  return s.length > n ? s.slice(0, n - 1) + '…' : s
}

// 把不同工具的輸入壓成一句人看得懂的摘要
function summarize(tool, input = {}) {
  switch (tool) {
    case 'Bash':
    case 'PowerShell': return clip(input.description || input.command)
    case 'Edit':
    case 'Write':
    case 'Read':
    case 'NotebookEdit': return clip(rel(input.file_path || input.notebook_path))
    case 'Glob':
    case 'Grep': return clip(`${input.pattern || ''} ${input.path ? rel(input.path) : ''}`)
    case 'Agent': return clip(`${input.subagent_type || 'agent'}：${input.description || ''}`)
    case 'Skill': return clip(`/${input.skill || ''} ${input.args || ''}`)
    case 'WebFetch': return clip(input.url)
    case 'WebSearch': return clip(input.query)
    case 'Artifact': return clip(`${input.action || 'publish'} ${input.file_path || input.url || ''}`)
    default: return clip(JSON.stringify(input))
  }
}

function rel(p) {
  if (!p) return ''
  const r = path.relative(ROOT, String(p))
  return r && !r.startsWith('..') ? r.replace(/\\/g, '/') : String(p)
}

function readStdin() {
  try { return fs.readFileSync(0, 'utf8') } catch { return '' }
}

function main() {
  const raw = readStdin()
  let payload = {}
  try { payload = raw ? JSON.parse(raw) : {} } catch { payload = { parse_error: true, raw: clip(raw, 200) } }

  const ev = {
    ts: new Date().toISOString(),
    event: payload.hook_event_name || process.argv[2] || 'unknown',
    session: payload.session_id ? String(payload.session_id).slice(0, 8) : undefined,
  }
  const tool = payload.tool_name
  if (tool) {
    ev.tool = tool
    ev.summary = summarize(tool, payload.tool_input || {})
    // PostToolUse 的回應：只記成功／失敗，不存內容（內容可能很大，也可能含密鑰）
    if (payload.tool_response !== undefined) {
      const r = payload.tool_response
      const errored = (r && typeof r === 'object' && (r.is_error || r.error || (typeof r.exit_code === 'number' && r.exit_code !== 0)))
      ev.ok = !errored
    }
  }
  if (ev.event === 'UserPromptSubmit') ev.summary = clip(payload.prompt, 200)
  if (ev.event === 'SessionStart') ev.summary = clip(payload.source || '')
  if (ev.event === 'SubagentStop' || ev.event === 'SubagentStart') {
    ev.summary = clip(payload.agent_type || payload.subagent_type || payload.agent_id || payload.agent_name || '')
  }
  if (ev.event === 'Notification') ev.summary = clip(payload.message || payload.title || '')
  if (ev.event === 'PreCompact') ev.summary = clip(payload.trigger || '')

  fs.mkdirSync(OUT_DIR, { recursive: true })
  fs.appendFileSync(OUT, JSON.stringify(ev) + '\n')

  try {
    if (fs.statSync(OUT).size > MAX_BYTES) {
      const lines = fs.readFileSync(OUT, 'utf8').split('\n').filter(Boolean)
      fs.writeFileSync(OUT, lines.slice(-KEEP_LINES).join('\n') + '\n')
    }
  } catch { /* 輪替失敗就算了 */ }
}

try { main() } catch { /* 記錄器永遠不擋工作 */ }
process.exit(0)
