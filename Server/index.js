/**
 * Node.js Server — 處理資料庫與前端畫面資料
 * 監聽 http://localhost:3001
 *
 * 啟動方式：
 *   npm start          (生產)
 *   npm run dev        (開發，自動重載)
 *
 * 架構：
 *   Frontend (React) → Node.js Server (3001) → PostgreSQL
 *   /crawler/*        → Proxy → FastAPI (8000) → FinMind API
 *
 * 應用程式本體在 app.js（路由、中介層、初始化）；這裡只做啟動，測試可以 require('./app') 不監聽。
 */
const { app, init } = require('./app')

async function start() {
  await init()

  app.listen(3001, () => {
    console.log('Node.js Server 已啟動：http://localhost:3001')
    console.log('前端請將 API_URL 指向 http://localhost:3001')
    console.log('爬蟲觸發將 proxy 至 http://localhost:8000')
  })
}

start().catch(err => {
  console.error('伺服器啟動失敗：', err.message)
  process.exit(1)
})
