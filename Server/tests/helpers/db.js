/**
 * 測試資料庫工具（只對 *_test 資料庫；setup-env.js 已擋住其他名字）
 *
 *   bootstrap()      建基底表 → 跑 18 個 migration → app.init()（user_news 等）。可重複呼叫。
 *   resetUserData()  清掉持股、交易、新聞、投票；使用者只留 admin（id=1）
 *   resetMarket()    清掉行情、籌碼、外資、股票主檔
 *   closeDb()        關連線池（每個測試檔 afterAll 呼叫，避免 jest 掛著）
 */
const fs = require('fs')
const path = require('path')
const db = require('../../db')
const runMigrations = require('../../lib/migrate')

let booted = null

async function bootstrap() {
  if (!booted) {
    booted = (async () => {
      await db.query(fs.readFileSync(path.join(__dirname, 'bootstrap.sql'), 'utf8'))
      await runMigrations()
      const { init } = require('../../app')
      await init()
    })()
  }
  return booted
}

async function resetUserData() {
  await db.query('TRUNCATE user_trades, user_holdings, user_news, voting_results RESTART IDENTITY CASCADE')
  await db.query("DELETE FROM users WHERE username <> 'admin'")
}

async function resetMarket() {
  await db.query('TRUNCATE stock_daily_prices, stock_chip_analysis, stock_foreign_holding, stock_info')
}

async function closeDb() {
  await db.end()
}

module.exports = { db, bootstrap, resetUserData, resetMarket, closeDb }
