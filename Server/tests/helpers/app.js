/** 給 http 測試用：bootstrap 測試庫後回傳 express app（不 listen）。 */
const { bootstrap } = require('./db')

let ready = null
function getApp() {
  if (!ready) ready = bootstrap().then(() => require('../../app').app)
  return ready
}

module.exports = { getApp }
