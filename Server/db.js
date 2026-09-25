/**
 * PostgreSQL 連線池
 *
 * 連線資訊從 repo 根目錄的 .env 讀（DB_HOST / DB_PORT / DB_NAME / DB_USER / DB_PASSWORD，見 .env.example）。
 * 密碼不再寫在程式裡——這個檔案會進公開的 repo。
 */
const path = require('path')
require('dotenv').config({ path: path.join(__dirname, '..', '.env') })
require('dotenv').config({ path: path.join(__dirname, '.env') })      // Server/.env 可覆寫（選用）

const { Pool, types } = require('pg')

// DATE（OID 1082）一律原樣回傳 'YYYY-MM-DD' 字串，不轉成 JS Date。
// node-postgres 預設把 DATE 解析成**本地時區的午夜**，後面再 toISOString()
// 會退回 UTC 的前一天——台北 +8 之下每個日期都少一天：9/11 的收盤被標成 9/10，
// 市場總覽的「資料日期」也跟著錯。這個 bug 在 stocks.js 存活到 Iteration 35。
// 在連線層統一處理，之後任何路由拿到 DATE 都是字串，不必各自記得 ::text。
types.setTypeParser(1082, v => v)

if (!process.env.DB_PASSWORD) {
  console.warn('[db] ⚠ 未設 DB_PASSWORD：請複製 .env.example 成 .env 並填入 PostgreSQL 密碼')
}

const db = new Pool({
  host:     process.env.DB_HOST || 'localhost',
  port:     Number(process.env.DB_PORT || 5432),
  database: process.env.DB_NAME || 'Stock',
  user:     process.env.DB_USER || 'postgres',
  password: process.env.DB_PASSWORD || '',
})

module.exports = db
