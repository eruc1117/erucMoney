// Iteration 89：兩個前端的使用說明是不是同一份。
// 1. PageHelp.jsx、helpContent.js 逐 byte 比對（Screen/src ↔ ../meeting_front_end/src/stock）。
// 2. 統一前端的 stock.css 是 Screen/src/index.css 經 scripts/prefix-stock-css.js 產生的：重新產生一份到暫存檔，
//    和現在那份比對（換行統一成 LF 再比——git 在 Windows 會把工作區的 LF 換成 CRLF）。
// 3. 兩個前端共用的頁面與元件檔（統一前端 src/stock/pages、components 裡 Screen 也有的那些）逐 byte 比對：
//    說明內容只有一份，前提是頁面兩邊一樣。
// 執行：node AI/experiments/iter89_fesync.mjs（在 repo 根目錄）
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..')
const SCREEN = path.join(ROOT, 'Screen', 'src')
const MFE_ROOT = path.resolve(ROOT, '..', 'meeting_front_end')
const MFE = path.join(MFE_ROOT, 'src', 'stock')

let bad = 0
for (const f of ['components/PageHelp.jsx', 'lib/helpContent.js']) {
  const a = fs.readFileSync(path.join(SCREEN, f)), b = fs.readFileSync(path.join(MFE, f))
  const same = a.equals(b)
  console.log(`${same ? 'SAME' : 'DIFF'} ${f} (${a.length} bytes vs ${b.length} bytes)`)
  if (!same) bad++
}

const tmp = path.join(os.tmpdir(), `stock-css-${process.pid}.css`)
const r = spawnSync(process.execPath, [path.join(MFE_ROOT, 'scripts', 'prefix-stock-css.js'), path.join(SCREEN, 'index.css'), tmp], { encoding: 'utf8' })
if (r.status !== 0) { console.log('prefix-stock-css.js 失敗：' + r.stderr); bad++ } else {
  const lf = p => fs.readFileSync(p, 'utf8').replace(/\r\n/g, '\n')
  const gen = lf(tmp), cur = lf(path.join(MFE, 'stock.css'))
  const same = gen === cur
  console.log(`${same ? 'SAME' : 'DIFF'} stock.css 對重新產生的那份（${cur.length} 字元；.help- 規則 ${(cur.match(/\.stock-app \.help-/g) || []).length} 處）`)
  if (!same) bad++
  fs.unlinkSync(tmp)
}
let shared = 0
const diff = []
for (const dir of ['pages', 'components']) {
  for (const f of fs.readdirSync(path.join(MFE, dir)).filter(f => f.endsWith('.jsx')).sort()) {
    const a = path.join(SCREEN, dir, f)
    if (!fs.existsSync(a) || f === 'PageHelp.jsx') continue     // 只在統一前端的（Admin*.jsx）不比；PageHelp 上面比過
    shared++
    if (!fs.readFileSync(a).equals(fs.readFileSync(path.join(MFE, dir, f)))) diff.push(`${dir}/${f}`)
  }
}
console.log(`${diff.length ? 'DIFF' : 'SAME'} 共用的頁面與元件 ${shared} 檔（pages ＋ components）${diff.length ? '：' + diff.join('、') : ''}`)
if (diff.length) bad++
process.exit(bad ? 1 : 0)
