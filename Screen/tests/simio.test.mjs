// 交易模擬匯入／匯出（Iteration 87）：純函式測試，node --test 跑，不用瀏覽器、不用伺服器。
// 執行：cd Screen && node --test tests/simio.test.mjs
import { test } from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { parseInstructionsCsv, parseRulesJson, parseImport, buildResultJson, buildExportFiles, zipStore, zipEntries, crc32, exportSim, instructionsFromParsed, normDate, RESULT_FORMAT } from '../src/lib/simIO.js'
import { INSTR_RESULT, FORM, ROWS, NOW } from './fixtures/sim_sample.mjs'      // 與 AI/experiments/iter87_templates.mjs 同一份樣本

const HERE = path.dirname(fileURLToPath(import.meta.url))
const TPL = path.join(HERE, '..', '..', 'AI', 'UserDoc', 'sim_templates')
const read = f => fs.readFileSync(path.join(TPL, f), 'utf8')

test('指令 CSV 範本：六列全部讀進來、註解列略過、英文與全部都認得', () => {
  const p = parseInstructionsCsv('\uFEFF' + read('sim_instructions.csv'))
  assert.equal(p.errors.length, 0)
  assert.deepEqual(p.rows.map(r => [r.date, r.side, r.stock, r.qty, r.unit]), [
    ['2024-01-15', 'buy', '2330', 10, '股'], ['2024-01-15', 'buy', '2454', 2, '張'], ['2024-02-01', 'buy', '0050', 50000, '元'],
    ['2024-06-03', 'sell', '2330', '', '全部'], ['2024-06-03', 'sell', '2454', 500, '股'], ['2024-07-01', 'sell', '0050', '', '全部']])
  assert.equal(p.rows[0].note, '零股')
  assert.equal(p.rows[2].note, '用金額，當天開盤換算成股數')
})

test('指令 CSV：壞列各自報原因、好列照收、日期排序、沒標題列也照位置讀、引號欄位', () => {
  const p = parseInstructionsCsv(['date,side,stock_id,qty,unit,note', '2024/03/01,buy,2330,1,張,"有,逗號"', '2024-02-30,買,2330,1,股,', 'x,買,2330,1,股,',
                                  '2024-01-02,hold,2330,1,股,', '2024-01-02,買,23,1,股,', '2024-01-02,買,2330,0,股,', '2024-01-02,賣,2330,100,元,', '2024-01-02,買,2330,,全部,'].join('\r\n'))
  assert.equal(p.rows.length, 1)
  assert.deepEqual(p.rows[0], { date: '2024-03-01', side: 'buy', stock: '2330', qty: 1000 / 1000, unit: '張', note: '有,逗號' })
  assert.deepEqual(p.errors.map(e => e.line), [3, 4, 5, 6, 7, 8, 9])
  assert.match(p.errors[0].reason, /日期看不懂/); assert.match(p.errors[1].reason, /日期看不懂/); assert.match(p.errors[2].reason, /買／賣/); assert.match(p.errors[3].reason, /代號/)
  assert.match(p.errors[4].reason, /數量要大於 0/); assert.match(p.errors[5].reason, /賣出請用股數/); assert.match(p.errors[6].reason, /只能用在賣出/)
  const q = parseInstructionsCsv('2024-06-03,賣,2330,,全部\n2024-01-15,買,2330,10,股')
  assert.deepEqual(q.rows.map(r => r.date), ['2024-01-15', '2024-06-03'])
  assert.equal(normDate('20240115'), '2024-01-15'); assert.equal(normDate('2024.1.5'), '2024-01-05'); assert.equal(normDate('2024-13-01'), null)
})

test('規則 JSON：範本物件（含 settings）與純陣列都收、壞的回 error', () => {
  const p = parseRulesJson(read('sim_rules.json'))
  assert.equal(p.error, undefined)
  assert.equal(p.rules.length, 3)
  assert.deepEqual(p.settings, { start: '2024-01-02', end: '2024-09-30', capital: 1000000, source: 'real', seed: 0 })
  assert.equal(p.rules[1].when.op, 'or')
  const arr = parseRulesJson(JSON.stringify([{ stock_id: ' 2330 ', when: { type: 'monthly_day', d: 5 }, then: { side: 'buy', qty: 1000, unit: '元' } }]))
  assert.equal(arr.settings, null); assert.equal(arr.rules[0].stock_id, '2330'); assert.equal(arr.rules[0].max_times, null); assert.equal(arr.rules[0].cooldown, 0)
  assert.match(parseRulesJson('{').error, /JSON/)
  assert.match(parseRulesJson('{"rules":[]}').error, /rules/)
  assert.match(parseRulesJson('{"rules":[{"stock_id":"2330","when":{},"then":{"side":"hold"}}]}').error, /第 1 條/)
})

test('parseImport：副檔名決定 CSV／JSON；結果檔（程式產生的範本）會還原設定與輸入', () => {
  assert.equal(parseImport('a.csv', read('sim_instructions.csv')).kind, 'instructions')
  assert.equal(parseImport('a.json', read('sim_rules.json')).kind, 'rules')
  const r = parseImport('sim_result.json', read('sim_result.json'))
  assert.equal(r.kind, 'result'); assert.equal(r.mode, 'instructions')
  assert.deepEqual(r.settings, { start: '2024-01-02', end: '2024-09-30', capital: 1000000, source: 'real', seed: 0 })
  assert.deepEqual(r.rows, [{ date: '2024-01-15', side: 'buy', stock: '2330', qty: 10, unit: '股', note: ROWS[0].note }, { date: '2024-06-01', side: 'sell', stock: '2330', qty: '', unit: '全部', note: '' },
                          { date: '2024-02-01', side: 'buy', stock: '0050', qty: 50000, unit: '元', note: ROWS[2].note }])     // 範本由 iter87_templates.mjs 用同一份樣本產生
  assert.match(parseImport('x.csv', '# 只有註解').error, /沒有任何指令列/)
  assert.match(parseImport('x.json', 'nope').error, /JSON/)
})


test('結果 JSON：指令模式——ref 是「第 N 列」、signal_date 用指令日、input 從 parsed 還原並帶 note、skipped 有／triggers null', () => {
  const rows = [{ note: '零股' }, { note: '' }, { note: '湊股' }]
  const res = buildResultJson({ mode: 'instructions', settings: FORM, result: INSTR_RESULT, input: { instructions: instructionsFromParsed(INSTR_RESULT.parsed, rows), rules: null }, now: NOW })
  assert.equal(res.format, RESULT_FORMAT); assert.equal(res.mode, 'instructions'); assert.match(res.generated_at, /^2026-10-19T22:30:00[+-]\d\d:\d\d$/)
  assert.deepEqual(res.settings, FORM)
  assert.deepEqual(res.input.instructions, [{ date: '2024-01-15', side: '買', stock_id: '2330', qty: 10, unit: '股', note: '零股' }, { date: '2024-06-01', side: '賣', stock_id: '2330', qty: null, unit: '全部', note: '' },
                                            { date: '2024-02-01', side: '買', stock_id: '0050', qty: 50000, unit: '元', note: '湊股' }])
  assert.deepEqual(res.trades[1], { seq: 2, ref: '第 2 列', signal_date: '2024-06-01', date: '2024-06-03', stock_id: '2330', side: 'sell', shares: 10, price: 850, gross: 8500, fee: 7.27, tax: 25.5, pnl: 2572.19, note: '部分' })
  assert.deepEqual(res.skipped, [{ ref: '第 3 列', date: '2024-02-01', stock_id: '0050', reason: '現金不夠' }]); assert.equal(res.triggers, null)
  assert.deepEqual(res.series[0], { date: '2024-01-02', nav: 1, bench: 1, cash: 1000000 })
  // 結果檔匯回去：設定與輸入都回來
  const back = parseImport('sim_result_x.json', JSON.stringify(res))
  assert.equal(back.kind, 'result'); assert.deepEqual(back.settings, FORM)
  assert.deepEqual(back.rows.map(r => [r.date, r.side, r.stock, r.qty, r.unit, r.note]), [['2024-01-15', 'buy', '2330', 10, '股', '零股'], ['2024-06-01', 'sell', '2330', '', '全部', ''], ['2024-02-01', 'buy', '0050', 50000, '元', '湊股']])
})

test('結果 JSON：規則模式——ref 是「規則 #N」、triggers 有／skipped null、input.rules 原樣', () => {
  const rules = [{ stock_id: '2330', when: { type: 'monthly_day', d: 5 }, then: { side: 'buy', qty: 1000, unit: '元' }, max_times: null, only_if_flat: false, cooldown: 0 }]
  const result = { ...INSTR_RESULT, trades: [{ rule: 0, signal_date: '2024-01-05', date: '2024-01-05', stock_id: '2330', side: 'buy', shares: 1, price: 589, gross: 589, fee: 1, tax: 0, pnl: null }],
                   triggers: [{ rule: 0, signal_date: '2024-01-05', date: '2024-01-05', result: 'filled', note: '買 1 股 @ 589', text: 't' }], skipped: undefined }
  const res = buildResultJson({ mode: 'rules', settings: FORM, result, input: { instructions: null, rules }, now: NOW })
  assert.equal(res.trades[0].ref, '規則 #1'); assert.equal(res.trades[0].signal_date, '2024-01-05'); assert.equal(res.skipped, null)
  assert.deepEqual(res.triggers, [{ ref: '規則 #1', signal_date: '2024-01-05', date: '2024-01-05', result: 'filled', note: '買 1 股 @ 589', text: 't' }])
  assert.deepEqual(res.input, { instructions: null, rules })
  const back = parseImport('r.json', JSON.stringify(res))
  assert.equal(back.mode, 'rules'); assert.deepEqual(back.rules, rules)
})

test('四個檔：檔名帶時間戳、CSV 帶 BOM 與 CRLF、欄位照規格、metrics 一列一項', () => {
  const res = buildResultJson({ mode: 'instructions', settings: FORM, result: INSTR_RESULT, input: { instructions: instructionsFromParsed(INSTR_RESULT.parsed), rules: null }, now: NOW })
  const files = buildExportFiles(res, NOW)
  assert.deepEqual(files.map(f => f.name), ['sim_result_20261019-2230.json', 'sim_trades_20261019-2230.csv', 'sim_series_20261019-2230.csv', 'sim_metrics_20261019-2230.csv'])
  const trades = files[1].text
  assert.ok(trades.startsWith('\uFEFFseq,ref,signal_date,date,stock_id,side,shares,price,gross,fee,tax,pnl,note\r\n'))
  assert.ok(trades.includes('\r\n2,第 2 列,2024-06-01,2024-06-03,2330,sell,10,850,8500,7.27,25.5,2572.19,部分\r\n'))
  assert.ok(trades.includes('\r\n1,第 1 列,2024-01-15,2024-01-15,2330,buy,10,589,5890,5.04,0,,\r\n'))
  assert.equal(files[2].text, '\uFEFFdate,nav,bench,cash\r\n2024-01-02,1,1,1000000\r\n2024-01-15,0.9999,1.012,994105\r\n2024-06-03,1.0123,1.251,1012300\r\n2024-09-30,1.0123,1.3012,1012300\r\n')   // \u4E0D\u88DC\u96F6\uFF1A1 \u5C31\u662F 1
  const metrics = files[3].text.split('\r\n')
  assert.equal(metrics[0], '\uFEFFkey,label,value'); assert.ok(metrics.includes('total_return,總報酬,0.0123')); assert.ok(metrics.includes('n_skipped,略過筆數,1')); assert.ok(!metrics.some(l => l.startsWith('n_triggers')))
  assert.equal(JSON.parse(files[0].text).format, RESULT_FORMAT)
})

test('zip：四個條目、檔名 UTF-8、大小與 CRC 對得上；寫到暫存區給 Expand-Archive 驗', () => {
  const r = exportSim({ mode: 'instructions', settings: FORM, result: INSTR_RESULT, input: { instructions: instructionsFromParsed(INSTR_RESULT.parsed), rules: null }, now: NOW, download: false })
  assert.equal(r.name, 'sim_20261019-2230.zip')
  const entries = zipEntries(r.bytes)
  assert.deepEqual(entries.map(e => e.name), r.files.map(f => f.name))
  const enc = new TextEncoder()
  r.files.forEach((f, i) => { const data = enc.encode(f.text); assert.equal(entries[i].size, data.length); assert.equal(entries[i].crc, crc32(data)) })
  assert.equal(crc32(enc.encode('123456789')), 0xCBF43926)                 // CRC-32 的標準測試向量
  const dv = new DataView(r.bytes.buffer); assert.equal(dv.getUint32(0, true), 0x04034B50)
  const out = process.env.SIMIO_ZIP_OUT
  if (out) fs.writeFileSync(out, r.bytes)
  assert.deepEqual(zipEntries(zipStore([{ name: '中文.txt', text: 'hi' }])).map(e => e.name), ['中文.txt'])
})
