// 週預測頁（Iteration 37）
// ───────────────────────────────────────────────────────────────────────────
// 每星期日 08:00 排程器用所有可用模型，對所有已有股票預測「下一週」與「下下週」，
// 結果存表；這一頁開了就顯示最新一次，不需要按任何按鈕。
//
// 每個模型的視野不同，畫面照實標：LSTM 十個模型逐日 10 個交易日（兩週都有）、
// 波動率 20 日（兩週都在裡面）、振幅／成交量 5 日（只有下週）、
// M3／M2 3 日方向、跳空只有下週第一天。視野不到的格子就是「–」，不硬湊。
//
// LSTM 的可信度：Iteration 11／36 兩次實測方向等同擲銅板。這裡顯示十個模型的
// 中位數與範圍，是為了讓「十個模型各說各話」這件事看得見，不是把中位數當答案。
import { useEffect, useState } from 'react'
import { getWeeklyForecast, runWeeklyForecast, getWeeklyForecastStatus } from '../services/api'

const LSTM_LABEL = {
  m01_vanilla: 'M01 Vanilla', m02_stacked: 'M02 Stacked', m03_bidirectional: 'M03 BiLSTM',
  m04_attention: 'M04 Attention', m05_cnn_lstm: 'M05 CNN-LSTM', m06_multifeature: 'M06 Multi',
  m07_seq2seq: 'M07 Seq2Seq', m08_mc_dropout: 'M08 MC Dropout', m09_technical: 'M09 Technical',
  m10_ensemble: 'M10 Ensemble',
}
const SIGNAL_LABEL = { Buy: '買進', Sell: '賣出', Hold: '觀望' }

function pct(v, digits = 2) {
  if (v === null || v === undefined || Number.isNaN(Number(v))) return '–'
  const n = Number(v)
  return `${n > 0 ? '+' : ''}${n.toFixed(digits)}%`
}
function tone(v) {
  if (v === null || v === undefined || Number.isNaN(Number(v))) return 'muted'
  return Number(v) > 0 ? 'up' : Number(v) < 0 ? 'down' : 'muted'
}
function num(v, digits = 2) {
  return v === null || v === undefined ? '–' : Number(v).toFixed(digits)
}
function fmtDate(s) {
  if (!s) return '–'
  const d = String(s).slice(0, 10)
  return `${Number(d.slice(5, 7))}/${Number(d.slice(8, 10))}`
}
function fmtTime(s) {
  return s ? String(s).replace('T', ' ').slice(0, 16) : '–'
}

function LstmCell({ w }) {
  if (!w || w.median_chg_pct === null || w.median_chg_pct === undefined) return <span className="muted">–</span>
  return (
    <span title={`十個模型：${w.n_up} 個看漲；範圍 ${pct(w.min_chg_pct)} ~ ${pct(w.max_chg_pct)}`}>
      <span className={tone(w.median_chg_pct)}>{pct(w.median_chg_pct)}</span>
      <div className="muted" style={{ fontSize: '0.72rem' }}>
        {pct(w.min_chg_pct, 1)} ~ {pct(w.max_chg_pct, 1)} · {w.n_up}/10 漲
      </div>
    </span>
  )
}

function SignalCell({ s }) {
  if (!s || !s.signal) return <span className="muted">–</span>
  const cls = s.signal === 'Buy' ? 'up' : s.signal === 'Sell' ? 'down' : 'muted'
  return (
    <span title={s.reason || ''}>
      <span className={cls}>{SIGNAL_LABEL[s.signal] || s.signal}</span>
      {s.confidence ? <span className="muted" style={{ fontSize: '0.72rem' }}> {Math.round(s.confidence * 100)}%</span> : null}
    </span>
  )
}

function LstmDetail({ row, run }) {
  const models = row.lstm?.models || {}
  const keys = Object.keys(LSTM_LABEL).filter(k => models[k])
  if (!keys.length) return <div className="muted" style={{ padding: '8px 12px' }}>這一檔沒有 LSTM 結果（預測服務未啟動或資料不足）</div>
  return (
    <table className="data-table" style={{ fontSize: '0.8rem' }}>
      <thead>
        <tr>
          <th>LSTM 模型</th>
          <th style={{ textAlign: 'right' }}>下週末（{fmtDate(run.week1.end)}）</th>
          <th style={{ textAlign: 'right' }}>變動</th>
          <th style={{ textAlign: 'right' }}>95% 區間</th>
          <th style={{ textAlign: 'right' }}>下下週末（{fmtDate(run.week2.end)}）</th>
          <th style={{ textAlign: 'right' }}>變動</th>
          <th style={{ textAlign: 'right' }}>95% 區間</th>
        </tr>
      </thead>
      <tbody>
        {keys.map(k => {
          const m = models[k]
          return (
            <tr key={k}>
              <td>{LSTM_LABEL[k]}</td>
              <td style={{ textAlign: 'right' }}>{num(m.week1?.close)}</td>
              <td style={{ textAlign: 'right' }} className={tone(m.week1?.chg_pct)}>{pct(m.week1?.chg_pct)}</td>
              <td style={{ textAlign: 'right' }} className="muted">{m.week1 ? `${num(m.week1.ci_low)} ~ ${num(m.week1.ci_high)}` : '–'}</td>
              <td style={{ textAlign: 'right' }}>{num(m.week2?.close)}</td>
              <td style={{ textAlign: 'right' }} className={tone(m.week2?.chg_pct)}>{pct(m.week2?.chg_pct)}</td>
              <td style={{ textAlign: 'right' }} className="muted">{m.week2 ? `${num(m.week2.ci_low)} ~ ${num(m.week2.ci_high)}` : '–'}</td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}

export default function WeeklyForecast({ onSelectStock }) {
  const [data, setData]       = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError]     = useState('')
  const [market, setMarket]   = useState('tw')
  const [open, setOpen]       = useState({})
  const [running, setRunning] = useState(false)
  const [msg, setMsg]         = useState('')

  function load() {
    setLoading(true)
    getWeeklyForecast().then(({ data: res, error: e }) => {
      if (e) setError(e)
      else { setData(res); setError(''); setRunning(!!res?.status?.running) }
      setLoading(false)
    })
  }
  useEffect(() => { load() }, [])

  // 執行中每 15 秒看一次狀態，跑完自動刷新——使用者不必按重新整理
  useEffect(() => {
    if (!running) return undefined
    const t = setInterval(() => {
      getWeeklyForecastStatus().then(({ data: st }) => {
        if (st && !st.running) { setRunning(false); setMsg('執行完成，已更新'); load() }
      })
    }, 15000)
    return () => clearInterval(t)
  }, [running])

  async function rerun() {
    setMsg('')
    const { data: r, error: e } = await runWeeklyForecast()
    if (e) { setMsg(`無法啟動：${e}`); return }
    if (r?.status === 'already_running') setMsg('已在執行中')
    else setMsg('已開始執行，十個 LSTM × 全部股票約需數分鐘，完成後自動更新')
    setRunning(true)
  }

  const run  = data?.run
  const rows = data?.markets?.[market] || []
  const errors = run?.errors || []
  const lstmMissing = errors.some(e => String(e).startsWith('lstm:'))
  const isUs = market === 'us'

  return (
    <>
      <div className="cards-grid">
        <div className="metric-card">
          <div className="metric-label">上次自動執行</div>
          <div className="metric-value sm">{run ? fmtTime(run.finished_at) : '尚未執行'}</div>
          <div className="metric-delta muted">
            {run ? `行情基準日 ${run.base_date || '–'} · ${run.trigger === 'schedule' ? '排程' : run.trigger === 'catch_up' ? '啟動補跑' : '手動'}` : '排程每週日 08:00'}
          </div>
        </div>
        <div className="metric-card">
          <div className="metric-label">下一週</div>
          <div className="metric-value sm">{run ? `${fmtDate(run.week1.start)} – ${fmtDate(run.week1.end)}` : '–'}</div>
          <div className="metric-delta muted">LSTM 第 1~5 個交易日；振幅、成交量、跳空、籌碼、新聞</div>
        </div>
        <div className="metric-card">
          <div className="metric-label">下下週</div>
          <div className="metric-value sm">{run ? `${fmtDate(run.week2.start)} – ${fmtDate(run.week2.end)}` : '–'}</div>
          <div className="metric-delta muted">LSTM 第 6~10 個交易日；波動率（20 日）涵蓋兩週</div>
        </div>
        <div className="metric-card">
          <div className="metric-label">下次自動執行</div>
          <div className="metric-value sm">{data?.next_run ? fmtTime(data.next_run) : '週日 08:00'}</div>
          <div className="metric-delta muted">
            {run ? `${run.n_stocks} 檔 · ${run.n_models} 個模型 · ${run.n_rows} 筆` : '不需人工觸發'}
          </div>
        </div>
      </div>

      {lstmMissing && (
        <div className="card" style={{ borderColor: 'var(--orange)' }}>
          <div className="card-body">
            ⚠ 上次執行時 LSTM 預測服務（:8001）沒有啟動，十個 LSTM 的欄位是空的；其餘模型正常。
            啟動 start-dev.bat 後按「立即補跑」即可補齊。
          </div>
        </div>
      )}

      <div className="card">
        <div className="card-header">
          <span className="card-title">
            {isUs ? '美股' : '台股'}全部股票 · 全模型預測
            {run?.errors?.length ? <span className="muted"> · {run.errors.length} 個模型／股票失敗</span> : null}
          </span>
          <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
            <button className={`btn-chip${market === 'tw' ? ' active' : ''}`} onClick={() => setMarket('tw')}>台股</button>
            <button className={`btn-chip${market === 'us' ? ' active' : ''}`} onClick={() => setMarket('us')}>美股</button>
            <button className="btn-chip" onClick={load}>重新整理</button>
            <button className="btn-chip" onClick={rerun} disabled={running}>{running ? '執行中…' : '立即補跑'}</button>
          </div>
        </div>
        {msg && <div className="card-body muted">{msg}</div>}
        {loading && <div className="card-body muted">載入中…</div>}
        {error && <div className="card-body" style={{ color: 'var(--orange)' }}>{error}</div>}
        {!loading && !error && data && !data.available && (
          <div className="card-body muted">{data.reason}（下次：{fmtTime(data.next_run)}）</div>
        )}

        {!loading && !error && run && (
          <div style={{ overflowX: 'auto' }}>
            <table className="data-table">
              <thead>
                <tr>
                  <th>股票</th>
                  <th style={{ textAlign: 'right' }}>基準收盤</th>
                  <th style={{ textAlign: 'right' }}>LSTM 下週<div className="muted" style={{ fontSize: '0.7rem', fontWeight: 400 }}>十模型中位數</div></th>
                  <th style={{ textAlign: 'right' }}>LSTM 下下週<div className="muted" style={{ fontSize: '0.7rem', fontWeight: 400 }}>十模型中位數</div></th>
                  {!isUs && <th style={{ textAlign: 'right' }}>振幅 5 日</th>}
                  {!isUs && <th style={{ textAlign: 'right' }}>波動率 · 停損 · 部位</th>}
                  {!isUs && <th style={{ textAlign: 'right' }}>量能 5 日</th>}
                  {!isUs && <th>籌碼 3 日</th>}
                  {!isUs && <th>新聞 3 日</th>}
                  <th style={{ textAlign: 'right' }}>{isUs ? '下一場跳空' : '次日跳空'}</th>
                </tr>
              </thead>
              <tbody>
                {rows.map(r => {
                  const key = `${market}:${r.stock_id}`
                  const isOpen = !!open[key]
                  return (
                    <>
                      <tr key={key}>
                        <td style={{ whiteSpace: 'nowrap' }}>
                          <strong>{r.stock_id}</strong>
                          <div className="muted" style={{ fontSize: '0.75rem' }}>{r.name}</div>
                          <div style={{ marginTop: 4, display: 'flex', gap: 4 }}>
                            <button className={`btn-chip${isOpen ? ' active' : ''}`} style={{ fontSize: '0.7rem', padding: '1px 6px' }}
                                    onClick={() => setOpen(o => ({ ...o, [key]: !isOpen }))}>
                              {isOpen ? '收合十模型' : '十模型'}
                            </button>
                            {!isUs && onSelectStock && (
                              <button className="btn-chip" style={{ fontSize: '0.7rem', padding: '1px 6px' }} onClick={() => onSelectStock(r.stock_id)}>分析</button>
                            )}
                          </div>
                        </td>
                        <td style={{ textAlign: 'right' }}>
                          {num(r.close)}
                          <div className="muted" style={{ fontSize: '0.72rem' }}>{fmtDate(r.last_date)}</div>
                        </td>
                        <td style={{ textAlign: 'right' }}><LstmCell w={r.lstm?.week1} /></td>
                        <td style={{ textAlign: 'right' }}><LstmCell w={r.lstm?.week2} /></td>
                        {!isUs && (
                          <td style={{ textAlign: 'right' }}>
                            {r.range ? (
                              <span title={`自身中位數 ${num(r.range.hist_median_pct)}% 的 ${num(r.range.self_ratio)} 倍；同儕前 ${num(100 - r.range.peer_pct, 0)}%`}>
                                {num(r.range.range_pct)}%{r.range.is_significant ? <span className="up"> ★</span> : null}
                                <div className="muted" style={{ fontSize: '0.72rem' }}>{num(r.range.expected_low)} ~ {num(r.range.expected_high)}</div>
                              </span>
                            ) : <span className="muted">–</span>}
                          </td>
                        )}
                        {!isUs && (
                          <td style={{ textAlign: 'right' }}>
                            {r.volatility ? (
                              <span title={`引擎 ${r.volatility.engine}`}>
                                {r.volatility.vol_regime}
                                <div className="muted" style={{ fontSize: '0.72rem' }}>停損 {num(r.volatility.stop_pct, 1)}% · 部位 {num(r.volatility.position_pct, 0)}%</div>
                              </span>
                            ) : <span className="muted">–</span>}
                          </td>
                        )}
                        {!isUs && (
                          <td style={{ textAlign: 'right' }}>
                            {r.volume ? (
                              <span title={r.volume.expected_daily_volume ? `預估日均量 ${Number(r.volume.expected_daily_volume).toLocaleString()} 股` : ''}>
                                <span className={r.volume.liquidity === 'thin' ? 'down' : r.volume.liquidity === 'thick' ? 'up' : ''}>×{num(r.volume.vol_multiple)}</span>
                                <div className="muted" style={{ fontSize: '0.72rem' }}>
                                  {r.volume.liquidity === 'thin' ? '量縮' : r.volume.liquidity === 'thick' ? '量增' : '常態'}
                                </div>
                              </span>
                            ) : <span className="muted">–</span>}
                          </td>
                        )}
                        {!isUs && <td><SignalCell s={r.m3_chip} /></td>}
                        {!isUs && <td><SignalCell s={r.m2_news} /></td>}
                        <td style={{ textAlign: 'right' }}>
                          {r.gap ? (
                            <span title={r.gap.caveat || (r.gap.target_session ? `場次 ${r.gap.target_session}` : '')}>
                              <span className={tone(r.gap.gap_pct)}>{pct(r.gap.gap_pct)}</span>
                              {r.gap.caveat ? <span className="muted" style={{ fontSize: '0.7rem' }}> ⚠</span> : null}
                              <div className="muted" style={{ fontSize: '0.72rem' }}>開 {num(r.gap.implied_open)}</div>
                            </span>
                          ) : <span className="muted">–</span>}
                        </td>
                      </tr>
                      {isOpen && (
                        <tr key={`${key}-detail`}>
                          <td colSpan={isUs ? 5 : 10} style={{ padding: 0, background: 'var(--surface)' }}>
                            <LstmDetail row={r} run={run} />
                          </td>
                        </tr>
                      )}
                    </>
                  )
                })}
                {rows.length === 0 && (
                  <tr><td colSpan={10} className="muted">這個市場沒有結果</td></tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {run && errors.length > 0 && (
        <div className="card">
          <div className="card-header"><span className="card-title">上次執行的失敗項目（{errors.length}）</span></div>
          <div className="card-body muted" style={{ fontSize: '0.8rem', maxHeight: 220, overflowY: 'auto' }}>
            {errors.slice(0, 60).map((e, i) => <div key={i}>{String(e)}</div>)}
            {errors.length > 60 && <div>…其餘 {errors.length - 60} 項略</div>}
          </div>
        </div>
      )}

      <div className="card">
        <div className="card-header"><span className="card-title">怎麼讀這張表</span></div>
        <div className="card-body" style={{ lineHeight: 1.8 }}>
          <p>
            <strong>每週日 08:00 自動跑，不用按。</strong> 排程器對台股追蹤清單與美股標的，用目錄裡全部模型各算一次；
            程序若週日沒開，下次啟動時會補跑。「立即補跑」只是給 LSTM 服務當時沒開的情況用。
          </p>
          <p>
            <strong>視野不同，格子就不同。</strong> LSTM 逐日算 10 個交易日，所以下週、下下週都有；波動率看 20 日，兩週都在裡面；
            振幅與成交量只看 5 日、籌碼與新聞只看 3 日、跳空只看下一個交易日——這些只涵蓋下週，下下週的欄位就沒有它們。
          </p>
          <p>
            <strong>LSTM 的數字是「十個模型各說各話」的紀錄，不是答案。</strong> Iteration 11 與 36 兩次實測，十個 LSTM 的方向準確率
            都在擲銅板附近；中位數與範圍是為了讓分歧看得見。振幅（★ = 顯著偏大）、波動率、量能三個閘門模型在線上實測站得住，
            它們回答的是「會不會震、押多少、吃不吃得下」，不是漲跌。
          </p>
          <p>
            <strong>跳空欄的 ⚠。</strong> 2026-09-20 的準確度報告發現台股跳空模型線上餵的是當天的夜盤特徵，數字可能對應已發生的跳空；修好前照實標出。
          </p>
        </div>
      </div>
    </>
  )
}
