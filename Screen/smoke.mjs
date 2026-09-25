/**
 * 前端冒煙測試：在 jsdom 裡實際掛載頁面，抓出「build 過得了但 render 會炸」的錯誤。
 *
 * 為什麼需要它：`vite build` 只檢查語法，元件在 render 期間拋的例外它一概不知道。
 * 而 React 預設 render 拋例外就卸載整棵樹——畫面全空、按鈕全部沒反應，
 * 從外面完全看不出原因。這支腳本讓那類錯誤在命令列就現形。
 *
 * 用法：cd Screen && node smoke.mjs [頁面名稱...]
 *       預設跑全部頁面。需要 Node.js 伺服器（:3001）在跑，才有資料可渲染。
 */
import { JSDOM } from 'jsdom'
import { createServer } from 'vite'

const PAGES = process.argv.slice(2).length ? process.argv.slice(2) : [
  'Overview', 'BudgetSearch', 'StockAnalysis', 'NewsInput', 'NewsSentiment',
  'Prediction', 'PredictionCompare', 'QueryHistory', 'VotingDashboard',
  'ModelVersions', 'Holdings', 'IdleCash',
]

const dom = new JSDOM('<!doctype html><html><head></head><body><div id="root"></div></body></html>', {
  url: 'http://localhost:5173/', pretendToBeVisual: true,
})
const { window } = dom
globalThis.window = window
globalThis.document = window.document
globalThis.navigator = window.navigator
globalThis.HTMLElement = window.HTMLElement
globalThis.Element = window.Element
globalThis.Node = window.Node
globalThis.SVGElement = window.SVGElement
globalThis.getComputedStyle = window.getComputedStyle
globalThis.requestAnimationFrame = cb => setTimeout(cb, 0)
globalThis.cancelAnimationFrame = clearTimeout
globalThis.localStorage = window.localStorage
// jsdom 沒有 IntersectionObserver / ResizeObserver，ApexCharts 與延遲載入都會用到
class FakeObserver { observe() {} unobserve() {} disconnect() {} }
globalThis.IntersectionObserver = window.IntersectionObserver = FakeObserver
globalThis.ResizeObserver = window.ResizeObserver = FakeObserver
// ApexCharts 的瀏覽器版會在載入時設 window.Apex 全域；jsdom 下要自己補
globalThis.Apex = window.Apex = {}
// jsdom 沒實作 SVG 量測，ApexCharts 會呼叫它們
if (!window.SVGElement.prototype.getBBox) {
  window.SVGElement.prototype.getBBox = () => ({ x: 0, y: 0, width: 100, height: 20 })
}
if (!window.SVGElement.prototype.getComputedTextLength) {
  window.SVGElement.prototype.getComputedTextLength = () => 50
}
if (!window.SVGElement.prototype.getScreenCTM) {
  window.SVGElement.prototype.getScreenCTM = () => ({ a: 1, b: 0, c: 0, d: 1, e: 0, f: 0,
    inverse: () => ({ a: 1, b: 0, c: 0, d: 1, e: 0, f: 0 }) })
}
window.HTMLCanvasElement.prototype.getContext = () => ({ measureText: () => ({ width: 50 }) })

// 讓 CSS 變數解析得到值（jsdom 不會套用外部樣式表）
const TOKENS = {
  '--bg': '#0f1420', '--bg2': '#161d2e', '--bg3': '#1f2839', '--border': '#2a3446',
  '--text': '#e6ebf5', '--dim': '#8e9bb3', '--blue': '#5b9dff', '--green': '#35c76a',
  '--red': '#ff5f57', '--yellow': '#f2c14e', '--purple': '#b98cff', '--orange': '#f59e5b',
}
const realGCS = window.getComputedStyle.bind(window)
globalThis.getComputedStyle = window.getComputedStyle = el => {
  const s = realGCS(el)
  return { ...s, getPropertyValue: n => TOKENS[n] ?? s.getPropertyValue(n) }
}

const errors = []
const origError = console.error
console.error = (...a) => { errors.push(a.map(String).join(' ')); origError(...a) }
window.addEventListener('error', e => errors.push('window.onerror: ' + e.message))

const server = await createServer({ server: { middlewareMode: true }, appType: 'custom' })
// react / react-dom 直接用 Node 的解析，不要走 Vite 的 SSR 轉換
// （它會把 CJS 的 react 當 ESM 執行而炸掉）
const React = (await import('react')).default
const { createRoot } = await import('react-dom/client')
const { ThemeProvider } = await server.ssrLoadModule('/src/theme.jsx')

let failed = 0
for (const name of PAGES) {
  const before = errors.length
  let mod
  try {
    mod = await server.ssrLoadModule(`/src/pages/${name}.jsx`)
  } catch (e) {
    console.log(`✗ ${name} — 載入失敗：${e.message}`); failed++; continue
  }
  const Page = mod.default
  const host = document.createElement('div')
  document.body.appendChild(host)
  try {
    const root = createRoot(host)
    root.render(React.createElement(ThemeProvider, null, React.createElement(Page)))
    await new Promise(r => setTimeout(r, 900))     // 等資料抓回來、圖表掛上
    // ApexCharts 在 jsdom 下的 SVG 量測錯誤不是我們要找的目標，濾掉；
    // 真正要抓的是「我們自己的元件」在 render 期間拋的例外
    const APEX_NOISE = /apexcharts|svg\.js|getBBox|getScreenCTM|getComputedTextLength/i
    const crashed = errors.slice(before).filter(e =>
      /Uncaught|The above error|Cannot read|is not a function|undefined is not/.test(e)
      && !APEX_NOISE.test(e))
    if (crashed.length) {
      console.log(`✗ ${name} — render 期間有錯誤：`)
      crashed.slice(0, 3).forEach(e => console.log('   ' + e.split('\n')[0].slice(0, 220)))
      failed++
    } else {
      console.log(`✓ ${name} — 掛載成功（DOM ${host.innerHTML.length} 字元）`)
    }
    root.unmount()
  } catch (e) {
    console.log(`✗ ${name} — 掛載拋出例外：${e.message}`); failed++
  }
  host.remove()
}

await server.close()
console.log(failed ? `\n${failed} 個頁面有問題` : '\n全部頁面掛載正常')
process.exit(failed ? 1 : 0)
