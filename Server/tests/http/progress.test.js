/**
 * 工作進度 /progress：只讀檔案與 git，資料來源用 PROGRESS_ROOT 指到暫存目錄。
 * 管理端點：匿名 401、一般使用者 403、admin 200 且各區塊解析正確。
 */
const fs = require('fs')
const os = require('os')
const path = require('path')
const request = require('supertest')
const { getApp } = require('../helpers/app')
const { closeDb } = require('../helpers/db')
const { localToken, calendarToken, bearer } = require('../helpers/tokens')
const { parseHandoff } = require('../../routes/progress')

let app, tmp
const ADMIN = bearer(localToken({ id: 1, role: 'admin' }))
const USER = bearer(calendarToken({ id: 7701, username: 'viewer' }))

const HANDOFF = `# 交接
**更新：** 2026-10-09

## 任務
紙上交易（階段 4）

## 產出
- Crawler/portfolio_paper.py
- Server/migrations/025_portfolio_paper.sql

## 已完成
- 回測引擎
- 候選標記

## 決策
- 候選不換（2026-10-09）

## 未解
- 公告日精確度

## 下一步
寫 Iteration-54.md

## 階段
- [x] 階段 1 股票池
- [x] 階段 2 回測
- [~] 階段 4 紙上交易
- [ ] 階段 5 保留期
`

beforeAll(async () => {
  tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'progress-'))
  fs.writeFileSync(path.join(tmp, 'progress.md'), HANDOFF)
  fs.mkdirSync(path.join(tmp, 'AI', 'progress'), { recursive: true })
  fs.mkdirSync(path.join(tmp, 'AI', 'Doc', 'Iterations'), { recursive: true })
  fs.writeFileSync(path.join(tmp, 'AI', 'progress', 'checks.json'), JSON.stringify({ updated_at: '2026-10-09T01:00:00Z', checks: [{ name: 'jest', status: 'pass', at: '2026-10-09T01:00:00Z', summary: 'ok' }] }))
  fs.writeFileSync(path.join(tmp, 'AI', 'progress', 'events.jsonl'), [
    JSON.stringify({ ts: '2026-10-01T10:00:00Z', event: 'SessionStart', session: 'aaaa1111' }),
    JSON.stringify({ ts: '2026-10-02T10:00:00Z', event: 'PostToolUse', session: 'bbbb2222', tool: 'Edit', summary: 'Server/app.js', ok: true }),
    'not json',
    JSON.stringify({ ts: '2026-10-02T10:01:00Z', event: 'Stop', session: 'bbbb2222' }),
  ].join('\n') + '\n')
  fs.writeFileSync(path.join(tmp, 'AI', 'Doc', 'Iterations', 'Iteration-07.md'), '# Iteration 7 — 籌碼全史回補\n\n**日期：** 2026-08-07\n**依據：** 使用者：「補齊」\n')
  fs.writeFileSync(path.join(tmp, 'AI', 'Doc', 'Iterations', 'Iteration-12.md'), '# Iteration 12 — 資料擴充至 1994 年\n\n**日期：** 2026-08-12\n')
  process.env.PROGRESS_ROOT = tmp
  app = await getApp()
})
afterAll(async () => {
  delete process.env.PROGRESS_ROOT
  fs.rmSync(tmp, { recursive: true, force: true })
  await closeDb()
})

describe('權限', () => {
  it('匿名 401、一般使用者 403', async () => {
    expect((await request(app).get('/progress')).status).toBe(401)
    expect((await request(app).get('/progress').set(USER)).status).toBe(403)
  })
})

describe('內容', () => {
  let body
  beforeAll(async () => {
    const r = await request(app).get('/progress').set(ADMIN)
    expect(r.status).toBe(200)
    body = r.body
  })
  it('交接筆記分段解析，階段有三種狀態', () => {
    const h = body.handoff
    expect(h.exists).toBe(true)
    expect(h.task).toBe('紙上交易（階段 4）')
    expect(h.outputs).toEqual(['Crawler/portfolio_paper.py', 'Server/migrations/025_portfolio_paper.sql'])
    expect(h.completed).toHaveLength(2)
    expect(h.decisions[0]).toMatch(/候選不換/)
    expect(h.open_issues).toEqual(['公告日精確度'])
    expect(h.next_action).toBe('寫 Iteration-54.md')
    expect(h.updated).toBe('2026-10-09')
    expect(h.stages.map(s => s.status)).toEqual(['done', 'done', 'doing', 'todo'])
  })
  it('驗證結果照檔案回', () => {
    expect(body.checks.checks).toHaveLength(1)
    expect(body.checks.checks[0].name).toBe('jest')
  })
  it('事件：壞行略過、最新在前、每日筆數、session 數', () => {
    const e = body.events
    expect(e.total).toBe(3)
    expect(e.recent[0].event).toBe('Stop')
    expect(e.per_day).toEqual([{ d: "2026-10-01", n: 1 }, { d: "2026-10-02", n: 2 }])
    expect(e.sessions).toBe(2)
    expect(e.active).toBe(false)
  })
  it('迭代紀錄由新到舊、標題與日期', () => {
    expect(body.iterations.map(i => i.n)).toEqual([12, 7])
    expect(body.iterations[1]).toMatchObject({ title: '籌碼全史回補', date: '2026-08-07', basis: '使用者：「補齊」' })
  })
  it('暫存目錄不是 git repo → git.available = false 但不會 500', () => {
    expect(body.git.available).toBe(false)
    expect(body.git.commits).toEqual([])
  })
  it('harness 七層：暫存目錄沒有 CLAUDE.md／skills，前兩層 false', () => {
    expect(body.harness).toHaveLength(7)
    expect(body.harness[0].ok).toBe(false)
    expect(body.harness[1].ok).toBe(false)
  })
})

describe('parseHandoff 邊界', () => {
  it('空檔案回空結構', () => {
    const h = parseHandoff(null)
    expect(h.task).toBe('')
    expect(h.stages).toEqual([])
  })
  it('標題帶括號註解也能對上：## 未解（缺證據）', () => {
    const h = parseHandoff('## 未解（缺證據）\n- a\n- b\n')
    expect(h.open_issues).toEqual(['a', 'b'])
  })
})
