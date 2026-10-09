#!/usr/bin/env node
/**
 * 驗證結果記錄器（harness 第 5／7 層：reviewer 要回證據、完成條件要看得到）
 *
 * 兩種用法：
 *   1. 跑一個指令並記結果（exit 0 = pass）：
 *        node AI/harness/record_check.js --name jest --cwd Server -- npm test
 *        node AI/harness/record_check.js --name pytest --cwd Crawler -- python -m pytest -q
 *      指令的輸出照常印出來（模型還是要看測試訊息），最後 30 行存進 checks.json 當證據。
 *   2. 直接記一個判定（給 reviewer 的 PASS／FAIL、或人工確認）：
 *        node AI/harness/record_check.js --name evidence-reviewer --status pass --summary "12 項主張全部 verified"
 *        node AI/harness/record_check.js --name evidence-reviewer --status fail --summary "2 項 incorrect，見 AI/progress/review.md"
 *
 * 結果寫進 AI/progress/checks.json（同名覆蓋、其餘保留），同時在 events.jsonl 記一筆 check 事件。
 * 儀表板「工作進度」頁的「驗證結果」表就是讀這個檔。
 */
const fs = require('fs')
const path = require('path')
const { spawnSync } = require('child_process')

const ROOT = process.env.CLAUDE_PROJECT_DIR || path.resolve(__dirname, '..', '..')
const DIR = path.join(ROOT, 'AI', 'progress')
const CHECKS = path.join(DIR, 'checks.json')
const EVENTS = path.join(DIR, 'events.jsonl')

function parseArgs(argv) {
  const opts = { name: null, cwd: ROOT, status: null, summary: '', cmd: null, timeout: 15 * 60 * 1000 }
  const i = argv.indexOf('--')
  const own = i >= 0 ? argv.slice(0, i) : argv
  if (i >= 0) opts.cmd = argv.slice(i + 1)
  for (let k = 0; k < own.length; k++) {
    const a = own[k]
    if (a === '--name') opts.name = own[++k]
    else if (a === '--cwd') opts.cwd = path.resolve(ROOT, own[++k])
    else if (a === '--status') opts.status = own[++k]
    else if (a === '--summary') opts.summary = own[++k]
    else if (a === '--timeout') opts.timeout = Number(own[++k]) * 1000
  }
  return opts
}

function load() {
  try { return JSON.parse(fs.readFileSync(CHECKS, 'utf8')) } catch { return { updated_at: null, checks: [] } }
}

function save(doc) {
  fs.mkdirSync(DIR, { recursive: true })
  fs.writeFileSync(CHECKS, JSON.stringify(doc, null, 2) + '\n')
}

function record(entry) {
  const doc = load()
  doc.checks = (doc.checks || []).filter(c => c.name !== entry.name)
  doc.checks.push(entry)
  doc.updated_at = entry.at
  save(doc)
  try {
    fs.appendFileSync(EVENTS, JSON.stringify({ ts: entry.at, event: 'check', summary: `${entry.name}：${entry.status}${entry.summary ? '｜' + entry.summary : ''}`, ok: entry.status === 'pass' }) + '\n')
  } catch { /* 事件記不到不影響結果 */ }
}

function tail(s, n = 30) {
  const lines = String(s || '').split(/\r?\n/).filter(l => l.trim())
  return lines.slice(-n).join('\n')
}

function main() {
  const o = parseArgs(process.argv.slice(2))
  if (!o.name) { console.error('用法：record_check.js --name <名稱> [--cwd 目錄] -- <指令…>  或  --status pass|fail|skip --summary "…"'); process.exit(2) }

  if (o.cmd && o.cmd.length) {
    const started = Date.now()
    const r = spawnSync(o.cmd.join(' '), { cwd: o.cwd, shell: true, encoding: 'utf8', timeout: o.timeout,
      env: { ...process.env, PYTHONUTF8: '1', FORCE_COLOR: '0', NO_COLOR: '1' }, maxBuffer: 64 * 1024 * 1024 })
    if (r.stdout) process.stdout.write(r.stdout)
    if (r.stderr) process.stderr.write(r.stderr)
    const timedOut = r.error && r.error.code === 'ETIMEDOUT'
    const status = timedOut ? 'fail' : r.status === 0 ? 'pass' : 'fail'
    record({
      name: o.name, status, at: new Date().toISOString(),
      command: o.cmd.join(' '), cwd: path.relative(ROOT, o.cwd) || '.',
      exit_code: timedOut ? 'timeout' : r.status,
      duration_s: Math.round((Date.now() - started) / 1000),
      summary: o.summary || (timedOut ? `逾時（${o.timeout / 1000}s）` : status === 'pass' ? '指令成功（exit 0）' : `exit ${r.status}`),
      detail: tail((r.stdout || '') + '\n' + (r.stderr || '')),
    })
    process.exit(status === 'pass' ? 0 : 1)
  }

  if (!['pass', 'fail', 'skip'].includes(o.status)) { console.error('--status 要是 pass、fail 或 skip'); process.exit(2) }
  record({ name: o.name, status: o.status, at: new Date().toISOString(), summary: o.summary, detail: '' })
  console.log(`[check] ${o.name}：${o.status}${o.summary ? '｜' + o.summary : ''}`)
}

main()
