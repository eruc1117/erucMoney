// Iteration 89：統一前端（../meeting_front_end）的使用說明在真正的瀏覽器裡長什麼樣。
// 把 CRA 的 build/ 用一個臨時的靜態伺服器（:5199，找不到的路徑回 index.html）開起來，後端請求一律回 503，
// 開 /stock/analysis/overview：量標題列三塊的位置（標題／說明文字／開關）、按開關、換五個頁簽量面板高度與字級。
// 先在 ../meeting_front_end 跑過 npm run build 才有 build/。
// 執行：node AI/experiments/iter89_mfe_shot.mjs [截圖目錄]（在 repo 根目錄；Playwright 用 Screen/node_modules 的）
import http from 'node:http'
import fs from 'node:fs'
import path from 'node:path'
import { createRequire } from 'node:module'
import { fileURLToPath } from 'node:url'
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..')
const require = createRequire(path.join(ROOT, 'Screen', 'package.json'))
const { chromium } = require('playwright')
const BUILD = path.resolve(ROOT, '..', 'meeting_front_end', 'build')
const SHOTS = process.argv[2] || path.join(ROOT, 'Screen', '.ui-shots')
fs.mkdirSync(SHOTS, { recursive: true })
const TYPES = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.json': 'application/json', '.png': 'image/png', '.svg': 'image/svg+xml', '.ico': 'image/x-icon', '.woff2': 'font/woff2' }
const srv = http.createServer((req, res) => {
  let p = path.join(BUILD, decodeURIComponent(req.url.split('?')[0]))
  if (!fs.existsSync(p) || fs.statSync(p).isDirectory()) p = path.join(BUILD, 'index.html')
  res.writeHead(200, { 'Content-Type': TYPES[path.extname(p)] || 'application/octet-stream' }); fs.createReadStream(p).pipe(res)
}).listen(5199)
const browser = await chromium.launch().catch(() => chromium.launch({ channel: 'chrome' }))
const page = await browser.newPage({ viewport: { width: 1600, height: 900 } })
const errs = []; page.on('pageerror', e => errs.push(e.message))
await page.route(u => !u.href.startsWith('http://localhost:5199/'), r => r.fulfill({ status: 503, contentType: 'application/json', body: '{}' }))
await page.goto('http://localhost:5199/stock/analysis/overview'); await page.waitForSelector('.stock-page-head')
const head0 = await page.evaluate(() => [...document.querySelector('.stock-page-head').children].map(e => `${e.tagName}.${e.className}@${Math.round(e.getBoundingClientRect().left)}-${Math.round(e.getBoundingClientRect().right)}`))
console.log('標題列三塊：', head0.join('  '), ' 面板（預設）：', await page.locator('.help-panel').count())
await page.getByRole('button', { name: /使用說明/ }).click(); await page.waitForSelector('.help-panel')
await page.screenshot({ path: path.join(SHOTS, 'mfe-overview.png') })
const res = []
for (const k of ['stock', 'simulate', 'holdings', 'signals', 'history']) {
  await page.locator(`.stock-side a[href$="/analysis/${k}"]`).click(); await page.waitForTimeout(200)
  res.push(await page.evaluate(() => { const p = document.querySelector('.help-panel'); return `${p.querySelector('.card-title').textContent}｜h=${Math.round(p.getBoundingClientRect().height)}｜clipped=${p.scrollHeight - p.clientHeight}｜li字級=${getComputedStyle(p.querySelector('li')).fontSize}｜h4=${getComputedStyle(p.querySelector('h4')).fontSize}` }))
}
console.log(res.join('\n'))
await page.screenshot({ path: path.join(SHOTS, 'mfe-history.png') })
console.log('pageerror', errs.length, errs[0] || '')
await browser.close(); srv.close()
