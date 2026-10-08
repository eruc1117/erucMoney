// 新聞訊號頁（Iteration 47）
// ───────────────────────────────────────────────────────────────────────────
// 「新聞與股價關聯性」研究方案的落地畫面：每檔股票最新的六個可量化維度
// （意外程度、情緒、新穎度、報導強度、異常注意力、不確定性）加 MOPS 重大訊息，
// 以及三個新聞訊號模型的輸出。
//
// 模型只有通過訓練關卡（N1~N4）的才會有值；沒過的照實顯示「未通過，僅累積台帳」——
// 這不是畫面缺一塊，是方案的五道關卡在起作用。關卡數字在下方那張表。
import { useEffect, useState } from 'react'
import { getNewsSignals, getNewsSignalGates } from '../services/api'
import ModelBar from '../components/ModelBar'

function num(v, d = 2) { return v === null || v === undefined || Number.isNaN(Number(v)) ? '–' : Number(v).toFixed(d) }
function pct(v, d = 2) {
  if (v === null || v === undefined || Number.isNaN(Number(v))) return '–'
  const n = Number(v) * 100
  return `${n > 0 ? '+' : ''}${n.toFixed(d)}%`
}
function tone(v) {
  if (v === null || v === undefined || Number.isNaN(Number(v))) return 'muted'
  return Number(v) > 0 ? 'up' : Number(v) < 0 ? 'down' : 'muted'
}
function fmtDate(s) {
  if (!s) return '–'
  const d = String(s).slice(0, 10)
  return `${Number(d.slice(5, 7))}/${Number(d.slice(8, 10))}`
}

const MODEL_ORDER = [
  { key: 'news_event_vol', short: 'event_vol', label: '事件波動', unit: '次日振幅' },
  { key: 'news_drift',     short: 'drift',     label: '營收漂移', unit: '20 日方向' },
  { key: 'news_tone',      short: 'tone',      label: '新聞語調', unit: '3 日方向' },
]
const CRED_LABEL = { proven: '已驗證', weak: '邊際', none: '無 edge', unvalidated: '未驗證' }

function Sub({ children }) { return <div className="muted" style={{ fontSize: '0.72rem' }}>{children}</div> }

function DimSurprise({ d }) {
  if (d.ev_sue === null || d.ev_sue === undefined) return <span className="muted" title="這檔沒有足夠的月營收歷史算 SUE">–</span>
  const inWin = d.ev_in_window === 1
  return (
    <span title={`SUE = surprise ÷ 24 個月標準差；YoY ${pct(d.ev_yoy, 1)}；公布日 AR₀ ${pct(d.ev_rev_ar0)}`}>
      <span className={tone(d.ev_sue)}>{num(d.ev_sue, 2)}</span>
      {d.ev_yoy_extreme === 1 ? <span className="down" title="YoY 落在該股歷史前 20%：universe 研究顯示極端 YoY 之後反轉"> ⚠極端</span> : null}
      <Sub>{inWin ? `公布後第 ${num(d.ev_days_since_rev, 0)} 日` : `距公布 ${num(d.ev_days_since_rev, 0)} 日（窗口外）`}</Sub>
    </span>
  )
}

function DimSentiment({ d }) {
  if (!d.ns_has_news) return <span className="muted" title="今天沒有新聞：不是中性，是未知">無新聞</span>
  return (
    <span title={`當日 ${num(d.ns_sent)}；3 日衰減加權 ${num(d.ns_sent_3d)}；強效關鍵字淨命中 ${num(d.ns_strong_kw, 0)}`}>
      <span className={tone(d.ns_sent)}>{num(d.ns_sent)}</span>
      <Sub>3 日 {num(d.ns_sent_3d)}</Sub>
    </span>
  )
}

function DimAttention({ d }) {
  const v = d.ns_abn_attn
  const cls = v === null ? 'muted' : v >= 0.7 ? 'up' : v <= -0.7 ? 'down' : ''
  return (
    <span title="log(1+當日則數) − log(1+前 60 交易日日均則數)；正值 = 比平常多人在講">
      <span className={cls}>{v === null || v === undefined ? '–' : (v > 0 ? '+' : '') + num(v)}</span>
      <Sub>3 日 {d.ns_attn_3d === null || d.ns_attn_3d === undefined ? '–' : (d.ns_attn_3d > 0 ? '+' : '') + num(d.ns_attn_3d)}</Sub>
    </span>
  )
}

function ModelCell({ m, meta, value }) {
  if (!meta) return <span className="muted">–</span>
  if (!meta.serving) return <span className="muted" title="訓練關卡未通過（見下方關卡表）；模型仍每天寫台帳累積線上紀錄">未服役</span>
  if (!value) return <span className="muted">–</span>
  if (m.short === 'event_vol') {
    return (
      <span title={`自身 20 日中位數 ${num(value.hist_median_pct)}% 的 ${num(value.self_ratio)} 倍；同儕分位 ${num(value.peer_pct, 0)}`}>
        {num(value.range_pct)}%{value.is_elevated ? <span className="up"> ★</span> : null}
        <Sub>×{num(value.self_ratio)} 自身中位</Sub>
      </span>
    )
  }
  const cls = value.signal > 0 ? 'up' : value.signal < 0 ? 'down' : 'muted'
  return (
    <span title={`分數 ${pct(value.score)}；${value.eligible ? '在可出手的列' : '不在可出手的列（無新聞／窗口外）'}`}>
      <span className={cls}>{value.label}</span>
      <Sub>{value.eligible ? pct(value.score) : '不適用'}</Sub>
    </span>
  )
}

function GateTable({ gates }) {
  const models = gates?.models || {}
  const keys = MODEL_ORDER.filter(m => models[m.key])
  if (!keys.length) return <div className="card-body muted">尚未訓練（UnifiedModel/train_news_models.py）</div>
  const ok = v => v === true ? <span className="up">通過</span> : v === false ? <span className="down">未過</span> : <span className="muted">–</span>
  return (
    <div style={{ overflowX: 'auto' }}>
      <table className="data-table" style={{ fontSize: '0.85rem' }}>
        <thead>
          <tr>
            <th>模型</th><th style={{ textAlign: 'right' }}>樣本</th>
            <th style={{ textAlign: 'right' }}>價格控制組</th><th style={{ textAlign: 'right' }}>＋新聞</th>
            <th>N2 增量</th><th>N1 方向</th><th>N3 剔除鎖死</th><th>N4 扣成本</th><th>部署</th>
          </tr>
        </thead>
        <tbody>
          {keys.map(m => {
            const r = models[m.key]; const g = r.gates || {}
            const po = r.price_only || {}; const pn = r.price_news || {}
            const isDir = r.target_kind === 'signal'
            return (
              <tr key={m.key}>
                <td><strong>{m.label}</strong><Sub>{r.label} · {r.trained_at ? String(r.trained_at).replace('T', ' ') : ''}</Sub></td>
                <td style={{ textAlign: 'right' }}>{r.n?.toLocaleString?.() ?? r.n}</td>
                <td style={{ textAlign: 'right' }}>{num(po.rank_corr, 4)}{isDir && po.dir_acc !== null && po.dir_acc !== undefined ? <Sub>方向 {pct(po.dir_acc, 1)}</Sub> : null}</td>
                <td style={{ textAlign: 'right' }}>{num(pn.rank_corr, 4)}{isDir && pn.dir_acc !== null && pn.dir_acc !== undefined ? <Sub>方向 {pct(pn.dir_acc, 1)} 對多數 {pct(pn.majority, 1)}</Sub> : null}</td>
                <td>{ok(g.N2_pass)}<Sub>{g.N2_gain !== undefined ? `${g.N2_gain > 0 ? '+' : ''}${num(g.N2_gain, 4)}，最差折 ${num(g.N2_worst_fold, 4)}` : ''}</Sub></td>
                <td>{isDir ? ok(g.N1_pass) : <span className="muted" title="量級模型的目標本來就是 t+1">不適用</span>}{isDir && g.N1_dir_margin !== undefined ? <Sub>{pct(g.N1_dir_margin, 1)}</Sub> : null}</td>
                <td>{isDir ? ok(g.N3_pass) : <span className="muted">不適用</span>}{isDir && g.N3_dir_acc_unlocked ? <Sub>{pct(g.N3_dir_acc_unlocked, 1)}</Sub> : null}</td>
                <td>{isDir ? ok(g.N4_pass) : <span className="muted">不適用</span>}{isDir && g.N4_net_exc_ret !== undefined ? <Sub>{pct(g.N4_net_exc_ret)}</Sub> : null}</td>
                <td>{ok(g.deploy)}{!isDir && g.beats_naive !== undefined ? <Sub>贏天真基準：{g.beats_naive ? '是' : '否'}{r.baseline ? `（${num(r.baseline.rank_corr, 4)}）` : ''}</Sub> : null}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

export default function NewsSignals({ onSelectStock }) {
  const [data, setData]   = useState(null)
  const [gates, setGates] = useState(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [filter, setFilter] = useState('all')   // all | news | window | elevated

  function load() {
    setLoading(true)
    Promise.all([getNewsSignals(), getNewsSignalGates()]).then(([a, b]) => {
      if (a.error) setError(a.error)
      else { setData(a.data); setError('') }
      if (!b.error) setGates(b.data)
      setLoading(false)
    })
  }
  useEffect(() => { load() }, [])

  const rows = (data?.results || []).filter(r => {
    if (filter === 'news') return r.dims?.ns_has_news === 1
    if (filter === 'window') return r.dims?.ev_in_window === 1
    if (filter === 'elevated') return !!r.event_vol?.is_elevated
    return true
  })
  const models = data?.models || {}
  const nNews = (data?.results || []).filter(r => r.dims?.ns_has_news === 1).length
  const nElev = (data?.results || []).filter(r => r.event_vol?.is_elevated).length

  return (
    <>
      <ModelBar page="signals" />
      <div className="cards-grid">
        <div className="metric-card">
          <div className="metric-label">資料基準日</div>
          <div className="metric-value sm">{data?.as_of || '–'}</div>
          <div className="metric-delta muted">新聞依 13:30 規則歸日；只用 ≤ 基準日的新聞</div>
        </div>
        <div className="metric-card">
          <div className="metric-label">今天有新聞</div>
          <div className="metric-value sm">{data ? `${nNews} / ${data.results.length}` : '–'}</div>
          <div className="metric-delta muted">沒有新聞 ≠ 中性——那些格子是「未知」</div>
        </div>
        <div className="metric-card">
          <div className="metric-label">明日振幅偏大</div>
          <div className="metric-value sm">{models.news_event_vol?.serving ? `${nElev} 檔 ★` : '模型未服役'}</div>
          <div className="metric-delta muted">事件波動模型：≥ 自身 20 日中位數 1.3 倍</div>
        </div>
        {MODEL_ORDER.map(m => {
          const meta = models[m.key]
          return (
            <div className="metric-card" key={m.key}>
              <div className="metric-label">{m.label}</div>
              <div className="metric-value sm">{meta ? (meta.serving ? '服役中' : '未通過關卡') : '未訓練'}</div>
              <div className="metric-delta muted">{m.unit} · {meta ? `${CRED_LABEL[meta.credibility] || meta.credibility}${meta.version ? ` · v${meta.version}` : ''}` : ''}</div>
            </div>
          )
        })}
      </div>

      <div className="card">
        <div className="card-header">
          <span className="card-title">六個維度 × 三個模型（追蹤股票）</span>
          <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
            {[['all', '全部'], ['news', '今天有新聞'], ['window', '營收漂移窗口內'], ['elevated', '明日振幅偏大 ★']].map(([k, l]) => (
              <button key={k} className={`btn-chip${filter === k ? ' active' : ''}`} onClick={() => setFilter(k)}>{l}</button>
            ))}
            <button className="btn-chip" onClick={load}>重新整理</button>
          </div>
        </div>
        {loading && <div className="card-body muted">載入中…（第一次要建三年的新聞面板，約十幾秒）</div>}
        {error && <div className="card-body" style={{ color: 'var(--orange)' }}>{error}</div>}
        {!loading && !error && data && !data.available && <div className="card-body muted">{data.reason}</div>}
        {!loading && !error && data?.available && (
          <div style={{ overflowX: 'auto' }}>
            <table className="data-table">
              <thead>
                <tr>
                  <th>股票</th>
                  <th style={{ textAlign: 'right' }}>收盤</th>
                  <th style={{ textAlign: 'right' }}>意外程度 ★<Sub>營收 SUE</Sub></th>
                  <th style={{ textAlign: 'right' }}>情緒<Sub>字典 L1</Sub></th>
                  <th style={{ textAlign: 'right' }}>新穎度<Sub>對前 5 日標題</Sub></th>
                  <th style={{ textAlign: 'right' }}>報導強度<Sub>則數 / 家數</Sub></th>
                  <th style={{ textAlign: 'right' }}>異常注意力<Sub>對 60 日日均</Sub></th>
                  <th style={{ textAlign: 'right' }}>不確定性<Sub>每千字</Sub></th>
                  <th style={{ textAlign: 'right' }}>MOPS<Sub>非例行 / 注意</Sub></th>
                  {MODEL_ORDER.map(m => <th key={m.key} style={{ textAlign: 'right' }}>{m.label}<Sub>{m.unit}</Sub></th>)}
                </tr>
              </thead>
              <tbody>
                {rows.map(r => {
                  const d = r.dims || {}
                  return (
                    <tr key={r.stock_id}>
                      <td style={{ whiteSpace: 'nowrap' }}>
                        <strong>{r.stock_id}</strong>
                        <Sub>{fmtDate(r.as_of)}{onSelectStock ? <> · <button className="btn-chip" style={{ fontSize: '0.7rem', padding: '0 6px' }} onClick={() => onSelectStock(r.stock_id)}>分析</button></> : null}</Sub>
                      </td>
                      <td style={{ textAlign: 'right' }}>{num(r.close)}</td>
                      <td style={{ textAlign: 'right' }}><DimSurprise d={d} /></td>
                      <td style={{ textAlign: 'right' }}><DimSentiment d={d} /></td>
                      <td style={{ textAlign: 'right' }}>{d.ns_has_news ? <span title="1 = 標題與前 5 個新聞日完全不像；0 = 重複" className={d.ns_novelty !== null && d.ns_novelty < 0.5 ? 'down' : ''}>{num(d.ns_novelty)}</span> : <span className="muted">–</span>}</td>
                      <td style={{ textAlign: 'right' }}>{num(d.ns_n_articles, 0)}<Sub>{num(d.ns_n_sources, 0)} 家</Sub></td>
                      <td style={{ textAlign: 'right' }}><DimAttention d={d} /></td>
                      <td style={{ textAlign: 'right' }}>{d.ns_has_news ? <span title="避險／條件用語（可能、預期、傳出、不排除…）密度" className={d.ns_uncertainty !== null && d.ns_uncertainty >= 5 ? 'down' : ''}>{num(d.ns_uncertainty, 1)}</span> : <span className="muted">–</span>}</td>
                      <td style={{ textAlign: 'right' }}>
                        {d.ns_mops_nonroutine ? <span className="up" title="非例行重大訊息（庫藏股、澄清、併購、人事…）：MopsEventStudy 的波動訊號">{num(d.ns_mops_nonroutine, 0)}</span> : <span className="muted">0</span>}
                        {' / '}
                        {d.ns_mops_attention ? <span className="down" title="注意交易／處置：前一天就已放大，內生，不進模型主特徵">{num(d.ns_mops_attention, 0)}</span> : <span className="muted">0</span>}
                      </td>
                      {MODEL_ORDER.map(m => <td key={m.key} style={{ textAlign: 'right' }}><ModelCell m={m} meta={models[m.key]} value={r[m.short]} /></td>)}
                    </tr>
                  )
                })}
                {rows.length === 0 && <tr><td colSpan={12} className="muted">沒有符合篩選的股票</td></tr>}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="card">
        <div className="card-header"><span className="card-title">五道關卡（最近一次訓練）</span></div>
        <GateTable gates={gates} />
        <div className="card-body muted" style={{ fontSize: '0.8rem', lineHeight: 1.7 }}>
          N0 時間戳：新聞用 13:30 規則歸日、面板只取 ≤ 基準日的新聞（設計上不可能洩漏）。
          N2 增量：同一批列上比「12 個價量控制特徵」與「控制＋新聞／事件特徵」，新聞變體要高出 +0.01 且每一折不輸——
          否則它只是動能／成交量的代理。方向模型再看 N1（|預測| 前 20% 出手列的方向準確率高出多數類別 3 個百分點）、
          N3（剔除事件日或次日鎖漲跌停的列後仍成立）、N4（扣掉來回 0.585% 後超額報酬 &gt; 0）。
          四關全過才服役；沒過的每天照樣寫台帳，累積到 100 筆線上紀錄再看一次。
        </div>
      </div>

      <div className="card">
        <div className="card-header"><span className="card-title">怎麼讀這張表</span></div>
        <div className="card-body" style={{ lineHeight: 1.8 }}>
          <p>
            <strong>先看意外程度，再看情緒。</strong> 方案的立場是排程型新聞（月營收）優先於媒體報導：營收 surprise 是純數值、時間戳精確、
            沒有「股價漲了才有人寫」的內生性。SUE 是本月 YoY 減近三個月趨勢、再除以該股 24 個月的標準差；⚠極端 代表 YoY 在該股歷史前 20%，
            181 檔的事件研究顯示這種月份之後 20 日反而回落。
          </p>
          <p>
            <strong>異常注意力比報導強度有用。</strong> 台積電每天幾十則，絕對則數只是市值的代理；相對於自己 60 日日均的放大倍數才是訊號。
            新穎度低（標題與前幾天重複）加上情緒偏高，是 Tetlock (2011) 說的「對陳舊新聞過度反應」的候選。不確定性高代表報導裡滿是「可能、傳出、不排除」。
          </p>
          <p>
            <strong>三個模型，只有過關的才給值。</strong> 事件波動回答「明天會不會震」（次日振幅），不是方向；營收漂移只在公布後 20 日窗口內、語調只在有新聞的日子才可能出手，
            其餘棄權。未服役的模型欄位一律顯示「未服役」，關卡數字在上一張表——這比顯示一個沒驗證過的箭頭誠實。
          </p>
        </div>
      </div>
    </>
  )
}
