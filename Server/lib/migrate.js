/**
 * Migration runner
 *
 * 啟動時自動執行 Server/migrations/*.sql（依檔名排序）
 * 已執行過的 migration 會記錄在 _migrations 表中，不會重複執行
 */

const db   = require('../db')
const fs   = require('fs')
const path = require('path')

async function runMigrations() {
  // 建立 migration 追蹤表
  await db.query(`
    CREATE TABLE IF NOT EXISTS _migrations (
      id         SERIAL PRIMARY KEY,
      filename   VARCHAR(200) UNIQUE NOT NULL,
      applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
  `)

  const dir = path.join(__dirname, '../migrations')
  if (!fs.existsSync(dir)) return

  const files = fs.readdirSync(dir)
    .filter(f => f.endsWith('.sql'))
    .sort()

  for (const file of files) {
    const { rowCount } = await db.query(
      'SELECT 1 FROM _migrations WHERE filename = $1',
      [file]
    )
    if (rowCount > 0) {
      console.log(`[Migration] Already applied: ${file}`)
      continue
    }

    const sql = fs.readFileSync(path.join(dir, file), 'utf8')
    await db.query(sql)
    await db.query('INSERT INTO _migrations (filename) VALUES ($1)', [file])
    console.log(`[Migration] Applied: ${file}`)
  }
}

module.exports = runMigrations
