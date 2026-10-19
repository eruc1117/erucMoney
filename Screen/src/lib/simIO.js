// 交易模擬的匯入／匯出（Iteration 87）：純函式、不碰 DOM（只有 downloadBytes 用到 document），`node --test` 可以直接測。
// 格式規格在 AI/UserDoc/TradingSimIO.md，範本在 AI/UserDoc/sim_templates/。
//   匯入：指令 CSV（date,side,stock_id,qty,unit,note；# 列是註解）、規則 JSON（{format, settings?, rules} 或純陣列）、
//        結果 JSON（format = erucmoney-sim-result/1，會還原輸入與設定）
//   匯出：一個 zip 裝四個檔——sim_result_<時間>.json、sim_trades／sim_series／sim_metrics_<時間>.csv（CSV 帶 BOM、CRLF，Excel 直接開）
// zip 自己寫（只存不壓，STORE），不加套件：兩個前端都要同一份，而檔案本來就小。

export const RULES_FORMAT = 'erucmoney-sim-rules/1'
export const RESULT_FORMAT = 'erucmoney-sim-result/1'
const BOM = '﻿'
const SIDE = { '買': 'buy', '買進': 'buy', '買入': 'buy', buy: 'buy', b: 'buy', '賣': 'sell', '賣出': 'sell', sell: 'sell', s: 'sell' }
const UNIT = { '股': '股', share: '股', shares: '股', '張': '張', lot: '張', lots: '張', '元': '元', twd: '元', 'nt$': '元', nt: '元', '全部': '全部', all: '全部', '全賣': '全部', '清倉': '全部' }
const SETTING_KEYS = ['start', 'end', 'capital', 'source', 'seed']

// ── 小工具 ──
export function normDate(s) {
  const t = String(s || '').trim().replace(/[/.]/g, '-')
  const m = t.match(/^(\d{4})-?(\d{1,2})-?(\d{1,2})$/)
  if (!m) return null
  const [y, mo, d] = [Number(m[1]), Number(m[2]), Number(m[3])]
  const dt = new Date(Date.UTC(y, mo - 1, d))
  if (dt.getUTCFullYear() !== y || dt.getUTCMonth() !== mo - 1 || dt.getUTCDate() !== d) return null
  return `${y}-${String(mo).padStart(2, '0')}-${String(d).padStart(2, '0')}`
}

/** 一列 CSV → 欄位陣列；處理雙引號包起來的欄位與 "" 跳脫。 */
export function splitCsvLine(line) {
  const out = []; let cur = ''; let q = false
  for (let i = 0; i < line.length; i++) {
    const c = line[i]
    if (q) {
      if (c === '"') { if (line[i + 1] === '"') { cur += '"'; i++ } else q = false } else cur += c
    } else if (c === '"') q = true
    else if (c === ',') { out.push(cur); cur = '' }
    else cur += c
  }
  out.push(cur)
  return out
}

function csvCell(v) {
  const s = v == null ? '' : String(v)
  return /[",\r\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
}

/** 表頭 + 列 → CSV 文字（BOM、CRLF）。 */
export function toCsv(header, rows) {
  return BOM + [header, ...rows].map(r => r.map(csvCell).join(',')).join('\r\n') + '\r\n'
}

export function stamp(d = new Date()) {
  const p = n => String(n).padStart(2, '0')
  return `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}-${p(d.getHours())}${p(d.getMinutes())}`
}

function isoLocal(d = new Date()) {
  const p = n => String(n).padStart(2, '0')
  const off = -d.getTimezoneOffset(); const sign = off >= 0 ? '+' : '-'; const a = Math.abs(off)
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}${sign}${p(Math.floor(a / 60))}:${p(a % 60)}`
}

/** 只留合法的設定欄；一個都沒有回 null。 */
export function pickSettings(s) {
  if (!s || typeof s !== 'object') return null
  const out = {}
  if (normDate(s.start)) out.start = normDate(s.start)
  if (normDate(s.end)) out.end = normDate(s.end)
  if (Number(s.capital) > 0) out.capital = Number(s.capital)
  if (s.source === 'real' || s.source === 'synthetic') out.source = s.source
  if (Number.isInteger(Number(s.seed)) && Number(s.seed) >= 0) out.seed = Number(s.seed)
  return Object.keys(out).length ? out : null
}

// ── 匯入 ──

/** 指令 CSV → {rows:[{date, side:'buy'|'sell', stock, qty, unit, note}], errors:[{line, text, reason}]}；rows 與頁面表單模式同一種形狀。 */
export function parseInstructionsCsv(text) {
  const rows = [], errors = []
  let header = null
  const lines = String(text || '').replace(/^﻿/, '').split(/\r?\n/)
  lines.forEach((raw, i) => {
    const line = raw.trim()
    if (!line || line.startsWith('#')) return
    const cells = splitCsvLine(raw).map(c => c.trim())
    if (!header) {
      if (cells[0].toLowerCase() === 'date') { header = cells.map(c => c.toLowerCase()); return }
      header = ['date', 'side', 'stock_id', 'qty', 'unit', 'note']        // 沒有標題列就照範本的欄位順序
    }
    const get = k => { const j = header.indexOf(k); return j >= 0 ? (cells[j] ?? '') : '' }
    const bad = reason => errors.push({ line: i + 1, text: raw, reason })
    const date = normDate(get('date'))
    const side = SIDE[get('side').toLowerCase()]
    const stock = get('stock_id').toUpperCase()
    const unit = UNIT[get('unit').toLowerCase()]
    const qtyRaw = get('qty').replace(/,/g, '')
    if (!date) return bad(`日期看不懂：${get('date') || '（空）'}`)
    if (!side) return bad(`side 要是 買／賣：${get('side') || '（空）'}`)
    if (!/^[0-9A-Z]{4,6}$/.test(stock)) return bad(`股票代號看不懂：${stock || '（空）'}`)
    if (!unit) return bad(`unit 要是 股／張／元／全部：${get('unit') || '（空）'}`)
    let qty = ''
    if (unit === '全部') {
      if (side !== 'sell') return bad('「全部」只能用在賣出')
    } else {
      qty = Number(qtyRaw)
      if (!(qty > 0)) return bad(`數量要大於 0：${qtyRaw || '（空）'}`)
      if (unit === '元' && side === 'sell') return bad('賣出請用股數或「全部」')
    }
    rows.push({ date, side, stock, qty, unit, note: get('note') })
  })
  rows.sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0))
  return { rows, errors }
}

function checkRules(rules) {
  if (!Array.isArray(rules) || !rules.length) return '找不到 rules 陣列'
  for (let i = 0; i < rules.length; i++) {
    const r = rules[i]
    if (!r || typeof r !== 'object' || !r.stock_id || !r.when || typeof r.when !== 'object' || !r.then || !['buy', 'sell'].includes(r.then.side)) return `第 ${i + 1} 條規則缺 stock_id／when／then（side 要是 buy 或 sell）`
  }
  return null
}

function normRules(rules) {
  return rules.map(r => ({ ...r, stock_id: String(r.stock_id).trim().toUpperCase(), max_times: r.max_times ?? null, only_if_flat: !!r.only_if_flat, cooldown: Number(r.cooldown) || 0 }))
}

/** 規則 JSON（{format, settings?, rules} 或純陣列）→ {rules, settings} 或 {error}。 */
export function parseRulesJson(text) {
  let obj
  try { obj = typeof text === 'string' ? JSON.parse(text) : text } catch { return { error: '不是合法的 JSON' } }
  const rules = Array.isArray(obj) ? obj : obj?.rules
  const err = checkRules(rules)
  if (err) return { error: err }
  return { rules: normRules(rules), settings: Array.isArray(obj) ? null : pickSettings(obj.settings) }
}

function rowsFromResultInput(list) {
  return (list || []).map(x => ({ date: normDate(x.date) || '', side: SIDE[String(x.side).toLowerCase()] || 'buy', stock: String(x.stock_id || '').toUpperCase(),
                                 qty: x.unit === '全部' ? '' : Number(x.qty), unit: UNIT[String(x.unit).toLowerCase()] || '股', note: x.note || '' }))
}

/** 依副檔名與內容判斷匯入了什麼：{kind:'instructions', rows, errors} | {kind:'rules', rules, settings} | {kind:'result', mode, settings, rows?, rules?} | {error}。 */
export function parseImport(name, text) {
  if (/\.csv$/i.test(name || '')) {
    const p = parseInstructionsCsv(text)
    if (!p.rows.length) return { error: p.errors.length ? `CSV 每一列都看不懂（第一列：${p.errors[0].reason}）` : 'CSV 沒有任何指令列' }
    return { kind: 'instructions', ...p }
  }
  let obj
  try { obj = JSON.parse(text) } catch { return { error: '不是合法的 JSON' } }
  if (obj && obj.format === RESULT_FORMAT) {
    const settings = pickSettings(obj.settings)
    if (obj.mode === 'rules') {
      const err = checkRules(obj.input?.rules)
      return err ? { error: `結果檔的 input.rules 有問題：${err}` } : { kind: 'result', mode: 'rules', settings, rules: normRules(obj.input.rules) }
    }
    const rows = rowsFromResultInput(obj.input?.instructions).filter(r => r.date && r.stock)
    return rows.length ? { kind: 'result', mode: 'instructions', settings, rows } : { error: '結果檔的 input.instructions 是空的' }
  }
  const p = parseRulesJson(obj)
  return p.error ? p : { kind: 'rules', ...p }
}

// ── 匯出 ──

/** 指令模式：後端回的 parsed（date, side, stock_id, shares, amount, all）→ 結果檔的 input.instructions；note 從表單列（第 N 行 ↔ rows[N-1]）帶回。 */
export function instructionsFromParsed(parsed, rows = []) {
  return (parsed || []).map(it => ({ date: it.date, side: it.side === 'buy' ? '買' : '賣', stock_id: it.stock_id,
                                     qty: it.all ? null : (it.amount != null ? it.amount : it.shares), unit: it.all ? '全部' : (it.amount != null ? '元' : '股'),
                                     note: rows[it.line - 1]?.note || '' }))
}

/** 頁面結果 → 結果 JSON（規格第二節）。mode = 'instructions' | 'rules'。 */
export function buildResultJson({ mode, settings, result, input, now = new Date() }) {
  const rules = mode === 'rules'
  const ref = t => (rules ? `規則 #${t.rule + 1}` : `第 ${t.line} 列`)
  const trades = (result.trades || []).map((t, i) => ({ seq: i + 1, ref: ref(t), signal_date: rules ? t.signal_date : t.asked, date: t.date, stock_id: t.stock_id, side: t.side,
                                                       shares: t.shares, price: t.price, gross: t.gross, fee: t.fee, tax: t.tax, pnl: t.pnl ?? null, note: t.note || '' }))
  return {
    format: RESULT_FORMAT, generated_at: isoLocal(now), mode,
    settings: Object.fromEntries(SETTING_KEYS.map(k => [k, settings?.[k] ?? null])),
    source: result.source || null,
    input: { instructions: rules ? null : (input?.instructions || []), rules: rules ? (input?.rules || []) : null },
    metrics: result.metrics || {},
    trades,
    skipped: rules ? null : (result.skipped || []).map(s => ({ ref: `第 ${s.line} 列`, date: s.date, stock_id: s.stock_id, reason: s.reason })),
    triggers: rules ? (result.triggers || []).map(t => ({ ref: `規則 #${t.rule + 1}`, signal_date: t.signal_date, date: t.date, result: t.result, note: t.note || '', text: t.text })) : null,
    final: result.final, realized_pnl: result.realized_pnl, costs: result.costs,
    series: (result.series || []).map(p => ({ date: p.d, nav: p.nav, bench: p.bench, cash: p.cash })),
    caveat: result.caveat || '',
  }
}

const METRIC_ROWS = [['start', '起日'], ['end', '迄日'], ['capital', '資金'], ['total_return', '總報酬'], ['bench_return', '0050 含息報酬'], ['active_return', '主動報酬'],
                     ['ann_active', '年化主動報酬'], ['mdd_port', '最大回撤'], ['mdd_bench', '0050 最大回撤'], ['monthly_win_rate', '月勝率'],
                     ['realized_pnl', '已實現損益'], ['costs', '費用合計'], ['final_value', '期末總值'], ['n_trades', '成交筆數'], ['n_skipped', '略過筆數'], ['n_triggers', '觸發筆數']]

/** 結果 JSON → 四個檔 [{name, text}]。 */
export function buildExportFiles(res, now = new Date()) {
  const s = stamp(now)
  const m = res.metrics || {}
  const flat = { start: res.settings?.start ?? m.start, end: res.settings?.end ?? m.end, capital: res.settings?.capital, total_return: m.total_return, bench_return: m.bench_return,
                 active_return: m.active_return, ann_active: m.ann_active, mdd_port: m.mdd_port, mdd_bench: m.mdd_bench, monthly_win_rate: m.monthly_win_rate,
                 realized_pnl: res.realized_pnl, costs: res.costs, final_value: res.final?.value, n_trades: res.trades.length,
                 n_skipped: res.skipped ? res.skipped.length : null, n_triggers: res.triggers ? res.triggers.length : null }
  return [
    { name: `sim_result_${s}.json`, text: JSON.stringify(res, null, 2) },
    { name: `sim_trades_${s}.csv`, text: toCsv(['seq', 'ref', 'signal_date', 'date', 'stock_id', 'side', 'shares', 'price', 'gross', 'fee', 'tax', 'pnl', 'note'],
                                              res.trades.map(t => [t.seq, t.ref, t.signal_date, t.date, t.stock_id, t.side, t.shares, t.price, t.gross, t.fee, t.tax, t.pnl, t.note])) },
    { name: `sim_series_${s}.csv`, text: toCsv(['date', 'nav', 'bench', 'cash'], res.series.map(p => [p.date, p.nav, p.bench, p.cash])) },
    { name: `sim_metrics_${s}.csv`, text: toCsv(['key', 'label', 'value'], METRIC_ROWS.filter(([k]) => flat[k] != null).map(([k, label]) => [k, label, flat[k]])) },
  ]
}

// ── zip（STORE，不壓縮）──
const CRC_TABLE = (() => {
  const t = new Uint32Array(256)
  for (let n = 0; n < 256; n++) { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xEDB88320 ^ (c >>> 1) : c >>> 1; t[n] = c >>> 0 }
  return t
})()
export function crc32(bytes) {
  let c = 0xFFFFFFFF
  for (let i = 0; i < bytes.length; i++) c = CRC_TABLE[(c ^ bytes[i]) & 0xFF] ^ (c >>> 8)
  return (c ^ 0xFFFFFFFF) >>> 0
}
function dosTime(d) { return ((d.getHours() << 11) | (d.getMinutes() << 5) | (d.getSeconds() >> 1)) & 0xFFFF }
function dosDate(d) { return (((d.getFullYear() - 1980) << 9) | ((d.getMonth() + 1) << 5) | d.getDate()) & 0xFFFF }

/** files: [{name, text}] 或 [{name, data: Uint8Array}] → zip 的 Uint8Array（檔名 UTF-8、flag bit 11）。 */
export function zipStore(files, now = new Date()) {
  const enc = new TextEncoder()
  const parts = [], central = []
  let offset = 0
  const u16 = (v) => [v & 0xFF, (v >>> 8) & 0xFF]
  const u32 = (v) => [v & 0xFF, (v >>> 8) & 0xFF, (v >>> 16) & 0xFF, (v >>> 24) & 0xFF]
  for (const f of files) {
    const name = enc.encode(f.name)
    const data = f.data instanceof Uint8Array ? f.data : enc.encode(f.text ?? '')
    const crc = crc32(data), t = dosTime(now), dt = dosDate(now)
    const local = new Uint8Array([...u32(0x04034B50), ...u16(20), ...u16(0x0800), ...u16(0), ...u16(t), ...u16(dt), ...u32(crc), ...u32(data.length), ...u32(data.length), ...u16(name.length), ...u16(0), ...name])
    central.push(new Uint8Array([...u32(0x02014B50), ...u16(20), ...u16(20), ...u16(0x0800), ...u16(0), ...u16(t), ...u16(dt), ...u32(crc), ...u32(data.length), ...u32(data.length),
                                 ...u16(name.length), ...u16(0), ...u16(0), ...u16(0), ...u16(0), ...u32(0), ...u32(offset), ...name]))
    parts.push(local, data)
    offset += local.length + data.length
  }
  const cdSize = central.reduce((n, c) => n + c.length, 0)
  const eocd = new Uint8Array([...u32(0x06054B50), ...u16(0), ...u16(0), ...u16(files.length), ...u16(files.length), ...u32(cdSize), ...u32(offset), ...u16(0)])
  const all = [...parts, ...central, eocd]
  const out = new Uint8Array(all.reduce((n, p) => n + p.length, 0))
  let pos = 0
  for (const p of all) { out.set(p, pos); pos += p.length }
  return out
}

/** 讀 zip 的中央目錄（給測試用）：[{name, size, crc}]。 */
export function zipEntries(bytes) {
  const dv = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength)
  const eocd = bytes.length - 22
  if (dv.getUint32(eocd, true) !== 0x06054B50) throw new Error('不是 zip（EOCD 找不到）')
  const count = dv.getUint16(eocd + 10, true); let p = dv.getUint32(eocd + 16, true)
  const dec = new TextDecoder(); const out = []
  for (let i = 0; i < count; i++) {
    if (dv.getUint32(p, true) !== 0x02014B50) throw new Error('中央目錄壞掉')
    const crc = dv.getUint32(p + 16, true), size = dv.getUint32(p + 24, true), n = dv.getUint16(p + 28, true), off = dv.getUint32(p + 42, true)
    out.push({ name: dec.decode(bytes.subarray(p + 46, p + 46 + n)), size, crc, offset: off })
    p += 46 + n
  }
  return out
}

/** 瀏覽器：把 bytes 存成檔案。 */
export function downloadBytes(name, bytes, type = 'application/zip') {
  const url = URL.createObjectURL(new Blob([bytes], { type }))
  const a = document.createElement('a'); a.href = url; a.download = name; document.body.appendChild(a); a.click(); a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

/** 頁面用：組結果 JSON → 四個檔 → zip → 下載。回 {name, files, bytes} 方便測試。 */
export function exportSim({ mode, settings, result, input, now = new Date(), download = true }) {
  const res = buildResultJson({ mode, settings, result, input, now })
  const files = buildExportFiles(res, now)
  const bytes = zipStore(files, now)
  const name = `sim_${stamp(now)}.zip`
  if (download) downloadBytes(name, bytes)
  return { name, files, bytes }
}
