#!/usr/bin/env node
/**
 * 工作進度的獨立畫面（本機、不用登入；資料與 /progress、網頁版同一來源 progress_data.js）
 *
 *   node AI/harness/progress_ui.js            # http://localhost:3010，每 5 秒自動更新；啟動時自動開瀏覽器視窗
 *   node AI/harness/progress_ui.js --port 3011 --no-open
 *
 * 顯示：任務／下一步、階段、**目前負責的代理人**（24 小時內每個 Claude session：進行中或閒置、最近一句指令、
 * 派出的子代理與是否還在跑）、驗證結果、最近迭代與提交、未解、事件流。只讀 repo 檔案與 git，不改任何東西。
 */
'use strict'
const http = require('http')
const { spawn } = require('child_process')
const { collect, ROOT } = require('./progress_data')

const args = process.argv.slice(2)
const PORT = Number(args.includes('--port') ? args[args.indexOf('--port') + 1] : process.env.PROGRESS_UI_PORT || 3010)
const OPEN = !args.includes('--no-open')

const HTML = `<!doctype html>
<html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Claude 工作進度</title>
<style>
:root{--bg:#0f1115;--card:#171a21;--line:#262b36;--text:#e6e8ee;--muted:#8b93a7;--ok:#3ecf8e;--warn:#f5a524;--bad:#ff5c5c;--acc:#6c8cff}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:14px/1.5 system-ui,-apple-system,"Segoe UI","Noto Sans TC",sans-serif}
header{display:flex;justify-content:space-between;align-items:center;padding:14px 20px;border-bottom:1px solid var(--line);position:sticky;top:0;background:var(--bg)}
h1{font-size:16px;margin:0}h2{font-size:13px;margin:0 0 10px;color:var(--muted);letter-spacing:.04em;text-transform:uppercase}
main{display:grid;grid-template-columns:repeat(auto-fit,minmax(380px,1fr));gap:14px;padding:16px 20px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px}
.wide{grid-column:1/-1}.muted{color:var(--muted)}.ok{color:var(--ok)}.bad{color:var(--bad)}.warn{color:var(--warn)}
.pill{display:inline-block;padding:1px 8px;border-radius:999px;font-size:12px;border:1px solid var(--line);margin-left:6px}
.pill.working{background:rgba(62,207,142,.12);color:var(--ok);border-color:rgba(62,207,142,.4)}.pill.idle{color:var(--muted)}
.agent{display:flex;gap:8px;align-items:baseline;padding:6px 0;border-top:1px dashed var(--line)}
.agent .type{font-weight:600;min-width:150px}.dot{display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--muted);margin-right:6px}
.dot.on{background:var(--ok);box-shadow:0 0 0 3px rgba(62,207,142,.2);animation:p 1.4s infinite}@keyframes p{50%{opacity:.4}}
.stage{display:flex;gap:10px;align-items:center;padding:4px 0}.stage .box{width:14px;height:14px;border-radius:3px;border:1px solid var(--line)}
.stage.done .box{background:var(--ok);border-color:var(--ok)}.stage.active .box{background:var(--warn);border-color:var(--warn)}
table{width:100%;border-collapse:collapse;font-size:13px}td,th{padding:4px 6px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}th{color:var(--muted);font-weight:500}
.ev{font-family:ui-monospace,Consolas,monospace;font-size:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.task{font-size:15px}.next{padding:8px 10px;border-left:3px solid var(--acc);background:rgba(108,140,255,.08);border-radius:4px}
ul{margin:0;padding-left:18px}li{margin:2px 0}.sid{font-family:ui-monospace,Consolas,monospace}
</style></head><body>
<header><h1>Claude 工作進度 <span class="muted" id="root"></span></h1><div class="muted"><span id="when"></span> · 每 5 秒更新 · <span id="dirty"></span></div></header>
<main id="main"><div class="card wide muted">載入中…</div></main>
<script>
const esc=s=>String(s??'').replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]))
const t=iso=>{if(!iso)return'';const d=new Date(iso);return d.toLocaleString('zh-TW',{hour12:false,month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'})}
const ago=iso=>{const m=Math.round((Date.now()-new Date(iso))/60000);return m<1?'剛剛':m<60?m+' 分鐘前':m<1440?Math.round(m/60)+' 小時前':Math.round(m/1440)+' 天前'}
function render(d){
  document.getElementById('root').textContent=d.root
  document.getElementById('when').textContent='更新 '+t(d.now)+'（筆記 '+(d.updated||'?')+'）'
  document.getElementById('dirty').textContent=d.dirty_files?('工作區 '+d.dirty_files+' 個檔案未提交'):'工作區乾淨'
  const s=d.sections||{}
  const sessions=d.sessions.map(x=>{
    const run=x.running_agents.map(a=>'<div class="agent"><span class="dot on"></span><span class="type">'+esc(a.type)+'</span><span>'+esc(a.description)+'</span><span class="muted">'+ago(a.started)+'起</span></div>').join('')
    const done=x.done_agents.map(a=>'<div class="agent muted"><span class="dot"></span><span class="type">'+esc(a.type)+'</span><span>'+esc(a.description)+'</span><span>完成 '+t(a.stopped)+'</span></div>').join('')
    return '<div class="card"><h2>代理人 · session <span class="sid">'+esc(x.id)+'</span><span class="pill '+x.state+'">'+(x.state==='working'?'進行中':'閒置')+'</span></h2>'
      +'<div class="task">'+(x.task?esc(x.task.text):'<span class="muted">（還沒有指令）</span>')+'</div>'
      +'<div class="muted">最近指令 '+(x.task?t(x.task.ts):'–')+' · 最後活動 '+ago(x.last)+' · 工具呼叫 '+x.tools+' 次'+(x.failures?' · <span class="bad">失敗 '+x.failures+'</span>':'')+(x.lastTool?' · 最近 '+esc(x.lastTool):'')+'</div>'
      +(run?'<div style="margin-top:8px"><b>正在跑的子代理</b>'+run+'</div>':'')+(done?'<div style="margin-top:8px" class="muted"><b>最近完成的子代理</b>'+done+'</div>':'')+'</div>'
  }).join('')||'<div class="card muted">24 小時內沒有 session 活動</div>'
  const stages=(d.stages||[]).map(x=>'<div class="stage '+x.state+'"><span class="box"></span><span>'+esc(x.text)+'</span></div>').join('')
  const checks=d.checks.map(c=>'<tr><td class="'+(c.status==='pass'?'ok':'bad')+'">'+(c.status==='pass'?'✔':'✘')+'</td><td>'+esc(c.name)+'</td><td class="muted">'+t(c.at)+'</td><td>'+esc((c.summary||'').slice(0,90))+'</td></tr>').join('')
  const iters=d.iterations.map(i=>'<li><b>Iteration '+i.n+'</b>'+(i.date?' <span class="muted">'+i.date+'</span>':'')+'：'+esc(i.title)+'</li>').join('')
  const commits=d.commits.map(c=>'<li><span class="sid">'+c.hash+'</span> <span class="muted">'+t(c.date)+'</span> '+esc(c.subject.slice(0,110))+'</li>').join('')
  const open=(s['未解']||[]).map(l=>'<li>'+esc(l.replace(/^-\\s*/,''))+'</li>').join('')
  const events=d.events.map(e=>'<div class="ev"><span class="muted">'+t(e.ts)+'</span> <span class="sid">'+esc(e.session||'')+'</span> '+esc(e.event)+' '+esc(e.tool||'')+' '+esc((e.summary||'').slice(0,80))+(e.ok===false?' <span class="bad">✘</span>':'')+'</div>').join('')
  document.getElementById('main').innerHTML=
    '<div class="card wide"><h2>任務</h2><div class="task">'+esc((s['任務']||[]).join(' '))+'</div><h2 style="margin-top:12px">下一步</h2><div class="next">'+esc((s['下一步']||[]).join(' '))+'</div></div>'
    +sessions
    +'<div class="card"><h2>階段</h2>'+stages+'</div>'
    +'<div class="card"><h2>驗證結果 checks.json</h2><table><tbody>'+checks+'</tbody></table></div>'
    +'<div class="card"><h2>最近迭代</h2><ul>'+iters+'</ul><h2 style="margin-top:12px">最近提交</h2><ul>'+commits+'</ul></div>'
    +'<div class="card"><h2>未解</h2><ul>'+open+'</ul></div>'
    +'<div class="card wide"><h2>事件流（最新在上）</h2>'+events+'</div>'
}
async function tick(){try{const r=await fetch('/data?events=40',{cache:'no-store'});render(await r.json())}catch(e){document.getElementById('when').textContent='連不上：'+e.message}}
tick();setInterval(tick,5000)
</script></body></html>`

const server = http.createServer((req, res) => {
  const url = new URL(req.url, 'http://x')
  if (url.pathname === '/data') {
    try {
      const n = Number(url.searchParams.get('events') || 30)
      res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' })
      res.end(JSON.stringify(collect({ events: n })))
    } catch (e) {
      res.writeHead(500, { 'Content-Type': 'application/json; charset=utf-8' }); res.end(JSON.stringify({ error: e.message }))
    }
    return
  }
  res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' }); res.end(HTML)
})

server.listen(PORT, '127.0.0.1', () => {
  const url = `http://localhost:${PORT}/`
  console.log(`Claude 工作進度畫面：${url}（repo ${ROOT}；Ctrl+C 停止）`)
  if (OPEN) {
    try {
      if (process.platform === 'win32') spawn('cmd', ['/c', 'start', '', url], { detached: true, stdio: 'ignore' }).unref()
      else spawn(process.platform === 'darwin' ? 'open' : 'xdg-open', [url], { detached: true, stdio: 'ignore' }).unref()
    } catch { /* 開不了瀏覽器就自己開網址 */ }
  }
})
