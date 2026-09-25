// 預測比對頁面 — 列出所有已儲存預測，到期後與實際收盤價比對
//
// 這一版是重做的，前一版有兩個問題：
//
// 1. **整頁會被單一元件的例外拖垮。** React 預設 render 拋例外就卸載整棵樹，
//    所以一張圖表設定寫錯，整頁變空白、按鈕全部沒反應，畫面上還看不出原因。
//    現在每張圖表都包在 ErrorBoundary 裡，壞掉的只有那一塊。
// 2. **靠 IntersectionObserver 延後載入太脆弱。** 只要觀察沒觸發，卡片就永遠
//    停在「載入中」。改用分頁：每頁固定幾筆，同時存在的圖表數量有上限，
//    行為完全可預期，不依賴捲動事件。
//
// 版面原則：
//   · 圖表與指標**預設就顯示**——這一頁的重點就是「預測畫得準不準」，
//     要點開才看得到圖等於把主要內容藏起來。摺疊只留給逐日明細。
//   · 卡片標題分兩行，避免七八個標籤擠成一團。
//   · 數值欄一律右對齊，小數點對齊才看得出大小。
//
// 內容原則（Iteration 21 建立，未變）：
//   · 每個指標旁邊都放天真基準，贏了才標綠。只看 MAE／MAPE 測不出模型好壞——
//     Iteration 11 實測 LSTM 的 MAE 5.17~5.25，而天真基準是 5.20。
//   · 方向側的基準是多數類別（一律猜漲能拿幾分），不是「明日＝今日」。
//   · 實際值以 adj_close 換算到預測基準日的價格尺度，除權息與減資不進誤差。
//
// 市場切換（台股／美股）：同一張表、同一套比對邏輯，差別只在後端去哪張價格表
// 取實際值、彙總時不把台幣與美元的 MAE 混在一列，以及資料新鮮度看哪張表。

import { useEffect, useState } from 'react'
import ReactApexChart from 'react-apexcharts'
import {
  getSavedPredictions, deleteSavedPrediction,
  getPredictionCompare, getPredictionSummary,
  getDataFreshness, backfillData,
  getExogenousFreshness, backfillExogenous,
} from '../services/api'
import { chartBase, cssColors, chartPx, useTheme } from '../theme'
import ErrorBoundary from '../components/ErrorBoundary'
import ModelBar from '../components/ModelBar'

const PAGE_SIZE = 6      // 每頁筆數＝同時存在的圖表數上限

const MARKETS = [
  { key: 'tw', label: '台股', unit: '元' },
  { key: 'us', label: '美股', unit: '美元' },
]
const unitOf = (market) => (market === 'us' ? '美元' : '元')

const pct = (v, sign = false) =>
  (v == null ? '–' : `${sign && v > 0 ? '+' : ''}${v}%`)

// ── 小元件 ────────────────────────────────────────────────────────────────────
function StatTile({ label, value, sub, color, title }) {
  return (
    <div className="stat-tile" title={title}>
      <div className="k">{label}</div>
      <div className="v" style={{ color: color ?? 'var(--text-strong)' }}>{value}</div>
      {sub && <div className="s">{sub}</div>}
    </div>
  )
}

function MiniBar({ done, total }) {
  const p = total > 0 ? Math.round((done / total) * 100) : 0
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: '.4rem' }}>
      <span className="mini-bar"><i style={{ width: `${p}%` }} /></span>
      <span>{done}/{total} 天已可比對</span>
    </span>
  )
}

// ── 比對圖 ────────────────────────────────────────────────────────────────────
// 信賴區間用 rangeArea 畫成**一條帶狀**，而不是上下界兩條各自從座標軸往上填的 area。
// 後者疊在一起看不出區間在哪，圖例上有「95% 上界／下界」卻什麼也看不到——
// 那正是改版前的樣子。rangeArea 一個系列就是一段區間，語意與畫面都對得上。
function CompareChart({ rows }) {
  const actual = rows.map(r => r.actual_close)
  const hasActual = actual.some(v => v != null)
  const xy = (get) => rows.map(r => ({ x: r.date, y: get(r) }))
  const hasCI = rows.some(r => r.ci_low != null && r.ci_high != null)

  const series = [
    ...(hasCI ? [{
      name: '95% 信賴區間', type: 'rangeArea',
      data: rows.map(r => ({ x: r.date, y: [r.ci_low, r.ci_high] })),
    }] : []),
    { name: '預測收盤', type: 'line', data: xy(r => r.predicted_close) },
    { name: '天真基準', type: 'line', data: xy(r => r.baseline_close) },
    ...(hasActual ? [{ name: '實際收盤', type: 'line', data: xy(r => r.actual_close) }] : []),
  ]

  // 每個系列一組樣式，順序必須與 series 一致
  const colors = []
  const width = []
  const dash = []
  if (hasCI) { colors.push('var(--blue)'); width.push(0); dash.push(0) }
  colors.push('var(--blue)'); width.push(2.5); dash.push(5)     // 預測
  colors.push('var(--dim)'); width.push(1.5); dash.push(3)      // 天真基準
  if (hasActual) { colors.push('var(--green)'); width.push(2.5); dash.push(0) }

  // Y 軸範圍取所有系列的極值再留 4% 邊界
  const all = rows.flatMap(r => [r.ci_low, r.ci_high, r.predicted_close,
                                 r.baseline_close, r.actual_close])
                  .filter(v => v != null).map(Number)
  const span = all.length ? Math.max(...all) - Math.min(...all) : 0
  const pad = Math.max(span * 0.04, 1)
  // 取整到 10 的倍數，刻度才不會出現 2537 / 2446 這種讀不出意義的數字；
  // 但價格區間本身不到 15 時（美股 UMC 約 8 美元、台股低價股），取 10 會把
  // 整條線壓成一條水平線，改取 1
  const step = span < 15 ? 1 : 10
  const round = (v, dir) => (dir < 0 ? Math.floor(v / step) : Math.ceil(v / step)) * step
  const lo = all.length ? round(Math.min(...all) - pad, -1) : undefined
  const hi = all.length ? round(Math.max(...all) + pad, 1) : undefined

  const b = chartBase(document.documentElement.dataset.theme)

  return (
    <div className="chart-pad" style={{ paddingTop: '.8rem' }}>
      <ReactApexChart
        type={hasCI ? 'rangeArea' : 'line'}
        height={260}
        series={series}
        options={{
          ...b,
          chart: { ...b.chart, type: hasCI ? 'rangeArea' : 'line',
                   animations: { enabled: false } },
          xaxis: { ...b.xaxis, type: 'category',
                   labels: { ...b.xaxis.labels, rotate: -30 },
                   tickAmount: Math.min(rows.length, 8) },
          // rangeArea 會把 Y 軸下限拉到 0，所有線擠成一條——必須自己給範圍。
          // 股價圖看的是幾十元的差距，從 0 起算等於什麼都看不出來。
          yaxis: {
            ...b.yaxis, min: lo, max: hi, tickAmount: 5, forceNiceScale: true,
            labels: { ...b.yaxis.labels,
                      formatter: v => (v == null ? '' : Number(v).toFixed(0)) },
          },
          // Apex 會拿系列色去算漸層與標記，吃不了 CSS 變數字串，
          // 必須先解析成實際色值（見 theme.jsx 的 cssColors）
          colors: cssColors(colors),
          stroke: { curve: 'smooth', width, dashArray: dash },
          fill: { type: 'solid', opacity: hasCI ? [0.16, 1, 1, 1].slice(0, series.length)
                                               : 1 },
          markers: { size: 0 },
          dataLabels: { enabled: false },
          legend: { ...b.legend, position: 'top', horizontalAlign: 'left' },
          tooltip: { ...b.tooltip, shared: true, intersect: false },
        }}
      />
    </div>
  )
}

// ── 逐日明細 ──────────────────────────────────────────────────────────────────
function DetailTable({ rows }) {
  return (
    <div className="table-wrap">
      <table className="data-table">
        <thead>
          <tr>
            <th title="第 i 筆預測對應基準日之後第 i 個真實交易日；存檔時推估的日期遇休市會往後順延">日期</th>
            <th className="num">預測收盤</th>
            <th className="num">實際收盤</th>
            <th className="num">誤差</th>
            <th className="num">誤差 %</th>
            <th className="num" title="天真基準「明日＝今日」的誤差；模型要贏過它才有意義">基準誤差</th>
            <th className="mid" title="預測方向與實際方向是否一致">方向</th>
            <th className="mid">信賴區間</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(r => {
            const dirOk = r.pred_dir !== 0 && r.actual_dir !== 0
              ? r.pred_dir === r.actual_dir : null
            const better = r.error != null && r.baseline_error != null
              && Math.abs(r.error) < Math.abs(r.baseline_error)
            return (
              <tr key={r.planned_date ?? r.date}>
                <td>
                  {r.date}
                  {r.planned_date && r.planned_date !== r.date && (
                    <span className="muted" style={{ fontSize: '.72rem', marginLeft: '.35rem' }}
                          title="存檔時推估的日期落在休市日，已順延到下一個真實交易日">
                      （原估 {r.planned_date.slice(5)}）
                    </span>
                  )}
                </td>
                <td className="num muted">{r.predicted_close?.toFixed(2)}</td>
                <td className="num">
                  {r.actual_close != null
                    ? <strong>{r.actual_close.toFixed(2)}</strong>
                    : <span className="muted">尚未到期</span>}
                </td>
                {/* 誤差方向也是價格方向：實際高於預測＝偏漲側，用紅色 */}
                <td className="num" style={{
                  color: r.error == null ? undefined
                    : r.error >= 0 ? 'var(--up)' : 'var(--down)',
                }}>
                  {r.error == null ? '–' : `${r.error >= 0 ? '+' : ''}${r.error}`}
                </td>
                <td className="num muted">{r.error_pct != null ? `${r.error_pct}%` : '–'}</td>
                <td className="num" style={{ color: better ? 'var(--green)' : 'var(--dim)' }}>
                  {r.baseline_error != null ? Math.abs(r.baseline_error).toFixed(2) : '–'}
                </td>
                <td className="mid">
                  {dirOk == null ? '–'
                    : dirOk ? <span className="tag green">✓</span>
                            : <span className="tag red">✗</span>}
                </td>
                <td className="mid">
                  {r.in_ci == null ? '–'
                    : r.in_ci ? <span className="tag green">✓</span>
                              : <span className="tag red">✗</span>}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

// ── 資料新鮮度 ────────────────────────────────────────────────────────────────
// 比對能不能做，前提是目標日期的收盤價已進資料庫。少了那幾天，卡片會一直停在
// 「尚未到期」——而畫面上看不出是「還沒到那天」還是「到了但沒抓」。
// 這兩件事對使用者的意義完全不同：前者只能等，後者按一下就能解決。
function FreshnessBar({ info, onFilled }) {
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')
  if (!info?.available) return null

  const stale = info.stale ?? []
  const marketStale = info.market_stale

  async function fill() {
    setBusy(true); setMsg('')
    const { data, error } = await backfillData(stale.map(s => s.stock_id))
    setBusy(false)
    setMsg(error ? `補齊失敗：${error}` : (data?.reason ?? '已完成'))
    if (!error) onFilled?.()
  }

  if (!stale.length && !marketStale) {
    return (
      <div className="card">
        <div className="note-box" style={{ borderTop: 'none' }}>
          ✓ 比對用到的 {info.items.length} 檔股票行情都已更新到市場最新交易日
          {' '}<strong style={{ color: 'var(--text)' }}>{info.market_last}</strong>。
          服務啟動時會自動做這項檢查，落後就補齊。
        </div>
      </div>
    )
  }

  return (
    <div className="card">
      <div className="card-header">
        <span className="card-title">資料新鮮度</span>
        {stale.length > 0 && <span className="tag red">{stale.length} 檔行情落後</span>}
        {marketStale && (
          <span className="tag yellow">市場基準日距今 {info.market_gap_days} 天</span>
        )}
        {stale.length > 0 && (
          <button className="btn-primary" style={{ marginLeft: 'auto' }}
                  disabled={busy} onClick={fill}>
            {busy ? '補齊中…（可能要一分鐘）' : '立即補齊'}
          </button>
        )}
      </div>
      <div className="table-wrap">
        <table className="data-table">
          <thead>
            <tr><th>股票</th><th>最後交易日</th><th className="num">已有筆數</th>
                <th className="num">落後交易日</th></tr>
          </thead>
          <tbody>
            {stale.map(r => (
              <tr key={r.stock_id}>
                <td><strong>{r.stock_id}</strong></td>
                <td style={{ color: 'var(--red)' }}>{r.last_date ?? '沒有任何行情'}</td>
                <td className="num muted">{r.rows}</td>
                <td className="num" style={{ color: 'var(--red)' }}>
                  {r.last_date ? r.days_behind : '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="note-box">
        市場最新交易日 <strong style={{ color: 'var(--text)' }}>{info.market_last}</strong>。
        {info.note}
        {marketStale && (
          <div style={{ color: 'var(--yellow)', marginTop: '.35rem' }}>
            市場基準日本身就落後了——那是每日排程沒跑，補齊個股解決不了。
            請確認 `python main.py --mode schedule` 是否在執行。
          </div>
        )}
        <div style={{ marginTop: '.35rem' }}>
          FinMind 匿名額度為 30 次/小時，一次最多補 8 檔；沒補完會照實回報。
        </div>
        {msg && <div style={{ marginTop: '.35rem', color: 'var(--green)' }}>{msg}</div>}
      </div>
    </div>
  )
}

// ── 資料新鮮度（美股）────────────────────────────────────────────────────────
// 美股行情整張表是同一個市場，沒有「其他標的今天有資料」可以當基準，
// 只能用日曆天判斷（門檻 4 天涵蓋週末與國定假日）。補齊走排程 06:10／19:10
// 同一條路，一次補全部美股標的＋台指期＋韓日指數。
function UsFreshnessBar({ info, onFilled }) {
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')
  if (!info?.available) return null

  const us = (info.items ?? []).find(i => i.key === 'us')
  const stale = (info.items ?? []).filter(i => i.stale)

  async function fill() {
    setBusy(true); setMsg('')
    const { data, error } = await backfillExogenous()
    setBusy(false)
    setMsg(error ? `補齊失敗：${error}` : (data?.reason ?? '已完成'))
    if (!error) onFilled?.()
  }

  if (!stale.length) {
    return (
      <div className="card">
        <div className="note-box" style={{ borderTop: 'none' }}>
          ✓ 美股行情已更新到 <strong style={{ color: 'var(--text)' }}>{us?.last_date ?? '–'}</strong>
          （美東場次日期）。排程每日 06:10 與 19:10 自動更新。
        </div>
      </div>
    )
  }

  return (
    <div className="card">
      <div className="card-header">
        <span className="card-title">資料新鮮度</span>
        <span className="tag red">{stale.map(i => i.label).join('、')}落後</span>
        <button className="btn-primary" style={{ marginLeft: 'auto' }}
                disabled={busy} onClick={fill}>
          {busy ? '補齊中…（可能要一分鐘）' : '立即補齊'}
        </button>
      </div>
      <div className="table-wrap">
        <table className="data-table">
          <thead>
            <tr><th>資料</th><th>最後日期</th><th className="num">落後日曆天</th><th>用途</th></tr>
          </thead>
          <tbody>
            {(info.items ?? []).map(i => (
              <tr key={i.key}>
                <td><strong>{i.label}</strong></td>
                <td style={{ color: i.stale ? 'var(--red)' : undefined }}>{i.last_date ?? '沒有任何資料'}</td>
                <td className="num" style={{ color: i.stale ? 'var(--red)' : undefined }}>{i.days_behind ?? '—'}</td>
                <td className="muted">{i.note}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="note-box">
        美股比對要等該場次的收盤進 us_daily_prices（美東收盤後、台北隔日 06:10 排程抓）。
        持續落後代表 <code>python main.py --mode schedule</code> 沒在跑。
        {msg && <div style={{ marginTop: '.35rem', color: 'var(--green)' }}>{msg}</div>}
      </div>
    </div>
  )
}

// ── 比對卡片 ──────────────────────────────────────────────────────────────────
function CompareCard({ record, onDelete, expandAll }) {
  const [detail, setDetail] = useState(null)
  const [state, setState] = useState('loading')   // loading | ok | error
  const [err, setErr] = useState('')
  const [openTable, setOpenTable] = useState(false)

  useEffect(() => {
    let alive = true
    setState('loading'); setErr('')
    getPredictionCompare(record.id).then(({ data, error }) => {
      if (!alive) return
      if (error || !data) { setState('error'); setErr(error || '沒有回應內容'); return }
      setDetail(data); setState('ok')
    })
    return () => { alive = false }
  }, [record.id])

  useEffect(() => { if (expandAll != null) setOpenTable(expandAll) }, [expandAll])

  const matured = Number(record.matured_days ?? 0)
  const totalDays = Number(record.days ?? 0)
  const m = detail?.metrics
  const unit = unitOf(record.market)

  return (
    <div className="card">
      <div className="card-header" style={{ alignItems: 'flex-start' }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div className="row-head">
            {record.market === 'us' && <span className="tag">🇺🇸 美股</span>}
            <span className="card-title">{record.stock_id}</span>
            {record.stock_name && (
              <span style={{ color: 'var(--dim)', fontSize: '.95rem' }}>{record.stock_name}</span>
            )}
            <span className="tag blue">{record.model_label}</span>
            {record.model_version && (
              <span className="tag" title="產生這筆預測的模型版本">v{record.model_version}</span>
            )}
          </div>
          <div className="row-sub">
            <span>{record.first_date} → {record.last_date}（{totalDays} 個{record.market === 'us' ? '場次' : '交易日'}）</span>
            <span>·</span>
            {matured > 0
              ? <MiniBar done={matured} total={totalDays} />
              : <span>尚未到期，等對應日期的收盤價進資料庫</span>}
            <span>·</span>
            <span>儲存於 {new Date(record.saved_at).toLocaleDateString('zh-TW')}</span>
          </div>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '.5rem', flexShrink: 0 }}>
          {m && (
            <span className="tag" style={{
              color: m.margin > 0 ? 'var(--green)' : 'var(--red)',
              background: m.margin > 0 ? 'var(--green-soft)' : 'var(--red-soft)',
            }}>
              超越基準 {pct(m.margin, true)}
            </span>
          )}
          <button className="btn-chip" onClick={() => setOpenTable(o => !o)}>
            {openTable ? '收合明細 ▲' : '逐日明細 ▼'}
          </button>
          <button className="btn-icon" title="刪除這筆紀錄"
                  onClick={() => onDelete(record.id)}>✕</button>
        </div>
      </div>

      {state === 'loading' && (
        <div className="empty-state" style={{ padding: '2rem' }}>載入比對資料…</div>
      )}

      {state === 'error' && (
        <div className="note-box" style={{ color: 'var(--red)' }}>
          比對資料載入失敗：{err}
        </div>
      )}

      {state === 'ok' && detail && (
        <>
          {m ? (
            <>
              <div className="stat-grid">
                <StatTile label="方向準確率" value={pct(m.direction_acc)}
                          color={m.margin > 0 ? 'var(--green)' : 'var(--red)'}
                          sub={`多數類別基準 ${pct(m.baseline_direction_acc)}`}
                          title="預測漲跌方向對的比例；基準是「一律猜漲」能拿到的分數" />
                <StatTile label="超越基準" value={pct(m.margin, true)}
                          color={m.margin > 0 ? 'var(--green)' : 'var(--red)'}
                          sub={`${m.direction_n} 天可判方向`} />
                <StatTile label="MAE" value={`${m.mae} ${unit}`}
                          color={m.beats_baseline_mae ? 'var(--green)' : 'var(--red)'}
                          sub={`天真基準 ${m.baseline_mae} ${unit}`}
                          title="平均絕對誤差；天真基準是「明日＝今日」" />
                <StatTile label="MAPE" value={`${m.mape}%`} />
                {m.hit_rate != null && (
                  <StatTile label="信賴區間命中" value={`${m.hit_rate}%`}
                            color={m.hit_rate >= 70 ? 'var(--green)' : 'var(--yellow)'} />
                )}
                <StatTile label="已比對" value={`${m.filled_days} / ${m.total_days}`}
                          sub={`基準日 ${m.base_date ?? '–'}　收盤 ${m.base_close ?? '–'}`} />
              </div>
              {m.filled_days < 10 && (
                <div className="note-box" style={{ color: 'var(--yellow)' }}>
                  只有 {m.filled_days} 天樣本——這個數量的準確率完全在雜訊範圍內，不足以判斷模型好壞。
                  請看「依模型彙總」分頁，或到「模型版本」頁看累積的線上實測。
                </div>
              )}
            </>
          ) : (
            <div className="note-box">
              尚無實際收盤可比對，下圖只有預測線與天真基準線；
              等 {record.first_date} 之後的收盤價進資料庫，指標與實際線就會出現。
            </div>
          )}

          <ErrorBoundary label={`${record.stock_id} 的比對圖`}>
            <CompareChart rows={detail.rows} />
          </ErrorBoundary>

          {openTable && (
            <ErrorBoundary label="逐日明細">
              <DetailTable rows={detail.rows} />
            </ErrorBoundary>
          )}

          {detail.note && <div className="note-box">{detail.note}</div>}
        </>
      )}
    </div>
  )
}

// ── 依模型彙總 ────────────────────────────────────────────────────────────────
function SummaryPanel({ rows }) {
  if (!rows?.length) {
    return (
      <div className="empty-state">
        <div className="empty-icon">📊</div>
        <div>尚無已到期的預測可彙總</div>
        <div className="muted" style={{ fontSize: '.85rem', marginTop: '.3rem' }}>
          存下的預測要等對應日期的收盤價進資料庫後才會出現在這裡
        </div>
      </div>
    )
  }
  const best = rows[0]
  return (
    <>
      {best?.margin != null && (
        <div className="stat-grid">
          <StatTile label="表現最好的模型" value={best.model_label ?? best.model_key}
                    sub={`${best.matured_days} 天樣本`} />
          <StatTile label="其方向準確率" value={pct(best.direction_acc)}
                    color={best.margin > 0 ? 'var(--green)' : 'var(--red)'}
                    sub={`多數類別基準 ${pct(best.baseline_direction_acc)}`} />
          <StatTile label="超越基準" value={pct(best.margin, true)}
                    color={best.margin > 0 ? 'var(--green)' : 'var(--red)'} />
          <StatTile label="納入彙總的模型" value={rows.length} sub="依超越基準排序" />
        </div>
      )}

      <div className="table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              <th>模型</th>
              <th className="num">紀錄</th>
              <th className="num">已到期天數</th>
              <th className="num">方向準確率</th>
              <th className="num" title="一律猜漲（或猜跌，取高者）能拿到的準確率">多數類別基準</th>
              <th className="num">超越基準</th>
              <th className="num">MAE</th>
              <th className="num" title="明日＝今日">基準 MAE</th>
              <th className="num">信賴區間命中</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(r => (
              <tr key={r.model_key}>
                <td><strong>{r.model_label ?? r.model_key}</strong></td>
                <td className="num muted">{r.records}</td>
                <td className="num muted">{r.matured_days}</td>
                <td className="num">
                  {pct(r.direction_acc)}
                  {r.direction_n != null && (
                    <span className="muted" style={{ fontSize: '.72rem' }}>（{r.direction_n} 天）</span>
                  )}
                </td>
                <td className="num muted">{pct(r.baseline_direction_acc)}</td>
                <td className="num">
                  {r.margin == null ? '–' : (
                    <strong style={{ color: r.margin > 0 ? 'var(--green)' : 'var(--red)' }}>
                      {pct(r.margin, true)}
                    </strong>
                  )}
                </td>
                <td className="num muted">{r.mae ?? '–'}</td>
                <td className="num muted">{r.baseline_mae ?? '–'}</td>
                <td className="num muted">{r.ci_hit_rate != null ? `${r.ci_hit_rate}%` : '–'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="note-box">
        「超越基準」是唯一該看的欄位。方向準確率 55% 聽起來不錯，但若同期一律猜漲就有 58%，
        這個模型是負貢獻。本專案已反覆驗證方向不可預測（Iteration 11、12），
        看到正的超越基準請先確認樣本數夠大。
      </div>
    </>
  )
}

// ── 分頁列 ────────────────────────────────────────────────────────────────────
// 上下各放一份：每張卡片含圖表約 600px 高，只放底部的話要捲過六張卡才看得到，
// 使用者會以為沒有分頁。
function Pager({ page, pageCount, total, pageSize, onChange }) {
  if (total <= pageSize) return null
  return (
    <div className="card">
      <div style={{ display: 'flex', alignItems: 'center', gap: '.6rem',
                    padding: '.75rem 1.25rem', flexWrap: 'wrap' }}>
        <span className="muted" style={{ fontSize: '.85rem' }}>
          第 {page * pageSize + 1}–{Math.min((page + 1) * pageSize, total)} 筆，共 {total} 筆
        </span>
        <div className="btn-group" style={{ marginLeft: 'auto' }}>
          <button className="btn-secondary" disabled={page === 0}
                  onClick={() => onChange(Math.max(page - 1, 0))}>上一頁</button>
          {Array.from({ length: pageCount }, (_, i) => (
            <button key={i} className={i === page ? 'btn-chip active' : 'btn-chip'}
                    onClick={() => onChange(i)}>{i + 1}</button>
          ))}
          <button className="btn-secondary" disabled={page >= pageCount - 1}
                  onClick={() => onChange(Math.min(page + 1, pageCount - 1))}>下一頁</button>
        </div>
      </div>
    </div>
  )
}

// ── 主頁面 ────────────────────────────────────────────────────────────────────
export default function PredictionCompare() {
  useTheme()   // 訂閱主題：切換時重新 render，圖表才會換色
  const [records, setRecords] = useState([])
  const [summary, setSummary] = useState([])
  const [loading, setLoading] = useState(true)
  const [filters, setFilters] = useState({ stock_id: '', model_key: '', status: '', sort: '', market: 'tw' })
  const [tab, setTab] = useState('list')
  const [page, setPage] = useState(0)
  const [expandAll, setExpandAll] = useState(null)   // null = 各卡片自己決定
  const [freshness, setFreshness] = useState(null)
  const market = filters.market

  // 三個請求都帶市場：清單只回該市場、彙總不混幣別、新鮮度看對應的價格表
  async function loadList(f = filters) {
    setLoading(true)
    const [{ data }, s, fresh] = await Promise.all([
      getSavedPredictions(f), getPredictionSummary(f.market),
      f.market === 'us' ? getExogenousFreshness() : getDataFreshness(),
    ])
    setRecords(data ?? [])
    setSummary(s.data ?? [])
    setFreshness(fresh.data ?? null)
    setPage(0)
    setLoading(false)
  }

  useEffect(() => { loadList() }, [])   // eslint-disable-line react-hooks/exhaustive-deps

  function setFilter(key, value) {
    const next = { ...filters, [key]: value }
    setFilters(next)
    loadList(next)
  }

  // 切市場：股票與模型篩選是上一個市場的選項，一併清掉
  function switchMarket(key) {
    if (key === market) return
    const next = { ...filters, market: key, stock_id: '', model_key: '' }
    setFilters(next)
    setFreshness(null)
    loadList(next)
  }

  async function handleDelete(id) {
    await deleteSavedPrediction(id)
    setRecords(prev => prev.filter(r => r.id !== id))
  }

  const stockOptions = [...new Set(records.map(r => r.stock_id))].sort()
  const modelOptions = [...new Map(records.map(r => [r.model_key, r.model_label])).entries()]
  const maturedCount = records.filter(r => Number(r.matured_days) > 0).length
  const pageCount = Math.max(1, Math.ceil(records.length / PAGE_SIZE))
  const shown = records.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE)

  return (
    <>
      <ModelBar page={market === 'us' ? 'compare_us' : 'compare'}
                note={market === 'us'
                  ? '這裡比對的是套在美股上的 LSTM 逐日收盤預測（日期為美東場次）。美股開盤跳空模型走另一條線上台帳，見「美股跳空」與「模型版本」頁。'
                  : '這裡比對的是 LSTM 逐日收盤預測。實際在做買賣決策的跳空／振幅／波動率／成交量／籌碼模型走另一條線上台帳，見「模型版本」頁。'} />
      <div className="card">
        <div className="card-header">
          <div style={{ flex: 1, minWidth: 0 }}>
            <div className="row-head">
              <span className="card-title">預測比對</span>
              <div className="btn-group">
                {MARKETS.map(m => (
                  <button key={m.key} className={`btn-period${market === m.key ? ' active' : ''}`}
                          onClick={() => switchMarket(m.key)}>{m.label}</button>
                ))}
              </div>
              <span className="tag blue">{records.length} 筆已儲存</span>
              {maturedCount > 0
                ? <span className="tag green">{maturedCount} 筆可比對</span>
                : <span className="tag">尚無到期紀錄</span>}
            </div>
            <div className="row-sub">
              於「趨勢預測」執行預測後點「💾 儲存」，待對應日期到來即自動比對實際收盤價；
              指標與圖表直接顯示，逐日明細可收合
            </div>
          </div>
          <div className="btn-group">
            <button className={tab === 'list' ? 'btn-primary' : 'btn-secondary'}
                    onClick={() => setTab('list')}>逐筆比對</button>
            <button className={tab === 'summary' ? 'btn-primary' : 'btn-secondary'}
                    onClick={() => setTab('summary')}>依模型彙總</button>
            <button className="btn-secondary" onClick={() => loadList()}>重新整理</button>
          </div>
        </div>

        {tab === 'list' && (
          <div className="toolbar">
            <label className="fld">
              <span>{market === 'us' ? '標的' : '股票'}</span>
              <select className="ctrl-select" value={filters.stock_id}
                      onChange={e => setFilter('stock_id', e.target.value)}>
                <option value="">全部</option>
                {stockOptions.map(s => <option key={s} value={s}>{s}</option>)}
              </select>
            </label>
            <label className="fld">
              <span>模型</span>
              <select className="ctrl-select" value={filters.model_key}
                      onChange={e => setFilter('model_key', e.target.value)}>
                <option value="">全部</option>
                {modelOptions.map(([k, l]) => <option key={k} value={k}>{l ?? k}</option>)}
              </select>
            </label>
            <label className="fld">
              <span>狀態</span>
              <select className="ctrl-select" value={filters.status}
                      onChange={e => setFilter('status', e.target.value)}>
                <option value="">全部</option>
                <option value="matured">只看已可比對</option>
                <option value="pending">只看尚未到期</option>
              </select>
            </label>
            <label className="fld">
              <span>排序</span>
              <select className="ctrl-select" value={filters.sort}
                      onChange={e => setFilter('sort', e.target.value)}>
                <option value="">依儲存時間</option>
                <option value="stock">依股票</option>
                <option value="model">依模型</option>
              </select>
            </label>
            <button className="btn-secondary" style={{ marginLeft: 'auto' }}
                    onClick={() => setExpandAll(v => !(v === true))}>
              {expandAll === true ? '全部收合明細' : '全部展開明細'}
            </button>
          </div>
        )}

        <div className="note-box">
          實際收盤已還原除權息與減資，並換算到預測基準日的價格尺度，故與預測值同尺度可比；
          每個指標旁邊都附<strong style={{ color: 'var(--text)' }}>天真基準</strong>，贏過基準才標綠。
          單筆紀錄只有幾天樣本，判斷模型好壞請看「依模型彙總」或「模型版本」頁。
        </div>
      </div>

      <ErrorBoundary label="資料新鮮度">
        {market === 'us'
          ? <UsFreshnessBar info={freshness} onFilled={() => loadList()} />
          : <FreshnessBar info={freshness} onFilled={() => loadList()} />}
      </ErrorBoundary>

      {tab === 'summary' && (
        <div className="card">
          <div className="card-header"><span className="card-title">依模型彙總</span></div>
          <ErrorBoundary label="模型彙總">
            <SummaryPanel rows={summary} />
          </ErrorBoundary>
        </div>
      )}

      {tab === 'list' && (
        <>
          {loading && <div className="card"><div className="empty-state">載入中…</div></div>}

          {!loading && records.length === 0 && (
            <div className="card">
              <div className="empty-state">
                <div className="empty-icon">📭</div>
                <div>沒有符合條件的{market === 'us' ? '美股' : ''}預測紀錄</div>
                <div className="muted" style={{ fontSize: '.85rem', marginTop: '.3rem' }}>
                  前往「趨勢預測」{market === 'us' ? '切到美股、' : ''}執行預測後儲存，或放寬上方篩選條件
                </div>
              </div>
            </div>
          )}

          <Pager page={page} pageCount={pageCount} total={records.length}
                 pageSize={PAGE_SIZE} onChange={setPage} />

          {shown.map(r => (
            <CompareCard key={r.id} record={r} onDelete={handleDelete} expandAll={expandAll} />
          ))}

          <Pager page={page} pageCount={pageCount} total={records.length}
                 pageSize={PAGE_SIZE} onChange={p => { setPage(p); window.scrollTo?.({ top: 0 }) }} />

        </>
      )}
    </>
  )
}
