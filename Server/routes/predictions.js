/**
 * 預測儲存 & 比對路由
 *
 * POST   /predictions              儲存一筆預測結果（同時登錄模型版本、寫入預測台帳）
 * GET    /predictions              取得所有已儲存預測（可篩選、排序）
 * GET    /predictions/summary      依模型彙總線上表現
 * DELETE /predictions/:id          刪除一筆
 * GET    /predictions/:id/compare  取得預測 + 實際值比對（含方向準確率與天真基準）
 *
 * ## 兩個 Iteration 21 的重要修正
 *
 * 1. **改用 adj_close 比對。** 原本直接拿 `close_price` 當實際值，
 *    除權息與減資造成的機械性缺口會被算成模型預測失準
 *    （Iteration 18：旺宏 2017-08-28 原始資料是單日 +123.56%）。
 *    現在一律把實際價換算到「預測基準日的價格尺度」：
 *
 *        實際值 = 基準日收盤 × adj_close(當日) ÷ adj_close(基準日)
 *
 *    如此 predicted 與 actual 同尺度可比，公司行動不進誤差。
 *
 * 2. **加上方向準確率與天真基準。** 只看 MAE／MAPE 幾乎測不出模型好壞——
 *    「明日＝今日」的 MAE 本來就很低（Iteration 11 實測 LSTM 的 MAE 5.17~5.25，
 *    天真基準 5.20）。沒有基準對照的準確率數字，看起來再漂亮都不代表有 edge。
 *
 * ## 交易日以真實日曆為準（Iteration 33）
 *
 * 前端存下的預測日期是「跳過週末」推估的，國定假日不在裡面。原本比對用
 * 日期精確匹配：假日那一列永遠不到期，之後每一列都錯位一天——第 3 步的
 * 預測被拿去比第 2 個交易日的收盤。
 *
 * 現在改成與 resolve_predictions.py 同一個定位法：**第 i 筆預測 ＝ 基準日之後
 * 第 i 個真實交易日**。到期的列 `date` 改為真實交易日（保留 `planned_date`），
 * 未到期的列從最後一個真實交易日起再跳週末往後估。不需要維護假日表——
 * 資料庫裡有哪一天，哪一天就是交易日。
 *
 * ## 美股（market = 'us'）
 *
 * 同一張 saved_predictions 也收美股的 LSTM 預測。差別只在實際值去哪張表取：
 * 台股查 stock_daily_prices（stock_id），美股查 us_daily_prices（ticker）。
 * 台帳的 target_kind 也分開（close / us_close），回填端才知道要查哪張表；
 * 模型類型也分開（lstm:m02 / lstm_us:m02），否則台幣與美元的 MAE 會混在同一個
 * 版本的線上指標裡。
 */
const { Router } = require('express')
const db = require('../db')

const router = Router()

// 兩個市場的價格表：欄位語意相同，只有表名與代號欄不同
const MARKETS = {
  tw: { table: 'stock_daily_prices', idCol: 'stock_id', kind: 'close',    typePrefix: 'lstm' },
  us: { table: 'us_daily_prices',    idCol: 'ticker',   kind: 'us_close', typePrefix: 'lstm_us' },
}
const marketOf = (v) => (String(v ?? 'tw').toLowerCase() === 'us' ? 'us' : 'tw')

// ── 取得（必要時建立）該 LSTM 模型的 candidate 版本 ──────────────────────────
// 前端存下的預測要能追溯到「是哪一版模型算的」，否則版本管理頁上的線上實測
// 指標就只涵蓋 Python 端的模型，看不到使用者真正在比對的 LSTM。
async function ensureLstmVersion(modelKey, market = 'tw') {
  const mk = MARKETS[market]
  const modelType = `${mk.typePrefix}:${modelKey}`
  const existing = await db.query(
    `SELECT id FROM model_versions
      WHERE model_type = $1 AND (is_serving OR status = 'candidate')
      ORDER BY is_serving DESC LIMIT 1`, [modelType])
  if (existing.rowCount > 0) return existing.rows[0].id

  const artifact = require('path').join(__dirname, '..', '..', 'LSTM', 'saved_models', modelKey)
  // $1 同時出現在 VALUES 與子查詢的 WHERE，pg 會回「inconsistent types deduced
  // for parameter $1」——要明確轉型。美股類型是第一個走到這裡才建立的版本，
  // 台股的 lstm:* 版本早就由 Python 端登錄過，所以這個錯一直沒浮現。
  const { rows } = await db.query(
    `INSERT INTO model_versions
       (model_type, version, status, artifact_path, target_kind, horizon_days)
     VALUES ($1::varchar,
             (SELECT COALESCE(MAX(version), 0) + 1 FROM model_versions
               WHERE model_type = $1::varchar),
             'candidate', $2, $3, 7)
     ON CONFLICT (model_type, version) DO NOTHING
     RETURNING id`, [modelType, artifact, mk.kind])
  return rows[0]?.id ?? null
}

// 找出預測的基準日：第一個預測日之前最後一個有價格的交易日
async function findBase(stockId, firstDate, market = 'tw') {
  const mk = MARKETS[market]
  const { rows } = await db.query(
    `SELECT trade_date::text AS date, close_price, adj_close
       FROM ${mk.table}
      WHERE ${mk.idCol} = $1 AND trade_date < $2 AND close_price > 0
      ORDER BY trade_date DESC LIMIT 1`, [stockId, firstDate])
  if (rows.length === 0) return null
  const r = rows[0]
  return {
    date: r.date,
    close: parseFloat(r.close_price),
    adj: r.adj_close != null ? parseFloat(r.adj_close) : parseFloat(r.close_price),
  }
}

// ── 儲存預測 ──────────────────────────────────────────────────────────────────
router.post('/', async (req, res) => {
  const { model_key, model_label, predictions } = req.body
  const market = marketOf(req.body.market)
  // 美股代號一律大寫：'tsm' 與 'TSM' 在 us_daily_prices 是兩個不同的鍵
  const stock_id = market === 'us'
    ? String(req.body.stock_id ?? '').trim().toUpperCase()
    : String(req.body.stock_id ?? '').trim()
  if (!stock_id || !model_key || !Array.isArray(predictions) || predictions.length === 0)
    return res.status(400).json({ detail: 'stock_id、model_key、predictions 為必填' })

  try {
    let versionId = null
    try {
      versionId = await ensureLstmVersion(model_key, market)
    } catch (e) {
      // 登錄失敗不該擋下使用者存預測——那是附帶效果，不是主要目的
      console.warn('[POST /predictions] 模型版本登錄略過：', e.message)
    }

    const { rows } = await db.query(
      `INSERT INTO saved_predictions
         (stock_id, model_key, model_label, predictions, model_version_id, market)
       VALUES ($1, $2, $3, $4, $5, $6) RETURNING id, saved_at, market`,
      [stock_id, model_key, model_label ?? model_key,
       JSON.stringify(predictions), versionId, market]
    )

    // 同步寫入預測台帳：讓這筆預測進入模型的線上實測成績
    if (versionId) {
      try {
        const base = await findBase(stock_id, predictions[0].date, market)
        const values = predictions.map((p, i) => [
          versionId, stock_id, MARKETS[market].kind, base?.date ?? predictions[0].date,
          p.date, i + 1, base?.close ?? null,
          p.predicted_close, base?.close ?? null,   // 天真基準：明日＝今日
          p.ci_low ?? null, p.ci_high ?? null,
        ])
        const ph = values.map((_, i) => {
          const o = i * 11
          return `($${o + 1},$${o + 2},$${o + 3},$${o + 4},$${o + 5},$${o + 6},$${o + 7},$${o + 8},$${o + 9},$${o + 10},$${o + 11})`
        }).join(',')
        await db.query(
          `INSERT INTO model_predictions
             (model_version_id, stock_id, target_kind, predicted_on, target_date,
              horizon_days, ref_value, predicted_value, baseline_value, ci_low, ci_high)
           VALUES ${ph}
           ON CONFLICT (model_version_id, stock_id, target_kind, predicted_on, horizon_days)
           DO UPDATE SET predicted_value = EXCLUDED.predicted_value,
                         target_date     = EXCLUDED.target_date,
                         baseline_value  = EXCLUDED.baseline_value,
                         ci_low = EXCLUDED.ci_low, ci_high = EXCLUDED.ci_high`,
          values.flat())
      } catch (e) {
        console.warn('[POST /predictions] 台帳寫入略過：', e.message)
      }
    }

    res.status(201).json({ ...rows[0], model_version_id: versionId })
  } catch (e) {
    console.error('[POST /predictions]', e.message)
    res.status(500).json({ detail: e.message })
  }
})

// ── 取得所有已儲存預測 ─────────────────────────────────────────────────────────
// 支援 ?stock_id= &model_key= &status=matured|pending &sort=saved|stock|model &market=tw|us
// 不帶 market 時回全部（舊前端相容）；帶了就只回該市場。
router.get('/', async (req, res) => {
  const { stock_id, model_key, status, sort, market } = req.query
  const where = []
  const params = []
  if (stock_id) { params.push(stock_id);  where.push(`sp.stock_id = $${params.length}`) }
  if (model_key) { params.push(model_key); where.push(`sp.model_key = $${params.length}`) }
  if (market)    { params.push(marketOf(market)); where.push(`sp.market = $${params.length}`) }

  const orderBy = sort === 'stock' ? 'sp.stock_id, sp.saved_at DESC'
    : sort === 'model' ? 'sp.model_key, sp.saved_at DESC'
    : 'sp.saved_at DESC'

  try {
    const { rows } = await db.query(`
      SELECT sp.id, sp.stock_id, sp.market, sp.model_key, sp.model_label, sp.saved_at,
             sp.model_version_id,
             mv.version AS model_version, mv.status AS model_status, mv.is_serving,
             COALESCE(si.stock_name, ut.name) AS stock_name,
             sp.predictions->0->>'date'         AS first_date,
             sp.predictions->-1->>'date'        AS last_date,
             jsonb_array_length(sp.predictions) AS days,
             -- 到期天數：第一個預測日起有幾個真實交易日（上限為預測筆數）。
             -- 不用日期精確匹配——推估的日期落在假日時會永遠不到期，之後全部錯位。
             -- 兩個子查詢依市場互斥，不會同時計數。
             LEAST(jsonb_array_length(sp.predictions),
               (SELECT COUNT(*) FROM stock_daily_prices p
                 WHERE sp.market = 'tw' AND p.stock_id = sp.stock_id
                   AND p.trade_date >= (sp.predictions->0->>'date')::date)
               + (SELECT COUNT(*) FROM us_daily_prices u
                   WHERE sp.market = 'us' AND u.ticker = sp.stock_id
                     AND u.trade_date >= (sp.predictions->0->>'date')::date)) AS matured_days
        FROM saved_predictions sp
        LEFT JOIN model_versions mv ON mv.id = sp.model_version_id
        LEFT JOIN stock_info si     ON si.stock_id = sp.stock_id AND sp.market = 'tw'
        LEFT JOIN us_tickers ut     ON ut.ticker   = sp.stock_id AND sp.market = 'us'
       ${where.length ? 'WHERE ' + where.join(' AND ') : ''}
       ORDER BY ${orderBy}
    `, params)

    const filtered = status === 'matured' ? rows.filter(r => Number(r.matured_days) > 0)
      : status === 'pending' ? rows.filter(r => Number(r.matured_days) === 0)
      : rows
    res.json(filtered)
  } catch (e) {
    console.error('[GET /predictions]', e.message)
    res.status(500).json({ detail: e.message })
  }
})

// ── 依模型彙總 ────────────────────────────────────────────────────────────────
// 把所有已儲存預測攤平成逐日樣本，算出每個模型的方向準確率與天真基準對照。
// ?market=tw|us 只彙總該市場；台幣與美元的 MAE 不能混在同一列
router.get('/summary', async (req, res) => {
  try {
    const params = req.query.market ? [marketOf(req.query.market)] : []
    const { rows } = await db.query(
      `SELECT id, stock_id, market, model_key, model_label, predictions
         FROM saved_predictions${params.length ? ' WHERE market = $1' : ''}`, params)
    const byModel = new Map()

    for (const rec of rows) {
      const cmp = await compareRecord(rec)
      if (!cmp || !cmp.metrics) continue
      const key = rec.model_key
      if (!byModel.has(key)) {
        byModel.set(key, {
          model_key: key, model_label: rec.model_label, records: 0,
          days: 0, absErr: 0, baseAbsErr: 0, dirN: 0, dirHit: 0, up: 0,
          ciN: 0, ciHit: 0,
        })
      }
      const a = byModel.get(key)
      a.records += 1
      for (const r of cmp.rows) {
        if (r.actual_close == null) continue
        a.days += 1
        a.absErr += Math.abs(r.error)
        if (r.baseline_error != null) a.baseAbsErr += Math.abs(r.baseline_error)
        if (r.pred_dir !== 0 && r.actual_dir !== 0) {
          a.dirN += 1
          if (r.pred_dir === r.actual_dir) a.dirHit += 1
          if (r.actual_dir > 0) a.up += 1
        }
        if (r.in_ci != null) { a.ciN += 1; if (r.in_ci) a.ciHit += 1 }
      }
    }

    const out = [...byModel.values()].map(a => {
      // 天真的方向基準是「多數類別」（一律猜漲能拿幾分），
      // 不是「明日＝今日」——後者預測變動為零，根本沒有方向可言。
      const baseDir = a.dirN > 0 ? Math.max(a.up, a.dirN - a.up) / a.dirN : null
      const dirAcc = a.dirN > 0 ? a.dirHit / a.dirN : null
      return {
        model_key: a.model_key, model_label: a.model_label,
        records: a.records, matured_days: a.days,
        mae: a.days ? +(a.absErr / a.days).toFixed(3) : null,
        baseline_mae: a.days ? +(a.baseAbsErr / a.days).toFixed(3) : null,
        direction_n: a.dirN,
        direction_acc: dirAcc != null ? +(dirAcc * 100).toFixed(1) : null,
        baseline_direction_acc: baseDir != null ? +(baseDir * 100).toFixed(1) : null,
        margin: (dirAcc != null && baseDir != null)
          ? +((dirAcc - baseDir) * 100).toFixed(1) : null,
        ci_hit_rate: a.ciN ? +(a.ciHit / a.ciN * 100).toFixed(1) : null,
      }
    }).sort((x, y) => (y.margin ?? -99) - (x.margin ?? -99))

    res.json(out)
  } catch (e) {
    console.error('[GET /predictions/summary]', e.message)
    res.status(500).json({ detail: e.message })
  }
})

// ── 刪除 ──────────────────────────────────────────────────────────────────────
router.delete('/:id', async (req, res) => {
  try {
    const { rowCount } = await db.query(
      'DELETE FROM saved_predictions WHERE id = $1', [req.params.id]
    )
    if (rowCount === 0) return res.status(404).json({ detail: '找不到此筆記錄' })
    res.json({ ok: true })
  } catch (e) {
    console.error('[DELETE /predictions/:id]', e.message)
    res.status(500).json({ detail: e.message })
  }
})

// ── 比對核心 ──────────────────────────────────────────────────────────────────
async function compareRecord(record) {
  const predictions = record.predictions
  if (!Array.isArray(predictions) || predictions.length === 0) return null
  const dates = predictions.map(p => p.date)
  const market = marketOf(record.market)
  const mk = MARKETS[market]

  const base = await findBase(record.stock_id, dates[0], market)
  // 基準日之後的真實交易日，依序對上第 1、2、… 筆預測（不做日期精確匹配，見檔頭）
  const { rows: priceRows } = await db.query(
    `SELECT trade_date::text AS date, close_price, adj_close
       FROM ${mk.table}
      WHERE ${mk.idCol} = $1 AND trade_date >= $2::date AND close_price > 0
      ORDER BY trade_date
      LIMIT $3`,
    [record.stock_id, dates[0], predictions.length])

  const actuals = priceRows.map(r => ({
    date: r.date,
    close: parseFloat(r.close_price),
    adj: r.adj_close != null ? parseFloat(r.adj_close) : parseFloat(r.close_price),
  }))

  // 未到期的列：從最後一個真實交易日（或最後一筆推估日）起跳週末往後估
  const nextWeekday = (iso) => {
    const d = new Date(`${iso}T00:00:00Z`)
    do { d.setUTCDate(d.getUTCDate() + 1) } while (d.getUTCDay() === 0 || d.getUTCDay() === 6)
    return d.toISOString().slice(0, 10)
  }
  let cursor = actuals.length ? actuals[actuals.length - 1].date : null

  const compared = predictions.map((p, i) => {
    const px = actuals[i]
    if (!px || !base) {
      // 推估日期只在「前面有真實交易日」時往後推；完全沒到期的紀錄維持原推估
      const est = cursor ? nextWeekday(cursor) : p.date
      if (cursor) cursor = est
      return { ...p, planned_date: p.date, date: est,
               actual_close: null, error: null, error_pct: null,
               in_ci: null, baseline_close: base?.close ?? null,
               baseline_error: null, pred_dir: 0, actual_dir: 0 }
    }
    // 還原公司行動後、換算到「預測基準日價格尺度」的實際收盤
    const actual = +(base.close * px.adj / base.adj).toFixed(2)
    const error = +(actual - p.predicted_close).toFixed(2)
    const errorPct = +((Math.abs(actual - p.predicted_close) / actual) * 100).toFixed(2)
    const inCI = (p.ci_low != null && p.ci_high != null)
      ? (actual >= p.ci_low && actual <= p.ci_high) : null
    return {
      ...p,
      planned_date: p.date,                      // 存檔時推估的日期（跳週末）
      date: px.date,                             // 真實交易日：基準日之後第 i 個
      actual_close: actual,
      raw_close: px.close,                       // 未還原的原始收盤，供對照
      error, error_pct: errorPct, in_ci: inCI,
      baseline_close: base.close,                // 天真基準：明日＝今日
      baseline_error: +(actual - base.close).toFixed(2),
      pred_dir: Math.sign(+(p.predicted_close - base.close).toFixed(4)),
      actual_dir: Math.sign(+(actual - base.close).toFixed(4)),
    }
  })

  const filled = compared.filter(r => r.actual_close != null)
  let metrics = null
  if (filled.length > 0) {
    const mae = +(filled.reduce((s, r) => s + Math.abs(r.error), 0) / filled.length).toFixed(2)
    const mape = +(filled.reduce((s, r) => s + r.error_pct, 0) / filled.length).toFixed(2)
    const baseMae = +(filled.reduce((s, r) => s + Math.abs(r.baseline_error), 0) / filled.length).toFixed(2)
    const ciRows = filled.filter(r => r.in_ci != null)
    const hitRate = ciRows.length
      ? +(ciRows.filter(r => r.in_ci).length / ciRows.length * 100).toFixed(1) : null

    const dirRows = filled.filter(r => r.pred_dir !== 0 && r.actual_dir !== 0)
    const dirHit = dirRows.filter(r => r.pred_dir === r.actual_dir).length
    const up = dirRows.filter(r => r.actual_dir > 0).length
    const dirAcc = dirRows.length ? +(dirHit / dirRows.length * 100).toFixed(1) : null
    const baseDir = dirRows.length
      ? +(Math.max(up, dirRows.length - up) / dirRows.length * 100).toFixed(1) : null

    metrics = {
      mae, mape, baseline_mae: baseMae,
      beats_baseline_mae: mae < baseMae,
      hit_rate: hitRate,
      direction_n: dirRows.length,
      direction_acc: dirAcc,
      baseline_direction_acc: baseDir,
      margin: (dirAcc != null && baseDir != null) ? +(dirAcc - baseDir).toFixed(1) : null,
      filled_days: filled.length, total_days: compared.length,
      base_date: base?.date ?? null, base_close: base?.close ?? null,
    }
  }
  return { rows: compared, metrics, base }
}

// ── 取得預測 + 實際收盤價比對 ──────────────────────────────────────────────────
router.get('/:id/compare', async (req, res) => {
  try {
    const { rows } = await db.query(
      `SELECT sp.*, mv.version AS model_version, mv.status AS model_status,
              mv.is_serving
         FROM saved_predictions sp
         LEFT JOIN model_versions mv ON mv.id = sp.model_version_id
        WHERE sp.id = $1`, [req.params.id])
    if (rows.length === 0) return res.status(404).json({ detail: '找不到此筆記錄' })

    const record = rows[0]
    const cmp = await compareRecord(record)
    if (!cmp) return res.status(400).json({ detail: '此筆記錄沒有預測內容' })

    res.json({
      id: record.id,
      stock_id: record.stock_id,
      market: marketOf(record.market),
      model_key: record.model_key,
      model_label: record.model_label,
      model_version: record.model_version,
      model_status: record.model_status,
      is_serving: record.is_serving,
      saved_at: record.saved_at,
      metrics: cmp.metrics,
      rows: cmp.rows,
      note: ('實際收盤已還原除權息與減資，並換算到預測基準日的價格尺度，'
             + '故與預測值同尺度可比；「天真基準」為「明日＝今日」，'
             + '方向側的基準則為多數類別（一律猜漲能拿幾分）。'
             + '第 i 筆預測對應基準日之後第 i 個真實交易日，'
             + '存檔時推估的日期若遇休市會往後順延（明細表有標）。'
             + (marketOf(record.market) === 'us'
                ? '　美股的日期為美東場次日期；實際值來自 us_daily_prices（每日 06:10 更新）。'
                : '')),
    })
  } catch (e) {
    console.error('[GET /predictions/:id/compare]', e.message)
    res.status(500).json({ detail: e.message })
  }
})

module.exports = router
