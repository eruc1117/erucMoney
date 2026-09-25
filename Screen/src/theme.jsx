// 主題與字級（Iteration 25）
//
// 兩件事都存在 localStorage，並直接寫到 <html> 的 data 屬性上，
// 由 CSS 變數承接：`html[data-theme]` 換色、`html[data-size]` 換根字級。
//
// **為什麼字級用 rem 而不是 px。** 字級切換若要真的有效，所有尺寸都必須
// 相對於根字級。CSS 裡好處理，但這個專案有大量寫在 JSX 裡的行內字級，
// 那些 px 值不會跟著縮放——所以行內字級一併換算成 rem。
// 這是換風格時最花工夫、也最不能省的一步：切了沒反應的設定比沒有更糟。

import { createContext, useContext, useEffect, useState } from 'react'

const THEME_KEY = 'ui.theme'   // 'dark' | 'light'
const SIZE_KEY = 'ui.size'     // 'sm' | 'md' | 'lg'

const ThemeCtx = createContext(null)

function read(key, fallback, valid) {
  try {
    const v = localStorage.getItem(key)
    return valid.includes(v) ? v : fallback
  } catch {
    return fallback           // 隱私模式下 localStorage 可能拋例外
  }
}

export function ThemeProvider({ children }) {
  const [theme, setTheme] = useState(() => read(THEME_KEY, 'dark', ['dark', 'light']))
  const [size, setSize] = useState(() => read(SIZE_KEY, 'md', ['sm', 'md', 'lg']))

  useEffect(() => {
    document.documentElement.dataset.theme = theme
    try { localStorage.setItem(THEME_KEY, theme) } catch { /* 忽略 */ }
  }, [theme])

  useEffect(() => {
    document.documentElement.dataset.size = size
    try { localStorage.setItem(SIZE_KEY, size) } catch { /* 忽略 */ }
  }, [size])

  return (
    <ThemeCtx.Provider value={{
      theme, size,
      toggleTheme: () => setTheme(t => (t === 'dark' ? 'light' : 'dark')),
      setTheme, setSize,
      dark: theme === 'dark',
    }}>
      {children}
    </ThemeCtx.Provider>
  )
}

export function useTheme() {
  const ctx = useContext(ThemeCtx)
  // 沒包 Provider 時給一個可用的預設，避免元件在測試或局部渲染時整個掛掉
  return ctx ?? { theme: 'dark', size: 'md', dark: true,
                  toggleTheme: () => {}, setTheme: () => {}, setSize: () => {} }
}

// ── 圖表主題 ──────────────────────────────────────────────────────────────────
// ApexCharts 不能直接吃 CSS 變數：它會對系列顏色做運算（漸層、標記、
// tooltip 色塊都是從基色推算出來的），拿到 `var(--blue)` 這種字串會算出 NaN。
//
// 所以這裡把 CSS 變數**解析成實際色值**再交給圖表。好處是色票只有一份
// （index.css 的 token），不必在 JS 裡再維護一份對照表——
// 那種兩份色票的做法遲早會有一邊忘了改。
export function cssColor(value) {
  if (typeof value !== 'string') return value
  const m = value.match(/^var\((--[\w-]+)\)$/)
  if (!m) return value
  const v = getComputedStyle(document.documentElement).getPropertyValue(m[1]).trim()
  return v || value
}

export const cssColors = arr => (Array.isArray(arr) ? arr.map(cssColor) : cssColor(arr))

/**
 * 圖表字級：**必須給 px，不能給 rem。**
 *
 * ApexCharts 內部會用 parseInt(fontSize) 去算文字寬度，
 * `parseInt('0.8125rem')` 的結果是 0——於是圖例只剩色點、文字寬度變成零。
 * 實際踩過一次，而且畫面上不會有任何錯誤訊息。
 *
 * 這裡從根字級換算成 px，字級切換（小／中／大）仍然有效。
 */
export function chartPx(rem) {
  const base = parseFloat(getComputedStyle(document.documentElement).fontSize) || 16
  return `${Math.round(rem * base)}px`
}

export function chartPalette() {
  return {
    grid: cssColor('var(--border)'), axis: cssColor('var(--dim)'),
    text: cssColor('var(--text)'),
    blue: cssColor('var(--blue)'), green: cssColor('var(--green)'),
    red: cssColor('var(--red)'), yellow: cssColor('var(--yellow)'),
    purple: cssColor('var(--purple)'), orange: cssColor('var(--orange)'),
  }
}

/**
 * 所有圖表共用的底層設定。頁面在 render 時呼叫，
 * 主題一變、Provider 觸發重繪，圖表就會拿到新的一份。
 */
export function chartBase(theme) {
  const p = chartPalette()
  return {
    theme: { mode: theme === 'light' ? 'light' : 'dark' },
    chart: { background: 'transparent', toolbar: { show: false },
             fontFamily: 'inherit' },
    grid: { borderColor: p.grid, strokeDashArray: 3 },
    tooltip: { theme: theme === 'light' ? 'light' : 'dark' },
    xaxis: { labels: { style: { colors: p.axis, fontSize: chartPx(0.75) } },
             axisBorder: { color: p.grid }, axisTicks: { color: p.grid } },
    yaxis: { labels: { style: { colors: p.axis, fontSize: chartPx(0.75) } } },
    legend: { labels: { colors: p.axis }, fontSize: chartPx(0.8125) },
  }
}
