/**
 * 測試環境：先把根目錄 .env 讀進來（拿 DB_PASSWORD 這類本機才有的值），
 * 再用 Server/.env.test 覆寫（DB_NAME=Stock_test、測試密鑰…）。
 * DB_NAME 不是 _test 結尾就直接拒跑——這是唯一擋住「對正式庫跑測試」的保險。
 */
const path = require('path')
const dotenv = require('dotenv')

dotenv.config({ path: path.join(__dirname, '..', '..', '.env'), quiet: true })
dotenv.config({ path: path.join(__dirname, '..', '.env.test'), override: true, quiet: true })

if (!/_test$/i.test(process.env.DB_NAME || '')) {
  throw new Error(`拒絕執行：DB_NAME=${process.env.DB_NAME}，測試只能對 *_test 資料庫跑（見 Server/.env.test）`)
}
process.env.NODE_ENV = 'test'
