/**
 * 使用說明面板的版面檢查（Iteration 89）：用真正的瀏覽器引擎量，jsdom 沒有版面計算。
 *
 * 開使用說明模式後逐一點 22 個頁簽，深色、淺色各一輪，每頁檢查：
 *   1. 面板有高度（沒被 .content 的直向 flex 壓扁——.card 有 overflow:hidden，壓扁時內容會被裁掉又不報錯）
 *   2. 面板內容沒被裁掉（scrollHeight 不超過 clientHeight）
 *   3. 面板是 .content 的第一個子元素，而且在可視範圍最上方
 *   4. 整頁沒有橫向溢出
 * 另外量 1100px 寬（兩欄）與 480px 寬（單欄、側欄收起）各一頁並截圖；再量七種視窗寬度下的頂欄（開關不折行、標題高度不超過加開關之前）。
 *
 * 後端請求一律攔下回 503：假的登入 token 打到真後端會 401 被登出；這支只看說明面板，不看各頁資料。
 *
 * 用法：cd Screen && node tests/help-ui.mjs [截圖目錄]   （需要 npm run dev 在 :5173）
 */
import { chromium } from 'playwright'
import { mkdirSync } from 'node:fs'
import path from 'node:path'

const BASE = 'http://localhost:5173/'
const SHOTS = process.argv[2] || '.ui-shots'
mkdirSync(SHOTS, { recursive: true })

// Playwright 自帶的 Chromium 沒下載時改用本機安裝的 Chrome（獨立的暫時設定檔，不碰使用者的瀏覽器資料）
const browser = await chromium.launch().catch(() => chromium.launch({ channel: 'chrome' }))
console.log(`瀏覽器：${browser.browserType().name()} ${browser.version()}`)
let bad = 0
const check = (ok, msg) => { console.log(`${ok ? '✓' : '✗'} ${msg}`); if (!ok) bad++ }

const AUDIT = () => {
  const p = document.querySelector('.help-panel')
  const content = document.querySelector('.content')
  if (!p) return null
  const r = p.getBoundingClientRect(), c = content.getBoundingClientRect()
  return {
    h: Math.round(r.height), clipped: p.scrollHeight - p.clientHeight,
    first: content.firstElementChild === p, top: Math.round(r.top - c.top),
    overflowX: document.documentElement.scrollWidth - window.innerWidth,
    cols: getComputedStyle(p.querySelector('.help-grid')).gridTemplateColumns.split(' ').length,
    secs: p.querySelectorAll('.help-sec').length, title: p.querySelector('.card-title').textContent,
    border: getComputedStyle(p).borderLeftWidth,
  }
}

async function open(theme, width) {
  const page = await browser.newPage({ viewport: { width, height: 950 } })
  const errors = []
  page.on('pageerror', e => errors.push(e.message))
  await page.route(u => !u.href.startsWith(BASE), r => r.fulfill({ status: 503, contentType: 'application/json', body: '{"detail":"help-ui"}' }))
  await page.addInitScript(t => {
    localStorage.setItem('ui.theme', t); localStorage.setItem('ui.help', '1')
    localStorage.setItem('auth_token', 'help-ui')
    localStorage.setItem('auth_user', JSON.stringify({ id: 1, username: 'help-ui', role: 'user', display_name: '版面檢查' }))
  }, theme)
  await page.goto(BASE, { waitUntil: 'domcontentloaded' })
  await page.waitForSelector('.help-panel')
  return { page, errors }
}

for (const theme of ['dark', 'light']) {
  const { page, errors } = await open(theme, 1600)
  const navs = await page.locator('.sidebar .nav-item').all()
  let ok = 0
  const heights = []
  for (const [i, nav] of navs.entries()) {
    await nav.click()
    await page.waitForTimeout(150)
    const a = await page.evaluate(AUDIT)
    const label = (await nav.textContent()).trim()
    const good = a && a.h >= 120 && a.clipped <= 1 && a.first && a.top <= 30 && a.overflowX <= 0 && a.secs === 3 && a.border === '3px'
    if (good) { ok++; heights.push(a.h) } else check(false, `${theme} ${label}：${JSON.stringify(a)}`)
    if ([0, 2, 13].includes(i)) await page.screenshot({ path: path.join(SHOTS, `help-${theme}-${i}.png`) })
  }
  check(ok === 22 && navs.length === 22, `${theme}：22 個頁簽裡 ${ok} 個面板版面正常（高度 ${Math.min(...heights)}～${Math.max(...heights)}px、沒被裁、在內容區最上方、無橫向溢出）`)
  check(errors.length === 0, `${theme}：頁面錯誤 ${errors.length} 個${errors[0] ? '：' + errors[0].slice(0, 160) : ''}`)

  // 關掉：面板消失、按鈕不再是 active
  await page.locator('.topbar button', { hasText: '使用說明' }).click()
  check(await page.locator('.help-panel').count() === 0, `${theme}：按頂欄「使用說明」關閉後面板消失`)
  await page.close()
}

for (const [width, want] of [[1100, 2], [480, 1]]) {
  const { page } = await open('dark', width)
  if (width > 760) await page.locator('.sidebar .nav-item').nth(13).click()   // 交易模擬：條目最多的一頁之一
  await page.waitForTimeout(150)
  const a = await page.evaluate(AUDIT)
  check(a && a.cols === want && a.clipped <= 1 && a.overflowX <= 0, `${width}px 寬：說明排成 ${a?.cols} 欄（預期 ${want}）、沒被裁、無橫向溢出`)
  await page.screenshot({ path: path.join(SHOTS, `help-w${width}.png`) })
  await page.close()
}

// 頂欄：多了一顆開關以後，標題最長的頁簽（正式策略、交易模擬）不能比原本更擠。
// 「原本」＝同一頁把說明開關藏起來、把本輪加的兩條頂欄樣式（按鈕不折行、窄視窗收間距）還原後量到的標題高度。
// 開關按鈕上的字一律不折行；視窗 1900px 以下開關只留「？」（1901 與 1900 各量一次，就是門檻兩側）。
const MEASURE = () => ({
  btn: Math.round(Math.max(...[...document.querySelectorAll('.topbar .ui-toggle button')].filter(b => b.offsetParent).map(b => b.getBoundingClientRect().height))),
  title: Math.round(document.querySelector('.page-title').getBoundingClientRect().height),
})
for (const width of [1920, 1901, 1900, 1750, 1600, 1440, 1366]) {
  const { page } = await open('dark', width)
  const now = [], base = []
  for (const i of [0, 11, 13]) {
    await page.locator('.sidebar .nav-item').nth(i).click()
    await page.waitForTimeout(100)
    now.push(await page.evaluate(MEASURE))
  }
  const label = (await page.locator('.topbar .ui-toggle button').first().innerText()).trim()
  // 用開關自己的 aria-label 選：.topbar-right 的子元素全是 div，:first-of-type 會選到指數那一塊
  await page.addStyleTag({ content: '.topbar-right > .ui-toggle:has(button[aria-label="使用說明模式"]) { display: none } .ui-toggle button { white-space: normal } .topbar-right { gap: 1rem }' })
  const hidden = await page.locator('.topbar .ui-toggle button[aria-label="使用說明模式"]').isHidden()
  for (const i of [0, 11, 13]) {
    await page.locator('.sidebar .nav-item').nth(i).click()
    await page.waitForTimeout(100)
    base.push(await page.evaluate(MEASURE))
  }
  const want = width > 1900 ? '？ 使用說明' : '？'
  const ok = hidden && now.every((m, k) => m.btn <= 24 && m.title <= base[k].title) && label === want
  check(ok, `${width}px 寬頂欄（市場總覽／正式策略／交易模擬）：標題高 ${now.map(m => m.title).join('／')}px（原本 ${base.map(m => m.title).join('／')}），按鈕高 ${now.map(m => m.btn).join('／')}px（原本 ${base.map(m => m.btn).join('／')}），說明鈕「${label}」，量原本時開關${hidden ? '已藏起' : '沒藏到'}`)
  await page.close()
}

await browser.close()
console.log(bad ? `\n${bad} 項沒過` : '\n使用說明面板版面檢查全過')
process.exit(bad ? 1 : 0)
