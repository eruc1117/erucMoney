/**
 * 18 個 SQL migration 對一個全新的資料庫（Stock_migtest）：跑得過、重跑冪等、關鍵索引存在。
 * 資料庫建了就刪；需要 DB_USER 有 CREATEDB 權限，沒有就整個 describe 跳過並印出原因。
 */
const fs = require('fs')
const path = require('path')
const { Pool, Client } = require('pg')
const runMigrations = require('../../lib/migrate')

const DBNAME = 'Stock_migtest'
const cfg = () => ({ host: process.env.DB_HOST, port: Number(process.env.DB_PORT), user: process.env.DB_USER, password: process.env.DB_PASSWORD })

async function withAdmin(fn) {
  const c = new Client({ ...cfg(), database: 'postgres' })
  await c.connect()
  try { return await fn(c) } finally { await c.end() }
}

let pool, skipReason = ''

beforeAll(async () => {
  try {
    await withAdmin(async c => {
      await c.query(`DROP DATABASE IF EXISTS "${DBNAME}"`)
      await c.query(`CREATE DATABASE "${DBNAME}"`)
    })
    pool = new Pool({ ...cfg(), database: DBNAME })
  } catch (e) {
    skipReason = e.message
    console.warn('[migrations.test] 無法建立臨時資料庫，跳過：', e.message)
  }
})

afterAll(async () => {
  if (pool) await pool.end()
  if (!skipReason) await withAdmin(c => c.query(`DROP DATABASE IF EXISTS "${DBNAME}"`))
})

describe('migrations', () => {
  it('全新資料庫：基底表 + 18 個 migration 全部套用', async () => {
    if (skipReason) return
    await pool.query(fs.readFileSync(path.join(__dirname, '..', 'helpers', 'bootstrap.sql'), 'utf8'))
    const applied = await runMigrations(pool)
    const files = fs.readdirSync(path.join(__dirname, '..', '..', 'migrations')).filter(f => f.endsWith('.sql')).sort()
    expect(applied).toEqual(files)
    expect(applied).toHaveLength(18)
  })
  it('重跑冪等：第二次不套用任何檔案，_migrations 筆數不變', async () => {
    if (skipReason) return
    const again = await runMigrations(pool)
    expect(again).toEqual([])
    const { rows } = await pool.query('SELECT COUNT(*)::int AS n FROM _migrations')
    expect(rows[0].n).toBe(18)
  })
  it('users 表：role 檢查約束、admin 占位列、external_id 部分唯一索引', async () => {
    if (skipReason) return
    const idx = await pool.query("SELECT indexdef FROM pg_indexes WHERE tablename = 'users' AND indexname = 'uq_users_external_id'")
    expect(idx.rows[0].indexdef).toMatch(/UNIQUE INDEX .* \(external_id\) WHERE \(external_id IS NOT NULL\)/)
    const admin = await pool.query("SELECT id, role, password_hash FROM users WHERE username = 'admin'")
    expect(admin.rows[0]).toEqual({ id: 1, role: 'admin', password_hash: '' })
    await expect(pool.query("INSERT INTO users (username, role) VALUES ('x', 'root')")).rejects.toThrow(/users_role_check/)
  })
  it('持股／交易以 (user_id, stock_id) 為唯一鍵並 CASCADE 到 users', async () => {
    if (skipReason) return
    const idx = await pool.query("SELECT indexname FROM pg_indexes WHERE tablename = 'user_holdings'")
    expect(idx.rows.map(r => r.indexname)).toContain('uq_user_holdings_user_stock')
    const fk = await pool.query(`
      SELECT tc.table_name, rc.delete_rule FROM information_schema.table_constraints tc
      JOIN information_schema.referential_constraints rc ON tc.constraint_name = rc.constraint_name
      WHERE tc.constraint_type = 'FOREIGN KEY' AND tc.table_name IN ('user_holdings', 'user_trades', 'user_news') ORDER BY 1`)
    expect(fk.rows).toEqual([
      { table_name: 'user_holdings', delete_rule: 'CASCADE' },
      { table_name: 'user_news', delete_rule: 'SET NULL' },
      { table_name: 'user_trades', delete_rule: 'CASCADE' },
    ])
  })
})
