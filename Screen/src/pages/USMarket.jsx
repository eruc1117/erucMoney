// 美股開盤跳空頁（Iteration 32）
// ───────────────────────────────────────────────────────────────────────────
// 回答一個問題：「今天亞洲盤這樣走，今晚美股大概開在哪。」
//
// 這一頁的模型與台股跳空模型方向相反。台股那邊是美股 D−1 → 台股 D 開盤；
// 這邊是台股／韓日 D 日盤（美股開盤前 8 小時就收了）→ 美股 D 開盤。
// 走查證實只用美股自身歷史時相關僅 0.0085 ≈ 0，訊號全部來自亞洲時區——
// 所以畫面把「台股資訊取自哪一天」放在最上面，那是這個預測的命脈。
//
// 顏色沿用全站的台股慣例（紅漲綠跌），與美股當地慣例相反，頁面上有註明。
import { useEffect, useState } from 'react'
import { getUsOverview } from '../services/api'
import ModelBar from '../components/ModelBar'

const CATEGORY_LABEL = {
  index: '指數 ETF', semiconductor: '半導體', equipment: '半導體設備',
  tw_adr: '台股 ADR', tw_etf: '台股 ETF', bigtech: '大型科技',
}

function pct(v, digits = 2) {
  if (v === null || v === undefined || Number.isNaN(Number(v))) return '–'
  const n = Number(v)
  return `${n > 0 ? '+' : ''}${n.toFixed(digits)}%`
}

function toneClass(v) {
  if (v === null || v === undefined || Number.isNaN(Number(v))) return 'muted'
  return Number(v) > 0 ? 'up' : Number(v) < 0 ? 'down' : 'muted'
}

export default function USMarket() {
  const [data, setData]       = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError]     = useState('')
  const [days, setDays]       = useState(60)

  function load(d = days) {
    setLoading(true)
    getUsOverview(d).then(({ data: res, error: e }) => {
      if (e) setError(e)
      else { setData(res); setError('') }
      setLoading(false)
    })
  }

  useEffect(() => { load(days) }, [days])

  const snap  = data?.snapshot
  const pred  = data?.prediction
  const items = snap?.items || []
  const stale = (data?.freshness?.items || []).filter(i => i.stale)

  const ups   = items.filter(i => i.gap_prediction?.gap_pct > 0).length
  const downs = items.filter(i => i.gap_prediction?.gap_pct < 0).length

  // 說明段落用的「最準／最差」直接取自各檔的走查成績，不寫死數字——
  // 清單或模型一換，寫死的數字就是錯的（EWT 是套套邏輯，不列入）
  const ranked = items
    .filter(i => i.gap_prediction?.walk_forward && i.category !== 'tw_etf')
    .map(i => ({ ticker: i.ticker, corr: i.gap_prediction.walk_forward.corr }))
    .sort((a, b) => b.corr - a.corr)
  const best  = ranked.slice(0, 2)
  const worst = ranked.slice(-2).reverse()

  return (
    <>
      <ModelBar page="us" />

      {/* 資料落後時要講出來——模型照樣會輸出預測，不講就看不出用的是舊資料 */}
      {stale.length > 0 && (
        <div className="card" style={{ borderColor: 'var(--orange)' }}>
          <div className="card-body">
            ⚠ 資料落後：{stale.map(s => `${s.label}（最新 ${s.last_date}，落後 ${s.days_behind} 天）`).join('、')}。
            <span className="muted"> 排程每日 06:10 與 19:10 會自動更新；持續落後代表排程沒在跑。</span>
          </div>
        </div>
      )}

      <div className="cards-grid">
        <div className="metric-card">
          <div className="metric-label">預測這一場</div>
          <div className="metric-value">{pred?.target_session || '–'}</div>
          <div className="metric-delta muted">
            上一場收盤 {pred?.base_date || snap?.as_of || '–'}
          </div>
        </div>
        <div className="metric-card">
          <div className="metric-label">台股資訊取自</div>
          <div className="metric-value">{pred?.tw_session || '–'}</div>
          <div className="metric-delta muted">訊號來源；落後一天代表台股尚未收盤或沒抓到</div>
        </div>
        <div className="metric-card">
          <div className="metric-label">預測開高 / 開低</div>
          <div className="metric-value">
            <span className="up">{ups}</span>
            <span className="muted"> / </span>
            <span className="down">{downs}</span>
          </div>
          <div className="metric-delta muted">共 {items.length} 檔</div>
        </div>
        <div className="metric-card">
          <div className="metric-label">走查方向準確率</div>
          <div className="metric-value">61.32%</div>
          <div className="metric-delta muted">多數類別基準 55.33%（Iteration 32）</div>
        </div>
      </div>

      <div className="card">
        <div className="card-header">
          <span className="card-title">
            美股標的與下一場開盤跳空預測
            {pred?.version ? <span className="muted"> · 模型 v{pred.version}</span> : null}
          </span>
          <div style={{ display: 'flex', gap: 6 }}>
            {[20, 60, 120].map(d => (
              <button key={d} className={`btn-chip${days === d ? ' active' : ''}`}
                      onClick={() => setDays(d)}>{d} 日</button>
            ))}
            <button className="btn-chip" onClick={() => load()}>重新整理</button>
          </div>
        </div>

        {loading && <div className="card-body muted">載入中…</div>}
        {error && <div className="card-body" style={{ color: 'var(--orange)' }}>{error}</div>}

        {!loading && !error && (
          <div style={{ overflowX: 'auto' }}>
            <table className="data-table">
              <thead>
                <tr>
                  <th>標的</th>
                  <th>類別</th>
                  <th style={{ textAlign: 'right' }}>收盤</th>
                  <th style={{ textAlign: 'right' }}>當日</th>
                  <th style={{ textAlign: 'right' }}>{days} 日</th>
                  <th style={{ textAlign: 'right' }}>預測跳空</th>
                  <th style={{ textAlign: 'right' }}>隱含開盤</th>
                  <th style={{ textAlign: 'right' }}>這一檔的走查成績</th>
                </tr>
              </thead>
              <tbody>
                {items.map(it => {
                  const g = it.gap_prediction
                  const wf = g?.walk_forward
                  return (
                    <tr key={it.ticker}>
                      <td>
                        <strong>{it.ticker}</strong>
                        <div className="muted" style={{ fontSize: '0.75rem' }}>{it.name}</div>
                      </td>
                      <td className="muted">{CATEGORY_LABEL[it.category] || it.category || '–'}</td>
                      <td style={{ textAlign: 'right' }}>{it.close?.toFixed(2)}</td>
                      <td style={{ textAlign: 'right' }} className={toneClass(it.change_pct)}>
                        {pct(it.change_pct)}
                      </td>
                      <td style={{ textAlign: 'right' }} className={toneClass(it.period_pct)}>
                        {pct(it.period_pct)}
                      </td>
                      <td style={{ textAlign: 'right' }} className={toneClass(g?.gap_pct)}>
                        {g ? pct(g.gap_pct, 2) : '–'}
                        {g?.magnitude === '偏大' && (
                          <span className="muted" style={{ fontSize: '0.7rem' }}> 幅度偏大</span>
                        )}
                      </td>
                      <td style={{ textAlign: 'right' }} className="muted">
                        {g?.implied_open ?? '–'}
                      </td>
                      <td style={{ textAlign: 'right', fontSize: '0.75rem' }}>
                        {wf ? (
                          <span title="走查（擴張視窗）分標的成績">
                            方向 <span className={wf.dir_acc > wf.dir_base ? 'up' : 'muted'}>
                              {wf.dir_acc}%
                            </span>
                            <span className="muted"> / 多數類別 {wf.dir_base}%　相關 {wf.corr}</span>
                          </span>
                        ) : <span className="muted">–</span>}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}

        {!loading && pred && !pred.available && (
          <div className="card-body muted">跳空預測不可用：{pred.reason}</div>
        )}
      </div>

      <div className="card">
        <div className="card-header"><span className="card-title">這個預測是什麼、不是什麼</span></div>
        <div className="card-body" style={{ lineHeight: 1.8 }}>
          <p>
            <strong>訊號來源是亞洲時區，不是美股自己。</strong> 台股 13:30、韓日 14:30 收盤，
            都在美股 09:30 ET 開盤之前 8 小時。走查消融顯示：只用美股自身歷史時相關 0.0085
            （等於沒有），加入台股後 0.2375，再加韓日 0.2781。
          </p>
          <p>
            <strong>能預測的部分不能交易。</strong> 跳空發生在開盤那一瞬間，事後買不到。
            而開盤之後那一段（收盤 ÷ 開盤）走查相關僅 0.02、方向 49.4%，
            <span className="muted"> 低於多數類別 51.45%</span>——所以本頁不出買賣訊號，
            也不進投票計分，用途是盤前心理準備與掛單價位。
          </p>
          <p>
            <strong>幅度不要當真。</strong> 模型 MAE 只比直接猜 0 好一點點（走查 1.078% 對 1.113%）——
            量級幾乎沒有改善，模型抓到的是方向與排序。「開高還是開低、幅度算不算大」可以參考，
            「開高 1.2%」不要當成可下單的數字。
          </p>
          <p>
            <strong>{items.length || 23} 檔的準確度差很多。</strong>
            {best.length > 0 && <> 走查最準的是 {best.map(b => `${b.ticker}（${b.corr}）`).join('、')}，</>}
            {worst.length > 0 && <>最差的是 {worst.map(b => `${b.ticker}（${b.corr}）`).join('、')}</>}
            ——與台股連動越深的標的越準，這個排序本身就是訊號真實存在的旁證。
            每一列右側都標了該檔自己的成績。清單在 Iteration 34 以巢狀走查重新檢討過：
            新增半導體設備（ASML／AMAT／LRCX／KLAC）、台灣公司 ADR（ASX／HIMX／SIMO）等 11 檔，
            原 12 檔全數過門檻留任。
          </p>
          <p>
            <strong>EWT 不算數。</strong> 它本身就是台股（iShares MSCI Taiwan），只是在美國時區交易——
            用台股當日盤預測它的開盤跳空近乎套套邏輯。留著是因為「台股 ETF 今晚在美國會怎麼開」有用，
            但它的高分不代表模型能預測美股。
          </p>
          <p className="muted">
            另外：美股波動率模型在同一批走查被否決（QLIKE 輸給 EWMA 基準），所以這一頁沒有風險欄位。
            漲跌顏色沿用全站的台股慣例（紅漲綠跌），與美股當地慣例相反。
          </p>
        </div>
      </div>
    </>
  )
}
