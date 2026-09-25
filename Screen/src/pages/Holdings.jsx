// 持股管理 — 輸入目前持有的股票數量與購買成本
//
// 這些資料會直接進入投票決策：沒有持股資訊時，系統只能回答「該不該買」，
// 有了持股與成本才能回答真正該回答的問題——加碼、減碼、停損、還是不動。
// 對沒持有的股票發賣出訊號是沒有意義的（本系統不做放空）。

import { useEffect, useState } from 'react'
import {
  getHoldings, saveHolding, updateHolding, deleteHolding, getTrackedStocks,
  getTrades, addTrade, deleteTrade, estimateTradeCosts, getDecisionReview,
} from '../services/api'
import { Shares, SharesInput, formatShares } from '../components/Shares'
import ModelBar from '../components/ModelBar'

const money = v => (v == null ? '–' : Number(v).toLocaleString('zh-TW',
  { maximumFractionDigits: 0 }))
// 損益用台股慣例：獲利紅、虧損綠
const pnlColor = v => (v == null ? 'var(--dim)' : v > 0 ? 'var(--up)' : v < 0 ? 'var(--down)' : 'var(--dim)')

// ── 新增／編輯表單 ────────────────────────────────────────────────────────────
function HoldingForm({ stocks, editing, onDone, onCancel }) {
  const [stockId, setStockId] = useState(editing?.stock_id ?? '')
  const [shares, setShares] = useState(editing?.shares ?? '')
  const [cost, setCost] = useState(editing?.avg_cost ?? '')
  const [note, setNote] = useState(editing?.note ?? '')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')

  async function submit(e) {
    e.preventDefault()
    if (!stockId || !(Number(shares) > 0) || !(Number(cost) > 0)) {
      setErr('股票代號、股數、成本都要填，且股數與成本須大於 0')
      return
    }
    setBusy(true); setErr('')
    const { error } = editing
      ? await updateHolding(editing.id, { shares: Number(shares), avg_cost: Number(cost), note })
      : await saveHolding({ stock_id: stockId.trim(), shares: Number(shares), avg_cost: Number(cost), note })
    setBusy(false)
    if (error) setErr(error)
    else onDone()
  }

  return (
    <form onSubmit={submit} style={{ padding: '14px 18px', borderTop: '1px solid var(--border)' }}>
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'flex-end' }}>
        <Field label="股票代號">
          <input className="ctrl-select" list="holding-stocks" value={stockId}
                 disabled={!!editing} placeholder="2330"
                 onChange={e => setStockId(e.target.value)} style={{ width: 120 }} />
          <datalist id="holding-stocks">
            {stocks.map(s => (
              <option key={s.stock_id} value={s.stock_id}>{s.stock_name}</option>
            ))}
          </datalist>
        </Field>
        <Field label="持有股數" hint="1 張 = 1000 股；零股填在右欄（0~999）">
          <SharesInput value={shares} onChange={setShares} />
        </Field>
        <Field label="每股平均成本">
          <input className="ctrl-select" type="number" step="0.01" min="0.01" value={cost}
                 placeholder="580.5" onChange={e => setCost(e.target.value)}
                 style={{ width: 130 }} />
        </Field>
        <Field label="備註（選填）">
          <input className="ctrl-select" value={note} placeholder="長期／波段…"
                 onChange={e => setNote(e.target.value)} style={{ width: 180 }} />
        </Field>
        <button className="btn-primary" type="submit" disabled={busy}>
          {busy ? '儲存中…' : editing ? '更新' : '新增持股'}
        </button>
        {editing && (
          <button className="btn-secondary" type="button" onClick={onCancel}>取消</button>
        )}
      </div>
      {err && <div style={{ color: 'var(--red)', fontSize: '0.75rem', marginTop: 8 }}>{err}</div>}
      {!editing && (
        <div style={{ color: 'var(--dim)', fontSize: '0.6875rem', marginTop: 8 }}>
          同一檔股票再次新增會覆蓋原本的股數與成本（視為更新持倉，而非加倉紀錄）。
          要記錄分批進出請改用「交易紀錄」。
        </div>
      )}
    </form>
  )
}

function Field({ label, hint, children }) {
  return (
    <div>
      <div style={{ fontSize: '0.6875rem', color: 'var(--dim)', marginBottom: 4 }} title={hint}>{label}</div>
      {children}
    </div>
  )
}

// ── 交易表單 ──────────────────────────────────────────────────────────────────
// 手續費與證交稅預設依台股費率估算，但一律可覆寫——券商折扣人人不同，
// 而不計費用的損益數字看起來永遠比真實情況好。
function TradeForm({ stocks, onDone }) {
  const today = new Date().toISOString().slice(0, 10)
  const [f, setF] = useState({
    stock_id: '', trade_date: today, side: 'Buy',
    shares: '', price: '', fee: '', tax: '', note: '',
  })
  const [est, setEst] = useState(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')

  const set = (k, v) => setF(prev => ({ ...prev, [k]: v }))

  useEffect(() => {
    if (!(Number(f.shares) > 0) || !(Number(f.price) > 0)) { setEst(null); return }
    let alive = true
    estimateTradeCosts(f.side, f.shares, f.price).then(({ data }) => {
      if (alive) setEst(data)
    })
    return () => { alive = false }
  }, [f.side, f.shares, f.price])

  async function submit(e) {
    e.preventDefault()
    if (!f.stock_id || !(Number(f.shares) > 0) || !(Number(f.price) > 0)) {
      setErr('股票代號、股數、價格為必填，且股數與價格須大於 0')
      return
    }
    setBusy(true); setErr('')
    const { error } = await addTrade({ ...f, shares: Number(f.shares), price: Number(f.price) })
    setBusy(false)
    if (error) setErr(error)
    else { setF({ ...f, shares: '', price: '', fee: '', tax: '', note: '' }); onDone() }
  }

  const gross = (Number(f.shares) || 0) * (Number(f.price) || 0)
  const fee = f.fee !== '' ? Number(f.fee) : (est?.fee ?? 0)
  const tax = f.tax !== '' ? Number(f.tax) : (est?.tax ?? 0)
  const net = f.side === 'Buy' ? gross + fee : gross - fee - tax

  return (
    <form onSubmit={submit} style={{ padding: '14px 18px', borderTop: '1px solid var(--border)' }}>
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'flex-end' }}>
        <Field label="股票代號">
          <input className="ctrl-select" list="trade-stocks" value={f.stock_id}
                 placeholder="2330" onChange={e => set('stock_id', e.target.value)}
                 style={{ width: 110 }} />
          <datalist id="trade-stocks">
            {stocks.map(x => <option key={x.stock_id} value={x.stock_id}>{x.stock_name}</option>)}
          </datalist>
        </Field>
        <Field label="日期">
          <input className="ctrl-select" type="date" value={f.trade_date}
                 onChange={e => set('trade_date', e.target.value)} style={{ width: 150 }} />
        </Field>
        <Field label="買賣別">
          <select className="ctrl-select" value={f.side}
                  onChange={e => set('side', e.target.value)} style={{ width: 90 }}>
            <option value="Buy">買進</option>
            <option value="Sell">賣出</option>
          </select>
        </Field>
        <Field label="成交股數" hint="1 張 = 1000 股；盤中零股填在右欄（0~999）">
          <SharesInput value={f.shares} onChange={v => set('shares', v)} />
        </Field>
        <Field label="成交價">
          <input className="ctrl-select" type="number" step="0.01" min="0.01" value={f.price}
                 placeholder="2350" onChange={e => set('price', e.target.value)}
                 style={{ width: 110 }} />
        </Field>
        <Field label="手續費" hint="留空則依 0.1425%（最低 20 元）自動估算">
          <input className="ctrl-select" type="number" step="1" value={f.fee}
                 placeholder={est ? String(est.fee) : '自動'}
                 onChange={e => set('fee', e.target.value)} style={{ width: 100 }} />
        </Field>
        {f.side === 'Sell' && (
          <Field label="證交稅" hint="留空則依 0.3% 自動估算">
            <input className="ctrl-select" type="number" step="1" value={f.tax}
                   placeholder={est ? String(est.tax) : '自動'}
                   onChange={e => set('tax', e.target.value)} style={{ width: 100 }} />
          </Field>
        )}
        <Field label="備註（選填）">
          <input className="ctrl-select" value={f.note} placeholder="加碼／停利…"
                 onChange={e => set('note', e.target.value)} style={{ width: 150 }} />
        </Field>
        <button className="btn-primary" type="submit" disabled={busy}>
          {busy ? '記錄中…' : '記錄交易'}
        </button>
      </div>

      {gross > 0 && (
        <div style={{ fontSize: '0.75rem', color: 'var(--dim)', marginTop: 10 }}>
          {formatShares(f.shares)} × {Number(f.price).toFixed(2)} ＝
          價金 {money(gross)} 元　手續費 {money(fee)} 元
          {f.side === 'Sell' && `　證交稅 ${money(tax)} 元`}
          　→ <strong style={{ color: 'var(--text)' }}>
            實際{f.side === 'Buy' ? '支出' : '入帳'} {money(net)} 元
          </strong>
        </div>
      )}
      {Number(f.shares) > 0 && Number(f.shares) < 1000 && (
        <div style={{ fontSize: '0.6875rem', color: 'var(--dim)', marginTop: 6 }}>
          零股交易的手續費仍有最低收費（預設 20 元），小額成交時它佔比會很高——
          上面的「實際{f.side === 'Buy' ? '支出' : '入帳'}」已經把它算進去了。
          你的券商若有零股優惠，直接覆寫手續費欄。
        </div>
      )}
      {err && <div style={{ color: 'var(--red)', fontSize: '0.75rem', marginTop: 8 }}>{err}</div>}
    </form>
  )
}

// ── 交易台帳 ──────────────────────────────────────────────────────────────────
function TradeTable({ trades, onDelete }) {
  if (!trades.length) {
    return (
      <div className="empty-state">
        <div className="empty-icon">🧾</div>
        <div>尚無交易紀錄</div>
        <div className="muted" style={{ fontSize: '0.75rem', marginTop: 6 }}>
          記錄買賣之後，持股的平均成本與已實現損益都會自動推導，不必手算
        </div>
      </div>
    )
  }
  return (
    <div className="table-wrap">
      <table className="data-table">
        <thead>
          <tr>
            <th>日期</th><th>股票</th><th>買賣</th><th>股數</th><th>成交價</th>
            <th>價金</th><th>手續費</th><th>證交稅</th>
            <th title="這筆交易之後的持股數與平均成本">交易後持倉</th>
            <th>已實現損益</th><th>備註</th><th></th>
          </tr>
        </thead>
        <tbody>
          {trades.map(t => (
            <tr key={t.id}>
              <td className="muted">{t.trade_date}</td>
              <td>
                <strong>{t.stock_id}</strong>
                {t.stock_name && <span className="muted" style={{ marginLeft: 5, fontSize: '0.75rem' }}>{t.stock_name}</span>}
              </td>
              <td>
                <span style={{
                  padding: '2px 8px', borderRadius: 8, fontSize: '0.75rem', fontWeight: 600,
                  background: t.side === 'Buy' ? 'var(--up-soft)' : 'var(--down-soft)',
                  color: t.side === 'Buy' ? 'var(--up)' : 'var(--down)',
                }}>{t.side === 'Buy' ? '買進' : '賣出'}</span>
              </td>
              <td><Shares value={t.shares} muted /></td>
              <td>{t.price?.toFixed(2)}</td>
              <td className="muted">{money(t.gross)}</td>
              <td className="muted">{money(t.fee)}</td>
              <td className="muted">{t.tax ? money(t.tax) : '–'}</td>
              <td className="muted">
                {t.shares_after != null
                  ? <><Shares value={t.shares_after} muted /> @ {t.avg_cost_after?.toFixed(2)}</>
                  : '–'}
              </td>
              <td style={{ color: pnlColor(t.realized_pnl), fontWeight: 600 }}>
                {t.realized_pnl == null ? '–'
                  : `${t.realized_pnl > 0 ? '+' : ''}${money(t.realized_pnl)}`}
              </td>
              <td className="muted" style={{ fontSize: '0.75rem' }}>{t.note ?? ''}</td>
              <td>
                <button className="btn-chip" style={{ color: 'var(--dim)' }}
                        onClick={() => onDelete(t)}>刪除</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="muted" style={{ fontSize: '0.6875rem', padding: '10px 18px', lineHeight: 1.7 }}>
        成本基礎採<strong>移動平均法</strong>：買進時把手續費計入成本
        （新均價 =（原股數×原成本 + 本次價金 + 手續費）÷ 新股數），
        賣出時已實現損益 = 價金 − 賣出股數×平均成本 − 手續費 − 證交稅，平均成本不變。
        刪除任一筆交易會把該股票的所有交易重新回放一次，後續每筆的均價都會跟著重算。
      </div>
    </div>
  )
}

// ── 建議 vs 實際 ──────────────────────────────────────────────────────────────
// 這一頁的意義不在「使用者有沒有聽話」，而在兩邊都要被檢驗：
// 聽了建議結果變差是模型的問題，沒聽建議結果更好也是模型的問題。
// 所以每一筆都附上事後 5 個交易日的實際報酬。
const MATCH_STYLE = {
  follow:  { color: 'var(--green)', bg: 'var(--green-soft)' },
  against: { color: 'var(--red)',   bg: 'var(--red-soft)' },
  neutral: { color: 'var(--yellow)',      bg: 'var(--yellow-soft)' },
  none:    { color: 'var(--dim)',   bg: 'var(--dim-soft)' },
}

function ReviewPanel({ review }) {
  if (!review) return <div className="empty-state"><div className="muted">載入中...</div></div>
  const { items = [], missed = [], summary, note } = review

  if (items.length === 0) {
    return (
      <div className="empty-state">
        <div className="empty-icon">🔍</div>
        <div>尚無交易可對照</div>
        <div className="muted" style={{ fontSize: '0.75rem', marginTop: 6, lineHeight: 1.7 }}>
          在「交易紀錄」記下實際買賣之後，這裡會把當天的系統建議、你的動作、
          以及事後 5 個交易日的實際報酬放在一起
          {summary?.missed_count > 0 && (
            <div style={{ marginTop: 4 }}>
              目前有 {summary.missed_count} 筆系統建議沒有對應的交易動作
            </div>
          )}
        </div>
      </div>
    )
  }

  return (
    <>
      <div className="card">
        <div style={{ display: 'flex', gap: 28, padding: '14px 18px', flexWrap: 'wrap' }}>
          <Stat label="已對照交易" value={`${summary.matured} / ${summary.trades} 筆`}
                hint="需等事後 5 個交易日的收盤價進資料庫才能對照" />
          <Stat label="跟隨建議比例"
                value={summary.follow_rate == null ? '–' : `${summary.follow_rate}%`}
                hint="只計入系統有明確買賣建議的交易；建議觀望與無建議不算" />
          <Stat label="跟隨建議的平均效益"
                value={summary.follow.avg_benefit == null ? '–' : `${summary.follow.avg_benefit > 0 ? '+' : ''}${summary.follow.avg_benefit}%`}
                color={pnlColor(summary.follow.avg_benefit)}
                hint={`${summary.follow.n} 筆`} />
          <Stat label="違背建議的平均效益"
                value={summary.against.avg_benefit == null ? '–' : `${summary.against.avg_benefit > 0 ? '+' : ''}${summary.against.avg_benefit}%`}
                color={pnlColor(summary.against.avg_benefit)}
                hint={`${summary.against.n} 筆`} />
          <Stat label="未執行的建議" value={`${summary.missed_count} 筆`}
                hint="系統喊買／賣但 3 天內沒有對應交易" />
        </div>
        <div className="muted" style={{ fontSize: '0.6875rem', padding: '0 18px 14px', lineHeight: 1.7 }}>
          {note}
        </div>
      </div>

      <div className="card">
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>交易日</th><th>股票</th><th>動作</th><th>股數</th><th>成交價</th>
                <th>當時建議</th><th>一致性</th>
                <th title="交易日之後 5 個交易日的 adj_close 變動">事後 5 日</th>
                <th title="買進看漲幅、賣出看跌幅">效益</th>
              </tr>
            </thead>
            <tbody>
              {items.map(r => {
                const m = MATCH_STYLE[r.match.key] ?? MATCH_STYLE.none
                return (
                  <tr key={r.id}>
                    <td className="muted">{r.trade_date}</td>
                    <td>
                      <strong>{r.stock_id}</strong>
                      {r.stock_name && <span className="muted" style={{ marginLeft: 5, fontSize: '0.75rem' }}>{r.stock_name}</span>}
                    </td>
                    <td>
                      <span style={{
                        padding: '2px 8px', borderRadius: 8, fontSize: '0.75rem', fontWeight: 600,
                        background: r.side === 'Buy' ? 'var(--up-soft)' : 'var(--down-soft)',
                        color: r.side === 'Buy' ? 'var(--up)' : 'var(--down)',
                      }}>{r.side === 'Buy' ? '買進' : '賣出'}</span>
                    </td>
                    <td><Shares value={r.shares} muted /></td>
                    <td className="muted">{r.price?.toFixed(2)}</td>
                    <td className="muted" style={{ fontSize: '0.75rem' }}>
                      {r.recommendation ?? '–'}
                      {r.vote_date && (
                        <span style={{ fontSize: '0.625rem', marginLeft: 4 }}
                              title={`投票日 ${r.vote_date}`}>
                          （{r.vote_age_days} 天前{r.stale_vote ? '·已過期' : ''}）
                        </span>
                      )}
                    </td>
                    <td>
                      <span style={{ padding: '2px 8px', borderRadius: 8, fontSize: '0.6875rem',
                                     background: m.bg, color: m.color }}>
                        {r.match.label}
                      </span>
                    </td>
                    <td style={{ color: pnlColor(r.fwd_return_5d) }}>
                      {r.fwd_return_5d == null ? '尚未到期'
                        : `${r.fwd_return_5d > 0 ? '+' : ''}${r.fwd_return_5d}%`}
                    </td>
                    <td style={{ color: pnlColor(r.benefit), fontWeight: 600 }}>
                      {r.benefit == null ? '–'
                        : `${r.benefit > 0 ? '+' : ''}${r.benefit}%`}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </div>

      {missed.length > 0 && (
        <div className="card">
          <div className="card-header">
            <span className="card-title">未執行的建議</span>
            <span className="tag" style={{ color: 'var(--dim)' }}>{missed.length} 筆</span>
          </div>
          <div className="muted" style={{ padding: '0 18px 10px', fontSize: '0.6875rem', lineHeight: 1.7 }}>
            系統當天給了明確的買／賣建議，但 3 天內沒有對應的交易紀錄。
            沒動作不代表做錯——本專案的方向訊號至今沒有一個通過走查驗證，
            這份清單的用途是讓「系統說了什麼」不會悄悄消失。
          </div>
          <div className="table-wrap">
            <table className="data-table">
              <thead><tr><th>投票日</th><th>股票</th><th>建議</th></tr></thead>
              <tbody>
                {missed.map((m, i) => (
                  <tr key={i}>
                    <td className="muted">{m.vote_date}</td>
                    <td><strong>{m.stock_id}</strong></td>
                    <td className="muted">{m.recommendation}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </>
  )
}

// ── 主頁面 ────────────────────────────────────────────────────────────────────
export default function Holdings() {
  const [data, setData] = useState({ items: [], summary: null })
  const [trades, setTrades] = useState([])
  const [review, setReview] = useState(null)
  const [stocks, setStocks] = useState([])
  const [loading, setLoading] = useState(true)
  const [editing, setEditing] = useState(null)
  const [showForm, setShowForm] = useState(false)
  const [tab, setTab] = useState('positions')

  async function load() {
    setLoading(true)
    const [h, s, t, v] = await Promise.all([
      getHoldings(), getTrackedStocks(), getTrades(), getDecisionReview(),
    ])
    setData(h.data ?? { items: [], summary: null })
    setStocks(Array.isArray(s.data) ? s.data : (s.data?.items ?? []))
    setTrades(t.data ?? [])
    setReview(v.data ?? null)
    setLoading(false)
  }

  async function handleDeleteTrade(t) {
    if (!window.confirm(
      `刪除 ${t.stock_id} ${t.trade_date} 的${t.side === 'Buy' ? '買進' : '賣出'}紀錄？\n\n`
      + '該股票的所有交易會重新回放，後續每筆的平均成本都會跟著重算。')) return
    await deleteTrade(t.id)
    load()
  }

  useEffect(() => { load() }, [])

  async function handleDelete(row) {
    if (!window.confirm(`刪除 ${row.stock_id} 的持股紀錄？`)) return
    await deleteHolding(row.id)
    load()
  }

  const s = data.summary
  const items = data.items ?? []

  return (
    <>
      <ModelBar page="holdings" />
      <div className="card">
        <div className="card-header">
          <span className="card-title">我的持股</span>
          <span className="tag blue">{items.length} 檔</span>
          {s?.unrealized_pct != null && (
            <span className="tag" style={{
              color: pnlColor(s.unrealized_pnl),
              background: s.unrealized_pnl > 0 ? 'var(--up-soft)' : 'var(--down-soft)',
            }}>
              未實現損益 {s.unrealized_pnl > 0 ? '+' : ''}{money(s.unrealized_pnl)} 元
              （{s.unrealized_pct > 0 ? '+' : ''}{s.unrealized_pct}%）
            </span>
          )}
          <button className={tab === 'positions' ? 'btn-primary' : 'btn-secondary'}
                  style={{ marginLeft: 'auto' }}
                  onClick={() => { setTab('positions'); setShowForm(false); setEditing(null) }}>
            目前持倉
          </button>
          <button className={tab === 'trades' ? 'btn-primary' : 'btn-secondary'}
                  onClick={() => { setTab('trades'); setShowForm(false); setEditing(null) }}>
            交易紀錄 {trades.length > 0 && `(${trades.length})`}
          </button>
          <button className={tab === 'review' ? 'btn-primary' : 'btn-secondary'}
                  onClick={() => { setTab('review'); setShowForm(false); setEditing(null) }}>
            建議對照
          </button>
          {tab !== 'review' && (
            <button className="btn-secondary"
                    onClick={() => { setEditing(null); setShowForm(v => !v) }}>
              {showForm ? '收起' : tab === 'trades' ? '＋ 記錄交易' : '＋ 手動輸入持倉'}
            </button>
          )}
          <button className="btn-secondary" onClick={load}>重新整理</button>
        </div>

        <div style={{ padding: '8px 18px 14px', color: 'var(--dim)', fontSize: '0.75rem', lineHeight: 1.7 }}>
          持股與成本會作為投票決策的條件之一：<strong style={{ color: 'var(--text)' }}>持倉管家</strong>角色
          依浮動損益判斷停損停利與集中度，<strong style={{ color: 'var(--text)' }}>風險控管</strong>角色
          比較「建議部位」與「實際部位」後給出加碼／減碼建議。
          未持有的股票不會出現賣出建議——本系統不做放空。
          <div style={{ marginTop: 4 }}>
            市值與損益以最新收盤價（未還原）計算，對應你實際付出的成本；
            模型評估用的 adj_close 是另一回事，那是算報酬率用的。
          </div>
          <div style={{ marginTop: 4 }}>
            分批進出請用<strong style={{ color: 'var(--text)' }}>交易紀錄</strong>：
            持倉會由台帳以移動平均法自動推導，已實現損益也會一併算出（含手續費與證交稅）。
            只想快速填一個現況、不打算補歷史的話，用「手動輸入持倉」即可——
            但有交易紀錄的股票不能再手動改持倉，否則台帳與持倉會各說各話。
          </div>
        </div>

        {showForm && tab === 'trades' && !editing && (
          <TradeForm stocks={stocks} onDone={load} />
        )}
        {((showForm && tab === 'positions') || editing) && (
          <HoldingForm
            stocks={stocks} editing={editing}
            onDone={() => { setEditing(null); setShowForm(false); load() }}
            onCancel={() => { setEditing(null); setShowForm(false) }}
          />
        )}
      </div>

      {s && items.length > 0 && tab === 'positions' && (
        <div className="card">
          <div style={{ display: 'flex', gap: 28, padding: '14px 18px', flexWrap: 'wrap' }}>
            <Stat label="總成本" value={`${money(s.total_cost)} 元`} />
            <Stat label="目前市值" value={`${money(s.total_value)} 元`} />
            <Stat label="未實現損益"
                  value={`${s.unrealized_pnl > 0 ? '+' : ''}${money(s.unrealized_pnl)} 元`}
                  color={pnlColor(s.unrealized_pnl)} />
            <Stat label="報酬率"
                  value={s.unrealized_pct == null ? '–' : `${s.unrealized_pct > 0 ? '+' : ''}${s.unrealized_pct}%`}
                  color={pnlColor(s.unrealized_pnl)} />
            <Stat label="已實現損益"
                  value={`${s.realized_pnl > 0 ? '+' : ''}${money(s.realized_pnl)} 元`}
                  color={pnlColor(s.realized_pnl)}
                  hint="來自交易台帳的所有賣出，已扣手續費與證交稅；含已全部出清、不在持倉表裡的股票" />
            <Stat label="總損益（已實現＋未實現）"
                  value={`${s.total_pnl > 0 ? '+' : ''}${money(s.total_pnl)} 元`}
                  color={pnlColor(s.total_pnl)} />
            <Stat label="最大單一持股佔比"
                  value={s.max_weight_pct == null ? '–' : `${s.max_weight_pct}%`}
                  color={s.max_weight_pct > 40 ? 'var(--red)' : undefined}
                  hint="超過 40% 時持倉管家角色會示警：單一標的的個別風險無法被分散抵銷" />
          </div>
        </div>
      )}

      {loading && <div className="empty-state"><div className="muted">載入中...</div></div>}

      {!loading && tab === 'trades' && (
        <div className="card">
          <TradeTable trades={trades} onDelete={handleDeleteTrade} />
        </div>
      )}

      {!loading && tab === 'review' && <ReviewPanel review={review} />}

      {!loading && tab === 'positions' && items.length === 0 && (
        <div className="empty-state">
          <div className="empty-icon">💼</div>
          <div>尚未輸入任何持股</div>
          <div className="muted" style={{ fontSize: '0.75rem', marginTop: 6 }}>
            輸入後，投票決策頁會多出「持倉管家」與加碼／減碼建議
          </div>
        </div>
      )}

      {tab === 'positions' && items.length > 0 && (
        <div className="card">
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>股票</th><th>來源</th><th>股數</th><th>每股成本</th><th>最新價</th>
                  <th>成本</th><th>市值</th><th>未實現損益</th><th>報酬率</th>
                  <th>已實現</th><th>備註</th><th>操作</th>
                </tr>
              </thead>
              <tbody>
                {items.map(r => (
                  <tr key={r.id}>
                    <td>
                      <strong>{r.stock_id}</strong>
                      {r.stock_name && (
                        <span className="muted" style={{ marginLeft: 6, fontSize: '0.75rem' }}>{r.stock_name}</span>
                      )}
                    </td>
                    <td>
                      <span title={r.source === 'trades'
                        ? `由 ${r.trade_count} 筆交易紀錄回放推導`
                        : '手動輸入的持倉快照'}
                        style={{
                          padding: '2px 8px', borderRadius: 8, fontSize: '0.6875rem',
                          background: r.source === 'trades' ? 'var(--blue-soft)' : 'var(--dim-soft)',
                          color: r.source === 'trades' ? 'var(--blue)' : 'var(--dim)',
                        }}>
                        {r.source === 'trades' ? `台帳 ${r.trade_count} 筆` : '手動'}
                      </span>
                    </td>
                    <td><Shares value={r.shares} muted /></td>
                    <td className="muted">{r.avg_cost?.toFixed(2)}</td>
                    <td>{r.last_price != null
                      ? <strong>{r.last_price.toFixed(2)}</strong>
                      : <span className="muted" title="此股票無價格資料（非追蹤中）">–</span>}
                    </td>
                    <td className="muted">{money(r.cost_value)}</td>
                    <td className="muted">{money(r.market_value)}</td>
                    <td style={{ color: pnlColor(r.unrealized_pnl), fontWeight: 600 }}>
                      {r.unrealized_pnl == null ? '–'
                        : `${r.unrealized_pnl > 0 ? '+' : ''}${money(r.unrealized_pnl)}`}
                    </td>
                    <td style={{ color: pnlColor(r.unrealized_pnl), fontWeight: 600 }}>
                      {r.unrealized_pct == null ? '–'
                        : `${r.unrealized_pct > 0 ? '+' : ''}${r.unrealized_pct.toFixed(2)}%`}
                    </td>
                    <td style={{ color: pnlColor(r.realized_pnl), fontWeight: 600 }}>
                      {!r.realized_pnl ? '–'
                        : `${r.realized_pnl > 0 ? '+' : ''}${money(r.realized_pnl)}`}
                    </td>
                    <td className="muted" style={{ fontSize: '0.75rem' }}>{r.note ?? ''}</td>
                    <td style={{ whiteSpace: 'nowrap' }}>
                      {r.source === 'trades' ? (
                        <span className="muted" style={{ fontSize: '0.6875rem' }}
                              title="持倉由交易台帳推導，請到「交易紀錄」新增或刪除交易">
                          由台帳管理
                        </span>
                      ) : (
                        <>
                          <button className="btn-chip" onClick={() => { setEditing(r); setShowForm(true) }}>編輯</button>
                          <button className="btn-chip" style={{ color: 'var(--dim)' }}
                                  onClick={() => handleDelete(r)}>刪除</button>
                        </>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </>
  )
}

function Stat({ label, value, color, hint }) {
  return (
    <div title={hint}>
      <div style={{ fontSize: '0.6875rem', color: 'var(--dim)', marginBottom: 4 }}>{label}</div>
      <div style={{ fontSize: '1.125rem', fontWeight: 700, color: color ?? 'var(--text)' }}>{value}</div>
    </div>
  )
}
