// Iteration 87：用 Screen/src/lib/simIO.js 對 tests 的共用樣本實際跑一次匯出，把四個匯出範本寫進 AI/UserDoc/sim_templates/
// （sim_result.json、sim_trades.csv、sim_series.csv、sim_metrics.csv），所以範本就是程式輸出，不另外手寫。
// 執行：node AI/experiments/iter87_templates.mjs（經 record_check.js --name templates-gen-87）
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { exportSim, instructionsFromParsed } from '../../Screen/src/lib/simIO.js'
import { INSTR_RESULT, FORM, ROWS, NOW } from '../../Screen/tests/fixtures/sim_sample.mjs'

const OUT = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', 'UserDoc', 'sim_templates')
const { files } = exportSim({ mode: 'instructions', settings: FORM, result: INSTR_RESULT, input: { instructions: instructionsFromParsed(INSTR_RESULT.parsed, ROWS), rules: null }, now: NOW, download: false })
for (const f of files) {
  const name = f.name.replace(/_\d{8}-\d{4}/, '')          // 範本檔名不帶時間戳
  fs.writeFileSync(path.join(OUT, name), f.text, 'utf8')
  console.log(name, Buffer.byteLength(f.text, 'utf8'), 'bytes')
}
