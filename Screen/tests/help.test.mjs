// 使用說明模式（Iteration 89）：每個頁簽都要有一份說明，而且沒有對不到頁簽的孤兒說明。
// 執行：cd Screen && node --test tests/help.test.mjs
//
// 頁簽清單不另外維護一份：直接從兩個前端的導覽檔讀 key（Sidebar.jsx／App.jsx 的 PAGE_TITLES、
// 統一前端的 nav.js）。以後加頁簽忘了寫說明，這支測試會指名是哪一個。
import { test } from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { HELP, HELP_SECTIONS } from '../src/lib/helpContent.js'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const SRC = path.join(HERE, '..', 'src')
const MFE = path.join(HERE, '..', '..', '..', 'meeting_front_end', 'src', 'stock')

const keysIn = (file, re) => [...fs.readFileSync(file, 'utf8').matchAll(re)].map(m => m[1])
const sidebarKeys = keysIn(path.join(SRC, 'components', 'Sidebar.jsx'), /\{ key: '(\w+)'/g)
const titleBlock = fs.readFileSync(path.join(SRC, 'App.jsx'), 'utf8').match(/const PAGE_TITLES = \{([\s\S]*?)\n\}/)[1]
const titleKeys = [...titleBlock.matchAll(/^\s*(\w+):/gm)].map(m => m[1])
const hasMfe = fs.existsSync(path.join(MFE, 'nav.js'))
const mfeKeys = hasMfe ? keysIn(path.join(MFE, 'nav.js'), /\{ key: '(\w+)'/g) : []

test('Screen：側欄 22 個頁簽與 PAGE_TITLES 的每個 key 都有說明', () => {
  assert.equal(sidebarKeys.length, 22)
  assert.deepEqual([...sidebarKeys].sort(), [...titleKeys].sort())
  assert.deepEqual(sidebarKeys.filter(k => !HELP[k]), [])
})

test('統一前端：nav.js 分析 19 個＋管理 7 個頁簽都有說明', { skip: !hasMfe && '沒有 ../meeting_front_end' }, () => {
  assert.equal(mfeKeys.length, 26)
  assert.deepEqual(mfeKeys.filter(k => !HELP[k]), [])
})

test('沒有孤兒：每份說明都對得到某個前端的頁簽', { skip: !hasMfe && '沒有 ../meeting_front_end（管理頁的 key 只在那邊）' }, () => {
  const all = new Set([...sidebarKeys, ...mfeKeys])
  assert.deepEqual(Object.keys(HELP).filter(k => !all.has(k)), [])
})

test('每份說明四段齊全：一句用途、至少兩個步驟、至少一條怎麼看、至少一條注意；沒有空字串', () => {
  assert.deepEqual(HELP_SECTIONS.map(s => s.key), ['steps', 'read', 'notes'])
  for (const [k, h] of Object.entries(HELP)) {
    assert.ok(typeof h.what === 'string' && h.what.length >= 15, `${k}.what 太短`)
    assert.ok(h.steps.length >= 2, `${k}.steps 少於 2 條`)
    assert.ok(h.read.length >= 1, `${k}.read 是空的`)
    assert.ok(h.notes.length >= 1, `${k}.notes 是空的`)
    for (const s of HELP_SECTIONS) {
      for (const t of h[s.key]) {
        assert.ok(typeof t === 'string' && t.trim() === t && t.length >= 6, `${k}.${s.key} 有空的或頭尾帶空白的項目：「${t}」`)
        assert.ok(t.length <= 160, `${k}.${s.key} 單條超過 160 字（說明要短）：「${t.slice(0, 30)}…」`)
      }
    }
    assert.deepEqual(Object.keys(h).sort(), ['notes', 'read', 'steps', 'what'], `${k} 有多餘或缺少的欄位`)
  }
})
