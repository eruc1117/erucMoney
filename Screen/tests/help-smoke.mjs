/**
 * 使用說明模式的互動冒煙（Iteration 89）：在 jsdom 裡掛真正的 App，
 * 按頂欄「使用說明」→ 逐一點側欄每個頁簽，確認說明面板換成那一頁的內容；再關掉、確認記進 localStorage。
 *
 * 為什麼掛整個 App 而不是只掛 PageHelp：要驗的是「每個頁簽都接上了」，那是 App／Topbar／Sidebar 的接線。
 * fetch 換成永不回應的 Promise：各頁停在「載入中」，不會打到真的後端（假 token 會被 401 登出），
 * 也不會因為假資料的形狀讓頁面自己炸掉——頁面本身掛不掛得起來是 smoke.mjs 的事。
 *
 * 用法：cd Screen && node tests/help-smoke.mjs
 */
import { JSDOM } from 'jsdom'
import { createServer } from 'vite'
import fs from 'node:fs'

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
// 圖表主題會把 CSS 變數解析成色值（theme.jsx 的 cssColor）；jsdom 不套外部樣式表，直接給值
const TOKENS = { '--bg': '#0f1420', '--bg2': '#161d2e', '--bg3': '#1f2839', '--border': '#2a3446',
  '--text': '#e6ebf5', '--dim': '#8e9bb3', '--blue': '#5b9dff', '--green': '#35c76a',
  '--red': '#ff5f57', '--yellow': '#f2c14e', '--purple': '#b98cff', '--orange': '#f59e5b' }
const realGCS = window.getComputedStyle.bind(window)
globalThis.getComputedStyle = window.getComputedStyle = el => {
  const s = realGCS(el)
  return { ...s, getPropertyValue: n => TOKENS[n] ?? s.getPropertyValue(n) }
}
globalThis.fetch = window.fetch = () => new Promise(() => {})

// 假的登入狀態：App 沒有使用者只會顯示登入頁
localStorage.setItem('auth_token', 'smoke')
localStorage.setItem('auth_user', JSON.stringify({ id: 1, username: 'smoke', role: 'user', display_name: '冒煙' }))

const errors = []
const origError = console.error
console.error = (...a) => { errors.push(a.map(String).join(' ')); origError(...a) }

const server = await createServer({ server: { middlewareMode: true }, appType: 'custom' })
const React = (await import('react')).default
const { createRoot } = await import('react-dom/client')
globalThis.IS_REACT_ACT_ENVIRONMENT = true
const act = React.act ?? (await import('react-dom/test-utils')).act
const { ThemeProvider } = await server.ssrLoadModule('/src/theme.jsx')
const App = (await server.ssrLoadModule('/src/App.jsx')).default
const { HELP } = await server.ssrLoadModule('/src/lib/helpContent.js')

const host = document.getElementById('root')
const root = createRoot(host)
const wait = ms => new Promise(r => setTimeout(r, ms))
const click = async el => { await act(async () => { el.click(); await wait(120) }) }
let bad = 0
const check = (ok, msg) => { console.log(`${ok ? '✓' : '✗'} ${msg}`); if (!ok) bad++ }
const panel = () => host.querySelector('.help-panel')
const helpBtn = () => [...host.querySelectorAll('.topbar button')].find(b => /使用說明/.test(b.textContent))

await act(async () => { root.render(React.createElement(ThemeProvider, null, React.createElement(App))) })
await act(async () => { await wait(300) })

check(Boolean(host.querySelector('.sidebar')), '假登入後 App 掛起來（有側欄，不是登入頁）')
check(Boolean(helpBtn()), '頂欄有「使用說明」按鈕')
check(!panel(), '預設關閉：沒有說明面板')
check(helpBtn()?.getAttribute('aria-pressed') === 'false', '按鈕 aria-pressed=false')

await click(helpBtn())
check(Boolean(panel()), '按下後出現說明面板')
check(localStorage.getItem('ui.help') === '1', "localStorage ui.help = '1'")
check(helpBtn()?.className === 'active' && helpBtn()?.getAttribute('aria-pressed') === 'true', '按鈕變成 active、aria-pressed=true')

// 逐一點側欄：面板要換成那一頁的用途句與第一個步驟，而且是 .content 的第一個子元素（在頁面內容上方）
const keysInOrder = [...fs.readFileSync('src/components/Sidebar.jsx', 'utf8').matchAll(/\{ key: '(\w+)'/g)].map(m => m[1])
const navs = [...host.querySelectorAll('.sidebar .nav-item')]
check(navs.length === keysInOrder.length && navs.length === 22, `側欄 ${navs.length} 個頁簽`)
let okPages = 0
for (let i = 0; i < navs.length; i++) {
  const key = keysInOrder[i]
  await click(navs[i])
  const p = panel()
  const h = HELP[key]
  const ok = Boolean(p) && Boolean(h)
    && p.querySelector('.help-what')?.textContent === h.what
    && p.querySelector('.help-sec li')?.textContent === h.steps[0]
    && p.querySelectorAll('.help-sec').length === 3
    && host.querySelector('.content')?.firstElementChild === p
    && p.querySelector('.card-title')?.textContent === `使用說明：${host.querySelector('.page-title')?.textContent}`
  if (ok) okPages++
  else check(false, `頁簽 ${key}（${navs[i].textContent.trim()}）的說明沒有正確顯示`)
}
check(okPages === 22, `22 個頁簽裡 ${okPages} 個顯示自己的說明（用途句、第一步、三段、標題、位置都對）`)

// 面板上的「關閉說明」也能關，而且關了以後換頁簽不會再出現
await click([...panel().querySelectorAll('button')].find(b => /關閉說明/.test(b.textContent)))
check(!panel(), '按「關閉說明」後面板消失')
check(localStorage.getItem('ui.help') === '0', "localStorage ui.help = '0'")
await click(navs[0])
check(!panel(), '關閉後換頁簽不會再出現')

// 重新掛載：開著的狀態要記得
localStorage.setItem('ui.help', '1')
await act(async () => { root.unmount() })
const root2 = createRoot(host)
await act(async () => { root2.render(React.createElement(ThemeProvider, null, React.createElement(App))) })
await act(async () => { await wait(200) })
check(Boolean(panel()), "ui.help = '1' 時重新載入，面板直接開著")

const crashed = errors.filter(e => /Uncaught|The above error|Cannot read|is not a function|undefined is not/.test(e)
  && !/apexcharts|svg\.js|getBBox|getScreenCTM|getComputedTextLength/i.test(e))
check(crashed.length === 0, `render 期間錯誤 ${crashed.length} 個${crashed[0] ? '：' + crashed[0].split('\n')[0].slice(0, 200) : ''}`)

await server.close()
console.log(bad ? `\n${bad} 項沒過` : '\n使用說明模式互動冒煙全過')
process.exit(bad ? 1 : 0)
