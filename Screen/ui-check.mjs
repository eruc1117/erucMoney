/**
 * 版面檢查：用真正的瀏覽器引擎跑一遍，抓 jsdom 抓不到的問題。
 *
 * 為什麼需要它：smoke.mjs / smoke-interact.mjs 跑在 jsdom 上，
 * 而 jsdom **沒有版面計算引擎**——getBoundingClientRect 永遠回 0。
 * 所以「DOM 完整、沒有錯誤、畫面卻是空的」這類純版面問題，那兩支測試驗不出來。
 * 實際踩過一次：`.card` 加了 overflow: hidden 之後，在直向 flex 容器裡
 * min-height 變成 0，所有卡片被壓扁、內容被裁掉，兩支測試卻全數通過。
 *
 * 這支檢查四件事，每一件都對應一種「看起來壞掉但不會報錯」的狀況：
 *   1. 卡片被壓扁      —— 高度小於門檻
 *   2. 內容被裁掉      —— overflow:hidden 的容器 scrollHeight 明顯大於 clientHeight
 *   3. 整頁橫向溢出    —— body.scrollWidth 超過視窗寬
 *   4. 主要區塊無高度  —— .content 幾乎沒有內容高度
 *
 * 另外會把每一頁截圖到 .ui-shots/，可以直接開來看。
 *
 * 用法：cd Screen && node ui-check.mjs [--light] [頁面 key...]
 *       需要前端 (:5173) 與 Node 伺服器 (:3001) 在跑。
 */
import { chromium } from 'playwright'
import { mkdirSync } from 'node:fs'

const BASE = 'http://localhost:5173/'
const SHOT_DIR = '.ui-shots'

const PAGES = [
  ['overview', '市場總覽'], ['budget', '預算查詢'], ['stock', '個股分析'],
  ['news', '新聞輸入'], ['sentiment', '新聞情緒'], ['prediction', '趨勢預測'],
  ['compare', '預測比對'], ['history', '查詢紀錄'], ['holdings', '我的持股'], ['cash', '閒置資金'],
  ['voting', '投票決策'], ['models', '模型版本'],
]

const args = process.argv.slice(2)
const light = args.includes('--light')
const only = args.filter(a => !a.startsWith('--'))
const targets = only.length ? PAGES.filter(([k]) => only.includes(k)) : PAGES

mkdirSync(SHOT_DIR, { recursive: true })

const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1600, height: 950 } })

const consoleErrors = []
page.on('console', m => { if (m.type() === 'error') consoleErrors.push(m.text()) })
page.on('pageerror', e => consoleErrors.push('pageerror: ' + e.message))

await page.goto(BASE, { waitUntil: 'networkidle' })
await page.evaluate(t => localStorage.setItem('ui.theme', t), light ? 'light' : 'dark')
await page.reload({ waitUntil: 'networkidle' })

// 在瀏覽器裡實際量測版面
const AUDIT = () => {
  const out = { squashed: [], clipped: [], contentHeight: 0, bodyOverflow: 0, cards: 0 }
  const content = document.querySelector('.content')
  if (content) {
    out.contentHeight = content.scrollHeight
    for (const el of content.children) {
      const r = el.getBoundingClientRect()
      out.cards++
      // 高度過小＝被壓扁；空狀態卡片本來就矮，故門檻放在 40px
      if (r.height < 40) {
        out.squashed.push({ cls: el.className, h: Math.round(r.height),
                            text: el.textContent.trim().slice(0, 40) })
      }
      // 內容比容器高很多，又設了 overflow:hidden＝被裁掉
      const cs = getComputedStyle(el)
      if (cs.overflowY === 'hidden' && el.scrollHeight > el.clientHeight + 4) {
        out.clipped.push({ cls: el.className, scroll: el.scrollHeight,
                           client: el.clientHeight,
                           text: el.textContent.trim().slice(0, 40) })
      }
    }
  }
  out.bodyOverflow = document.body.scrollWidth - window.innerWidth
  return out
}

let bad = 0
for (const [key, label] of targets) {
  consoleErrors.length = 0
  await page.click(`.nav-item:has-text("${label}")`)
  await page.waitForTimeout(1800)          // 等資料與圖表
  // 有些頁面要按一下才有內容，空狀態的版面驗不出東西
  const trigger = page.locator('button:has-text("產生配置方案")')
  if (await trigger.count()) { await trigger.first().click(); await page.waitForTimeout(11000) }

  const a = await page.evaluate(AUDIT)
  const shot = `${SHOT_DIR}/${light ? 'light-' : ''}${key}.png`
  await page.screenshot({ path: shot, fullPage: false })

  const problems = []
  if (a.squashed.length) problems.push(`${a.squashed.length} 個區塊被壓扁`)
  if (a.clipped.length) problems.push(`${a.clipped.length} 個區塊內容被裁掉`)
  if (a.bodyOverflow > 1) problems.push(`整頁橫向溢出 ${a.bodyOverflow}px`)
  if (a.contentHeight < 100) problems.push('主要區塊幾乎沒有高度')
  const errs = consoleErrors.filter(e => !/favicon|DevTools/.test(e))
  if (errs.length) problems.push(`console 錯誤 ${errs.length} 則`)

  if (problems.length) {
    bad++
    console.log(`✗ ${label} — ${problems.join('、')}`)
    a.squashed.slice(0, 3).forEach(s =>
      console.log(`    壓扁: <${s.cls}> 高 ${s.h}px　「${s.text}」`))
    a.clipped.slice(0, 3).forEach(c =>
      console.log(`    裁切: <${c.cls}> 內容 ${c.scroll}px / 容器 ${c.client}px　「${c.text}」`))
    errs.slice(0, 2).forEach(e => console.log(`    console: ${e.slice(0, 160)}`))
  } else {
    console.log(`✓ ${label} — ${a.cards} 個區塊、內容高 ${a.contentHeight}px`)
  }
}

await browser.close()
console.log(`\n截圖已存到 ${SHOT_DIR}/`)
console.log(bad ? `${bad} 個頁面有版面問題` : '版面檢查全部通過')
process.exit(bad ? 1 : 0)
