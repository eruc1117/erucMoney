/**
 * 互動冒煙測試：掛載頁面後真的去點按鈕，檢查該出現的東西有沒有出現。
 *
 * smoke.mjs 只確認「掛得起來」，但這次的問題是「掛起來了、按鈕也在，
 * 點下去卻沒東西」——那種問題只有真的點一下才驗得出來。
 */
import { JSDOM } from 'jsdom'
import { createServer } from 'vite'

const dom = new JSDOM('<!doctype html><html><head></head><body><div id="root"></div></body></html>',
  { url: 'http://localhost:5173/', pretendToBeVisual: true })
const { window } = dom
Object.assign(globalThis, {
  window, document: window.document, navigator: window.navigator,
  HTMLElement: window.HTMLElement, Element: window.Element, Node: window.Node,
  SVGElement: window.SVGElement, localStorage: window.localStorage,
  requestAnimationFrame: cb => setTimeout(cb, 0), cancelAnimationFrame: clearTimeout,
})
class FakeObserver { observe() {} unobserve() {} disconnect() {} }
globalThis.IntersectionObserver = window.IntersectionObserver = FakeObserver
globalThis.ResizeObserver = window.ResizeObserver = FakeObserver
globalThis.Apex = window.Apex = {}
window.SVGElement.prototype.getBBox ||= () => ({ x: 0, y: 0, width: 100, height: 20 })
window.SVGElement.prototype.getComputedTextLength ||= () => 50
window.SVGElement.prototype.getScreenCTM ||= () => ({ a: 1, b: 0, c: 0, d: 1, e: 0, f: 0,
  inverse: () => ({ a: 1, b: 0, c: 0, d: 1, e: 0, f: 0 }) })
window.HTMLCanvasElement.prototype.getContext = () => ({ measureText: () => ({ width: 50 }) })
const TOKENS = { '--bg': '#0f1420', '--bg2': '#161d2e', '--bg3': '#1f2839', '--border': '#2a3446',
  '--text': '#e6ebf5', '--dim': '#8e9bb3', '--blue': '#5b9dff', '--green': '#35c76a',
  '--red': '#ff5f57', '--yellow': '#f2c14e', '--purple': '#b98cff', '--orange': '#f59e5b' }
const realGCS = window.getComputedStyle.bind(window)
globalThis.getComputedStyle = window.getComputedStyle = el => {
  const s = realGCS(el)
  return { ...s, getPropertyValue: n => TOKENS[n] ?? s.getPropertyValue(n) }
}

// 把真實樣式灌進 jsdom：要分辨「元素不存在」和「元素存在但被樣式藏起來」
const cssText = (await import('node:fs')).readFileSync('src/index.css', 'utf8')
const styleEl = window.document.createElement('style')
styleEl.textContent = cssText
window.document.head.appendChild(styleEl)
window.document.documentElement.dataset.theme = 'dark'

const server = await createServer({ server: { middlewareMode: true }, appType: 'custom' })
const React = (await import('react')).default
const { createRoot } = await import('react-dom/client')
globalThis.IS_REACT_ACT_ENVIRONMENT = true
const act = React.act ?? (await import('react-dom/test-utils')).act
const { ThemeProvider } = await server.ssrLoadModule('/src/theme.jsx')
const Page = (await server.ssrLoadModule('/src/pages/PredictionCompare.jsx')).default

const host = document.createElement('div')
document.body.appendChild(host)
const root = createRoot(host)

const wait = ms => new Promise(r => setTimeout(r, ms))
const byText = (sel, re) => [...host.querySelectorAll(sel)].filter(e => re.test(e.textContent))
const click = async el => { await act(async () => { el.click(); await wait(250) }) }
// ApexCharts 在 jsdom 下每張圖要花上百毫秒，固定等待時間不可靠；
// 改成輪詢到條件成立為止，測試才不會因為機器快慢而時好時壞
const waitFor = async (fn, ms = 8000) => {
  const end = Date.now() + ms
  while (Date.now() < end) {
    if (fn()) return true
    await act(async () => { await wait(200) })
  }
  return false
}

await act(async () => {
  root.render(React.createElement(ThemeProvider, null, React.createElement(Page)))
})
await act(async () => { await wait(3500) })   // 等列表與每張卡片的比對資料回來
console.log('   標題列：', host.querySelector('.row-head')?.textContent?.replace(/\s+/g,' ').trim())

// 錯誤邊界攔到什麼？這正是「畫面少一塊」時最該先看的地方
const boundaries = [...host.querySelectorAll('div')]
  .filter(e => /顯示失敗/.test(e.textContent) && e.children.length <= 3)
console.log('   錯誤邊界攔截：', boundaries.length, '處')
boundaries.slice(0, 2).forEach(e =>
  console.log('     ' + e.textContent.replace(/\s+/g, ' ').trim().slice(0, 200)))
const firstCard = host.querySelectorAll('.card')[1]
console.log('   第一張卡片內容：',
  firstCard?.textContent.replace(/\s+/g, ' ').trim().slice(0, 200))

const say = (ok, msg) => console.log(`${ok ? '✓' : '✗'} ${msg}`)
let bad = 0
const check = (ok, msg) => { say(ok, msg); if (!ok) bad++ }

// 1. 卡片與圖表（等到卡片都載完為止）
await waitFor(() => !/載入比對資料/.test(host.textContent))
check(host.querySelectorAll('.card').length > 1, `卡片 ${host.querySelectorAll('.card').length} 張`)
const charts = host.querySelectorAll('.chart-pad')
check(charts.length > 0, `圖表容器 ${charts.length} 個`)
// 統計磚只有「已到期」的紀錄才有。不能假設它落在第 1 頁——
// 使用者隨時會存新預測把它擠到後面。改成先篩「只看已可比對」再驗。
const statusSel = [...host.querySelectorAll('select')]
  .find(el => [...el.options].some(o => /已可比對/.test(o.textContent)))
if (statusSel) {
  await act(async () => {
    statusSel.value = 'matured'
    statusSel.dispatchEvent(new window.Event('change', { bubbles: true }))
    await wait(400)
  })
  await waitFor(() => !/載入比對資料/.test(host.textContent))
}
const tiles = host.querySelectorAll('.stat-grid')
check(tiles.length > 0, `篩選「只看已可比對」後統計磚 ${tiles.length} 組`)
// 驗完把篩選還原，後面的分頁與展開才是在完整清單上測
if (statusSel) {
  await act(async () => {
    statusSel.value = ''
    statusSel.dispatchEvent(new window.Event('change', { bubbles: true }))
    await wait(400)
  })
  await waitFor(() => !/載入比對資料/.test(host.textContent))
}

// 2. 逐日明細
const detailBtn = byText('button', /逐日明細/)[0]
check(!!detailBtn, '找得到「逐日明細」按鈕')
if (detailBtn) {
  const before = host.querySelectorAll('table.data-table').length
  await click(detailBtn)
  const after = host.querySelectorAll('table.data-table').length
  check(after > before, `點擊後表格由 ${before} 張變 ${after} 張`)
  const rows = host.querySelectorAll('table.data-table tbody tr').length
  check(rows > 0, `明細表列數 ${rows}`)
  if (rows > 0) {
    const first = host.querySelector('table.data-table tbody tr')
    console.log('   第一列內容：', first.textContent.replace(/\s+/g, ' ').trim().slice(0, 110))
  }
}

// 3. 分頁
const pager = byText('button', /^\d+$/)
check(pager.length > 0, `分頁按鈕 ${pager.length} 個`)
const firstStock = () => host.querySelector('.card-title')?.textContent
if (pager.length > 1) {
  // 卡片內容可能完全相同（同一檔、同一段預測期間），比卡片文字分不出換頁。
  // 改讀分頁列的「第 X–Y 筆」——那是唯一保證會變的東西。
  const sig = () => (host.textContent.match(/第 \d+–\d+ 筆/g) || []).join('|')
  const before = sig()
  await click(pager[1])
  const after = sig()
  check(before !== after, '切到第 2 頁後卡片有換')
  console.log('   第 1 頁：', before.slice(0, 80))
  console.log('   第 2 頁：', after.slice(0, 80))
}

// 4. 全部展開
const expandBtn = byText('button', /全部展開明細/)[0]
check(!!expandBtn, '找得到「全部展開明細」按鈕')
if (expandBtn) {
  await click(expandBtn)
  const n = host.querySelectorAll('table.data-table').length
  check(n >= 2, `全部展開後表格 ${n} 張`)
}

// 存在但看不見？逐一檢查關鍵區塊的計算樣式
const probe = (sel, label) => {
  const el = host.querySelector(sel)
  if (!el) { console.log(`   [樣式] ${label}：DOM 裡沒有這個元素`); return }
  const cs = realGCS(el)
  console.log(`   [樣式] ${label}：display=${cs.display || '(空)'} visibility=${cs.visibility || '(空)'}`
    + ` height=${el.getBoundingClientRect?.().height ?? '?'} 文字長度=${el.textContent.trim().length}`)
}
probe('table.data-table', '逐日明細表格')
probe('.table-wrap', '表格容器')
probe('.chart-pad', '圖表容器')
probe('.stat-grid', '統計磚')
const pagerCard = [...host.querySelectorAll('.card')].find(c => /上一頁/.test(c.textContent))
console.log('   [樣式] 分頁列：', pagerCard ? '存在，文字＝' +
  pagerCard.textContent.replace(/\s+/g,' ').trim().slice(0, 90) : '不存在')

root.unmount()
await server.close()
console.log(bad ? `\n${bad} 項不通過` : '\n互動全部通過')
process.exit(bad ? 1 : 0)
