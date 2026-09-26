/**
 * Migration runner
 *
 * 啟動時自動執行 Server/migrations/*.sql（依檔名排序）
 * 已執行過的 migration 會記錄在 _migrations 表中，不會重複執行
 *
 * @param {object} [client] 可傳入別的連線池（測試對臨時資料庫跑 migration 用）；預設用 db.js 的池
 */

const db   = require('../db')
const fs   = require('fs')
const path = require('path')

async function runMigrations(client = db) {
  // 建立 migration 追蹤表
  await client.query(`
    CREATE TABLE IF NOT EXISTS _migrations (
      id         SERIAL PRIMARY KEY,
      filename   VARCHAR(200) UNIQUE NOT NULL,
      applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
  `)

  const dir = path.join(__dirname, '../migrations')
  if (!fs.existsSync(dir)) return []

  const files = fs.readdirSync(dir)
    .filter(f => f.endsWith('.sql'))
    .sort()

  const applied = []
  for (const file of files) {
    const { rowCount } = await client.query(
      'SELECT 1 FROM _migrations WHERE filename = $1',
      [file]
    )
    if (rowCount > 0) {
      console.log(`[Migration] Already applied: ${file}`)
      continue
    }

    const sql = fs.readFileSync(path.join(dir, file), 'utf8')
    await client.query(sql)
    await client.query('INSERT INTO _migrations (filename) VALUES ($1)', [file])
    console.log(`[Migration] Applied: ${file}`)
    applied.push(file)
  }
  return applied
}

module.exports = runMigrations
