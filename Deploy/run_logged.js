// 常駐工作的外殼：視窗標題 = 工作名稱，子程序的 stdout/stderr 同時印在視窗、附加寫進 log 檔。
//   node run_logged.js <工作名稱> <log 檔> <執行檔> [參數...]
// 工作排程器的四個工作（MoneyApi、MoneyCalendarApi、MoneyCrawlerApi、MoneyLstm）都經過這裡啟動。
// 關掉視窗 = 關掉該服務（工作排程器兩分鐘後會嘗試重啟）。
'use strict';
const fs = require('fs');
const path = require('path');
const { spawn } = require('child_process');

const [, , name, logPath, exe, ...args] = process.argv;
if (!name || !logPath || !exe) {
  console.error('用法：node run_logged.js <工作名稱> <log 檔> <執行檔> [參數...]');
  process.exit(2);
}

process.title = name;                       // Windows 主控台視窗標題
fs.mkdirSync(path.dirname(logPath), { recursive: true });
const out = fs.createWriteStream(logPath, { flags: 'a' });
const stamp = () => { const d = new Date(); return new Date(d - d.getTimezoneOffset() * 60000).toISOString().replace('T', ' ').slice(0, 19); }; // 本地時間
const both = (s) => { process.stdout.write(s); out.write(s); };

both(`\n[${stamp()}] [${name}] 啟動：${exe} ${args.join(' ')}（cwd ${process.cwd()}）\n`);
both(`[${stamp()}] [${name}] log：${logPath}\n`);

const child = spawn(exe, args, {
  stdio: ['ignore', 'pipe', 'pipe'],
  env: { ...process.env, PYTHONUTF8: '1', PYTHONIOENCODING: 'utf-8', PYTHONUNBUFFERED: '1', FORCE_COLOR: '0' },
});
child.stdout.on('data', (d) => { process.stdout.write(d); out.write(d); });
child.stderr.on('data', (d) => { process.stderr.write(d); out.write(d); });
child.on('error', (e) => { both(`[${stamp()}] [${name}] 啟動失敗：${e.message}\n`); out.end(() => process.exit(1)); });
child.on('exit', (code, signal) => {
  both(`[${stamp()}] [${name}] 結束：code=${code} signal=${signal}\n`);
  out.end(() => process.exit(code == null ? 1 : code));
});
for (const sig of ['SIGINT', 'SIGTERM', 'SIGHUP', 'SIGBREAK']) {
  process.on(sig, () => { try { child.kill(); } catch (_) {} });
}
